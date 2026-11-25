"""La console des serveurs MCP (ADR 0064), le parcours d'un opérateur, sans réseau (un faux serveur en ASGI).

Brancher un serveur dans Configuration (le jeton scellé, jamais réaffiché ; un nom qui entre dans des noms d'outils
refusé s'il est mal formé) ; le tester depuis sa fiche ; voir ce qu'il propose — rien n'est servi avant
l'accord ; approuver un outil par le formulaire affiché : il devient le sien, « extérieur » dans « Ses outils » ;
le serveur change l'outil : suspendu, signalé à l'opérateur."""

from __future__ import annotations

import html
import re
from types import SimpleNamespace as NS

import httpx
import pytest

from mika.adapters.mcp.http import HttpTransport
from mika.app.domains.tools.console import subject as server_fiche
from mika.app.handmade.access import KEEP_CHOICES, POLICY_CHOICES
from mika.kernel.inspect import Note
from mika.plugins.mcp.inspect import access_said
from mika.ports.mcp import KEEPS, Access
from mika.runtime.inspection import Inspection
from mika.vocab.access import CLOSE, EVERYONE, OWNER
from tests.contract.test_mcp_client import TOKEN, URL, FakeServer
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

SETTINGS = "/admin/reglages/serveurs-mcp"


def html_of(r) -> str:
    return html.unescape(r.text)


def brief_of(page: str) -> str:
    """Le contenu de « En bref » d'un serveur (``div.now-page.server``, jusqu'au technique replié) : sans la barre
    d'onglets, qui mène elle aussi à « Accès aux outils »."""
    start = page.index('<div class="now-page server">')
    return page[start:page.index('<details class="now-card server-tech">', start)]


def post(client, path: str, data: dict):
    return client.post(path, data={"csrf": client.cookies.get("csrftoken"), **data})


def server(name: str, **fields: str) -> dict:
    return {"_section": "mcp", "_enregistrement": "servers", "_ancienne": "", "_cle": name, "_champs": list(fields),
            **fields}


def submit(client, page: str, action: str, **values: str):
    """Envoyer un formulaire d'action tel que la page l'affiche (ses champs cachés, ses valeurs pré-remplies)."""
    forms = re.findall(rf'<form[^>]+action="/admin/action/{re.escape(action)}".*?</form>', page, re.S)
    assert forms, f"pas de formulaire {action}"
    form = next((f for f in forms if all(f'value="{v}"' in f for k, v in values.items() if k == "outil")), forms[0])
    data: dict[str, list[str]] = {}
    for name, value in re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form):
        data.setdefault(name, []).append(value)
    for k, v in values.items():
        data[k] = [v]
    return client.post(f"/admin/action/{action}", data=data)


