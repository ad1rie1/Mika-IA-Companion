"""« Ses outils » (ADR 0064, 0122) : la console lit ce que le moteur exécute.

« Ce qu'elle peut faire » est une grille : chaque outil du registre y a sa ligne, sous sa famille, et sa fiche ; ce
qu'elle dit est calculé par la porte d'offre du pipeline — le récit « pourquoi pas » dit la même chose qu'elle,
situation par situation. On y décoche un outil pour le lui retirer dans une situation, et sa fiche le règle plus
finement — sans jamais lui donner un outil que le code n'offre pas. Elle porte aussi le texte que son prompt porte
vraiment."""

from __future__ import annotations

import hashlib
import html
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from mika.contracts import runtime as rt
from mika.inspector.mcp import TOOLS as CONSOLE_TOOLS
from mika.inspector.pages import tools as page
from mika.kernel.text import fold
from mika.plugins.mcp import specs_of
from mika.ports.mcp import CLOSED, Access, OfferedTool, ServerStatus
from mika.runtime.tool_offer import gate_of
from mika.vocab.phrasebook import phrase
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_inspector_pages import html_of
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

ACTING = phrase("runtime.tools.acting")

BASE = "/admin/outils"


def _shown(body: str) -> set[str]:
    """Les outils que la page montre (chacun a le lien de sa fiche)."""
    return set(re.findall(r'\?outil=([a-zA-Z0-9_]+)', body))


def _where(body: str, situation: str) -> str:
    """Ce que la fiche d'un outil dit d'une situation : « oui… », ou « non — pourquoi »."""
    found = re.search(rf'<span class="can-where-sit">{re.escape(situation)}</span>\s*<span[^>]*>([^<]*)</span>', body)
    return found.group(1).strip() if found else ""


def _subtitle(body: str, name: str) -> str | None:
    """Le sous-titre de la fiche d'un outil, sous son nom (``page.html``) ; ``None`` quand elle n'en a pas."""
    found = re.search(rf"<h1>{re.escape(name)}</h1>\s*(?:<p>(.*?)</p>)?", body, re.S)
    assert found is not None, name
    return found.group(1)


def _read_of(body: str) -> str:
    """Ce que « Ce qu'elle lit de lui » cite d'un outil, tel quel."""
    found = re.search(r'<h2 id="tool-read-title">Ce qu\'elle lit de lui</h2>.*?<blockquote class="tool-read">(.*?)'
                      r"</blockquote>", body, re.S)
    return found.group(1) if found else ""


