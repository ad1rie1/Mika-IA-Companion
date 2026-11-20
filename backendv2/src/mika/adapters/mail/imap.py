"""Une session IMAP (bibliothèque standard, bloquante : appelée dans un fil).

- **UID**, jamais numéro de séquence ; lectures en ``BODY.PEEK[]`` : relever
  ne marque jamais un mail comme lu.
- Les noms de dossiers circulent en UTF-7 modifié (``utf7``), sont montrés
  décodés ; leur rôle vient des attributs *special-use* (RFC 6154), sinon du
  nom (« Sent », « Envoyés », « [Gmail]/Corbeille »…).
- Déplacer : ``MOVE`` si le serveur l'annonce, sinon ``COPY`` + ``\\Deleted`` +
  ``EXPUNGE`` (``UID EXPUNGE`` avec UIDPLUS).
- Les erreurs d'``imaplib`` sont traduites **au bord** : une réponse ``BAD`` lève
  ``IMAP4.error``, une connexion coupée en cours de commande ``IMAP4.abort`` —
  ni l'une ni l'autre n'est une ``OSError``. Hors de cette session, une panne IMAP
  est toujours une ``OSError`` ou une ``ImapError``.
- Une boîte Microsoft entre par ``AUTHENTICATE XOAUTH2`` avec le jeton d'accès
  qu'on lui donne (``oauth``, ADR 0166), les autres par ``LOGIN``.
- Créer un dossier : sous la racine des dossiers personnels (``NAMESPACE``,
  RFC 2342), puis s'y abonner (ADR 0248).
- Chercher des mots : ``UID SEARCH`` dans l'objet, l'expéditeur ou le texte ; un
  mot en ASCII voyage entre guillemets, un autre en littéral UTF-8, seul dans sa
  commande (``imaplib`` n'en porte qu'un) ; les ensembles se croisent ici
  (ADR 0249).
"""

from __future__ import annotations

import functools
import imaplib
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesHeaderParser
from typing import Any, TypeVar

from mika.adapters.mail import compose, oauth, utf7
from mika.adapters.mail.config import MailAccount
from mika.adapters.mail.parse import HEADER_MAX
from mika.ports.mail import addresses

TIMEOUT = 30.0
FETCH_BATCH = 25
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_LIST = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$', re.I)
_UID = re.compile(rb"UID (\d+)", re.I)
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)", re.I)
_CODE = re.compile(rb"\[(UIDVALIDITY|UIDNEXT) (\d+)\]", re.I)
_COPYUID = re.compile(rb"COPYUID \d+ [\d:,]+ (\d+)", re.I)
#: la première racine personnelle d'une réponse ``NAMESPACE`` : ``(("INBOX." "."))`` ou ``(("" "/"))``
_NAMESPACE = re.compile(rb'^\(\("((?:[^"\\]|\\.)*)"\s+(?:"((?:[^"\\]|\\.)*)"|NIL)', re.I)
_INTERNALDATE = re.compile(rb'INTERNALDATE "\s?(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})"',
                           re.I)
_MESSAGE_ID = re.compile(rb"^Message-ID:[ \t]*(\S[^\r\n]*)", re.I | re.M)
_FOLD = re.compile(rb"\r?\n[ \t]+")
#: le début d'une réponse ``FETCH`` (son numéro de séquence) : ce qui ne commence pas ainsi la continue
_START = re.compile(rb"^\d+ \(")
#: au plus, les mots d'une recherche envoyés au serveur
WORDS_MAX = 8
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


_F = TypeVar("_F", bound=Callable[..., Any])


def _said(exc: imaplib.IMAP4.error) -> ImapError:
    if isinstance(exc, imaplib.IMAP4.abort):
        return ImapError(f"la connexion au serveur a été coupée : {exc}"[:300])
    return ImapError(f"le serveur a refusé la commande : {exc}"[:300])


