"""L'hôte de la Forge : les apps qu'elle écrit, exécutées hors de son processus.

**Le bac à sable, c'est le système** (bubblewrap) : chaque app tourne dans
son propre processus, sans réseau, sans les bases ni les clés de Mika (rien
n'est monté hormis ``/usr`` en lecture, son dossier en lecture, un ``/tmp``
éphémère), dans un environnement reconstruit, mémoire, CPU, fichiers et
descripteurs bornés. Un appel qui dépasse son délai **tue** le processus : c'est le seul moyen
d'interrompre un appel C (une expression régulière pathologique tiendrait un
fil pendant des secondes). Sans
bubblewrap, rien ne tourne.

La relecture à l'écriture (syntaxe, imports inutiles dans un bac à sable,
fonctions attendues, taille) est une politesse, pas la défense.

**Son réseau est libre** (ADR 0105) : l'app n'a pas de réseau, elle demande
ses requêtes à l'hôte (``api.http``, ``api.http_get``) — toute adresse
d'Internet, toute méthode, ses en-têtes, les redirections suivies ; jamais
cette machine ni le réseau local (chaque nom est résolu une fois et vérifié,
à chaque saut). ``allowed_domains`` n'est plus qu'une indication.

Le processus d'une app reste chaud entre deux appels ; une nouvelle version
le remplace ; il est relancé s'il meurt.

**Sa base** (``bases.py``, ADR 0101) : une base SQL à elle, créée à sa
première écriture, que l'hôte interroge pour elle (``api.query``,
``api.execute``) sous un utilisateur qui n'a de droits que sur elle ; son
stockage clé/valeur en est une table. Une nouvelle version la garde ; vider
la vide ; effacer l'exporte dans la corbeille, puis la supprime.

**Seules les fonctions déclarées s'appellent** : les fixes (``tick``,
``context``, ``view``, ``action``, ``on_event``) quand elles existent, et
celles que le manifeste déclare (``view_<vue>``, ``action_<vue>_<action>``,
``tool_<nom>``). Une vue rendue pour la console est gardée un instant
(``cache_s``) ; tout autre appel à l'app l'oublie.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import ipaddress
import json
import logging
import os
import re
import resource
import select
import shutil
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy.exc import SQLAlchemyError

from mika.adapters.forge.bases import ForgeBases, SqlRefused
from mika.adapters.forge.manifest import HANDLERS, coherence, lint, read_manifest, signatures
from mika.ports.forge import (
    AppInfo,
    AppService,
    AppTool,
    CallResult,
    ForgeRefused,
    SignalRules,
    StagedVersion,
    arg_specs,
    config_form,
    ui_dump,
    view_specs,
)

__all__ = ["ForgeBases", "ForgeHost", "Limits", "fingerprint", "lint", "read_manifest", "real_http_get"]

log = logging.getLogger("mika.forge")

WORKER = Path(__file__).with_name("worker.py")
NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
#: une ligne de l'app au plus (octets) : de quoi porter un corps de ``HTTP_BODY_MAX`` encodé en JSON, avec une marge ;
#: au-delà, le processus est tué (``worker.MAX_LINE``, le même, refuse avant d'envoyer une demande plus grosse)
MAX_LINE = 2_000_000
MAX_RESULT = 64_000
MAX_LOGS = 500
#: ce qu'une requête de Mika (ses outils, la console) a pour s'exécuter
DB_TIMEOUT_S = 5.0
#: une réponse lue au plus (octets) : au-delà, elle est coupée et l'app le sait (``truncated``)
HTTP_MAX = 5_000_000
#: les vues rendues gardées un instant (même app, version, fonction, paramètres, réglages)
CACHE_MAX = 64
_SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")


@dataclass(frozen=True, slots=True)
class Limits:
    memory_bytes: int = 512 * 1024 * 1024
    cpu_seconds: int = 600  # filet : la durée de vie d'un processus chaud (un service peut durer deux minutes)
    file_bytes: int = 10 * 1024 * 1024
    files: int = 64
    load_timeout_s: float = 5.0


def surface(manifest: Mapping[str, Any], functions: Mapping[str, int] | set[str], title: str
            ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """(vues déclarées dont les fonctions existent, outils, fonctions appelables).
    Une ancienne ``view(api)`` sans vues déclarées devient la vue « principale »."""
    views = []
    for v in manifest.get("views", []):
        if v["function"] not in functions:
            continue
        views.append({**v, "actions": [a for a in v["actions"] if a["function"] in functions]})
    if not views and "view" in functions:
        views = [{"key": "principale", "label": title or "Vue principale", "description": "", "order": 100,
                  "params": [], "actions": [], "function": "view"}]
    tools = [t["name"] for t in manifest.get("tools", []) if f"tool_{t['name']}" in functions]
    services = {f"service_{s['name']}" for s in manifest.get("services", [])} & set(functions)
    callable_ = {h for h in HANDLERS if h in functions} | {v["function"] for v in views} \
        | {a["function"] for v in views for a in v["actions"]} | {f"tool_{t}" for t in tools} | services
    return views, tools, sorted(callable_)


@dataclass(slots=True)
class _Worker:
    proc: subprocess.Popen[bytes]
    version: int
    buffer: bytes = b""


@dataclass(slots=True)
class _Call:
    logs: list[str] = field(default_factory=list)
    signals: list[tuple[str, float, str]] = field(default_factory=list)
    emits: list[tuple[str, str]] = field(default_factory=list)
    #: l'échéance de l'appel (``time.monotonic``) : un service ne la dépasse pas
    deadline: float = 0.0
    #: l'app lit-elle ses réglages secrets (une app qu'un opérateur a validée)
    secrets: bool = True
    #: ses requêtes sur le réseau pendant cet appel (``HTTP_PER_CALL`` au plus)
    requests: int = 0


#: le préfixe NAT64 bien connu : l'adresse IPv4 qu'il porte compte, pas lui
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
#: une requête de l'app dure au plus ça quand elle ne dit rien (``timeout``), jamais plus que ce qui reste à son appel
HTTP_TIMEOUT_S = 15.0
#: …ni plus que ça, même si elle le demande
HTTP_TIMEOUT_MAX_S = 120.0


def is_global(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Une adresse joignable d'Internet et rien d'autre : ni la machine, ni le réseau local, ni l'espace partagé
    d'un opérateur (100.64/10), ni une adresse IPv4 privée déguisée en IPv6 (correspondance, 6to4, Teredo,
    NAT64)."""
    if ip.is_multicast or not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            return is_global(embedded)
    return True


