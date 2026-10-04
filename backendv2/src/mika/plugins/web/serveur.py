#!/usr/bin/env python3
"""Le serveur MCP du plugin ``web`` (stdio) : chercher sur le web avec DuckDuckGo, lire des pages.

Mika ne l'importe pas : le plugin ``web`` le lance, quand il est actif, comme un serveur MCP local du client MCP
(ADR 0064, 0066) — ``python3`` dans sa cage bubblewrap, réseau « isolé » (Internet, jamais cette machine ni le
réseau local). Ses outils sont des outils système : approuvés d'office, ils deviennent ``mcp_web_search``,
``mcp_web_read`` et ``mcp_web_read_pages``.

- ``search`` : la version HTML de DuckDuckGo (``html.duckduckgo.com/html/``), sans clé ni compte. Ses résultats
  sont lus dans la page (titre, adresse, extrait) ; les publicités sont écartées, les liens de redirection défaits.
- ``read`` : le texte d'une page web, le principal d'abord (``<main>``, ``<article>``), par morceaux (``start``)
  pour qu'une longue page se lise en plusieurs fois sous le plafond de réponse de Mika.
- ``read_pages`` (seulement si le plugin permet d'en charger plusieurs à la fois) : quelques pages **en même
  temps**, le début de chacune.

**DuckDuckGo n'aime pas les robots** : deux requêtes trop rapprochées suffisent à lui faire demander de prouver
qu'on est humain (statut 202, ``anomaly-modal``). D'où trois bornes : les recherches sont espacées (et comptées à
la minute), une même recherche est servie du cache un moment, et un défi met la recherche en **pause** (elle le
dit, avec l'heure de reprise) plutôt que d'insister. Les requêtes ressemblent à celles d'un navigateur (GET, ses
en-têtes) : c'est ce que la version HTML laisse passer.

Seulement la bibliothèque standard (Python ≥ 3.10) : ``/usr/bin/python3`` suffit dans la cage. Rien n'est écrit
sur le disque ; la sortie d'erreur (gardée par Mika pour l'opérateur) ne dit jamais ce qui a été cherché ou lu.

Ses réglages viennent de l'environnement, posé par le plugin d'après ses paramètres (``Settings.from_env``).
Essai à la main : ``python3 serveur.py --chercher "actualités"`` ; ``python3 serveur.py --lire https://…``.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

NAME, VERSION = "mika-web", "1.1.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

SEARCH_URL = "https://html.duckduckgo.com/html/"
#: un navigateur ordinaire : la version HTML de DuckDuckGo refuse ce qui ne ressemble à rien
BROWSER = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 "
                  "Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}
HTTP_TIMEOUT_S = 15.0
#: une page au-delà : lue jusque-là seulement
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
#: une même page tant de temps en cache (lire sa suite ne la retélécharge pas)
CACHE_SIZE = 64

MAX_RESULTS = 10
SNIPPET_CHARS = 300
READ_DEFAULT_CHARS = 3500  # sous le plafond de réponse par défaut d'un outil (4 000), la suite comprise
READ_MAX_CHARS = 20_000
#: ce qu'on lit de chaque page dans ``read_pages`` (par défaut, et au plus)
PAGES_DEFAULT_CHARS = 1500
PAGES_MAX_CHARS = 6000
#: le texte d'un <main>/<article> au-delà : c'est lui qu'on lit, pas toute la page
MAIN_MIN_CHARS = 400

PERIODS = {"jour": "d", "semaine": "w", "mois": "m", "annee": "y"}
SAFESEARCH = {"strict": "1", "modere": "-1", "non": "-2"}
REGION = re.compile(r"[a-z]{2}-[a-z]{2}")
#: le préfixe de ses variables d'environnement
ENV = "MIKA_WEB_"


@dataclass(frozen=True, slots=True)
class Settings:
    """Ce que le plugin règle (ses paramètres, passés par l'environnement)."""

    #: entre deux recherches, au moins ce délai ; et pas plus de tant par minute
    spacing_s: float = 3.0
    searches_per_minute: int = 12
    reads_per_minute: int = 30
    #: combien de pages ``read_pages`` charge en même temps (1 : pas de ``read_pages``)
    parallel_pages: int = 3
    #: un défi de DuckDuckGo : plus aucune recherche pendant ce temps
    pause_s: float = 15 * 60
    #: une même recherche, une même page, servies du cache tant de temps (0 : jamais)
    cache_s: float = 15 * 60
    #: on attend son tour sans rien dire jusque-là ; au-delà, on le dit (le client attend l'outil 45 s)
    max_wait_s: float = 10.0
    region: str = "fr-fr"
    safesearch: str = "modere"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Les réglages de l'environnement ; une valeur illisible garde son défaut (le serveur démarre quand même)."""
        env = os.environ if env is None else env
        base = cls()

        def num(key: str, default: float, lo: float, hi: float) -> float:
            try:
                return min(hi, max(lo, float(env.get(ENV + key, default))))
            except ValueError:
                return default

        region = env.get(ENV + "REGION", base.region).strip().lower()
        safe = env.get(ENV + "SAFESEARCH", base.safesearch).strip().lower()
        return cls(spacing_s=num("ESPACEMENT_S", base.spacing_s, 0.0, 120.0),
                   searches_per_minute=int(num("RECHERCHES_PAR_MINUTE", base.searches_per_minute, 1, 60)),
                   reads_per_minute=int(num("LECTURES_PAR_MINUTE", base.reads_per_minute, 1, 120)),
                   parallel_pages=int(num("PAGES_EN_PARALLELE", base.parallel_pages, 1, 8)),
                   pause_s=num("PAUSE_S", base.pause_s, 60.0, 24 * 3600.0),
                   cache_s=num("CACHE_S", base.cache_s, 0.0, 24 * 3600.0),
                   max_wait_s=num("ATTENTE_MAX_S", base.max_wait_s, 0.0, 60.0),
                   region=region if REGION.fullmatch(region) else base.region,
                   safesearch=safe if safe in SAFESEARCH else base.safesearch)

    def env(self) -> dict[str, str]:
        """L'inverse de ``from_env`` : ce que le plugin pose dans l'environnement du serveur."""
        return {ENV + "ESPACEMENT_S": f"{self.spacing_s:g}", ENV + "RECHERCHES_PAR_MINUTE": str(self.searches_per_minute),
                ENV + "LECTURES_PAR_MINUTE": str(self.reads_per_minute),
                ENV + "PAGES_EN_PARALLELE": str(self.parallel_pages), ENV + "PAUSE_S": f"{self.pause_s:g}",
                ENV + "CACHE_S": f"{self.cache_s:g}", ENV + "ATTENTE_MAX_S": f"{self.max_wait_s:g}",
                ENV + "REGION": self.region, ENV + "SAFESEARCH": self.safesearch}


_READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}


