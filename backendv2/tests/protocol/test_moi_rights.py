"""L'API par personne, Outils (ADR 0187) : la matrice de ses droits, case par case — la décision même de la porte
d'offre pour elle, par chaque canal et à chaque moment. Une propriétaire a ses outils réservés en privé, jamais dans
un salon ; une autre personne ne les a pas, sauf ce qu'une boîte à son nom lui ouvre (ADR 0185) ; ses comptes disent
leur règle d'envoi ; rien n'y montre les lignes d'une famille."""

from __future__ import annotations

from mika.app.moi.rights import CANALS, MOMENTS, WORK
from mika.vocab.access import OWNER
from mika.vocab.canals import CanalRule, CanalTable
from tests.fixtures.courrier import mailbox
from tests.protocol.test_moi_mail import API, login, owners, second_person
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def resources(got: dict, group: str) -> dict:
    return {r["key"]: r for g in got["groups"] if g["key"] == group for r in g["resources"]}


def tool(got: dict, family: str, name: str) -> dict:
    return next(t for t in resources(got, "families")[family]["tools"] if t["name"] == name)


def test_the_matrix_says_each_canal_and_moment(world):  # noqa: F811
    client, _, _ = world
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
    assert web["level"] == "seule" and web["why"] and not web["owned"]
    assert all("lines" not in r for r in resources(got, "families").values())  # jamais les lignes d'une famille


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
