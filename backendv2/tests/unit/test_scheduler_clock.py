"""Preuve M0 — horloge : un saut de +8 h donne au plus une exécution de
rattrapage (avec ``missed``), sans rafale ; la nuit du passage à l'heure
d'hiver, la tâche nocturne tourne une fois et date correctement sa nuit. Et
l'échéance que l'ordonnanceur retient (``due``, ce que lit la console) compte
le recul après un échec et la garde des passages à vide, et passe à
l'occurrence suivante dès qu'une échéance en retard est sautée. Chaque
processus se réévalue à son propre quantum, après un ajout ou après son
passage (ADR 0223)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from zoneinfo import ZoneInfo

from mika.kernel.builtin import KernelParams
from mika.kernel.clock import HOUR, MINUTE, instant, local, local_date_of_night, next_local
from mika.kernel.events import Origin, Payload
from mika.kernel.faculty import CatchUp, Faculty
from mika.runtime.scheduler import IDLE_GUARD_US
from mika.sim.clock import SimClock, run_virtual
from tests.fixtures.harness import build, events_of

PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True, slots=True)
class TickState:
    ticks: int = 0


class Ticked(Payload):
    missed: bool


TICKER = Faculty("ticker", state=TickState, init=lambda p: TickState())
TICKED = TICKER.event("ticked", Ticked)


@TICKER.reducer(TICKED)
def _ticked(s: TickState, e, cx) -> TickState:
    return replace(s, ticks=s.ticks + 1)


@TICKER.process("tic", max_quantum_s=300)
class Tic:
    def next_due(self, state, frame, last_run):
        return frame.now if last_run is None else last_run + 10 * MINUTE

    async def run(self, ctx):
        await ctx.emit(TICKED.draft(missed=ctx.missed is not None))


@dataclass(frozen=True, slots=True)
class DiaryState:
    last_at: int = 0


class Written(Payload):
    covers: str
    local_time: str


DIARY = Faculty("diary", state=DiaryState, init=lambda p: DiaryState())
WRITTEN = DIARY.event("written", Written)


@DIARY.reducer(WRITTEN)
def _written(s: DiaryState, e, cx) -> DiaryState:
    return replace(s, last_at=e.at)


@DIARY.process("journal-de-nuit", max_quantum_s=3600)
class NightJournal:
    def next_due(self, state, frame, last_run):
        tz = frame.env.tz_of(frame.root)
        after = state.last_at or (frame.now - 1)
        return next_local(after, 3, 30, tz)

    async def run(self, ctx):
        tz = ctx.frame.env.tz_of(ctx.frame.root)
        now = ctx.now
        await ctx.emit(WRITTEN.draft(covers=str(local_date_of_night(now, tz)),
                                     local_time=local(now, tz).strftime("%H:%M")))


def test_clock_jump_gives_one_catch_up_run(tmp_path):
    kernel, clock, _ = build(tmp_path, [TICKER])

    async def main():
        await kernel.start()
        await asyncio.sleep(30 * 60 + 1)
        before = kernel.mind.root.slices["ticker"].ticks
        clock.advance_to(clock.now() + 8 * HOUR)  # la machine a dormi huit heures
        kernel.scheduler.poke()
        await asyncio.sleep(60)
        after = kernel.mind.root.slices["ticker"].ticks
        await asyncio.sleep(11 * 60)
        later = kernel.mind.root.slices["ticker"].ticks
        ticks = [e.data.missed for e in events_of(kernel, "ticker.ticked")]
        await kernel.stop()
        return before, after, later, ticks

    before, after, later, ticks = run_virtual(kernel.deps.clock, main)
    assert before == 4
    assert after == before + 1, "une seule exécution de rattrapage"
    assert ticks[before] is True, "l'exécution de rattrapage le sait (missed)"
    assert later == after + 1 and ticks[-1] is False


def test_dst_fall_back_night(tmp_path):
    start = instant(datetime(2026, 10, 24, 12, 0, tzinfo=PARIS))
    kernel, clock, _ = build(tmp_path, [DIARY], start=start)

    async def main():
        await kernel.start()
        await kernel.set_params("kernel", KernelParams(tz="Europe/Paris"))
        kernel.scheduler.poke()
        await asyncio.sleep(3 * 24 * 3600)
        written = [(e.data.covers, e.data.local_time) for e in events_of(kernel, "diary.written")]
        await kernel.stop()
        return written

    written = run_virtual(kernel.deps.clock, main)
    assert written == [("2026-10-24", "03:30"), ("2026-10-25", "03:30"), ("2026-10-26", "03:30")]


def test_the_virtual_loop_keeps_going_past_194_days():
    """Au-delà de 2²⁴ s de temps de boucle (194,18 jours), un minuteur échu n'était plus jugé prêt : la boucle
    tournait à vide pour toujours (audit « vie longue » du 2026-10-03). Une année de virtuel va au bout."""
    async def main():
        loop = asyncio.get_running_loop()
        while loop.time() < 365 * 86400:
            await asyncio.sleep(6 * 3600)
        await asyncio.sleep(1.0)
        return loop.time()

    assert run_virtual(SimClock(1_791_000_000 * 10**6), main) >= 365 * 86400


# ── L'échéance retenue (``Scheduler.due``) ───────────────────────────────
#
# Seul l'ordonnanceur appelle ``next_due`` : une page lit l'échéance qu'il a retenue. Chaque jouet se borne lui-même
# (``LIMIT`` passages) : une garde cassée fait échouer le test, elle ne le fait pas tourner sans fin.

LIMIT = 50


@dataclass(frozen=True, slots=True)
class Nothing:
    n: int = 0


class Called(Payload):
    n: int = 0


class _Eager:
    """Se croit dû sur-le-champ à chaque passe ; garde l'instant de chacun de ses passages."""

    def __init__(self) -> None:
        self.runs: list[int] = []

    def next_due(self, state, frame, last_run):
        return frame.now if len(self.runs) < LIMIT else None