def _translated(method: _F) -> _F:
    """Une commande dont l'erreur d'``imaplib`` (``BAD``, connexion coupée) devient une ``ImapError``."""
    @functools.wraps(method)
    def run(*args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except imaplib.IMAP4.error as exc:
            raise _said(exc) from None
    return run  # type: ignore[return-value]


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


def _ascii(word: str) -> bool:
    return word.isascii() and word.isprintable()


def _astring(word: str) -> str:
    """Un mot ASCII entre guillemets, échappé (RFC 3501)."""
    return '"' + word.replace("\\", "\\\\").replace('"', '\\"') + '"'


def internaldate(text: bytes) -> int:
    """L'instant (µs) d'un ``INTERNALDATE`` ; 0 s'il est illisible."""
    found = _INTERNALDATE.search(text)
    if not found:
        return 0
    day, month, year, hh, mm, ss, sign, oh, om = (g.decode("ascii") for g in found.groups())
    try:
        number = [m.lower() for m in _MONTHS].index(month.lower()) + 1
        offset = (int(oh) * 60 + int(om)) * (1 if sign == "+" else -1)
        at = datetime(int(year), number, int(day), int(hh), int(mm), int(ss), tzinfo=timezone(timedelta(minutes=offset)))
    except ValueError:
        return 0
    return int(at.timestamp() * 1_000_000)


@dataclass(frozen=True, slots=True)
class Head:
    """Ce qu'on lit d'un mail avant de le lire en entier : de quoi le dater, le reconnaître, et ne pas relire celui
    d'un correspondant oublié."""

    uid: int
    #: sa date d'arrivée (µs), 0 si illisible
    at: int
    message_id: str
    #: l'adresse de l'expéditeur, et celles des destinataires (« À », « Cc »), en minuscules
    sender: str = ""
    recipients: tuple[str, ...] = ()


def _head(uid: int, at: int, literal: bytes) -> Head:
    """Un en-tête court lu comme ``parse`` lit le mail : un en-tête plié se déplie, le Message-ID est borné."""
    try:
        msg = BytesHeaderParser(policy=policy.default).parsebytes(literal)
        mid = " ".join(str(msg.get("Message-ID", "") or "").split())[:HEADER_MAX]
        sender = next((a for _, a in addresses(str(msg.get("From", "") or ""))), "")
        to = tuple(a for _, a in addresses(f"{msg.get('To', '') or ''},{msg.get('Cc', '') or ''}"))
    except (TypeError, ValueError, IndexError):
        found = _MESSAGE_ID.search(_FOLD.sub(b" ", literal))
        mid = " ".join(found.group(1).decode("utf-8", "replace").split())[:HEADER_MAX] if found else ""
        sender, to = "", ()
    return Head(uid, at, mid, sender, to)


def _unquote(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


def quoted(name: str) -> str:
    return '"' + utf7.encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


class Session:
    def __init__(self, account: MailAccount, *, timeout: float = TIMEOUT, token: str = "") -> None:
        if account.microsoft and not token:
            raise ImapError(oauth.NOT_SIGNED_IN)
        self.timeout = timeout
        try:  # un accueil refusé ou coupé lève une erreur d'imaplib, pas une OSError
            if account.imap_ssl:
                self.box: imaplib.IMAP4 = imaplib.IMAP4_SSL(account.imap_host, account.imap_port,
                                                            ssl_context=ssl.create_default_context(), timeout=timeout)
            else:
                self.box = imaplib.IMAP4(account.imap_host, account.imap_port, timeout=timeout)
        except imaplib.IMAP4.error as exc:
            raise _said(exc) from None
        if not account.imap_ssl:
            # sans SSL d'emblée : chiffrer avant d'envoyer le mot de passe, si le serveur le propose
            if "STARTTLS" in {str(c).upper() for c in getattr(self.box, "capabilities", ())}:
                try:
                    self._ok(self.box.starttls(ssl_context=ssl.create_default_context()), "STARTTLS refusé")
                except (imaplib.IMAP4.error, ssl.SSLError, OSError) as exc:
                    self.close()
                    raise ImapError(f"le chiffrement (STARTTLS) a échoué : {exc}") from None
        try:
            if account.microsoft:
                self._ok(self.box.authenticate("XOAUTH2", oauth.answer(account.user, token)), "connexion refusée")
            else:
                self._ok(self.box.login(account.user, account.password), "connexion refusée")
        except imaplib.IMAP4.error as exc:
            self.close()
            raise ImapError(f"connexion refusée : {exc}") from None
        self.caps = {str(c).upper() for c in getattr(self.box, "capabilities", ())}
        self.selected = ""
        self.writable = False
        #: le séparateur de la hiérarchie que la liste des dossiers dit (vide : pas encore lue)
        self.delimiter = ""

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
    @_translated
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
            delim = found.group("delim")
            if delim.upper() != b"NIL" and not self.delimiter:
                self.delimiter = _unquote(delim)
            if "\\noselect" in flags or "\\nonexistent" in flags:
                continue
            name = utf7.decode(_unquote(found.group("name")))
            # la réception s'écrit sans casse (RFC 3501) : « Inbox » chez Outlook est l'« INBOX » des réglages, et
            # son curseur ne se perd pas quand la liste se relit
            out.append(("INBOX" if name.upper() == "INBOX" else name, flags))
        return out

    @_translated
    def root(self) -> tuple[str, str]:
        """La racine des dossiers personnels (``INBOX.`` chez certains, souvent rien) et le séparateur de la
        hiérarchie : ce que dit ``NAMESPACE`` (RFC 2342), sinon ce que dit la liste des dossiers."""
        if "NAMESPACE" in self.caps:
            typ, data = self.box.namespace()
            first = data[0] if typ == "OK" and data else None
            found = _NAMESPACE.match(first.strip()) if isinstance(first, bytes) else None
            if found:
                prefix = utf7.decode(_unquote(b'"' + found.group(1) + b'"'))
                delim = _unquote(b'"' + found.group(2) + b'"') if found.group(2) is not None else ""
                if not delim and not self.delimiter:
                    self.folders()
                return prefix, delim or self.delimiter or "/"
        if not self.delimiter:
            self.folders()
        return "", self.delimiter or "/"

    @_translated
    def create(self, name: str) -> None:
        """Crée un dossier (son nom complet sur le serveur), puis s'y abonne : sans abonnement, bien des clients ne le
        montrent pas. Un abonnement refusé n'empêche rien."""
        self._ok(self.box.create(quoted(name)), f"création du dossier « {name} » refusée")
        try:
            self.box.subscribe(quoted(name))
        except imaplib.IMAP4.error as exc:
            if isinstance(exc, imaplib.IMAP4.abort):
                raise

    @_translated
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
    @_translated
    def search(self, criteria: str) -> list[int]:
        data = self._ok(self.box.uid("SEARCH", None, criteria), "recherche refusée")
        return sorted({int(u) for u in (data[0] or b"").split() if u.isdigit()}) if data else []

    @_translated
    def matching(self, words: list[str], senders: list[str]) -> list[int]:
        """Les UID du dossier ouvert dont l'objet, l'expéditeur ou le texte portent chaque mot de ``words``, et dont
        l'expéditeur porte chaque mot de ``senders`` (le serveur ne distingue pas la casse). Les mots ASCII partent
        en une commande ; chaque autre, en littéral UTF-8, une commande par champ."""
        words, senders = words[:WORDS_MAX], senders[:WORDS_MAX]
        plain = [f"OR SUBJECT {_astring(w)} OR FROM {_astring(w)} BODY {_astring(w)}" for w in words if _ascii(w)]
        plain += [f"FROM {_astring(w)}" for w in senders if _ascii(w)]
        found: set[int] | None = set(self.search(" ".join(plain))) if plain else None
        wide = [(("SUBJECT", "FROM", "BODY"), w) for w in words if not _ascii(w)]
        wide += [(("FROM",), w) for w in senders if not _ascii(w)]
        for keys, word in wide:
            if found is not None and not found:
                break
            hits: set[int] = set()
            for key in keys:
                self.box.literal = word.encode("utf-8")
                data = self._ok(self.box.uid("SEARCH", "CHARSET", "UTF-8", key), "recherche refusée")
                hits |= {int(u) for u in (data[0] or b"").split() if u.isdigit()} if data else set()
            found = hits if found is None else found & hits
        return sorted(found or ())

    @_translated
    def heads(self, uids: list[int]) -> list[Head]:
        """L'en-tête court de ces mails (``Head``), sans les lire en entier ni poser ``\\Seen``."""
        out = []
        for i in range(0, len(uids), 200):
            batch = ",".join(str(u) for u in uids[i:i + 200])
            data = self._ok(self.box.uid("FETCH", batch,
                                         "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM TO CC)])"),
                            "lecture refusée")
            # une réponse : ses éléments d'en-tête et son littéral (l'en-tête du mail) ; ce qui suit le littéral
            # (« INTERNALDATE … ) », l'ordre est celui du serveur) arrive à part, et se recolle à elle
            answers: list[list[bytes]] = []
            for item in data or ():
                if isinstance(item, tuple) and isinstance(item[0], bytes | bytearray):
                    literal = item[1] if len(item) > 1 and isinstance(item[1], bytes | bytearray) else b""
                    answers.append([bytes(item[0]), bytes(literal)])
                elif isinstance(item, bytes | bytearray):
                    if _START.match(item) or not answers:
                        answers.append([bytes(item), b""])
                    else:
                        answers[-1][0] += b" " + bytes(item)
            for head, literal in answers:
                uid = _UID.search(head)
                if uid:
                    out.append(_head(int(uid.group(1)), internaldate(head), literal))
        return out

    @_translated
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

    @_translated
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
    @_translated
    def store(self, uid: int, flag: str, on: bool) -> None:
        self._ok(self.box.uid("STORE", str(uid), "+FLAGS" if on else "-FLAGS", f"({flag})"), "drapeau refusé")

    @_translated
    def store_many(self, uids: list[int], flag: str, on: bool) -> None:
        """Un drapeau posé (ou retiré) sur plusieurs mails du dossier ouvert, en une commande."""
        if uids:
            self._ok(self.box.uid("STORE", ",".join(str(u) for u in uids), "+FLAGS" if on else "-FLAGS",
                                  f"({flag})"), "drapeau refusé")

    @_translated
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

    @_translated
    def expunge(self, uid: int) -> None:
        if "UIDPLUS" in self.caps:
            self._ok(self.box.uid("EXPUNGE", str(uid)), "suppression refusée")
        else:
            self._ok(self.box.expunge(), "suppression refusée")

    @_translated
    def append(self, folder: str, raw: bytes, *, seen: bool = True) -> None:
        self.box.sock.settimeout(compose.transfer_timeout(len(raw), self.timeout))
        try:
            self._ok(self.box.append(quoted(folder), "(\\Seen)" if seen else None, None, raw),
                     f"copie dans « {folder} » refusée")
        finally:
            self.box.sock.settimeout(self.timeout)


def _flags(head: bytes) -> frozenset[str]:
    found = _FLAGS.search(head)
    return frozenset(f.lower() for f in found.group(1).decode("ascii", "replace").split()) if found else frozenset()
