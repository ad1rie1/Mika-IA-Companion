"""Les requêtes d'une app de la Forge, telles que l'hôte les envoie pour elle.

**Son réseau est libre** (ADR 0105) : une app n'a pas de réseau, elle demande ses requêtes à l'hôte
(``api.http``, ``api.http_get``), qui les fait partir d'ici — tout Internet, toute méthode, ses en-têtes, un corps,
les redirections suivies et chacune revérifiée ; jamais cette machine ni le réseau local : chaque nom est résolu une
fois et jugé par la règle d'``adapters/addresses.py`` (ADR 0228). Ce module porte ce qu'une requête peut demander
(en-têtes, corps, méthodes), ce qu'elle envoie et lit au plus, ses délais et ses redirections ; l'hôte
(``ForgeHost._http``, ``forge/__init__.py``) compte les requêtes d'un appel, note celles qui échouent et rend la
réponse à l'app.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import httpx

from mika.adapters.addresses import resolve_public

#: une réponse lue au plus (octets) : au-delà, elle est coupée et l'app le sait (``truncated``)
HTTP_MAX = 5_000_000


def shown_url(url: str) -> str:
    """Une adresse telle qu'une erreur ou le journal la montrent : schéma, hôte et chemin — sans sa requête ni son
    fragment, où une app met souvent sa clé (``?apikey=…``) : un secret n'en sort jamais (ADR 0161)."""
    parts = urlsplit(url)
    bare = f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}{parts.path}" if parts.netloc else url.split("?", 1)[0]
    return (bare + ("?…" if parts.query or parts.fragment else ""))[:200]
#: une requête de l'app dure au plus ça quand elle ne dit rien (``timeout``), jamais plus que ce qui reste à son appel
HTTP_TIMEOUT_S = 15.0
#: …ni plus que ça, même si elle le demande
HTTP_TIMEOUT_MAX_S = 120.0
#: les en-têtes que l'hôte pose lui-même (la connexion, la taille, la machine visée) : une app choisit tous les autres
#: (ADR 0105 — son réseau est libre : une clé, un cookie, une langue, son nom de client…)
HTTP_RESERVED = frozenset({"host", "content-length", "transfer-encoding", "connection", "keep-alive", "upgrade", "te",
                           "trailer", "expect", "proxy-authorization", "proxy-connection"})
HTTP_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
HTTP_HEADERS_MAX = 40
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
#: ce qu'une requête envoie au plus (octets)
HTTP_BODY_MAX = 1_000_000
#: les redirections suivies au plus, chacune revérifiée (jamais vers cette machine ni le réseau local)
HTTP_REDIRECTS = 5
#: son nom de client quand elle n'en donne pas
USER_AGENT = "Mika-Forge/3"


