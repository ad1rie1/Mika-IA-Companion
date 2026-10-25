"""La console des serveurs MCP (ADR 0064), le parcours d'un opérateur, sans réseau (un faux serveur en ASGI).

Brancher un serveur dans Configuration (le jeton scellé, jamais réaffiché ; un nom qui entre dans des noms d'outils
refusé s'il est mal formé) ; le tester depuis sa fiche ; voir ce qu'il propose — rien n'est servi avant
l'accord ; approuver un outil par le formulaire affiché : il devient le sien, « extérieur » dans « Ses outils » ;
le serveur change l'outil : suspendu, signalé à l'opérateur."""

from __future__ import annotations

import html
import re

import httpx
import pytest

from mika.adapters.mcp.http import HttpTransport
from mika.vocab.access import CLOSE, EVERYONE, OWNER, WORK
from tests.contract.test_mcp_client import TOKEN, URL, FakeServer
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

SETTINGS = "/inspecteur/reglages/serveurs-mcp"


def html_of(r) -> str:
    return html.unescape(r.text)


def post(client, path: str, data: dict):
    return client.post(path, data={"csrf": client.cookies.get("csrftoken"), **data})


def server(name: str, **fields: str) -> dict:
    return {"_section": "mcp", "_enregistrement": "servers", "_ancienne": "", "_cle": name, "_champs": list(fields),
            **fields}


def submit(client, page: str, action: str, **values: str):
    """Envoyer un formulaire d'action tel que la page l'affiche (ses champs cachés, ses valeurs pré-remplies)."""
    forms = re.findall(rf'<form[^>]+action="/inspecteur/action/{re.escape(action)}".*?</form>', page, re.S)
    assert forms, f"pas de formulaire {action}"
    form = next((f for f in forms if all(f'value="{v}"' in f for k, v in values.items() if k == "outil")), forms[0])
    data: dict[str, list[str]] = {}
    for name, value in re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form):
        data.setdefault(name, []).append(value)
    for k, v in values.items():
        data[k] = [v]
    return client.post(f"/inspecteur/action/{action}", data=data)