def tools(settings: Settings) -> list[dict[str, Any]]:
    """Ce qu'il propose (``tools/list``) : ``read_pages`` seulement s'il peut charger plusieurs pages à la fois. Le
    plugin s'en sert aussi pour approuver d'office ce que le serveur dira — une seule définition."""
    out: list[dict[str, Any]] = [
        {
            "name": "search",
            "title": "Chercher sur le web",
            "description": ("Chercher sur le web (DuckDuckGo) : les résultats, chacun avec son titre, son adresse et "
                            "un extrait. Pour en savoir plus, lire ensuite une page avec « read »."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 300,
                              "description": "ce qu'il faut chercher, en quelques mots"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS,
                                    "description": "combien de résultats (5 par défaut)"},
                    "period": {"type": "string", "enum": list(PERIODS),
                               "description": "seulement ce qui date de moins d'un jour, d'une semaine, d'un mois, "
                                              "d'un an (rien : sans limite)"},
                    "region": {"type": "string", "description": "la région des résultats : fr-fr par défaut, "
                                                                "wt-wt pour le monde entier"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "annotations": _READ_ONLY,
        },
        {
            "name": "read",
            "title": "Lire une page web",
            "description": ("Lire le texte d'une page web (une adresse http ou https, par exemple un résultat de "
                            "« search »). Une longue page se lit par morceaux : la réponse dit où reprendre (start)."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000,
                            "description": "l'adresse de la page"},
                    "start": {"type": "integer", "minimum": 0,
                              "description": "où reprendre la lecture (0 : au début)"},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": READ_MAX_CHARS,
                                  "description": f"combien de caractères lire ({READ_DEFAULT_CHARS} par défaut)"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            "annotations": _READ_ONLY,
        },
    ]
    if settings.parallel_pages > 1:
        out.append({
            "name": "read_pages",
            "title": "Lire plusieurs pages",
            "description": (f"Lire jusqu'à {settings.parallel_pages} pages web en même temps (par exemple les "
                            "meilleurs résultats d'une recherche) : le début de chacune. Pour la suite d'une page, "
                            "« read »."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"},
                             "description": f"les adresses, {settings.parallel_pages} au plus"},
                    "max_chars": {"type": "integer", "minimum": 300, "maximum": PAGES_MAX_CHARS,
                                  "description": f"combien de caractères de chaque page ({PAGES_DEFAULT_CHARS} par "
                                                 "défaut)"},
                },
                "required": ["urls"],
                "additionalProperties": False,
            },
            "annotations": _READ_ONLY,
        })
    return out


