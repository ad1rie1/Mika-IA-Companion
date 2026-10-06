"""Le cache de Teams (``teams.db``) : ce que l'extension a poussé (conversations, messages), ses brouillons et la
file de ce qui doit repartir.

- **Un message se désigne par sa référence**, attribuée ici (``ports.teams.message_ref``) : la même pour un même
  message, qu'il arrive par le réseau ou par la base locale du client, rejoué ou retouché (un message modifié dans
  Teams garde sa référence, son texte suit).
- **Ses messages à elle** (ceux de la personne qui s'occupe d'elle) sont gardés pour le fil, jamais rendus comme
  « reçus ». Ce sont eux qui disent qu'un brouillon posé est parti : un message de la personne dans la conversation,
  après qu'il a été posé, qui lui ressemble — retouché s'il n'est pas identique ; s'il ne lui ressemble pas, la
  personne a écrit autre chose, et le brouillon n'a pas servi.
- **Ce qui part est ce qui a été montré** : le texte final (signature comprise) est figé à la mise en file, avec
  son condensé ; l'extension relève ce texte-là.
"""

from __future__ import annotations

import difflib
import hashlib
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from mika.adapters.teams.config import TeamsConfig
from mika.ports.teams import (
    ACCEPTED,
    CONFLICT,
    DISCARDED,
    DRAFT,
    FAILED,
    GONE,
    MISSING,
    OPEN_STATES,
    PLACED,
    QUEUED,
    SEND,
    UNUSED,
    WRITTEN,
    Conversation,
    Draft,
    InboxBatch,
    Message,
    OutboxItem,
    Preview,
    Settled,
    Stored,
    Voice,
    message_ref,
    plain,
    to_fill,
)

SCHEMA = 1
#: au plus tant de messages gardés par conversation (les plus récents)
KEEP_PER_CONVERSATION = 1000
#: un message de la personne compte pour un brouillon posé s'il est écrit au plus tant avant qu'on le sache posé
#: (deux horloges : celle du navigateur, celle du serveur)
CLOCK_SLACK = 120 * 1_000_000
#: à partir de cette ressemblance, le message de la personne est le brouillon (retouché ou non)
SIMILAR = 0.5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, title TEXT, kind TEXT, last_at INTEGER);
CREATE TABLE IF NOT EXISTS messages(
  ref TEXT PRIMARY KEY, conversation TEXT NOT NULL, external_id TEXT NOT NULL, author TEXT, author_id TEXT,
  at INTEGER, text TEXT, own INTEGER, mentions_me INTEGER, received INTEGER, acked INTEGER);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation, at);
