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
    # un flux choisi par un opérateur peut être local ; l'article qu'il désigne ne l'est jamais : un flux
    # peut mentir, et un lien vers la machine elle-même (127.0.0.1) n'est pas suivi
    assert fresh.link.startswith("http://127.0.0.1:") and go(feeds.article(fresh.id)) == ""
    assert go(feeds.article("une-adresse-inventée")) == ""  # seulement un article relevé
    # chaque relevé se note : la console dit quel flux ne répond plus, et pourquoi (jamais son adresse entière)
    health = {h["title"] or h["url"].rsplit("/", 1)[-1]: h for h in feeds.health()}
    journal, blog, absent = health["Le Journal"], health["Le Blog"], health["absent.xml"]
    assert not journal["error"] and journal["failures"] == 0 and journal["ok_at"] and journal["items"] == 9
    assert journal["added"] == 1 and journal["kept"] == 9  # le dernier relevé a apporté « Titre 20 »
    assert not blog["error"] and blog["items"] == 1
    assert absent["error"] == "le serveur répond 404" and absent["failures"] == 3 and not absent["ok_at"]
    assert absent["attempted_at"] and absent["kept"] == 0
    assert feeds.cached_count() == 10
    feeds._feeds = lambda: []  # un abonnement retiré ne fait pas disparaître ses articles de la consultation
    assert feeds.health() == [] and feeds.cached_count() == len(feeds.cached(100)) == 10


def test_a_feed_cache_from_before_feed_health_is_completed(tmp_path, site):
    import sqlite3

    old = sqlite3.connect(str(tmp_path / "f.db"))
    old.executescript("CREATE TABLE feeds(url TEXT PRIMARY KEY, polled INTEGER DEFAULT 0);"
                      f"INSERT INTO feeds VALUES('{site}/flux.xml', 1);")
    old.commit()
    old.close()
    feeds = HttpFeeds(lambda: [f"{site}/flux.xml"], tmp_path / "f.db")
    assert feeds.health()[0]["attempted_at"] == 0  # colonnes ajoutées, rien de faux inventé
    assert go(feeds.poll(30)) and feeds.health()[0]["ok_at"]  # déjà relevé : tout ce qui paraît est neuf


# ── Un flux peut mentir : un article ne mène jamais à une machine privée (EDG-4, CON-2) ──

#: un faux DNS : des noms publics, un nom qui pointe vers le réseau local, un nom qui donne les deux
DNS = {"journal.example": ["93.184.216.34"], "cdn.example": ["151.101.1.69"], "interne.example": ["10.0.0.5"],
       "rebind.example": ["93.184.216.35", "127.0.0.1"], "prive.example": ["93.184.216.36"]}
LIES = {  # l'article n° → son lien, tel que le flux le donne
    1: "https://journal.example/a/1",  # un vrai article public
    2: "https://journal.example/vers-local",  # redirige vers la machine elle-même
    3: "http://169.254.169.254/latest/meta-data/iam/",  # les métadonnées d'un nuage
    4: "https://interne.example/admin",  # un nom public qui pointe vers le réseau local
    5: "https://rebind.example/a",  # un nom qui répond public ET local
    6: "https://journal.example/r1",  # quatre redirections
    7: "https://journal.example/vers-cdn",  # une redirection vers une autre machine publique
    8: "http://[::ffff:127.0.0.1]/secret",  # la boucle locale, déguisée en IPv6
}


async def resolver(host: str, port: int) -> list[str]:
    if host not in DNS:
        raise OSError("nom inconnu")
    return DNS[host]


