"""Le courrier et les flux réels, contre de faux serveurs (IMAP, SMTP, HTTP)
qui parlent le vrai protocole.

- IMAP : chaque mail n'est rendu qu'une fois ; UID et non numéro ; texte
  brut extrait (même d'un mail HTML) ; un envoi de masse est reconnu ;
- SMTP : l'envoi s'authentifie et part tel qu'écrit ;
- flux : RSS et Atom, un article rendu une fois, les archives ignorées au
  premier relevé ; un article se lit par son identifiant (jamais une adresse
  arbitraire), sans scripts.
"""

from __future__ import annotations

import asyncio
import base64
import socketserver
import threading
from datetime import UTC, datetime
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mika.adapters.feeds import HttpFeeds
from mika.adapters.mail import ImapSmtpMail, MailConfig


def go(coro):
    return asyncio.run(coro)


# ── Un faux serveur IMAP ──────────────────────────────────────────────────


def raw_mail(uid: int, subject: str, body: str, *, html: bool = False, bulk: bool = False) -> bytes:
    m = EmailMessage()
    m["From"] = "Alice <Alice@Exemple.fr>"
    m["To"] = "mika@exemple.fr"
    m["Subject"] = subject
    m["Message-ID"] = f"<mail-{uid}@exemple.fr>"
    m["Date"] = "Mon, 28 Sep 2026 10:00:00 +0200"
    if bulk:
        m["List-Unsubscribe"] = "<mailto:stop@exemple.fr>"
    if html:
        m.set_content("<html><head><style>x{}</style></head><body><p>Bonjour <b>Mika</b></p>"
                      "<script>alert(1)</script></body></html>", subtype="html")
    else:
        m.set_content(body)
    return bytes(m)


class Imap(socketserver.StreamRequestHandler):
    mailbox: dict[int, bytes] = {}
    logins: list[tuple[str, str]] = []

    def say(self, line: str | bytes) -> None:
        self.wfile.write(line if isinstance(line, bytes) else line.encode() + b"\r\n")

    def handle(self) -> None:
        self.say("* OK faux IMAP prêt")
        while True:
            line = self.rfile.readline().decode().strip()
            if not line:
                return
            tag, _, rest = line.partition(" ")
            cmd = rest.upper()
            if cmd.startswith("CAPABILITY"):
                self.say("* CAPABILITY IMAP4rev1")
                self.say(f"{tag} OK fait")
            elif cmd.startswith("LOGIN"):
                _, user, password = rest.split(" ", 2)
                self.logins.append((user.strip('"'), password.strip('"')))
                self.say(f"{tag} OK connecté")
            elif cmd.startswith(("SELECT", "EXAMINE")):
                self.say(f"* {len(self.mailbox)} EXISTS")
                self.say(f"{tag} OK [READ-ONLY] fait")
            elif cmd.startswith("UID SEARCH"):
                self.say("* SEARCH " + " ".join(str(u) for u in sorted(self.mailbox)))
                self.say(f"{tag} OK fait")
            elif cmd.startswith("UID FETCH"):
                uid = int(rest.split()[2])
                data = self.mailbox[uid]
                self.say(f"* {uid} FETCH (UID {uid} RFC822 {{{len(data)}}}".encode() + b"\r\n" + data + b")\r\n")
                self.say(f"{tag} OK fait")
            elif cmd.startswith("LOGOUT"):
                self.say("* BYE")
                self.say(f"{tag} OK au revoir")
                return
            else:
                self.say(f"{tag} BAD inconnu")


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


@pytest.fixture
def servers():
    Imap.mailbox = {3: raw_mail(3, "Coucou", "Tu viens samedi ?"), 7: raw_mail(7, "Lettre", "", bulk=True)}
    Imap.logins, Smtp.received = [], []
    imap, smtp = serve(Imap), serve(Smtp)
    yield imap.server_address[1], smtp.server_address[1]
    imap.shutdown()
    smtp.shutdown()


def config(imap_port: int, smtp_port: int) -> MailConfig:
    return MailConfig(address="mika@exemple.fr", imap_host="127.0.0.1", imap_port=imap_port, imap_ssl=False,
                      user="mika", password="secret", smtp_host="127.0.0.1", smtp_port=smtp_port,
                      smtp_security="none", since_days=7)


