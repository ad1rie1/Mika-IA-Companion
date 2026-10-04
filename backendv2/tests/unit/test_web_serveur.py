"""Le serveur du plugin ``web``, hors ligne : DuckDuckGo et les pages sont simulés (``Web(fetch=…)``), le temps aussi.

- les résultats se lisent comme la vraie page HTML les montre : titre, adresse, extrait ; publicités écartées,
  redirections défaites, doublons retirés, nombre borné ;
- DuckDuckGo n'est pas harcelé : recherches espacées, comptées à la minute, une même recherche servie du cache,
  et un défi anti-robot met la recherche en pause (dite, avec l'heure de reprise) au lieu d'insister ;
- une page se lit sans ses menus ni ses scripts, le principal d'abord, par morceaux ; ce qui n'est pas du web
  public (cette machine, le réseau local, un fichier, des identifiants) ne se lit pas ; plusieurs pages se lisent
  en même temps quand le plugin le permet, et pas sinon ;
- ses réglages viennent de l'environnement que le plugin pose ; une valeur illisible garde son défaut ;
- le protocole : poignée de main, deux outils, un échec d'outil est un ``isError`` en français, une requête
  annulée en vol ne reçoit rien ; la sortie d'erreur ne dit jamais ce qui a été cherché.
"""

from __future__ import annotations

import io
import json
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from mika.plugins.web import serveur as s

RESULTS = """<html><body><div class="serp__results"><div class="results">
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://www.exemple.fr/a">Premier <b>titre</b></a></h2>
    <a class="result__snippet" href="https://www.exemple.fr/a">Un extrait avec du <b>gras</b> et des &quot;guillemets&quot;.</a>
  </div>
</div>
<div class="result results_links results_links_deep result--ad">
  <div class="links_main result__body">
    <h2 class="result__title"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Une publicité</a></h2>
    <a class="result__snippet">Achetez</a>
  </div>
</div>
<div class="result results_links result--ad">
  <div class="links_main result__body">
    <h2 class="result__title"><a class="result__a" href="https://boutique.example.com/promo">Une autre publicité</a></h2>
  </div>
</div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main result__body">
    <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwiki.exemple.org%2Fpage%3Fx%3D1&amp;rut=abc">Deuxième</a></h2>
    <div class="result__snippet">Un extrait en div.</div>
  </div>
</div>
<div class="result results_links web-result ">
  <div class="links_main result__body">
    <h2 class="result__title"><a class="result__a" href="https://www.exemple.fr/a">Premier titre (doublon)</a></h2>
  </div>
</div>
<div class="result results_links web-result ">
  <div class="links_main result__body">
    <h2 class="result__title"><a class="result__a" href="https://troisieme.example.com/">Troisième</a></h2>
  </div>
</div>
</div></div></body></html>"""

CHALLENGE = """<html><body><div class="anomaly-modal__mask"><div class="anomaly-modal__modal">
<div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div></div></div></body></html>"""

ARTICLE = """<html><head><title>Un article &amp; son titre</title><script>var x = "pas du texte";</script>
<style>p { color: red }</style></head><body>
<header><nav><a href="/">Accueil</a> <a href="/menu">Menu</a></nav></header>
<main><article><h1>Le grand titre</h1>
<p>""" + ("Une phrase de l'article qui compte. " * 30) + """</p>
<p>Deuxième paragraphe.<br>Avec un saut de ligne.</p>
<button>Partager</button></article></main>
<aside>Publicité latérale</aside><footer>Mentions légales</footer>
<script>track()</script></body></html>"""