STUMBLING = Faculty("stumbling", state=Nothing, init=lambda p: Nothing())


@STUMBLING.process("trebuche", wake_on=[])
class Stumbles(_Eager):
    async def run(self, ctx):
        self.runs.append(ctx.now)
        raise RuntimeError("port indisponible")


IDLING = Faculty("idling", state=Nothing, init=lambda p: Nothing())


@IDLING.process("a_vide", wake_on=[])
class Idles(_Eager):
    async def run(self, ctx):
        self.runs.append(ctx.now)  # n'écrit rien


WAITING = Faculty("waiting", state=Nothing, init=lambda p: Nothing())
CALLED = WAITING.event("called", Called)


@WAITING.process("attend", wake_on=[CALLED])
class Waits(_Eager):
    def next_due(self, state, frame, last_run):
        return frame.now if last_run is None else None  # une fois, puis il attend qu'on l'appelle

    async def run(self, ctx):
        self.runs.append(ctx.now)


SKIPPING = Faculty("skipping", state=Nothing, init=lambda p: Nothing())


@SKIPPING.process("saute", wake_on=[], catch_up=CatchUp.SKIP, max_quantum_s=60)
class Skips:
    """Toutes les dix minutes ; au départ, l'occurrence d'il y a une heure, manquée (la machine dormait)."""

    def __init__(self) -> None:
        self.runs: list[int] = []

    def next_due(self, state, frame, last_run):
        return frame.now - HOUR if last_run is None else last_run + 10 * MINUTE

    async def run(self, ctx):
        self.runs.append(ctx.now)


DRIFTING = Faculty("drifting", state=Nothing, init=lambda p: Nothing())


@DRIFTING.process("recule", wake_on=[], catch_up=CatchUp.SKIP, max_quantum_s=60)
class Drifts:
    """Sans lire ``last_run``, redonne à chaque évaluation un retard neuf (une heure avant l'instant, un peu plus
    tard que le précédent) : sauté chaque fois. Se borne à ``LIMIT`` évaluations."""

    def __init__(self) -> None:
        self.asked = 0

    def next_due(self, state, frame, last_run):
        self.asked += 1
        return frame.now - HOUR + self.asked if self.asked < LIMIT else None

    async def run(self, ctx):
        pass


