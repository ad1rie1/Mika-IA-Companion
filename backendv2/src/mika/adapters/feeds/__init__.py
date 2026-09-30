"""Les flux réels : HTTP (httpx), RSS 2.0 / RDF / Atom en bibliothèque
standard, un cache SQLite à part.

- Chaque article n'est rendu qu'une fois (``poll``) ; au premier relevé d'un
  flux, seuls les plus récents (on n'hérite pas de trois ans d'archives).
- Un article se lit par son identifiant, depuis le cache : l'adresse vient
  du flux, jamais d'un texte. Les redirections sont suivies dans la limite
  de trois, la taille est bornée.
- La liste des flux est relue à chaque relevé.
- Chaque relevé d'un flux se note (tentative, succès, erreur, articles lus,
  nouveaux) : la console dit quel flux ne répond plus, et pourquoi.
"""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import html
import json
import re
import sqlite3
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from mika.ports.feeds import Entry
from mika.ports.paging import Page, fold_text

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_RSS1 = "http://purl.org/rss/1.0/"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
SUMMARY_MAX = 2000
ARTICLE_MAX = 12_000
FIRST_POLL = 5
MAX_BYTES = 5_000_000
#: ce qu'un relevé note de chaque flux (ajouté à un cache plus ancien)
HEALTH_COLUMNS = (("attempted_at", "INTEGER DEFAULT 0"), ("ok_at", "INTEGER DEFAULT 0"), ("error", "TEXT DEFAULT ''"),
                  ("failures", "INTEGER DEFAULT 0"), ("items", "INTEGER DEFAULT 0"), ("added", "INTEGER DEFAULT 0"))


def _why(exc: BaseException) -> str:
    """Une erreur de relevé en mots (jamais l'adresse : elle peut porter un jeton)."""
    if isinstance(exc, httpx.TimeoutException):
        return "trop long : le serveur ne répond pas à temps"
    if isinstance(exc, httpx.ConnectError):
        return "injoignable (nom inconnu ou connexion refusée)"
    if isinstance(exc, httpx.TooManyRedirects):
        return "trop de redirections"
    return f"erreur réseau ({type(exc).__name__})"


