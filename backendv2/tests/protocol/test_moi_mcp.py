"""L'API par personne, ses services MCP (ADR 0192) : un service qu'elle branche est à elle, distant (une adresse
https), avec une seule ligne d'accès, la sienne ; personne d'autre ne le voit ni ne le règle ; elle le retire. Un
service qu'on lui partage se lit chez elle (ADR 0188), sans son adresse ni ses en-têtes ; sa ligne se reconnaît à ce
que l'API en dit (``mine``), jamais à un nom."""

from __future__ import annotations

from dataclasses import replace

from mika.app.moi import mcp as mcp_moi
from mika.ports.mcp import LiveTool, ToolReview
from tests.protocol.test_moi_mail import API, login, post, second_person
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

SERVICE = {"name": "factures", "purpose": "Ses factures et ses devis, pour les retrouver.",
           "url": "https://mcp.factures.example.test/mcp", "headers": "Authorization: Bearer abc"}


def servers(client, live) -> dict:
    return client.portal.call(live.settings.mcp).servers


def test_a_service_she_plugs_is_hers_with_one_access_line(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    login(client, "lea")
    assert client.get(API + "/mcp/services").json() == {"plugged": True, "items": [], "received": []}
    assert post(client, "/mcp/plug", {**SERVICE, "url": "http://192.168.1.1/mcp"}).status_code == 400  # https
    assert post(client, "/mcp/plug", {**SERVICE, "name": "Factures !"}).status_code == 400
    made = post(client, "/mcp/plug", SERVICE)
    assert made.status_code == 200, made.text
    stored = servers(client, live)["factures"]
    assert stored.owner == "personne:" + lea and stored.transport == "distant"
    assert [list(a.who) for a in stored.access] == [["personne:" + lea]]
    assert (stored.access[0].read, stored.access[0].act, stored.access[0].keep) == ("seule", "carte", "prive")
    assert (stored.default_read, stored.default_act) == ("non", "non")  # la ligne par défaut reste fermée
    listed = client.get(API + "/mcp/services").json()["items"]
    assert [s["name"] for s in listed] == ["factures"] and listed[0]["headers"] and "abc" not in str(listed)
    assert listed[0]["access"][0]["read"] == "seule" and listed[0]["default"]["read"] == "non"
    assert listed[0]["access"][0]["mine"] is True  # sa ligne : la sienne, dite par l'API
    assert post(client, "/mcp/plug", SERVICE).status_code == 400  # un nom déjà pris

    saved = post(client, "/mcp/save", {"name": "factures", "values": {"when_to_use": "quand on parle d'argent",
                                                                    "secret_headers": ""}})
    assert saved.status_code == 200, saved.text
    again = servers(client, live)["factures"]
    assert again.when_to_use == "quand on parle d'argent" and again.secret_headers == "Authorization: Bearer abc"
    assert post(client, "/mcp/save", {"name": "factures", "values": {"owner": ""}}).status_code == 400
    # un réglage refusé se dit en mots : le champ et ce qu'il veut, jamais l'adresse de la documentation de pydantic
    wrong = post(client, "/mcp/save", {"name": "factures", "values": {"enabled": "peut-être"}})
    assert wrong.status_code == 400 and "enabled" in wrong.json()["error"] and "pydantic" not in wrong.text

    login(client, "adrien")  # le service de Léa n'existe pas pour toi ici (la console, elle, les voit tous)
    assert client.get(API + "/mcp/services").json()["items"] == []
    for path in ("/mcp/test", "/mcp/remove", "/mcp/save"):
        assert post(client, path, {"name": "factures", "values": {}}).status_code == 404, path
    login(client, "lea")
    assert post(client, "/mcp/remove", {"name": "factures"}).status_code == 200
    assert "factures" not in servers(client, live)


def test_a_person_plugs_a_bounded_number_of_services(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(mcp_moi, "OWN_MAX", 1)
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    assert post(client, "/mcp/plug", SERVICE).status_code == 200
    assert post(client, "/mcp/plug", {**SERVICE, "name": "agenda"}).status_code == 409
    login(client, "adrien")  # une opératrice, comme dans la console
    assert post(client, "/mcp/plug", {**SERVICE, "name": "meteo"}).status_code == 200
    assert post(client, "/mcp/plug", {**SERVICE, "name": "agenda"}).status_code == 200


def test_a_service_shared_with_her_shows_in_her_list_without_its_address(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    assert post(client, "/mcp/plug", SERVICE).status_code == 200  # le service d'Adrien
    assert post(client, "/shares/set", {"kind": "mcp", "key": "factures", "person": lea, "level": "servir"}
                ).status_code == 200
    login(client, "lea")
    got = client.get(API + "/mcp/services")
    body = got.json()
    assert body["items"] == []  # pas le sien : rien à régler
    [shared] = body["received"]
    assert shared["name"] == "factures" and shared["purpose"] == SERVICE["purpose"]
    assert shared["level"] == "servir" and shared["owner_name"] and "state" in shared
    assert shared["line"]["mine"] is True and shared["line"]["act"] == "carte"  # sa ligne : elle lui demande
    assert shared["tools"] == []  # aucun outil choisi par son propriétaire : aucun servi
    # ni son adresse, ni ses en-têtes, ni le détail d'une panne (il peut nommer l'adresse)
    assert {"url", "headers", "detail"}.isdisjoint(shared)
    assert "factures.example.test" not in got.text and "abc" not in got.text
    for path in ("/mcp/save", "/mcp/remove", "/mcp/tools"):  # le partage ne le lui donne pas à régler
        assert post(client, path, {"name": "factures", "values": {}, "choices": {}}).status_code == 404, path
    login(client, "adrien")
    assert client.get(API + "/mcp/services").json()["received"] == []  # le sien n'est pas « partagé avec toi »
    assert post(client, "/shares/set", {"kind": "mcp", "key": "factures", "person": lea, "level": ""}
                ).status_code == 200
    login(client, "lea")
    assert client.get(API + "/mcp/services").json()["received"] == []  # partage retiré : il s'en va


def test_her_access_line_is_told_by_the_api_not_by_a_name(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    assert post(client, "/mcp/plug", SERVICE).status_code == 200
    assert post(client, "/shares/set", {"kind": "mcp", "key": "factures", "person": lea, "level": "lire"}
                ).status_code == 200
    [mine, shared] = client.get(API + "/mcp/services").json()["items"][0]["access"]
    assert (mine["mine"], shared["mine"]) == (True, False)
    # il prend le nom même sous lequel la ligne de Léa se dit : les deux lignes portent alors ce nom, et seule
    # l'API les distingue — la sienne reste la sienne, celle de Léa reste un partage
    assert post(client, "/account/name", {"name": shared["who"]}).status_code == 200
    assert client.get(API).json()["name"] == shared["who"]
    again = client.get(API + "/mcp/services").json()["items"][0]["access"]
    assert [(a["who"], a["mine"]) for a in again] == [(shared["who"], True), (shared["who"], False)]


def test_a_shared_service_only_shows_the_tools_its_owner_serves(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    assert post(client, "/mcp/plug", SERVICE).status_code == 200
    assert post(client, "/shares/set", {"kind": "mcp", "key": "factures", "person": lea, "level": "lire"}
                ).status_code == 200
    port = live.kernel.ports["mcp"]
    real = port.status

    def tool(remote: str, fingerprint: str) -> LiveTool:
        return LiveTool(remote, remote, f"{remote} (serveur)", {}, {}, fingerprint)

    def status(name: str):  # le service répond : un outil servi, un changé (suspendu), un coupé, un retiré
        st = real(name)
        if name != "factures" or st is None:
            return st
        return replace(st, state="connecte", live=(tool("lister", "a"), tool("payer", "b2"), tool("compter", "c")),
                       reviews={"lister": ToolReview("lister", "a", enabled=True, nature="lecture",
                                                     description="Liste ses factures.", name="mcp_factures_lister"),
                                "payer": ToolReview("payer", "b", enabled=True, nature="action"),
                                "compter": ToolReview("compter", "c", enabled=False),
                                "ancien": ToolReview("ancien", "z", enabled=True)})

    monkeypatch.setattr(port, "status", status)
    login(client, "lea")
    [shared] = client.get(API + "/mcp/services").json()["received"]
    assert shared["state"] == "connecte" and shared["level"] == "lire"
    assert shared["tools"] == [{"remote": "lister", "name": "mcp_factures_lister", "description": "Liste ses factures.",
                                "choice": "lecture"}]