class FakeNet:
    """Le réseau simulé : une réponse par adresse, chaque appel noté."""

    def __init__(self, pages: dict[str, s.Fetched] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[tuple[str, dict[str, list[str]]]] = []

    def __call__(self, url, *, data=None, headers=None):  # noqa: ANN001
        parts = urlsplit(url)
        self.calls.append((url, parse_qs(parts.query)))
        page = self.pages.get(url) or self.pages.get(f"{parts.scheme}://{parts.netloc}{parts.path}")
        if page is None:
            raise OSError("pas de réseau")
        return page


def html(body: str, status: int = 200, url: str = s.SEARCH_URL, kind: str = "text/html") -> s.Fetched:
    return s.Fetched(status, url, kind, "utf-8", body.encode())


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def web(net: FakeNet, clock: Clock | None = None, **settings) -> s.Web:  # noqa: ANN003
    clock = clock or Clock()
    return s.Web(s.Settings(**settings), fetch=net, now=clock.now, sleep=clock.sleep, clock=lambda: "22:50")


# ── Chercher ─────────────────────────────────────────────────────────────────────────────────────────


def test_results_read_like_the_page_shows_them():
    out = web(FakeNet({s.SEARCH_URL: html(RESULTS)})).search("une question", 5)
    assert out.splitlines()[0] == "Résultats DuckDuckGo pour « une question » :"
    assert "1. Premier titre\n   https://www.exemple.fr/a\n   Un extrait avec du gras et des \"guillemets\"." in out
    assert "2. Deuxième\n   https://wiki.exemple.org/page?x=1\n   Un extrait en div." in out  # redirection défaite
    assert "3. Troisième" in out
    assert "publicité" not in out.lower() and "doublon" not in out  # publicité et doublon écartés


def test_the_number_of_results_is_bounded():
    out = web(FakeNet({s.SEARCH_URL: html(RESULTS)})).search("q", 1)
    assert "1. Premier titre" in out and "2." not in out


def test_the_search_says_its_region_safety_and_period():
    net = FakeNet({s.SEARCH_URL: html(RESULTS)})
    web(net).search("  météo   Lyon ", 3, "semaine", "be-fr")
    form = net.calls[0][1]
    assert form == {"q": ["météo Lyon"], "kl": ["be-fr"], "kp": ["-1"], "df": ["w"]}
    with pytest.raises(s.ToolError, match="région"):
        web(net).search("q", 3, None, "france")
    with pytest.raises(s.ToolError, match="période"):
        web(net).search("q", 3, "siècle")


def test_nothing_found_is_said_not_failed():
    assert web(FakeNet({s.SEARCH_URL: html("<html><body></body></html>")})).search("zzz") == \
        "Aucun résultat pour « zzz »."


def test_a_same_search_is_served_from_the_cache():
    net = FakeNet({s.SEARCH_URL: html(RESULTS)})
    w = web(net)
    assert w.search("Une Question") == w.search("une question")
    assert len(net.calls) == 1


def test_searches_are_spaced_and_counted():
    clock = Clock()
    net = FakeNet({s.SEARCH_URL: html(RESULTS)})
    w = web(net, clock)
    w.search("un")
    w.search("deux")  # tout de suite après : elle attend son tour
    assert clock.slept == [s.Settings().spacing_s]
    throttle = s.Throttle(per_minute=2, spacing=0.0, now=clock.now, sleep=clock.sleep, max_wait=5.0)
    throttle.take("recherches")
    throttle.take("recherches")
    with pytest.raises(s.ToolError, match="trop de recherches d'affilée : réessaie dans"):
        throttle.take("recherches")  # la minute n'est pas finie : attendre plus que permis, c'est le dire


def test_a_challenge_pauses_the_search_and_says_until_when():
    clock = Clock()
    net = FakeNet({s.SEARCH_URL: html(CHALLENGE, status=202)})
    w = web(net, clock)
    with pytest.raises(s.ToolError, match="prouver qu'on est humain.*avant 23h05"):
        w.search("un")
    with pytest.raises(s.ToolError, match="pris pour un robot.*23h05"):
        w.search("deux")
    assert len(net.calls) == 1  # pendant la pause, DuckDuckGo n'est plus sollicité
    clock.t += s.Settings().pause_s + 1
    net.pages[s.SEARCH_URL] = html(RESULTS)
    assert "Premier titre" in w.search("trois")


def test_a_challenge_is_recognized_by_its_page_even_with_a_200():
    with pytest.raises(s.ToolError, match="humain"):
        web(FakeNet({s.SEARCH_URL: html(CHALLENGE, status=200)})).search("q")


def test_no_network_is_said_in_her_words():
    with pytest.raises(s.ToolError, match="joindre DuckDuckGo"):
        web(FakeNet()).search("q")


# ── Lire ─────────────────────────────────────────────────────────────────────────────────────────────

PAGE = "https://www.exemple.fr/article"


def test_a_page_is_read_without_its_menus_and_scripts():
    out = web(FakeNet({PAGE: html(ARTICLE, url=PAGE)})).read(PAGE, max_chars=20_000)
    assert out.startswith(f"Titre : Un article & son titre\nAdresse : {PAGE}\n\n")
    assert "Le grand titre" in out and "Deuxième paragraphe.\nAvec un saut de ligne." in out
    for noise in ("pas du texte", "color", "Accueil", "Menu", "Partager", "Publicité", "Mentions", "track"):
        assert noise not in out
    assert out.endswith("[fin de la page]")


def test_a_long_page_is_read_in_pieces():
    net = FakeNet({PAGE: html(ARTICLE, url=PAGE)})
    w = web(net)
    first = w.read(PAGE, max_chars=500)
    assert "[suite : start=" in first and "[fin de la page]" not in first
    start = int(first.rsplit("start=", 1)[1].split(",")[0])
    second = w.read(PAGE, start=start, max_chars=20_000)
    assert f"(à partir du caractère {start})" in second and second.endswith("[fin de la page]")
    assert len(net.calls) == 1  # la suite vient du cache
    assert "s'arrête avant" in w.read(PAGE, start=10**6)


def test_the_final_address_after_redirects_is_shown():
    out = web(FakeNet({PAGE: html(ARTICLE, url="https://www.exemple.fr/article-v2")})).read(PAGE)
    assert "Adresse : https://www.exemple.fr/article-v2" in out


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8001/", "http://192.168.1.10/admin",
                                 "http://[::1]/", "http://10.0.0.2/", "http://box.lan/", "http://imprimante.local/",
                                 "file:///etc/passwd", "ftp://exemple.fr/", "https://moi:secret@exemple.fr/", "exemple.fr"])
