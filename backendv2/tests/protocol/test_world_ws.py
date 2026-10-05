"""``/ws/world`` tel qu'un moteur de jeu le parle (ADR 0050, 0051), sur l'application réelle.

- se connecter : ``welcome`` (rôles accordés, acteur, monde, révision, ``seq``), puis la définition si le client
  n'a pas la bonne révision, l'instantané ou le rattrapage, et le bail d'hôte demandé ;
- un client natif s'authentifie par un jeton de son compte, **sans** ``Origin`` (avec : refusé) ; révoqué, ses
  connexions se ferment ; ``/ws`` accepte le même jeton, aux mêmes conditions ;
- ce que Mika fait part à tous, avec son ``seq`` ; l'hôte termine une action, le noyau la conclut : l'accusé
  d'abord, puis la trame qui l'applique ; une commande répétée est reconnue, une commande en trop est bornée ;
- un seul hôte ; un hôte qui se tait perd le bail et le suivant l'obtient ; un compte qui n'est pas opérateur
  ne l'obtient pas ;
- la pose d'un corps va aux autres, jamais à soi ; une trame illisible est dite, une trame qui n'est pas du
  JSON ferme la connexion.

Chaque trame reçue est relue par le schéma publié du protocole. L'horloge du bail et des débits est celle du
test (``live.world.monotonic``) : rien n'attend pour de vrai.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.adapters.world import protocol as p
from mika.app.server import build
from mika.contracts import world as w
from mika.faculties.world import plan, timing
from mika.kernel.events import Origin

ORIGIN = "http://localhost:3000"
WORLD = "ws://localhost:8001/ws/world"
CHAT = "ws://localhost:8001/ws"
PASSWORD = "un-mot-de-passe-long"


@dataclass
class Ctx:
    client: TestClient
    live: Any
    clock: list[float]

    def call(self, fn, *args, **kw):
        return self.client.portal.call(functools.partial(fn, *args, **kw))

    def tick(self, seconds: float = 1.1) -> None:
        self.clock[0] += seconds

    def operator(self) -> int:
        """Le premier compte (opérateur), par l'amorçage du site : son cookie de session reste au client."""
        self.client.get("/auth/whoami")
        r = self.client.post("/auth/bootstrap", json={"username": "adrien", "password": PASSWORD},
                             headers={"X-CSRFToken": self.client.cookies.get("csrftoken")})
        assert r.status_code == 200, r.text
        return 1

    def account(self, name: str, *, operator: bool = False) -> int:
        return self.call(self.live.accounts.create, name, PASSWORD, operator=operator).id

    def token(self, account: int, label: str = "essai") -> tuple[int, str]:
        info, raw = self.call(self.live.accounts.create_token, account, label)
        return info.id, raw

    def going(self, ident: str = "i-test", place: str = "window") -> tuple[w.Intent, int]:
        return self.call(_going, self.live.kernel, ident, place)


async def _going(kernel, ident: str, place: str) -> tuple[w.Intent, int]:
    """Mika part quelque part (lentement : l'échéance ne tombe pas pendant l'essai)."""
    frame = kernel.mind.frame()
    s = frame.state("world")
    t = replace(timing(None), walk_speed=0.05)
    steps = plan.plan_go(s.definition, t, s.actors, w.MIKA, place)
    intent = plan.intent_of(w.MIKA, steps, frame.now, t, w.Cause(source=w.Source.MIKA, actor=w.MIKA), ident)
    commit = await kernel.mind.append([w.INTENDED.draft(intent=intent)], emitter="world", correlation="test:geste",
                                      origin=Origin.EXTERNAL)
    return intent, commit.seqs[-1]


@pytest.fixture
def ctx(tmp_path) -> Iterator[Ctx]:
    app, live = build(tmp_path / "data", web=WebConfig(), embedder=HashEmbedder())
    # pas d'Origin par défaut : un client natif n'en a pas ; un « navigateur » la pose lui-même
    with TestClient(app, base_url="http://localhost:8001") as client:
        clock = [1000.0]
        live.world.monotonic = lambda: clock[0]
        yield Ctx(client, live, clock)


