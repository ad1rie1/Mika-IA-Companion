"""De faux serveurs IMAP et SMTP qui parlent le vrai protocole (ce que
``imaplib`` et ``smtplib`` envoient), pour éprouver l'adaptateur du courrier.

L'IMAP tient des dossiers (noms en UTF-7 modifié, attributs special-use), des
UID par dossier avec UIDVALIDITY et UIDNEXT, des drapeaux ; il répond à LIST,
SELECT/EXAMINE, UID SEARCH (SINCE, UID n:*, HEADER Message-ID, et SUBJECT, FROM,
BODY, TEXT, OR, CHARSET avec un littéral UTF-8, comme un vrai serveur : sans
casse), UID FETCH (BODY.PEEK[], FLAGS, et INTERNALDATE avec l'en-tête Message-ID),
UID STORE, UID MOVE (si annoncé), UID COPY, EXPUNGE / UID EXPUNGE, APPEND,
CREATE, SUBSCRIBE et NAMESPACE (si annoncé). Un SELECT en lecture seule qui
tenterait d'écrire est refusé : on sait ainsi qu'un relevé ne touche à rien.

Il sait aussi attendre (``IDLE``, RFC 2177, s'il l'annonce) : un mail qu'on lui
livre (``Imap.deliver``) ou un drapeau qu'on change ailleurs (``Imap.touch``) se
dit à chaque connexion qui attend, et ``Imap.cut`` coupe ces connexions comme un
serveur qui les ferme (le courrier en direct, ADR 0308).

Les deux acceptent aussi ``XOAUTH2`` (une boîte Microsoft, ADR 0166) : le jeton
« refuse » est refusé comme Microsoft le fait (un défi JSON, puis un refus).
"""

from __future__ import annotations

import base64
import contextlib
import email
import email.utils
import json
import queue
import re
import socket
import socketserver
import threading
import time
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def raw_mail(uid: int, subject: str, body: str, *, html: bool = False, bulk: bool = False,
             sender: str = "Alice <Alice@Exemple.fr>", to: str = "mika@exemple.fr", cc: str = "",
             reply_to: str = "", in_reply_to: str = "", message_id: str = "",
             date: str = "Mon, 28 Sep 2026 10:00:00 +0200") -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    if cc:
        m["Cc"] = cc
    if reply_to:
        m["Reply-To"] = reply_to
    m["Subject"] = subject
    m["Message-ID"] = message_id or f"<mail-{uid}@exemple.fr>"
    m["Date"] = date
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    if bulk:
        m["List-Unsubscribe"] = "<mailto:stop@exemple.fr>"
    if html:
        m.set_content("<html><head><style>x{}</style></head><body><p>Bonjour <b>Mika</b></p>"
                      "<script>alert(1)</script></body></html>", subtype="html")
    else:
        m.set_content(body)
    return bytes(m)


@dataclass
class Box:
    """Un dossier : ses attributs, son UIDVALIDITY, ses mails (uid → [drapeaux, octets])."""

    attrs: str = ""
    validity: int = 1
    next_uid: int = 1
    mails: dict[int, list] = field(default_factory=dict)

    def add(self, raw: bytes, flags: set[str] | None = None, uid: int | None = None) -> int:
        uid = uid if uid is not None else self.next_uid
        self.mails[uid] = [set(flags or ()), raw]
        self.next_uid = max(self.next_uid, uid + 1)
        return uid


