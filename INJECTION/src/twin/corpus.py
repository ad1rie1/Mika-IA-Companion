"""``travail/corpus.db`` : toutes les archives, normalisées, dans une seule base SQLite.

- ``sources`` : un fichier lu (son empreinte : relire un fichier inchangé ne fait rien,
  un fichier modifié remplace ce qu'il avait apporté) ;
- ``participants`` : quelqu'un dans un canal, avec l'indice « c'est elle » de son lecteur ;
  ``person`` le rattache à une personne (étape « personnes ») ;
- ``conversations`` / ``members`` : un fil, unique par (canal, clé) — un fil exporté en
  plusieurs fichiers se recoud ici ;
- ``messages`` et ``documents`` : le texte, son ``Temps`` (``t_*``) et son rang dans la
  source ; ``fingerprint`` rend la relecture d'exports qui se chevauchent sans doublon ;
- ``conflicts`` : les dates qui contredisent l'ordre de leur source, à revoir ;
- ``fts_messages`` / ``fts_documents`` : la recherche plein texte (outil MCP ``corpus_chercher``).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from twin.records import Author, Conversation, Document, Item, Message
from twin.timing import Temps

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, sha256 TEXT NOT NULL, reader TEXT NOT NULL,
    reader_version INTEGER NOT NULL, size INTEGER, ingested_at TEXT, messages INTEGER DEFAULT 0,
    documents INTEGER DEFAULT 0, warnings TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY, channel TEXT NOT NULL, key TEXT NOT NULL, name TEXT DEFAULT '',
    address TEXT DEFAULT '', aliases TEXT DEFAULT '[]', me_hint INTEGER, me_reason TEXT DEFAULT '',
    person INTEGER, manual INTEGER DEFAULT 0, UNIQUE (channel, key)
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY, channel TEXT NOT NULL, key TEXT NOT NULL, title TEXT DEFAULT '',
    is_group INTEGER DEFAULT 0, UNIQUE (channel, key)
);
CREATE TABLE IF NOT EXISTS members (
    conversation INTEGER NOT NULL, participant INTEGER NOT NULL, PRIMARY KEY (conversation, participant)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, source INTEGER NOT NULL, conversation INTEGER NOT NULL, author INTEGER,
    rank INTEGER NOT NULL, native_key TEXT DEFAULT '', reply_to TEXT DEFAULT '', kind TEXT DEFAULT 'message',
    subject TEXT DEFAULT '', text TEXT NOT NULL, attachments TEXT DEFAULT '[]',
    t_start INTEGER, t_end INTEGER, t_point INTEGER, t_precision TEXT NOT NULL, t_origin TEXT NOT NULL,
    fingerprint TEXT NOT NULL, duplicate_of INTEGER, session INTEGER, UNIQUE (conversation, fingerprint)
);
CREATE INDEX IF NOT EXISTS messages_by_time ON messages (conversation, t_point, rank);
CREATE INDEX IF NOT EXISTS messages_by_source ON messages (source, rank);
CREATE INDEX IF NOT EXISTS messages_by_author ON messages (author);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY, source INTEGER NOT NULL, channel TEXT NOT NULL, key TEXT NOT NULL,
    kind TEXT NOT NULL, title TEXT DEFAULT '', author INTEGER, path TEXT DEFAULT '', rank INTEGER NOT NULL,
    text TEXT NOT NULL, t_start INTEGER, t_end INTEGER, t_point INTEGER, t_precision TEXT NOT NULL,
    t_origin TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS documents_by_source ON documents (source, rank);
CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, handle TEXT UNIQUE NOT NULL, relation TEXT DEFAULT '',
    is_me INTEGER DEFAULT 0, ignored INTEGER DEFAULT 0, review TEXT DEFAULT '', manual INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, conversation INTEGER, document INTEGER, n_messages INTEGER NOT NULL,
    n_her INTEGER NOT NULL, chars INTEGER NOT NULL, persons TEXT DEFAULT '[]',
    t_start INTEGER, t_end INTEGER, t_point INTEGER, t_precision TEXT NOT NULL, t_origin TEXT NOT NULL,
    significance REAL NOT NULL, tier TEXT DEFAULT '', status TEXT DEFAULT 'todo'
);
CREATE INDEX IF NOT EXISTS sessions_by_time ON sessions (t_point);
CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY, table_name TEXT NOT NULL, ref INTEGER NOT NULL, reason TEXT NOT NULL,
    resolved INTEGER DEFAULT 0, UNIQUE (table_name, ref)
);
-- ce que la main (ou Claude Code par le MCP) a décidé : survit à la relecture d'une source
CREATE TABLE IF NOT EXISTS decisions (
    kind TEXT NOT NULL, ref TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (kind, ref)
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_messages USING fts5(
    text, subject, content='messages', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(
    title, text, content='documents', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
"""