class ToolError(Exception):
    """Un échec à dire à Mika (``isError``) : le texte est pour elle, en français."""


# ── Le réseau ────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Fetched:
    status: int
    url: str  # l'adresse finale (après redirections)
    content_type: str
    charset: str | None
    body: bytes


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Les redirections : http(s) seulement, cinq au plus."""

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urlsplit(newurl).scheme.lower() not in ("http", "https"):
            raise ToolError("la page redirige vers une adresse qui n'est pas du web")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


#: aucun mandataire hérité de l'environnement
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects())


def http(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> Fetched:
    """Un aller-retour HTTP, borné en taille et en temps. Un statut d'erreur rend sa page (DuckDuckGo répond 202
    à un robot) ; une panne de réseau lève ``OSError``."""
    req = urllib.request.Request(url, data=data, headers={**BROWSER, **(headers or {})})
    try:
        resp = _OPENER.open(req, timeout=HTTP_TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        resp = exc
    with resp:
        body = resp.read(MAX_PAGE_BYTES)
        info: Message = resp.headers
        return Fetched(resp.status if hasattr(resp, "status") else resp.code, resp.geturl(),
                       info.get_content_type(), info.get_content_charset(), body)


# ── Les bornes ───────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Throttle:
    """Pas plus de ``per_minute`` appels sur une minute glissante, et au moins ``spacing`` entre deux. On attend son
    tour (``sleep``) jusqu'à ``max_wait`` ; au-delà, ``ToolError`` dit dans combien de temps réessayer."""

    per_minute: int
    spacing: float
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    max_wait: float = 10.0
    _times: deque[float] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def take(self, what: str) -> None:
        with self._lock:
            t = self.now()
            while self._times and t - self._times[0] >= 60.0:
                self._times.popleft()
            ready = self._times[-1] + self.spacing if self._times else t
            if len(self._times) >= self.per_minute:
                ready = max(ready, self._times[0] + 60.0)
            wait = max(0.0, ready - t)
            if wait > self.max_wait:
                raise ToolError(f"trop de {what} d'affilée : réessaie dans {int(wait) + 1} s")
            self._times.append(t + wait)
        if wait > 0:
            self.sleep(wait)