def _kept(tmp_path, faculty, name, *pauses_s):
    """Fait vivre ``faculty`` ; après chaque pause, relève ce que l'ordonnanceur a retenu pour ``name`` : son
    échéance, la fin de son recul et l'heure. Rend aussi son instance (ses passages)."""
    kernel, clock, _ = build(tmp_path, [faculty])
    sched = kernel.scheduler

    async def main():
        await kernel.start()
        seen = []
        for pause in pauses_s:
            await asyncio.sleep(pause)
            seen.append((sched.due(name), sched.not_before.get(name), clock.now()))
        await kernel.stop()
        return seen

    seen = run_virtual(clock, main)
    return sched.instances[name], seen


def test_a_failing_process_is_due_at_the_end_of_its_back_off(tmp_path):
    """Un passage qui lève : la passe suivante retient la fin du recul, pas « maintenant » (la page disait « dès
    que possible » pendant qu'il attendait jusqu'à une heure)."""
    process, [(due, floor, now)] = _kept(tmp_path, STUMBLING, "trebuche", 1)
    assert len(process.runs) == 1
    assert floor is not None and floor > now
    assert due == floor


def test_an_idle_process_due_again_waits_for_the_end_of_the_guard(tmp_path):
    """Un passage qui n'a rien écrit et se redit dû aussitôt : l'échéance retenue est la fin de la garde (son
    passage plus ``IDLE_GUARD_US``, doublé au passage à vide suivant), pas l'instant présent."""
    process, [(first, _, now), (second, _, later)] = _kept(tmp_path, IDLING, "a_vide", 1, 30)
    assert len(process.runs) == 2
    assert first == process.runs[0] + IDLE_GUARD_US and first > now
    assert second == process.runs[1] + 2 * IDLE_GUARD_US and second > later


def test_a_process_waiting_for_an_event_has_no_deadline(tmp_path):
    """Un processus qui a tourné et attend un événement : ``None``. La passe d'après son passage l'a relu (un
    processus en cours garde l'échéance de la passe qui l'a lancé, ici l'instant de son départ)."""
    process, [(due, _, _)] = _kept(tmp_path, WAITING, "attend", 1)
    assert len(process.runs) == 1
    assert due is None


def test_a_skipped_deadline_gives_way_at_once_to_the_next_one(tmp_path):
    """Une échéance en retard sautée (``CatchUp.SKIP``) : la boucle refait aussitôt une passe, qui retient
    l'occurrence suivante et en fait le réveil du processus. Avant, ``due`` gardait l'instant sauté tant qu'aucun
    autre minuteur ni aucun événement ne relançait de passe (Processus disait « dès que possible », Échéances
    rangeait une heure passée sous « Dans l'heure »)."""
    process, [(due, _, now), (_, _, later)] = _kept(tmp_path, SKIPPING, "saute", 1, 10 * 60)
    assert due is not None and due > now
    assert process.runs == [due] and later > due, "l'occurrence manquée n'est pas rattrapée ; la suivante l'est"


def test_a_deadline_skipped_again_and_again_does_not_spin_the_loop(tmp_path):
    """Le saut ne redemande qu'une passe : un ``next_due`` qui redonne sans fin un retard neuf, sauté à chaque
    passe, ne relance pas la boucle aussitôt chaque fois (elle tournerait à vide, l'horloge réelle avançant
    toujours d'un peu entre deux passes)."""
    process, _ = _kept(tmp_path, DRIFTING, "recule", 1)
    assert process.asked < 10


# ── Chaque processus à son quantum (ADR 0223) ────────────────────────────
#
# L'ordonnanceur garde l'échéance de chaque processus : il ne la redemande qu'après un ajout, après un passage du
# processus, ou à cette échéance, au plus tard à son quantum — jamais au rythme du plus pressé.


class _Counted:
    """N'attend rien (aucun événement, rien de prévu) ; compte les fois où on lui demande son échéance."""

    def __init__(self) -> None:
        self.asked = 0

    def next_due(self, state, frame, last_run):
        self.asked += 1
        return None

    async def run(self, ctx):
        pass


QUIET = Faculty("quiet", state=Nothing, init=lambda p: Nothing())
NOTED = QUIET.event("noted", Called)


@QUIET.process("presse", wake_on=[], max_quantum_s=60)
class Hurried(_Counted):
    pass


@QUIET.process("patient", wake_on=[], max_quantum_s=300)
class Patient(_Counted):
    pass


