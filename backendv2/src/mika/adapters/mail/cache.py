"""Le cache du courrier (``mail.db``) : ce qui est arrivé, par compte et par
dossier ; les dossiers et leur curseur IMAP ; ce qui a déjà été rendu (et ce
qui l'a été sans être encore accusé) ; les
brouillons ; ce qui est parti ; l'état de chaque compte.

Une ligne par (compte, dossier, UID) : les UID ne valent que dans leur
dossier (et leur UIDVALIDITY). **Un mail se désigne par sa référence**
(colonne ``ref``), attribuée ici à son arrivée — jamais choisie par
l'expéditeur : le premier mail d'un Message-ID garde la forme historique
``compte:Message-ID``, une copie du même mail (un autre dossier, même
contenu) la partage, un autre mail qui porte le même Message-ID en reçoit
une autre (``…#2``) et les deux sont marqués (``twin``). Un mail qui se dit
l'un de ses envois sans être rangé dans « Envoyés » est traité de même. Ce
qui a été rendu se retient par référence : un mail qui change de dossier
n'est pas rendu deux fois, un faux qui imite un vrai l'est (on le remarque).

Oublier un correspondant (``forget``) efface ses mails, ce qui lui a été écrit
et ce qui lui répondait ; ses mails restent sur le serveur, leur empreinte est
retenue (``forgotten``) pour qu'une relecture ne les ramène pas.

Le cache d'avant les comptes (une table ``mails``, des ``uids``) est repris
sous le compte « principal », dossier ``INBOX`` ; celui d'avant les
références reçoit les siennes (le premier mail de chaque Message-ID garde la
forme historique : les journaux restent valables).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from mika.adapters.mail.browse import Browse
from mika.ports.mail import (
    AccountStatus,
    Attachment,
    Draft,
    Folder,
    Mail,
    Sent,
    addresses,
    assigned_ref,
    mail_ref,
    reference_key,
    split_ref,
)
from mika.ports.paging import fold_text

#: limite d'une purge de maintenance explicite ; la synchronisation ne purge pas l'historique
KEEP_PER_FOLDER = 2000
SCHEMA = 7
LEGACY_ACCOUNT = "principal"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS messages(
  account TEXT NOT NULL, folder TEXT NOT NULL, uid INTEGER NOT NULL, message_id TEXT NOT NULL,
  sender TEXT, address TEXT, reply_to TEXT, dest TEXT, cc TEXT, subject TEXT, date INTEGER, body TEXT,
  has_html INTEGER, attachments TEXT, in_reply_to TEXT, refs TEXT, bulk INTEGER,
  seen INTEGER, flagged INTEGER, answered INTEGER,
  PRIMARY KEY(account, folder, uid));
CREATE INDEX IF NOT EXISTS messages_mid ON messages(account, message_id);
CREATE INDEX IF NOT EXISTS messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS messages_folder_date ON messages(account,folder,date DESC);
CREATE TABLE IF NOT EXISTS folders(
  account TEXT NOT NULL, name TEXT NOT NULL, role TEXT, uidvalidity INTEGER, uidnext INTEGER,
  total INTEGER, unseen INTEGER, last_sync INTEGER, PRIMARY KEY(account, name));
CREATE TABLE IF NOT EXISTS handed(account TEXT NOT NULL, message_id TEXT NOT NULL, PRIMARY KEY(account, message_id));
CREATE TABLE IF NOT EXISTS offered(account TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY(account, ref));
CREATE TABLE IF NOT EXISTS drafts(
  id TEXT PRIMARY KEY, account TEXT, dest TEXT, cc TEXT, subject TEXT, body TEXT, reply_to TEXT, quote INTEGER,
  author TEXT, created INTEGER, updated INTEGER, state TEXT, sent_id TEXT, edited_by TEXT);
CREATE TABLE IF NOT EXISTS status(account TEXT PRIMARY KEY, last_poll INTEGER, error TEXT, error_at INTEGER);
CREATE TABLE IF NOT EXISTS envoyes(message_id TEXT PRIMARY KEY, dest TEXT, subject TEXT, body TEXT, date INTEGER,
  in_reply_to TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS forgotten(account TEXT NOT NULL, print TEXT NOT NULL, PRIMARY KEY(account, print));
"""
_COLUMNS = ("account", "folder", "uid", "message_id", "sender", "address", "reply_to", "dest", "cc", "subject",
            "date", "body", "has_html", "attachments", "in_reply_to", "refs", "bulk", "seen", "flagged", "answered", "html",
            "complete", "ref", "twin")