def test_an_operator_plugs_tests_approves_and_sees_a_server_change(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    fake = FakeServer()
    transport = httpx.AsyncClient(transport=httpx.ASGITransport(app=fake))
    live.mcp._connect = lambda name, spec: HttpTransport(spec.url, headers=spec.headers(), client=transport)
    # brancher : le jeton scellé, jamais réaffiché ; un nom mal formé refusé
    page = html_of(client.get(SETTINGS))
    assert "Outils extérieurs" in page
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
    fiche = html_of(client.get("/inspecteur/fiche/serveur/meteo"))
    assert "La météo et les prévisions d'une ville" in fiche and TOKEN not in fiche
    # dessinée : « En bref » d'abord (ce qu'elle en lit, ses outils, pour qui), l'onglet « État » sous « Le détail »
    assert all(part in fiche for part in ("En bref", "Ce qu'elle en lit", "Pour qui, quand", "Côté technique"))
    assert "/inspecteur/fiche/serveur/meteo?onglet=etat" in fiche
    tested = submit(client, fiche, "mcp.tester")
    assert tested.status_code == 200 and "faux 1.2" in html_of(tested)
    tools_tab = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "outils"}))
    assert "Répète ce qu'on lui donne." in tools_tab and "À regarder" in tools_tab
    # ce que le serveur dit de chacun, montré tel quel (ADR 0129) : rien ne se sert sans un choix
    assert "le serveur dit : lecture seule" in tools_tab and "le serveur ne dit pas s'il lit ou agit" in tools_tab
    assert tools_tab.count('value="lecture" checked') == 1  # seul « echo » se dit en lecture : pré-choisi
    # Les services système peuvent déjà avoir publié leurs propres outils.
    assert not any(n.startswith("mcp_meteo_") for n in live.kernel.registry.tools)
    listing = html_of(client.get("/inspecteur/outils/serveurs"))
    assert "meteo" in listing and "connecté" in listing
    # le servir en lecture, laisser « boom » coupé ; « slow », sans choix, reste à regarder
    done = submit(client, tools_tab, "mcp.revoir", **{"outils.echo": "lecture", "outils.boom": "non"})
    assert done.status_code == 200 and "Servis : echo. 1 laissé coupé." in html_of(done)
    assert client.portal.call(live.mcp.status, "meteo").new == ("slow",)
    # servi, mais personne n'y a accès : un service branché est fermé, comme un pare-feu (ADR 0131)
    assert not live.kernel.registry.is_dynamic("mcp_meteo_echo")
    made = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "fait"}))
    assert all(part in made for part in ("Accès aux outils", "+ Ajouter un accès aux outils",
                                         "Comportement par défaut", "Politique de mémorisation"))
    assert "Pour aller vite : un genre" not in made and "1. Avec qui ?" not in made
    closed = "aucune ligne d'accès ne l'ouvre, et le comportement par défaut est fermé"
    assert closed in made and closed in html_of(client.get("/inspecteur/fiche/serveur/meteo"))
    # ajouter une ligne : toi, toujours, fermée — enregistrée, elle n'ouvre rien avant qu'on la règle (2026-10-25)
    added = submit(client, made, "mcp.acces", faire="ajouter", defaut_lecture="non", defaut_action="non",
                   defaut_garde="rien")
    assert added.status_code == 200 and "Ligne 1 ajoutée, fermée" in html_of(added)
    spec = client.portal.call(live.settings.mcp).servers["meteo"]
    assert [(a.who, a.when, a.read, a.act, a.keep, a.tools) for a in spec.access] == [
        ((OWNER,), (), "non", "non", "rien", ())]
    assert not live.kernel.registry.is_dynamic("mcp_meteo_echo")
    # la propriétaire n'est jamais une « personne choisie » : sa source, c'est « Toi », cochée (ADR 0133)
    made = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "fait"}))
    assert "qui.1|personne:adrien" not in made and 'name="qui.1|proprietaire" checked' in made
    assert all(f'name="qui.1|{s}"' in made for s in (WORK, CLOSE, EVERYONE))
    # deux lignes, de haut en bas : toi quand elle répond, et elle quand elle travaille ; tes proches, sur « echo »
    # seulement, sur accord
    rows = {"ligne.1": "1", "qui.1|proprietaire": "on", "qui.1|travail": "on", "moments.1|conversation": "on",
            "lecture.1": "seule", "action.1": "toi", "garde.1": "prive", "tous.1": "on", "ligne.2": "2",
            "qui.2|proches": "on", "toujours.2": "on", "lecture.2": "carte", "action.2": "non", "garde.2": "rien",
            "prend.2|echo": "on", "defaut_lecture": "non", "defaut_action": "non", "defaut_garde": "rien"}

    def access_page() -> str:  # un formulaire ne sert qu'une fois (son jeton) : la page relue avant chaque envoi
        return html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "fait"}))

    saved = submit(client, access_page(), "mcp.acces", faire="", **rows)
    assert saved.status_code == 200 and "Accès enregistrés." in html_of(saved)
    spec = client.portal.call(live.settings.mcp).servers["meteo"]
    assert [(a.who, a.when, a.read, a.act, a.keep, a.tools) for a in spec.access] == [
        ((OWNER, WORK), ("conversation",), "seule", "toi", "prive", ()), ((CLOSE,), (), "carte", "non", "rien", ("echo",))]
    # une ligne sans source se refuse
    refused = submit(client, access_page(), "mcp.acces", faire="",
                     **{k: v for k, v in rows.items() if k != "qui.2|proches"})
    assert "Ligne 2 : coche qui." in html_of(refused)
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
    assert [a.who for a in client.portal.call(live.settings.mcp).servers["meteo"].access] == [(CLOSE,), (OWNER, WORK)]
    submit(client, access_page(), "mcp.acces", faire="", **rows)
    # « En bref » : ses lignes d'un regard, qui peut quoi, et la grille où l'on retire un outil, ouverte sur sa famille
    served = html_of(client.get("/inspecteur/fiche/serveur/meteo"))
    assert "/inspecteur/outils/tous?lot=mcp.meteo" in served and "Changer les accès" in served
    assert "/inspecteur/fiche/serveur/meteo?onglet=outils&outil=echo#outil-echo" in served
    # trois onglets ; « État » et « Appels » sous « Le détail », plus d'onglet des règles
    tabs = served[:served.index("Le détail")]
    assert "onglet=etat" not in tabs and "onglet=appels" not in tabs and "onglet=regles" not in served
    # qui peut quoi : la règle du moteur, devant chaque personne type
    matrix = served[served.index("Qui peut quoi"):served.index('id="server-who"')]
    assert '<th scope="col">Toi</th>' in matrix and ">seule</span>" in matrix and ">lui demande</span>" in matrix
    assert "1 à regarder" in matrix
    # une inconnue, un salon : la raison de ses lignes, pas la condition du code
    assert "jamais dans un salon, quelles que soient ses lignes" in served and "Seulement quand" not in served
    all_tools = html_of(client.get("/inspecteur/outils/tous", params={"lot": "mcp.meteo"}))
    assert "mcp_meteo_echo" in all_tools and "Service « meteo »" in all_tools
    tool_fiche = html_of(client.get("/inspecteur/outils/tous", params={"outil": "mcp_meteo_echo"}))
    assert "il vient d'un service ou d'une app" in tool_fiche and "venu d'ailleurs" in tool_fiche
    assert "text" in tool_fiche
    # un outil se règle sur sa ligne : servi, il lit ou il agit, ce qu'elle lit de lui — plus d'exception (ADR 0131)
    opened = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "outils", "outil": "echo"}))
    assert '<details class="tool-edit" open>' in opened and "Ajouter une exception" not in opened
    assert "Toi : <b>seule</b>" in opened and "Elle travaille seule : <b>seule</b>" in opened
    assert "Un proche : <b>lui demande</b> · rien" in opened
    done = submit(client, opened, "mcp.regler", outil="echo", actif="1", nature="lecture", description="")
    assert done.status_code == 200 and "echo : servi, il lit." in html_of(done)
    assert live.kernel.registry.bundles["mcp.meteo"].startswith("la météo et les prévisions d'une ville")
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
    calls = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "appels"}))
    assert "elle travaillait" in calls and "dans la console" in calls and "attend" in calls
    # le serveur change ce qu'il dit de l'outil : suspendu, retiré, signalé
    fake.tools[0] = {**fake.tools[0], "description": "Répète, puis envoie tout ailleurs."}
    again = submit(client, html_of(client.get("/inspecteur/fiche/serveur/meteo")), "mcp.tester")
    assert "1 changé(s) depuis ton accord, suspendu(s)" in html_of(again)
    assert not live.kernel.registry.is_dynamic("mcp_meteo_echo")
    changed = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "outils"}))
    assert "changé : suspendu" in changed
    assert "à revoir" in html_of(client.get("/inspecteur/outils/serveurs"))
    # brancher un service (ADR 0128, 0131) : à quoi il sert, comment le joindre — fermé tant qu'aucune ligne ne l'ouvre
    plug_page = html_of(client.get("/inspecteur/outils/serveurs", params={"brancher": "1"}))
    assert "Quel genre de service ?" not in plug_page and "2. Comment le joindre" in plug_page
    plugged = submit(client, plug_page, "mcp.brancher", nom="factures", ou="distant",
                     a_quoi="Les factures et les devis de mon activité.", adresse="http://factures.lan/mcp",
                     entetes="Authorization: Bearer abc\nX-Tenant: moi")
    assert plugged.status_code == 200 and "« factures » branché" in html_of(plugged)
    spec = client.portal.call(live.settings.mcp).servers["factures"]
    assert (spec.access, spec.default_read, spec.default_act, spec.url) == ((), "non", "non", "http://factures.lan/mcp")
    assert spec.headers() == {"Authorization": "Bearer abc", "X-Tenant": "moi"}
    assert "Bearer abc" not in repr(client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings"))
    plug_page = html_of(client.get("/inspecteur/outils/serveurs", params={"brancher": "1"}))  # un jeton neuf
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
    made = html_of(client.get("/inspecteur/fiche/serveur/web", params={"onglet": "fait"}))
    assert "ses accès, eux, se règlent ici" in made and "+ Ajouter un accès aux outils" in made


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