class Cache:
    """Les dernières réponses, un temps : une même recherche ne repart pas chez DuckDuckGo (``ttl`` 0 : rien
    n'est gardé)."""

    def __init__(self, ttl: float = 15 * 60, size: int = CACHE_SIZE,
                 now: Callable[[], float] = time.monotonic) -> None:
        self.ttl, self.size, self.now = ttl, size, now
        self._items: OrderedDict[Any, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> str | None:
        with self._lock:
            got = self._items.get(key)
            if got is None or self.ttl <= 0 or self.now() - got[0] > self.ttl:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return got[1]

    def put(self, key: Any, value: str) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            self._items[key] = (self.now(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)


# ── Lire les pages ───────────────────────────────────────────────────────────────────────────────────


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    return set((dict(attrs).get("class") or "").split())


class ResultsParser(HTMLParser):
    """Une page de résultats de la version HTML de DuckDuckGo : un ``div.result`` par résultat, son titre
    (``a.result__a``, qui porte l'adresse) et son extrait (``.result__snippet``). Un défi anti-robot se reconnaît à
    ses classes ``anomaly-modal``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, Any]] = []
        self.challenge = False
        self._field: str | None = None
        self._tag = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _classes(attrs)
        if any(c.startswith("anomaly-modal") for c in classes):
            self.challenge = True
        if tag == "div" and "result" in classes:
            self.results.append({"title": [], "url": "", "snippet": [], "ad": "result--ad" in classes})
            self._field = None
            return
        if not self.results:
            return
        if self._field is not None:
            if tag == self._tag:
                self._depth += 1
            return
        if tag == "a" and "result__a" in classes:
            self._field, self._tag, self._depth = "title", "a", 1
            self.results[-1]["url"] = dict(attrs).get("href") or ""
        elif "result__snippet" in classes:
            self._field, self._tag, self._depth = "snippet", tag, 1

    def handle_endtag(self, tag: str) -> None:
        if self._field is not None and tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                self._field = None

    def handle_data(self, data: str) -> None:
        if self._field is not None and self.results:
            self.results[-1][self._field].append(data)


def real_url(href: str) -> str:
    """L'adresse d'un résultat : un lien de redirection de DuckDuckGo (``/l/?uddg=…``) défait ; une publicité
    (``/y.js``) ou ce qui n'est pas du web : vide."""
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    host = parts.hostname or ""
    if host == "duckduckgo.com" or host.endswith(".duckduckgo.com"):
        if parts.path.startswith("/l/"):
            href = parse_qs(parts.query).get("uddg", [""])[0]
            parts = urlsplit(href)
        else:
            return ""
    return href if parts.scheme in ("http", "https") and parts.hostname else ""


def squash(text: str) -> str:
    return " ".join(text.split())


def parse_results(html: str, limit: int) -> tuple[list[dict[str, str]], bool]:
    """(résultats, défi) d'une page de résultats."""
    parser = ResultsParser()
    parser.feed(html)
    parser.close()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for r in parser.results:
        url = real_url(r["url"])
        title = squash("".join(r["title"]))
        if r["ad"] or not url or not title or url in seen:
            continue
        seen.add(url)
        snippet = squash("".join(r["snippet"]))
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        out.append({"title": title, "url": url, "snippet": snippet})
        if len(out) >= limit:
            break
    return out, parser.challenge


#: ce qui n'est pas le texte d'une page (pas ``form`` : certains sites y mettent la page entière)
SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "aside",
                     "iframe", "button", "select", "textarea", "canvas", "object", "header", "dialog"})
#: ce qui passe à la ligne
BLOCKS = frozenset({"p", "div", "section", "article", "main", "li", "ul", "ol", "br", "h1", "h2", "h3", "h4", "h5",
                    "h6", "tr", "table", "blockquote", "pre", "figcaption", "dd", "dt", "hr", "td", "th"})
VOID = frozenset({"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track",
                  "wbr", "param"})


class TextParser(HTMLParser):
    """Le texte lisible d'une page : sans scripts, menus, pieds de page ni formulaires ; celui de ``<main>`` ou
    ``<article>`` à part (c'est lui qu'on lit quand il pèse assez). Le titre : ``<title>``, sinon ``og:title``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.og_title = ""
        self.all: list[str] = []
        self.main: list[str] = []
        self._skip = 0
        self._main = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            if (a.get("property") or a.get("name")) == "og:title" and not self.og_title:
                self.og_title = a.get("content") or ""
        if tag in VOID:
            if tag in ("br", "hr") and not self._skip:
                self._newline()
            return
        if tag in SKIPPED:
            self._skip += 1
        elif tag in ("main", "article"):
            self._main += 1
        if tag in BLOCKS and not self._skip:
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in VOID:
            return
        if tag in SKIPPED and self._skip:
            self._skip -= 1
        elif tag in ("main", "article") and self._main:
            self._main -= 1
        if tag in BLOCKS and not self._skip:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._skip:
            return
        self.all.append(data)
        if self._main:
            self.main.append(data)

    def _newline(self) -> None:
        self.all.append("\n")
        if self._main:
            self.main.append("\n")


def _lines(parts: list[str]) -> str:
    lines = (squash(line) for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def page_text(html: str) -> tuple[str, str]:
    """(titre, texte) d'une page HTML."""
    parser = TextParser()
    parser.feed(html)
    parser.close()
    main, everything = _lines(parser.main), _lines(parser.all)
    title = squash("".join(parser.title_parts)) or squash(parser.og_title)
    return title, main if len(main) >= MAIN_MIN_CHARS else everything


