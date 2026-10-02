"""La parole n'attend jamais (ADR 0040), par ce qu'on attend d'elle.

- une réponse ne passe jamais derrière une initiative bloquée par le fond
  (KER-4, EDG-13) ;
- la parole n'attend jamais une capacité lente ; l'ordre d'un destinataire est
  gardé (KER-8, PRJ-5, EDG-7) ;
- un envoi raté est réessayé à une date, un ``False`` du transport est un
  échec, une parole trop vieille ne part plus (KER-9) ;
- un gestionnaire fautif ne tue pas la file (KER-7) ;
- une capacité non rejouable, interrompue par une panne, n'est pas relancée
  en silence (PRJ-25) ;
- le murmure passe après le départ gardé de l'initiative, et ne part pas si
  elle est devancée (KER-24) ;
- le démarrage en deux temps : rien ne vit avant ``live`` (KER-20) ;
- un épisode porte le numéro exact de la sélection qui l'a choisi (CON-17) ;
- une réponse recomposée ne refait pas les écritures de ses outils (KER-23) ;
- un bail pris en route est toujours rendu (KER-25).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mika.app import composition
from mika.contracts import runtime as rt
from mika.faculties.expression import ExpressionParams
from mika.kernel.arbitration import Candidate, Row
from mika.kernel.builtin import LEASE, LEASE_ACQUIRED
from mika.kernel.clock import MINUTE, US
from mika.kernel.episode import EpisodePolicy, Outcome
from mika.kernel.events import Content, Origin, Payload
from mika.kernel.faculty import CAPABILITY_LANE, Faculty, ToolResult
from mika.kernel.guards import Guard
from mika.kernel.registry import ArbitrationPolicy
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.scripted import ScriptedLLM
from mika.sim.world import Driver
from mika.vocab.episodes import Kind
from tests.conftest import START
from tests.fixtures.harness import CONTACTS, events_of
from tests.fixtures.harness import build as build_toy
from tests.fixtures.harness import said as said_toy
from tests.fixtures.mika import AFTERNOON, boot, build, connect, said


@dataclass(frozen=True, slots=True)
class Nothing:
    n: int = 0


class Ping(Payload):
    n: int = 0
    target: str | None = None


# ── KER-4 : une réponse ne passe pas derrière une initiative ──────────────

LAT = {"step": 60.0, "initiative": 20.0, "reply": 5.0}


def test_a_reply_never_waits_behind_an_initiative_stuck_behind_the_background(tmp_path):
    kernel, clock, llm = build_toy(tmp_path, [CONTACTS], respond=lambda r: LLMResponse(f"[{r.role}] ok"),
                                   latency=lambda r: LAT[r.role])

    async def main():
        await kernel.start()
        step = kernel.lanes.submit(EpisodeRequest(kind="STEP", priority=2))  # tient le seul créneau 60 s
        await asyncio.sleep(1)
        initiative = kernel.lanes.submit(EpisodeRequest(kind="INITIATIVE", target="bob", priority=1))
        await asyncio.sleep(1)
        t0 = clock.now()
        p = await kernel.perceive(said_toy("alice", "t'es là ?"))  # premier plan, pour quelqu'un d'autre
        rep = await p.reply
        lag = (clock.now() - t0) / US
        outcomes = ((await step).outcome, (await initiative).outcome)
        await kernel.stop()
        return rep, lag, outcomes

    rep, lag, outcomes = run_virtual(clock, main)
    assert rep.outcome is Outcome.DONE and lag < LAT["reply"] + 2, f"réponse à +{lag:.0f} s"
    assert outcomes == (Outcome.PREEMPTED, Outcome.PREEMPTED), "le fond tenait vraiment le modèle"


# ── KER-8 / KER-9 / KER-7 : la file de sortie ─────────────────────────────

OUT = Faculty("out", state=Nothing, init=lambda p: Nothing())
SLOW = OUT.event("out.slow", Ping, public=True)
SAY = OUT.event("out.say", Ping, public=True)
BAD = OUT.event("out.bad", Ping, public=True)
SAID: list[tuple[int, int, str | None]] = []
FAILS: dict[int, int] = {}


@OUT.effect(SLOW, lane=CAPABILITY_LANE, deadline_s=600.0)
async def _slow(ev, ports):
    await asyncio.sleep(90)  # une commande réseau, un git push


@OUT.effect(SAY)
async def _say(ev, ports):
    if FAILS.get(ev.data.n, 0) > 0:
        FAILS[ev.data.n] -= 1
        raise ConnectionError("le transport hoquette")
    SAID.append((ev.data.n, ports["frame"]().now, ev.data.target))


@OUT.effect(BAD)
async def _bad(ev, ports):
    return [CONTACTS_EV.draft()]  # un bogue : un brouillon d'un autre propriétaire


OTHER = Faculty("other", state=Nothing, init=lambda p: Nothing())
CONTACTS_EV = OTHER.event("other.ev", Ping, public=True)


async def _emit(kernel, ev, **kw) -> int:
    commit = await kernel.mind.append([ev.draft(**kw)], emitter=ev.owner, correlation="t", origin=Origin.EXTERNAL)
    return commit.seqs[-1]


def test_speech_never_waits_behind_a_slow_capability(tmp_path):
    SAID.clear()
    FAILS.clear()
    kernel, clock, _ = build_toy(tmp_path, [OUT, OTHER])

    async def main():
        await kernel.start()
        await _emit(kernel, SLOW, n=0)
        await asyncio.sleep(1)
        t0 = clock.now()
        await _emit(kernel, SAY, n=1, target="alice")
        await asyncio.sleep(2)
        lag = (SAID[0][1] - t0) / US if SAID else None
        await kernel.stop()
        return lag

    lag = run_virtual(clock, main)
    assert lag is not None and lag < 1, "la parole part pendant que la capacité tourne"


def test_a_failed_delivery_is_retried_at_a_date_and_keeps_its_recipients_order(tmp_path):
    SAID.clear()
    FAILS.clear()
    FAILS[1] = 2  # la première parole à Alice échoue deux fois
    kernel, clock, _ = build_toy(tmp_path, [OUT, OTHER])

    async def main():
        await kernel.start()
        t0 = clock.now()
        await _emit(kernel, SAY, n=1, target="alice")
        await _emit(kernel, SAY, n=2, target="alice")
        await _emit(kernel, SAY, n=3, target="bob")
        await asyncio.sleep(60)  # aucun autre événement : la reprise est datée, pas attendue d'un réveil
        await kernel.stop()
        return t0

    t0 = run_virtual(clock, main)
    order = [n for n, _, _ in SAID]
    assert sorted(order) == [1, 2, 3], "tout finit par partir"
    assert order.index(1) < order.index(2), "jamais une parole avant celle d'avant, pour la même personne"
    bob = next(at for n, at, _ in SAID if n == 3)
    alice = next(at for n, at, _ in SAID if n == 1)
    assert (bob - t0) / US < 1, "Bob n'attend pas les hoquets d'Alice"
    assert 10 <= (alice - t0) / US <= 30, "deux reculs (5 s puis 10 s), pas un réessai à chaque événement"


def test_a_poisoned_effect_does_not_kill_the_outbox(tmp_path):
    """Un gestionnaire qui rend un compte rendu refusé (un bogue), une ligne dont l'événement ne se relit plus
    (un journal abîmé) : chacune est close en échec, la file continue — à chaque démarrage aussi."""
    SAID.clear()
    FAILS.clear()
    kernel, clock, _ = build_toy(tmp_path, [OUT, OTHER])

    async def main():
        await kernel.start()
        await kernel.mind.store.run_mind(lambda sql: sql.execute(
            "INSERT INTO outbox(key, seq, effect, status, attempts, last_error) VALUES(?,?,?,?,?,?)",
            ("illisible", 0, "out:out.say", "pending", 0, None)))
        await _emit(kernel, BAD, n=0)
        await asyncio.sleep(1)
        for i in range(3):
            await _emit(kernel, SAY, n=10 + i)
            await asyncio.sleep(1)
        dead = kernel.dead_loops()
        status = kernel.mind.store.query_mind("SELECT status FROM outbox WHERE key='illisible'")
        await kernel.stop()
        return dead, status

    dead, status = run_virtual(clock, main)
    assert dead == [] and [n for n, _, _ in SAID] == [10, 11, 12]
    assert status == [("failed",)]


class Refusing:
    """Un transport qui ne peut pas prendre la livraison (canal absent) : il rend ``False``."""

    def __init__(self, refuse: int) -> None:
        self.refuse = refuse
        self.items: list[Any] = []

    async def deliver(self, d: Any) -> bool:
        if d.kind == "speech" and d.source == "reply" and self.refuse > 0:
            self.refuse -= 1
            return False
        self.items.append(d)
        return True


def test_a_false_from_the_transport_is_a_failure_and_is_retried(tmp_path):
    port = Refusing(refuse=1)
    kernel, clock, llm, _ = build(tmp_path, lambda r: LLMResponse("oui ! [EMOTION:happy:0.5]"),
                                  ports={"delivery": port})

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        p = await kernel.perceive(said("user_1", "t'es là ?"))
        await p.reply
        await asyncio.sleep(30)
        await kernel.stop()

    run_virtual(clock, main)
    assert [d.text for d in port.items if d.source == "reply"] == ["oui !"], "réessayée, livrée une fois"


def test_speech_that_could_not_leave_in_ten_minutes_is_not_said_late(tmp_path):
    port = Refusing(refuse=10_000)
    kernel, clock, llm, _ = build(tmp_path, lambda r: LLMResponse("oui ! [EMOTION:happy:0.5]"),
                                  ports={"delivery": port})

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(1200)
        p = await kernel.perceive(said("user_1", "t'es là ?"))
        await p.reply
        await asyncio.sleep(30 * MINUTE / US)
        statuses = kernel.mind.store.query_mind("SELECT status FROM outbox WHERE effect='expression:episode.utterance'")
        await kernel.stop()
        return [s for (s,) in statuses]

    statuses = run_virtual(clock, main)
    assert "stale" in statuses and not [d for d in port.items if d.source == "reply"]


# ── PRJ-25 : une capacité interrompue n'est pas relancée en silence ───────

CAP = Faculty("cap", state=Nothing, init=lambda p: Nothing())
RAN: list[str] = []


@CAP.capability("send", description="envoyer quelque chose (non rejouable)")
async def _send(args, context, ports):
    RAN.append("send")
    await asyncio.sleep(30)
    return True, "parti"


@CAP.capability("fetch", description="récupérer quelque chose (rejouable)", idempotent=True)
async def _fetch(args, context, ports):
    RAN.append("fetch")
    await asyncio.sleep(30)
    return True, "récupéré"


def _propose(capability: str) -> Any:
    return rt.EFFECT_PROPOSED.draft(capability=capability, owner="cap", args_json="{}",
                                    summary=Content.of(capability), approval=False)


def test_a_non_replayable_capability_cut_by_a_crash_is_not_rerun(tmp_path):
    RAN.clear()
    clock = SimClock(START)

    async def main():
        kernel, _, _ = build_toy(tmp_path, [CAP], clock=clock)
        await kernel.start()
        await kernel.mind.append([_propose("cap.send"), _propose("cap.fetch")], emitter="runtime",
                                 correlation="t", origin=Origin.KERNEL)
        await asyncio.sleep(5)  # les deux tournent
        await kernel.abort()  # kill -9 pendant l'exécution
        again, _, _ = build_toy(tmp_path, [CAP], clock=clock, seed=1)
        await again.start()
        await asyncio.sleep(60)
        executed = [e.data for e in events_of(again, rt.EFFECT_EXECUTED.name)]
        await again.stop()
        return executed

    executed = run_virtual(clock, main)
    assert RAN.count("send") == 1, "un envoi interrompu n'est pas relancé tout seul"
    assert RAN.count("fetch") == 2, "une capacité rejouable repart"
    failed = [e for e in executed if not e.ok]
    assert len(failed) == 1 and "interrompue par un arrêt" in failed[0].result
    assert any(e.ok and e.result == "récupéré" for e in executed)


@CAP.capability("hang", description="une commande qui ne finit pas (non rejouable)")
async def _hang(args, context, ports):
    RAN.append("hang")
    await asyncio.sleep(5000)
    return True, "fini"


def test_a_capability_cut_by_its_deadline_says_so_not_a_crash(tmp_path):
    """Au-delà de son échéance (900 s), une capacité est coupée : on ne sait pas si elle a eu lieu, on ne la
    relance pas — mais il n'y a pas eu d'arrêt, et elle (comme l'opérateur) ne doit pas lire « un arrêt »."""
    RAN.clear()
    clock = SimClock(START)

    async def main():
        kernel, _, _ = build_toy(tmp_path, [CAP], clock=clock)
        await kernel.start()
        await kernel.mind.append([_propose("cap.hang")], emitter="runtime", correlation="t", origin=Origin.KERNEL)
        await asyncio.sleep(1200)
        executed = [e.data for e in events_of(kernel, rt.EFFECT_EXECUTED.name)]
        rows = kernel.mind.store.query_mind("SELECT status, last_error FROM outbox WHERE effect LIKE '%proposed'")
        await kernel.stop()
        return executed, rows

    executed, rows = run_virtual(clock, main)
    assert RAN == ["hang"]  # pas relancée
    assert len(executed) == 1 and not executed[0].ok
    said_ = executed[0].result
    assert "900 s" in said_ and "délai dépassé" in said_ and "arrêt" not in said_
    assert rows == [("interrupted", "délai dépassé : coupée au bout de 900 s")]


# ── KER-24 : le murmure ───────────────────────────────────────────────────


def _murmur_world(tmp_path: Path, latency: dict[str, float]) -> tuple[Driver, SimClock]:
    clock = SimClock(AFTERNOON)

    def respond(req: LLMRequest) -> LLMResponse:
        if req.role == "murmur":
            return LLMResponse("tiens, si je lui écrivais")
        if req.role == "initiative":
            return LLMResponse("Coucou toi ! [EMOTION:happy:0.5]")
        return LLMResponse("d'accord [EMOTION:happy:0.4]")

    llm = ScriptedLLM(clock, respond, latency=lambda r: latency.get(r.role, 1.0))
    return Driver(tmp_path, composition.for_simulation(), llm, clock), clock


async def _always_murmur(driver: Driver, adrift: float = 0.0) -> None:
    """Le murmure n'est pas tiré au sort ici (il l'est d'ordinaire une fois sur trois), ni le fait qu'elle se
    ravise (``adrift``)."""
    assert driver.kernel is not None
    await driver.kernel.set_params("expression", ExpressionParams(murmur_chance=1.0, murmur_charged_chance=1.0,
                                                                  murmur_adrift=adrift))


def _initiative(driver: Driver) -> Any:
    assert driver.kernel is not None
    return driver.kernel.lanes.submit(EpisodeRequest(kind=Kind.INITIATIVE, target="user_2", reason="envie",
                                                     priority=1))


def test_the_murmur_comes_after_the_guarded_start_and_right_before_the_words(tmp_path):
    driver, clock = _murmur_world(tmp_path, {"initiative": 10.0, "murmur": 1.0})

    async def main():
        await driver.boot()
        await _always_murmur(driver)
        await driver.connect("user_1", "Adrien")
        await driver.connect("user_2", "Bea")
        await asyncio.sleep(2 * 3600)  # salutations et murmures passés
        report = await _initiative(driver)
        events = driver.read_events()
        await driver.stop()
        return report, events

    report, events = run_virtual(clock, main)
    assert report.outcome is Outcome.DONE
    started = next(e for e in events if e.type.name == rt.EPISODE_STARTED.name and e.correlation == report.id)
    murmur = [e for e in events if e.type.name == rt.UTTERANCE.name and e.data.kind == "MURMUR"
              and e.seq > started.seq]
    words = next(e for e in events if e.type.name == rt.UTTERANCE.name and e.correlation == report.id)
    assert murmur and started.seq < murmur[-1].seq < words.seq


def test_no_murmur_when_the_initiative_is_cut_before_speaking(tmp_path):
    driver, clock = _murmur_world(tmp_path, {"initiative": 20.0, "murmur": 1.0, "reply": 2.0})

    async def main():
        await driver.boot()
        await _always_murmur(driver)
        await driver.connect("user_1", "Adrien")
        await driver.connect("user_2", "Bea")
        await asyncio.sleep(2 * 3600)
        fut = _initiative(driver)
        await asyncio.sleep(5)  # elle compose son initiative…
        await driver.say("user_1", "dis, t'es là ?")  # …quelqu'un écrit : la réponse passe devant
        report = await fut
        events = driver.read_events()
        await driver.stop()
        return report, events

    report, events = run_virtual(clock, main)
    assert report.outcome is Outcome.PREEMPTED
    started = next(e for e in events if e.type.name == rt.EPISODE_STARTED.name and e.correlation == report.id)
    assert not [e for e in events if e.type.name == rt.UTTERANCE.name and e.data.kind == "MURMUR"
                and e.seq > started.seq], "devancée avant de parler : pas de murmure"


def test_when_she_changes_her_mind_the_initiative_is_not_even_composed(tmp_path):
    """Elle y pense, se ravise (un murmure sans suite) : la pensée part, seule ; l'initiative se règle sans
    avoir été composée — aucun appel de modèle pour une parole qui ne partira pas. Contre-exemple : si elle
    ne se ravise pas, l'initiative est bien composée et dite."""
    def world(adrift: float) -> tuple[Any, list[str], list[Any]]:
        driver, clock = _murmur_world(tmp_path / str(adrift), {"initiative": 10.0, "murmur": 1.0})

        async def main():
            await driver.boot()
            await _always_murmur(driver, adrift)
            await driver.connect("user_1", "Adrien")
            await driver.connect("user_2", "Bea")
            await asyncio.sleep(2 * 3600)
            before = len(driver.llm.calls)
            report = await _initiative(driver)
            roles = [c.role for c in driver.llm.calls[before:]]
            events = driver.read_events()
            await driver.stop()
            return report, roles, [e for e in events if e.type.name == rt.UTTERANCE.name
                                   and e.correlation == report.id]

        return run_virtual(clock, main)

    report, roles, words = world(1.0)
    assert report.outcome is Outcome.ABSTAINED and "ravisée" in report.detail
    assert roles == ["murmur"] and not words
    report, roles, words = world(0.0)
    assert report.outcome is Outcome.DONE and roles == ["initiative", "murmur"] and words


# ── KER-20 : deux temps ───────────────────────────────────────────────────


def test_nothing_lives_between_boot_and_live(tmp_path):
    kernel, clock, llm = build_toy(tmp_path, [CONTACTS])

    async def main():
        await kernel.boot()
        between = (kernel.phase, kernel.started, list(kernel._tasks))
        p = await kernel.perceive(said_toy("alice", "coucou"))
        await asyncio.sleep(30)
        answered_before = p.reply.done()
        await kernel.live()
        report = await p.reply
        after = kernel.phase
        await kernel.stop()
        return between, answered_before, report, after

    between, answered_before, report, after = run_virtual(clock, main)
    assert between == ("starting", False, [])
    assert not answered_before and report.outcome is Outcome.DONE and after == "ready"


# ── CON-17 : la sélection exacte ──────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Pull:
    pass


PULLER = Faculty("puller", state=Pull, init=lambda p: Pull())


@PULLER.propose(kinds=["INITIATIVE"], reasons={"envie": (0.0, 9.0)})
def _want(s, frame):
    return [Candidate("INITIATIVE", "alice", "envie", 9.0)]


def test_an_episode_carries_the_exact_selection_that_chose_it(tmp_path):
    policy = ArbitrationPolicy(thresholds={"INITIATIVE": 0.0}, max_rates={"INITIATIVE": 1 / 30})
    kernel, clock, _ = build_toy(tmp_path, [CONTACTS, PULLER], arbitration=policy)

    async def main():
        await kernel.start()
        await asyncio.sleep(600)
        await kernel.stop()

    run_virtual(clock, main)
    selections = {e.seq for e in events_of(kernel, "kernel.selected")}
    started = [e.data for e in events_of(kernel, rt.EPISODE_STARTED.name) if e.data.kind == "INITIATIVE"]
    assert started and all(s.selected in selections for s in started)
    assert all(s.trigger == f"selected:{s.selected}" for s in started)


# ── KER-23 : une réponse recomposée ne refait pas ses écritures ───────────

NOTES = Faculty("notes", state=Nothing, init=lambda p: Nothing())
NOTED = NOTES.event("notes.noted", Ping, public=True)


class NoteArgs(BaseModel):
    text: str


@NOTES.tool("note_this", description="noter", args=NoteArgs, bundle="notes", episodes=["REPLY"])
async def _note(args: NoteArgs, ctx) -> ToolResult:
    await ctx.emit(NOTED.draft(n=len(args.text)))
    return ToolResult(content="noté")


def test_a_recomposed_reply_does_not_redo_its_tool_writes(tmp_path):
    ids = iter(range(1, 100))

    def respond(req: LLMRequest) -> LLMResponse:
        if req.messages[-1].role == "tool":
            return LLMResponse("c'est noté ! [EMOTION:happy:0.5]")
        # un vrai fournisseur donne un nouvel identifiant à chaque appel (« toolu_… ») : la recomposition ne
        # retrouve pas le sien — l'écriture se reconnaît à ce qu'elle est (l'outil, ses arguments, au même tour)
        return LLMResponse("", tool_calls=(ToolCall(f"toolu_{next(ids)}", "note_this", {"text": "rappel lundi"}),),
                           stop="tool_use")

    reply = EpisodePolicy(kind="REPLY", role="reply", priority=0, lane="conversation",
                          tool_bundles=frozenset({"notes"}))
    kernel, clock, _ = build_toy(tmp_path, [CONTACTS, NOTES], respond=respond, latency=10.0,
                                 policies={"REPLY": reply})

    async def main():
        await kernel.start()
        a = await kernel.perceive(said_toy("alice", "note que j'ai rdv lundi"))
        await asyncio.sleep(15)  # l'outil a écrit, la réponse se compose encore…
        b = await kernel.perceive(said_toy("alice", "à 9 h"))  # …elle est supplantée, puis recomposée
        await a.reply
        await b.reply
        await asyncio.sleep(5)
        await kernel.stop()

    run_virtual(clock, main)
    assert len(events_of(kernel, NOTED.name)) == 1, "le même appel, au même tour : une seule écriture"
    replies = [e for e in events_of(kernel, rt.UTTERANCE.name) if e.data.kind == "REPLY"]
    assert len(replies) == 1


def test_identical_provider_call_ids_in_two_turns_both_write(tmp_path):
    """Le contre-exemple : deux tours différents, le même identifiant d'appel ``call_0`` du fournisseur — deux
    écritures (l'ancienne clé ``call_0:0`` avalait la seconde)."""

    def respond(req: LLMRequest) -> LLMResponse:
        if req.messages[-1].role == "tool":
            return LLMResponse("noté ! [EMOTION:happy:0.5]")
        return LLMResponse("", tool_calls=(ToolCall("call_0", "note_this", {"text": req.messages[-1].content}),),
                           stop="tool_use")

    reply = EpisodePolicy(kind="REPLY", role="reply", priority=0, lane="conversation",
                          tool_bundles=frozenset({"notes"}))
    kernel, clock, _ = build_toy(tmp_path, [CONTACTS, NOTES], respond=respond, policies={"REPLY": reply})

    async def main():
        await kernel.start()
        for text in ("note A", "note BB"):
            p = await kernel.perceive(said_toy("alice", text))
            await p.reply
        await kernel.stop()

    run_virtual(clock, main)
    assert len(events_of(kernel, NOTED.name)) == 2


# ── KER-25 : un bail pris en route est rendu ──────────────────────────────


def test_a_lease_taken_before_a_busy_one_is_always_given_back(tmp_path):
    kernel, clock, _ = build_toy(tmp_path, [CONTACTS])
    row_args = FrozenDict()

    async def main():
        await kernel.start()
        # « b » est tenu par quelqu'un d'autre ; l'initiative veut « a » puis « b »
        await kernel.mind.append([LEASE_ACQUIRED.draft(resource="b", holder="quelqu'un",
                                                       until=clock.now() + 3600 * US)],
                                 emitter="kernel", correlation="x", origin=Origin.KERNEL)
        from_row = Row("INITIATIVE", "alice", (("x", "envie", 1.0),), 0.0, (), 1.0, 0.1,
                       resources=frozenset({"a", "b"}), args=row_args, guards=(Guard("rien"),))
        report = await kernel.lanes.submit(EpisodeRequest(kind="INITIATIVE", target="alice", selected=from_row,
                                                          priority=1))
        frame = kernel.mind.frame()
        held_a = frame.get(LEASE("a"))
        await kernel.stop()
        return report, held_a

    report, held_a = run_virtual(clock, main)
    assert report.outcome is Outcome.SUPERSEDED and "ressource occupée" in report.detail
    assert held_a is None, "le bail « a » pris en route a été rendu"