_SENT_COLUMNS = ("message_id", "dest", "subject", "body", "date", "in_reply_to", "by", "account", "draft", "cc", "attachments")
_DRAFT_COLUMNS = ("id", "account", "dest", "cc", "subject", "body", "reply_to", "quote", "author", "created",
                  "updated", "state", "sent_id", "edited_by", "original_body")


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class MailCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.create_function("fold", 1, lambda s: fold_text(s or ""), deterministic=True)
        self._db.create_function("mail_ref", 2, mail_ref, deterministic=True)
        self._db.create_function("mail_mid", 1, lambda s: split_ref(s or "")[1], deterministic=True)
        self._db.create_function("mail_key", 1, reference_key, deterministic=True)
        self._db.create_function("mail_addresses", 1, lambda s: json.dumps(addresses(s or "")), deterministic=True)
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._migrate()

    # ── schéma ──
    def _migrate(self) -> None:
        mail_cols = {r[1] for r in self._db.execute("PRAGMA table_info(messages)")}
        if "html" not in mail_cols:
            self._db.execute("ALTER TABLE messages ADD COLUMN html TEXT NOT NULL DEFAULT ''")
        if "complete" not in mail_cols:
            self._db.execute("ALTER TABLE messages ADD COLUMN complete INTEGER NOT NULL DEFAULT 0")
        if "ref" not in mail_cols:
            self._db.execute("ALTER TABLE messages ADD COLUMN ref TEXT NOT NULL DEFAULT ''")
        if "twin" not in mail_cols:
            self._db.execute("ALTER TABLE messages ADD COLUMN twin INTEGER NOT NULL DEFAULT 0")
        self._db.execute("CREATE INDEX IF NOT EXISTS messages_ref ON messages(account, ref)")
        sent_cols = {r[1] for r in self._db.execute("PRAGMA table_info(envoyes)")}
        if "source" not in sent_cols:
            self._db.execute("ALTER TABLE envoyes ADD COLUMN source BLOB")
        if "attachments" not in sent_cols:
            self._db.execute("ALTER TABLE envoyes ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'")
        for col in ("account", "draft", "cc"):
            if col not in sent_cols:
                self._db.execute(f"ALTER TABLE envoyes ADD COLUMN {col} TEXT DEFAULT ''")
        draft_cols = {r[1] for r in self._db.execute("PRAGMA table_info(drafts)")}
        if "original_body" not in draft_cols:  # sa version, gardée à la première retouche
            self._db.execute("ALTER TABLE drafts ADD COLUMN original_body TEXT NOT NULL DEFAULT ''")
        tables = {r[0] for r in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "mails" in tables:  # le cache d'avant les comptes : sous « principal », dans INBOX
            rows = self._db.execute("SELECT message_id, uid, sender, address, subject, date, body, dest, in_reply_to,"
                                    " bulk FROM mails").fetchall()
            for i, (mid, uid, sender, address, subject, date, body, dest, irt, bulk) in enumerate(rows):
                try:
                    number = int(uid)
                except (TypeError, ValueError):
                    number = -(i + 1)
                self._db.execute(
                    "INSERT OR IGNORE INTO messages(account, folder, uid, message_id, sender, address, reply_to,"
                    " dest, cc, subject, date, body, has_html, attachments, in_reply_to, refs, bulk, seen, flagged,"
                    " answered) VALUES(?,?,?,?,?,?,'',?,'',?,?,?,0,'[]',?,'',?,0,0,0)",
                    (LEGACY_ACCOUNT, "INBOX", number, mid, sender, address, dest, subject, date, body, irt, bulk))
                self._db.execute("INSERT OR IGNORE INTO handed VALUES(?,?)", (LEGACY_ACCOUNT, mid))
            known = []
            if "uids" in tables:
                for (uid,) in self._db.execute("SELECT uid FROM uids"):
                    try:
                        known.append(int(uid))
                    except (TypeError, ValueError):
                        continue
            if known:
                self._db.execute("INSERT OR IGNORE INTO folders(account, name, role, uidvalidity, uidnext, total,"
                                 " unseen, last_sync) VALUES(?,?,?,0,?,0,0,0)",
                                 (LEGACY_ACCOUNT, "INBOX", "inbox", max(known) + 1))
            self._db.execute("UPDATE envoyes SET account=? WHERE account IS NULL OR account=''", (LEGACY_ACCOUNT,))
            self._db.execute("DROP TABLE mails")
            self._db.execute("DROP TABLE IF EXISTS uids")
        # un cache d'avant les références : chaque ligne reçoit la sienne, dans l'ordre d'arrivée
        # (le premier mail d'un Message-ID garde la forme historique, que le journal connaît déjà)
        pending = self._db.execute("SELECT rowid, account, folder, message_id FROM messages WHERE ref='' "
                                   "ORDER BY rowid").fetchall()
        for rowid, account, folder, mid in pending:
            ref, twin = self._assign(account, folder, mid, self._print_of_row(rowid), legacy=True)
            self._db.execute("UPDATE messages SET ref=?, twin=? WHERE rowid=?", (ref, int(twin), rowid))
        self._db.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (str(SCHEMA),))
        self._db.commit()

    # ── références ──
    @staticmethod
    def _print(address: str, subject: str, date: int, body: str) -> str:
        """L'empreinte d'un contenu : deux copies du même mail (deux dossiers) ont la même."""
        raw = "\x1f".join((address or "", subject or "", str(date or 0), (body or "")[:20_000]))
        return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()

    def _print_of_row(self, rowid: int) -> str:
        row = self._db.execute("SELECT address, subject, date, body FROM messages WHERE rowid=?", (rowid,)).fetchone()
        return self._print(*row) if row else ""

    def _assign(self, account: str, folder: str, message_id: str, fingerprint: str, *,
                legacy: bool = False) -> tuple[str, bool]:
        """La référence d'un mail qui arrive (et s'il a un jumeau) : celle d'une copie du même contenu
        s'il en a une ; la forme historique s'il est le premier de ce Message-ID ; sinon une
        référence numérotée — et l'autre mail est marqué lui aussi."""
        rows = self._db.execute("SELECT rowid, ref, twin FROM messages WHERE account=? AND message_id=? AND ref!='' "
                                "ORDER BY rowid", (account, message_id)).fetchall()
        for rowid, ref, twin in rows:
            if self._print_of_row(rowid) == fingerprint:
                return ref, bool(twin)
        role = self._db.execute("SELECT role FROM folders WHERE account=? AND name=?", (account, folder)).fetchone()
        # un mail qui reprend le Message-ID de l'un de ses envois sans être rangé dans « Envoyés » : un imitateur
        claims_hers = not legacy and (role is None or role[0] != "sent") and self._db.execute(
            "SELECT 1 FROM envoyes WHERE message_id IN (?, ?) AND (account=? OR account='')",
            (message_id, mail_ref(account, message_id), account)).fetchone() is not None
        taken = {r[1] for r in rows}
        if not rows and not claims_hers:
            first = mail_ref(account, message_id) if legacy else assigned_ref(account, message_id)
            return first, False
        rank = 2
        while assigned_ref(account, message_id, rank) in taken:
            rank += 1
        if rows:
            self._db.execute("UPDATE messages SET twin=1 WHERE account=? AND message_id=?", (account, message_id))
        return assigned_ref(account, message_id, rank), True

    # ── mails ──
    @staticmethod
    def _mail(r: tuple[Any, ...]) -> Mail:
        d = dict(zip(_COLUMNS, r, strict=True))
        try:
            files = tuple(Attachment(str(a[0]), str(a[1]), int(a[2])) for a in json.loads(d["attachments"] or "[]"))
        except (ValueError, TypeError, IndexError):
            files = ()
        return Mail(message_id=d["message_id"], sender=d["sender"] or "", address=d["address"] or "",
                    subject=d["subject"] or "", date=d["date"] or 0, body=d["body"] or "", to=d["dest"] or "",
                    in_reply_to=d["in_reply_to"] or "", bulk=bool(d["bulk"]), account=d["account"],
                    folder=d["folder"], cc=d["cc"] or "", reply_to=d["reply_to"] or "", references=d["refs"] or "",
                    seen=bool(d["seen"]), flagged=bool(d["flagged"]), answered=bool(d["answered"]),
                    attachments=files, has_html=bool(d["has_html"]), html=d["html"] or "", complete=bool(d["complete"]),
                    key=d["ref"] or "", twin=bool(d["twin"]))

    def store(self, m: Mail, uid: int) -> Mail:
        """Garde un mail à sa place (compte, dossier, UID) et rend ce qui est gardé, avec sa référence :
        celle qu'il avait déjà à cette place (ou à sa place provisoire, s'il vient d'être déplacé),
        sinon celle que lui attribue ``_assign``. Un mail oublié (``forget``) n'est pas gardé de nouveau :
        il est rendu tel quel."""
        files = json.dumps([[a.name, a.mime, a.size] for a in m.attachments], ensure_ascii=False)
        fingerprint = self._print(m.address, m.subject, m.date, m.body)
        with self._lock:
            if self._db.execute("SELECT 1 FROM forgotten WHERE account=? AND print=?",
                                (m.account, fingerprint)).fetchone() is not None:
                return m  # une relecture du serveur ne ramène pas ce qui a été oublié
            known = self._db.execute(
                "SELECT ref, twin FROM messages WHERE account=? AND folder=? AND ((uid=? AND message_id=?) OR "
                "(uid<=0 AND message_id=?)) AND ref!='' ORDER BY uid DESC LIMIT 1",
                (m.account, m.folder, uid, m.message_id, m.message_id)).fetchone()
            # un mail déplacé d'ici attendait son vrai UID (une place provisoire, négative) : il l'a
            self._db.execute("DELETE FROM messages WHERE account=? AND folder=? AND message_id=? AND uid<=0",
                             (m.account, m.folder, m.message_id))
            if known is not None:
                ref, twin = str(known[0]), bool(known[1])
            else:
                self._db.execute("DELETE FROM messages WHERE account=? AND folder=? AND uid=?",
                                 (m.account, m.folder, uid))  # cette place change d'occupant
                ref, twin = self._assign(m.account, m.folder, m.message_id, fingerprint)
            self._db.execute(
                f"INSERT OR REPLACE INTO messages({', '.join(_COLUMNS)}) VALUES({', '.join('?' * len(_COLUMNS))})",
                (m.account, m.folder, uid, m.message_id, m.sender, m.address, m.reply_to, m.to, m.cc, m.subject,
                 m.date, m.body, int(m.has_html), files, m.in_reply_to, m.references, int(m.bulk), int(m.seen),
                 int(m.flagged), int(m.answered), m.html, int(m.complete), ref, int(twin)))
            self._db.commit()
        return replace(m, key=ref, twin=twin)

    def _where_ref(self, ref: str) -> tuple[str, tuple[Any, ...]]:
        """Où chercher une référence : exactement elle ; sans compte (un ancien journal), le premier mail
        de ce Message-ID, jamais un jumeau arrivé après."""
        account, local = split_ref(ref)
        if account:
            first = assigned_ref(account, local)
            return ("account=? AND (ref=? OR (message_id=? AND ref=? AND ref!=?))",
                    (account, ref, local, first, ref))
        return "message_id=? AND ref=mail_ref(account, message_id)", (local,)

    def one(self, ref: str) -> Mail | None:
        where, args = self._where_ref(ref)
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_COLUMNS)} FROM messages WHERE {where} "
                                    "ORDER BY (ref=?) DESC, (folder='INBOX') DESC, date DESC LIMIT 1",
                                    (*args, ref)).fetchall()
        return self._mail(rows[0]) if rows else None

    def at_row(self, rowid: int, *, sent: bool = False):
        columns = _SENT_COLUMNS if sent else _COLUMNS
        projection = ", ".join("substr(body,1,400)" if c == "body" else "''" if c == "html" else c for c in columns)
        row = self._db.execute(f"SELECT {projection} FROM {'envoyes' if sent else 'messages'} WHERE rowid=?", (rowid,)).fetchone()
        return self._sent(row) if sent else self._mail(row)

    def draft_at_row(self, rowid: int):
        return self._draft(self._db.execute(f"SELECT {', '.join(_DRAFT_COLUMNS)} FROM drafts WHERE rowid=?", (rowid,)).fetchone())

    def browse(self, method: str, *args):
        with self._lock:
            return getattr(Browse(self), method)(*args)

    def located(self, ref: str) -> tuple[Mail, int] | None:
        """Le mail et son UID dans son dossier."""
        where, args = self._where_ref(ref)
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_COLUMNS)} FROM messages WHERE {where} "
                                    "ORDER BY (ref=?) DESC, (folder='INBOX') DESC, date DESC LIMIT 1",
                                    (*args, ref)).fetchall()
        return (self._mail(rows[0]), int(rows[0][2])) if rows else None

    def located_all(self, refs: Iterable[str]) -> list[tuple[Mail, int]]:
        """Chaque mail (et son UID) de ces références, sans doublon."""
        out: list[tuple[Mail, int]] = []
        seen: set[tuple[str, str, int]] = set()
        for ref in refs:
            found = self.located(ref)
            if found is not None and (found[0].account, found[0].folder, found[1]) not in seen:
                seen.add((found[0].account, found[0].folder, found[1]))
                out.append(found)
        return out

    def recent(self, limit: int, *, account: str = "", folder: str = "") -> list[Mail]:
        clauses, args = [], []
        if account:
            clauses.append("account=?")
            args.append(account)
        if folder:
            clauses.append("folder=?")
            args.append(folder)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_COLUMNS)} FROM messages {where} "
                                    "ORDER BY date DESC, rowid DESC LIMIT ?", (*args, max(0, limit))).fetchall()
        return [self._mail(r) for r in rows]

    def search(self, text: str, limit: int, *, account: str = "") -> list[Mail]:
        pattern = _like(text.strip())
        clause, args = ("AND account=?", (account,)) if account else ("", ())
        with self._lock:
            rows = self._db.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM messages WHERE (subject LIKE ? ESCAPE '\\' OR sender LIKE ? "
                f"ESCAPE '\\' OR body LIKE ? ESCAPE '\\') {clause} ORDER BY date DESC LIMIT ?",
                (pattern, pattern, pattern, *args, max(0, limit))).fetchall()
        return [self._mail(r) for r in rows]

    def uids(self, account: str, folder: str, limit: int) -> list[tuple[int, str, bool]]:
        """Les derniers ``(uid, référence, lu)`` d'un dossier."""
        with self._lock:
            return [(int(u), str(r), bool(s)) for u, r, s in self._db.execute(
                "SELECT uid, ref, seen FROM messages WHERE account=? AND folder=? AND uid>0 "
                "ORDER BY uid DESC LIMIT ?", (account, folder, max(0, limit)))]

    def oldest_uid(self, account: str, folder: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COALESCE(MIN(uid),0) FROM messages WHERE account=? AND folder=? AND uid>0",
                                    (account, folder)).fetchone()[0]

    def folder_count(self, account: str, folder: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM messages WHERE account=? AND folder=?", (account, folder)).fetchone()[0]

    def find_ref(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT ref FROM messages WHERE mail_key(ref)=? "
                "UNION ALL SELECT mail_ref(account,mail_mid(message_id)) FROM envoyes "
                "WHERE mail_key(mail_ref(account,mail_mid(message_id)))=? OR mail_key(message_id)=? LIMIT 1", (key, key, key)).fetchone()
        return row[0] if row else None

    def missing_html(self, account: str, folder: str, limit: int) -> list[int]:
        """Sources HTML absentes d'un ancien cache ; relecture explicite seulement."""
        with self._lock:
            return [int(r[0]) for r in self._db.execute(
                "SELECT uid FROM messages WHERE account=? AND folder=? AND uid>0 AND has_html=1 AND html='' "
                "ORDER BY date DESC LIMIT ?", (account, folder, max(0, limit)))]

    def set_flags(self, account: str, folder: str, uid: int, *, seen: bool | None = None,
                  flagged: bool | None = None, answered: bool | None = None) -> None:
        sets, args = [], []
        for name, value in (("seen", seen), ("flagged", flagged), ("answered", answered)):
            if value is not None:
                sets.append(f"{name}=?")
                args.append(int(value))
        if not sets:
            return
        with self._lock:
            self._db.execute(f"UPDATE messages SET {', '.join(sets)} WHERE account=? AND folder=? AND uid=?",
                             (*args, account, folder, uid))
            self._db.commit()

    def forget_uids(self, account: str, folder: str, uids: Iterable[int]) -> None:
        with self._lock:
            self._db.executemany("DELETE FROM messages WHERE account=? AND folder=? AND uid=?",
                                 [(account, folder, u) for u in uids])
            self._db.commit()

    def relocate(self, account: str, folder: str, uid: int, dest: str, new_uid: int | None) -> None:
        """Un mail déplacé : il change de dossier (et d'UID, s'il est connu)."""
        with self._lock:
            if new_uid is None:
                new_uid = -int(self._db.execute("SELECT COALESCE(MAX(rowid), 0) + 1 FROM messages").fetchone()[0])
            self._db.execute("UPDATE OR REPLACE messages SET folder=?, uid=? WHERE account=? AND folder=? AND uid=?",
                             (dest, new_uid, account, folder, uid))
            self._db.commit()

    def reset_folder(self, account: str, folder: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM messages WHERE account=? AND folder=?", (account, folder))
            self._db.commit()

    def prune(self, account: str, folder: str, keep: int = KEEP_PER_FOLDER) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM messages WHERE account=? AND folder=? AND rowid NOT IN (SELECT rowid FROM messages "
                "WHERE account=? AND folder=? ORDER BY date DESC LIMIT ?)", (account, folder, account, folder, keep))
            self._db.commit()

    # ── rendus une fois ──
    def handed(self, account: str, message_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM handed WHERE account=? AND message_id=?",
                                    (account, message_id)).fetchone() is not None

    def hand(self, account: str, message_id: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO handed VALUES(?,?)", (account, message_id))
            self._db.commit()

    def offer(self, account: str, ref: str) -> None:
        """Rendu par un relevé, pas encore accusé : chaque relevé le rend encore tant qu'il ne l'est pas
        (le curseur IMAP, lui, est déjà passé)."""
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO offered VALUES(?,?)", (account, ref))
            self._db.commit()

    def offered(self, account: str, limit: int) -> list[Mail]:
        """Les mails rendus et pas encore accusés de ce compte, les plus anciens d'abord ; un mail sorti du
        cache entre-temps (supprimé, rangé ailleurs par un autre client) n'est plus à rendre."""
        out: list[Mail] = []
        with self._lock:
            refs = self._db.execute("SELECT ref FROM offered WHERE account=? ORDER BY rowid", (account,)).fetchall()
            for (ref,) in refs:
                if len(out) >= limit:
                    break
                mail = self.one(ref)
                if mail is None:
                    self._db.execute("DELETE FROM offered WHERE account=? AND ref=?", (account, ref))
                else:
                    out.append(mail)
            self._db.commit()
        return out

    def ack(self, refs: Iterable[str]) -> None:
        """Ces mails ont été remarqués : rendus pour de bon, plus jamais rendus."""
        with self._lock:
            for ref in refs:
                account, local = split_ref(ref)
                self._db.execute("INSERT OR IGNORE INTO handed VALUES(?,?)", (account, local))
                self._db.execute("DELETE FROM offered WHERE account=? AND ref=?", (account, ref))
            self._db.commit()

    # ── dossiers ──
    @staticmethod
    def _folder(r: tuple[Any, ...], polled: frozenset[str]) -> Folder:
        account, name, role, _validity, _next, total, unseen, last = r
        return Folder(account, name, role or "", name in polled, total or 0, unseen or 0, last or 0)

    def folders(self, account: str, polled: Iterable[str] = ()) -> list[Folder]:
        chosen = frozenset(polled)
        with self._lock:
            rows = self._db.execute("SELECT account, name, role, uidvalidity, uidnext, total, unseen, last_sync "
                                    "FROM folders WHERE account=?", (account,)).fetchall()
        known = {r[1] for r in rows}
        out = [self._folder(r, chosen) for r in rows]
        out += [Folder(account, name, "inbox" if name.upper() == "INBOX" else "", True) for name in chosen
                if name not in known]
        order = {"inbox": 0, "drafts": 1, "sent": 2, "archive": 3, "": 4, "junk": 5, "trash": 6}
        return sorted(out, key=lambda f: (order.get(f.role, 4), f.name.lower()))

    def cursor(self, account: str, folder: str) -> tuple[int, int] | None:
        """``(uidvalidity, uidnext)`` d'un dossier déjà relu."""
        with self._lock:
            row = self._db.execute("SELECT uidvalidity, uidnext FROM folders WHERE account=? AND name=?",
                                   (account, folder)).fetchone()
        return (int(row[0] or 0), int(row[1] or 0)) if row else None

    def save_folder(self, account: str, name: str, *, role: str | None = None, uidvalidity: int | None = None,
                    uidnext: int | None = None, total: int | None = None, unseen: int | None = None,
                    last_sync: int | None = None) -> None:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO folders(account, name, role, uidvalidity, uidnext, total, unseen,"
                             " last_sync) VALUES(?,?,'',0,0,0,0,0)", (account, name))
            for col, value in (("role", role), ("uidvalidity", uidvalidity), ("uidnext", uidnext), ("total", total),
                               ("unseen", unseen), ("last_sync", last_sync)):
                if value is not None:
                    self._db.execute(f"UPDATE folders SET {col}=? WHERE account=? AND name=?", (value, account, name))
            self._db.commit()

    def keep_folders(self, account: str, names: Iterable[str]) -> None:
        """La liste des dossiers vient d'être relue : ceux qui n'existent plus s'en vont."""
        kept = set(names)
        with self._lock:
            gone = [n for (n,) in self._db.execute("SELECT name FROM folders WHERE account=?", (account,))
                    if n not in kept]
            for name in gone:
                self._db.execute("DELETE FROM folders WHERE account=? AND name=?", (account, name))
            self._db.commit()

    def role_folder(self, account: str, role: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT name FROM folders WHERE account=? AND role=? ORDER BY name LIMIT 1",
                                   (account, role)).fetchone()
        return str(row[0]) if row else None

    def recount(self, account: str, folder: str) -> None:
        with self._lock:
            total, unseen = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(1 - seen), 0) FROM messages WHERE account=? AND folder=?",
                (account, folder)).fetchone()
        self.save_folder(account, folder, total=int(total), unseen=int(unseen))

    # ── envoyés ──
    def remember_sent(self, s: Sent, source: bytes | None = None) -> None:
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO envoyes({', '.join(_SENT_COLUMNS)}) "
                             f"VALUES({', '.join('?' * len(_SENT_COLUMNS))})",
                             (s.message_id, s.to, s.subject, s.body, s.date, s.in_reply_to, s.by, s.account,
                              s.draft, s.cc, json.dumps([[a.name, a.mime, a.size] for a in s.attachments])))
            if source is not None:
                self._db.execute("UPDATE envoyes SET source=? WHERE message_id=?", (source, s.message_id))
            self._db.commit()

    def sent_source(self, ref: str) -> bytes | None:
        account, mid = split_ref(ref)
        with self._lock:
            row = self._db.execute("SELECT source FROM envoyes WHERE message_id IN (?,?) AND (?='' OR account=?)",
                                   (ref, mid, account, account)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _sent(r: tuple[Any, ...]) -> Sent:
        d = dict(zip(_SENT_COLUMNS, r, strict=True))
        return Sent(d["message_id"], d["dest"] or "", d["subject"] or "", d["body"] or "", d["date"] or 0,
                    d["in_reply_to"] or "", d["by"] or "", d["account"] or "", d["draft"] or "", d["cc"] or "",
                    tuple(Attachment(*a) for a in json.loads(d["attachments"] or "[]")))

    def sent(self, limit: int, *, account: str = "") -> list[Sent]:
        clause, args = ("WHERE account=?", (account,)) if account else ("", ())
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_SENT_COLUMNS)} FROM envoyes {clause} "
                                    "ORDER BY date DESC, rowid DESC LIMIT ?", (*args, max(0, limit))).fetchall()
        return [self._sent(r) for r in rows]

    def sent_one(self, message_id: str) -> Sent | None:
        account, mid = split_ref(message_id)
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_SENT_COLUMNS)} FROM envoyes WHERE message_id IN (?, ?) AND (?='' OR account=?)",
                                    (message_id, mid, account, account)).fetchall()
        return self._sent(rows[0]) if rows else None

    # ── brouillons ──
    @staticmethod
    def _draft(r: tuple[Any, ...]) -> Draft:
        d = dict(zip(_DRAFT_COLUMNS, r, strict=True))
        return Draft(id=d["id"], account=d["account"] or "", to=d["dest"] or "", subject=d["subject"] or "",
                     body=d["body"] or "", cc=d["cc"] or "", reply_to=d["reply_to"] or "", quote=bool(d["quote"]),
                     author=d["author"] or "", created=d["created"] or 0, updated=d["updated"] or 0,
                     state=d["state"] or "brouillon", sent_id=d["sent_id"] or "", edited_by=d["edited_by"] or "",
                     original_body=d["original_body"] or "")

    def save_draft(self, d: Draft) -> Draft:
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO drafts({', '.join(_DRAFT_COLUMNS)}) "
                             f"VALUES({', '.join('?' * len(_DRAFT_COLUMNS))})",
                             (d.id, d.account, d.to, d.cc, d.subject, d.body, d.reply_to, int(d.quote), d.author,
                              d.created, d.updated, d.state, d.sent_id, d.edited_by, d.original_body))
            self._db.commit()
        return d

    def draft(self, draft_id: str) -> Draft | None:
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_DRAFT_COLUMNS)} FROM drafts WHERE id=?",
                                    (draft_id,)).fetchall()
        return self._draft(rows[0]) if rows else None

    def drafts(self, limit: int, *, state: str = "") -> list[Draft]:
        clause, args = ("WHERE state=?", (state,)) if state else ("", ())
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_DRAFT_COLUMNS)} FROM drafts {clause} "
                                    "ORDER BY updated DESC, rowid DESC LIMIT ?", (*args, max(0, limit))).fetchall()
        return [self._draft(r) for r in rows]

    def recent_edits(self, account: str, limit: int) -> list[Draft]:
        """Ses brouillons de ce compte partis après une retouche, le plus récent d'abord."""
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(_DRAFT_COLUMNS)} FROM drafts WHERE account=? AND "
                                    "state='envoye' AND sent_id!='' AND edited_by!='' AND original_body!='' "
                                    "ORDER BY updated DESC, rowid DESC LIMIT ?", (account, max(0, limit))).fetchall()
        return [self._draft(r) for r in rows]

    def mark_draft(self, draft_id: str, *, state: str, sent_id: str = "") -> None:
        found = self.draft(draft_id)
        if found is not None:
            self.save_draft(replace(found, state=state, sent_id=sent_id or found.sent_id))

    # ── l'oubli ──
    def forget(self, address: str) -> int:
        """Oublier un correspondant, par son adresse : les mails qu'il a écrits ; ce qui lui a été écrit
        (brouillons, envois, leurs copies dans « Envoyés ») ; ce qui répondait à ses mails (ça les cite).
        Ses mails restent sur le serveur : leur empreinte est retenue, pour qu'une relecture ne les
        ramène pas. Rend combien de lignes ont été effacées."""
        address = address.strip().lower()
        if not address:
            return 0
        to_them = ("EXISTS(SELECT 1 FROM json_each(mail_addresses(COALESCE(dest,'') || ',' || COALESCE(cc,''))) j "
                   "WHERE json_extract(j.value,'$[1]')=?)")
        in_sent = ("(EXISTS(SELECT 1 FROM folders f WHERE f.account=messages.account AND f.name=messages.folder "
                   "AND f.role='sent') OR lower(folder) IN ('sent','sent items','envoyés'))")
        with self._lock:
            rows = self._db.execute(f"SELECT rowid, account, folder, ref, message_id, address, subject, date, body "
                                    f"FROM messages WHERE address=? OR ({to_them} AND {in_sent})",
                                    (address, address)).fetchall()
            # ce qui leur répondait les désigne par référence (ou, dans un ancien cache, par Message-ID)
            theirs = json.dumps(sorted({k for r in rows if r[5] == address for k in (r[3], r[4]) if k}))
            n = self._db.execute(f"DELETE FROM drafts WHERE {to_them} OR reply_to IN (SELECT value FROM json_each(?))",
                                 (address, theirs)).rowcount
            n += self._db.execute(f"DELETE FROM envoyes WHERE {to_them} OR in_reply_to IN "
                                  "(SELECT value FROM json_each(?))", (address, theirs)).rowcount
            for rowid, account, _folder, ref, _mid, sender, subject, date, body in rows:
                self._db.execute("INSERT OR IGNORE INTO forgotten VALUES(?,?)",
                                 (account, self._print(sender, subject, date, body)))
                self._db.execute("DELETE FROM offered WHERE account=? AND ref=?", (account, ref))
                n += self._db.execute("DELETE FROM messages WHERE rowid=?", (rowid,)).rowcount
            self._db.commit()
            for account, folder in sorted({(r[1], r[2]) for r in rows}):
                self.recount(account, folder)
        return n

    # ── état des comptes ──
    def status(self, account: str) -> AccountStatus:
        with self._lock:
            row = self._db.execute("SELECT last_poll, error, error_at FROM status WHERE account=?",
                                   (account,)).fetchone()
        return AccountStatus(account, int(row[0] or 0), row[1] or "", int(row[2] or 0)) if row \
            else AccountStatus(account)

    def note(self, account: str, *, at: int, error: str = "", polled: bool = False) -> None:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO status VALUES(?, 0, '', 0)", (account,))
            if polled:
                self._db.execute("UPDATE status SET last_poll=? WHERE account=?", (at, account))
            if error:
                self._db.execute("UPDATE status SET error=?, error_at=? WHERE account=?", (error[:300], at, account))
            elif polled:
                self._db.execute("UPDATE status SET error='' WHERE account=?", (account,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


def ref_of(m: Mail) -> str:
    return m.ref