def test_what_is_not_the_public_web_is_not_read(url):
    net = FakeNet()
    with pytest.raises(s.ToolError):
        web(net).read(url)
    assert net.calls == []


def test_a_pdf_or_a_binary_is_refused_and_plain_text_is_read():
    pdf = "https://exemple.fr/doc.pdf"
    img = "https://exemple.fr/i.png"
    txt = "https://exemple.fr/notes.txt"
    w = web(FakeNet({pdf: html("%PDF", url=pdf, kind="application/pdf"), img: html("x", url=img, kind="image/png"),
                     txt: html("des notes\nen texte", url=txt, kind="text/plain")}))
    with pytest.raises(s.ToolError, match="PDF"):
        w.read(pdf)
    with pytest.raises(s.ToolError, match="image/png"):
        w.read(img)
    assert "des notes\nen texte" in w.read(txt)


def test_an_empty_page_says_why():
    w = web(FakeNet({PAGE: html("<html><body><script>app()</script></body></html>", url=PAGE)}))
    with pytest.raises(s.ToolError, match="JavaScript"):
        w.read(PAGE)


def test_a_page_in_another_charset_is_decoded():
    body = "<html><head><meta charset='iso-8859-1'><title>Été</title></head><body><p>déjà là</p></body></html>"
    got = s.Fetched(200, PAGE, "text/html", None, body.encode("latin-1"))
    assert "Titre : Été" in web(FakeNet({PAGE: got})).read(PAGE)


# ── Le protocole ─────────────────────────────────────────────────────────────────────────────────────