def lying_site(asked: list[tuple[str, str]]):
    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        host = req.headers.get("host", "")
        asked.append((req.url.host, host))
        path = req.url.path
        if host == "journal.example" and path == "/flux.xml":
            items = "".join(f"<item><title>Article {n}</title><link>{link}</link><guid>a{n}</guid></item>"
                            for n, link in LIES.items())
            return httpx.Response(200, content=f"<rss><channel><title>Le Journal</title>{items}</channel></rss>")
        if host == "journal.example" and path == "/vers-local":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/interne/secret"})
        if host == "journal.example" and path.startswith("/r"):
            return httpx.Response(302, headers={"location": f"/r{int(path[2:]) + 1}"})
        if host == "journal.example" and path == "/vers-cdn":
            return httpx.Response(301, headers={"location": "https://cdn.example/b"})
        if host == "prive.example":
            return httpx.Response(200, content="<rss><channel><item><title>Sans titre de flux</title>"
                                               "<guid>p1</guid></item></channel></rss>")
        if host in ("journal.example", "cdn.example"):
            return httpx.Response(200, html=f"<html><body><p>Le texte public de {host}{path}.</p></body></html>")
        return httpx.Response(200, html="<html>CLE_INTERNE=secret ; AccessKeyId=AKIA…</html>")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_an_article_never_leads_to_a_private_machine_but_a_public_one_is_read(tmp_path):
    asked: list[tuple[str, str]] = []
    feeds = HttpFeeds(lambda: ["https://journal.example/flux.xml"], tmp_path / "f.db",
                      client=lying_site(asked), resolve=resolver)

    async def main():
        await feeds.poll(30)
        entries = {e.title: e for e in feeds.cached(30)}
        return {n: await feeds.article(entries[f"Article {n}"].id) for n in LIES}

    texts = go(main())
    # un vrai flux public passe : l'article est lu, et la connexion va vers l'adresse vérifiée (pas une seconde
    # résolution qu'un DNS pourrait retourner), le nom restant dans « Host »
    assert texts[1] == "Le texte public de journal.example/a/1."
    assert ("93.184.216.34", "journal.example") in asked
    assert texts[7] == "Le texte public de cdn.example/b."  # une redirection vers une machine publique
    for n in (2, 3, 4, 5, 6, 8):  # la boucle locale, les métadonnées, le réseau local, le DNS menteur, 4 sauts
        assert texts[n] == "", n
    assert not any(ip in ("127.0.0.1", "169.254.169.254", "10.0.0.5", "::ffff:127.0.0.1") for ip, _ in asked)
    assert all("CLE_INTERNE" not in t for t in texts.values())


def test_a_feed_that_redirects_to_the_local_network_is_refused_and_says_why(tmp_path):
    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "journal.example":
            return httpx.Response(302, headers={"location": "http://10.0.0.5/flux.xml"})
        return httpx.Response(200, content=b"<rss><channel><title>Interne</title></channel></rss>")

    feeds = HttpFeeds(lambda: ["https://journal.example/flux.xml"], tmp_path / "f.db",
                      client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), resolve=resolver)
    assert go(feeds.poll(10)) == []
    [health] = feeds.health()
    assert health["error"].startswith("refusé") and "privée" in health["error"]


def test_a_feed_without_a_title_is_never_named_by_its_token(tmp_path):
    feeds = HttpFeeds(lambda: ["https://prive.example/flux.xml?token=SECRET-ABC123"], tmp_path / "f.db",
                      client=lying_site([]), resolve=resolver)
    [entry] = go(feeds.poll(10))
    assert "SECRET" not in entry.feed and entry.feed == "https://prive.example/flux.xml?token=…"
    assert all("SECRET" not in str(h) for h in feeds.health()) and "SECRET" not in str(feeds.followed())


def test_a_server_that_drips_its_answer_does_not_hold_a_poll_beyond_its_deadline(tmp_path):
    import time

    async def drip(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/rss+xml\r\nTransfer-Encoding: chunked\r\n\r\n")
        try:
            for _ in range(40):  # un octet toutes les 0,25 s : chaque lecture arrive avant le délai de lecture
                writer.write(b"1\r\n \r\n")
                await writer.drain()
                await asyncio.sleep(0.25)
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def main():
        server = await asyncio.start_server(drip, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        feeds = HttpFeeds(lambda: [f"http://127.0.0.1:{port}/flux"], tmp_path / "f.db", timeout_s=1.0)
        started = time.monotonic()
        await feeds.poll(10)
        took = time.monotonic() - started
        server.close()
        return took, feeds.health()[0]["error"]

    took, error = go(main())
    assert took < 3.0 and error.startswith("trop long")  # sans délai total : dix secondes, au choix du serveur