class Imap(socketserver.StreamRequestHandler):
    #: nom décodé → dossier ; ``mailbox`` : raccourci vers INBOX (les anciens tests)
    boxes: dict[str, Box] = {}
    logins: list[tuple[str, str]] = []
    #: les entrées par XOAUTH2 : (utilisateur, jeton)
    bearers: list[tuple[str, str]] = []
    caps = "IMAP4rev1 MOVE UIDPLUS"
    #: ce que le serveur a reçu (pour vérifier qu'un relevé n'écrit rien)
    commands: list[str] = []
    #: ce qu'il laisse passer avant de lire un littéral : un débit lent, vu du client
    stall = 0.0
    #: la racine des dossiers personnels et le séparateur (``NAMESPACE``, s'il est annoncé)
    namespace: tuple[str, str] = ("", "/")
    #: les dossiers auxquels on s'est abonné
    subscribed: list[str] = []
    #: une commande à la fois sur les dossiers (les connexions sont des fils, le test en est un autre)
    lock = threading.Lock()
    #: les connexions qui attendent (``IDLE``) : le dossier qu'elles ont ouvert, et ce qu'on leur dira (une ligne, ou
    #: ``None`` : coupée)
    idling: list[tuple[str, queue.Queue]] = []

    @classmethod
    def reset(cls, inbox: dict[int, bytes] | None = None, *, caps: str = "IMAP4rev1 MOVE UIDPLUS") -> None:
        cls.boxes = {"INBOX": Box(), "Envoyés": Box("\\Sent"), "Archives": Box("\\Archive"),
                     "Corbeille": Box("\\Trash"), "Indésirables": Box("\\Junk")}
        for uid, raw in (inbox or {}).items():
            cls.boxes["INBOX"].add(raw, uid=uid)
        cls.logins, cls.bearers, cls.commands, cls.caps = [], [], [], caps
        cls.namespace, cls.subscribed = ("", "/"), []
        cls.cut()

    # ── attendre (IDLE) ──
    @classmethod
    def _tell(cls, line: str | None, folder: str | None = None) -> None:
        """Dit ``line`` à qui attend sur ce dossier (sans dossier : à tous) — un serveur ne parle que du dossier
        ouvert."""
        for where, waiting in list(cls.idling):
            if folder is None or where == folder:
                waiting.put(("say", line))

    @classmethod
    def deliver(cls, raw: bytes, folder: str = "INBOX", flags: set[str] | None = None) -> int:
        """Un mail arrive dans ce dossier : rend son UID, et le dit à qui attend."""
        with cls.lock:
            box = cls.boxes[folder]
            uid = box.add(raw, flags)
            count = len(box.mails)
        cls._tell(f"* {count} EXISTS", folder)
        return uid

    @classmethod
    def touch(cls, uid: int, flag: str, folder: str = "INBOX") -> None:
        """Un drapeau posé dans un autre client : dit à qui attend."""
        with cls.lock:
            cls.boxes[folder].mails[uid][0].add(flag)
            shown = " ".join(sorted(cls.boxes[folder].mails[uid][0]))
        cls._tell(f"* 1 FETCH (FLAGS ({shown}))", folder)

    @classmethod
    def cut(cls) -> None:
        """Coupe chaque connexion qui attend, comme un serveur qui la ferme."""
        cls._tell(None)

    @classmethod
    def waiting(cls) -> int:
        """Combien de connexions attendent en ce moment."""
        return len(cls.idling)

    def idle(self, tag: str) -> bool:
        """``IDLE`` : on dit ce qui arrive jusqu'au ``DONE`` du client ; ``False`` si la connexion est finie."""
        said: queue.Queue = queue.Queue()

        def read() -> None:  # le ``DONE`` du client (ou rien : la connexion est finie)
            try:
                line = self.rfile.readline()
            except (OSError, ValueError):
                line = b""
            said.put(("line", line))

        self.say("+ idling")
        threading.Thread(target=read, daemon=True).start()
        entry = (self.selected or "", said)
        type(self).idling.append(entry)
        try:
            while True:
                kind, data = said.get()
                if kind == "line":
                    if not data:
                        return False
                    self.say(f"{tag} OK IDLE terminated")
                    return True
                if data is None:  # coupée par le serveur : la prise d'abord (le fil qui lit tient son tampon)
                    with contextlib.suppress(OSError):
                        self.request.shutdown(socket.SHUT_RDWR)
                    return False
                self.say(data)
        finally:
            type(self).idling.remove(entry)

    @classmethod
    def set_mailbox(cls, mailbox: dict[int, bytes]) -> None:
        cls.reset(mailbox)

    def say(self, line: str | bytes) -> None:
        self.wfile.write(line if isinstance(line, bytes) else line.encode() + b"\r\n")

    def handle(self) -> None:
        from mika.adapters.mail import utf7

        self.selected: str | None = None
        self.readonly = True
        self.say("* OK faux IMAP prêt")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode().rstrip("\r\n")
            literal = re.search(r"\{(\d+)\}$", line)
            data = b""
            if literal:
                self.say("+ vas-y")
                time.sleep(self.stall)
                data = self.rfile.read(int(literal.group(1)))
                self.rfile.readline()
            tag, _, rest = line.partition(" ")
            cmd = rest.upper()
            type(self).commands.append(rest)
            if cmd == "IDLE" and "IDLE" in type(self).caps.split():
                if not self.idle(tag):
                    return
                continue
            try:
                with type(self).lock:
                    if not self.command(tag, rest, cmd, data, utf7):
                        return
            except (KeyError, ValueError, IndexError, AssertionError) as exc:
                self.say(f"{tag} NO {exc}")

    def _name(self, text: str, utf7) -> str:
        text = text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return utf7.decode(text)

    def _uids(self, spec: str, box: Box) -> list[int]:
        out = []
        for part in spec.split(","):
            if ":" in part:
                lo, hi = part.split(":")
                top = max(box.mails, default=0) if hi == "*" else int(hi)
                start = int(lo)
                found = [u for u in box.mails if start <= u <= top]
                if hi == "*" and not found and box.mails:
                    found = [max(box.mails)]  # le « n:* » d'IMAP rend au moins le dernier
                out += found
            elif int(part) in box.mails:
                out.append(int(part))
        return sorted(set(out))

    def command(self, tag: str, rest: str, cmd: str, data: bytes, utf7) -> bool:
        cls = type(self)
        box = cls.boxes.get(self.selected) if self.selected is not None else None
        if cmd.startswith("CAPABILITY"):
            self.say(f"* CAPABILITY {cls.caps}")
        elif cmd.startswith("LOGIN"):
            _, user, password = rest.split(" ", 2)
            cls.logins.append((user.strip('"'), password.strip('"')))
        elif cmd.startswith("AUTHENTICATE XOAUTH2"):
            self.say("+ ")
            user, token = bearer(self.rfile.readline())
            if token == "refuse":
                self.say("+ " + refusal())
                self.rfile.readline()  # la réponse vide qui clôt l'échange
                self.say(f"{tag} NO AUTHENTICATE failed.")
                return True
            cls.bearers.append((user, token))
        elif cmd.startswith("LIST"):
            for name, b in cls.boxes.items():
                attrs = f"\\HasNoChildren {b.attrs}".strip()
                self.say(f'* LIST ({attrs}) "{cls.namespace[1]}" "{utf7.encode(name)}"')
        elif cmd.startswith("NAMESPACE"):
            if "NAMESPACE" not in cls.caps:
                self.say(f"{tag} BAD inconnu")
                return True
            self.say(f'* NAMESPACE (("{cls.namespace[0]}" "{cls.namespace[1]}")) NIL NIL')
        elif cmd.startswith("CREATE"):
            name = self._name(rest.split(" ", 1)[1], utf7)
            if name in cls.boxes:
                self.say(f"{tag} NO [ALREADYEXISTS] il existe")
                return True
            prefix = cls.namespace[0]
            if prefix and not name.startswith(prefix) and name.upper() != "INBOX":
                self.say(f"{tag} NO [CANNOT] un dossier commence par {prefix}")
                return True
            cls.boxes[name] = Box()
        elif cmd.startswith("SUBSCRIBE"):
            cls.subscribed.append(self._name(rest.split(" ", 1)[1], utf7))
        elif cmd.startswith(("SELECT", "EXAMINE")):
            name = self._name(rest.split(" ", 1)[1], utf7)
            if name not in cls.boxes:
                self.say(f"{tag} NO dossier inconnu")
                return True
            self.selected, self.readonly = name, cmd.startswith("EXAMINE")
            b = cls.boxes[name]
            self.say(f"* {len(b.mails)} EXISTS")
            self.say(f"* OK [UIDVALIDITY {b.validity}] valide")
            self.say(f"* OK [UIDNEXT {b.next_uid}] prochain")
            self.say(f"{tag} OK [{'READ-ONLY' if self.readonly else 'READ-WRITE'}] fait")
            return True
        elif cmd.startswith("UID SEARCH"):
            assert box is not None
            crit = rest.split(" ", 2)[2]
            if crit.upper().startswith("UID "):
                found = self._uids(crit.split(" ", 1)[1], box)
            elif crit.upper().startswith("HEADER MESSAGE-ID"):
                wanted = crit.split(" ", 2)[2].strip('"')
                found = [u for u, (_, raw_) in box.mails.items() if wanted.encode() in raw_]
            elif re.search(r"\b(SUBJECT|FROM|BODY|TEXT|OR|CHARSET)\b", crit, re.I):
                tokens = _tokens(crit, data)
                found = sorted(u for u, (_, raw_) in box.mails.items() if _all_match(tokens, _fields(raw_)))
            else:
                found = sorted(box.mails)
            self.say("* SEARCH " + " ".join(str(u) for u in found))
        elif cmd.startswith("UID FETCH"):
            assert box is not None
            _, _, spec, what = rest.split(" ", 3)
            for i, uid in enumerate(self._uids(spec, box), start=1):
                flags, raw_ = box.mails[uid]
                shown = " ".join(sorted(flags))
                if "INTERNALDATE" in what.upper():  # sa date d'arrivée (celle de son en-tête) et son Message-ID
                    head = _message_id_header(raw_)
                    self.say(f"* {i} FETCH (UID {uid} INTERNALDATE \"{_internaldate(raw_)}\" "
                             f"BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(head)}}}".encode() + b"\r\n" + head + b")\r\n")
                elif "BODY.PEEK[]" in what.upper():
                    self.say(f"* {i} FETCH (UID {uid} FLAGS ({shown}) BODY[] {{{len(raw_)}}}".encode() + b"\r\n"
                             + raw_ + b")\r\n")
                elif "RFC822" in what.upper():  # l'ancienne lecture : pose \Seen, comme un vrai serveur
                    flags.add("\\Seen")
                    self.say(f"* {i} FETCH (UID {uid} RFC822 {{{len(raw_)}}}".encode() + b"\r\n" + raw_ + b")\r\n")
                else:
                    self.say(f"* {i} FETCH (UID {uid} FLAGS ({shown}))")
        elif cmd.startswith("UID STORE"):
            assert box is not None and not self.readonly, "écriture dans un dossier ouvert en lecture seule"
            _, _, spec, op, flags = rest.split(" ", 4)
            wanted = set(flags.strip("()").split())
            for uid in self._uids(spec, box):
                if op.upper().startswith("+"):
                    box.mails[uid][0] |= wanted
                else:
                    box.mails[uid][0] -= wanted
        elif cmd.startswith(("UID MOVE", "UID COPY")):
            assert box is not None
            if cmd.startswith("UID MOVE"):
                assert not self.readonly and "MOVE" in cls.caps
            _, verb, spec, dest = rest.split(" ", 3)
            target = cls.boxes[self._name(dest, utf7)]
            for uid in self._uids(spec, box):
                flags, raw_ = box.mails[uid]
                new = target.add(raw_, set(flags) - {"\\Deleted"})
                self.say(f"* OK [COPYUID {target.validity} {uid} {new}] fait")
                if verb.upper() == "MOVE":
                    del box.mails[uid]
        elif cmd.startswith(("UID EXPUNGE", "EXPUNGE")):
            assert box is not None and not self.readonly
            for uid in [u for u, (f, _) in box.mails.items() if "\\Deleted" in f]:
                del box.mails[uid]
        elif cmd.startswith("APPEND"):
            name = self._name(re.match(r'APPEND ("(?:[^"\\]|\\.)*"|\S+)', rest, re.I).group(1), utf7)
            flags = set(re.search(r"\(([^)]*)\)", rest).group(1).split()) if "(" in rest else set()
            cls.boxes[name].add(data, flags)
        elif cmd.startswith("LOGOUT"):
            self.say("* BYE")
            self.say(f"{tag} OK au revoir")
            return False
        else:
            self.say(f"{tag} BAD inconnu")
            return True
        self.say(f"{tag} OK fait")
        return True