def test_each_process_is_asked_again_at_its_own_quantum(tmp_path):
    """Deux processus sans événement, l'un au quantum d'une minute, l'autre de cinq : sur une heure, le second n'est
    redemandé qu'une douzaine de fois. Avant, chaque passe redemandait tout le monde, et le plus pressé en imposait
    une par minute : une soixantaine (la voie rapide passait 35 s sur 45 de S05 dans l'ordonnanceur)."""
    kernel, clock, _ = build(tmp_path, [QUIET])
    sched = kernel.scheduler

    async def main():
        await kernel.start()
        await asyncio.sleep(3600)
        await kernel.stop()

    run_virtual(clock, main)
    hurried, patient = sched.instances["presse"], sched.instances["patient"]
    assert 11 <= patient.asked <= 14, patient.asked
    assert 57 <= hurried.asked <= 63, hurried.asked


def test_an_append_asks_every_process_again(tmp_path):
    """Un ajout au journal fait redemander son échéance à chacun, à la passe qui suit, bien avant son quantum."""
    kernel, clock, _ = build(tmp_path, [QUIET])
    sched = kernel.scheduler

    async def main():
        await kernel.start()
        await asyncio.sleep(90)  # entre deux quanta du plus pressé (60 s, 120 s) et avant celui de l'autre (300 s)
        before = sched.instances["presse"].asked, sched.instances["patient"].asked
        await kernel.mind.append([NOTED.draft(n=1)], emitter="quiet", correlation="t", origin=Origin.KERNEL)
        await asyncio.sleep(1)
        after = sched.instances["presse"].asked, sched.instances["patient"].asked
        await kernel.stop()
        return before, after

    before, after = run_virtual(clock, main)
    assert after == (before[0] + 1, before[1] + 1)


INSTEP = Faculty("instep", state=Nothing, init=lambda p: Nothing())


@INSTEP.process("pas", wake_on=[], max_quantum_s=3600)
class Steps:
    """Son échéance tient dans son état en mémoire, que seul son passage change : dû au départ, puis sept minutes
    après chaque passage. Il ne l'écrit pas au journal : seul son passage dit qu'elle a changé."""

    def __init__(self) -> None:
        self.runs: list[int] = []
        self.next_at: int | None = None

    def next_due(self, state, frame, last_run):
        if len(self.runs) >= 3:
            return None
        return frame.now if self.next_at is None else self.next_at

    async def run(self, ctx):
        self.runs.append(ctx.now)
        self.next_at = ctx.now + 7 * MINUTE


def test_a_process_that_ran_is_asked_again_at_the_next_pass(tmp_path):
    """Un processus qui a tourné redonne son échéance à la passe qui suit son passage : la nouvelle, sept minutes
    plus tard, et non celle d'avant, gardée jusqu'à son quantum d'une heure."""
    process, _ = _kept(tmp_path, INSTEP, "pas", 20 * 60)
    start = process.runs[0]
    assert process.runs == [start, start + 7 * MINUTE, start + 14 * MINUTE]


RELATIVE = Faculty("relative", state=Nothing, init=lambda p: Nothing())


@RELATIVE.process("releve", wake_on=[], max_quantum_s=3600)
class Reads:
    """Un relevé « dans un quart d'heure » (``frame.now + 15 min``), sans lire ``last_run``."""

    def __init__(self) -> None:
        self.runs: list[int] = []

    def next_due(self, state, frame, last_run):
        return frame.now + 15 * MINUTE

    async def run(self, ctx):
        self.runs.append(ctx.now)


def test_a_relative_deadline_gives_a_run_every_quarter_of_an_hour(tmp_path):
    """Une échéance relative est un relevé à cette cadence : un passage tous les quarts d'heure. Avant, chaque passe
    la redemandait et elle reculait d'autant : elle n'arrivait jamais."""
    kernel, clock, _ = build(tmp_path, [RELATIVE])

    async def main():
        await kernel.start()
        start = clock.now()
        await asyncio.sleep(3600 + 30)
        await kernel.stop()
        return start

    start = run_virtual(clock, main)
    runs = kernel.scheduler.instances["releve"].runs
    assert len(runs) == 4, runs
    assert [b - a for a, b in zip([start, *runs], runs, strict=False)] == [15 * MINUTE] * 4
