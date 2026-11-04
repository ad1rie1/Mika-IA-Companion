"""L'API par personne, ses services MCP (ADR 0192) : un service qu'elle branche est à elle, distant (une adresse
https), avec une seule ligne d'accès, la sienne ; personne d'autre ne le voit ni ne le règle ; elle le retire."""

from __future__ import annotations

from mika.app.moi import mcp as mcp_moi
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
    assert client.get(API + "/mcp/services").json() == {"plugged": True, "items": []}
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
    assert post(client, "/mcp/plug", SERVICE).status_code == 400  # un nom déjà pris

    saved = post(client, "/mcp/save", {"name": "factures", "values": {"when_to_use": "quand on parle d'argent",
                                                                    "secret_headers": ""}})
    assert saved.status_code == 200, saved.text
    again = servers(client, live)["factures"]
    assert again.when_to_use == "quand on parle d'argent" and again.secret_headers == "Authorization: Bearer abc"
    assert post(client, "/mcp/save", {"name": "factures", "values": {"owner": ""}}).status_code == 400

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