def _tokens(text: str, literal: bytes) -> list[str]:
    """Les mots d'un critère de recherche : un mot, une chaîne entre guillemets, ou le littéral (``{n}``)."""
    out, i = [], 0
    while i < len(text):
        if text[i] == " ":
            i += 1
        elif text[i] == '"':
            j, buf = i + 1, []
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                buf.append(text[j])
                j += 1
            out.append("\x00" + "".join(buf))
            i = j + 1
        elif text[i] == "{":
            out.append("\x00" + literal.decode("utf-8"))
            i = text.index("}", i) + 1
        else:
            j = text.find(" ", i)
            j = len(text) if j < 0 else j
            out.append(text[i:j])
            i = j
    return out


def _fields(raw: bytes) -> dict[str, str]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    body = msg.get_body(("plain", "html"))
    return {"SUBJECT": str(msg["Subject"] or ""), "FROM": str(msg["From"] or ""),
            "BODY": body.get_content() if body is not None else "", "TEXT": raw.decode("utf-8", "replace")}


def _one(tokens: list[str], at: int, fields: dict[str, str]) -> tuple[bool, int]:
    key = tokens[at].upper()
    if key == "OR":
        first, at = _one(tokens, at + 1, fields)
        second, at = _one(tokens, at, fields)
        return first or second, at
    if key == "CHARSET":
        return True, at + 2
    if key in fields:
        return tokens[at + 1].lstrip("\x00").casefold() in fields[key].casefold(), at + 2
    if key == "SINCE":
        return True, at + 2
    return True, at + 1  # ALL, ce que ce faux serveur ne juge pas


