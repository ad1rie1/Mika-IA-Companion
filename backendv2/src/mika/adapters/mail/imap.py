"""Une session IMAP (bibliothèque standard, bloquante : appelée dans un fil).

- **UID**, jamais numéro de séquence ; lectures en ``BODY.PEEK[]`` : relever
  ne marque jamais un mail comme lu.
- Les noms de dossiers circulent en UTF-7 modifié (``utf7``), sont montrés
  décodés ; leur rôle vient des attributs *special-use* (RFC 6154), sinon du
  nom (« Sent », « Envoyés », « [Gmail]/Corbeille »…).
- Déplacer : ``MOVE`` si le serveur l'annonce, sinon ``COPY`` + ``\\Deleted`` +
  ``EXPUNGE`` (``UID EXPUNGE`` avec UIDPLUS).
"""

from __future__ import annotations

import imaplib
import re
import ssl
from datetime import datetime
from typing import Any

from mika.adapters.mail import utf7
from mika.adapters.mail.config import MailAccount

TIMEOUT = 30.0
FETCH_BATCH = 25
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_LIST = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$', re.I)
_UID = re.compile(rb"UID (\d+)", re.I)
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)", re.I)
_CODE = re.compile(rb"\[(UIDVALIDITY|UIDNEXT) (\d+)\]", re.I)
_COPYUID = re.compile(rb"COPYUID \d+ [\d:,]+ (\d+)", re.I)
_SPECIAL = {"\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash", "\\junk": "junk", "\\archive": "archive"}
_NAMES = {
    "sent": ("sent", "sent items", "sent messages", "sent mail", "envoyés", "envoyes", "éléments envoyés",
             "messages envoyés", "courrier envoyé"),
    "drafts": ("drafts", "brouillons", "draft"),
    "trash": ("trash", "deleted", "deleted items", "deleted messages", "corbeille", "éléments supprimés", "bin"),
    "junk": ("junk", "spam", "indésirables", "courrier indésirable", "junk e-mail", "pourriel", "bulk mail"),
    "archive": ("archive", "archives", "all mail", "tous les messages"),
}


class ImapError(RuntimeError):
    """Une réponse du serveur qui n'est pas « OK » (dite en français)."""


def since(when: datetime) -> str:
    return f"{when.day:02d}-{_MONTHS[when.month - 1]}-{when.year}"


def role_of(name: str, flags: frozenset[str]) -> str:
    for flag, role in _SPECIAL.items():
        if flag in flags:
            return role
    if name.upper() == "INBOX":
        return "inbox"
    leaf = re.split(r"[./]", name)[-1].strip().lower()
    for role, names in _NAMES.items():
        if leaf in names:
            return role
    return "archive" if "\\all" in flags else ""


