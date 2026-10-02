"""L'adaptateur du monde (ADR 0051) : le journal traduit en trames, et le port qui décide à sa place.

- chaque événement que les écrans reçoivent devient sa trame, avec **son** ``seq`` (croissant, pas contigu) ;
  ce qui ne regarde qu'elle (ce qu'elle remarque, la prose) n'en a pas ;
- le coucher part avec l'endormissement : l'``intent`` du réflexe porte le ``seq`` de ``body.fell_asleep`` ;
- ce qui change le monde sans action à rejouer (le réveil, une édition) demande un instantané ; ce qui ne l'a
  pas changé ne demande rien ;
- le port : un refus garde son code, une écriture rend son ``seq``, un progrès est accepté sans rien écrire, un
  monde qui a bougé entre la décision et l'écriture rend ``stale`` ; le rattrapage relit le journal, et dit
  quand il y a trop à relire.
"""

from __future__ import annotations

import json
from dataclasses import replace

from pydantic import ValidationError

from mika.adapters.world import protocol as p
from mika.adapters.world.server import explain, translate
from mika.app.mindport import KernelPort
from mika.contracts import body as body_c
from mika.contracts import world as w
from mika.faculties.world import plan, timing
from mika.kernel.events import Content, Event, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build

AT = 1_790_000_000_000_000


def _event(seq: int, etype, data, at: int = AT) -> Event:
    return Event(seq, f"e{seq}", etype, at, data, None, "test", seq - 1, Origin.EXTERNAL)


def _intent(ident: str = "i-1", *, source=w.Source.MIKA, started: int = AT) -> w.Intent:
    return w.Intent(id=ident, actor=w.MIKA, started=started, eta=started + 5_000_000, deadline=started + 7_000_000,
                    cause=w.Cause(source=source, actor=w.MIKA),
                    steps=(w.Step(kind="walk", to_room="bedroom", to_place="bed", duration_us=5_000_000),))


def _state(seq: int, *intents: w.Intent) -> w.WorldState:
    return w.WorldState(rev=0, seq=seq, actors=(w.ActorState(id=w.MIKA, room="bedroom", place="center"),),
                        objects=(), intents=intents)


def _wire(frame: p.Wire) -> dict:
    """La trame telle qu'elle part, relue par le schéma du protocole (elle doit s'y conformer)."""
    text = p.dump(frame)
    p.server_frame(text)
    return json.loads(text)