def resolve_public(host: str, port: int = 443) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Résout ``host`` **une fois** : toutes ses adresses doivent être publiques (sinon ``ValueError``). On se
    connecte ensuite à l'une d'elles, jamais à une seconde résolution (qui pourrait répondre autre chose)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"« {host} » ne se résout pas") from exc
    ips = list(dict.fromkeys(ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos))
    if not ips or not all(is_global(ip) for ip in ips):
        raise ValueError(f"« {host} » est une adresse privée : refusée")
    return ips


def _is_public(host: str) -> bool:
    try:
        resolve_public(host)
    except ValueError:
        return False
    return True


#: les en-têtes que l'hôte pose lui-même (la connexion, la taille, la machine visée) : une app choisit tous les autres
#: (ADR 0105 — son réseau est libre : une clé, un cookie, une langue, son nom de client…)
HTTP_RESERVED = frozenset({"host", "content-length", "transfer-encoding", "connection", "keep-alive", "upgrade", "te",
                           "trailer", "expect", "proxy-authorization", "proxy-connection"})
HTTP_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
HTTP_HEADERS_MAX = 40
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
#: ce qu'une requête envoie au plus (octets)
HTTP_BODY_MAX = 1_000_000
#: les signaux qu'un appel peut émettre au plus (ils vont dans la file de l'app, ADR 0105)
SIGNALS_PER_CALL = 20
#: les redirections suivies au plus, chacune revérifiée (jamais vers cette machine ni le réseau local)
HTTP_REDIRECTS = 5
#: les requêtes d'un même appel au plus : de quoi parcourir des pages, pas marteler un site par une boucle ratée
HTTP_PER_CALL = 200
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


