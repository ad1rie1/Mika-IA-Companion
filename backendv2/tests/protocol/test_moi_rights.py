"""L'API par personne, Outils (ADR 0187) : la matrice de ses droits, case par case — la décision même de la porte
d'offre pour elle, par chaque canal et à chaque moment. Une propriétaire a ses outils réservés en privé, jamais dans
un salon ; une autre personne ne les a pas, sauf ce qu'une boîte à son nom lui ouvre (ADR 0185) ; ses comptes disent
la règle d'envoi qui vaut pour eux ; rien n'y montre les lignes d'une famille. Chaque outil s'y nomme pour elle
(``label``, ADR 0208), et le pourquoi d'une case ne lui dit que la part de la ligne qui la concerne — le numéro de la
ligne et la page de la console, seulement à une opératrice (ADR 0209)."""

from __future__ import annotations

import re

from mika.app.moi.rights import CANALS, MOMENTS, OWNED, WORK
from mika.app.system_mcp import spec as system_spec
from mika.plugins import web
from mika.plugins.mcp import specs_of
from mika.ports.mcp import CLOSED, Access, OfferedTool, ServerStatus
from mika.vocab.access import INTERNAL, OWNER, PERSON, SELF, Table, ToolRule
from mika.vocab.canals import CanalRule, CanalTable
from tests.fixtures.courrier import mailbox
from tests.protocol.test_moi_mail import API, login, owners, second_person
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

#: un numéro de ligne, tel que la console le dit (« ligne 2 ») : jamais à qui n'est pas opératrice
LINE_NUMBER = re.compile(r"\bligne \d")


def resources(got: dict, group: str) -> dict:
    return {r["key"]: r for g in got["groups"] if g["key"] == group for r in g["resources"]}


def tool(got: dict, family: str, name: str) -> dict:
    return next(t for t in resources(got, "families")[family]["tools"] if t["name"] == name)


