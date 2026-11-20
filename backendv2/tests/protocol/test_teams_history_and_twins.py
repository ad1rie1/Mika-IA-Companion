"""Teams (ADR 0251) par le vrai serveur : l'historique chargé à la mise en service, et les doublons.

L'historique se range déjà lu : elle ne le remarque pas comme du neuf, rien n'en est journalisé, il ne règle aucun
brouillon. Un même message reçu sous un autre identifiant (sa version en attente dans Teams puis celle du service,
une empreinte de l'extension) n'est rangé qu'une fois ; deux messages du service au même texte restent deux.
"""

from __future__ import annotations

import time

from mika.adapters.teams.store import maybe_same_message
from mika.plugins.teams import RECEIVED
from tests.protocol.test_teams_web import DM, batch, headers, new_key
from tests.protocol.test_web import world  # noqa: F401 — fixture


def message(mid: str, text: str, *, ago_ms: int = 0, author: str = "8:orgid:a", own: bool = False) -> dict:
    return {"id": mid, "conv": DM, "author": "Alice", "author_id": author, "time": int(time.time() * 1000) - ago_ms,
            "text": text, "own": own, "mentions_me": False}


def push(client, key, *messages, history: bool = False) -> dict:
    got = client.post("/api/teams/inbox", headers=headers(key), json={
        "self": {"id": "8:orgid:adrien", "name": "Adrien"}, "conversations": [{"id": DM, "kind": "dm"}],
        "messages": list(messages), **({"history": True} if history else {})})
    assert got.status_code == 202, got.text
    return got.json()


def received(client, live) -> list:
    store = live.kernel.mind.store
    return client.portal.call(lambda: [e for e in store.read() if e.type == RECEIVED.name])


