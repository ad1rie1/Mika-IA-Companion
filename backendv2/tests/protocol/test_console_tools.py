"""« Ses outils » (ADR 0064, 0122) : la console lit ce que le moteur exécute.

« Ce qu'elle peut faire » est une grille : chaque outil du registre y a sa ligne, sous sa famille, et sa fiche ; ce
qu'elle dit est calculé par la porte d'offre du pipeline — le récit « pourquoi pas » dit la même chose qu'elle,
situation par situation. On y décoche un outil pour le lui retirer dans une situation, et sa fiche le règle plus
finement — sans jamais lui donner un outil que le code n'offre pas. Elle porte aussi le texte que son prompt porte
vraiment."""

from __future__ import annotations

import hashlib
import html
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from mika.contracts import runtime as rt
from mika.inspector.mcp import TOOLS as CONSOLE_TOOLS
from mika.inspector.pages import tools as page
from mika.vocab.phrasebook import phrase
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_inspector_pages import html_of
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

ACTING = phrase("runtime.tools.acting")

BASE = "/inspecteur/outils"


def _shown(body: str) -> set[str]:
    """Les outils que la grille montre (chacun y laisse son nom dans un champ caché)."""
    return set(re.findall(r'name="vu" value="([a-zA-Z0-9_]+)"', body))


def _checked(body: str, tool: str) -> list[str]:
    """Les cases cochées d'un outil dans la grille : « situation:outil »."""
    return re.findall(rf'name="o" value="([a-z]+:{tool})" checked', body)