class TestTraduction:
    def test_chaque_evenement_du_monde_a_sa_trame_et_son_seq(self) -> None:
        moved = w.ActorMoved(actor=w.MIKA, room="bedroom", place="window")
        cause = w.Cause(source=w.Source.HOST, actor="player:user_1", handle="user_1")
        request = w.Request(id="q-1", kind=w.RequestKind.HUG, from_actor="player:user_1", to_actor=w.MIKA,
                            expires=AT + 60_000_000)
        events = [
            _event(10, w.INTENDED, w.Intended(intent=_intent())),
            _event(14, w.ENDED, w.Ended(intent="i-1", actor=w.MIKA, outcome=w.Outcome.DONE, changes=(moved,))),
            _event(15, w.CHANGED, w.Changed(cause=cause, changes=(moved,))),
            _event(17, w.REQUESTED, w.Requested(request=request)),
            _event(18, w.ANSWERED, w.Answered(request="q-1", answer=w.Answer.DECLINED)),
            _event(20, w.GESTURED, w.Gestured(actor="player:user_1", gesture=w.Gesture.WAVE, to_actor=w.MIKA)),
            _event(21, w.JOINED, w.Joined(actor="player:user_1", handle="user_1", room="bedroom", place="door")),
            _event(25, w.LEFT, w.Left(actor="player:user_1", handle="user_1")),
        ]
        got = translate(events, _state(25), {"user_1": "Adrien"})
        frames = [_wire(f) for f in got.frames]
        assert [(f["type"], f["seq"]) for f in frames] == [
            ("intent", 10), ("intent_end", 14), ("delta", 15), ("request", 17), ("request_end", 18),
            ("gesture", 20), ("presence", 21), ("presence", 25)]
        assert not got.reset and not got.redefined
        assert frames[1]["changes"][0]["place"] == "window" and frames[2]["at"] == AT
        assert frames[6]["joined"] is True and frames[6]["label"] == "Adrien" and frames[7]["joined"] is False

    def test_ce_qui_ne_regarde_qu_elle_n_a_pas_de_trame(self) -> None:
        events = [
            _event(3, w.NOTICED, w.Noticed(source="monde", kind="signal", summary=Content.of("une tasse est tombée"),
                                           pertinence=0.4)),
            _event(4, w.DESCRIBED, w.Described(of=w.DefKind.OBJECT, id="desk", text=Content.of("son bureau"))),
        ]
        assert translate(events, _state(2)) == translate([], _state(2))

    def test_le_coucher_part_avec_l_endormissement(self) -> None:
        """Le réflexe naît dans la même transaction : son ``intent`` porte le ``seq`` de l'endormissement."""
        bed = _intent("coucher:e40", source=w.Source.REFLEX)
        asleep = _event(40, body_c.FELL_ASLEEP, body_c.FellAsleep(at=AT, pressure=0.9))
        got = translate([asleep], _state(40, bed))
        assert [(f.type, f.seq, f.intent.id) for f in got.frames] == [("intent", 40, "coucher:e40")]
        assert not got.reset
        # une action de Mika commencée au même instant n'est pas un réflexe : elle a sa propre trame
        assert translate([asleep], _state(40, _intent("i-9"))).reset

    def test_un_changement_sans_action_a_rejouer_demande_un_instantane(self) -> None:
        woke = _event(50, body_c.WOKE, body_c.Woke(at=AT, pressure=0.1))
        assert translate([woke], _state(50)).reset  # elle s'est réveillée assise au bord du lit
        assert translate([woke], _state(49)) == translate([], _state(49))  # elle était déjà debout : rien n'a bougé

    def test_une_edition_dit_sa_revision_et_demande_la_definition(self) -> None:
        change = w.DefRemove(of=w.DefKind.OBJECT, id="cookie_2")
        got = translate([_event(60, w.AUTHORED, w.Authored(base_rev=3, changes=(change,), by="user_1"))], _state(60))
        frame = _wire(got.frames[0])
        assert (frame["type"], frame["seq"], frame["base"], frame["rev"]) == ("definition_delta", 60, 3, 4)
        assert got.reset and got.redefined


class TestTramesIllisibles:
    def _why(self, raw: dict) -> str:
        try:
            p.client_frame(json.dumps(raw))
        except ValidationError as exc:
            return explain(exc, raw)
        raise AssertionError("trame lue")

    def test_la_phrase_dit_quoi_et_quelle_commande(self) -> None:
        assert self._why({"type": "act", "cmd": "a-1", "action": "ouvrir", "foo": 1}) == \
            "trame illisible (a-1) : champ inconnu « foo »"
        assert self._why({"type": "teleport", "to": "garden"}) == "trame illisible : type de trame inconnu « teleport »"
        assert "champ manquant « action »" in self._why({"type": "act", "cmd": "a-2"})


# ── Le port ────────────────────────────────────────────────────────────────


def _run(tmp_path, script):
    kernel, clock, _, _ = build(tmp_path, lambda req: LLMResponse("…"), start=at_paris(2026, 9, 28, 15, 0))
    out: dict = {}

    async def main():
        await boot(kernel)
        try:
            await script(kernel, KernelPort(kernel), out)
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    return out


async def _going(kernel, ident: str, place: str = "window") -> tuple[w.Intent, int]:
    frame = kernel.mind.frame()
    s = frame.state("world")
    t = replace(timing(None), walk_speed=0.05)  # lente : l'échéance ne tombe pas pendant l'essai
    steps = plan.plan_go(s.definition, t, s.actors, w.MIKA, place)
    intent = plan.intent_of(w.MIKA, steps, frame.now, t, w.Cause(source=w.Source.MIKA, actor=w.MIKA), ident)
    commit = await kernel.mind.append([w.INTENDED.draft(intent=intent)], emitter="world", correlation="test",
                                      origin=Origin.EXTERNAL)
    return intent, commit.seqs[-1]