def hello(ws, *, roles=("viewer",), rev=None, after=None, token=None) -> None:
    frame: dict[str, Any] = {"type": "hello", "protocol": "mika.world/1", "roles": list(roles),
                             "client": {"name": "essai", "version": "0.1", "engine": "pytest"}}
    for key, value in (("rev", rev), ("after", after), ("token", token)):
        if value is not None:
            frame[key] = value
    ws.send_json(frame)


def recv(ws) -> dict:
    """La trame suivante, hors ``presence`` : les personnes entrent et sortent avec leurs connexions, ce dont ces
    essais ne parlent pas."""
    while True:
        frame = ws.receive_json()
        p.server_frame(json.dumps(frame))  # chaque trame reçue respecte le protocole publié
        if frame["type"] != "presence":
            return frame


def until(ws, kind: str, limit: int = 30, **match: Any) -> tuple[dict, list[dict]]:
    """La prochaine trame de ce type (et qui porte ces valeurs), et celles reçues avant elle."""
    seen = []
    for _ in range(limit):
        frame = recv(ws)
        if frame["type"] == kind and all(frame.get(k) == v for k, v in match.items()):
            return frame, seen
        seen.append(frame)
    raise AssertionError(f"pas de trame {kind} {match} : {[f['type'] for f in seen]}")


def opened(ws) -> dict:
    """L'accueil d'un client neuf : welcome, definition, snapshot (et rien d'autre entre eux)."""
    welcome = recv(ws)
    assert welcome["type"] == "welcome"
    assert recv(ws)["type"] == "definition"
    assert recv(ws)["type"] == "snapshot"
    return welcome


#: ce que sa propre vie peut faire passer pendant un essai (l'horloge est réelle : la nuit, elle va se coucher)
BACKGROUND = frozenset({"intent", "intent_end"})


def ping(ctx: Ctx, ws, t: int) -> list[dict]:
    """Un ``ping`` comme barrière : ce qui arrive avant son ``pong`` (hors sa propre vie)."""
    ctx.tick()
    ws.send_json({"type": "ping", "t": t})
    return [f for f in until(ws, "pong", t=t)[1] if f["type"] not in BACKGROUND]


# ── Se connecter ──────────────────────────────────────────────────────────


def test_hello_welcome_definition_snapshot_puis_le_bail(ctx) -> None:
    _, token = ctx.token(ctx.operator(), "Unity")
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, roles=("viewer", "host"), token=token)
        welcome = recv(ws)
        assert welcome["protocol"] == "mika.world/1" and welcome["granted"] == ["viewer", "host"]
        assert welcome["actor"] == "player:user_1" and welcome["world"] == "chambre"
        assert welcome["session"] and welcome["now"] > 1_700_000_000_000_000  # des microsecondes
        definition = recv(ws)
        assert definition["type"] == "definition" and definition["world"]["rev"] == welcome["rev"]
        snapshot = recv(ws)
        assert snapshot["type"] == "snapshot" and snapshot["state"]["seq"] == welcome["seq"]
        assert any(a["id"] == "mika" for a in snapshot["state"]["actors"])
        assert recv(ws) == {"type": "host", "granted": True, "ttl_ms": 15000}
        assert ping(ctx, ws, 1) == []


def test_un_client_a_jour_ne_recoit_ni_definition_ni_instantane(ctx) -> None:
    _, token = ctx.token(ctx.operator())
    definition, state = ctx.call(ctx.live.port.world_view)
    rev, seq = definition.rev, state.seq
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, rev=rev, after=seq, token=token)
        assert recv(ws)["type"] == "welcome"
        assert ping(ctx, ws, 7) == []