def _ref(ref: str) -> tuple[str, str]:
    """« whatsapp:Julie Martin » → (canal, clé) ; la clé peut contenir des deux-points (« mail:sujet:… »)."""
    channel, _, key = ref.partition(":")
    return channel, key


def fingerprint(*parts: object) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class SourceStats:
    messages: int = 0
    documents: int = 0
    duplicates: int = 0
    forgotten: int = 0
    warnings: list[str] = field(default_factory=list)


class Corpus:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.db.commit()

    def _migrate(self) -> None:
        """Les colonnes ajoutées après coup, pour une base créée par une version précédente."""
        added = {"participants": [("manual", "INTEGER DEFAULT 0")], "messages": [("session", "INTEGER")]}
        for table, columns in added.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self.db.execute("CREATE INDEX IF NOT EXISTS messages_by_session ON messages (session, t_point, rank)")

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    # -- sources ------------------------------------------------------------------------------

    def source_unchanged(self, path: str, sha: str, reader: str, version: int) -> bool:
        row = self.db.execute("SELECT sha256, reader, reader_version FROM sources WHERE path = ?", (path,)).fetchone()
        return row is not None and (row["sha256"], row["reader"], row["reader_version"]) == (sha, reader, version)

    def source_read(self, path: str) -> bool:
        """Une séance de cette source a-t-elle déjà été lue (ou planifiée hors « à faire ») ? Alors on ne la relit
        pas : ses messages perdraient leurs identifiants, leurs séances et les annotations qui y renvoient."""
        row = self.db.execute("SELECT id FROM sources WHERE path = ?", (path,)).fetchone()
        if row is None:
            return False
        hit = self.db.execute(
            "SELECT 1 FROM messages m JOIN sessions s ON s.id = m.session WHERE m.source = ? AND s.status != 'todo' "
            "UNION SELECT 1 FROM documents d JOIN sessions s ON s.document = d.id WHERE d.source = ? "
            "AND s.status != 'todo' LIMIT 1", (row["id"], row["id"])).fetchone()
        return hit is not None

    def begin_source(self, path: str, sha: str, reader: str, version: int, size: int, now: str) -> int:
        """Ouvre (ou rouvre) une source : ce qu'elle avait apporté est retiré d'abord."""
        old = self.db.execute("SELECT id FROM sources WHERE path = ?", (path,)).fetchone()
        if old is not None:
            self.db.execute("DELETE FROM messages WHERE source = ?", (old["id"],))
            self.db.execute("DELETE FROM documents WHERE source = ?", (old["id"],))
            self.db.execute("DELETE FROM sources WHERE id = ?", (old["id"],))
        cur = self.db.execute(
            "INSERT INTO sources (path, sha256, reader, reader_version, size, ingested_at) VALUES (?, ?, ?, ?, ?, ?)",
            (path, sha, reader, version, size, now))
        return int(cur.lastrowid or 0)

    def end_source(self, source: int, stats: SourceStats) -> None:
        self.db.execute("UPDATE sources SET messages = ?, documents = ?, warnings = ? WHERE id = ?",
                        (stats.messages, stats.documents, json.dumps(stats.warnings, ensure_ascii=False), source))

    # -- écriture des enregistrements ---------------------------------------------------------

    def add_items(self, source: int, items: Iterable[Item], stats: SourceStats) -> None:
        authors: dict[tuple[str, str], int] = {}
        convs: dict[tuple[str, str], int] = {}
        #: deux « ok » de la même personne dans la même minute sont deux messages : leur rang d'occurrence dans la
        #: source entre dans l'empreinte (deux exports qui se chevauchent les numérotent pareil : ils restent fusionnés)
        self._seen: dict[tuple[int, int | None, object, str], int] = {}
        # une personne oubliée (``jumeau oublier``) ne revient pas par une source relue : ni elle, ni ses messages,
        # ni ses tête-à-tête
        forgotten = self.forgotten()
        silent = {_ref(r.removeprefix("conversation:")) for r in forgotten if r.startswith("conversation:")}
        gone = {_ref(r) for r in forgotten if not r.startswith("conversation:")}
        for item in items:
            if isinstance(item, Author) and (item.channel, item.key) in gone:
                continue
            if isinstance(item, Conversation) and not item.group and any((item.channel, k) in gone for k in item.members):
                silent.add((item.channel, item.key))
            if isinstance(item, Message) and ((item.channel, item.author) in gone
                                              or (item.channel, item.conversation) in silent):
                stats.forgotten += 1
                continue
            if isinstance(item, Author):
                authors[(item.channel, item.key)] = self._author(item)
            elif isinstance(item, Conversation):
                if (item.channel, item.key) in silent:
                    continue
                cid = self._conversation(item)
                convs[(item.channel, item.key)] = cid
                for key in (k for k in item.members if (item.channel, k) not in gone):
                    pid = authors.get((item.channel, key)) or self._author(Author(item.channel, key))
                    authors[(item.channel, key)] = pid
                    self.db.execute("INSERT OR IGNORE INTO members VALUES (?, ?)", (cid, pid))
            elif isinstance(item, Message):
                cid = convs.get((item.channel, item.conversation)) or self._conversation(
                    Conversation(item.channel, item.conversation))
                convs[(item.channel, item.conversation)] = cid
                pid = None
                if item.author:
                    pid = authors.get((item.channel, item.author)) or self._author(Author(item.channel, item.author))
                    authors[(item.channel, item.author)] = pid
                    self.db.execute("INSERT OR IGNORE INTO members VALUES (?, ?)", (cid, pid))
                if self._message(source, cid, pid, item):
                    stats.messages += 1
                else:
                    stats.duplicates += 1
            elif isinstance(item, Document):
                pid = authors.get((item.channel, item.author)) or self._author(Author(item.channel, item.author))
                authors[(item.channel, item.author)] = pid
                if self._document(source, pid, item):
                    stats.documents += 1
                else:
                    stats.duplicates += 1

    def forgotten(self) -> set[str]:
        """Les références oubliées : « canal:clé » d'un participant, « conversation:canal:clé » d'un tête-à-tête."""
        return {r["ref"] for r in self.db.execute("SELECT ref FROM decisions WHERE kind = 'oubli'")}

    def _author(self, a: Author) -> int:
        row = self.db.execute("SELECT id, name, address, aliases, me_hint FROM participants WHERE channel = ? AND key = ?",
                              (a.channel, a.key)).fetchone()
        if row is None:
            cur = self.db.execute(
                "INSERT INTO participants (channel, key, name, address, aliases, me_hint, me_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (a.channel, a.key, a.name, a.address, json.dumps(sorted(a.aliases), ensure_ascii=False),
                 None if a.me is None else int(a.me), a.me_reason))
            return int(cur.lastrowid or 0)
        aliases = sorted(set(json.loads(row["aliases"])) | set(a.aliases))
        name = row["name"] or a.name
        address = row["address"] or a.address
        me_hint, me_reason = row["me_hint"], None
        if a.me is not None and me_hint is None:
            me_hint, me_reason = int(a.me), a.me_reason
        self.db.execute("UPDATE participants SET name = ?, address = ?, aliases = ?, me_hint = ?, "
                        "me_reason = COALESCE(?, me_reason) WHERE id = ?",
                        (name, address, json.dumps(aliases, ensure_ascii=False), me_hint, me_reason, row["id"]))
        return int(row["id"])

    def _conversation(self, c: Conversation) -> int:
        row = self.db.execute("SELECT id FROM conversations WHERE channel = ? AND key = ?", (c.channel, c.key)).fetchone()
        if row is None:
            cur = self.db.execute("INSERT INTO conversations (channel, key, title, is_group) VALUES (?, ?, ?, ?)",
                                  (c.channel, c.key, c.title, int(c.group)))
            return int(cur.lastrowid or 0)
        if c.title or c.group:
            self.db.execute("UPDATE conversations SET title = COALESCE(NULLIF(?, ''), title), "
                            "is_group = MAX(is_group, ?) WHERE id = ?", (c.title, int(c.group), row["id"]))
        return int(row["id"])

    def _message(self, source: int, conv: int, author: int | None, m: Message) -> bool:
        t = m.temps
        # une date exacte identifie le message ; sans elle, son rang dans la source
        where = t.point if t.precision.value == "exacte" else f"rang:{m.rank}"
        same = (conv, author, where, m.text)
        occurrence = self._seen.get(same, 0)
        self._seen[same] = occurrence + 1
        fp = fingerprint(m.native_key or "", author, where, m.text, occurrence or "")
        cur = self.db.execute(
            "INSERT OR IGNORE INTO messages (source, conversation, author, rank, native_key, reply_to, kind, subject, "
            "text, attachments, t_start, t_end, t_point, t_precision, t_origin, fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, conv, author, m.rank, m.native_key, m.reply_to, m.kind, m.subject, m.text,
             json.dumps([a.name for a in m.attachments], ensure_ascii=False), *t.as_row(), fp))
        return cur.rowcount > 0

    def _document(self, source: int, author: int, d: Document) -> bool:
        fp = fingerprint(d.channel, d.key, d.text)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO documents (source, channel, key, kind, title, author, path, rank, text, "
            "t_start, t_end, t_point, t_precision, t_origin, fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, d.channel, d.key, d.kind, d.title, author, d.path, d.rank, d.text, *d.temps.as_row(), fp))
        return cur.rowcount > 0

    def rebuild_search(self) -> None:
        self.db.execute("INSERT INTO fts_messages (fts_messages) VALUES ('rebuild')")
        self.db.execute("INSERT INTO fts_documents (fts_documents) VALUES ('rebuild')")
        self.db.commit()

    # -- lecture ------------------------------------------------------------------------------

    def temps_of(self, row: sqlite3.Row) -> Temps:
        return Temps.from_row(row["t_start"], row["t_end"], row["t_point"], row["t_precision"], row["t_origin"])

    def stats(self) -> dict[str, object]:
        q = self.db.execute
        by_reader = {r["reader"]: (r["n"], r["m"], r["d"]) for r in q(
            "SELECT reader, COUNT(*) n, SUM(messages) m, SUM(documents) d FROM sources GROUP BY reader")}
        precision = {r["t_precision"]: r["n"] for r in q(
            "SELECT t_precision, COUNT(*) n FROM (SELECT t_precision FROM messages UNION ALL "
            "SELECT t_precision FROM documents) GROUP BY t_precision")}
        span = q("SELECT MIN(t_point) lo, MAX(t_point) hi FROM (SELECT t_point FROM messages UNION ALL "
                 "SELECT t_point FROM documents)").fetchone()
        channels = {r["channel"]: r["n"] for r in q(
            "SELECT c.channel, COUNT(*) n FROM messages m JOIN conversations c ON c.id = m.conversation "
            "GROUP BY c.channel")}
        return {
            "sources": by_reader,
            "messages": q("SELECT COUNT(*) FROM messages").fetchone()[0],
            "documents": q("SELECT COUNT(*) FROM documents").fetchone()[0],
            "conversations": q("SELECT COUNT(*) FROM conversations").fetchone()[0],
            "participants": q("SELECT COUNT(*) FROM participants").fetchone()[0],
            "moi": q("SELECT COUNT(*) FROM participants WHERE me_hint = 1").fetchone()[0],
            "precision": precision,
            "span": (span["lo"], span["hi"]),
            "channels": channels,
            "conflicts": q("SELECT COUNT(*) FROM conflicts WHERE resolved = 0").fetchone()[0],
            "text_bytes": q("SELECT COALESCE(SUM(LENGTH(text)), 0) FROM messages").fetchone()[0]
            + q("SELECT COALESCE(SUM(LENGTH(text)), 0) FROM documents").fetchone()[0],
        }