def _finished(intent: str, cmd: str = "r-1") -> w.Report:
    return w.Report(cmd=cmd, report=w.Finished(intent=intent, outcome=w.Outcome.DONE))


def test_le_port_rend_ce_que_la_faculte_decide(tmp_path) -> None:
    async def script(kernel, port, out):
        intent, out["intended"] = await _going(kernel, "i-a")
        kw = {"actor": "player:user_1", "handle": "user_1", "session": "s-1"}
        out["guest"] = await port.world_command(_finished(intent.id), operator=False, **kw)
        out["progress"] = await port.world_command(w.Report(cmd="r-0", report=w.Progress(intent=intent.id, step=0)),
                                                   operator=True, **kw)
        out["done"] = await port.world_command(_finished(intent.id), operator=True, **kw)
        out["again"] = await port.world_command(_finished(intent.id, "r-2"), operator=True, **kw)
        out["me"] = port.world_view()[1]

    out = _run(tmp_path, script)
    assert (out["guest"].status, out["guest"].code) == (w.CommandStatus.REFUSED, w.Refusal.NOT_HOST)
    assert out["guest"].message
    assert (out["progress"].status, out["progress"].seq) == (w.CommandStatus.ACCEPTED, None)  # rien d'écrit
    assert out["done"].status is w.CommandStatus.ACCEPTED and out["done"].seq > out["intended"]
    assert out["again"].code is w.Refusal.UNKNOWN  # déjà terminée
    assert out["me"].seq == out["done"].seq and not out["me"].intents


def test_un_monde_qui_a_bouge_entre_la_decision_et_l_ecriture_rend_stale(tmp_path) -> None:
    async def script(kernel, port, out):
        first, _ = await _going(kernel, "i-a")
        decided = kernel.mind.frame()  # la décision lit ce monde-là…
        await _going(kernel, "i-b", "door")  # … qui bouge avant l'écriture
        live = kernel.mind.frame
        kernel.mind.frame = lambda **kw: decided
        try:
            out["late"] = await port.world_command(_finished(first.id), actor="player:user_1", handle="user_1",
                                                   operator=True)
        finally:
            kernel.mind.frame = live
        out["ends"] = sum(1 for e in kernel.mind.store.read(after=0) if e.type == w.ENDED.name)

    out = _run(tmp_path, script)
    assert (out["late"].status, out["late"].code) == (w.CommandStatus.REFUSED, w.Refusal.STALE)
    assert out["late"].message and out["ends"] == 0


def test_le_rattrapage_relit_le_journal_et_dit_quand_c_est_trop(tmp_path) -> None:
    async def script(kernel, port, out):
        out["start"] = kernel.mind.head
        _, out["a"] = await _going(kernel, "i-a")
        _, out["b"] = await _going(kernel, "i-b", "door")
        out["all"] = port.world_events(out["start"], limit=10)
        out["one"] = port.world_events(out["start"], limit=1)
        out["after_a"] = port.world_events(out["a"], limit=10)
        out["types"] = port._screen_types()
        commit = await kernel.mind.append([body_c.FELL_ASLEEP.draft(at=kernel.mind.frame().now, pressure=0.9)],
                                          emitter="body", correlation="test", origin=Origin.EXTERNAL)
        update = port.world_update(commit.events, commit.root)
        out["asleep"], out["frames"] = commit.seqs[-1], translate(update[0], update[2]).frames

    out = _run(tmp_path, script)
    assert [e.seq for e in out["all"]] == [out["a"], out["b"]]
    assert out["one"] is None  # plus que la limite : le client recevra un instantané
    assert [e.seq for e in out["after_a"]] == [out["b"]]
    # ce que le monde réduit sans le posséder en est (le coucher, le réveil, les lieux d'avant le monde) ; ce
    # qu'elle remarque et la prose n'en sont pas
    assert {"body.fell_asleep", "body.woke", "place.moved", "world.intended"} <= out["types"]
    assert not {"world.noticed", "world.described"} & out["types"]
    assert [(f.type, f.seq, f.intent.cause.source) for f in out["frames"]] == [
        ("intent", out["asleep"], w.Source.REFLEX)]