_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([A-Za-z0-9_.:-]+)""", re.I)


def decode(body: bytes, charset: str | None) -> str:
    """Le texte d'une page : le jeu de caractères de l'en-tête, sinon celui de la page, sinon UTF-8."""
    if not charset:
        found = _META_CHARSET.search(body[:4096])
        charset = found.group(1).decode("ascii", "replace") if found else "utf-8"
    try:
        return body.decode(charset, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def check_url(url: str) -> str:
    """Une adresse web qu'on peut lire : http(s), un hôte, pas d'identifiants, pas une adresse de cette machine ou
    du réseau local (la cage l'interdit déjà ; on le dit plus tôt et plus clairement)."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ToolError("donne une adresse web complète (http:// ou https://)")
    if parts.username or parts.password:
        raise ToolError("une adresse avec un identifiant ou un mot de passe ne se lit pas ici")
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".lan", ".home.arpa", ".internal", ".localdomain")):
        raise ToolError("cette adresse est sur cette machine ou le réseau local : je ne la lis pas")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url
    if not ip.is_global:
        raise ToolError("cette adresse est sur cette machine ou le réseau local : je ne la lis pas")
    return url


# ── Les outils ───────────────────────────────────────────────────────────────────────────────────────


def _clock() -> str:
    return datetime.now().strftime("%H:%M")


class Web:
    """Ce que font les outils. ``fetch``, ``now``, ``sleep`` et ``clock`` s'injectent (les tests)."""

    def __init__(self, settings: Settings | None = None, *, fetch: Callable[..., Fetched] = http,
                 now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], str] = _clock) -> None:
        self.settings = st = settings or Settings()
        self.fetch, self.now, self.clock = fetch, now, clock
        self.region = _region(st.region)
        self.safesearch = SAFESEARCH.get(st.safesearch, SAFESEARCH["modere"])
        self.searches = Throttle(st.searches_per_minute, st.spacing_s, now=now, sleep=sleep, max_wait=st.max_wait_s)
        self.reads = Throttle(st.reads_per_minute, 0.0, now=now, sleep=sleep, max_wait=st.max_wait_s)
        self.cache = Cache(st.cache_s, now=now)
        self.paused_until = 0.0
        self._paused_at = ""

    # ── search
    def search(self, query: str, max_results: int = 5, period: str | None = None, region: str | None = None) -> str:
        query = squash(query)
        if not query:
            raise ToolError("dis ce qu'il faut chercher")
        limit = min(MAX_RESULTS, max(1, int(max_results)))
        df = PERIODS.get(period or "", "")
        if period and not df:
            raise ToolError(f"période inconnue : {', '.join(PERIODS)}")
        kl = _region(region) if region else self.region
        key = (query.lower(), limit, df, kl)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self.now() < self.paused_until:
            raise ToolError("DuckDuckGo m'a pris pour un robot : je ne cherche plus avant "
                            f"{self._paused_at} (une pause, pour ne pas insister)")
        self.searches.take("recherches")
        form = {"q": query, "kl": kl, "kp": self.safesearch, **({"df": df} if df else {})}
        try:
            got = self.fetch(f"{SEARCH_URL}?{urlencode(form)}")
        except ToolError:
            raise
        except (OSError, ValueError) as exc:
            log(f"recherche : réseau ({type(exc).__name__})")
            raise ToolError("je n'arrive pas à joindre DuckDuckGo (pas de réseau ?)") from None
        results, challenge = parse_results(decode(got.body, got.charset), limit)
        if challenge or got.status == 202:
            pause = self.settings.pause_s
            self.paused_until = self.now() + pause
            self._paused_at = _later(self.clock(), pause)
            log("recherche : défi anti-robot, pause")
            raise ToolError("DuckDuckGo demande de prouver qu'on est humain (trop de recherches) : je ne cherche "
                            f"plus avant {self._paused_at}")
        if got.status >= 400:
            log(f"recherche : statut {got.status}")
            raise ToolError(f"DuckDuckGo a répondu par une erreur ({got.status})")
        text = format_results(query, results)
        self.cache.put(key, text)
        return text

    # ── read
    def read(self, url: str, start: int = 0, max_chars: int = READ_DEFAULT_CHARS) -> str:
        size = min(READ_MAX_CHARS, max(500, int(max_chars)))
        return format_page(*self._load(url), max(0, int(start)), size)

    def read_pages(self, urls: Any, max_chars: int = PAGES_DEFAULT_CHARS) -> str:
        """Plusieurs pages **en même temps** (le début de chacune) ; une page qui échoue le dit à sa place, les
        autres sont lues ; si aucune ne l'est, c'est un échec."""
        most = self.settings.parallel_pages
        if most <= 1:
            raise ToolError("lire plusieurs pages à la fois n'est pas permis ici : une à la fois, avec « read »")
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            raise ToolError("« urls » : une liste d'adresses")
        unique = list(dict.fromkeys(u.strip() for u in urls if u.strip()))
        if not unique:
            raise ToolError("donne au moins une adresse")
        if len(unique) > most:
            raise ToolError(f"{most} pages au plus à la fois")
        size = min(PAGES_MAX_CHARS, max(300, int(max_chars)))

        def one(url: str) -> tuple[bool, str]:
            try:
                return True, format_page(*self._load(url), 0, size)
            except ToolError as exc:
                return False, f"Adresse : {url}\nImpossible de la lire : {exc}"

        with ThreadPoolExecutor(max_workers=len(unique)) as pool:
            pages = list(pool.map(one, unique))
        text = "\n\n———\n\n".join(page for _ok, page in pages)
        if not any(ok for ok, _page in pages):
            raise ToolError("aucune de ces pages n'a pu être lue :\n\n" + text)
        return text

    def _load(self, url: str) -> tuple[str, str, str]:
        """(titre, adresse finale, texte) d'une page, du cache si elle y est encore."""
        url = check_url(url)
        key = ("read", url)
        page = self.cache.get(key)
        if page is None:
            self.reads.take("lectures")
            try:
                got = self.fetch(url)
            except ToolError:
                raise
            except (OSError, ValueError) as exc:
                log(f"lecture : réseau ({type(exc).__name__})")
                raise ToolError("je n'arrive pas à joindre cette page (adresse introuvable ou pas de réseau)") \
                    from None
            if got.status >= 400:
                raise ToolError(f"la page a répondu par une erreur ({got.status})")
            page = _page(got)
            self.cache.put(key, page)
        title, _, rest = page.partition("\n")
        final, _, text = rest.partition("\n")
        return title, final, text


