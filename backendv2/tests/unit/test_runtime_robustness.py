"""Des boucles sûres par construction (ADR 0040), par ce qu'on attend d'elles.

- un processus en échec n'est pas relancé à l'infini : recul, une seule trace
  par série ; un passage qui ne fait rien ne tourne pas à vide (KER-1) ;
- le calcul pur ne fait jamais la queue derrière le modèle ; un passage figé
  est coupé (KER-16) ;
- un instantané impossible, une garde qui lève, une purge qui lève, un plugin
  retiré : la vie continue et le journal se relit (KER-6, 10, 11, 18) ;
- une composition à double effet est refusée (KER-21) ;
- l'heure d'hiver ne fait pas tourner un agenda en boucle (KER-22) ;
- une envie « ANY » ne se multiplie pas par le nombre de présents (KER-17).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.faculties.memory.consolidation import Index, LetGo
from mika.kernel.arbitration import Anyone, Candidate, pool
from mika.kernel.clock import DAY, HOUR, MINUTE, US, instant
from mika.kernel.events import Content, Origin, Payload
from mika.kernel.faculty import Faculty
from mika.kernel.guards import Guard
from mika.kernel.registry import ArbitrationPolicy, CompositionError, Registry
from mika.kernel.schedule import next_after, parse
from mika.ports.llm import LLMRequest, LLMResponse, PersonaRender
from mika.runtime import health
from mika.runtime.scheduler import _BoundedLLM
from mika.sim.clock import run_virtual
from tests.conftest import make_mind
from tests.fixtures.harness import build, events_of
from tests.fixtures.mika import boot as boot_mika
from tests.fixtures.mika import build as build_mika
from tests.fixtures.toys import BUMPED, COUNTER, PEOPLE

PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True, slots=True)
class Nothing:
    n: int = 0


class Ping(Payload):
    n: int = 0


# ── KER-1 : un processus qui échoue, ou ne fait rien ──────────────────────
#
# Ces épreuves sont bornées par elles-mêmes : un processus qui dépasse ``RUNAWAY`` passages arrête
# l'ordonnanceur — un emballement fait **échouer** le test (en une fraction de seconde), il ne le fait pas
# tourner jusqu'à épuiser la mémoire (le 2026-10-02, une boucle sans recul avait pris 23 Go).

RUNAWAY = 2_000
BROKEN = Faculty("broken", state=Nothing, init=lambda p: Nothing())
RUNS = {"broken": 0, "idle": 0, "busy": 0, "same": 0}
STOP: list[Any] = []


def _runaway(name: str) -> None:
    RUNS[name] += 1
    if RUNS[name] >= RUNAWAY and STOP:
        STOP[0].stop()  # emballement : on arrête tout, le test échouera sur son compte


@BROKEN.process("toujours_du", wake_on=[])
class AlwaysDue:
    def next_due(self, state, frame, last_run):
        return frame.now  # « il y a du travail » tant que l'état n'a pas changé

    async def run(self, ctx) -> None:
        _runaway("broken")
        raise RuntimeError("port indisponible")  # l'index de vecteurs injoignable


IDLE = Faculty("idle", state=Nothing, init=lambda p: Nothing())


@IDLE.process("rien_a_faire", wake_on=[])
class NothingToDo:
    def next_due(self, state, frame, last_run):
        return frame.now  # se croit dû, ne fait jamais rien

    async def run(self, ctx) -> None:
        _runaway("idle")


BUSY = Faculty("busy", state=Nothing, init=lambda p: Nothing())
TICKED = BUSY.event("ticked", Ping, public=True)


@BUSY.process("toujours_occupe", wake_on=[])
class AlwaysWriting:
    def next_due(self, state, frame, last_run):
        return frame.now  # se croit toujours dû…

    async def run(self, ctx) -> None:
        _runaway("busy")
        await ctx.emit(TICKED.draft(n=RUNS["busy"]))  # … et écrit à chaque passage, sans jamais finir


SAME = Faculty("same", state=Nothing, init=lambda p: Nothing())
REWRITTEN = SAME.event("rewritten", Ping, public=True)


@SAME.process("redit_la_meme_chose", wake_on=[])
class SaysTheSameThing:
    def next_due(self, state, frame, last_run):
        return frame.now  # son état ne change jamais : il se croit toujours dû…

    async def run(self, ctx) -> None:
        _runaway("same")
        await ctx.emit(REWRITTEN.draft(dedupe_key="toujours-la-meme"))  # … et réécrit ce qui est déjà écrit


def _run_for(tmp_path, faculties, minutes: float) -> tuple[Any, health.Health]:
    """Fait vivre ``faculties`` ``minutes`` ; rend le noyau arrêté et son bilan de santé juste avant l'arrêt."""
    kernel, clock, _ = build(tmp_path, faculties)

    async def main():
        await kernel.start()
        STOP[:] = [kernel.scheduler]
        try:
            await asyncio.sleep(minutes * MINUTE / US)
            return health.report(kernel)
        finally:
            STOP.clear()
            await kernel.stop()

    return kernel, run_virtual(clock, main)


