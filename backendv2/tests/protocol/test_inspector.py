"""L'inspecteur : réservé aux opérateurs, lisible, et ses formulaires protégés."""

from __future__ import annotations

from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée


def test_the_inspector_is_for_operators_only(world):  # noqa: F811
    client, live, _ = world
    r = client.get("/inspecteur/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/inspecteur/connexion")
    assert client.get("/inspecteur/connexion").status_code == 200


def test_an_operator_follows_a_reply_from_message_to_episode(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)  # le premier compte est opérateur
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "raconte-moi ta journée", "client_msg_id": "i1"})
        recv_until(ws, "speech")
    home = client.get("/inspecteur/")
    assert home.status_code == 200 and "Journal" in home.text and "REPLY" in home.text
    timeline = client.get("/inspecteur/chronologie?type=episode.")
    assert "episode.utterance" in timeline.text
    ended = client.portal.call(lambda: list(live.kernel.mind.store.read(types={"episode.ended"})))
    chain = client.get(f"/inspecteur/episode/{ended[-1].correlation}")
    assert "episode.started" in chain.text and "episode.utterance" in chain.text
    assert client.get("/inspecteur/decisions").status_code == 200
    state = client.get("/inspecteur/etat")
    assert "affect" in state.text and "identity" in state.text


def test_model_settings_form_needs_its_token_and_never_shows_a_key(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get("/inspecteur/modeles")
    refused = client.post("/inspecteur/modeles", data={"action": "backend", "name": "claude", "kind": "claude",
                                                       "model": "claude-sonnet-5", "api_key": "sk-secret-123"})
    assert "Jeton de formulaire invalide" in refused.text
    token = client.cookies.get("csrftoken")
    saved = client.post("/inspecteur/modeles", data={"csrf": token, "action": "backend", "name": "claude",
                                                     "kind": "claude", "model": "claude-sonnet-5",
                                                     "api_key": "sk-secret-123"})
    assert saved.status_code == 200 and "sk-secret-123" not in saved.text and "••••" in saved.text
    routed = client.post("/inspecteur/modeles", data={"csrf": token, "action": "routes", "route_reply": "claude",
                                                      "context": "32000"})
    assert routed.status_code == 200
    cfg = client.portal.call(live.settings.llm)  # lu dans la boucle de l'application
    assert cfg.routes == {"reply": "claude"} and cfg.context_tokens == 32000
    assert cfg.backends["claude"].api_key == "sk-secret-123"  # déchiffrée à la lecture, jamais affichée
    raw = client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings")
    assert "sk-secret-123" not in raw[0][0]  # chiffrée au repos
