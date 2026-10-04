"""L'application du téléphone se connecte par identifiant et mot de passe (ADR 0062), sur l'application réelle.

- ``POST /auth/token`` rend un jeton de client natif **sans** ``Origin`` ; un navigateur (une ``Origin``) est
  renvoyé à sa session, sans compter d'échec ; les essais ratés comptent avec ceux de ``/auth/login`` ;
- le jeton ouvre ``/ws`` ; ``/auth/whoami`` le reconnaît (mais pas à côté d'une ``Origin``) ;
- ``DELETE /auth/token`` le rend : sa connexion se ferme en 4401, il ne vaut plus rien ;
- au-delà de dix jetons obtenus par mot de passe, le moins récemment utilisé part ;
- changer le mot de passe, ou désactiver le compte, révoque les jetons obtenus par mot de passe, pas ceux qu'un
  opérateur a donnés (un moteur de jeu configuré à la main) ;
- un téléphone connecté la laisse écrire à la personne absente ; rendu, plus.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.server import build, register_accounts
from mika.contracts import identity as identity_c

ORIGIN = "http://localhost:3000"
CHAT = "ws://localhost:8001/ws"
PASSWORD = "un-mot-de-passe-long"


@dataclass
class Ctx:
    client: TestClient
    live: Any

    def call(self, fn, *args, **kw):
        return self.client.portal.call(functools.partial(fn, *args, **kw))

    def account(self, name: str = "bea", *, operator: bool = False) -> int:
        return self.call(self.live.accounts.create, name, PASSWORD, operator=operator).id

    def login(self, name: str = "bea", *, password: str = PASSWORD, client: str = "mobile", label: str = "Pixel",
              headers: dict[str, str] | None = None):
        return self.client.post("/auth/token", json={"username": name, "password": password, "client": client,
                                                     "label": label}, headers=headers or {})


@pytest.fixture
def ctx(tmp_path) -> Iterator[Ctx]:
    app, live = build(tmp_path / "data", web=WebConfig(), embedder=HashEmbedder())
    with TestClient(app, base_url="http://localhost:8001") as client:
        yield Ctx(client, live)


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def test_un_jeton_contre_un_mot_de_passe(ctx) -> None:
    account = ctx.account()
    r = ctx.login()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"].startswith("mw_")
    assert body["client"] == "mobile" and body["person_id"] == f"user_{account}" and body["authenticated"]
    assert r.headers["cache-control"] == "no-store"
    assert "set-cookie" not in r.headers  # un client natif n'a pas de cookies : rien n'est planté
    [token] = ctx.call(ctx.live.accounts.tokens, account)
    assert (token.client, token.source, token.label) == ("mobile", "login", "Pixel")
    with ctx.client.websocket_connect(CHAT, headers=bearer(body["token"])) as ws:
        first = ws.receive_json()
        assert first["type"] == "history" and first["mode"] == "initial"


def test_un_navigateur_est_renvoye_a_sa_session(ctx) -> None:
    ctx.account()
    for _ in range(8):  # plus que l'étranglement : un refus pour Origin ne compte pas comme un échec
        r = ctx.login(headers={"origin": ORIGIN})
        assert r.status_code == 403
    assert ctx.login().status_code == 200


def test_les_refus(ctx) -> None:
    ctx.account()
    assert ctx.client.post("/auth/token", json={"username": "bea"}).status_code == 400
    assert ctx.login(client="grille-pain").status_code == 400
    r = ctx.login(password="pas-le-bon-mot")
    assert r.status_code == 401 and r.json()["error"] == "Identifiants invalides."


def test_les_echecs_comptent_avec_ceux_du_site(ctx) -> None:
    ctx.account()
    ctx.client.get("/auth/whoami")
    csrf = {"X-CSRFToken": ctx.client.cookies.get("csrftoken")}
    for _ in range(5):
        r = ctx.client.post("/auth/login", json={"username": "bea", "password": "faux-faux-faux"}, headers=csrf)
        assert r.status_code == 401
    r = ctx.login()
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


def test_whoami_lit_le_jeton_sans_origin(ctx) -> None:
    account = ctx.account()
    token = ctx.login().json()["token"]
    ctx.client.cookies.clear()
    me = ctx.client.get("/auth/whoami", headers=bearer(token)).json()
    assert me["authenticated"] and me["person_id"] == f"user_{account}" and me["client"] == "mobile"
    assert me["token_id"] == ctx.call(ctx.live.accounts.tokens, account)[0].id
    # à côté d'une Origin, un jeton ne vaut rien : c'est une page, seule sa session compte
    page = ctx.client.get("/auth/whoami", headers={**bearer(token), "origin": ORIGIN}).json()
    assert page["authenticated"] is False
    assert ctx.client.get("/auth/whoami", headers=bearer("mw_inconnu")).json()["authenticated"] is False


def test_rendre_son_jeton_ferme_la_connexion(ctx) -> None:
    ctx.account()
    token = ctx.login().json()["token"]
    with ctx.client.websocket_connect(CHAT, headers=bearer(token)) as ws:
        assert ws.receive_json()["type"] == "history"
        r = ctx.client.delete("/auth/token", headers=bearer(token))
        assert r.status_code == 200 and r.json() == {"ok": True}
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
        assert closed.value.code == 4401
    assert ctx.client.delete("/auth/token", headers=bearer(token)).status_code == 401
    with ctx.client.websocket_connect(CHAT, headers=bearer(token)) as ws, \
            pytest.raises(WebSocketDisconnect) as refused:
        ws.receive_json()
    assert refused.value.code == 4401
    # un navigateur ne peut pas rendre le jeton d'un autre en le posant à côté de son Origin
    other = ctx.login().json()["token"]
    assert ctx.client.delete("/auth/token", headers={**bearer(other), "origin": ORIGIN}).status_code == 401


def test_dix_jetons_au_plus_par_mot_de_passe(ctx) -> None:
    account = ctx.account()
    first = ctx.login(label="premier").json()["token_id"]
    for n in range(10):
        assert ctx.login(label=f"n{n}").status_code == 200
    tokens = ctx.call(ctx.live.accounts.tokens, account)
    live = [t for t in tokens if not t.revoked]
    assert len(live) == 10
    assert [t.id for t in tokens if t.revoked] == [first]  # le plus ancien jamais utilisé est parti


def test_changer_le_mot_de_passe_revoque_les_jetons_obtenus_par_mot_de_passe(ctx) -> None:
    account = ctx.account()
    by_login = ctx.login().json()["token"]
    given, _raw = ctx.call(ctx.live.accounts.create_token, account, "moteur")  # donné par un opérateur
    with ctx.client.websocket_connect(CHAT, headers=bearer(by_login)) as ws:
        assert ws.receive_json()["type"] == "history"
        assert ctx.call(ctx.live.accounts.update, account, password="un-autre-mot-de-passe") is None
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
        assert closed.value.code == 4401
    states = {t.source: t.revoked for t in ctx.call(ctx.live.accounts.tokens, account)}
    assert states == {"login": True, "cli": False}
    assert ctx.client.get("/auth/whoami", headers=bearer(by_login)).json()["authenticated"] is False


def test_desactiver_le_compte_revoque_aussi(ctx) -> None:
    ctx.account(operator=False)
    account = ctx.account("chloe")
    ctx.client.post("/auth/token", json={"username": "chloe", "password": PASSWORD, "client": "mobile"})
    assert ctx.call(ctx.live.accounts.update, account, active=False) is None
    assert [t.revoked for t in ctx.call(ctx.live.accounts.tokens, account)] == [True]


def test_le_telephone_rend_joignable_et_le_rendre_retire(ctx) -> None:
    """Un jeton ``mobile`` vivant : elle peut écrire à la personne absente ; rendu, plus. ``register_accounts`` n'écrit
    qu'au changement (idempotent)."""
    account = ctx.account()
    handle = f"user_{account}"

    def state() -> tuple[bool, int]:
        frame = ctx.live.kernel.mind.frame()
        registered = [e for e in ctx.live.kernel.mind.store.read() if e.type == identity_c.REGISTERED.name]
        return bool(frame.get(identity_c.REACHABLE(handle))), len(registered)

    before = ctx.call(lambda: state())
    assert before[0] is False
    token = ctx.login().json()["token"]
    reachable, after_login = ctx.call(lambda: state())
    assert reachable and after_login == before[1] + 1
    assert ctx.call(register_accounts, ctx.live.kernel, ctx.live.accounts) == 0  # rien de neuf : rien d'écrit
    screen = ctx.login(client="screen").json()["token"]  # un écran ne change rien à la joignabilité
    assert ctx.call(lambda: state()) == (True, after_login)
    ctx.client.delete("/auth/token", headers=bearer(token))
    assert ctx.call(lambda: state()) == (False, after_login + 1)
    ctx.client.delete("/auth/token", headers=bearer(screen))
    assert ctx.call(lambda: state()) == (False, after_login + 1)