def test_ce_que_fait_mika_part_a_tous_avec_son_seq_et_se_rattrape(ctx) -> None:
    _, token = ctx.token(ctx.operator())
    with ctx.client.websocket_connect(WORLD) as first:
        hello(first, token=token)
        welcome = opened(first)
        intent, seq = ctx.going()
        frame, _ = until(first, "intent", seq=seq)
        assert seq > welcome["seq"] and frame["intent"]["id"] == intent.id
        assert frame["intent"]["steps"] and frame["intent"]["deadline"] > frame["intent"]["eta"]
    # un client qui revient avec ce qu'il avait reçoit ce qu'il a manqué, et seulement ça
    with ctx.client.websocket_connect(WORLD) as again:
        hello(again, rev=welcome["rev"], after=welcome["seq"], token=token)
        assert recv(again)["seq"] >= seq  # welcome : le monde en est là
        caught = recv(again)
        assert (caught["type"], caught["seq"], caught["intent"]["id"]) == ("intent", seq, intent.id)
        assert ping(ctx, again, 2) == []
        # ``sync`` redemande la même chose ; un ``after`` que ce journal ne connaît pas vaut un instantané
        again.send_json({"type": "sync", "after": welcome["seq"]})
        assert until(again, "intent", seq=seq)[0]["intent"]["id"] == intent.id
        ctx.tick()
        again.send_json({"type": "sync", "after": seq + 10_000})
        assert until(again, "snapshot")[0]["state"]["seq"] >= seq


# ── Commandes ─────────────────────────────────────────────────────────────


def test_l_hote_termine_une_action_l_accuse_puis_la_fin(ctx) -> None:
    _, token = ctx.token(ctx.operator())
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, roles=("viewer", "host"), token=token)
        opened(ws)
        until(ws, "host")
        intent, _ = ctx.going()
        until(ws, "intent")
        ws.send_json({"type": "report", "cmd": "r-1", "report": {"kind": "progress", "intent": intent.id, "step": 0}})
        assert until(ws, "result")[0] == {"type": "result", "cmd": "r-1", "status": "accepted", "code": None,
                                          "message": "", "seq": None}
        done = {"type": "report", "cmd": "r-2", "report": {"kind": "finished", "intent": intent.id,
                                                          "outcome": "done"}}
        ws.send_json(done)
        result, before = until(ws, "result", cmd="r-2")
        assert not [f for f in before if f["type"] == "intent_end"]  # l'accusé d'abord
        assert result["status"] == "accepted" and result["seq"]
        end, _ = until(ws, "intent_end", intent=intent.id)
        assert (end["seq"], end["outcome"]) == (result["seq"], "done")
        moved = [c for c in end["changes"] if c["kind"] == "actor_moved" and c["actor"] == "mika"]
        assert moved and moved[-1]["place"] == "window"
        # la même commande, renvoyée : reconnue, même accusé
        ws.send_json(done)
        again, _ = until(ws, "result", cmd="r-2")
        assert (again["status"], again["seq"]) == ("duplicate", result["seq"])
        # une action qui n'est plus en cours : refusée par le noyau, rien d'écrit
        ws.send_json({**done, "cmd": "r-3"})
        refused, _ = until(ws, "result", cmd="r-3")
        assert (refused["status"], refused["code"]) == ("refused", "unknown") and refused["message"]
        # ce qui manque au moteur est gardé pour la console
        ws.send_json({"type": "report", "cmd": "r-4", "report": {"kind": "loaded", "rev": 0,
                                                                "missing_assets": ["props/guitar"]}})
        assert until(ws, "result", cmd="r-4")[0]["status"] == "accepted"
        loaded = ctx.call(ctx.live.world.overview)["loaded"]
        assert loaded[0]["missing_assets"] == ["props/guitar"] and loaded[0]["client"].startswith("essai")


def test_ce_que_le_noyau_ne_sait_pas_faire_est_dit_et_les_debits_bornes(ctx) -> None:
    _, token = ctx.token(ctx.operator())
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, token=token)
        opened(ws)
        for i in range(5):  # « act » : quatre par seconde
            ws.send_json({"type": "act", "cmd": f"a-{i}", "action": "ouvrir", "object": "window_pane"})
        results = {}
        while len(results) < 5:
            frame, _ = until(ws, "result")
            results[frame["cmd"]] = frame
        assert {results[f"a-{i}"]["code"] for i in range(4)} == {"unsupported"}  # P4 : dit tel quel
        assert results["a-4"]["status"] == "refused" and results["a-4"]["code"] == "rate_limited"
        # un rôle manquant : constater est à l'hôte, éditer au créateur
        ctx.tick()
        ws.send_json({"type": "report", "cmd": "r-1", "report": {"kind": "loaded", "rev": 0}})
        assert until(ws, "result", cmd="r-1")[0]["code"] == "not_host"
        ws.send_json({"type": "describe", "cmd": "e-1", "of": "object", "id": "desk", "text": "son bureau"})
        assert until(ws, "result", cmd="e-1")[0]["code"] == "not_creator"