def test_a_failing_process_backs_off_and_is_journaled_once(tmp_path):
    RUNS["broken"] = 0
    kernel, _ = _run_for(tmp_path, [BROKEN], 10)
    failed = events_of(kernel, rt.PROCESS_FAILED.name)
    # 5 s, 10 s, 20 s… : une dizaine de passages en dix minutes, jamais des milliers
    assert 3 <= RUNS["broken"] <= 10, RUNS["broken"]
    assert len(failed) == 1, "une série d'échecs : une seule trace au journal"


def test_a_process_that_does_nothing_does_not_spin(tmp_path):
    RUNS["idle"] = 0
    _run_for(tmp_path, [IDLE], 10)
    # 0, 30 s, 1 min 30, 3 min 30, 7 min 30 : de plus en plus espacés tant que rien ne le réveille
    assert 3 <= RUNS["idle"] <= 8, RUNS["idle"]


def test_rewriting_what_is_already_written_is_not_progress(tmp_path):
    """Un ajout entièrement dédoublonné n'écrit rien : le passage compte comme un passage à vide (le cas
    d'une promesse qu'on « laisse filer » à chaque tour sans que l'état ne le retienne jamais)."""
    RUNS["same"] = 0
    kernel, _ = _run_for(tmp_path, [SAME], 10)
    assert 3 <= RUNS["same"] <= 8, RUNS["same"]
    assert len(events_of(kernel, REWRITTEN.name)) == 1


def test_a_process_that_writes_forever_is_held_back(tmp_path):
    """Quoi qu'il fasse — ici, écrire à chaque passage sans jamais cesser de se dire dû — un processus ne
    tourne pas en boucle : au-delà d'une rafale, il est retenu (une minute, puis deux, quatre…), et la santé
    le montre."""
    RUNS["busy"] = 0
    kernel, report = _run_for(tmp_path, [BUSY], 10)
    assert RUNS["busy"] < RUNAWAY and len(events_of(kernel, TICKED.name)) <= 5 * 120, RUNS["busy"]
    assert kernel.scheduler.storms.get("toujours_occupe", 0) >= 2
    processes = next(c for c in report.checks if c.name == "processes")
    assert processes.state == "degraded" and any("rafale" in d for d in processes.detail)