CREATE INDEX IF NOT EXISTS messages_pending ON messages(acked, own, at);
CREATE INDEX IF NOT EXISTS messages_author ON messages(author_id);
CREATE TABLE IF NOT EXISTS drafts(
  id TEXT PRIMARY KEY, conversation TEXT, body TEXT, reply_to TEXT, author TEXT, created INTEGER, updated INTEGER,
  state TEXT, mode TEXT, digest TEXT, final TEXT, expires_at INTEGER, placed_at INTEGER, sent_at INTEGER,
  sent_text TEXT, edited INTEGER, edited_by TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS drafts_open ON drafts(state, conversation);
"""
_MESSAGE = ("ref", "conversation", "author", "author_id", "at", "text", "own", "mentions_me")
_DRAFT = ("id", "conversation", "body", "reply_to", "author", "created", "updated", "state", "mode", "digest",
          "final", "expires_at", "placed_at", "sent_at", "sent_text", "edited", "edited_by", "reason")


def _now_us() -> int:
    return time.time_ns() // 1000


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, plain(a), plain(b)).ratio()


class TeamsStore:
    """Le port ``teams`` : le cache et la file d'envoi. ``config`` est relue à chaque usage (la signature, le nom)."""

    def __init__(self, config: Callable[[], TeamsConfig], path: Path, *,
                 now: Callable[[], int] = _now_us) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._config = config
        self._now = now
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.execute("INSERT OR IGNORE INTO meta VALUES('schema', ?)", (str(SCHEMA),))
            self._db.commit()

    # ── ce qu'on sait ──
    def _meta(self, key: str) -> str:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (key, value))

    def configured(self) -> bool:
        return bool(self._meta("last_batch"))

    def last_batch(self) -> int:
        """Le dernier lot poussé par l'extension (µs, 0 : jamais)."""
        return int(self._meta("last_batch") or 0)

    def owner(self) -> tuple[str, str]:
        return self._meta("self_id"), self._meta("self_name")

    def voice(self) -> Voice:
        return self._config().voice(fallback_name=self._meta("self_name"))

    # ── ce que pousse l'extension ──
    def store_batch(self, batch: InboxBatch, now: int) -> Stored:
        new = known = 0
        replied: list[str] = []
        settled: list[Settled] = []
        with self._lock:
            if batch.self_id:
                self._set_meta("self_id", batch.self_id)
            if batch.self_name:
                self._set_meta("self_name", batch.self_name)
            self._set_meta("last_batch", str(now))
            for c in batch.conversations:
                self._db.execute("INSERT INTO conversations VALUES(?, ?, ?, 0) ON CONFLICT(id) DO UPDATE SET "
                                 "title=CASE WHEN excluded.title<>'' THEN excluded.title ELSE title END, "
                                 "kind=CASE WHEN excluded.kind<>'other' THEN excluded.kind ELSE kind END",
                                 (c.id, c.title, c.kind))
            for m in sorted(batch.messages, key=lambda m: m.time_ms):
                ref = message_ref(m.conversation, m.id)
                at = m.time_ms * 1000
                row = self._db.execute("SELECT text FROM messages WHERE ref=?", (ref,)).fetchone()
                if row is not None:  # déjà connu (rejoué, ou retouché dans Teams : son texte suit)
                    known += 1
                    if row[0] != m.text:
                        self._db.execute("UPDATE messages SET text=? WHERE ref=?", (m.text, ref))
                    continue
                new += 1
                self._db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 (ref, m.conversation, m.id, m.author, m.author_id, at, m.text, int(m.own),
                                  int(m.mentions_me), now, int(m.own)))
                self._db.execute("INSERT OR IGNORE INTO conversations VALUES(?, '', 'other', 0)", (m.conversation,))
                self._db.execute("UPDATE conversations SET last_at=MAX(last_at, ?) WHERE id=?", (at, m.conversation))
                if m.own:
                    if m.conversation not in replied:
                        replied.append(m.conversation)
                    settled.extend(self._answered_by_owner(m.conversation, at, m.text, now))
            if new:
                self._prune()
            self._db.commit()
        return Stored(new=new, known=known, replied=tuple(replied), settled=tuple(settled))

    def _answered_by_owner(self, conversation: str, at: int, text: str, now: int) -> list[Settled]:
        """La personne a écrit dans cette conversation : un brouillon posé (ou en file pour être posé) qui ressemble
        à ce qu'elle a écrit est parti ; sinon, il n'a pas servi. Un envoi encore en file (validation, autonome)
        n'est réglé que s'il lui ressemble (l'extension l'a envoyé, et son accusé s'est perdu)."""
        out: list[Settled] = []
        rows = self._db.execute(f"SELECT {', '.join(_DRAFT)} FROM drafts WHERE conversation=? AND state IN (?, ?)",
                                (conversation, QUEUED, PLACED)).fetchall()
        for d in (self._draft(r) for r in rows):
            since = (d.placed_at or d.updated) - CLOCK_SLACK
            if at < since:
                continue
            similar = max(_ratio(text, d.final), _ratio(text, d.body)) >= SIMILAR
            if similar:
                edited = plain(text) not in (plain(d.final), plain(d.body))
                self._write(replace(d, state=GONE, sent_at=now, sent_text=text, edited=edited))
                out.append(Settled(d.id, GONE, edited=edited))
            elif d.mode == DRAFT:
                reason = "tu as écrit autre chose" if d.state == PLACED else "tu as répondu toi-même"
                self._write(replace(d, state=UNUSED, reason=reason))
                out.append(Settled(d.id, UNUSED, reason=reason))
        return out

    def _prune(self) -> None:
        self._db.execute(
            "DELETE FROM messages WHERE rowid IN (SELECT rowid FROM (SELECT rowid, ROW_NUMBER() OVER "
            "(PARTITION BY conversation ORDER BY at DESC) AS n FROM messages) WHERE n > ?)",
            (KEEP_PER_CONVERSATION,))

    # ── ce qu'elle remarque ──
    @staticmethod
    def _message(r: tuple[Any, ...]) -> Message:
        d = dict(zip(_MESSAGE, r, strict=True))
        return Message(ref=d["ref"], conversation=d["conversation"], author=d["author"] or "",
                       author_id=d["author_id"] or "", at=int(d["at"] or 0), text=d["text"] or "",
                       own=bool(d["own"]), mentions_me=bool(d["mentions_me"]))

    async def fetch_new(self, limit: int) -> list[Message]:
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_MESSAGE)} FROM messages WHERE acked=0 AND own=0 "
                                    "ORDER BY at, rowid LIMIT ?", (max(0, limit),)).fetchall()
        return [self._message(r) for r in rows]

    def ack(self, refs: Sequence[str]) -> None:
        if not refs:
            return
        with self._lock:
            self._db.executemany("UPDATE messages SET acked=1 WHERE ref=?", [(r,) for r in refs])
            self._db.commit()

    def message(self, ref: str) -> Message | None:
        with self._lock:
            row = self._db.execute(f"SELECT {', '.join(_MESSAGE)} FROM messages WHERE ref=?", (ref,)).fetchone()
        return self._message(row) if row else None

    def thread(self, conversation: str, limit: int, *, before: int = 0) -> list[Message]:
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_MESSAGE)} FROM messages WHERE conversation=? AND "
                                    "(?=0 OR at<?) ORDER BY at DESC, rowid DESC LIMIT ?",
                                    (conversation, before, before, max(0, limit))).fetchall()
        return [self._message(r) for r in reversed(rows)]

    def conversation(self, conversation: str) -> Conversation | None:
        with self._lock:
            row = self._db.execute("SELECT c.id, c.title, c.kind, c.last_at, (SELECT COUNT(*) FROM messages m "
                                   "WHERE m.conversation=c.id) FROM conversations c WHERE c.id=?",
                                   (conversation,)).fetchone()
        return Conversation(row[0], row[1] or "", row[2] or "other", int(row[3] or 0), int(row[4] or 0)) \
            if row else None

    def conversations(self, limit: int, *, text: str = "") -> list[Conversation]:
        like = f"%{text.strip().lower()}%" if text.strip() else ""
        with self._lock:
            rows = self._db.execute("SELECT c.id, c.title, c.kind, c.last_at, (SELECT COUNT(*) FROM messages m "
                                    "WHERE m.conversation=c.id) FROM conversations c WHERE c.last_at>0 AND "
                                    "(?='' OR lower(c.title) LIKE ? OR lower(c.id) LIKE ?) "
                                    "ORDER BY c.last_at DESC LIMIT ?", (like, like, like, max(0, limit))).fetchall()
        return [Conversation(r[0], r[1] or "", r[2] or "other", int(r[3] or 0), int(r[4] or 0)) for r in rows]

    def title(self, conversation: str) -> str:
        """Le nom d'une conversation : celui de Teams, sinon (un tête-à-tête) l'autre personne."""
        found = self.conversation(conversation)
        if found is not None and found.title:
            return found.title
        with self._lock:
            row = self._db.execute("SELECT author FROM messages WHERE conversation=? AND own=0 AND author<>'' "
                                   "ORDER BY at DESC LIMIT 1", (conversation,)).fetchone()
        return str(row[0]) if row else ""

    # ── ses brouillons ──
    @staticmethod
    def _draft(r: tuple[Any, ...]) -> Draft:
        d = dict(zip(_DRAFT, r, strict=True))
        return Draft(id=d["id"], conversation=d["conversation"] or "", body=d["body"] or "",
                     reply_to=d["reply_to"] or "", author=d["author"] or "", created=int(d["created"] or 0),
                     updated=int(d["updated"] or 0), state=d["state"] or WRITTEN, mode=d["mode"] or "",
                     digest=d["digest"] or "", final=d["final"] or "", expires_at=int(d["expires_at"] or 0),
                     placed_at=int(d["placed_at"] or 0), sent_at=int(d["sent_at"] or 0),
                     sent_text=d["sent_text"] or "", edited=bool(d["edited"]), edited_by=d["edited_by"] or "",
                     reason=d["reason"] or "")

    def _write(self, d: Draft) -> Draft:
        self._db.execute(f"INSERT OR REPLACE INTO drafts({', '.join(_DRAFT)}) VALUES({', '.join('?' * len(_DRAFT))})",
                         (d.id, d.conversation, d.body, d.reply_to, d.author, d.created, d.updated, d.state, d.mode,
                          d.digest, d.final, d.expires_at, d.placed_at, d.sent_at, d.sent_text, int(d.edited),
                          d.edited_by, d.reason))
        return d

    def save_draft(self, d: Draft) -> Draft:
        now = self._now()
        if not d.id:
            d = replace(d, id=f"t{uuid.uuid4().hex[:12]}", created=now)
        with self._lock:
            d = self._write(replace(d, updated=now))
            self._db.commit()
        return d

    def draft(self, draft_id: str) -> Draft | None:
        with self._lock:
            row = self._db.execute(f"SELECT {', '.join(_DRAFT)} FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return self._draft(row) if row else None

    def drafts(self, limit: int, *, state: str = "") -> list[Draft]:
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_DRAFT)} FROM drafts WHERE ?='' OR state=? "
                                    "ORDER BY updated DESC, rowid DESC LIMIT ?", (state, state, max(0, limit))).fetchall()
        return [self._draft(r) for r in rows]

    def discard_draft(self, draft_id: str) -> None:
        with self._lock:
            found = self.draft(draft_id)
            if found is not None and found.state == WRITTEN:
                self._write(replace(found, state=DISCARDED, updated=self._now()))
                self._db.commit()

    def _final(self, d: Draft) -> str:
        signature = self.voice().signature
        return f"{d.body.strip()}\n\n{signature}" if signature else d.body.strip()

    def preview(self, draft_id: str) -> Preview | None:
        d = self.draft(draft_id)
        if d is None:
            return None
        text = d.final if d.state != WRITTEN and d.final else self._final(d)
        digest = hashlib.sha256(f"{d.conversation}\n{text}".encode()).hexdigest()[:32]
        blocked = ""
        if d.state != WRITTEN:
            blocked = "il n'est plus à envoyer (déjà en file, parti ou abandonné)"
        elif to_fill(d.body):
            blocked = "il reste des passages [À COMPLÉTER] à remplir"
        elif not d.body.strip():
            blocked = "il est vide"
        return Preview(d.conversation, self.title(d.conversation), text, digest, blocked)

    # ── la file ──
    def enqueue(self, draft_id: str, *, mode: str, digest: str, expires_at: int, now: int) -> str:
        with self._lock:
            d = self.draft(draft_id)
            if d is None:
                return "ce brouillon n'existe plus"
            if d.state in (QUEUED, PLACED, GONE) and d.digest == digest:
                return ""  # déjà fait : rejoué après un arrêt
            shown = self.preview(draft_id)
            if shown is None or d.state != WRITTEN:
                return "il n'est plus à envoyer"
            if digest and shown.digest != digest:
                return "il a changé depuis qu'on l'a montré"
            if shown.blocked and (mode == SEND or not to_fill(d.body)):
                return shown.blocked  # posé dans Teams, un « à compléter » se remplit ; envoyé, jamais
            self._write(replace(d, state=QUEUED, mode=mode, digest=shown.digest, final=shown.text,
                                expires_at=expires_at, updated=now))
            self._db.commit()
        return ""

    def outbox(self, now: int) -> list[OutboxItem]:
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_DRAFT)} FROM drafts WHERE state IN (?, ?) "
                                    "ORDER BY updated, rowid", (QUEUED, PLACED)).fetchall()
        out = []
        for d in (self._draft(r) for r in rows):
            if d.expires_at and d.expires_at <= now:
                continue
            found = self.conversation(d.conversation)
            out.append(OutboxItem(d.id, d.conversation, self.title(d.conversation),
                                  found.kind if found is not None else "other", d.mode,
                                  "placed" if d.state == PLACED else "queued", d.final, d.updated // 1000,
                                  d.expires_at // 1000))
        return out

    def settle(self, draft_id: str, result: str, *, now: int, text: str = "", reason: str = "") \
            -> tuple[str, Settled | None]:
        with self._lock:
            d = self.draft(draft_id)
            if d is None or (d.state not in (*OPEN_STATES, GONE, FAILED, UNUSED)):
                return MISSING, None
            if result == "placed":
                if d.state == PLACED:
                    return ACCEPTED, None
                if d.state != QUEUED or d.mode != DRAFT:
                    return CONFLICT, None
                done = Settled(d.id, PLACED)
                self._write(replace(d, state=PLACED, placed_at=now))
            elif result == "sent":
                if d.state == GONE:
                    return ACCEPTED, None
                if d.state not in OPEN_STATES:
                    return CONFLICT, None
                edited = bool(text) and plain(text) not in (plain(d.final), plain(d.body))
                done = Settled(d.id, GONE, edited=edited)
                self._write(replace(d, state=GONE, sent_at=now, sent_text=text or d.final, edited=edited))
            elif result == "failed":
                if d.state == FAILED:
                    return ACCEPTED, None
                if d.state not in OPEN_STATES:
                    return CONFLICT, None
                why = reason.strip()[:300] or "l'extension n'a pas pu le faire"
                done = Settled(d.id, FAILED, reason=why)
                self._write(replace(d, state=FAILED, reason=why))
            elif result == "expired":
                if d.state not in OPEN_STATES:
                    return ACCEPTED, None
                if d.mode == SEND:
                    done = Settled(d.id, FAILED, reason="jamais envoyé : l'extension ne l'a pas relevé à temps")
                    self._write(replace(d, state=FAILED, reason=done.reason))
                else:
                    done = Settled(d.id, UNUSED, reason="personne ne l'a envoyé à temps")
                    self._write(replace(d, state=UNUSED, reason=done.reason))
            else:
                return CONFLICT, None
            self._db.commit()
        return ACCEPTED, done

    # ── l'oubli ──
    async def forget(self, subject: str) -> int:
        """Oublier quelqu'un (``teams:<identifiant>``) : ses messages, et ses tête-à-tête entiers (ce qui y a été
        écrit, les brouillons qui y répondaient, la conversation elle-même)."""
        if not subject.startswith("teams:"):
            return 0
        author = subject[len("teams:"):].strip().lower()
        if not author:
            return 0
        with self._lock:
            convs = [r[0] for r in self._db.execute(
                "SELECT DISTINCT m.conversation FROM messages m JOIN conversations c ON c.id=m.conversation "
                "WHERE lower(m.author_id)=? AND c.kind='dm'", (author,)).fetchall()]
            n = self._db.execute("DELETE FROM messages WHERE lower(author_id)=?", (author,)).rowcount
            for conv in convs:
                n += self._db.execute("DELETE FROM messages WHERE conversation=?", (conv,)).rowcount
                n += self._db.execute("DELETE FROM drafts WHERE conversation=?", (conv,)).rowcount
                self._db.execute("DELETE FROM conversations WHERE id=?", (conv,))
            self._db.commit()
        return n

    def close(self) -> None:
        with self._lock:
            self._db.close()
