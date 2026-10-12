"""Les flux réels : HTTP (httpx), RSS 2.0 / RDF / Atom en bibliothèque
standard, un cache à part (la base ``feeds``, déclarée dans ``models`` :
SQLite pour les tests, MariaDB en production — ADR 0101).

- Chaque article n'est rendu qu'une fois (``poll``) ; au premier relevé d'un
  flux, seuls les plus récents (on n'hérite pas de trois ans d'archives).
- Un article se lit par son identifiant, depuis le cache : l'adresse vient
  du flux, jamais d'un texte. **Mais un flux peut mentir** : l'adresse d'un
  article (et chaque redirection, suivie à la main, trois au plus) doit
  désigner une machine **publique** — l'hôte est résolu, toute adresse qui
  n'est pas globalement routable (boucle locale, réseau privé, lien local,
  plages réservées, métadonnées de nuage) est refusée, et la connexion se fait
  vers l'adresse vérifiée (pas de seconde résolution qu'un DNS pourrait
  retourner). Un flux, lui, est choisi par un opérateur : son adresse peut
  être locale ; ses redirections ne quittent pas son hôte pour une machine
  privée.
- **Des délais qui mordent** : un serveur qui égoutte sa réponse octet par
  octet ne retient pas un flux plus que son délai, ni un relevé plus que le
  sien ; le XML se lit hors de la boucle, et le texte HTML en une passe
  linéaire (``ports.preprocess.html_text``).
- La liste des flux est relue à chaque relevé.
- Chaque relevé d'un flux se note (tentative, succès, erreur, articles lus,
  nouveaux) : la console dit quel flux ne répond plus, et pourquoi.
- **Le cache tient un horizon**, pas tout ce qui a paru depuis l'installation
  (comme celui des mails) : un article déjà rendu s'efface quand son flux ne
  le liste plus depuis deux mois, ou au-delà des derniers de son flux. Jamais
  un article pas encore rendu, ni un que son flux liste encore (effacé, il
  reviendrait comme neuf) ; un flux qui revient après plus longtemps en
  panne n'hérite pas de ses archives.
"""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import ipaddress
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx
from sqlalchemy import delete, false, func, select, true, update
from sqlalchemy.orm import Session, sessionmaker

from mika.adapters.database import Target, as_target
from mika.adapters.feeds.models import URL_MAX, EntryRow, FeedRow, entry_values, fit
from mika.kernel.clock import DAY
from mika.ports.feeds import Entry, shown
from mika.ports.paging import Page, fold_text
from mika.ports.preprocess import HTML_SKIPPED, html_text
from mika.ports.sql import FEEDS, insert_ignore
from mika.vocab.phrasebook import phrase

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_RSS1 = "http://purl.org/rss/1.0/"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
SUMMARY_MAX = 2000
ARTICLE_MAX = 12_000
FIRST_POLL = 5
MAX_BYTES = 5_000_000
MAX_REDIRECTS = 3
#: un relevé entier (tous les flux) ne dure pas plus que ceci
POLL_TOTAL_S = 120.0
#: ce qu'on ne lit pas d'une page d'article
ARTICLE_SKIPPED = HTML_SKIPPED | frozenset({"nav", "footer", "aside"})
#: un article déjà rendu que son flux ne liste plus depuis ce délai quitte le cache…
KEPT_US = 60 * DAY
#: … comme au-delà de tant d'articles par flux (le garde-fou d'un flux qui déborde : un flux d'actualité
#: ordinaire, quelques dizaines d'articles par jour, n'y arrive pas avant le délai)
KEEP_PER_FEED = 5000

#: une résolution de nom : ``(hôte, port)`` → les adresses IP
Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
#: ce qu'on lit d'un article (dans l'ordre des champs d'``Entry``)
_ENTRY = (EntryRow.id, EntryRow.feed, EntryRow.title, EntryRow.link, EntryRow.summary, EntryRow.published)
#: les plus récents d'abord ; l'ordre d'arrivée, puis l'identifiant, départagent (le même ordre sur les deux moteurs)
_NEWEST = (EntryRow.published.desc(), EntryRow.n.desc(), EntryRow.id)

__all__ = ["HttpFeeds", "NotPublic", "clean", "parse", "routable", "shown"]


class NotPublic(OSError):
    """Une adresse qui ne désigne pas une machine publique : on n'y va pas."""


