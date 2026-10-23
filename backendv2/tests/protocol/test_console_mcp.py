"""La console des serveurs MCP (ADR 0064), le parcours d'un opérateur, sans réseau (un faux serveur en ASGI).

Brancher un serveur dans Configuration (le jeton scellé, jamais réaffiché ; un nom qui entre dans des noms d'outils
refusé s'il est mal formé) ; le tester depuis sa fiche ; voir ce qu'il propose — rien n'est servi avant
l'accord ; approuver un outil par le formulaire affiché : il devient le sien, « extérieur » dans « Ses outils » ;
le serveur change l'outil : suspendu, signalé à l'opérateur."""

from __future__ import annotations

import html
import re

import httpx

from mika.adapters.mcp.http import HttpTransport
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
    assert "Répète ce qu'on lui donne." in tools_tab and "à regarder" in tools_tab
    # Les services système peuvent déjà avoir publié leurs propres outils.
    assert not any(n.startswith("mcp_meteo_") for n in live.kernel.registry.tools)
    listing = html_of(client.get("/inspecteur/outils/serveurs"))
    assert "meteo" in listing and "connecté" in listing
    # approuver « echo » sans accord : il devient le sien, et « venu d'ailleurs » dans Ses outils
    done = submit(client, tools_tab, "mcp.regler", outil="echo", actif="1", nature="lecture", seule="seule",
                  description="")
    assert done.status_code == 200 and "echo : activé" in html_of(done)
    assert live.kernel.registry.is_dynamic("mcp_meteo_echo")
    assert live.kernel.registry.bundles["mcp.meteo"].startswith("la météo et les prévisions d'une ville")
    # « Pour qui, quand » mène à la grille où l'on retire un outil, ouverte sur sa famille, et à ses réglages
    served = html_of(client.get("/inspecteur/fiche/serveur/meteo"))
    assert "/inspecteur/outils/tous?lot=mcp.meteo" in served and "Changer avec qui, et quand" in served
    assert "Ce qu'elle en fait" in served and "Par situation et par personne" in served
    all_tools = html_of(client.get("/inspecteur/outils/tous", params={"lot": "mcp.meteo"}))
    assert "mcp_meteo_echo" in all_tools and "Service « meteo »" in all_tools
    tool_fiche = html_of(client.get("/inspecteur/outils/tous", params={"outil": "mcp_meteo_echo"}))
    assert "il vient d'un service ou d'une app" in tool_fiche and "venu d'ailleurs" in tool_fiche
    assert "text" in tool_fiche
    # ce qu'elle en fait (ADR 0128) : un genre en un clic, puis les trois réglages, redits en une phrase
    made = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "fait"}))
    assert "En une phrase" in made and "Quel genre de service ?" in made
    picked = submit(client, made, "mcp.genre")  # le premier : « Mon travail, sous contrôle »
    assert picked.status_code == 200 and "« Mon travail, sous contrôle »" in html_of(picked)
    spec = client.portal.call(live.settings.mcp).servers["meteo"]
    assert (spec.with_owner, spec.with_accounts, spec.autonomy, spec.keep) == (True, False, "toi", "rien")
    made = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "fait"}))
    saved = submit(client, made, "mcp.service", avec_toi="on", avec_les_comptes="on", repond="on", seule="seule",
                   garde="public")
    assert saved.status_code == 200 and "Avec toi et toute personne qui a un compte" in html_of(saved)
    spec = client.portal.call(live.settings.mcp).servers["meteo"]
    assert spec.with_accounts and spec.autonomy == "seule" and spec.keep == "public" and not spec.in_work
    assert live.kernel.registry.is_dynamic("mcp_meteo_echo")
    # un outil, par situation et par personne : les règles s'enregistrent, « En clair » les redit
    rules = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "regles", "outil": "echo"}))
    assert "Par situation : la règle par défaut" in rules and "En clair" in rules
    # (un navigateur envoie la valeur de chaque liste ; ``submit`` ne lit que les champs cachés)
    ruled = submit(client, rules, "mcp.regles", s_proprietaire="service", s_compte="non", p1="user_9", r1="carte")
    assert ruled.status_code == 200 and "echo : 2 règles." in html_of(ruled)
    review = client.portal.call(live.mcp.status, "meteo").reviews["echo"]
    assert dict(review.situations) == {"compte": "non"} and dict(review.people) == {"user_9": "carte"}
    clear = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "regles", "outil": "echo"}))
    assert "Les autres comptes" in clear
    # le serveur change ce qu'il dit de l'outil : suspendu, retiré, signalé
    fake.tools[0] = {**fake.tools[0], "description": "Répète, puis envoie tout ailleurs."}
    again = submit(client, html_of(client.get("/inspecteur/fiche/serveur/meteo")), "mcp.tester")
    assert "1 changé(s) depuis ton accord, suspendu(s)" in html_of(again)
    assert not live.kernel.registry.is_dynamic("mcp_meteo_echo")
    changed = html_of(client.get("/inspecteur/fiche/serveur/meteo", params={"onglet": "outils"}))
    assert "changé : suspendu" in changed
    assert "à revoir" in html_of(client.get("/inspecteur/outils/serveurs"))
    # brancher un service en trois questions (ADR 0128) : son genre d'un coup, puis ses outils à servir
    plug_page = html_of(client.get("/inspecteur/outils/serveurs", params={"brancher": "1"}))
    assert "Quel genre de service ?" in plug_page and "Mon travail, sous contrôle" in plug_page
    plugged = submit(client, plug_page, "mcp.brancher", nom="factures", genre="pro", ou="distant",
                     a_quoi="Les factures et les devis de mon activité.", adresse="http://factures.lan/mcp",
                     entetes="Authorization: Bearer abc\nX-Tenant: moi")
    assert plugged.status_code == 200 and "« factures » branché" in html_of(plugged)
    spec = client.portal.call(live.settings.mcp).servers["factures"]
    assert (spec.autonomy, spec.keep, spec.with_accounts, spec.url) == ("toi", "rien", False, "http://factures.lan/mcp")
    assert spec.headers() == {"Authorization": "Bearer abc", "X-Tenant": "moi"}
    assert "Bearer abc" not in repr(client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings"))
    plug_page = html_of(client.get("/inspecteur/outils/serveurs", params={"brancher": "1"}))  # un jeton neuf
    again = submit(client, plug_page, "mcp.brancher", nom="factures", genre="pro", ou="distant",
                   a_quoi="Les mêmes, une seconde fois.", adresse="http://factures.lan/mcp")
    assert "un serveur s'appelle déjà « factures »" in html_of(again)
    client.portal.call(transport.aclose)


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