def checked_headers(raw: Any) -> dict[str, str]:
    """Les en-têtes demandés, vérifiés (``ValueError`` en français sinon) : des noms d'en-tête, hors de ceux que
    l'hôte pose, des valeurs d'une ligne."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("headers : un dictionnaire {nom: valeur}")
    if len(raw) > HTTP_HEADERS_MAX:
        raise ValueError(f"headers : {HTTP_HEADERS_MAX} en-têtes au plus")
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not HTTP_HEADER_NAME.match(name):
            raise ValueError(f"en-tête « {name[:40]} » : un nom d'en-tête (lettres, chiffres, tirets)")
        if name.lower() in HTTP_RESERVED:
            raise ValueError(f"en-tête « {name} » : l'hôte le pose lui-même")
        text = str(value)
        if len(text) > 8000 or "\r" in text or "\n" in text:
            raise ValueError(f"en-tête « {name} » : une valeur d'une ligne, 8 000 caractères au plus")
        out[name] = text
    return out


def body_of(json_: Any = None, form: Any = None, body: Any = None) -> tuple[bytes | None, str]:
    """(ce qu'une requête envoie, son type) : du JSON, un formulaire, ou un texte tel quel — un seul des trois."""
    given = [x is not None for x in (json_, form, body)]
    if sum(given) > 1:
        raise ValueError("un seul corps : json, form ou body")
    if json_ is not None:
        data, kind = json.dumps(json_, ensure_ascii=False).encode(), "application/json"
    elif form is not None:
        if not isinstance(form, Mapping):
            raise ValueError("form : un dictionnaire {champ: valeur}")
        data, kind = urlencode({str(k): str(v) for k, v in form.items()}).encode(), \
            "application/x-www-form-urlencoded"
    elif body is not None:
        data, kind = str(body).encode(), ""
    else:
        return None, ""
    if len(data) > HTTP_BODY_MAX:
        raise ValueError(f"corps trop gros ({len(data) // 1000} Ko ; au plus {HTTP_BODY_MAX // 1000} Ko)")
    return data, kind


def has_header(headers: Mapping[str, str], name: str) -> bool:
    return any(k.lower() == name for k in headers)


def real_http(method: str, url: str, *, headers: Mapping[str, str] | None = None, body: bytes | None = None,
              deadline: float | None = None, timeout_s: float | None = None,
              max_bytes: int = HTTP_MAX) -> dict[str, Any]:
    """Une requête vers une adresse **publique** (ADR 0105 : tout Internet, jamais cette machine ni le réseau
    local) : chaque nom est résolu une seule fois, la connexion part vers l'adresse vérifiée (le nom ne sert qu'à
    l'en-tête ``Host`` et au certificat), les redirections sont suivies — chacune revérifiée, sans la clé ni les
    cookies quand l'hôte change —, la réponse est lue jusqu'à ``max_bytes`` (``truncated`` le dit) et la durée totale
    bornée (``deadline`` sur ``time.monotonic``, ``timeout_s`` pour cette requête).

    Rend ``{status, url, headers, body (octets), truncated}`` — une erreur HTTP est une réponse, pas une exception."""
    method = method.upper()
    if method not in HTTP_METHODS:
        raise ValueError(f"méthode « {method[:10]} » inconnue (au choix : {', '.join(sorted(HTTP_METHODS))})")
    end = time.monotonic() + min(timeout_s or HTTP_TIMEOUT_S, HTTP_TIMEOUT_MAX_S)
    if deadline is not None:
        end = min(end, deadline)

    def left() -> float:
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("délai dépassé")
        return remaining

    sent = dict(headers or {})
    for _hop in range(HTTP_REDIRECTS + 1):
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme not in ("http", "https") or not host:
            raise ValueError("une adresse http(s) complète")
        if parts.username or parts.password:
            raise ValueError("pas d'identifiants dans l'adresse (un en-tête Authorization)")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ip = resolve_public(host, port)[0]
        netloc = f"[{ip}]:{port}" if ip.version == 6 else f"{ip}:{port}"
        target = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
        out = {**({} if has_header(sent, "user-agent") else {"User-Agent": USER_AGENT}), **sent,
               "Host": host if parts.port is None else f"{host}:{parts.port}"}
        extra = {"content": body} if body is not None else {}
        with httpx.Client(follow_redirects=False, timeout=left(), trust_env=False) as client, \
                client.stream(method, target, headers=out, extensions={"sni_hostname": host}, **extra) as resp:
            status = int(resp.status_code)
            got_headers = getattr(resp, "headers", None) or {}
            location = str(got_headers.get("location") or "") if status in (301, 302, 303, 307, 308) else ""
            if location:
                following = urljoin(url, location)
                if (urlsplit(following).hostname or "").lower() != host.lower():
                    # une autre machine : sa clé et ses cookies ne la suivent pas
                    sent = {k: v for k, v in sent.items() if k.lower() not in ("authorization", "cookie",
                                                                                 "x-api-key")}
                if status == 303 or (status in (301, 302) and method not in ("GET", "HEAD")):
                    method, body = "GET", None
                    sent = {k: v for k, v in sent.items() if k.lower() != "content-type"}
                url = following
                continue
            chunks, size, truncated = [], 0, False
            if method != "HEAD":
                for chunk in resp.iter_bytes():
                    left()  # la durée totale, pas seulement chaque lecture
                    if size + len(chunk) > max_bytes:
                        chunks.append(chunk[: max_bytes - size])
                        truncated = True
                        break
                    size += len(chunk)
                    chunks.append(chunk)
            shown = {str(k).lower(): str(v)[:2000] for k, v in list(dict(got_headers).items())[:60]}
            return {"status": status, "url": url, "headers": shown, "body": b"".join(chunks),
                    "truncated": truncated}
    raise RuntimeError(f"trop de redirections ({HTTP_REDIRECTS}) — la dernière vers {url[:200]}")


def text_of(body: bytes, headers: Mapping[str, str]) -> str:
    """Le texte d'une réponse, dans le jeu de caractères qu'elle annonce (UTF-8 sinon)."""
    charset = re.search(r"charset=([\w.-]+)", str(headers.get("content-type") or ""), re.I)
    try:
        return body.decode(charset.group(1) if charset else "utf-8", "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def real_http_get(url: str, deadline: float | None = None, *, headers: Mapping[str, str] | None = None) -> str:
    """Un GET (``real_http``) qui rend le texte de la réponse ; une erreur HTTP lève une exception (``api.http_get``,
    la forme simple)."""
    got = real_http("GET", url, headers=headers, deadline=deadline)
    if got["status"] >= 400:
        raise RuntimeError(f"HTTP {got['status']}")
    return text_of(got["body"], got["headers"])