def _region(value: str) -> str:
    value = value.strip().lower()
    if not REGION.fullmatch(value):
        raise ToolError("région : deux lettres, un tiret, deux lettres (fr-fr, be-fr, wt-wt…)")
    return value


def _later(hhmm: str, seconds: float) -> str:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return "un moment"
    total = (h * 60 + m + int(seconds // 60)) % (24 * 60)
    return f"{total // 60}h{total % 60:02d}"


def _page(got: Fetched) -> str:
    """« titre \\n adresse finale \\n texte » d'une page lue (ce que garde le cache)."""
    kind = got.content_type
    if kind in ("text/html", "application/xhtml+xml"):
        title, text = page_text(decode(got.body, got.charset))
    elif kind.startswith("text/") or kind in ("application/json", "application/xml"):
        title, text = "", decode(got.body, got.charset).strip()
    elif kind == "application/pdf":
        raise ToolError("c'est un PDF : je ne sais pas le lire ici")
    else:
        raise ToolError(f"ce n'est pas une page lisible ({kind})")
    if not text:
        raise ToolError("la page ne contient pas de texte lisible (peut-être faite en JavaScript)")
    return f"{squash(title)}\n{got.url}\n{text}"


def format_results(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return f"Aucun résultat pour « {query} »."
    lines = [f"Résultats DuckDuckGo pour « {query} » :"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}" + (f"\n   {r['snippet']}" if r["snippet"] else ""))
    return "\n".join(lines)


def format_page(title: str, url: str, text: str, start: int, size: int) -> str:
    if start >= len(text):
        return f"La page s'arrête avant ({len(text)} caractères en tout)."
    chunk = text[start:start + size]
    end = start + len(chunk)
    if end < len(text):  # couper à la fin d'une phrase ou d'une ligne, si possible
        cut = max(chunk.rfind("\n"), chunk.rfind(". "))
        if cut > size // 2:
            chunk, end = chunk[:cut + 1], start + cut + 1
    head = [f"Titre : {title}" if title else "Titre : (aucun)", f"Adresse : {url}"]
    if start:
        head.append(f"(à partir du caractère {start})")
    tail = (f"\n\n[suite : start={end}, encore {len(text) - end} caractères]" if end < len(text)
            else "\n\n[fin de la page]")
    return "\n".join(head) + "\n\n" + chunk.strip() + tail


# ── Le protocole (JSON-RPC, une ligne par message) ───────────────────────────────────────────────────


def log(line: str) -> None:
    """Sa sortie d'erreur, que Mika garde pour l'opérateur : jamais ce qui a été cherché ou lu."""
    sys.stderr.write(f"{NAME}: {line}\n")
    sys.stderr.flush()


class Server:
    """Les messages MCP : ``initialize``, ``ping``, ``tools/list``, ``tools/call`` ; les notifications ne reçoivent
    rien. Un appel d'outil qui échoue rend ``isError`` (un texte pour Mika), jamais une erreur de protocole."""

    def __init__(self, web: Web | None = None) -> None:
        self.web = web or Web()

    def handle(self, msg: Any) -> dict[str, Any] | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "requête invalide")
        mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if "id" not in msg:
            return None  # une notification (initialized, cancelled…)
        if method == "initialize":
            asked = str(params.get("protocolVersion") or "")
            return _result(mid, {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                                 "capabilities": {"tools": {"listChanged": False}},
                                 "serverInfo": {"name": NAME, "version": VERSION}})
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": tools(self.web.settings)})
        if method == "tools/call":
            return self._call(mid, params)
        return _error(mid, -32601, f"méthode inconnue : {method}")

    def _call(self, mid: Any, params: dict[str, Any]) -> dict[str, Any]:
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in {t["name"] for t in tools(self.web.settings)} or not isinstance(args, dict):
            return _error(mid, -32602, f"outil inconnu : {name}")
        try:
            if name == "search":
                text = self.web.search(_text(args, "query"), _int(args, "max_results", 5),
                                       args.get("period") or None, args.get("region") or None)
            elif name == "read":
                text = self.web.read(_text(args, "url"), _int(args, "start", 0),
                                     _int(args, "max_chars", READ_DEFAULT_CHARS))
            else:
                text = self.web.read_pages(args.get("urls"), _int(args, "max_chars", PAGES_DEFAULT_CHARS))
            return _result(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        except ToolError as exc:
            return _result(mid, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # noqa: BLE001 — un défaut à nous ne fait pas tomber le serveur
            log(f"{name} : défaut ({type(exc).__name__})")
            return _result(mid, {"content": [{"type": "text", "text": "un défaut du serveur de recherche"}],
                                 "isError": True})


def _text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ToolError(f"« {key} » : un texte")
    return value


def _int(args: dict[str, Any], key: str, default: int) -> int:
    value = args.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(f"« {key} » : un nombre")
    return int(value)


def _result(mid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve(server: Server, stdin: Any = None, stdout: Any = None, workers: int = 4) -> None:
    """Lire une ligne, y répondre — les appels d'outils en parallèle (un ``ping`` n'attend pas une lecture). Une
    requête annulée (``notifications/cancelled``) pendant qu'elle tourne ne reçoit pas de réponse ; une annulation
    qui arrive après ne retient rien (un identifiant réutilisé plus tard n'est pas perdu)."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    lock = threading.Lock()
    running: set[Any] = set()
    cancelled: set[Any] = set()

    def send(reply: dict[str, Any] | None, *, call: bool = False) -> None:
        if reply is None:
            return
        with lock:
            mid = reply.get("id")
            if call:
                running.discard(mid)
                if mid in cancelled:
                    cancelled.discard(mid)
                    return
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                send(_error(None, -32700, "JSON illisible"))
                continue
            if isinstance(msg, dict) and msg.get("method") == "notifications/cancelled":
                target = (msg.get("params") or {}).get("requestId")
                with lock:
                    if target in running:
                        cancelled.add(target)
                continue
            if isinstance(msg, dict) and msg.get("method") == "tools/call" and "id" in msg:
                with lock:
                    running.add(msg["id"])
                pool.submit(lambda m=msg: send(server.handle(m), call=True))
            else:
                send(server.handle(msg))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--chercher", metavar="REQUÊTE", help="faire une recherche et l'afficher, puis quitter")
    parser.add_argument("--lire", metavar="ADRESSE", help="lire une page et l'afficher, puis quitter")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.chercher or args.lire:
        web = Web(settings)
        try:
            print(web.search(args.chercher) if args.chercher else web.read(args.lire))
        except ToolError as exc:
            print(f"échec : {exc}", file=sys.stderr)
            return 1
        return 0
    sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    serve(Server(Web(settings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