def test_une_trame_illisible_est_dite_une_trame_qui_n_est_pas_du_json_ferme(ctx) -> None:
    _, token = ctx.token(ctx.operator())
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, token=token)
        opened(ws)
        ws.send_json({"type": "act", "cmd": "a-1", "action": "ouvrir", "foo": 1})
        assert recv(ws) == {"type": "error", "code": "bad_frame", "fatal": False,
                            "message": "trame illisible (a-1) : champ inconnu « foo »"}
        ws.send_json({"type": "hello", "protocol": "mika.world/1", "roles": ["viewer"],
                      "client": {"name": "x", "version": "0", "engine": "x"}})
        assert recv(ws)["code"] == "bad_frame"
        ws.send_text("pas du json")
        fatal = recv(ws)
        assert (fatal["type"], fatal["code"], fatal["fatal"]) == ("error", "bad_frame", True)
        with pytest.raises(WebSocketDisconnect) as closed:
            recv(ws)
        assert closed.value.code == 1003


# ── Le bail d'hôte ────────────────────────────────────────────────────────


def test_un_seul_hote_et_le_bail_passe_au_silence(ctx) -> None:
    owner = ctx.operator()
    _, first_token = ctx.token(owner, "Unity")
    _, second_token = ctx.token(owner, "Unity, l'autre PC")
    with ctx.client.websocket_connect(WORLD) as a, ctx.client.websocket_connect(WORLD) as b:
        hello(a, roles=("viewer", "host"), token=first_token)
        first = recv(a)
        assert first["granted"] == ["viewer", "host"]
        until(a, "host", granted=True)
        hello(b, roles=("viewer", "host"), token=second_token)
        assert recv(b)["granted"] == ["viewer"]  # le bail est pris
        assert until(b, "host")[0] == {"type": "host", "granted": False, "ttl_ms": 0}
        # l'hôte renouvelle son bail en parlant…
        ctx.tick(10)
        assert ping(ctx, a, 1) == []
        ctx.tick(10)  # 21 s depuis l'accueil, 11 s depuis son ping : il le tient toujours
        assert ping(ctx, b, 2) == []
        assert ctx.call(lambda: ctx.live.world.host) == first["session"]
        # … puis se tait : le bail passe au suivant qui l'attend
        ctx.tick(16)
        assert ping(ctx, b, 3) == [{"type": "host", "granted": True, "ttl_ms": 15000}]
        assert until(a, "host")[0] == {"type": "host", "granted": False, "ttl_ms": 0}
        a.send_json({"type": "report", "cmd": "r-1", "report": {"kind": "loaded", "rev": 0}})
        assert until(a, "result", cmd="r-1")[0]["code"] == "not_host"
        b.send_json({"type": "report", "cmd": "r-1", "report": {"kind": "loaded", "rev": 0}})
        assert until(b, "result", cmd="r-1")[0]["status"] == "accepted"


def test_un_compte_qui_n_est_pas_operateur_n_obtient_pas_le_bail(ctx) -> None:
    ctx.operator()
    _, token = ctx.token(ctx.account("bea"))
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, roles=("viewer", "host", "creator"), token=token)
        welcome = recv(ws)
        assert welcome["granted"] == ["viewer"] and welcome["actor"] == "player:user_2"
        assert until(ws, "host")[0] == {"type": "host", "granted": False, "ttl_ms": 0}
        assert ctx.call(lambda: ctx.live.world.host) is None


# ── Authentification ──────────────────────────────────────────────────────