def _all_match(tokens: list[str], fields: dict[str, str]) -> bool:
    at, ok = 0, True
    while at < len(tokens):
        matched, at = _one(tokens, at, fields)
        ok = ok and matched
    return ok


def _internaldate(raw: bytes) -> str:
    msg = email.message_from_bytes(raw, policy=policy.default)
    when = email.utils.parsedate_to_datetime(str(msg["Date"]))
    offset = when.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset is not None else 0
    sign = "+" if minutes >= 0 else "-"
    return (f"{when.day:02d}-{_MONTHS[when.month - 1]}-{when.year} {when:%H:%M:%S} "
            f"{sign}{abs(minutes) // 60:02d}{abs(minutes) % 60:02d}")


def _message_id_header(raw: bytes) -> bytes:
    msg = email.message_from_bytes(raw, policy=policy.default)
    return f"Message-ID: {msg['Message-ID']}\r\n\r\n".encode() if msg["Message-ID"] else b"\r\n"


class Smtp(socketserver.StreamRequestHandler):
    received: list[tuple[str, list[str], bytes, str]] = []
    #: ce qu'il laisse passer avant de lire le mail : un débit lent, vu du client
    stall = 0.0

    def say(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")

    def handle(self) -> None:
        self.say("220 faux SMTP")
        sender, rcpts, auth = "", [], ""
        while True:
            line = self.rfile.readline().decode().strip()
            if not line:
                return
            up = line.upper()
            if up.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-faux\r\n250 AUTH PLAIN XOAUTH2\r\n")
            elif up.startswith("AUTH PLAIN"):
                auth = base64.b64decode(line.split()[-1]).decode()
                self.say("235 ok")
            elif up.startswith("AUTH XOAUTH2"):
                _user, token = bearer(line.split()[-1].encode())
                if token == "refuse":
                    self.say("334 " + refusal())
                    self.rfile.readline()
                    self.say("535 5.7.3 Authentication unsuccessful")
                    continue
                auth = base64.b64decode(line.split()[-1]).decode()
                self.say("235 ok")
            elif up.startswith("MAIL FROM"):
                sender = line.split(":", 1)[1].strip()
                self.say("250 ok")
            elif up.startswith("RCPT TO"):
                rcpts.append(line.split(":", 1)[1].strip())
                self.say("250 ok")
            elif up == "DATA":
                self.say("354 vas-y")
                time.sleep(self.stall)
                lines = []
                while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                    lines.append(chunk)
                self.received.append((sender, rcpts, b"".join(lines), auth))
                self.say("250 reçu")
            elif up == "QUIT":
                self.say("221 salut")
                return
            else:
                self.say("250 ok")


def bearer(line: bytes) -> tuple[str, str]:
    """L'utilisateur et le jeton d'une réponse ``XOAUTH2`` (en base64)."""
    said = base64.b64decode(line.strip()).decode()
    fields = dict(part.split("=", 1) for part in said.split("\x01") if "=" in part)
    return fields.get("user", ""), fields.get("auth", "").removeprefix("Bearer ")


def refusal() -> str:
    """Le défi par lequel Microsoft dit qu'un jeton ne passe pas."""
    return base64.b64encode(json.dumps({"status": "401", "schemes": "bearer"}).encode()).decode()


def serve(handler) -> socketserver.ThreadingTCPServer:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