def clean(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    return " ".join(text.split())


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
    return int(dt.timestamp() * 1_000_000)


def parse(raw: bytes) -> tuple[str, list[tuple[str, str, str, str, int]]]:
    """(titre du flux, [(id, titre, lien, résumé, date)]). Ne lève pas : un flux
    illisible rend une liste vide."""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
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
    title = clean(_text(node, f"{p}title")) or "(sans titre)"
    link = _text(node, f"{p}link").strip()
    guid = _text(node, f"{p}guid").strip()
    summary = clean(_text(node, f"{p}description") or _text(node, f"{{{NS_CONTENT}}}encoded"))
    date = _date(_text(node, f"{p}pubDate") or _text(node, f"{{{NS_DC}}}date"))
    return guid or link or title, title, link, summary[:SUMMARY_MAX], date


def _atom(node: Any) -> tuple[str, str, str, str, int]:
    title = clean(_text(node, f"{{{NS_ATOM}}}title")) or "(sans titre)"
    link = ""
    for cand in node.findall(f"{{{NS_ATOM}}}link"):
        if cand.get("rel", "alternate") == "alternate" or not link:
            link = (cand.get("href") or "").strip()
    uid = _text(node, f"{{{NS_ATOM}}}id").strip()
    summary = clean(_text(node, f"{{{NS_ATOM}}}summary") or _text(node, f"{{{NS_ATOM}}}content"))
    date = _date(_text(node, f"{{{NS_ATOM}}}published") or _text(node, f"{{{NS_ATOM}}}updated"))
    return uid or link or title, title, link, summary[:SUMMARY_MAX], date


def _key(feed_url: str, uid: str) -> str:
    return hashlib.sha256(f"{feed_url}\n{uid}".encode()).hexdigest()[:24]


def shown(url: str) -> str:
    """Une adresse montrable : ni identifiants, ni valeurs de paramètres (un flux
    privé porte souvent son jeton dans l'adresse)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "(adresse illisible)"
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    query = "&".join(f"{k}=…" for k, _ in parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit((parts.scheme, host, parts.path, query, ""))[:300]


class HttpFeeds:
    def __init__(self, feeds: Callable[[], Sequence[str]], cache: Path, *, client: httpx.AsyncClient | None = None,
                 timeout_s: float = 20.0) -> None:
        self._feeds = feeds
        self._client = client
        self._timeout = timeout_s
        cache.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(cache), check_same_thread=False)
        self._db.create_function("fold", 1, lambda s: fold_text(s or ""), deterministic=True)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY, feed_url TEXT, feed TEXT, title TEXT,"
            " link TEXT, summary TEXT, published INTEGER, handed INTEGER DEFAULT 0, n INTEGER);"
            "CREATE TABLE IF NOT EXISTS feeds(url TEXT PRIMARY KEY, polled INTEGER DEFAULT 0);")
        known = {r[1] for r in self._db.execute("PRAGMA table_info(feeds)")}
        for column, kind in HEALTH_COLUMNS:  # un cache d'avant la santé des flux : on complète la table
            if column not in known:
                self._db.execute(f"ALTER TABLE feeds ADD COLUMN {column} {kind}")
        self._db.commit()

    def configured(self) -> bool:
        return bool(list(self._feeds()))

    async def _get(self, url: str) -> bytes:
        client = self._client or httpx.AsyncClient(follow_redirects=True, max_redirects=3, timeout=self._timeout,
                                                   headers={"User-Agent": "Mika/2 (lecteur de flux)"})
        try:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                chunks = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)
        finally:
            if self._client is None:
                await client.aclose()

    async def poll(self, limit: int) -> list[Entry]:
        n = self._db.execute("SELECT COALESCE(MAX(n), 0) FROM entries").fetchone()[0]
        for url in list(self._feeds()):
            now = int(time.time() * 1_000_000)
            try:
                raw = await self._get(url)
            except httpx.HTTPStatusError as exc:  # un flux injoignable n'empêche pas les autres : on le note
                self._note(url, now, error=f"le serveur répond {exc.response.status_code}")
                continue
            except (httpx.HTTPError, OSError) as exc:
                self._note(url, now, error=_why(exc))
                continue
            title, items = parse(raw)
            first = not self._db.execute("SELECT polled FROM feeds WHERE url=? AND polled=1", (url,)).fetchone()
            ordered = sorted(items, key=lambda it: -it[4])
            added = 0
            for i, (uid, t, link, summary, date) in enumerate(ordered):
                n += 1
                handed = 1 if first and i >= FIRST_POLL else 0  # le premier relevé n'hérite pas des archives
                added += self._db.execute("INSERT OR IGNORE INTO entries VALUES(?,?,?,?,?,?,?,?,?)",
                                          (_key(url, uid), url, title or url, t, link, summary, date, handed,
                                           n)).rowcount
            self._note(url, now, ok=True, items=len(items), added=added,
                       error="" if items or title else "rien de lisible (ni RSS, ni Atom)")
        rows = self._db.execute("SELECT id, feed, title, link, summary, published FROM entries WHERE handed=0 "
                                "ORDER BY published DESC, n LIMIT ?", (limit,)).fetchall()
        self._db.executemany("UPDATE entries SET handed=1 WHERE id=?", [(r[0],) for r in rows])
        self._db.commit()
        return [Entry(*r) for r in rows]

    async def entry(self, entry_id: str) -> Entry | None:
        rows = self._db.execute("SELECT id, feed, title, link, summary, published FROM entries WHERE id=?",
                                (entry_id,)).fetchall()
        return Entry(*rows[0]) if rows else None

    async def recent(self, limit: int) -> list[Entry]:
        return self.cached(limit)

    def cached(self, limit: int) -> list[Entry]:
        rows = self._db.execute("SELECT id, feed, title, link, summary, published FROM entries "
                                "ORDER BY published DESC, n DESC LIMIT ?", (limit,)).fetchall()
        return [Entry(*r) for r in rows]

    def cached_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def entries_page(self, feed: str = "", text: str = "", page: int = 1, size: int = 25) -> Page[Entry]:
        where = "instr(fold(feed),?)>0 AND instr(fold(title || ' ' || summary),?)>0"
        args = (fold_text(feed), fold_text(text))
        total = self._db.execute("SELECT COUNT(*) FROM entries WHERE " + where, args).fetchone()[0]
        page, size, offset = Page.bounds(total, page, size)
        rows = self._db.execute("SELECT id,feed,title,link,summary,published FROM entries WHERE " + where +
                                " ORDER BY published DESC,n DESC,id LIMIT ? OFFSET ?", (*args, size, offset))
        return Page(tuple(Entry(*r) for r in rows), total, page, size)

    def entry_count(self, feed: str = "", exclude: tuple[str, ...] = ()) -> int:
        return self._db.execute("SELECT COUNT(*) FROM entries WHERE instr(fold(feed),?)>0 "
                               "AND id NOT IN (SELECT value FROM json_each(?))", (fold_text(feed), json.dumps(exclude))).fetchone()[0]

    def feed_counts(self) -> dict[str, int]:
        return dict(self._db.execute("SELECT feed,COUNT(*) FROM entries GROUP BY feed"))

    def _note(self, url: str, at: int, *, ok: bool = False, items: int = 0, added: int = 0,
              error: str = "") -> None:
        if ok:
            self._db.execute("INSERT INTO feeds(url, polled, attempted_at, ok_at, error, items, added) "
                             "VALUES(?, 1, ?, ?, ?, ?, ?) ON CONFLICT(url) DO UPDATE SET polled=1, attempted_at=?, "
                             "ok_at=?, error=?, items=?, added=?, failures=0",
                             (url, at, at, error, items, added, at, at, error, items, added))
        else:
            self._db.execute("INSERT INTO feeds(url, polled, attempted_at, error, failures) VALUES(?, 0, ?, ?, 1) "
                             "ON CONFLICT(url) DO UPDATE SET attempted_at=?, error=?, failures=failures+1",
                             (url, at, error[:300], at, error[:300]))

    def health(self) -> list[dict[str, Any]]:
        """Pour chaque flux suivi : son titre, son adresse montrable, la dernière tentative, le dernier
        succès, l'erreur (vide : il va bien), les échecs d'affilée, les articles lus au dernier relevé, les
        nouveaux, et ce que le cache en garde. Lecture seule (l'inspecteur)."""
        out = []
        for url in list(self._feeds()):
            row = self._db.execute("SELECT attempted_at, ok_at, error, failures, items, added FROM feeds WHERE url=?",
                                   (url,)).fetchone()
            title = self._db.execute("SELECT feed FROM entries WHERE feed_url=? LIMIT 1", (url,)).fetchone()
            kept = self._db.execute("SELECT COUNT(*) FROM entries WHERE feed_url=?", (url,)).fetchone()[0]
            attempted, ok, error, failures, items, added = row if row else (0, 0, "", 0, 0, 0)
            out.append({"title": title[0] if title and title[0] != url else "", "url": shown(url),
                        "attempted_at": attempted or 0, "ok_at": ok or 0, "error": error or "",
                        "failures": failures or 0, "items": items or 0, "added": added or 0, "kept": kept})
        return out

    def followed(self) -> list[tuple[str, str]]:
        out = []
        for url in list(self._feeds()):
            row = self._db.execute("SELECT feed FROM entries WHERE feed_url=? LIMIT 1", (url,)).fetchone()
            title = row[0] if row and row[0] != url else ""
            out.append((title, shown(url)))
        return out

    async def article(self, entry_id: str) -> str:
        e = await self.entry(entry_id)
        if e is None or not e.link.startswith(("http://", "https://")):
            return ""
        try:
            raw = await asyncio.wait_for(self._get(e.link), self._timeout)
        except (httpx.HTTPError, OSError, TimeoutError):
            return ""
        body = re.sub(r"(?is)<(script|style|head|nav|footer)[^>]*>.*?</\1>", " ", raw.decode("utf-8", "replace"))
        text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))
        text = re.sub(r"\s*\n\s*", "\n", re.sub(r"[ \t]+", " ", text)).strip()
        return text[:ARTICLE_MAX]

    def close(self) -> None:
        self._db.close()