def rpc(mid, method, params=None):  # noqa: ANN001
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def test_the_handshake_and_the_two_tools():
    server = s.Server(web(FakeNet()))
    hello = server.handle(rpc(1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}}))
    assert hello["result"]["protocolVersion"] == "2025-03-26"
    assert hello["result"]["serverInfo"]["name"] == "mika-web"
    newer = server.handle(rpc(2, "initialize", {"protocolVersion": "2099-01-01"}))
    assert newer["result"]["protocolVersion"] == s.PROTOCOL_VERSIONS[0]
    tools = server.handle(rpc(3, "tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["search", "read", "read_pages"]
    for t in tools:
        assert t["inputSchema"]["type"] == "object" and t["description"] and t["annotations"]["readOnlyHint"]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.handle(rpc(4, "ping")) == {"jsonrpc": "2.0", "id": 4, "result": {}}
    assert server.handle(rpc(5, "resources/list"))["error"]["code"] == -32601
    assert server.handle(rpc(6, "tools/call", {"name": "effacer", "arguments": {}}))["error"]["code"] == -32602


def test_a_tool_failure_is_an_error_result_in_french():
    server = s.Server(web(FakeNet({s.SEARCH_URL: html(RESULTS)})))
    ok = server.handle(rpc(1, "tools/call", {"name": "search", "arguments": {"query": "q", "max_results": 2}}))
    assert ok["result"]["isError"] is False and "Premier titre" in ok["result"]["content"][0]["text"]
    bad = server.handle(rpc(2, "tools/call", {"name": "read", "arguments": {"url": "http://127.0.0.1/"}}))
    assert bad["result"]["isError"] is True and "réseau local" in bad["result"]["content"][0]["text"]
    wrong = server.handle(rpc(3, "tools/call", {"name": "search", "arguments": {"query": 3}}))
    assert wrong["result"]["isError"] is True and "un texte" in wrong["result"]["content"][0]["text"]


def test_a_bug_of_ours_does_not_bring_the_server_down():
    class Broken(s.Web):
        def search(self, *a, **k):  # noqa: ANN002, ANN003
            raise KeyError("oups")

    got = s.Server(Broken(s.Settings(), fetch=FakeNet())).handle(rpc(1, "tools/call", {"name": "search", "arguments": {"query": "q"}}))
    assert got["result"]["isError"] is True and "défaut" in got["result"]["content"][0]["text"]


def test_the_stdio_loop_answers_and_drops_a_request_cancelled_in_flight():
    gate = threading.Event()

    class Slow(s.Web):
        def search(self, query, *a, **k):  # noqa: ANN001, ANN002, ANN003
            gate.wait(5)
            return f"fini : {query}"

    lines = [rpc(1, "initialize", {"protocolVersion": "2025-06-18"}),
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             rpc(2, "tools/call", {"name": "search", "arguments": {"query": "lent"}}),
             {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}},
             {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}},  # rien en vol
             rpc(3, "ping")]

    class Feed(io.StringIO):
        def __iter__(self):
            for line in lines:
                yield json.dumps(line) + "\n"
            gate.set()  # la recherche annulée finit après coup

    out = io.StringIO()
    s.serve(s.Server(Slow(s.Settings(), fetch=FakeNet())), stdin=Feed(), stdout=out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 3]  # l'appel annulé ne reçoit rien ; le ping, si


