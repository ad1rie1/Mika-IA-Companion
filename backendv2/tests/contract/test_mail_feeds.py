"""Les flux réels, contre un faux site qui parle le vrai protocole (le courrier
réel a ses propres épreuves : ``test_mail_imap.py``).

- flux : RSS et Atom, un article rendu une fois, les archives ignorées au
  premier relevé ; un article se lit par son identifiant (jamais une adresse
  arbitraire), sans scripts.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mika.adapters.feeds import HttpFeeds


def go(coro):
    return asyncio.run(coro)


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