async def system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def routable(ip: str) -> bool:
    """Une adresse globalement routable (ni boucle, ni privée, ni lien local, ni réservée, ni
    multidiffusion) — une IPv4 enveloppée dans une IPv6 est jugée pour ce qu'elle est."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        inner = addr.ipv4_mapped or addr.sixtofour or (addr.teredo[1] if addr.teredo else None)
        if inner is not None:
            addr = inner
    return bool(addr.is_global) and not addr.is_multicast


def _why(exc: BaseException) -> str:
    """Une erreur de relevé en mots (jamais l'adresse : elle peut porter un jeton)."""
    if isinstance(exc, NotPublic):
        return f"refusé : {exc}"
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "trop long : le serveur ne répond pas à temps"
    if isinstance(exc, httpx.ConnectError):
        return "injoignable (nom inconnu ou connexion refusée)"
    if isinstance(exc, httpx.TooManyRedirects):
        return "trop de redirections"
    return f"erreur réseau ({type(exc).__name__})"


def clean(raw: str) -> str:
    """Le texte d'un champ de flux (souvent du HTML échappé), sur une ligne."""
    return " ".join(html_text(raw or "", max_input=200_000, limit=50_000).split())


def _text(node: Any, tag: str) -> str:
    if node is None:
        return ""
    child = node.find(tag)
    return (child.text or "") if child is not None else ""


def _date(raw: str) -> int:
    raw = (raw or "").strip()
    if not raw:
        return 0
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    try:
        return int(dt.timestamp() * 1_000_000)
    except (OverflowError, OSError, ValueError):
        return 0


def parse(raw: bytes) -> tuple[str, list[tuple[str, str, str, str, int]]]:
    """(titre du flux, [(id, titre, lien, résumé, date)]). Ne lève pas : un flux
    illisible rend une liste vide."""
    try:
        root = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, ValueError):
        return "", []
    channel = root.find("channel")
    if channel is not None:
        return clean(_text(channel, "title")), [_rss(n) for n in channel.findall("item")]
    items = root.findall(f"{{{NS_RSS1}}}item")
    if items:
        return clean(_text(root.find(f"{{{NS_RSS1}}}channel"), f"{{{NS_RSS1}}}title")), [_rss(n, NS_RSS1) for n in items]
    if root.tag == f"{{{NS_ATOM}}}feed":
        return clean(_text(root, f"{{{NS_ATOM}}}title")), [_atom(n) for n in root.findall(f"{{{NS_ATOM}}}entry")]
    return "", []


def _rss(node: Any, ns: str = "") -> tuple[str, str, str, str, int]:
    p = f"{{{ns}}}" if ns else ""
    title = clean(_text(node, f"{p}title"))[:500] or phrase("feeds.untitled")
    link = _text(node, f"{p}link").strip()[:2000]
    guid = _text(node, f"{p}guid").strip()[:500]
    summary = clean(_text(node, f"{p}description") or _text(node, f"{{{NS_CONTENT}}}encoded"))
    date = _date(_text(node, f"{p}pubDate") or _text(node, f"{{{NS_DC}}}date"))
    return guid or link or title, title, link, summary[:SUMMARY_MAX], date


def _atom(node: Any) -> tuple[str, str, str, str, int]:
    title = clean(_text(node, f"{{{NS_ATOM}}}title"))[:500] or phrase("feeds.untitled")
    link = ""
    for cand in node.findall(f"{{{NS_ATOM}}}link"):
        if cand.get("rel", "alternate") == "alternate" or not link:
            link = (cand.get("href") or "").strip()[:2000]
    uid = _text(node, f"{{{NS_ATOM}}}id").strip()[:500]
    summary = clean(_text(node, f"{{{NS_ATOM}}}summary") or _text(node, f"{{{NS_ATOM}}}content"))
    date = _date(_text(node, f"{{{NS_ATOM}}}published") or _text(node, f"{{{NS_ATOM}}}updated"))
    return uid or link or title, title, link, summary[:SUMMARY_MAX], date


def _key(feed_url: str, uid: str) -> str:
    return hashlib.sha256(f"{feed_url}\n{uid}".encode()).hexdigest()[:24]