def test_garbage_is_answered_not_fatal():
    out = io.StringIO()
    s.serve(s.Server(web(FakeNet())), stdin=io.StringIO("pas du json\n\n" + json.dumps(rpc(1, "ping")) + "\n"),
            stdout=out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700 and replies[1] == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_its_error_output_never_says_what_was_searched(capsys):
    w = web(FakeNet())
    with pytest.raises(s.ToolError):
        w.search("mon secret médical")
    with pytest.raises(s.ToolError):
        w.read("https://exemple.fr/une-page-privee")
    err = capsys.readouterr().err
    assert "réseau" in err and "secret" not in err and "privee" not in err


# ── Ses réglages, et plusieurs pages à la fois ──────────────────────────────────────────────────────


def test_its_settings_come_from_the_environment_the_plugin_sets():
    wanted = s.Settings(spacing_s=5.0, searches_per_minute=6, reads_per_minute=20, parallel_pages=4, pause_s=1800,
                        cache_s=0, region="be-fr", safesearch="strict")
    assert s.Settings.from_env(wanted.env()) == wanted
    odd = s.Settings.from_env({"MIKA_WEB_ESPACEMENT_S": "beaucoup", "MIKA_WEB_PAGES_EN_PARALLELE": "99",
                               "MIKA_WEB_REGION": "france", "MIKA_WEB_SAFESEARCH": "?"})
    assert odd.spacing_s == s.Settings().spacing_s and odd.parallel_pages == 8  # illisible : défaut ; trop : borné
    assert odd.region == "fr-fr" and odd.safesearch == "modere"


def test_reading_several_pages_is_offered_only_when_allowed():
    assert [t["name"] for t in s.tools(s.Settings(parallel_pages=1))] == ["search", "read"]
    several = s.tools(s.Settings(parallel_pages=4))
    assert several[-1]["name"] == "read_pages" and "4 pages" in several[-1]["description"]
    server = s.Server(web(FakeNet(), parallel_pages=1))
    got = server.handle(rpc(1, "tools/call", {"name": "read_pages", "arguments": {"urls": [PAGE]}}))
    assert got["error"]["code"] == -32602  # pas proposé : inconnu


def test_several_pages_are_read_at_the_same_time():
    other = "https://www.exemple.fr/autre"
    barrier = threading.Barrier(2, timeout=5)

    class Together(FakeNet):
        def __call__(self, url, **kw):  # noqa: ANN001, ANN003
            barrier.wait()  # les deux lectures doivent être en vol ensemble, sinon la barrière casse
            return super().__call__(url, **kw)

    net = Together({PAGE: html(ARTICLE, url=PAGE), other: html("<p>" + "Autre page. " * 50 + "</p>", url=other)})
    out = web(net, parallel_pages=3).read_pages([PAGE, other, PAGE], max_chars=400)
    first, second = out.split("\n\n———\n\n")
    assert f"Adresse : {PAGE}" in first and f"Adresse : {other}" in second  # dans l'ordre demandé, doublon retiré
    assert "[suite : start=" in first and len(net.calls) == 2


def test_a_page_that_fails_is_said_in_its_place_and_all_failing_is_a_failure():
    w = web(FakeNet({PAGE: html(ARTICLE, url=PAGE)}), parallel_pages=3)
    out = w.read_pages([PAGE, "http://192.168.0.1/"])
    assert "Le grand titre" in out and "Impossible de la lire : cette adresse est sur cette machine" in out
    with pytest.raises(s.ToolError, match="aucune de ces pages"):
        w.read_pages(["http://127.0.0.1/", "https://absente.exemple.fr/"])
    with pytest.raises(s.ToolError, match="3 pages au plus"):
        w.read_pages([f"https://exemple.fr/{i}" for i in range(4)])
    with pytest.raises(s.ToolError, match="une liste"):
        w.read_pages("https://exemple.fr/")


def test_a_search_is_a_get_like_a_browser():
    net = FakeNet({s.SEARCH_URL: html(RESULTS)})
    web(net).search("q")
    assert net.calls[0][0].startswith(s.SEARCH_URL + "?q=q&")
    assert {"Sec-Fetch-Mode", "User-Agent", "Accept-Language"} <= set(s.BROWSER)


def test_with_no_cache_every_search_goes_out():
    net = FakeNet({s.SEARCH_URL: html(RESULTS)})
    w = web(net, cache_s=0)
    w.search("q")
    w.search("q")
    assert len(net.calls) == 2


def test_the_pause_after_a_challenge_follows_its_setting():
    clock = Clock()
    w = web(FakeNet({s.SEARCH_URL: html(CHALLENGE, status=202)}), clock, pause_s=3600)
    with pytest.raises(s.ToolError, match="avant 23h50"):
        w.search("q")
    clock.t += 3000
    with pytest.raises(s.ToolError, match="pris pour un robot"):
        w.search("q")


def test_the_server_starts_and_answers_as_a_process(tmp_path):
    """Le vrai fichier, lancé comme le client le lance (``python3 -I``) : il répond sur sa sortie standard."""
    import subprocess
    import sys

    msgs = [rpc(1, "initialize", {"protocolVersion": "2025-06-18"}), rpc(2, "tools/list")]
    proc = subprocess.run([sys.executable, "-I", s.__file__], input="".join(json.dumps(m) + "\n" for m in msgs),
                          capture_output=True, text=True, timeout=20,
                          env={"MIKA_WEB_PAGES_EN_PARALLELE": "1", "PATH": "/usr/bin:/bin"})
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert replies[0]["result"]["serverInfo"]["name"] == "mika-web"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == ["search", "read"]  # l'environnement est lu
