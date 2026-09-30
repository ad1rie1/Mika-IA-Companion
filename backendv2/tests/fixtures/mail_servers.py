"""De faux serveurs IMAP et SMTP qui parlent le vrai protocole (ce que
``imaplib`` et ``smtplib`` envoient), pour éprouver l'adaptateur du courrier.

L'IMAP tient des dossiers (noms en UTF-7 modifié, attributs special-use), des
UID par dossier avec UIDVALIDITY et UIDNEXT, des drapeaux ; il répond à LIST,
SELECT/EXAMINE, UID SEARCH (SINCE, UID n:*, HEADER Message-ID), UID FETCH
(BODY.PEEK[] et FLAGS), UID STORE, UID MOVE (si annoncé), UID COPY,
EXPUNGE / UID EXPUNGE et APPEND. Un SELECT en lecture seule qui tenterait
d'écrire est refusé : on sait ainsi qu'un relevé ne touche à rien.
"""

from __future__ import annotations

import base64
import re
import socketserver
import threading
from dataclasses import dataclass, field
from email.message import EmailMessage


def raw_mail(uid: int, subject: str, body: str, *, html: bool = False, bulk: bool = False,
             sender: str = "Alice <Alice@Exemple.fr>", to: str = "mika@exemple.fr", cc: str = "",
             reply_to: str = "", in_reply_to: str = "", message_id: str = "") -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    if cc:
        m["Cc"] = cc
    if reply_to:
        m["Reply-To"] = reply_to
    m["Subject"] = subject
    m["Message-ID"] = message_id or f"<mail-{uid}@exemple.fr>"
    m["Date"] = "Mon, 28 Sep 2026 10:00:00 +0200"
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
    caps = "IMAP4rev1 MOVE UIDPLUS"
    #: ce que le serveur a reçu (pour vérifier qu'un relevé n'écrit rien)
    commands: list[str] = []

    @classmethod
    def reset(cls, inbox: dict[int, bytes] | None = None, *, caps: str = "IMAP4rev1 MOVE UIDPLUS") -> None:
        cls.boxes = {"INBOX": Box(), "Envoyés": Box("\\Sent"), "Archives": Box("\\Archive"),
                     "Corbeille": Box("\\Trash"), "Indésirables": Box("\\Junk")}
        for uid, raw in (inbox or {}).items():
            cls.boxes["INBOX"].add(raw, uid=uid)
        cls.logins, cls.commands, cls.caps = [], [], caps

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
                data = self.rfile.read(int(literal.group(1)))
                self.rfile.readline()
            tag, _, rest = line.partition(" ")
            cmd = rest.upper()
            type(self).commands.append(rest)
            try:
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
        elif cmd.startswith("LIST"):
            for name, b in cls.boxes.items():
                attrs = f"\\HasNoChildren {b.attrs}".strip()
                self.say(f'* LIST ({attrs}) "/" "{utf7.encode(name)}"')
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
            else:
                found = sorted(box.mails)
            self.say("* SEARCH " + " ".join(str(u) for u in found))
        elif cmd.startswith("UID FETCH"):
            assert box is not None
            _, _, spec, what = rest.split(" ", 3)
            for i, uid in enumerate(self._uids(spec, box), start=1):
                flags, raw_ = box.mails[uid]
                shown = " ".join(sorted(flags))
                if "BODY.PEEK[]" in what.upper():
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



class Smtp(socketserver.StreamRequestHandler):
    received: list[tuple[str, list[str], bytes, str]] = []

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
                self.wfile.write(b"250-faux\r\n250 AUTH PLAIN\r\n")
            elif up.startswith("AUTH PLAIN"):
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
                data = b""
                while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                    data += chunk
                self.received.append((sender, rcpts, data, auth))
                self.say("250 reçu")
            elif up == "QUIT":
                self.say("221 salut")
                return
            else:
                self.say("250 ok")


def serve(handler) -> socketserver.ThreadingTCPServer:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