def test_on_her_real_life_a_process_that_does_nothing_or_fails_does_not_loop(tmp_path, monkeypatch):
    """Sur la composition réelle : ``memory.promises`` (laisser filer une promesse dépassée) dont le passage
    ne fait plus rien (un corps vidé), et ``memory.index`` dont l'index de vecteurs lève à chaque fois (l'extra
    absent) — ni l'un ni l'autre ne tourne en boucle sur deux heures."""
    runs = {"letgo": 0, "index": 0}
    stop: list[Any] = []

    async def emptied(self, ctx) -> None:
        runs["letgo"] += 1
        if runs["letgo"] >= RUNAWAY and stop:
            stop[0].stop()

    real_index = Index.run

    async def counted(self, ctx) -> None:
        runs["index"] += 1
        if runs["index"] >= RUNAWAY and stop:
            stop[0].stop()
        await real_index(self, ctx)

    class MissingExtra:
        name, dims = "st:absent", 0

        async def embed(self, texts):
            raise ModuleNotFoundError("No module named 'sentence_transformers'")

    monkeypatch.setattr(LetGo, "run", emptied)
    monkeypatch.setattr(Index, "run", counted)
    kernel, clock, _, _ = build_mika(tmp_path, lambda r: LLMResponse("{}"))
    kernel.ports["vectors"].embedder = MissingExtra()

    async def main():
        await boot_mika(kernel)
        stop[:] = [kernel.scheduler]
        now = kernel.mind.clock.now()
        await kernel.mind.append([memory_c.PROMISE_NOTICED.draft(
            text=Content.of("lui envoyer la recette", level=1), to="person:1", due=now - 30 * DAY),
            memory_c.REMEMBERED.draft(text=Content.of("on a parlé de jazz", level=1))],
            emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await asyncio.sleep(2 * HOUR / US)
        stop.clear()
        failed = [e for e in events_of(kernel, rt.PROCESS_FAILED.name) if e.data.process == "memory.index"]
        await kernel.stop()
        return failed

    failed = run_virtual(clock, main)
    assert 1 <= runs["letgo"] <= 12, runs  # 0, 30 s, 1 min 30… puis au plus une fois l'heure
    assert 1 <= runs["index"] <= 20 and len(failed) == 1, (runs, len(failed))


# ── KER-16 : le calcul pur ne fait pas la queue derrière le modèle ────────

LANES = Faculty("lanes", state=Nothing, init=lambda p: Nothing())
SEEN: dict[str, list[int]] = {"pure": [], "model": []}


class _Thinker:
    def next_due(self, state, frame, last_run):
        return frame.now if last_run is None else None

    async def run(self, ctx) -> None:
        await ctx.llm.call(LLMRequest(role="step", call_id=f"{ctx.run_id}#0", system_stable="x",
                                      persona=PersonaRender("Tu es Mika.", "h", "compact")))
        SEEN["model"].append(ctx.now)


LANES.process("pense_a", wake_on=[], priority=1)(type("ThinkA", (_Thinker,), {}))
LANES.process("pense_b", wake_on=[], priority=2)(type("ThinkB", (_Thinker,), {}))


@LANES.process("calcule", wake_on=[], priority=3)
class Pure:
    def next_due(self, state, frame, last_run):
        return frame.now if last_run is None else None

    async def run(self, ctx) -> None:
        SEEN["pure"].append(ctx.now)


HANGS = Faculty("hangs", state=Nothing, init=lambda p: Nothing())


@HANGS.process("fige", wake_on=[], deadline_s=60.0)
class Hangs:
    def next_due(self, state, frame, last_run):
        return frame.now if last_run is None else None

    async def run(self, ctx) -> None:
        await asyncio.sleep(3600)


def test_pure_work_never_waits_behind_model_calls(tmp_path):
    SEEN["pure"].clear()
    SEEN["model"].clear()
    kernel, clock, _ = build(tmp_path, [LANES], respond=lambda r: LLMResponse("ok"), latency=90.0,
                             process_lanes={"model": 1})

    async def main():
        await kernel.start()
        t0 = clock.now()
        await asyncio.sleep(300)
        await kernel.stop()
        return t0

    t0 = run_virtual(clock, main)
    assert SEEN["pure"] and SEEN["pure"][0] - t0 < 1 * US, "le calcul pur passe tout de suite"
    assert len(SEEN["model"]) == 2 and SEEN["model"][1] - SEEN["model"][0] >= 89 * US, "le modèle, un à la fois"


def test_a_stuck_process_is_cut_at_its_deadline(tmp_path):
    kernel, clock, _ = build(tmp_path, [HANGS])

    async def main():
        await kernel.start()
        await asyncio.sleep(120)
        out = dict(kernel.scheduler.consecutive), kernel.scheduler.running()
        await kernel.stop()
        return out

    consecutive, running = run_virtual(clock, main)
    assert consecutive.get("fige") == 1 and "fige" not in running


class _Session:
    """Un fournisseur à session : il tient chaque appel jusqu'à ce qu'on le relâche."""

    def __init__(self) -> None:
        self.released: list[str] = []

    async def call(self, req: LLMRequest) -> LLMResponse:
        return LLMResponse("", tool_calls=())

    def release(self, call_id: str) -> None:
        self.released.append(call_id)


async def test_a_process_model_call_is_released_as_soon_as_it_returns():
    """Jonction WP7 : un processus lit une sortie structurée en un appel (au besoin sur un appel d'outil) —
    l'appel est relâché dès son retour, sans attendre le fauchage du fournisseur à 660 s."""
    session = _Session()
    llm = _BoundedLLM(session, asyncio.Semaphore(1))
    await llm.call(LLMRequest(role="extract", call_id="memory.consolidate:1", system_stable=""))
    assert session.released == ["memory.consolidate:1"]


# ── KER-6 : un instantané impossible ──────────────────────────────────────


class Opaque:  # un objet métier glissé par erreur dans une tranche
    pass


@dataclass(frozen=True, slots=True)
class BadState:
    last: Any = None


BAD = Faculty("bad", state=BadState, init=lambda p: BadState())
NOTED = BAD.event("bad.noted", Ping, public=True)


@BAD.reducer(NOTED)
def _noted(s, e, cx):
    return replace(s, last=Opaque())


async def test_an_unserializable_slice_never_blocks_writes_nor_the_next_boot(tmp_path):
    m = make_mind(tmp_path, [COUNTER, BAD], snapshot_every=3)
    await m.boot()
    await m.append([NOTED.draft(n=1)], emitter="bad", correlation="x", origin=Origin.EXTERNAL)
    for _ in range(6):
        await m.append([BUMPED.draft(by=1)], emitter="counter", correlation="c", origin=Origin.EXTERNAL)
    head = m.head
    assert any("bad" in a for a in m.anomalies), "l'instantané impossible est dit"
    await m.close()
    m2 = make_mind(tmp_path, [COUNTER, BAD], snapshot_every=3)
    await m2.boot(append_boot=False)
    assert m2.root.slices["counter"].n == 6 and isinstance(m2.root.slices["bad"].last, Opaque)
    assert m2.head == head  # rien n'a été perdu
    await m2.close()


# ── KER-10 : une garde en vol qui lève ────────────────────────────────────


async def test_a_raising_guard_in_flight_never_fails_someone_elses_append(tmp_path):
    m = make_mind(tmp_path, [COUNTER])
    await m.boot()
    woken: list[Any] = []
    superseded: list[Any] = []
    m.subscribe(lambda evs, root: woken.append(len(evs)))
    m.track("épisode", Guard("fragile", predicate=lambda view: 1 / 0), m.root, "épisode", superseded.append)
    commit = await m.append([BUMPED.draft(by=1)], emitter="counter", correlation="autre", origin=Origin.EXTERNAL)
    assert commit.seqs and woken == [1]
    assert superseded and "la garde a levé" in superseded[0].reason
    await m.close()


# ── KER-11 : une purge d'oubli qui lève ───────────────────────────────────


@pytest.mark.parametrize("threaded", [False, True])
async def test_a_failing_forget_purge_never_poisons_the_writer(tmp_path, threaded):
    m = make_mind(tmp_path, [COUNTER], threaded=threaded)
    await m.boot()

    def purge(mind_sql, views_sql):
        views_sql.execute("DELETE FROM table_jamais_creee_v2 WHERE person=?", ("alice",))

    with pytest.raises(Exception, match="table_jamais_creee"):
        await m.store.forget_subject("alice", purge)
    for _ in range(2):
        await m.append([BUMPED.draft(by=1)], emitter="counter", correlation="c", origin=Origin.EXTERNAL)
    assert m.root.slices["counter"].n == 2
    await m.close()


# ── KER-18 : un plugin retiré de la composition ───────────────────────────


async def test_a_journal_still_replays_without_a_retired_faculty(tmp_path):
    m = make_mind(tmp_path, [COUNTER, PEOPLE])
    await m.boot()
    await m.append([BUMPED.draft(by=1)], emitter="counter", correlation="c", origin=Origin.EXTERNAL)
    head = m.head
    await m.close()
    m2 = make_mind(tmp_path, [PEOPLE])  # « counter » n'existe plus
    await m2.boot(append_boot=False)
    assert m2.head == head and m2.retired == {BUMPED.name}
    old = [m2.decode(s) for s in m2.store.read()]
    assert [e.type.owner for e in old if e.type.name == BUMPED.name] == ["retired"]
    await m2.close()


# ── KER-21 : deux effets d'un même propriétaire sur un même type ──────────

TWICE = Faculty("twice", state=Nothing, init=lambda p: Nothing())
TWICE_EV = TWICE.event("twice.ev", Ping, public=True)


@TWICE.effect(TWICE_EV)
async def _one(ev, ports):
    return None


@TWICE.effect(TWICE_EV)
async def _two(ev, ports):
    return None


def test_two_effects_of_one_owner_on_one_type_are_refused_at_composition():
    with pytest.raises(CompositionError, match="deux effets"):
        Registry([TWICE])


# ── KER-22 : l'heure d'hiver ──────────────────────────────────────────────


def test_a_cron_rule_never_answers_a_past_instant_when_clocks_go_back():
    rule = parse("cron:*/5 * * * *")
    # le 25 octobre 2026, 02:10 heure d'hiver (la seconde fois que la pendule marque 02:10)
    t = instant(datetime(2026, 10, 25, 2, 10, tzinfo=PARIS, fold=1))
    nxt = next_after(rule, t, PARIS)
    assert nxt is not None and nxt > t and nxt - t == 5 * MINUTE
    # et sur toute la nuit du changement, minute après minute
    start = instant(datetime(2026, 10, 25, 0, 0, tzinfo=PARIS))
    for k in range(4 * 60):
        t = start + k * MINUTE
        nxt = next_after(rule, t, PARIS)
        assert nxt is not None and t < nxt <= t + 5 * MINUTE


# ── KER-17 : une envie qui soutient tout le monde ─────────────────────────

POLICY = ArbitrationPolicy(thresholds={"INITIATIVE": 3.0}, max_rates={"INITIATIVE": 0.1})


def _total(n: int, *, any_evidence: float = 2.5, own: float = 0.3) -> float:
    proposals = [("needs", Candidate("INITIATIVE", Anyone.ANY, "envie", any_evidence))]
    proposals += [("social", Candidate("INITIATIVE", f"p{i}", "présent", own)) for i in range(n)]
    return sum(r.hazard for r in pool(proposals, POLICY, lambda view: []))


def test_wanting_to_talk_to_someone_does_not_multiply_with_the_audience():
    # ce qu'ajoute l'envie « ANY » à l'intensité totale, à 1 puis à 8 présents
    one = _total(1) - _total(1, any_evidence=0.0)
    eight = _total(8) - _total(8, any_evidence=0.0)
    assert one > 0 and eight < 1.1 * one, f"une envie de parler, pas huit : {one:.4f} → {eight:.4f}"
    # le contre-exemple : huit raisons propres (une par personne) s'additionnent bien
    own_one = _total(1, any_evidence=0.0, own=2.8)
    own_eight = _total(8, any_evidence=0.0, own=2.8)
    assert own_eight > 6 * own_one


def test_the_any_share_still_picks_targets_in_proportion():
    proposals = [("needs", Candidate("INITIATIVE", Anyone.ANY, "envie", 2.5)),
                 ("social", Candidate("INITIATIVE", "alice", "manque", 1.5)),
                 ("social", Candidate("INITIATIVE", "bob", "présent", 0.1))]
    rows = {r.target: r for r in pool(proposals, POLICY, lambda view: [])}
    assert rows["alice"].hazard > rows["bob"].hazard > 0


# ── les anomalies restent bornées ─────────────────────────────────────────


async def test_anomalies_are_bounded(tmp_path):
    m = make_mind(tmp_path, [COUNTER])
    for i in range(5000):
        m.anomalies.append(f"anomalie {i}")
    assert len(m.anomalies) <= 1000 and m.anomalies[-1] == "anomalie 4999"