def _origin(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    return (parts.hostname or "").lower(), parts.port or (443 if parts.scheme == "https" else 80)


class HttpFeeds:
    """Le port ``feeds``. Le cache a une seule connexion, partagée sous ``_lock`` : chaque accès est une
    session courte (``begin`` pour écrire, validée à la sortie), jamais deux à la fois, jamais à travers un
    ``await``."""

    def __init__(self, feeds: Callable[[], Sequence[str]], cache: Path | Target, *, client: httpx.AsyncClient | None = None,
                 timeout_s: float = 20.0, poll_total_s: float = POLL_TOTAL_S,
                 resolve: Resolver | None = None, kept_us: int = KEPT_US,
                 keep_per_feed: int = KEEP_PER_FEED) -> None:
        self._feeds = feeds
        self._client = client
        self._timeout = timeout_s
        self._poll_total = poll_total_s
        self._resolve = resolve or system_resolve
        self._kept = kept_us
        self._keep_per_feed = keep_per_feed
        self._lock = threading.RLock()
        target = as_target(cache)
        target.ensure()
        self._engine = target.engine(shared=True)
        FEEDS.create_all(self._engine)
        self._session = sessionmaker(self._engine, expire_on_commit=False)

    def configured(self) -> bool:
        return bool(list(self._feeds()))

    # ── aller chercher ──
    async def _public(self, url: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """L'adresse à demander, vérifiée : l'hôte résolu, chacune de ses adresses publique ; la
        requête part vers l'adresse vérifiée (l'hôte reste dans ``Host`` et dans le SNI)."""
        parts = urlsplit(url)
        host, port = _origin(url)
        if not host:
            raise NotPublic("adresse sans hôte")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            ips: Sequence[str] = [str(literal)]
        else:
            try:
                ips = await self._resolve(host, port)
            except (OSError, UnicodeError) as exc:
                raise httpx.ConnectError(f"nom inconnu ({type(exc).__name__})") from None
        if not ips:
            raise httpx.ConnectError("nom inconnu")
        if not all(routable(ip) for ip in ips):
            raise NotPublic("cette adresse désigne une machine privée ou locale")
        ip = ips[0]
        netloc = (f"[{ip}]" if ":" in ip else ip) + (f":{parts.port}" if parts.port else "")
        headers = {"Host": parts.netloc.rsplit("@", 1)[-1]}
        extensions = {"sni_hostname": host} if parts.scheme == "https" and literal is None else {}
        return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), headers, extensions

    async def _get(self, url: str, *, public: bool) -> bytes:
        """Le corps d'une adresse, borné en taille. Les redirections sont suivies à la main, trois au
        plus, chacune revérifiée : ``public`` (un article) exige une machine publique à chaque saut ;
        sinon (un flux choisi par un opérateur), seule une redirection qui quitte l'hôte de départ
        doit mener à une machine publique."""
        client = self._client or httpx.AsyncClient(timeout=self._timeout,
                                                   headers={"User-Agent": "Mika/2 (lecteur de flux)"})
        start = _origin(url)
        current = url
        try:
            for hop in range(MAX_REDIRECTS + 1):
                scheme = urlsplit(current).scheme.lower()
                if scheme not in ("http", "https"):
                    raise NotPublic("seulement http(s)")
                if public or (hop and _origin(current) != start):
                    target, headers, extensions = await self._public(current)
                else:
                    target, headers, extensions = current, {}, {}
                async with client.stream("GET", target, headers=headers, extensions=extensions,
                                         follow_redirects=False) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location", "")
                        if not location:
                            raise httpx.HTTPStatusError("redirection sans adresse", request=resp.request,
                                                        response=resp)
                        current = urljoin(current, location)
                        continue
                    resp.raise_for_status()
                    chunks = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            break
                        chunks.append(chunk)
                    return b"".join(chunks)
            raise httpx.TooManyRedirects("trop de redirections")
        finally:
            if self._client is None:
                await client.aclose()

    async def poll(self, limit: int) -> list[Entry]:
        with self._lock, self._session() as s:
            n = int(s.scalar(select(func.coalesce(func.max(EntryRow.n), 0))) or 0)
        urls = list(self._feeds())
        loop = asyncio.get_running_loop()
        stop = loop.time() + self._poll_total
        start = int(time.time() * 1_000_000)
        for url in urls:
            now = int(time.time() * 1_000_000)
            left = stop - loop.time()
            if left <= 0:  # le relevé a assez duré : les flux restants attendent le suivant
                self._failed(url, now, "pas relevé : le relevé précédent a pris trop de temps")
                continue
            try:
                # un délai **total** par flux : un serveur qui égoutte sa réponse ne retient rien
                raw = await asyncio.wait_for(self._get(url, public=False), min(self._timeout, left))
            except httpx.HTTPStatusError as exc:  # un flux injoignable n'empêche pas les autres : on le note
                self._failed(url, now, f"le serveur répond {exc.response.status_code}")
                continue
            except (httpx.HTTPError, OSError, TimeoutError) as exc:
                self._failed(url, now, _why(exc))
                continue
            title, items = await asyncio.to_thread(parse, raw)  # hors de la boucle : un gros flux ne la fige pas
            with self._lock, self._session.begin() as s:
                feed = s.get(FeedRow, fit(url, URL_MAX))
                # le premier relevé n'hérite pas des archives ; ni celui d'un flux revenu après plus longtemps en
                # panne que le cache ne garde ses articles (ils reviendraient comme neufs)
                first = feed is None or not feed.polled or 0 < feed.ok_at < now - self._kept
                ordered = sorted(items, key=lambda it: -it[4])
                added = 0
                for i, (uid, t, link, summary, date) in enumerate(ordered):
                    n += 1
                    key = _key(url, uid)
                    # un flux sans titre est nommé par son adresse montrable (jamais son jeton)
                    inserted = insert_ignore(s, EntryRow, entry_values(
                        id=key, feed_url=url, feed=title or shown(url), title=t, link=link, summary=summary,
                        published=date, handed=first and i >= FIRST_POLL, n=n, seen_at=now))
                    if not inserted:  # son flux le liste encore : il reste dans le cache
                        s.execute(update(EntryRow).where(EntryRow.id == key).values(seen_at=now))
                    added += inserted
                self._note(s, url, now, ok=True, items=len(items), added=added,
                           error="" if items or title else "rien de lisible (ni RSS, ni Atom)")
        with self._lock, self._session.begin() as s:
            rows = s.execute(select(*_ENTRY).where(EntryRow.handed == false())
                             .order_by(EntryRow.published.desc(), EntryRow.n, EntryRow.id).limit(limit)).all()
            if rows:
                s.execute(update(EntryRow).where(EntryRow.id.in_([r[0] for r in rows])).values(handed=True))
            self._prune(s, start)
        return [Entry(*r) for r in rows]

    def _prune(self, s: Session, start: int) -> None:
        """Ce que le cache oublie : un article déjà rendu que son flux ne liste plus depuis ``kept_us``, ou
        au-delà des ``keep_per_feed`` derniers vus de son flux. Jamais un article pas encore rendu, ni un que ce
        relevé vient de voir dans son flux : effacé, il reviendrait comme neuf au relevé suivant.

        Le rang se lit d'abord, la suppression vient après (MariaDB refuse de supprimer d'une table en relisant
        la même dans la condition) ; les articles trop vieux, partis avant, étaient les derniers de leur flux : le
        rang des autres n'en bouge pas."""
        s.execute(delete(EntryRow).where(EntryRow.handed == true(), EntryRow.seen_at < start - self._kept))
        ranked = select(EntryRow.id, EntryRow.handed, EntryRow.seen_at, func.row_number().over(
            partition_by=EntryRow.feed_url, order_by=(EntryRow.seen_at.desc(), EntryRow.n.desc())).label("rank")
        ).subquery()
        beyond = s.scalars(select(ranked.c.id).where(ranked.c.rank > self._keep_per_feed, ranked.c.handed == true(),
                                                     ranked.c.seen_at < start)).all()
        if beyond:
            s.execute(delete(EntryRow).where(EntryRow.id.in_(beyond)))

    async def entry(self, entry_id: str) -> Entry | None:
        with self._lock, self._session() as s:
            row = s.execute(select(*_ENTRY).where(EntryRow.id == entry_id)).first()
        return Entry(*row) if row else None

    async def recent(self, limit: int) -> list[Entry]:
        return self.cached(limit)

    def cached(self, limit: int) -> list[Entry]:
        with self._lock, self._session() as s:
            rows = s.execute(select(*_ENTRY).order_by(*_NEWEST).limit(limit)).all()
        return [Entry(*r) for r in rows]

    def cached_count(self) -> int:
        with self._lock, self._session() as s:
            return int(s.scalar(select(func.count()).select_from(EntryRow)) or 0)

    @staticmethod
    def _matching(feed: str = "", text: str = "") -> list[Any]:
        """Les articles d'un flux et qui contiennent un texte, casse et accents ignorés : les deux côtés repliés
        (le texte cherché ici, la colonne à l'écriture), comparés par ``instr`` — pareil sur les deux moteurs, et
        ``%`` ou ``_`` n'y sont que des caractères."""
        where = []
        if folded := fold_text(feed):
            where.append(func.instr(EntryRow.feed_fold, folded) > 0)
        if folded := fold_text(text):
            where.append(func.instr(EntryRow.text_fold, folded) > 0)
        return where

    def entries_page(self, feed: str = "", text: str = "", page: int = 1, size: int = 25) -> Page[Entry]:
        where = self._matching(feed, text)
        with self._lock, self._session() as s:
            total = int(s.scalar(select(func.count()).select_from(EntryRow).where(*where)) or 0)
            page, size, offset = Page.bounds(total, page, size)
            rows = s.execute(select(*_ENTRY).where(*where).order_by(*_NEWEST).limit(size).offset(offset)).all()
        return Page(tuple(Entry(*r) for r in rows), total, page, size)

    def entry_count(self, feed: str = "", exclude: tuple[str, ...] = ()) -> int:
        where = self._matching(feed)
        if exclude:
            where.append(EntryRow.id.not_in(exclude))
        with self._lock, self._session() as s:
            return int(s.scalar(select(func.count()).select_from(EntryRow).where(*where)) or 0)

    def feed_counts(self) -> dict[str, int]:
        with self._lock, self._session() as s:
            rows = s.execute(select(EntryRow.feed, func.count()).group_by(EntryRow.feed)).all()
        return {feed: int(count) for feed, count in rows}

    def _note(self, s: Session, url: str, at: int, *, ok: bool = False, items: int = 0, added: int = 0,
              error: str = "") -> None:
        """Ce que ce relevé a donné pour un flux : un succès remet les échecs à zéro, un échec s'ajoute aux
        précédents."""
        key = fit(url, URL_MAX)
        feed = s.get(FeedRow, key)
        if feed is None:
            feed = FeedRow(url=key)
            s.add(feed)
        feed.attempted_at = at
        if ok:
            feed.polled, feed.ok_at, feed.error, feed.items, feed.added, feed.failures = True, at, error, items, added, 0
        else:
            feed.error = error[:300]
            feed.failures = (feed.failures or 0) + 1

    def _failed(self, url: str, at: int, error: str) -> None:
        with self._lock, self._session.begin() as s:
            self._note(s, url, at, error=error)

    @staticmethod
    def _title(s: Session, url: str) -> str:
        """Le titre d'un flux, s'il en a un (un nom de repli n'en est pas un) : celui de son dernier article
        arrivé (un flux qui se renomme est nommé comme aujourd'hui)."""
        name = s.scalar(select(EntryRow.feed).where(EntryRow.feed_url == fit(url, URL_MAX))
                        .order_by(EntryRow.n.desc(), EntryRow.id).limit(1))
        return name if name and name not in (url, shown(url)) else ""

    def health(self) -> list[dict[str, Any]]:
        """Pour chaque flux suivi : son titre, son adresse montrable, la dernière tentative, le dernier
        succès, l'erreur (vide : il va bien), les échecs d'affilée, les articles lus au dernier relevé, les
        nouveaux, et ce que le cache en garde. Lecture seule (l'inspecteur)."""
        out = []
        with self._lock, self._session() as s:
            for url in list(self._feeds()):
                feed = s.get(FeedRow, fit(url, URL_MAX))
                kept = s.scalar(select(func.count()).select_from(EntryRow)
                                .where(EntryRow.feed_url == fit(url, URL_MAX)))
                out.append({"title": self._title(s, url), "url": shown(url),
                            "attempted_at": feed.attempted_at if feed else 0, "ok_at": feed.ok_at if feed else 0,
                            "error": feed.error if feed else "", "failures": feed.failures if feed else 0,
                            "items": feed.items if feed else 0, "added": feed.added if feed else 0,
                            "kept": int(kept or 0)})
        return out

    def followed(self) -> list[tuple[str, str]]:
        with self._lock, self._session() as s:
            return [(self._title(s, url), shown(url)) for url in list(self._feeds())]

    async def article(self, entry_id: str) -> str:
        e = await self.entry(entry_id)
        if e is None or not e.link.startswith(("http://", "https://")):
            return ""
        try:
            raw = await asyncio.wait_for(self._get(e.link, public=True), self._timeout)
        except (httpx.HTTPError, OSError, TimeoutError):
            return ""
        return await asyncio.to_thread(html_text, raw.decode("utf-8", "replace"), skipped=ARTICLE_SKIPPED,
                                       limit=ARTICLE_MAX)

    def close(self) -> None:
        with self._lock:
            self._engine.dispose()