def test_every_tool_is_in_the_grid_with_its_fiche(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    registry = live.kernel.registry
    # La découverte MCP peut ajouter des outils pendant la lecture des pages.
    specs = dict(registry.tools)
    dynamic = {name for name in specs if registry.is_dynamic(name)}
    grid = client.get(f"{BASE}/tous")
    ConsoleHTML(grid.text).check()
    missing = [n for n in specs if n not in _shown(grid.text)]
    assert missing == [], missing
    for name, spec in specs.items():
        r = client.get(f"{BASE}/tous", params={"outil": name})
        text = html_of(r)
        assert r.status_code == 200 and name in text and "Où elle peut s'en servir" in text, name
        assert ("il vient d'un service ou d'une app" in text) == (name in dynamic), name
        assert registry.bundles[spec.bundle] in text, name
        ConsoleHTML(r.text).check()
    assert "Aucun outil ne s'appelle" in html_of(client.get(f"{BASE}/tous", params={"outil": "rien_du_tout"}))


def test_the_grid_and_its_reasons_say_what_the_pipeline_offers(world):  # noqa: F811
    client, live, _ = world
    kernel = live.kernel
    ui = SimpleNamespace(kernel=kernel)
    offers = {}
    for s in page.situations(ui):
        policy = kernel.runner.policies[s.kind]
        offered = page.offered_in(ui, s)
        # la console et le pipeline passent par la même porte
        assert offered == kernel.runner._tools(policy, s.kind, s.audience), s.key
        for name, spec in kernel.registry.tools.items():
            assert (page.why_not(spec, policy, s, page.rules(ui, s)) == "") == (name in offered), (s.key, name)
        offers[s.key] = offered
    # cibles d'intention : sa boîte, pour sa propriétaire en privé seulement ; ses dessins, pour qui a un compte
    assert "email_read" in offers["proprietaire"]
    assert "email_read" not in offers["compte"] and "email_read" not in offers["salon"]
    assert "draw" in offers["compte"] and "draw" not in offers["inconnue"] and "draw" not in offers["salon"]
    assert not any(spec.owner_only for spec in offers["salon"].values())
    # et la grille le rend : sa boîte cochée pour sa propriétaire, un tiret en salon — et pourquoi
    bootstrap(client)
    body = client.get(f"{BASE}/tous").text
    assert "proprietaire:email_read" in _checked(body, "email_read")
    assert 'value="salon:email_read"' not in body
    assert "Elle répond dans un salon, devant plusieurs personnes : réservé à sa propriétaire" in html.unescape(body)


def test_what_she_reads_is_her_prompt(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    body = html_of(client.get(f"{BASE}/tous"))
    prompts = dict(re.findall(r'<details class="can-prompt"><summary>(.*?)</summary><pre>(.*?)</pre>', body, re.S))
    assert ACTING[:40] in prompts["Elle répond à sa propriétaire, en privé"]
    # un pas sur un but : personne ne lit sa parole, la règle de ses mains n'y est pas
    assert ACTING[:40] not in prompts["Elle avance seule sur un de ses buts"]


def _grid(client, tools: list[str], checked: list[str]):
    data = {"csrf": client.cookies.get("csrftoken"), "vu": tools, "o": checked}
    return client.post(f"{BASE}/regler", data=data, follow_redirects=False)


def _fiche(client, tool: str, **rules: str):
    data = {"csrf": client.cookies.get("csrftoken"), "outil": tool, **{f"r.{s}": r for s, r in rules.items()}}
    return client.post(f"{BASE}/regler", data=data, follow_redirects=False)


def test_an_operator_rules_her_tools_from_the_grid_and_the_fiche(world):  # noqa: F811
    """Décoché dans la grille, le pipeline ne l'offre plus dans cette situation, et la console le dit (la grille, sa
    fiche) ; ailleurs, rien ne change. Une grille filtrée ne touche que ce qu'elle montrait. La fiche le rend ;
    une règle sur une situation où le code ne l'offre pas est ignorée. Tout remettre efface."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    ui = SimpleNamespace(kernel=kernel)
    owner, room, step = (next(s for s in page.situations(ui) if s.key == key) for key in ("proprietaire", "salon", "pas"))
    body = client.get(f"{BASE}/tous").text
    ConsoleHTML(body).check()
    ticked = _checked(body, "email_read")
    assert "proprietaire:email_read" in ticked and "pas:email_read" in ticked
    saved = _grid(client, ["email_read"], [c for c in ticked if c != "proprietaire:email_read"])
    assert saved.status_code == 303 and saved.headers["location"].startswith(f"{BASE}/tous?")
    assert "email_read" not in page.offered_in(ui, owner)
    assert "email_read" not in kernel.runner._tools(kernel.runner.policies[owner.kind], owner.kind, owner.audience,
                                                    rules=kernel.runner.rules_of(owner.kind, owner.audience))
    assert "email_read" in page.offered_in(ui, step)  # ses autres cases sont restées cochées
    assert page.offered_in(ui, room) == page.offered_in(ui, room, ruled=False)  # ailleurs, rien ne change
    after = client.get(saved.headers["location"])
    assert "proprietaire:email_read" not in _checked(after.text, "email_read")
    assert "1 retiré par un opérateur" in html_of(after) and "email_read retiré" in html_of(after)
    fiche = client.get(f"{BASE}/tous", params={"outil": "email_read"}).text
    assert re.search(r'name="r\.proprietaire">.*?<option value="off" selected>', fiche, re.S)
    audit = client.portal.call(lambda: kernel.mind.store.latest([rt.OPERATED.name], 5))
    assert any("console.outils.regler" in a.data for a in audit)
    # une grille filtrée (une autre famille) ne touche pas à ce qu'elle ne montrait pas
    memory = _checked(body, "memory_search")
    assert _grid(client, ["memory_search"], memory).status_code == 303
    assert "email_read" not in page.offered_in(ui, owner)
    # le code ne l'offre pas en salon : la règle est ignorée ; sa fiche le rend à sa propriétaire
    _fiche(client, "email_read", salon="hand", proprietaire="")
    assert "email_read" not in live.settings.tool_rules_for("salon")
    assert "email_read" in page.offered_in(ui, owner)
    _grid(client, ["email_read"], [c for c in ticked if c != "proprietaire:email_read"])
    assert live.settings.tool_rules_for("proprietaire") == {"email_read": "off"}
    reset = client.post(f"{BASE}/regler", data={"csrf": client.cookies.get("csrftoken"), "faire": "remettre"},
                        follow_redirects=False)
    assert reset.status_code == 303 and live.settings.tool_rules_for("proprietaire") == {}
    assert "email_read" in page.offered_in(ui, owner)
    refused = client.post(f"{BASE}/regler", data={"csrf": "faux", "vu": ["email_read"], "o": []},
                          follow_redirects=False)
    assert refused.status_code == 303 and live.settings.tool_rules_for("proprietaire") == {}


def test_what_mika_serves_is_said(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    text = html_of(client.get(f"{BASE}/expose"))
    assert all(t.name in text for t in CONSOLE_TOOLS)
    assert "mika mcp token" in text and "/mcp/relais" in text


def test_the_grid_keeps_its_search_and_family_on_the_fiche(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    response = client.get(f"{BASE}/tous?lot=email")
    ConsoleHTML(response.text).check()
    # une seule famille, ouverte
    assert 'class="can-family" open' in response.text and _shown(response.text) and \
        all(n.startswith("email_") for n in _shown(response.text))
    link = html.unescape(re.search(r'href="([^\"]*outil=email_read[^\"]*)"', response.text).group(1))
    assert parse_qs(urlsplit(link).query)["lot"] == ["email"]
    detail = client.get(link)
    ConsoleHTML(detail.text).check()
    assert "<h1>email_read</h1>" in detail.text and "Arguments et règles d’utilisation" in detail.text
    crumb = re.search(r'<nav class="crumbs".*?</nav>', html.unescape(detail.text), re.S).group()
    assert f"{BASE}/tous?lot=email" in crumb
    accented = _shown(client.get(f"{BASE}/tous?q=écrire").text)
    assert accented and accented == _shown(client.get(f"{BASE}/tous?q=ecrire").text)
    assert "Aucun outil ne correspond" in client.get(f"{BASE}/tous?q=aucun-resultat").text
    # les anciennes pages mènent ici
    for old, new in (("qui", "tous"), ("texte", "tous"), ("outils_apps", "serveurs")):
        moved = client.get(f"{BASE}/{old}", follow_redirects=False)
        assert moved.status_code == 301 and moved.headers["location"] == f"{BASE}/{new}", old


def _expose(client, what: str, **fields):
    data = {"csrf": client.cookies.get("csrftoken"), "faire": what, **fields}
    return client.post(f"{BASE}/exposer", data=data, follow_redirects=False)


def test_what_she_exposes_is_set_from_the_console(world):  # noqa: F811
    """La console en MCP : un jeton créé ici se montre une seule fois (la ligne ``claude mcp add`` comprise), ce
    qu'elle sert se choisit, elle s'ouvre au réseau et s'y ferme (ADR 0126) ; un point de prêt se déclare (son jeton montré une fois, seule l'empreinte gardée),
    se règle — jamais au-delà de ce que la porte offre —, se renouvelle et se retire. Tout est audité."""
    client, live, _ = world
    bootstrap(client)
    settings = live.settings

    def read(what, *args):  # lu dans la boucle de l'application
        return client.portal.call(getattr(settings, what), *args)
    page = client.get(f"{BASE}/expose")
    ConsoleHTML(page.text).check()
    made = _expose(client, "console_jeton")
    assert made.status_code == 303 and "montrer=" in made.headers["location"]
    token = read("console_mcp_token")
    shown = client.get(made.headers["location"])
    ConsoleHTML(shown.text).check()
    assert token and token in shown.text and "claude mcp add --transport http mika" in html_of(shown)
    assert token not in client.get(made.headers["location"]).text  # une seule fois
    served = _expose(client, "console_servir", servi=["systeme.sante", "vues"])
    assert served.status_code == 303 and read("console_mcp_served") == ("systeme.sante", "vues")
    assert "http://127.0.0.1:8001/mcp/console/" in html_of(client.get(f"{BASE}/expose"))
    assert _expose(client, "console_reseau_ouvrir").status_code == 303 and read("console_mcp_network")
    assert "http://localhost:8001/mcp/console/" in html_of(client.get(f"{BASE}/expose"))  # là où on la lit
    assert _expose(client, "console_reseau_fermer").status_code == 303 and not read("console_mcp_network")
    _expose(client, "console_reseau_ouvrir")
    assert _expose(client, "console_fermer").status_code == 303 and not read("console_mcp_token")
    assert not read("console_mcp_network")  # fermer le jeton la ferme au réseau
    alone = _expose(client, "console_reseau_ouvrir")
    assert "la console n'a pas de jeton" in html_of(client.get(alone.headers["location"]))
    assert not read("console_mcp_network")
    declared = _expose(client, "pret_declarer", nom="agent", ecrit="non",
                       outil=["memory_search", "report_step", "outil_qui_n_existe_pas"])
    assert declared.status_code == 303
    entry = read("lent")["agent"]
    assert entry["tools"] == ["memory_search"] and not entry["writes"]  # rien au-delà de ce qu'elle peut prêter
    reveal = client.get(declared.headers["location"])
    ConsoleHTML(reveal.text).check()
    secret = re.search(r"mlp_[A-Za-z0-9_\-]+", reveal.text).group()
    assert hashlib.sha256(secret.encode()).hexdigest() == entry["digest"] and secret not in str(read("lent"))
    assert "/mcp/pret/agent" in html_of(reveal) and 'name="outil" value="memory_search" checked' in reveal.text
    again = _expose(client, "pret_declarer", nom="agent", ecrit="non")
    assert "un point s'appelle déjà « agent »" in html_of(client.get(again.headers["location"]))
    renewed = _expose(client, "pret_jeton", nom="agent")
    assert read("lent")["agent"]["digest"] != entry["digest"] and "montrer=" in renewed.headers["location"]
    assert _expose(client, "pret_supprimer", nom="agent").status_code == 303 and "agent" not in read("lent")
    audit = client.portal.call(lambda: live.kernel.mind.store.latest([rt.OPERATED.name], 20))
    actions = " ".join(a.data for a in audit)
    for action in ("console.mcp.jeton", "console.mcp.servir", "console.mcp.reseau.ouvrir", "console.mcp.reseau.fermer",
                   "console.mcp.fermer", "console.mcp.pret.declarer", "console.mcp.pret.jeton",
                   "console.mcp.pret.retirer"):
        assert action in actions, action
    refused = client.post(f"{BASE}/exposer", data={"csrf": "faux", "faire": "console_jeton"}, follow_redirects=False)
    assert refused.status_code == 303 and not read("console_mcp_token")