def _unquote(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


def quoted(name: str) -> str:
    return '"' + utf7.encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


class Session:
    def __init__(self, account: MailAccount, *, timeout: float = TIMEOUT) -> None:
        if account.imap_ssl:
            self.box: imaplib.IMAP4 = imaplib.IMAP4_SSL(account.imap_host, account.imap_port,
                                                        ssl_context=ssl.create_default_context(), timeout=timeout)
        else:
            self.box = imaplib.IMAP4(account.imap_host, account.imap_port, timeout=timeout)
            # sans SSL d'emblée : chiffrer avant d'envoyer le mot de passe, si le serveur le propose
            if "STARTTLS" in {str(c).upper() for c in getattr(self.box, "capabilities", ())}:
                try:
                    self._ok(self.box.starttls(ssl_context=ssl.create_default_context()), "STARTTLS refusé")
                except (imaplib.IMAP4.error, ssl.SSLError, OSError) as exc:
                    self.close()
                    raise ImapError(f"le chiffrement (STARTTLS) a échoué : {exc}") from None
        try:
            self._ok(self.box.login(account.user, account.password), "connexion refusée")
        except imaplib.IMAP4.error as exc:
            self.close()
            raise ImapError(f"connexion refusée : {exc}") from None
        self.caps = {str(c).upper() for c in getattr(self.box, "capabilities", ())}
        self.selected = ""
        self.writable = False

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    @staticmethod
    def _ok(result: tuple[str, Any], what: str) -> Any:
        status, data = result
        if status != "OK":
            detail = b" ".join(d for d in data or () if isinstance(d, bytes)).decode("utf-8", "replace")
            raise ImapError(f"{what} ({detail[:200]})" if detail else what)
        return data

    # ── dossiers ──
    def folders(self) -> list[tuple[str, frozenset[str]]]:
        """``(nom décodé, attributs)`` de chaque dossier sélectionnable."""
        data = self._ok(self.box.list(), "liste des dossiers illisible")
        out = []
        for item in data or ():
            raw = item[0] + b" " + item[1] if isinstance(item, tuple) else item
            if not isinstance(raw, bytes):
                continue
            found = _LIST.match(raw.strip())
            if not found:
                continue
            flags = frozenset(f.lower() for f in found.group("flags").decode("ascii", "replace").split())
            if "\\noselect" in flags or "\\nonexistent" in flags:
                continue
            out.append((utf7.decode(_unquote(found.group("name"))), flags))
        return out

    def select(self, name: str, *, write: bool = False) -> tuple[int, int, int]:
        """Ouvre un dossier ; rend ``(nombre, UIDVALIDITY, UIDNEXT)`` (0 : inconnu)."""
        if self.selected == name and (self.writable or not write):
            return self._counts
        try:
            data = self._ok(self.box.select(quoted(name), readonly=not write), f"dossier « {name} » introuvable")
        except imaplib.IMAP4.readonly:
            raise ImapError(f"le dossier « {name} » est en lecture seule") from None
        responses = getattr(self.box, "untagged_responses", {})
        codes: dict[str, int] = {}
        for key in ("UIDVALIDITY", "UIDNEXT"):
            for value in responses.get(key, ()):
                try:
                    codes[key] = int(value)
                except (TypeError, ValueError):
                    continue
        for value in responses.get("OK", ()):
            if isinstance(value, bytes):
                for key, number in _CODE.findall(value):
                    codes.setdefault(key.decode().upper(), int(number))
        try:
            count = int((data or [b"0"])[0] or 0)
        except (TypeError, ValueError):
            count = 0
        self.selected, self.writable = name, write
        self._counts = (count, codes.get("UIDVALIDITY", 0), codes.get("UIDNEXT", 0))
        return self._counts

    # ── lire ──
    def search(self, criteria: str) -> list[int]:
        data = self._ok(self.box.uid("SEARCH", None, criteria), "recherche refusée")
        return sorted({int(u) for u in (data[0] or b"").split() if u.isdigit()}) if data else []

    def fetch(self, uids: list[int]) -> list[tuple[int, frozenset[str], bytes]]:
        """``(uid, drapeaux, mail brut)`` — sans poser ``\\Seen``."""
        out = []
        for i in range(0, len(uids), FETCH_BATCH):
            batch = ",".join(str(u) for u in uids[i:i + FETCH_BATCH])
            data = self._ok(self.box.uid("FETCH", batch, "(UID FLAGS BODY.PEEK[])"), "lecture refusée")
            for item in data or ():
                if not isinstance(item, tuple) or len(item) < 2 or not isinstance(item[1], bytes | bytearray):
                    continue
                uid = _UID.search(item[0])
                if uid:
                    out.append((int(uid.group(1)), _flags(item[0]), bytes(item[1])))
        return out

    def flags(self, uids: list[int]) -> dict[int, frozenset[str]]:
        out: dict[int, frozenset[str]] = {}
        for i in range(0, len(uids), 200):
            batch = ",".join(str(u) for u in uids[i:i + 200])
            data = self._ok(self.box.uid("FETCH", batch, "(UID FLAGS)"), "lecture des drapeaux refusée")
            for item in data or ():
                head = item[0] if isinstance(item, tuple) else item
                if not isinstance(head, bytes):
                    continue
                uid = _UID.search(head)
                if uid:
                    out[int(uid.group(1))] = _flags(head)
        return out

    # ── ranger ──
    def store(self, uid: int, flag: str, on: bool) -> None:
        self._ok(self.box.uid("STORE", str(uid), "+FLAGS" if on else "-FLAGS", f"({flag})"), "drapeau refusé")

    def store_many(self, uids: list[int], flag: str, on: bool) -> None:
        """Un drapeau posé (ou retiré) sur plusieurs mails du dossier ouvert, en une commande."""
        if uids:
            self._ok(self.box.uid("STORE", ",".join(str(u) for u in uids), "+FLAGS" if on else "-FLAGS",
                                  f"({flag})"), "drapeau refusé")

    def move(self, uid: int, dest: str) -> int | None:
        """Déplace (dans le dossier ouvert) ; rend l'UID d'arrivée s'il est dit."""
        if "MOVE" in self.caps:
            typ, data = self.box.uid("MOVE", str(uid), quoted(dest))
            self._ok((typ, data), f"déplacement vers « {dest} » refusé")
        else:
            typ, data = self.box.uid("COPY", str(uid), quoted(dest))
            self._ok((typ, data), f"copie vers « {dest} » refusée")
            self.store(uid, "\\Deleted", True)
            self.expunge(uid)
        text = b" ".join(d for d in data or () if isinstance(d, bytes))
        for value in getattr(self.box, "untagged_responses", {}).get("OK", ()):
            if isinstance(value, bytes):
                text += b" " + value
        found = _COPYUID.search(text)
        return int(found.group(1)) if found else None

    def expunge(self, uid: int) -> None:
        if "UIDPLUS" in self.caps:
            self._ok(self.box.uid("EXPUNGE", str(uid)), "suppression refusée")
        else:
            self._ok(self.box.expunge(), "suppression refusée")

    def append(self, folder: str, raw: bytes, *, seen: bool = True) -> None:
        self._ok(self.box.append(quoted(folder), "(\\Seen)" if seen else None, None, raw),
                 f"copie dans « {folder} » refusée")


def _flags(head: bytes) -> frozenset[str]:
    found = _FLAGS.search(head)
    return frozenset(f.lower() for f in found.group(1).decode("ascii", "replace").split()) if found else frozenset()