def _has(headers: Mapping[str, str], name: str) -> bool:
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
        out = {**({} if _has(sent, "user-agent") else {"User-Agent": USER_AGENT}), **sent,
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


def _said(exc: BaseException) -> str:
    """Ce qu'une erreur de base dit, sans la requête que SQLAlchemy y ajoute."""
    text = str(getattr(exc, "orig", None) or exc).strip()
    return text.splitlines()[0][:300] if text else type(exc).__name__


def fingerprint(manifest: str, code: str) -> str:
    """L'empreinte d'une version : son manifeste et son code, rien d'autre."""
    return hashlib.sha256(manifest.encode() + b"\x00" + code.encode()).hexdigest()[:16]


class ForgeHost:
    def __init__(self, root: Path, *, limits: Limits = Limits(), bwrap: str | None = None,
                 http_get: Callable[[str], str] | None = None, public: Callable[[str], bool] | None = None,
                 http: Callable[[str, str, dict[str, str], bytes | None], Mapping[str, Any]] | None = None,
                 config: Callable[[str], Mapping[str, Any]] | None = None,
                 which: Callable[[str], str | None] = shutil.which, bases: ForgeBases | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits
        self.bwrap = bwrap if bwrap is not None else which("bwrap")
        self.python = which("python3") or "/usr/bin/python3"
        self._http_get = http_get
        #: un faux réseau entier (les essais) : (méthode, adresse, en-têtes, corps) → {status, headers, body, url}
        self._net = http
        self._public = public
        self._config = config
        self._workers: dict[str, _Worker] = {}
        self._locks: dict[str, threading.Lock] = {}
        #: leurs bases (sur le serveur de Mika, ou des fichiers sous ``root/_bases``) et leur journal
        self.bases = bases or ForgeBases(self.root)
        #: ``info`` relu seulement quand ses fichiers changent (la console le demande à chaque page)
        self._infos: dict[str, tuple[tuple[Any, ...], AppInfo | None]] = {}
        #: les vues rendues : clé → (instant, résultat)
        self._cache: dict[tuple[Any, ...], tuple[float, CallResult]] = {}
        self._cachelock = threading.Lock()
        #: qui veut savoir que l'offre a changé (une app écrite ou effacée : ses outils aussi, ADR 0104)
        self._listeners: list[Callable[[], Any]] = []
        #: son fuseau (« Europe/Paris »), relu au lancement de chaque processus d'app : l'horloge d'une app est la
        #: sienne, comme ses rythmes (un bac à sable en UTC lui faisait croire ses relevés décalés, sonde du
        #: 2026-10-13) ; ``None`` : UTC
        self.zone: Callable[[], str] | None = None

    def on_change(self, fn: Callable[[], Any]) -> None:
        self._listeners.append(fn)

    def _zone(self) -> str:
        """Son fuseau, s'il se lit (un nom de la base IANA) ; vide sinon."""
        try:
            zone = str(self.zone()) if self.zone is not None else ""
        except Exception:  # noqa: BLE001 — un fuseau illisible : l'app tourne en UTC, jamais une panne
            return ""
        return zone if re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z0-9_+-]+)*", zone) else ""

    def _changed(self) -> None:
        for fn in self._listeners:
            try:
                fn()
            except Exception:  # noqa: BLE001 — un auditeur en panne ne fait pas échouer l'écriture
                log.exception("forge : un auditeur de l'offre a échoué")

    # ── les apps ──
    def _dir(self, app: str) -> Path:
        if not NAME.match(app):
            raise ForgeRefused("un nom d'app : des minuscules, chiffres et _, commençant par une lettre (2 à 31)")
        return self.root / app

    def _version(self, app: str) -> int:
        try:
            return int(json.loads((self._dir(app) / "version.json").read_text())["version"])
        except (OSError, ValueError, KeyError):
            return 0

    def apps(self) -> list[AppInfo]:
        out = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and NAME.match(d.name) and (d / "main.py").exists():
                info = self.info(d.name)
                if info is not None:
                    out.append(info)
        return out

    def _stamp(self, d: Path) -> tuple[Any, ...]:
        out: list[Any] = []
        for name in ("manifest.yaml", "main.py", "version.json"):
            try:
                st = (d / name).stat()
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def info(self, app: str) -> AppInfo | None:
        try:
            d = self._dir(app)
        except ForgeRefused:
            return None
        stamp = self._stamp(d)
        cached = self._infos.get(app)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        info = self._read_info(app, d) if stamp[1] is not None else None
        self._infos[app] = (stamp, info)
        return info

    def _read_info(self, app: str, d: Path) -> AppInfo | None:
        try:
            text = (d / "manifest.yaml").read_text(encoding="utf-8") if (d / "manifest.yaml").exists() else ""
            code = (d / "main.py").read_text(encoding="utf-8")
        except OSError:
            return None
        manifest, problems = read_manifest(text)
        _, functions = signatures(code)
        title = manifest.get("title") or app
        views, tools, callable_ = surface(manifest, functions, title)
        config = manifest.get("config_fields", [])
        return AppInfo(
            name=app, title=title, description=manifest.get("description", ""),
            version=self._version(app), schedule=manifest.get("schedule", "manual"),
            context=bool(manifest.get("context")) and "context" in functions,
            tools=tuple(AppTool(t["name"], t["description"], arg_specs(t.get("args") or ()),
                                float(t.get("timeout") or 0.0))
                        for t in manifest.get("tools", []) if t["name"] in tools),
            services=tuple(AppService(s["name"], s["schedule"], s["description"], float(s.get("timeout") or 0.0))
                           for s in manifest.get("services", []) if f"service_{s['name']}" in functions),
            timeout=float(manifest.get("timeout") or 0.0),
            signals=SignalRules(**manifest.get("signals") or {}),
            handlers=tuple(sorted(functions)), error="; ".join(problems),
            events=tuple(manifest.get("events", [])) if "on_event" in functions else (),
            config=tuple(manifest.get("config", {}).items()),
            views=view_specs(views), config_fields=config_form(config),
            ui=ui_dump(views, config, tools, callable_), callable=tuple(callable_), fingerprint=fingerprint(text, code),
            domains=tuple(manifest.get("allowed_domains", [])))

    def source(self, app: str) -> tuple[str, str] | None:
        d = self._dir(app)
        if not (d / "main.py").exists():
            return None
        manifest = (d / "manifest.yaml").read_text(encoding="utf-8") if (d / "manifest.yaml").exists() else ""
        return manifest, (d / "main.py").read_text(encoding="utf-8")

    @staticmethod
    def _check(manifest: str, code: str) -> None:
        data, problems = read_manifest(manifest)
        code_problems, functions = signatures(code)
        problems += code_problems
        if not code_problems:
            problems += coherence(data, functions)
        if problems:
            raise ForgeRefused(" ; ".join(problems))

    def _stage_dir(self, app: str, print_: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{16}", print_ or ""):
            raise ForgeRefused("version mise de côté inconnue")
        return self.root / "_attente" / app / print_

    async def stage(self, app: str, manifest: str, code: str) -> str:
        self._dir(app)
        self._check(manifest, code)
        print_ = fingerprint(manifest, code)
        d = self._stage_dir(app, print_)
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.yaml").write_text(manifest, encoding="utf-8")
        (d / "main.py").write_text(code, encoding="utf-8")
        return print_

    def discard(self, app: str, print_: str) -> None:
        """Oublier une version mise de côté (refusée par un opérateur, ADR 0104)."""
        shutil.rmtree(self._stage_dir(app, print_), ignore_errors=True)

    def staged(self, app: str, print_: str) -> StagedVersion | None:
        try:
            d = self._stage_dir(app, print_)
            manifest, code = (d / "manifest.yaml").read_text(encoding="utf-8"), (d / "main.py").read_text(encoding="utf-8")
        except (OSError, ForgeRefused):
            return None
        if fingerprint(manifest, code) != print_:
            return None
        data, _ = read_manifest(manifest)
        return StagedVersion(manifest, code, tuple(data.get("allowed_domains", [])))

    async def install(self, app: str, print_: str) -> int:
        got = self.staged(app, print_)
        if got is None:
            raise ForgeRefused("cette version mise de côté n'existe plus")
        version, _ = await self.write(app, got.manifest, got.code)
        shutil.rmtree(self._stage_dir(app, print_), ignore_errors=True)
        return version

    async def write(self, app: str, manifest: str, code: str) -> tuple[int, list[str]]:
        d = self._dir(app)
        self._check(manifest, code)
        if not (d / "main.py").exists():  # une app neuve : sa base naît avec elle
            try:
                await asyncio.get_running_loop().run_in_executor(None, self.bases.ensure, app)
            except (SqlRefused, SQLAlchemyError) as exc:
                raise ForgeRefused(f"sa base ne se crée pas : {_said(exc)}") from None
        version = self._version(app) + 1
        if (d / "main.py").exists():
            archive = d / "_versions" / str(version - 1)
            archive.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.yaml", "main.py"):
                if (d / name).exists():
                    shutil.copy2(d / name, archive / name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.yaml").write_text(manifest, encoding="utf-8")
        (d / "main.py").write_text(code, encoding="utf-8")
        (d / "version.json").write_text(json.dumps({"version": version}))
        self._stop(app)  # la version suivante repart d'un processus neuf
        self._forget(app)
        # une borne dans son journal : ce qui précède vient d'une version d'avant (sonde du 2026-10-13 — une erreur
        # d'une ancienne version, relue dans le journal, passait pour une erreur de l'actuelle)
        self._log(app, f"── version {version} ──")
        self._changed()
        return version, []

    async def rollback(self, app: str) -> int:
        d = self._dir(app)
        versions = sorted((int(p.name) for p in (d / "_versions").glob("*") if p.name.isdigit()), reverse=True)
        if not versions:
            raise ForgeRefused("aucune version précédente")
        previous = d / "_versions" / str(versions[0])
        manifest = (previous / "manifest.yaml").read_text(encoding="utf-8")
        code = (previous / "main.py").read_text(encoding="utf-8")
        version, _ = await self.write(app, manifest, code)
        return version

    async def erase(self, app: str) -> str:
        d = self._dir(app)
        if not d.exists():
            raise ForgeRefused("cette app n'existe pas")
        self._stop(app)
        trash = self.root / "_corbeille"
        trash.mkdir(exist_ok=True)
        target = trash / f"{app}-{self._version(app)}-{int(time.time())}"
        shutil.move(str(d), str(target))
        self._forget(app)
        try:  # sa base : exportée à côté de son code, puis supprimée (recréée, l'app repartira de rien)
            await asyncio.get_running_loop().run_in_executor(None, self.bases.drop, app, target)
        except (SqlRefused, SQLAlchemyError, OSError) as exc:
            log.warning("forge : la base de « %s » n'a pas pu être supprimée : %s", app, _said(exc))
        self._changed()
        return str(target)

    async def reset_storage(self, app: str) -> int:
        """Vide sa base (ses tables, ses vues, son stockage clé/valeur) ; rend combien de lignes il y avait."""
        self._dir(app)
        try:
            n = await asyncio.get_running_loop().run_in_executor(None, self.bases.reset, app)
        except (SqlRefused, SQLAlchemyError) as exc:
            raise ForgeRefused(_said(exc)) from None
        self._drop_cache(app)
        return n

    # ── sa base, pour Mika et la console ──
    async def _on_base(self, app: str, fn: Callable[..., Any], *args: Any) -> Any:
        if not (self._dir(app) / "main.py").exists():
            raise ForgeRefused("cette app n'existe pas")
        try:
            return await asyncio.get_running_loop().run_in_executor(None, functools.partial(fn, app, *args))
        except (SqlRefused, SQLAlchemyError) as exc:
            raise ForgeRefused(_said(exc)) from None

    async def db_schema(self, app: str) -> dict[str, Any]:
        return await self._on_base(app, self.bases.schema)

    async def db_query(self, app: str, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return await self._on_base(app, self.bases.query, sql, dict(params or {}), time.monotonic() + DB_TIMEOUT_S)

    async def db_execute(self, app: str, sql: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        out = await self._on_base(app, self.bases.execute, sql, dict(params or {}), time.monotonic() + DB_TIMEOUT_S)
        self._drop_cache(app)  # ce qu'elle montre a pu changer
        return out

    async def reload(self, app: str) -> None:
        """Arrête son processus chaud (après l'appel en cours) : l'appel suivant
        repart du disque, et rien de ce qui était gardé ne resservira."""
        self._dir(app)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._reload_sync, app)

    def _reload_sync(self, app: str) -> None:
        with self._lock(app):
            self._stop(app)
        self._forget(app)

    def _forget(self, app: str) -> None:
        self._infos.pop(app, None)
        self._drop_cache(app)

    def _drop_cache(self, app: str) -> None:
        with self._cachelock:
            for key in [k for k in self._cache if k[0] == app]:
                del self._cache[key]

    def logs(self, app: str, n: int = 20) -> list[str]:
        try:
            return self.bases.logs(app, n)
        except SQLAlchemyError as exc:
            log.warning("forge : journal illisible : %s", _said(exc))
            return []

    # ── l'exécution ──
    async def call(self, app: str, method: str, args: dict[str, Any] | None = None, *,
                   timeout_s: float = 5.0, max_result: int = MAX_RESULT, cache_s: float = 0.0,
                   secrets: bool = True) -> CallResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._call_sync, app, method, dict(args or {}), timeout_s,
                                          max_result, cache_s, secrets)

    def _lock(self, app: str) -> threading.Lock:
        return self._locks.setdefault(app, threading.Lock())

    def _limits(self) -> None:  # dans le processus fils, avant bubblewrap
        lim = self.limits
        resource.setrlimit(resource.RLIMIT_AS, (lim.memory_bytes, lim.memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (lim.cpu_seconds, lim.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (lim.file_bytes, lim.file_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (lim.files, lim.files))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def _command(self, app: str) -> list[str]:
        assert self.bwrap
        args = [self.bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL"]
        for d in _SYSTEM_DIRS:
            p = Path(d)
            if p.is_symlink():
                args += ["--symlink", os.readlink(p), d]
            elif p.is_dir():
                args += ["--ro-bind", d, d]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--ro-bind", str(self._dir(app).resolve()), "/app",
                 "--ro-bind", str(WORKER.resolve()), "/runner/worker.py", "--chdir", "/tmp"]
        return [*args, "--", self.python, "-I", "-S", "/runner/worker.py"]

    def _start(self, app: str, info: AppInfo, call: _Call) -> _Worker | str:
        env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
               "PYTHONDONTWRITEBYTECODE": "1"}
        zone = self._zone()
        if zone:
            env["TZ"] = zone
        proc = subprocess.Popen(self._command(app), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=env, start_new_session=True,
                                preexec_fn=self._limits)  # noqa: PLW1509 — les limites du processus fils
        worker = _Worker(proc, info.version)
        deadline = call.deadline = time.monotonic() + self.limits.load_timeout_s
        hello = self._read(worker, deadline)
        # un ``print`` ou un ``api.*`` au niveau du module demande un service avant de se dire chargé
        while isinstance(hello, dict) and "host" in hello:
            reply = self._serve(app, info, str(hello.get("host")), hello.get("params") or {}, call)
            if not self._send(worker, reply):
                hello = "le processus de l'app ne répond plus"
                break
            hello = self._read(worker, deadline)
        if not isinstance(hello, dict) or not hello.get("loaded"):
            self._kill(worker)
            reason = hello.get("error") if isinstance(hello, dict) else hello
            return f"l'app ne se charge pas : {reason or 'délai dépassé au chargement'}"
        return worker

    def _kill(self, w: _Worker) -> None:
        try:
            os.killpg(w.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            w.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (w.proc.stdin, w.proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def _stop(self, app: str) -> None:
        w = self._workers.pop(app, None)
        if w is not None:
            self._kill(w)

    def shutdown(self) -> None:
        for app in list(self._workers):
            self._stop(app)
        self.bases.close()

    def _read(self, w: _Worker, deadline: float) -> dict[str, Any] | str | None:
        """Une ligne JSON avant l'échéance ; ``None`` au délai, un texte si le processus meurt."""
        assert w.proc.stdout is not None
        fd = w.proc.stdout.fileno()
        while b"\n" not in w.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(fd, 65536)
            if not chunk:
                return "le processus de l'app est mort (mémoire, CPU, ou sortie)"
            w.buffer += chunk
            if len(w.buffer) > MAX_LINE:
                return "réponse trop longue"
        line, w.buffer = w.buffer.split(b"\n", 1)
        try:
            msg = json.loads(line)
        except ValueError:
            return "réponse illisible"
        return msg if isinstance(msg, dict) else "réponse illisible"

    def _send(self, w: _Worker, obj: Any) -> bool:
        try:
            assert w.proc.stdin is not None
            w.proc.stdin.write((json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode())
            w.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def _call_sync(self, app: str, method: str, args: dict[str, Any], timeout_s: float,
                   max_result: int = MAX_RESULT, cache_s: float = 0.0, secrets: bool = True) -> CallResult:
        started = time.monotonic()
        call = _Call(secrets=secrets)

        def done(ok: bool, value: Any = None, error: str = "", killed: bool = False) -> CallResult:
            return CallResult(ok, value, error[:1000], killed, int((time.monotonic() - started) * 1000),
                              tuple(call.logs[-50:]), tuple(call.signals), tuple(call.emits))

        if not self.bwrap:
            return done(False, error="bubblewrap est absent : aucune app ne tourne sans isolation")
        info = self.info(app)
        if info is None:
            return done(False, error="cette app n'existe pas")
        if info.error:
            return done(False, error=f"manifeste : {info.error}")
        if method not in info.callable:
            known = ", ".join(info.callable) or "aucune"
            return done(False, error=f"« {method[:60]} » n'est pas une fonction déclarée de cette app "
                                     f"(appelables : {known})")
        key = self._cache_key(app, info, method, args, secrets) if cache_s > 0 else None
        if key is not None:
            with self._cachelock:
                hit = self._cache.get(key)
            if hit is not None and time.monotonic() - hit[0] <= cache_s:
                return hit[1]
        if not method.startswith("view"):
            self._drop_cache(app)  # ce qu'elle fait peut changer ce qu'elle montre
        result = self._run(app, info, method, args, timeout_s, max_result, call, done)
        if key is not None and result.ok:
            with self._cachelock:
                if len(self._cache) >= CACHE_MAX:
                    del self._cache[min(self._cache, key=lambda k: self._cache[k][0])]
                self._cache[key] = (time.monotonic(), result)
        return result

    def _cache_key(self, app: str, info: AppInfo, method: str, args: Mapping[str, Any],
                   secrets: bool = True) -> tuple[Any, ...] | None:
        try:
            config = json.dumps(dict(self._config(app) if self._config else {}), sort_keys=True, default=str)
            return (app, info.version, info.fingerprint, method, json.dumps(args, sort_keys=True, default=str),
                    config, secrets)
        except (TypeError, ValueError):
            return None

    def _run(self, app: str, info: AppInfo, method: str, args: dict[str, Any], timeout_s: float, max_result: int,
             call: _Call, done: Callable[..., CallResult]) -> CallResult:
        lock = self._lock(app)
        if not lock.acquire(timeout=max(0.0, timeout_s)):  # jamais une attente sans fin derrière un autre appel
            return done(False, error="l'app est occupée par un autre appel : réessaie plus tard")
        try:
            return self._run_locked(app, info, method, args, timeout_s, max_result, call, done)
        finally:
            lock.release()

    def _run_locked(self, app: str, info: AppInfo, method: str, args: dict[str, Any], timeout_s: float,
                    max_result: int, call: _Call, done: Callable[..., CallResult]) -> CallResult:
        w = self._workers.get(app)
        if w is None or w.version != info.version or w.proc.poll() is not None:
            if w is not None:
                self._stop(app)
            got = self._start(app, info, call)
            if isinstance(got, str):
                self._log(app, got)
                return done(False, error=got, killed=True)
            w = self._workers[app] = got
        deadline = call.deadline = time.monotonic() + timeout_s
        if not self._send(w, {"call": method, "args": args}):
            self._stop(app)
            return done(False, error="le processus de l'app ne répond plus", killed=True)
        while True:
            msg = self._read(w, deadline)
            if msg is None or isinstance(msg, str):
                self._stop(app)
                reason = msg or f"délai de {timeout_s:g} s dépassé : tuée"
                self._log(app, f"{method} : {reason}")
                return done(False, error=reason, killed=True)
            if "host" in msg:
                reply = self._serve(app, info, str(msg.get("host")), msg.get("params") or {}, call)
                if not self._send(w, reply):
                    self._stop(app)
                    return done(False, error="le processus de l'app ne répond plus", killed=True)
                continue
            if "error" in msg:
                self._log(app, f"{method} : {msg['error']}")
                return done(False, error=str(msg["error"]))
            value = msg.get("result")
            size = len(json.dumps(value, ensure_ascii=False, default=str))
            if size > max_result:
                self._log(app, f"{method} : résultat trop gros ({size // 1000} Ko)")
                return done(False, error=f"résultat trop gros ({size // 1000} Ko ; au plus "
                                         f"{max_result // 1000} Ko)")
            return done(True, value)

    # ── les services de l'hôte ──
    def _log(self, app: str, line: str) -> None:
        try:  # un journal qui ne s'écrit pas ne fait jamais échouer un appel
            self.bases.log(app, line, MAX_LOGS)
        except SQLAlchemyError as exc:
            log.warning("forge : journal de « %s » non écrit : %s", app, _said(exc))

    def _serve(self, app: str, info: AppInfo, name: str, p: Mapping[str, Any], call: _Call) -> dict[str, Any]:
        try:
            return {"result": self._service(app, name, p, call)}
        except (ValueError, RuntimeError, OSError, httpx.HTTPError) as exc:
            return {"error": str(exc)[:300]}
        except SQLAlchemyError as exc:
            return {"error": _said(exc)}

    def _service(self, app: str, name: str, p: Mapping[str, Any], call: _Call) -> Any:
        if name == "log":
            line = str(p.get("message") or "")[:1000]
            call.logs.append(line)
            self._log(app, line)
            return None
        if name == "kv_get":
            return self.bases.kv_get(app, str(p.get("key")), p.get("default"))
        if name == "kv_set":
            return self.bases.kv_set(app, str(p.get("key")), p.get("value"))
        if name == "kv_delete":
            return self.bases.kv_delete(app, str(p.get("key")))
        if name == "kv_keys":
            return self.bases.kv_keys(app, str(p.get("prefix") or ""))
        if name == "sql_query":
            return self.bases.query(app, str(p.get("sql") or ""), p.get("params"), call.deadline)
        if name == "sql_execute":
            return self.bases.execute(app, str(p.get("sql") or ""), p.get("params"), call.deadline)
        if name == "config":
            info = self.info(app)
            defaults = {**dict(info.config), **{f.path: f.default for f in info.config_fields
                                                if f.default is not None}} if info is not None else {}
            values = {**defaults, **dict((self._config(app) if self._config else {}) or {})}
            key = str(p.get("key"))
            secret = info is not None and any(f.path == key and f.kind == "secret" for f in info.config_fields)
            if secret and not call.secrets:  # une version qu'aucun opérateur n'a validée ne lit pas les secrets
                return p.get("default")
            return values.get(key, p.get("default"))
        if name == "emit":
            if len(call.emits) >= 5:
                raise ValueError("trop d'émissions pour un appel (5)")
            data = json.dumps(p.get("data"), ensure_ascii=False, default=str)
            if len(data) > 4000:
                raise ValueError("données trop grosses (4 Ko)")
            call.emits.append((re.sub(r"[^a-z0-9_]", "_", str(p.get("type") or "event").lower())[:40], data))
            return True
        if name == "signal":  # dans la file de l'app (ADR 0105) : bornée par ce qu'elle déclare, pas ici
            if len(call.signals) >= SIGNALS_PER_CALL:
                raise ValueError(f"trop de signaux pour un appel ({SIGNALS_PER_CALL})")
            call.signals.append((str(p.get("summary") or "")[:300], max(0.0, min(1.0, float(p.get("pertinence") or 0))),
                                 str(p.get("emotion") or "")[:20]))
            return True
        if name == "http_get":  # la forme simple : le texte, une erreur HTTP lève une exception
            got = self._http(app, "GET", str(p.get("url") or ""), call, headers=p.get("headers"))
            if got["status"] >= 400:
                raise RuntimeError(f"HTTP {got['status']}")
            return got["text"]
        if name == "http":  # la forme entière : toute méthode, un corps, la réponse avec son statut et ses en-têtes
            data, kind = body_of(p.get("json"), p.get("form"), p.get("body"))
            timeout = p.get("timeout")
            return self._http(app, str(p.get("method") or "GET"), str(p.get("url") or ""), call,
                              headers=p.get("headers"), body=data, kind=kind, binary=bool(p.get("binary")),
                              timeout_s=float(timeout) if isinstance(timeout, int | float) else None)
        raise ValueError(f"service inconnu : {name}")

    def _http(self, app: str, method: str, url: str, call: _Call, *, headers: Any = None, body: bytes | None = None,
              kind: str = "", binary: bool = False, timeout_s: float | None = None) -> dict[str, Any]:
        """Une requête de l'app (ADR 0105 : son réseau est libre — tout Internet, toute méthode, ses en-têtes ;
        jamais cette machine ni le réseau local, que ``real_http`` refuse à chaque saut). Rend ``{status, ok, url,
        headers, text | base64, truncated}`` ; une réponse coupée l'est dans son journal aussi."""
        sent = checked_headers(headers)
        if kind and not _has(sent, "content-type"):
            sent["Content-Type"] = kind
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not host:
            raise ValueError("une adresse http(s) complète")
        call.requests += 1
        if call.requests > HTTP_PER_CALL:
            raise RuntimeError(f"trop de requêtes pour un appel ({HTTP_PER_CALL}) : continue au prochain")
        if self._net is not None:  # un faux réseau entier (les essais)
            got = dict(self._net(method.upper(), url, sent, body))
        elif self._http_get is not None:  # un faux réseau qui ne sait que lire
            if not (self._public or _is_public)(host):
                raise ValueError(f"« {host} » est une adresse privée : refusée")
            got = {"status": 200, "url": url, "headers": {}, "body": self._http_get(url).encode(), "truncated": False}
        else:  # le vrai : une seule résolution par saut, vérifiée, et la durée qui reste à l'appel
            got = real_http(method, url, headers=sent, body=body, deadline=call.deadline or None, timeout_s=timeout_s)
        raw = got.get("body", b"")
        raw = raw.encode() if isinstance(raw, str) else bytes(raw)
        status, shown = int(got.get("status", 200)), dict(got.get("headers") or {})
        if got.get("truncated"):
            line = f"{method.upper()} {url[:200]} : réponse coupée à {HTTP_MAX // 1_000_000} Mo"
            call.logs.append(line)
            self._log(app, line)
        out: dict[str, Any] = {"status": status, "ok": 200 <= status < 300, "url": str(got.get("url") or url),
                               "headers": shown, "truncated": bool(got.get("truncated"))}
        if binary:
            out["base64"] = base64.b64encode(raw).decode()
        else:
            out["text"] = text_of(raw, shown)
        return out
