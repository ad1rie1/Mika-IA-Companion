"""« Ses outils » (ADR 0064) : la console lit ce que le moteur exécute.

Chaque outil du registre a sa ligne et sa fiche ; la matrice « qui reçoit quoi » est calculée par la porte d'offre
du pipeline — le récit « pourquoi pas » dit la même chose qu'elle, situation par situation ; un outil défini dans le
code ne se règle pas sur sa fiche (aucun formulaire de plus qu'une page sans action) ; « Régler ses outils » porte le
texte que son prompt porte vraiment, et y range ses outils situation par situation (ADR 0122) — sans jamais en
donner un que le code n'offre pas."""

from __future__ import annotations

import hashlib
import re
from types import SimpleNamespace

from mika.contracts import runtime as rt
from mika.inspector.mcp import TOOLS as CONSOLE_TOOLS
from mika.inspector.pages import tools as page
from mika.vocab.phrasebook import phrase
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_inspector_pages import every_page, html_of
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

ACTING = phrase("runtime.tools.acting")

BASE = "/inspecteur/outils"


def _forms(text: str) -> int:
    return len(re.findall(r"<form\b", text))


def test_every_tool_is_listed_with_its_fiche_and_none_can_be_set_here(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    registry = live.kernel.registry
    # La découverte MCP peut ajouter des outils pendant la lecture des pages.
    specs = dict(registry.tools)
    dynamic = {name for name in specs if registry.is_dynamic(name)}
    listed = every_page(client, f"{BASE}/tous")
    missing = [n for n in specs if n not in listed]
    assert missing == [], missing
    plain = _forms(client.get(f"{BASE}/qui").text)  # une page sans action : ses seuls formulaires sont ceux du cadre
    for name, spec in specs.items():
        r = client.get(f"{BASE}/tous", params={"outil": name})
        text = html_of(r)
        editable = "sur la fiche de son serveur" if name in dynamic else "non — défini dans le code"
        assert r.status_code == 200 and name in text and editable in text, name
        assert registry.bundles[spec.bundle] in text, name
        assert _forms(r.text) == plain, f"{name} : un outil du code ne se règle pas ici"
        ConsoleHTML(r.text).check()
    assert "Aucun outil ne s'appelle" in html_of(client.get(f"{BASE}/tous", params={"outil": "rien_du_tout"}))


def test_the_matrix_and_its_reasons_say_what_the_pipeline_offers(world):  # noqa: F811
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
    # et la page le rend : le lot du courrier, en tête-à-tête avec sa propriétaire
    bootstrap(client)
    text = html_of(client.get(f"{BASE}/qui"))
    assert "email" in text and ("●" in text or "○" in text)


def test_what_she_reads_is_her_prompt(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    spoken = html_of(client.get(f"{BASE}/texte", params={"situation": "proprietaire"}))
    assert ACTING[:40] in spoken and "En main" in spoken
    # un pas de travail : personne ne lit sa parole, la règle de ses mains n'y est pas
    silent = html_of(client.get(f"{BASE}/texte", params={"situation": "pas"}))
    assert ACTING[:40] not in silent


def _rule(client, situation: str, **rules: str):
    data = {"csrf": client.cookies.get("csrftoken"), "situation": situation,
            **{f"r.{name}": rule for name, rule in rules.items()}}
    return client.post(f"{BASE}/regler", data=data, follow_redirects=False)


def test_an_operator_rules_her_tools_situation_by_situation(world):  # noqa: F811
    """Retiré, le pipeline ne l'offre plus dans cette situation, et la console le dit partout (sa fiche, la grille) ;
    ailleurs, rien ne change. Une règle sur un outil que le code n'offre pas ici est ignorée. Tout remettre efface."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    ui = SimpleNamespace(kernel=kernel)
    owner, room = (next(s for s in page.situations(ui) if s.key == key) for key in ("proprietaire", "salon"))
    table = client.get(f"{BASE}/texte", params={"situation": "proprietaire"})
    ConsoleHTML(table.text).check()
    assert 'name="r.email_read"' in table.text and 'name="r.email_read"' not in \
        client.get(f"{BASE}/texte", params={"situation": "salon"}).text  # le code ne l'offre pas en salon
    saved = _rule(client, "proprietaire", email_read="off", memory_search="ask")
    assert saved.status_code == 303 and "situation=proprietaire" in saved.headers["location"]
    assert "email_read" not in page.offered_in(ui, owner)
    assert "email_read" not in kernel.runner._tools(kernel.runner.policies[owner.kind], owner.kind, owner.audience,
                                                    rules=kernel.runner.rules_of(owner.kind, owner.audience))
    assert page.offered_in(ui, room) == page.offered_in(ui, room, ruled=False)  # ailleurs, rien ne change
    fiche = html_of(client.get(f"{BASE}/tous", params={"outil": "email_read"}))
    assert "retiré par un opérateur" in fiche
    after = client.get(saved.headers["location"])
    assert "email_read" in html_of(after) and "1 outil retiré" in html_of(after)
    audit = client.portal.call(lambda: kernel.mind.store.latest([rt.OPERATED.name], 5))
    assert any("console.outils.regler" in a.data for a in audit)
    # le code ne l'offre pas en salon : la règle est ignorée
    _rule(client, "salon", email_read="hand")
    assert "email_read" not in live.settings.tool_rules_for("salon")
    reset = client.post(f"{BASE}/regler", data={"csrf": client.cookies.get("csrftoken"), "situation": "proprietaire",
                                                "faire": "remettre"}, follow_redirects=False)
    assert reset.status_code == 303 and live.settings.tool_rules_for("proprietaire") == {}
    assert "email_read" in page.offered_in(ui, owner)
    refused = client.post(f"{BASE}/regler", data={"csrf": "faux", "situation": "proprietaire", "r.email_read": "off"},
                          follow_redirects=False)
    assert refused.status_code == 303 and live.settings.tool_rules_for("proprietaire") == {}


def test_what_mika_serves_is_said(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    text = html_of(client.get(f"{BASE}/expose"))
    assert all(t.name in text for t in CONSOLE_TOOLS)
    assert "mika mcp token" in text and "/mcp/relais" in text


def test_catalogue_cards_and_fiche_preserve_filters_and_table_choice(world):  # noqa: F811
    import html
    from urllib.parse import parse_qs, urlsplit

    client, _, _ = world
    bootstrap(client)
    response = client.get(f'{BASE}/tous?lot=email&origine=interne')
    # le catalogue est dessiné en cartes (ADR 0121)
    assert response.status_code == 200 and 'class="now-card person-list' in response.text
    link = html.unescape(re.search(r'href="([^\"]*outil=email_read[^\"]*)"', response.text).group(1))
    assert parse_qs(urlsplit(link).query)['lot'] == ['email']
    detail = client.get(link)
    ConsoleHTML(detail.text).check()
    assert '<h1>email_read</h1>' in detail.text and 'Arguments et règles d’utilisation' in detail.text
    crumb = re.search(r'<nav class="crumbs".*?</nav>', html.unescape(detail.text), re.S).group()
    assert f'{BASE}/tous?lot=email&origine=interne' in crumb
    table = client.get(f'{BASE}/tous?lot=email&origine=interne&vue_pg1=table')
    assert 'person-list' not in table.text and 'class="hm-table"' in table.text
    table_link = html.unescape(re.search(r'href="([^\"]*outil=email_read[^\"]*)"', table.text).group(1))
    assert parse_qs(urlsplit(table_link).query)['vue_pg1'] == ['table']
    accented = client.get(f'{BASE}/tous?q=écrire').text
    unaccented = client.get(f'{BASE}/tous?q=ecrire').text
    def names_in(body):
        return set(re.findall(r'outil=([a-zA-Z0-9_]+)', body))
    assert names_in(accented) and names_in(accented) == names_in(unaccented)
    assert 'Aucun outil ne correspond' in client.get(f'{BASE}/tous?q=aucun-resultat').text


def _expose(client, what: str, **fields):
    data = {"csrf": client.cookies.get("csrftoken"), "faire": what, **fields}
    return client.post(f"{BASE}/exposer", data=data, follow_redirects=False)


def test_what_she_exposes_is_set_from_the_console(world):  # noqa: F811
    """La console en MCP : un jeton créé ici se montre une seule fois (la ligne ``claude mcp add`` comprise), ce
    qu'elle sert se choisit ; un point de prêt se déclare (son jeton montré une fois, seule l'empreinte gardée),
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
    assert _expose(client, "console_fermer").status_code == 303 and not read("console_mcp_token")
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
    for action in ("console.mcp.jeton", "console.mcp.servir", "console.mcp.fermer", "console.mcp.pret.declarer",
                   "console.mcp.pret.jeton", "console.mcp.pret.retirer"):
        assert action in actions, action
    refused = client.post(f"{BASE}/exposer", data={"csrf": "faux", "faire": "console_jeton"}, follow_redirects=False)
    assert refused.status_code == 303 and not read("console_mcp_token")