def test_the_matrix_says_each_canal_and_moment(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    got = client.get(API + "/rights").json()
    assert [c["key"] for c in got["canals"]] == [k for k, _c, _l in CANALS]
    assert [m["key"] for m in got["moments"]] == [k for k, _kind, _l in (*MOMENTS, WORK)]
    assert [g["key"] for g in got["groups"]] == ["families", "accounts", "services", "apps"]
    memory = tool(got, "famille:memory", "memory_search")
    assert set(memory["cells"]) == {"web/reply", "web/initiative", "salon/reply", "salon/initiative", "mobile/reply",
                                    "mobile/initiative", "teams/reply", "teams/initiative", "courrier/reply",
                                    "courrier/initiative", "seule/work"}
    web = memory["cells"]["web/reply"]
    assert web["level"] == "seule" and web["why"] == "toi, toujours" and not web["owned"]
    assert all("lines" not in r for r in resources(got, "families").values())  # jamais les lignes d'une famille
    # son nom pour la personne, déclaré avec l'outil (ADR 0208) — pas sa consigne au modèle
    assert memory["label"] == live.kernel.registry.tools["memory_search"].label
    assert memory["label"] and memory["label"] != memory["description"]
    # une opératrice lit aussi la ligne même, et où la console la montre
    assert web["line"] == "ligne 1"
    assert resources(got, "families")["famille:memory"]["href"] == \
        "/inspecteur/reglages/droits?detail=famille%3Amemory"
    assert memory["cells"]["seule/work"]["why"] == "elle seule, quand elle travaille"


def test_her_reserved_tools_are_hers_in_private_never_in_a_room(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(1)
    got = client.get(API + "/rights").json()
    read = tool(got, "famille:email", "email_read")
    assert read["cells"]["web/reply"]["level"] == "seule"
    assert read["cells"]["salon/reply"]["level"] == "non"  # à plusieurs, jamais sa boîte, même la sienne
    accounts = resources(got, "accounts")
    assert set(accounts) >= {"courrier:perso", "courrier:pro"}
    pro = accounts["courrier:pro"]
    assert pro["family"] == "famille:email" and pro["rules"]["canal"] == "courrier:pro"
    assert pro["rules"]["lines"][0]["reply"] == "accord" and not pro["rules"]["lines"][0]["prepare"]  # minimum vital


def test_another_person_has_them_only_through_a_box_of_her_own(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(1)
    lea = second_person(client, live)
    login(client, "lea")
    got = client.get(API + "/rights").json()
    assert tool(got, "famille:email", "email_read")["cells"]["web/reply"]["level"] == "non"
    assert resources(got, "accounts") == {}

    login(client, "adrien")
    owners(client, live, pro="personne:" + lea)
    login(client, "lea")
    got = client.get(API + "/rights").json()
    cell = tool(got, "famille:email", "email_read")["cells"]["web/reply"]
    assert cell["level"] == "seule" and cell["owned"]  # sa boîte à elle lui ouvre ses outils de courrier
    assert cell["why"] == OWNED and "ADR" not in cell["why"]  # dit par le moteur, sans numéro d'ADR
    assert tool(got, "famille:email", "email_read")["cells"]["salon/reply"]["level"] == "non"
    assert set(resources(got, "accounts")) == {"courrier:pro"}


def test_a_rule_naming_her_owners_says_so_to_someone_else(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(1)
    lea = second_person(client, live)
    owners(client, live, pro="personne:" + lea)
    owner_line = CanalTable(lines=(CanalRule(who=(OWNER,), reply="accord"),))
    for canal in ("courrier:pro", "courrier:perso"):
        client.portal.call(live.settings.save_canal, canal, owner_line)
    mine = resources(client.get(API + "/rights").json(), "accounts")["courrier:perso"]
    assert mine["rules"]["lines"][0]["who"] == "Toi"  # dit à une de ses propriétaires
    login(client, "lea")
    hers = resources(client.get(API + "/rights").json(), "accounts")["courrier:pro"]
    assert hers["rules"]["lines"][0]["who"] == "Ses propriétaires"  # dit à quelqu'un d'autre


def test_the_why_of_a_cell_tells_her_only_her_part_of_the_line(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    hidden = "personne:zoe-cachee"
    memory = Table[ToolRule](lines=(
        ToolRule(who=(PERSON + lea, hidden), when=("conversation",), read="seule", act="seule", keep="public"),
        ToolRule(who=(OWNER,), read="seule", act="seule", keep="public"),
        ToolRule(who=(SELF,), canal=(INTERNAL,), read="seule", act="seule", keep="public")),
        default=ToolRule(read="non", act="non", keep="rien"))
    client.portal.call(live.settings.save_family, "memory", memory)

    mine = tool(client.get(API + "/rights").json(), "famille:memory", "memory_search")["cells"]
    assert (mine["web/reply"]["why"], mine["web/reply"]["line"]) == ("toi, toujours", "ligne 2")

    login(client, "lea")
    got = client.get(API + "/rights")
    cells = tool(got.json(), "famille:memory", "memory_search")["cells"]
    # la part de la ligne qui la désigne, elle : ni l'autre personne que la ligne nomme, ni son numéro
    assert cells["web/reply"]["level"] == "seule" and cells["web/reply"]["why"] == "toi, quand elle répond"
    assert cells["web/initiative"]["why"] == "par défaut : personne"  # aucune ligne ne la désigne alors
    assert "zoe" not in got.text and not LINE_NUMBER.search(got.text)
    rows = [t for g in got.json()["groups"] for r in g["resources"] for t in r.get("tools", ())]
    assert all(c is None or c["line"] == "" for t in rows for c in t["cells"].values())
    assert all(not r.get("href") for g in got.json()["groups"] for r in g["resources"])


def test_the_why_says_when_the_ceiling_closed_it(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    got = client.get(API + "/rights").json()
    registry = live.kernel.registry
    # un outil qui agit, ouvert à tout le monde par le minimum vital de sa famille : dans un salon, le plafond le ferme
    acting = next(t for r in resources(got, "families").values() for t in r["tools"]
                  if registry.tools[t["name"]].acts and t["cells"]["web/reply"] is not None
                  and t["cells"]["web/reply"]["level"] == "seule" and t["cells"]["salon/reply"] is not None)
    room = acting["cells"]["salon/reply"]
    assert room["level"] == "non" and room["why"].startswith("tout le monde") and "des témoins" in room["why"]


def test_an_account_says_the_rule_that_holds_for_it(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    live.kernel.ports["mail"] = mailbox(1)
    common = CanalTable(lines=(CanalRule(who=(OWNER,), prepare=True, reply="seule"),))
    client.portal.call(live.settings.save_canal, "courrier", common)  # tout le canal, réglé dans la console
    pro = resources(client.get(API + "/rights").json(), "accounts")["courrier:pro"]["rules"]
    # celle que le courrier lit pour cette boîte : la règle commune, pas le minimum vital
    assert (pro["set"], pro["common"]) == (False, True)
    assert pro["lines"][0]["reply"] == "seule" and pro["lines"][0]["prepare"]


def test_a_service_says_its_purpose_and_the_line_that_opens_it(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    port = live.kernel.ports["mcp"]
    line = Access(who=("tous",), when=("conversation",), read="seule", act="carte", keep="public")
    offered = OfferedTool("meteo", "prevision", "mcp_meteo_prevision", "Prévisions (consigne du serveur).", {},
                          "lecture", frozenset({"conversation"}), False, 3, "La météo d'une ville.", "", False,
                          access=(line,), default=CLOSED)
    # un service qu'elle a branché sous son compte (ADR 0192) : son but, tel qu'elle l'a écrit
    status = ServerStatus("meteo", "distant", True, True, "connecte", purpose="La météo d'une ville.",
                          owner=PERSON + lea, access=(line,), default=CLOSED)
    monkeypatch.setattr(port, "offered", lambda: (offered,))
    monkeypatch.setattr(port, "statuses", lambda: (status,))
    specs, bundles = specs_of((offered,))
    assert live.kernel.registry.set_dynamic("mcp", specs, bundles) == []
    login(client, "lea")
    got = client.get(API + "/rights").json()
    meteo = resources(got, "services")["mcp:meteo"]
    assert meteo["title"] == "Service « meteo »" and meteo["description"] == "La météo d'une ville."
    [row] = meteo["tools"]
    assert row["label"] == "" and row["description"]  # venu d'ailleurs : sa description le nomme
    assert row["cells"]["web/reply"]["level"] == "seule"
    assert row["cells"]["web/reply"]["why"] == "tout le monde, quand elle répond"
    assert row["cells"]["web/reply"]["line"] == ""


def test_a_service_of_hers_never_shows_the_line_of_her_catalogue(world, monkeypatch):  # noqa: F811
    """Le but d'un service de Mika (sans propriétaire : la recherche web du système, ou un service réglé dans la
    console) est la ligne de son catalogue, écrite pour elle (« un sujet qui te rend curieuse » : « te », c'est
    elle) : la personne ne le lit pas, ni sous son titre ni dans Services (ADR 0209)."""
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    port = live.kernel.ports["mcp"]
    served = system_spec(web.system_server(None))  # tel que la composition le branche
    assert served.owner == "" and served.purpose
    line = Access(who=("tous",), when=("conversation",), read="seule", act="toi", keep="public")
    offered = OfferedTool(web.SERVER, "search", "mcp_web_search", "Search the web (consigne du serveur).", {},
                          "lecture", frozenset({"conversation"}), False, 3, served.purpose, "", True,
                          access=(line,), default=CLOSED)
    status = ServerStatus(web.SERVER, served.transport, True, True, "connecte", purpose=served.purpose,
                          owner=served.owner, access=(line,), default=CLOSED)
    monkeypatch.setattr(port, "offered", lambda: (offered,))
    monkeypatch.setattr(port, "statuses", lambda: (status,))
    specs, bundles = specs_of((offered,))
    assert live.kernel.registry.set_dynamic("mcp", specs, bundles) == []
    login(client, "lea")
    got = client.get(API + "/rights")
    found = resources(got.json(), "services")["mcp:web"]
    assert found["title"] == "Service « web »" and found["tools"][0]["cells"]["web/reply"]["level"] == "seule"
    assert found["description"] == ""  # « — » chez elle, tant qu'il n'a pas de but écrit pour la personne
    assert served.purpose not in got.text