def test_an_operator_plugs_tests_approves_and_sees_a_server_change(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    fake = FakeServer()
    transport = httpx.AsyncClient(transport=httpx.ASGITransport(app=fake))
    live.mcp._connect = lambda name, spec: HttpTransport(spec.url, headers=spec.headers(), client=transport)
    # brancher : le jeton scellé, jamais réaffiché ; un nom mal formé refusé
    page = html_of(client.get(SETTINGS))
    # ses réglages vivent dans Ses outils, derrière sa roue (ADR 0206) : l'ancienne adresse y mène ; la page se nomme
    # « Paramètres », comme la roue à une page des autres destinations (audit du 2026-11-05, C6-Q3)
    assert "<h1>Paramètres</h1>" in page and "un serveur MCP" in page and "Paramètres des services" not in page
    rule = "des minuscules, chiffres et _ (24 au plus), en commençant par une lettre"
    assert f"Le nom sous lequel les autres réglages le désignent : {rule}." in \
        html_of(client.get(SETTINGS, params={"enregistrement": "servers", "cle": "", "nouveau": "1"}))
    # refusé au champ « Nom », une seule fois (ni recopié dans le bandeau, ni en tête de la carte)
    bad = post(client, SETTINGS, server("Météo", purpose="la météo d'une ville", url=URL))
    assert bad.status_code == 400 and f'<span class="error">Nom refusé : {rule}.</span>' in html_of(bad)
    assert html_of(bad).count("Nom refusé") == 1 and "nom de serveur invalide" not in html_of(bad)
    # seules les majuscules s'adaptent d'elles-mêmes : le nom se lit pareil
    r = post(client, SETTINGS, server("Meteo", purpose="la météo et les prévisions d'une ville", transport="distant",
                                      url=URL, auth="bearer", token=TOKEN, in_conversation="1", enabled="1"))
    assert r.status_code == 200, html_of(r)[:2000]
    assert "« meteo » enregistré. Le nom tapé, « Meteo », est passé en minuscules." in html_of(r)
    assert TOKEN not in r.text
    stored = client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings")
    assert TOKEN not in repr(stored)
    assert client.portal.call(live.settings.mcp).servers["meteo"].token == TOKEN
    # sa fiche : le tester charge ce qu'il propose ; rien n'est servi avant l'accord
    fiche = html_of(client.get("/admin/fiche/serveur/meteo"))
    assert "La météo et les prévisions d'une ville" in fiche and TOKEN not in fiche
    # dessinée : « En bref » d'abord (ce qu'elle en lit, ses outils, pour qui), l'onglet « État » sous « Le détail »
    assert all(part in fiche for part in ("En bref", "Ce qu'elle en lit", "Pour qui, quand", "Côté technique"))
    assert "/admin/fiche/serveur/meteo?onglet=etat" in fiche
    tested = submit(client, fiche, "mcp.tester")
    assert tested.status_code == 200 and "faux 1.2" in html_of(tested)
    tools_tab = html_of(client.get("/admin/fiche/serveur/meteo", params={"onglet": "outils"}))
    assert "Répète ce qu'on lui donne." in tools_tab and "À regarder" in tools_tab
    # ce que le serveur dit de chacun, montré tel quel (ADR 0129) : rien ne se sert sans un choix
    assert "le serveur dit : lecture seule" in tools_tab and "le serveur ne dit pas s'il lit ou agit" in tools_tab
    assert tools_tab.count('value="lecture" checked') == 1  # seul « echo » se dit en lecture : pré-choisi
    # Les services système peuvent déjà avoir publié leurs propres outils.
    assert not any(n.startswith("mcp_meteo_") for n in live.kernel.registry.tools)
    listing = html_of(client.get("/admin/outils/serveurs"))
    assert "meteo" in listing and "connecté" in listing
    # le servir en lecture, laisser « boom » coupé ; « slow », sans choix, reste à regarder
    done = submit(client, tools_tab, "mcp.revoir", **{"outils.echo": "lecture", "outils.boom": "non"})
    assert done.status_code == 200 and "Servis : echo. 1 laissé coupé." in html_of(done)
    assert client.portal.call(live.mcp.status, "meteo").new == ("slow",)
    # servi, mais personne n'y a accès : un service branché est fermé, comme un pare-feu (ADR 0131)
    assert not live.kernel.registry.is_dynamic("mcp_meteo_echo")
    made = html_of(client.get("/admin/fiche/serveur/meteo", params={"onglet": "fait"}))
    assert all(part in made for part in ("Accès aux outils", "+ Ajouter un accès aux outils",
                                         "Comportement par défaut", "Ce qu'elle en garde"))
    # les colonnes et les choix des tableaux de ses familles (ADR 0134 ; audit du 2026-11-05, C6-03)
    assert all(part in made for part in ('<th scope="col">Un outil qui lit</th>', "Seule — sans demander",
                                         "Demande ton accord", "Public — un savoir", "Personnel — un souvenir"))
    assert "Ce qu'elle sait" not in made and "Politique de" not in made and "Ton accord<" not in made
    assert "Pour aller vite : un genre" not in made and "1. Avec qui ?" not in made
    closed = "aucune ligne d'accès ne l'ouvre, et le comportement par défaut est fermé"
    shut = brief_of(html_of(client.get("/admin/fiche/serveur/meteo")))
    assert closed in made and closed in shut
    # son alerte le dit sans lien : le « Changer » de ses lignes, juste dessous, est le seul chemin de « En bref »
    # vers « Accès aux outils » (audit du 2026-11-05, C6-Q1)
    assert shut.count("onglet=fait") == 1 and "Ajouter un accès aux outils" not in shut
    # ajouter une ligne : toi, toujours, fermée — enregistrée, elle n'ouvre rien avant qu'on la règle (2026-10-25)
    added = submit(client, made, "mcp.acces", faire="ajouter", defaut_lecture="non", defaut_action="non",
                   defaut_garde="rien")
    assert added.status_code == 200 and "Ligne 1 ajoutée, fermée" in html_of(added)
    spec = client.portal.call(live.settings.mcp).servers["meteo"]
    assert [(a.who, a.when, a.read, a.act, a.keep, a.tools) for a in spec.access] == [
        ((OWNER,), (), "non", "non", "rien", ())]
    assert not live.kernel.registry.is_dynamic("mcp_meteo_echo")
    # la propriétaire n'est jamais une « personne choisie » : sa source, c'est « Toi », cochée (ADR 0133)
    made = html_of(client.get("/admin/fiche/serveur/meteo", params={"onglet": "fait"}))
    assert "qui.1|personne:adrien" not in made and 'name="qui.1|proprietaire" checked' in made
    assert all(f'name="qui.1|{s}"' in made for s in (CLOSE, EVERYONE)) and 'name="canal.1|interne"' in made
    # deux lignes, de haut en bas : toi quand elle répond ; tes proches, sur « echo » seulement, sur accord
    rows = {"ligne.1": "1", "qui.1|proprietaire": "on", "moments.1|conversation": "on",
            "lecture.1": "seule", "action.1": "toi", "garde.1": "prive", "tous.1": "on", "ligne.2": "2",
            "qui.2|proches": "on", "toujours.2": "on", "lecture.2": "carte", "action.2": "non", "garde.2": "rien",
            "prend.2|echo": "on", "defaut_lecture": "non", "defaut_action": "non", "defaut_garde": "rien"}

    def access_page() -> str:  # un formulaire ne sert qu'une fois (son jeton) : la page relue avant chaque envoi
        return html_of(client.get("/admin/fiche/serveur/meteo", params={"onglet": "fait"}))

    saved = submit(client, access_page(), "mcp.acces", faire="", **rows)
    assert saved.status_code == 200 and "Accès enregistrés." in html_of(saved)
    lined = access_page()  # les sélecteurs d'une ligne se nomment comme ses colonnes
    assert 'aria-label="Ce qu\'elle en garde, ligne 2"' in lined and "Politique de" not in lined
    spec = client.portal.call(live.settings.mcp).servers["meteo"]
    assert [(a.who, a.when, a.read, a.act, a.keep, a.tools) for a in spec.access] == [
        ((OWNER,), ("conversation",), "seule", "toi", "prive", ()), ((CLOSE,), (), "carte", "non", "rien", ("echo",))]
    # une ligne sans source se refuse
    refused = submit(client, access_page(), "mcp.acces", faire="",
                     **{k: v for k, v in rows.items() if k != "qui.2|proches"})
    assert "Ligne 2 : coche qui" in html_of(refused)
    assert live.kernel.registry.is_dynamic("mcp_meteo_echo")  # réglée, la ligne l'ouvre
    # « quand » se coche : une ligne sans moment se refuse
    refused = submit(client, access_page(), "mcp.acces", faire="",
                     **{k: v for k, v in rows.items() if k != "toujours.2"})
    assert "Ligne 2 : coche au moins un moment, ou « toujours »." in html_of(refused)
    # une ligne sans outil se refuse ; rien n'est écrit
    # (une case décochée n'est pas envoyée)
    refused = submit(client, access_page(), "mcp.acces", faire="",
                     **{k: v for k, v in rows.items() if k != "prend.2|echo"})
    assert "Ligne 2 : coche au moins un outil, ou « tous »." in html_of(refused)
    assert len(client.portal.call(live.settings.mcp).servers["meteo"].access) == 2
    # monter la seconde : l'ordre change, rien d'autre
    moved = submit(client, access_page(), "mcp.acces", faire="monter:2", **rows)
    assert "Ligne 2 montée." in html_of(moved)
    assert [a.who for a in client.portal.call(live.settings.mcp).servers["meteo"].access] == [(CLOSE,), (OWNER,)]
    submit(client, access_page(), "mcp.acces", faire="", **rows)
    # « En bref » : ses lignes d'un regard ; plus de grille où l'on retirerait un outil (ADR 0134 : « Ce qu'elle peut
    # faire » renvoie un service à sa fiche) — « Accès aux outils » seul (audit du 2026-11-05, C6-02)
    served = html_of(client.get("/admin/fiche/serveur/meteo"))
    assert "/admin/outils/tous?lot=mcp.meteo" not in served and "Régler outil par outil" not in served
    assert "La grille" not in served
    # un serveur réglé à la main : sa connexion se modifie dans Ses outils › Paramètres, ce qu'elle en lit aussi
    edit = "/admin/outils/parametres?section=mcp&enregistrement=servers&cle=meteo"
    assert ">Modifier la connexion</a>" in served and served.count(edit) >= 2 and ">Le changer</a>" in served
    # trois onglets ; « État » et « Appels » sous « Le détail », plus d'onglet des règles
    tabs = served[:served.index("Le détail")]
    assert "onglet=etat" not in tabs and "onglet=appels" not in tabs and "onglet=regles" not in served
    # « En bref » résume d'un regard (audit du 2026-11-05, C6-Q1) : qui peut quoi, outil par outil, n'est que dans
    # « Ses outils » (plus bas) ; ses outils non servis s'y disent d'un mot, accordé ; « Changer » est son seul lien
    # vers « Accès aux outils » (plus de « Changer les accès », plus de bouton sous « Pour qui, quand »)
    brief = brief_of(served)
    assert "Qui peut quoi" not in brief and '<th scope="col">Toi</th>' not in brief and "Changer les accès" not in brief
    assert "Pas servis : <span>1 désactivé</span> <span>1 à regarder</span>" in brief
    assert brief.count("onglet=fait") == 1 and ">Changer</a>" in brief and "« Accès aux outils », plus haut" in brief
    # une inconnue, un salon : la raison de ses lignes, pas la condition du code
    assert "jamais dans un salon, quelles que soient ses lignes" in served and "Seulement quand" not in served
    all_tools = html_of(client.get("/admin/outils/tous", params={"lot": "mcp.meteo"}))
    assert "mcp_meteo_echo" in all_tools and "Service « meteo »" in all_tools
    tool_fiche = html_of(client.get("/admin/outils/tous", params={"outil": "mcp_meteo_echo"}))
    assert "il vient d'un service ou d'une app" in tool_fiche and "venu d'ailleurs" in tool_fiche
    assert "text" in tool_fiche
    # un outil se règle sur sa ligne : servi, il lit ou il agit, ce qu'elle lit de lui — plus d'exception (ADR 0131)
    opened = html_of(client.get("/admin/fiche/serveur/meteo", params={"onglet": "outils", "outil": "echo"}))
    assert '<details class="tool-edit" open>' in opened and "Ajouter une exception" not in opened
    assert "Toi : <b>seule</b>" in opened and "Elle travaille seule" not in opened  # aucune ligne « elle seule »
    assert "Un proche : <b>lui demande</b> · rien" in opened
    # la légende de ces mots est là où ils se lisent (audit du 2026-11-05, C6-Q1)
    assert "« te demande » : une carte dans ton chat" in opened and "« lui demande » : une carte à la personne" in opened
    done = submit(client, opened, "mcp.regler", outil="echo", actif="1", nature="lecture", description="")
    assert done.status_code == 200 and "echo : servi, il lit." in html_of(done)
    assert live.kernel.registry.bundles["mcp.meteo"].startswith("la météo et les prévisions d'une ville")
    # deux outils non servis du même mot : « En bref » accorde (« 2 désactivés », jamais « 2 désactivé ») ; « echo »
    # coupé (la case « Activé » décochée n'est pas envoyée), puis servi de nouveau pour la suite
    echo_page = {"onglet": "outils", "outil": "echo"}
    cut = submit(client, html_of(client.get("/admin/fiche/serveur/meteo", params=echo_page)), "mcp.regler",
                 outil="echo", nature="lecture", description="")
    assert cut.status_code == 200 and "echo : coupé, il lit." in html_of(cut)
    two_off = brief_of(html_of(client.get("/admin/fiche/serveur/meteo")))
    assert "Pas servis : <span>2 désactivés</span> <span>1 à regarder</span>" in two_off
    back = submit(client, html_of(client.get("/admin/fiche/serveur/meteo", params=echo_page)), "mcp.regler",
                  outil="echo", actif="1", nature="lecture", description="")
    assert back.status_code == 200 and "echo : servi, il lit." in html_of(back)
    # ses appels : un appel sur accord a sa ligne — pour qui, où l'accord se décide, où il en est
    import json as _json

    from mika.contracts import runtime as rt
    from mika.kernel.events import Content, Origin

    async def ask() -> None:
        args = {"server": "meteo", "remote": "echo", "args": {"text": "Lyon"}, "fingerprint": "f", "request": "e9:t1",
                "target": "", "approval": "operateur", "keep": "public",
                rt.EXPIRES: live.kernel.mind.clock.now() + 600_000_000}
        await live.kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="mcp.call", owner="mcp", args_json=_json.dumps(args), summary=Content.of("Appeler echo"),
            approval=True, context="mcp:meteo")], emitter="runtime", correlation="e9", origin=Origin.TOOL)

    client.portal.call(ask)
    calls = html_of(client.get("/admin/fiche/serveur/meteo", params={"onglet": "appels"}))
    assert "elle travaillait" in calls and "dans la console" in calls and "attend" in calls
    # le serveur change ce qu'il dit de l'outil : suspendu, retiré, signalé
    fake.tools[0] = {**fake.tools[0], "description": "Répète, puis envoie tout ailleurs."}
    again = submit(client, html_of(client.get("/admin/fiche/serveur/meteo")), "mcp.tester")
    said = html_of(again)
    assert "1 changé depuis ton accord, suspendu)" in said and "changé(s)" not in said and "outil(s)" not in said
    # la vue du plugin (la console en MCP, le repli) accorde aussi : un nouveau et un changé
    ins = Inspection(live.kernel)
    head = client.portal.call(ins.head, "serveur", "meteo")
    assert "2 outils à revoir" in [b.text for b in head.badges]
    noted = client.portal.call(lambda: ins.run(ins.find("mcp", "outils"), {}, subject="meteo"))
    assert any(isinstance(b, Note) and b.text.endswith("depuis ton accord : suspendu jusqu'à ce que tu le relises.")
               for b in noted)
    assert not live.kernel.registry.is_dynamic("mcp_meteo_echo")
    changed = html_of(client.get("/admin/fiche/serveur/meteo", params={"onglet": "outils"}))
    assert "changé : suspendu" in changed
    assert "à revoir" in html_of(client.get("/admin/outils/serveurs"))
    # brancher un service (ADR 0128, 0131) : à quoi il sert, comment le joindre — fermé tant qu'aucune ligne ne l'ouvre
    plug_page = html_of(client.get("/admin/outils/serveurs", params={"brancher": "1"}))
    assert "Quel genre de service ?" not in plug_page and "2. Comment le joindre" in plug_page
    plugged = submit(client, plug_page, "mcp.brancher", nom="factures", ou="distant",
                     a_quoi="Les factures et les devis de mon activité.", adresse="http://factures.lan/mcp",
                     entetes="Authorization: Bearer abc\nX-Tenant: moi")
    assert plugged.status_code == 200 and "« factures » branché" in html_of(plugged)
    spec = client.portal.call(live.settings.mcp).servers["factures"]
    assert (spec.access, spec.default_read, spec.default_act, spec.url) == ((), "non", "non", "http://factures.lan/mcp")
    assert spec.headers() == {"Authorization": "Bearer abc", "X-Tenant": "moi"}
    assert "Bearer abc" not in repr(client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings"))
    plug_page = html_of(client.get("/admin/outils/serveurs", params={"brancher": "1"}))  # un jeton neuf
    again = submit(client, plug_page, "mcp.brancher", nom="factures", ou="distant",
                   a_quoi="Les mêmes, une seconde fois.", adresse="http://factures.lan/mcp")
    assert "un serveur s'appelle déjà « factures »" in html_of(again)
    client.portal.call(transport.aclose)


def test_the_web_search_access_is_set_on_its_page_and_kept_apart(world):  # noqa: F811
    """ADR 0131 : la recherche web, un serveur du système, a ses lignes d'accès réglées sur sa fiche — rangées à part,
    elles remplacent celles de son plugin ; le reste (sa commande, sa cage) ne se règle pas ici."""
    client, live, _ = world
    bootstrap(client)
    assert "web" in client.portal.call(live.mcp.statuses).__repr__()
    rows = [{"who": [OWNER], "when": ["conversation"], "read": "seule", "act": "non", "keep": "public", "tools": []}]
    client.portal.call(live.mcp.settle, "web", {"access": rows, "default_read": "non", "default_act": "non",
                                                "default_keep": "rien"})
    assert client.portal.call(live.settings.mcp_system_access)["web"]["access"] == rows
    (row,) = client.portal.call(live.mcp.status, "web").access
    assert (row.who, row.when, row.act) == ((OWNER,), ("conversation",), "non")
    with pytest.raises(ValueError):
        client.portal.call(live.mcp.settle, "web", {"command": "sh"})
    assert "web" not in client.portal.call(live.settings.mcp).servers  # pas rangé comme un serveur de l'opérateur
    made = html_of(client.get("/admin/fiche/serveur/web", params={"onglet": "fait"}))
    assert "ses accès, eux, se règlent ici" in made and "+ Ajouter un accès aux outils" in made


def test_the_web_search_fiche_leads_to_its_plugin_not_to_a_new_server(world):  # noqa: F811
    """Audit du 2026-11-05, C6-01 : la recherche web est un serveur du système (ADR 0066) — le client le dit
    (``ServerStatus.plugin``). Sa fiche ne mène jamais au formulaire d'un serveur ajouté du même nom (il y serait
    « à ajouter », et s'effacerait devant lui) : ses réglages sont les paramètres de son plugin ; ce qu'elle en lit
    vient de son plugin. Ses outils › Paramètres le nomme."""
    client, live, _ = world
    bootstrap(client)
    assert client.portal.call(live.mcp.status, "web").plugin == "web"
    for tab in ("", "etat", "fait", "outils"):
        page = html_of(client.get("/admin/fiche/serveur/web", params={"onglet": tab} if tab else {}))
        forms = [h for h in re.findall(r'href="([^"]*)"', page) if "outils/parametres?" in h and "cle=web" in h]
        assert forms == [], (tab, forms)
        assert 'href="/admin/reglages/comportement-web"' in page, tab
    brief = html_of(client.get("/admin/fiche/serveur/web"))
    assert ">Régler son plugin</a>" in brief and "Modifier la connexion" not in brief
    assert "ils ne se changent pas dans la console" in brief and ">Le changer</a>" not in brief
    services = html_of(client.get("/admin/outils/parametres"))
    assert '<a href="/admin/fiche/serveur/web">web, réglé par son plugin</a>' in services
    listed = html_of(client.get("/admin/outils/serveurs"))
    assert not [h for h in re.findall(r'href="([^"]*)"', listed) if "cle=web" in h]


def test_a_card_reaches_only_its_person_and_only_she_decides_it(world):  # noqa: F811
    """La carte d'accord dans le chat (ADR 0064) : à la seule personne qu'elle concerne, par ses connexions
    authentifiées ; une autre ne peut pas la décider ; refusée, la liste se vide. (L'outil n'est plus servi : la carte
    se dit bloquée, et l'accepter est refusé.)"""
    import json as _json

    from mika.contracts import runtime as rt
    from mika.kernel.events import Content, Origin
    from tests.protocol.test_web import WS, recv_until

    client, live, _ = world
    bootstrap(client)

    async def setup() -> tuple[str, int]:
        bea = await live.accounts.create("bea", "un-mot-de-passe-long", operator=False)
        key = await live.accounts.open_session(bea)
        args = {"server": "meteo", "remote": "prevision", "args": {"ville": "Lyon"}, "fingerprint": "f1",
                "request": "e1:t1", "target": "user_1", "approval": "conversation", rt.DECIDER: "user_1",
                rt.EXPIRES: live.kernel.mind.clock.now() + 600_000_000}
        commit = await live.kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="mcp.call", owner="mcp", args_json=_json.dumps(args), summary=Content.of("Appeler prevision"),
            approval=True, context="mcp:meteo", about=("user_1",))], emitter="runtime", correlation="test",
            origin=Origin.TOOL)
        return key, commit.seqs[-1]

    key_b, proposal = client.portal.call(setup)
    with client.websocket_connect(WS) as a, client.websocket_connect(WS, headers={"cookie": f"sessionid={key_b}"}) as b:
        card = next(f for f in recv_until(a, "approvals") if f["type"] == "approvals")["items"][0]
        assert card["id"] == proposal and '"ville": "Lyon"' in card["text"] and card["expires_at"]
        assert "n'est plus servi" in card["blocked"]
        b.send_json({"type": "approval", "id": proposal, "decision": "refuse", "digest": card["digest"]})
        result = next(f for f in recv_until(b, "approval_result") if f["type"] == "approval_result")
        assert result["status"] == "forbidden"
        a.send_json({"type": "approval", "id": proposal, "decision": "accept", "digest": card["digest"]})
        assert next(f for f in recv_until(a, "approval_result") if f["type"] == "approval_result")["status"] == \
            "blocked"
        a.send_json({"type": "approval", "id": proposal, "decision": "refuse", "digest": ""})
        frames = recv_until(a, "approval_result")
        assert frames[-1]["status"] == "rejected"
        assert next(f for f in recv_until(a, "approvals") if f["type"] == "approvals")["items"] == []
        b.send_json({"type": "ping", "t": 1})
        assert all(f["type"] != "approvals" or f["items"] == [] for f in recv_until(b, "pong"))