def test_every_tool_is_in_the_grid_with_its_fiche(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    registry = live.kernel.registry
    # La découverte MCP peut ajouter des outils pendant la lecture des pages.
    specs = dict(registry.tools)
    dynamic = {name for name in specs if registry.is_dynamic(name)}
    page_ = client.get(f"{BASE}/tous")
    ConsoleHTML(page_.text).check()
    missing = [n for n in specs if n not in _shown(page_.text) and n not in dynamic]
    assert missing == [], missing
    for name in dynamic:  # ce qui vient d'ailleurs se montre par son lot, et renvoie à sa fiche
        assert name in _shown(client.get(f"{BASE}/tous", params={"lot": specs[name].bundle}).text), name
    for name, spec in specs.items():
        r = client.get(f"{BASE}/tous", params={"outil": name})
        text = html_of(r)
        assert r.status_code == 200 and name in text and "Où elle peut s'en servir" in text, name
        assert ("il vient d'un service ou d'une app" in text) == (name in dynamic), name
        assert registry.bundles[spec.bundle] in text, name
        # ce qu'il fait par son libellé, sous son nom ; ce qu'elle lit de lui, cité tel quel (C6-10)
        assert _subtitle(text, name) == (spec.label or None), name
        assert _read_of(text) == spec.description, name
        ConsoleHTML(r.text).check()
    assert "Aucun outil ne s'appelle" in html_of(client.get(f"{BASE}/tous", params={"outil": "rien_du_tout"}))


def test_a_tool_of_her_code_says_what_it_does_by_its_label_and_quotes_what_she_reads(world):  # noqa: F811
    """Sous « email_read », la fiche mettait sa description, une consigne au modèle où « tu » la désigne (« Ouvrir un
    mail de ta boîte. ») ; la console tutoie l'opératrice : elle s'y lisait. Le sous-titre est son libellé, dit à qui
    lit (ADR 0208) ; la consigne est citée telle quelle dans « Ce qu'elle lit de lui », et dite pour ce qu'elle est
    (audit du 2026-11-05, C6-10)."""
    client, live, _ = world
    bootstrap(client)
    spec = live.kernel.registry.tools["email_read"]
    raw = client.get(f"{BASE}/tous", params={"outil": "email_read"}).text
    ConsoleHTML(raw).check()
    fiche = html.unescape(raw)
    assert spec.label and spec.label != spec.description
    assert _subtitle(fiche, "email_read") == spec.label
    assert spec.description not in fiche.split("<h1>email_read</h1>", 1)[1].split("</div>", 1)[0]
    assert _read_of(fiche) == spec.description
    assert "La consigne exacte que reçoit le modèle avec cet outil, où « tu » la désigne, elle." in fiche
    assert "Ce que son service ou son app en dit" not in fiche
    # la section vient après « Où elle peut s'en servir », avant ses derniers appels
    assert fiche.index("Où elle peut s'en servir") < fiche.index("Ce qu'elle lit de lui") < fiche.index(
        "Ses derniers appels")


def test_a_tool_from_elsewhere_has_no_subtitle_and_quotes_what_its_service_says(world, monkeypatch):  # noqa: F811
    """Un outil venu d'un service n'a pas de libellé : sa fiche n'a pas de sous-titre — ni sa description, ni
    l'introduction de l'onglet à sa place —, et « Ce qu'elle lit de lui » cite ce que son service en dit, ou la phrase
    que l'opératrice lui a donnée à la place, qui se règle sur la fiche du serveur ; la liste de sa famille, et celle
    de son service dans Réglages › Droits, le disent par sa description (C6-10)."""
    client, live, _ = world
    bootstrap(client)
    port = live.kernel.ports["mcp"]
    line = Access(who=("tous",), when=("conversation",), read="seule", act="carte", keep="public")
    offered = OfferedTool("meteo", "prevision", "mcp_meteo_prevision", "Prévisions d'une ville (consigne du serveur).",
                          {}, "lecture", frozenset({"conversation"}), False, 3, "La météo d'une ville.", "", False,
                          access=(line,), default=CLOSED)
    status = ServerStatus("meteo", "distant", True, True, "connecte", purpose="La météo d'une ville.", access=(line,),
                          default=CLOSED)
    monkeypatch.setattr(port, "offered", lambda: (offered,))
    monkeypatch.setattr(port, "statuses", lambda: (status,))
    specs, bundles = specs_of((offered,))
    assert live.kernel.registry.set_dynamic("mcp", specs, bundles) == []
    raw = client.get(f"{BASE}/tous", params={"outil": "mcp_meteo_prevision"}).text
    ConsoleHTML(raw).check()
    fiche = html.unescape(raw)
    assert _subtitle(fiche, "mcp_meteo_prevision") is None
    assert "Ses propres outils, famille par famille" not in fiche
    assert _read_of(fiche) == "Prévisions d'une ville (consigne du serveur)."
    assert "Ce que son service ou son app en dit" in fiche and "La consigne exacte" not in fiche
    # ce qu'elle lit peut être la phrase que l'opératrice lui a donnée : elle se règle sur la fiche du serveur
    assert "ou, pour un service, la phrase que tu lui as donnée à la place" in fiche
    assert "celle d'un service se règle sur sa fiche (« Régler », sur sa ligne de « Ses outils »)" in fiche
    assert "se relit sur sa fiche" not in fiche
    listed = html_of(client.get(f"{BASE}/tous", params={"lot": "mcp.meteo"}))
    assert '<span class="access-tool-desc">Prévisions d\'une ville (consigne du serveur).</span>' in listed
    # Réglages › Droits, Services MCP : un outil sans libellé s'y dit aussi par sa description
    rights = html_of(client.get("/admin/reglages/droits"))
    services = rights.split('id="d-services" data-pane', 1)[1].split("data-pane", 1)[0]
    assert re.search(r"<code>mcp_meteo_prevision</code>.*?</td>\s*<td>Prévisions d'une ville \(consigne du serveur\)\."
                     r"</td>", services, re.S)


def test_a_search_finds_a_tool_by_the_label_its_family_shows(world):  # noqa: F811
    """La liste d'une famille dit chaque outil par son libellé : la recherche (``?q=``) le lit aussi, sinon un mot lu
    dans la liste ne retrouverait pas son outil (C6-10)."""
    client, live, _ = world
    bootstrap(client)
    registry = live.kernel.registry
    specs = sorted((s for s in registry.tools.values() if not registry.is_dynamic(s.name)), key=lambda s: s.name)
    families = re.findall(r'id="f-[\w-]+-title">([^<]+)<', html_of(client.get(f"{BASE}/tous")))
    elsewhere = " ".join([*(fold(f"{s.name} {s.description}") for s in specs), *map(fold, families)])
    word, spec = next((w, s) for s in specs for w in fold(s.label).split() if len(w) >= 5 and w not in elsewhere)
    found = html_of(client.get(f"{BASE}/tous", params={"q": word}))
    assert f'id="f-{spec.bundle.replace(".", "-")}-title"' in found, word
    assert f"?outil={spec.name}" in found, word


def test_the_grid_and_its_reasons_say_what_the_pipeline_offers(world):  # noqa: F811
    client, live, _ = world
    kernel = live.kernel
    ui = SimpleNamespace(kernel=kernel)
    # ses dessins seulement pour de vrai : sans fournisseur d'images configuré, « draw » n'est pas offert, et la
    # console dit pourquoi (ADR 0160) ; ensuite, un fournisseur est là
    account = next(s for s in page.situations(ui) if s.key == "compte")
    rights, close = gate_of(kernel.registry, account.frame)
    assert "draw" not in page.offered_in(ui, account)
    assert "configuré" in page.why_not(kernel.registry.tools["draw"], kernel.runner.policies[account.kind], account,
                                       kernel.registry.tools, rights, close, ports=kernel.runner.ports)
    kernel.runner.ports["imaging"] = SimpleNamespace(configured=True)
    offers = {}
    for s in page.situations(ui):
        policy = kernel.runner.policies[s.kind]
        offered = page.offered_in(ui, s)
        # la console et le pipeline passent par la même porte
        assert offered == kernel.runner._tools(policy, s.kind, s.audience, frame=s.frame), s.key
        rights, close = gate_of(kernel.registry, s.frame)
        for name, spec in kernel.registry.tools.items():
            why = page.why_not(spec, policy, s, kernel.registry.tools, rights, close, ports=kernel.runner.ports)
            assert (why == "") == (name in offered), (s.key, name, why)
        offers[s.key] = offered
    # cibles d'intention : sa boîte, pour sa propriétaire en privé seulement ; ses dessins, pour qui a un compte
    assert "email_read" in offers["proprietaire"]
    assert "email_read" not in offers["compte"] and "email_read" not in offers["salon"]
    assert "draw" in offers["compte"] and "draw" not in offers["inconnue"] and "draw" not in offers["salon"]
    assert not any(spec.owner_only for spec in offers["salon"].values())
    # et sa fiche le rend : oui pour sa propriétaire, non en salon — fermé par ses droits (le minimum vital)
    bootstrap(client)
    fiche = html_of(client.get(f"{BASE}/tous", params={"outil": "email_read"}))
    assert _where(fiche, "Elle répond à sa propriétaire, en privé").startswith("oui")
    assert _where(fiche, "Elle répond dans un salon, devant plusieurs personnes").startswith("non — fermé par ses droits")


def test_a_tool_waiting_for_its_port_says_what_is_missing_and_where_to_set_it(world):  # noqa: F811
    """La fiche de draw sans fournisseur d'images disait « non — « imaging » n'est pas configuré » : la clé d'un port,
    sans dire où le régler. Elle dit ce qui manque en mots, et mène une fois, sous ses situations, à la page qui le
    règle ; un outil des cartes dont la composition ne branche pas le port mène à « Lieux et adresses ». Le port
    prêt, plus de lien."""
    client, live, _ = world
    bootstrap(client)
    ports = live.kernel.runner.ports
    account = next(s.label for s in page.situations(SimpleNamespace(kernel=live.kernel)) if s.key == "compte")
    raw = client.get(f"{BASE}/tous", params={"outil": "draw"}).text
    ConsoleHTML(raw).check()
    fiche = html.unescape(raw)
    assert _where(fiche, account) == "non — aucun fournisseur d'images n'est configuré"
    assert "« imaging »" not in fiche
    assert fiche.count("Pour l'offrir") == 1
    assert re.search(r"Pour l'offrir : <a href=\"/admin/reglages/images-fournisseurs\">Fournisseurs d'images</a>",
                     fiche)
    maps = ports.pop("maps")
    try:
        places = html_of(client.get(f"{BASE}/tous", params={"outil": "places_search"}))
        assert _where(places, account) == "non — les lieux, les adresses et les itinéraires ne sont pas branchés"
        assert 'Pour l\'offrir : <a href="/admin/reglages/lieux">Lieux et adresses</a>' in places
    finally:
        ports["maps"] = maps
    assert "Pour l'offrir" not in html_of(client.get(f"{BASE}/tous", params={"outil": "places_search"}))
    ports["imaging"] = SimpleNamespace(configured=True)
    ready = html_of(client.get(f"{BASE}/tous", params={"outil": "draw"}))
    assert _where(ready, account).startswith("oui") and "Pour l'offrir" not in ready


def test_what_she_reads_is_her_prompt(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    body = html_of(client.get(f"{BASE}/tous"))
    prompts = dict(re.findall(r'<details class="can-prompt"><summary>(.*?)</summary><pre>(.*?)</pre>', body, re.S))
    assert ACTING[:40] in prompts["Elle répond à sa propriétaire, en privé"]
    # un pas sur un but : personne ne lit sa parole, la règle de ses mains n'y est pas
    assert ACTING[:40] not in prompts["Elle avance seule sur un de ses buts"]


def _family(client, bundle: str, faire: str = "", **fields: str):
    data = {"csrf": client.cookies.get("csrftoken"), "cle": bundle, "faire": faire, **fields}
    return client.post(f"{BASE}/familles/regler", data=data, follow_redirects=False)


def test_an_operator_rules_her_tools_by_their_family(world):  # noqa: F811
    """Une ligne de sa famille qui ferme un outil à sa propriétaire : le pipeline ne l'offre plus là, et la console
    le dit (sa fiche) ; ailleurs, rien ne change. Revenir au minimum vital efface. Sans jeton, rien."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    ui = SimpleNamespace(kernel=kernel)
    owner, room, step = (next(s for s in page.situations(ui) if s.key == key) for key in ("proprietaire", "salon", "pas"))
    assert "email_read" in page.offered_in(ui, owner) and "email_read" in page.offered_in(ui, step)
    before_room = page.offered_in(ui, room)
    saved = _family(client, "email", **{
        "ligne.1": "1", "qui.1|proprietaire": "on", "toujours.1": "on", "lecture.1": "non", "action.1": "non",
        "garde.1": "rien", "prend.1|email_read": "on",
        "ligne.2": "2", "qui.2|proprietaire": "on", "toujours.2": "on", "lecture.2": "seule", "action.2": "seule",
        "garde.2": "public", "tous.2": "on",
        "ligne.3": "3", "qui.3|elle": "on", "canal.3|interne": "on", "lecture.3": "seule", "action.3": "seule", "garde.3": "public",
        "tous.3": "on", "defaut_lecture": "non", "defaut_action": "non", "defaut_garde": "rien"})
    assert saved.status_code == 303 and saved.headers["location"].startswith(f"{BASE}/tous?")
    assert "email_read" not in page.offered_in(ui, owner) and "email_list" in page.offered_in(ui, owner)
    assert "email_read" not in kernel.runner._tools(kernel.runner.policies[owner.kind], owner.kind, owner.audience,
                                                    frame=owner.frame)
    assert "email_read" in page.offered_in(ui, step)  # elle seule garde sa ligne
    assert page.offered_in(ui, room) == before_room  # ailleurs, rien ne change
    after = html_of(client.get(saved.headers["location"]))
    assert "enregistrés" in after and 'name="prend.1|email_read" checked' in after
    fiche = html_of(client.get(f"{BASE}/tous", params={"outil": "email_read"}))
    assert _where(fiche, "Elle répond à sa propriétaire, en privé").startswith("non — fermé par ses droits (ligne 1")
    audit = client.portal.call(lambda: kernel.mind.store.latest([rt.OPERATED.name], 5))
    assert any("console.outils.familles" in a.data for a in audit)
    # revenir au minimum vital
    reset = _family(client, "email", "remettre")
    assert reset.status_code == 303 and "email" not in live.settings.families()
    assert "email_read" in page.offered_in(ui, owner)
    refused = client.post(f"{BASE}/familles/regler", data={"csrf": "faux", "cle": "email", "faire": "remettre"},
                          follow_redirects=False)
    assert refused.status_code == 303 and live.settings.families() == {}


def _place(client, tool: str, place: str, **fields: str):
    data = {"csrf": client.cookies.get("csrftoken"), "outil": tool, "place": place, **fields}
    return client.post(f"{BASE}/place/regler", data=data, follow_redirects=False)


def _placed(client, live) -> list[tuple[str, str, str]]:
    """Les gestes « Place d'un outil réglée » audités : (qui, la sorte de son sujet, son sujet)."""
    ops = client.portal.call(lambda: live.kernel.mind.store.latest([rt.OPERATED.name], 50))
    said = [json.loads(o.data) for o in ops]
    return [(s["by"], s["subject_kind"], s["subject"]) for s in said if s["action"] == "console.outils.place"]


def test_an_operator_sets_the_place_of_a_tool_of_her_code_on_its_fiche(world, monkeypatch):  # noqa: F811
    """Sa place (ADR 0123, 0134) : sur la fiche d'un outil de son code, « à chercher quand il lui faut » le sort de
    son prompt là où son fournisseur sait différer, « sous la main » l'y met, « ce que prévoit le code » retire le
    réglage ; chaque geste est audité, et la fiche le dit aussitôt. Un outil qui clôt sa boucle, un outil venu
    d'ailleurs, un outil inconnu ou un fournisseur qui reçoit tout n'ont pas ce choix : la route le refuse sans rien
    écrire. Sans jeton, rien."""
    client, live, backend = world
    bootstrap(client)
    owner = "Elle répond à sa propriétaire, en privé"

    def fiche(name: str) -> str:
        return html_of(client.get(f"{BASE}/tous", params={"outil": name}))

    def in_hand() -> dict[str, str]:
        return client.portal.call(live.settings.in_hand)

    # par défaut, ce que prévoit le code : la mémoire au socle d'une réponse, le courrier à chercher
    shown = fiche("memory_search")
    assert _where(shown, owner) == "oui, sous la main" and 'name="place"' in shown
    assert '<option value="" selected>ce que prévoit le code</option>' in shown
    assert _where(fiche("email_read"), owner) == "oui, à chercher quand il lui faut"
    # « à chercher » : enregistré, audité, la fiche le dit — et l'on y revient, ses filtres gardés
    saved = _place(client, "memory_search", "ask", q="memory")
    location = saved.headers["location"]
    assert saved.status_code == 303 and parse_qs(urlsplit(location).query)["q"] == ["memory"]
    assert in_hand() == {"memory_search": "ask"}
    after = html_of(client.get(location))
    assert "Sa place : à chercher quand il lui faut. Vaut dès son prochain épisode." in after
    assert _where(after, owner) == "oui, à chercher quand il lui faut"
    assert '<option value="ask" selected>à chercher quand il lui faut</option>' in after
    assert _placed(client, live) == [("user_1", "outil", "memory_search")]
    # « sous la main » : un outil que le code laisse à chercher passe dans son prompt
    assert _place(client, "email_read", "hand").status_code == 303
    assert _where(fiche("email_read"), owner) == "oui, sous la main"
    # « ce que prévoit le code » : le réglage retiré
    _place(client, "memory_search", "")
    assert in_hand() == {"email_read": "hand"} and _where(fiche("memory_search"), owner) == "oui, sous la main"
    assert len(_placed(client, live)) == 3
    # refusé, rien d'écrit ni d'audité : une place inconnue, un outil inconnu, sans jeton
    assert "Cette place n'existe pas" in html_of(client.get(_place(client, "memory_search", "off").headers["location"]))
    assert "ne se règle pas ici" in html_of(client.get(_place(client, "rien_du_tout", "ask").headers["location"]))
    client.post(f"{BASE}/place/regler", data={"csrf": "faux", "outil": "memory_search", "place": "ask"})
    assert in_hand() == {"email_read": "hand"} and len(_placed(client, live)) == 3
    # un outil qui clôt sa boucle (rendre compte d'un pas) : toujours offert, sa place ne se règle pas
    report = fiche("report_step")
    assert "oui, toujours (il clôt sa boucle)" in report and 'name="place"' not in report
    assert "ne se règle pas ici" in html_of(client.get(_place(client, "report_step", "ask").headers["location"]))
    # un outil venu d'un service ou d'une app : ses lignes se règlent sur leur fiche, pas sa place ici
    registry = live.kernel.registry
    static = registry.is_dynamic
    monkeypatch.setattr(registry, "is_dynamic", lambda name: name == "memory_search" or static(name))
    assert 'name="place"' not in fiche("memory_search")
    _place(client, "memory_search", "ask")
    monkeypatch.undo()
    # un fournisseur qui ne sait pas différer reçoit tout : le choix ne changerait rien, il n'est pas proposé
    backend.defers_tools = False
    shown = fiche("memory_search")
    assert _where(shown, owner) == "oui, sous la main" and 'name="place"' not in shown
    _place(client, "memory_search", "ask")
    assert in_hand() == {"email_read": "hand"} and len(_placed(client, live)) == 3


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
    # une seule famille, son tableau ouvert
    assert 'id="f-email"' in response.text and '<details class="access-rules" open>' in response.text
    assert _shown(response.text) and all(n.startswith("email_") for n in _shown(response.text))
    link = html.unescape(re.search(r'href="([^\"]*outil=email_read[^\"]*)"', response.text).group(1))
    assert parse_qs(urlsplit(link).query)["lot"] == ["email"]
    detail = client.get(link)
    ConsoleHTML(detail.text).check()
    assert "<h1>email_read</h1>" in detail.text and "Arguments et règles d’utilisation" in detail.text
    crumb = re.search(r'<nav class="crumbs".*?</nav>', html.unescape(detail.text), re.S).group()
    assert f"{BASE}/tous?lot=email" in crumb
    accented = _shown(client.get(f"{BASE}/tous?q=écrire").text)
    assert accented and accented == _shown(client.get(f"{BASE}/tous?q=ecrire").text)
    assert "Aucune famille ne correspond" in client.get(f"{BASE}/tous?q=aucun-resultat").text
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
    digest = read("console_mcp_digest")
    shown = client.get(made.headers["location"])
    ConsoleHTML(shown.text).check()
    assert "claude mcp add --transport http mika" in html_of(shown)
    # « Copier la ligne », « Copier le jeton » : une rangée neutre, jamais la barre d'enregistrement collée en bas
    copies = re.findall(r'<div class="([^"]*)"><button type="button" class="btn small" data-copy="(expose-\w+)"',
                        shown.text)
    assert [target for _, target in copies] == ["expose-command", "expose-token"]
    assert all("form-actions" not in classes.split() for classes, _ in copies)
    token = re.search(r"Bearer ([A-Za-z0-9_\-]{20,})", html_of(shown)).group(1)
    assert digest and hashlib.sha256(token.encode()).hexdigest() == digest  # seule l'empreinte est gardée
    rows = client.portal.call(lambda: live.kernel.mind.store.query_mind("SELECT value FROM settings"))
    assert all(token not in r[0] for r in rows)
    assert token not in client.get(made.headers["location"]).text  # une seule fois
    served = _expose(client, "console_servir", servi=["systeme.sante", "vues"])
    assert served.status_code == 303 and read("console_mcp_served") == ("systeme.sante", "vues")
    assert "http://127.0.0.1:8001/mcp/console/" in html_of(client.get(f"{BASE}/expose"))
    assert _expose(client, "console_reseau_ouvrir").status_code == 303 and read("console_mcp_network")
    assert "http://localhost:8001/mcp/console/" in html_of(client.get(f"{BASE}/expose"))  # là où on la lit
    assert _expose(client, "console_reseau_fermer").status_code == 303 and not read("console_mcp_network")
    _expose(client, "console_reseau_ouvrir")
    assert _expose(client, "console_fermer").status_code == 303 and not read("console_mcp_digest")
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
    assert refused.status_code == 303 and not read("console_mcp_digest")