def test_le_jeton_d_un_client_natif_sans_origin_seulement(ctx) -> None:
    _, token = ctx.token(ctx.operator())
    for headers, frame_token in (({}, None), ({"origin": ORIGIN}, token), ({}, "mw_faux")):
        with ctx.client.websocket_connect(WORLD, headers=headers) as ws:
            hello(ws, token=frame_token)
            refused = recv(ws)
            assert (refused["type"], refused["code"], refused["fatal"]) == ("error", "unauthorized", True)
            with pytest.raises(WebSocketDisconnect) as closed:
                recv(ws)
            assert closed.value.code == 4401
    # l'en-tête Authorization vaut hello.token
    with ctx.client.websocket_connect(WORLD, headers={"authorization": f"Bearer {token}"}) as ws:
        hello(ws)
        assert recv(ws)["actor"] == "player:user_1"
    # un navigateur : sa session (le cookie de l'amorçage) et une origine connue
    with ctx.client.websocket_connect(WORLD, headers={"origin": ORIGIN}) as ws:
        hello(ws)
        assert recv(ws)["actor"] == "player:user_1"
    with pytest.raises(WebSocketDisconnect) as foreign, \
            ctx.client.websocket_connect(WORLD, headers={"origin": "https://evil.test"}):
        pass
    assert foreign.value.code == 1008


def test_un_jeton_revoque_ferme_ses_connexions(ctx) -> None:
    token_id, token = ctx.token(ctx.operator())
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, token=token)
        opened(ws)
        assert ctx.call(ctx.live.accounts.revoke_token, token_id) is True
        closing = recv(ws)
        assert (closing["code"], closing["fatal"]) == ("unauthorized", True)
        with pytest.raises(WebSocketDisconnect) as closed:
            recv(ws)
        assert closed.value.code == 4401
    assert ctx.call(ctx.live.accounts.revoke_token, token_id) is False  # déjà révoqué
    with ctx.client.websocket_connect(WORLD) as ws:
        hello(ws, token=token)
        assert recv(ws)["code"] == "unauthorized"
    assert [t.revoked for t in ctx.call(ctx.live.accounts.tokens)] == [True]


def test_ws_accepte_le_jeton_sans_origin(ctx) -> None:
    token_id, token = ctx.token(ctx.operator())
    ctx.client.cookies.clear()  # plus de session : seul le jeton peut ouvrir
    bearer = {"authorization": f"Bearer {token}"}
    with ctx.client.websocket_connect(CHAT, headers=bearer) as ws:
        first = ws.receive_json()
        assert first["type"] == "history" and first["mode"] == "initial"
    # avec une Origin, c'est la session qui compte (un navigateur ne pose pas cet en-tête)
    with ctx.client.websocket_connect(CHAT, headers={**bearer, "origin": ORIGIN}) as ws, \
            pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == 4401
    ctx.call(ctx.live.accounts.revoke_token, token_id)
    with ctx.client.websocket_connect(CHAT, headers=bearer) as ws, pytest.raises(WebSocketDisconnect) as revoked:
        ws.receive_json()
    assert revoked.value.code == 4401


# ── Les corps ─────────────────────────────────────────────────────────────


def test_la_pose_va_aux_autres_jamais_a_soi_ni_au_journal(ctx) -> None:
    _, mine = ctx.token(ctx.operator())
    _, hers = ctx.token(ctx.account("bea"))
    head = ctx.call(lambda: ctx.live.kernel.mind.head)
    with ctx.client.websocket_connect(WORLD) as a, ctx.client.websocket_connect(WORLD) as b:
        hello(a, token=mine)
        opened(a)
        hello(b, token=hers)
        opened(b)
        pose = {"type": "pose", "t": 1790000141000000, "pos": {"x": 1.2, "y": 0.0, "z": 2.1}, "yaw": 3.0,
                "anim": "walk"}
        a.send_json(pose)
        assert recv(b) == {**pose, "actor": "player:user_1"}
        assert ping(ctx, a, 9) == []  # rien n'est revenu à qui l'a envoyée
    store = ctx.live.kernel.mind.store
    entering = {w.JOINED.name, w.LEFT.name, w.NOTICED.name}  # entrer, sortir, le remarquer : la connexion
    assert ctx.call(lambda: [e.type for e in store.read(after=head)
                             if e.type.startswith("world.") and e.type not in entering]) == []
    # jamais journalisée