def test_the_services_settings_count_in_words(world, monkeypatch):  # noqa: F811
    """Ses outils › Paramètres : « 1 (1 actif et prêt) », « 2 (2 actifs et prêts) » — jamais
    « actif(s) et prêt(s) » (audit du 2026-11-05, C4-R1)."""
    from types import SimpleNamespace

    from mika.app.settings_sections.plugins import sections

    _, live, _ = world

    def facts(*ready: bool) -> str:
        servers = {f"s{i}": SimpleNamespace(enabled=True, ready=r) for i, r in enumerate(ready)}
        monkeypatch.setattr(live.settings, "mcp", lambda: SimpleNamespace(servers=servers))
        return dict(next(s for s in sections(live) if s.key == "mcp").facts())["Réglés ici"]

    assert facts(True) == "1 (1 actif et prêt)"
    assert facts(False, False) == "2 (0 actif et prêt)"
    assert facts(True, True) == "2 (2 actifs et prêts)"
    assert facts() == "aucun"


def test_a_server_summary_speaks_like_the_tables_of_its_families():
    """« En bref » d'un serveur, ses sélecteurs et ses réglages disent les mots des familles (``vocab.access``, ADR
    0134 ; audit du 2026-11-05, C6-03) : « un savoir », jamais « ce qu'elle sait » ; la ligne par défaut s'appelle
    « Comportement par défaut », comme dans les tableaux, plus « — »."""
    st = NS(access=(Access(who=(OWNER,), read="seule", act="toi", keep="public"),),
            default=Access(who=(), read="carte", act="non", keep="public"))
    rows = server_fiche._summary(st, None)
    assert rows[-1]["who"] == "Comportement par défaut" and rows[-1]["default"] and rows[0]["who"] != "—"
    assert [r["keep"] for r in rows] == ["un savoir", "un savoir"]
    assert (rows[0]["read"], rows[0]["act"], rows[1]["read"]) == ("seule", "ton accord", "demande à la personne")
    assert access_said(st).endswith("garde un savoir")
    assert dict(POLICY_CHOICES) == {"seule": "Seule — sans demander", "carte": "Demande à la personne en face",
                                    "toi": "Demande ton accord", "non": "Non"}
    assert dict(KEEP_CHOICES) == {"public": "Public — un savoir", "perso": "Personnel — un souvenir",
                                  "prive": "Privé — une confidence", "rien": "Rien"}
    assert dict(KEEPS)["public"] == "un savoir — peut se raconter"
    assert not [said for _, said in (*KEEPS, *KEEP_CHOICES) if "ce qu'elle sait" in said.casefold()]