def test_imap_hands_each_mail_once_as_plain_text(tmp_path, servers):
    imap_port, smtp_port = servers
    box = ImapSmtpMail(lambda: config(imap_port, smtp_port), tmp_path / "mail.db",
                       now=lambda: datetime(2026, 9, 28, 12, tzinfo=UTC))
    first = go(box.fetch_new(10))
    assert [m.message_id for m in first] == ["<mail-3@exemple.fr>", "<mail-7@exemple.fr>"]
    coucou, lettre = first
    assert coucou.address == "alice@exemple.fr" and coucou.subject == "Coucou" and "samedi" in coucou.body
    assert not coucou.bulk and lettre.bulk and coucou.date > 0
    assert go(box.fetch_new(10)) == []  # déjà rendus
    Imap.mailbox[9] = raw_mail(9, "En HTML", "", html=True)
    [html] = go(box.fetch_new(10))
    assert "Bonjour Mika" in html.body and "alert" not in html.body and "<" not in html.body
    assert go(box.get("<mail-3@exemple.fr>")) == coucou and len(go(box.recent(10))) == 3
    assert Imap.logins[0] == ("mika", "secret")


def test_smtp_sends_as_written(tmp_path, servers):
    imap_port, smtp_port = servers
    box = ImapSmtpMail(lambda: config(imap_port, smtp_port), tmp_path / "mail.db")
    message_id = go(box.send("bob@exemple.fr", "Samedi", "Oui, je viens !", in_reply_to="<mail-3@exemple.fr>"))
    [(sender, rcpts, data, auth)] = Smtp.received
    assert "mika@exemple.fr" in sender and rcpts == ["<bob@exemple.fr>"] and "\0mika\0secret" == auth
    assert b"Oui, je viens !" in data and b"In-Reply-To: <mail-3@exemple.fr>" in data
    assert message_id.encode() in data


def test_an_unconfigured_box_reads_nothing(tmp_path):
    box = ImapSmtpMail(lambda: MailConfig(), tmp_path / "mail.db")
    assert not box.configured() and go(box.fetch_new(10)) == []


# ── Un faux site : flux et articles ───────────────────────────────────────

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Le Journal</title>{items}</channel></rss>"""
ITEM = ("<item><title>Titre {n}</title><link>http://127.0.0.1:{port}/article/{n}</link><guid>g{n}</guid>"
        "<description>&lt;b&gt;Résumé {n}&lt;/b&gt;</description><pubDate>Mon, 28 Sep 2026 {h:02d}:00:00 +0000"
        "</pubDate></item>")
ATOM = ("<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><title>Le Blog</title>"
        "<entry><title>Un billet</title><id>tag:b,1</id><link href='http://127.0.0.1:{port}/article/9'/>"
        "<updated>2026-09-28T09:00:00Z</updated><summary>Du pixel art</summary></entry></feed>")


class Site(BaseHTTPRequestHandler):
    items: list[int] = []

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        port = self.server.server_address[1]
        if self.path == "/flux.xml":
            body = RSS.format(items="".join(ITEM.format(n=n, port=port, h=n % 24) for n in self.items))
        elif self.path == "/atom.xml":
            body = ATOM.format(port=port)
        elif self.path.startswith("/article/"):
            body = ("<html><head><script>voler()</script></head><body><h1>Article</h1><p>Le pixel art revient."
                    "</p></body></html>")
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def site():
    Site.items = list(range(1, 9))  # huit articles d'archives
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_feeds_hand_new_entries_once_and_skip_the_archives(tmp_path, site):
    feeds = HttpFeeds(lambda: [f"{site}/flux.xml", f"{site}/atom.xml", f"{site}/absent.xml"], tmp_path / "f.db")
    first = go(feeds.poll(30))
    rss = [e for e in first if e.feed == "Le Journal"]
    assert [e.title for e in rss] == ["Titre 8", "Titre 7", "Titre 6", "Titre 5", "Titre 4"]  # pas les archives
    assert rss[0].summary == "Résumé 8" and any(e.feed == "Le Blog" for e in first)
    assert go(feeds.poll(30)) == []
    Site.items.append(20)
    [fresh] = go(feeds.poll(30))
    assert fresh.title == "Titre 20"
    text = go(feeds.article(fresh.id))
    assert "Le pixel art revient." in text and "voler" not in text
    assert go(feeds.article("une-adresse-inventée")) == ""  # seulement un article relevé