def test_history_is_stored_already_read_and_never_noticed(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    year = 365 * 86_400_000
    old = [message(str(1_600_000_000_000 + i), f"vieux message {i}", ago_ms=year + i * 60_000) for i in range(3)]
    mine = message("1600000999999", "ma vieille réponse", ago_ms=year, author="8:orgid:adrien", own=True)
    got = push(client, key, *old, mine, history=True)
    assert got["accepted"] == 4 and got["twins"] == 0
    assert len(client.portal.call(store.thread, "principal", DM, 10)) == 4
    assert client.portal.call(store.fetch_new, 10) == [], "l'historique se range déjà lu"
    assert received(client, live) == [], "rien de l'historique n'est journalisé"
    # rejoué (la mise en service relancée) : tout est déjà connu, rien n'est rangé deux fois
    again = push(client, key, *old, mine, history=True)
    assert again["accepted"] == 0 and again["known"] == 4
    # un message neuf, lui, se remarque comme avant
    push(client, key, message("1759000000001", "et maintenant ?"))
    assert [m.text for m in client.portal.call(store.fetch_new, 10)] == ["et maintenant ?"]
    assert len(received(client, live)) == 1


def test_the_same_message_under_another_id_is_stored_once(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    # sa version en attente dans Teams (l'identifiant du client, 19 chiffres), puis celle du service (13 chiffres)
    pending = message("8123456789012345678", "J'arrive dans  5 min", ago_ms=1500)
    final = message("1759000000123", "J'arrive dans 5 min")
    assert push(client, key, pending)["accepted"] == 1
    got = push(client, key, final)
    assert got["accepted"] == 0 and got["twins"] == 1
    assert push(client, key, final)["known"] == 1, "redit sous l'identifiant du service : connu par son alias"
    # une seule ligne, dont le texte suit la version du service
    assert [m.text for m in client.portal.call(store.thread, "principal", DM, 10)] == ["J'arrive dans 5 min"]
    # une empreinte de l'extension (« h… », faute d'identifiant), puis l'identifiant du service
    assert push(client, key, message("h1x2y3z", "Je pars", ago_ms=800))["accepted"] == 1
    assert push(client, key, message("1759000000124", "Je pars"))["twins"] == 1
    # deux identifiants du service au même texte : deux messages (un « ok » redit dans la minute)
    first = push(client, key, message("1759000000200", "ok"), message("1759000000201", "ok"))
    assert first["accepted"] == 2 and first["twins"] == 0
    # un autre auteur, ou bien plus tard, ou un autre texte : pas un jumeau
    other = message("8999999999999999999", "ok", author="8:orgid:b")
    later = message("8999999999999999998", "J'arrive dans 5 min", ago_ms=-10 * 60_000)
    assert push(client, key, other, later)["accepted"] == 2


def test_a_twin_follows_its_edits_and_its_deletion_under_the_other_id(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    push(client, key, message("8123456789012345678", "réunion à 14 h", ago_ms=1000))  # sa version en attente
    assert push(client, key, message("1759000000400", "réunion à 14 h"))["twins"] == 1  # celle du service
    # retouché dans Teams : la retouche arrive sous l'identifiant du service, et retrouve la ligne par son alias
    edited = push(client, key, message("1759000000400", "réunion à 15 h"))
    assert edited["accepted"] == 0 and edited["known"] == 1
    assert [m.text for m in client.portal.call(store.thread, "principal", DM, 10)] == ["réunion à 15 h"]
    # supprimé dans Teams, sous l'identifiant du service : son texte part
    gone = client.post("/api/teams/inbox", headers=headers(key), json={"messages": [
        {**message("1759000000400", ""), "deleted": True}]})
    assert gone.status_code == 202
    assert [m.text for m in client.portal.call(store.thread, "principal", DM, 10)] == [""]


def test_a_line_that_found_its_twin_does_not_swallow_a_second_message(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    # « ok » dans le navigateur : sa version en attente, puis celle du service (jumeaux)
    push(client, key, message("8123456789012345601", "ok", ago_ms=2000))
    assert push(client, key, message("1759000000501", "ok", ago_ms=1500))["twins"] == 1
    # une minute plus tard, « ok » depuis le téléphone : le navigateur ne voit que l'identifiant du service
    second = push(client, key, message("1759000000502", "ok"))
    assert second["accepted"] == 1 and second["twins"] == 0
    # deux empreintes au même texte : deux messages (une source sans identifiant, deux « ok »)
    assert push(client, key, message("haaa", "d'accord", ago_ms=500), message("hbbb", "d'accord"))["accepted"] == 2
    assert len(client.portal.call(store.thread, "principal", DM, 10)) == 4


def test_recent_history_is_stored_as_live_and_noticed(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    old = message("1600000000001", "il y a deux jours", ago_ms=2 * 86_400_000)
    fresh = message("1759000000600", "il y a une heure", ago_ms=3_600_000)
    got = push(client, key, old, fresh, history=True)
    assert got["accepted"] == 2
    # le récent se range comme du direct : elle le remarque, et ce qui est reçu le dit ; le vieux, non
    assert [m.text for m in client.portal.call(store.fetch_new, 10)] == ["il y a une heure"]
    [event] = received(client, live)
    assert live.kernel.mind.decode(event).data.new == 1


def test_an_edit_and_a_deletion_still_follow_the_id(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    store = live.kernel.ports["teams"]
    push(client, key, message("1759000000300", "réunion à 14 h"))
    assert push(client, key, message("1759000000300", "réunion à 15 h"))["known"] == 1
    assert [m.text for m in client.portal.call(store.thread, "principal", DM, 10)] == ["réunion à 15 h"]
    gone = client.post("/api/teams/inbox", headers=headers(key), json={"messages": [
        {**message("1759000000300", ""), "deleted": True}]})
    assert gone.status_code == 202
    assert [m.text for m in client.portal.call(store.thread, "principal", DM, 10)] == [""]
    # un message effacé n'est le jumeau de rien : le même texte, redit, est un message
    assert push(client, key, message("8000000000000000001", "réunion à 15 h"))["accepted"] == 1


def test_two_ids_may_name_one_message_only_when_their_kinds_differ():
    assert maybe_same_message("8123456789012345678", "1759000000123")
    assert maybe_same_message("h1x2y3z", "1759000000123") and maybe_same_message("h1x2y3z", "8123456789012345678")
    assert not maybe_same_message("habc", "hdef"), "deux empreintes sont deux messages"
    assert not maybe_same_message("1:abc", "1759000000123"), "une forme inconnue n'est le jumeau de rien"
    assert not maybe_same_message("1759000000200", "1759000000201")
    assert not maybe_same_message("8123456789012345678", "8123456789012345679")
    assert not maybe_same_message("1759000000123", "1759000000123")


def test_the_live_batch_is_unchanged_for_the_simple_case(world):  # noqa: F811
    client, live, _ = world
    key = new_key(client, live)
    got = client.post("/api/teams/inbox", json=batch(3), headers=headers(key)).json()
    assert got["accepted"] == 3 and got["twins"] == 0
