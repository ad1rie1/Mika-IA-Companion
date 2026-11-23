"""Ce qu'on attend d'elle part tout de suite et se suit en direct (ADR 0306).

Une ligne attendue (un candidat ``awaited`` : quelqu'un a demandé ce travail, « Préremplir avec Mika ») prend le taux
des lignes attendues, de l'ordre de la seconde, au lieu de celui de son type (une tâche : une toutes les cinq minutes
en moyenne), et part au premier plan ; tant qu'une de ses ressources est tenue, elle attend sous un veto plutôt que de
perdre une occurrence par seconde, et repart à la fin du bail. Le journal d'avant se relit tel quel. Chaque épisode en
cours dit où il en est (``EpisodeRunner.step_of``) : il réfléchit, ou tel outil tourne.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

from pydantic import BaseModel

from mika.faculties.body import _night
from mika.kernel.arbitration import Candidate, Modulation, Row, RowView, pool, sigmoid
from mika.kernel.builtin import LEASE_ACQUIRED, LEASE_RELEASED
from mika.kernel.clock import US
from mika.kernel.codec import canonical_json
from mika.kernel.episode import EpisodePolicy, Outcome
from mika.kernel.faculty import Faculty
from mika.kernel.registry import ArbitrationPolicy, Registry
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.arbiter import BUSY, HELD, RETRY, RETRY_US, Arbiter
from mika.runtime.pipeline import THINKING, TOOL, EpisodeRequest
from mika.runtime.state import RUNTIME, RuntimeParams
from mika.runtime.tools import ToolResult
from mika.sim.clock import run_virtual
from mika.vocab.episodes import PREEMPTION_GUARD, gave_way
from tests.fixtures.harness import START, build, events_of

POLICY = ArbitrationPolicy(thresholds={"STEP": 8.0}, max_rates={"STEP": 1 / 300}, awaited_rate=1.0)


def no_mod(view):
    return []


def test_an_awaited_row_takes_the_awaited_rate_whatever_its_kind():
    own, awaited = pool([("jouet", Candidate("STEP", "a", "envie", 12.0)),
                         ("jouet", Candidate("STEP", "b", "demande", 12.0, awaited=True))], POLICY, no_mod)[::-1]
    assert not own.awaited and math.isclose(own.hazard, sigmoid(4.0) / 300)
    assert awaited.awaited and math.isclose(awaited.hazard, POLICY.awaited_rate * sigmoid(4.0))
    assert awaited.hazard > 0.9, "en une seconde environ"
    # un veto la retient comme une autre
    vetoed = pool([("jouet", Candidate("STEP", "b", "demande", 12.0, awaited=True))], POLICY,
                  lambda view: [("body", Modulation(veto="nuit"))])
    assert vetoed[0].hazard == 0.0


def test_an_awaited_selection_says_so_and_an_older_journal_still_decodes():
    registry = Registry([RUNTIME])
    old = ('{"draw":0.42,"fired":["STEP:b"],"rows":[{"hazard":0.98,"kind":"STEP",'
           '"parts":[["jouet","demande",12.0]],"score":4.0,"shift":0.0,"target":"b","vetoes":[]}]}')
    _, data = registry.events.decode("kernel.selected", 1, old)
    assert data.rows[0].awaited is False
    [row] = pool([("jouet", Candidate("STEP", "b", "demande", 12.0, awaited=True))], POLICY, no_mod)
    record = row.record()
    assert record.awaited is True
    _, again = registry.events.decode("kernel.selected", 1, canonical_json(
        {"draw": 0.1, "fired": ["STEP:b"], "rows": [record]}))
    assert again.rows[0].awaited is True


def test_her_body_lets_what_someone_waits_for_through_even_asleep():
    """Le corps ne la retient pas : ce n'est pas une envie à elle, et on l'attend maintenant (le cadre n'est même pas
    lu)."""
    assert _night(None, None, RowView("TASK", "task:teams:t1", 12.0, ("draft",), 12.0, awaited=True)).veto is None


# ── Le noyau entier, sur un jouet ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Nothing:
    pass


class NoArgs(BaseModel):
    pass


ASKED = {"awaited": True, "resources": frozenset(), "on": True, "fail": False, "latency": 0.0}
WAITER = Faculty("jouet", state=Nothing, init=lambda p: Nothing())
SEEN: dict[str, list] = {"tool": [], "model": []}


@WAITER.propose(kinds=["STEP"], reasons={"demande": (0.0, 14.0)})
def _asked(s, frame):
    if not ASKED["on"]:
        return []
    return [Candidate("STEP", "task:jouet:1", "demande", 12.0, resources=ASKED["resources"],
                      awaited=ASKED["awaited"])]


@WAITER.tool("lire_le_fil", description="Relit le fil.", label="Relire le fil", args=NoArgs, bundle="atelier",
             episodes=["STEP"])
async def _read(args: NoArgs, ctx) -> ToolResult:
    SEEN["tool"].append(KERNEL[0].runner.step_of(ctx.episode_id))
    return ToolResult(content="le fil")


KERNEL: list = []
POLICIES = {"STEP": EpisodePolicy(kind="STEP", role="step", priority=1, lane="background", delivered=False,
                                  visible=False, tool_bundles=frozenset({"atelier"}), deadline_s=60.0)}


def working(req: LLMRequest) -> LLMResponse:
    kernel = KERNEL[0]
    if ASKED["fail"]:
        raise RuntimeError("le fournisseur ne répond pas")
    for eid in kernel.mind.root.slices[RUNTIME.name].open:
        SEEN["model"].append(kernel.runner.step_of(eid))
    if not any(m.role == "tool" for m in req.messages):
        return LLMResponse("", (ToolCall("c1", "lire_le_fil", {}),), stop="tool_use")
    return LLMResponse("fini")


def _run(tmp_path, *, awaited: bool, seconds: float, resources=frozenset(), during=None, on: bool = True,
         fail: bool = False, latency: float = 0.0):
    ASKED.update(awaited=awaited, resources=resources, on=on, fail=fail)
    SEEN.update(tool=[], model=[])
    kernel, clock, llm = build(tmp_path, [WAITER], respond=working, policies=POLICIES, arbitration=POLICY,
                               latency=latency)
    KERNEL[:] = [kernel]

    async def main():
        await kernel.start()
        try:
            got = await during(kernel) if during is not None else None
            await asyncio.sleep(seconds)
            return got
        finally:
            await kernel.stop()

    got = run_virtual(clock, main)
    started = [e for e in events_of(kernel, "episode.started")]
    return started, llm.calls, got


def test_what_someone_waits_for_starts_within_seconds_in_the_foreground(tmp_path):
    started, calls, _ = _run(tmp_path / "attendue", awaited=True, seconds=10)
    assert started and started[0].at - START < 5 * US, "pas au tirage des tâches : en quelques secondes"
    assert calls and {c.priority for c in calls} == {0}, "au premier plan chez le fournisseur"
    # ce qu'elle fait d'elle-même garde son tirage et son rang
    started, calls, _ = _run(tmp_path / "elle", awaited=False, seconds=4 * 3600)
    assert started and {c.priority for c in calls} == {1}
    gaps = [(b.at - a.at) / US for a, b in zip(started, started[1:], strict=False)]
    assert sum(gaps) / len(gaps) > 60, "une toutes les quelques minutes, pas une par seconde"


def test_each_running_episode_says_where_it_is(tmp_path):
    _run(tmp_path, awaited=True, seconds=3)
    thinking, tool = SEEN["model"][0], SEEN["tool"][0]
    assert thinking.phase == THINKING and not thinking.tool
    assert tool.phase == TOOL and tool.tool == "lire_le_fil" and tool.label == "Relire le fil"
    assert tool.started == thinking.started and tool.since >= thinking.since
    # le modèle rappelé après l'outil : elle réfléchit de nouveau, depuis la fin de l'outil
    after = SEEN["model"][1]
    assert after.phase == THINKING and after.since >= tool.since and after.started == thinking.started


def test_an_awaited_row_waits_for_a_held_resource_under_a_veto_then_goes(tmp_path):
    async def hold(kernel):
        await kernel.mind.append([LEASE_ACQUIRED.draft(resource="fil:1", holder="autre", until=START + 3600 * US)],
                                 emitter="kernel", correlation="autre")
        await asyncio.sleep(30)
        rows = kernel.arbiter.rows(kernel.mind.frame(), record=False)
        selected = len(events_of(kernel, "kernel.selected"))
        await kernel.mind.append([LEASE_RELEASED.draft(resource="fil:1", holder="autre")], emitter="kernel",
                                 correlation="autre")
        return rows, selected

    started, _calls, (rows, selected) = _run(tmp_path, awaited=True, seconds=5, resources=frozenset({"fil:1"}),
                                             during=hold)
    [row] = rows
    assert row.vetoes == (("kernel", BUSY),) and row.hazard == 0.0
    assert selected == 0, "pas une occurrence perdue par seconde pendant le bail"
    assert started, "la fin du bail la relance"


def test_neither_her_work_setting_nor_the_quota_hold_hold_back_what_someone_waits_for(tmp_path):
    """« Se mettre au travail » (ADR 0149) décale ses tâches à elle, pas ce qu'on attend d'elle ; la retenue du quota
    (ADR 0127) ne la retient pas : elle partira au premier plan, que le fournisseur laisse toujours passer."""
    def table(kernel, awaited: bool):
        ASKED["awaited"] = awaited
        arbiter = Arbiter(lambda: kernel.mind.registry, lambda *a: None, held=lambda kind: "quota réservé")
        [row] = arbiter.rows(kernel.mind.frame(), record=False)
        return row

    async def during(kernel):
        await kernel.set_params(RUNTIME.name, RuntimeParams(work_shift=-3.0))
        return table(kernel, True), table(kernel, False)

    _started, _calls, (awaited, own) = _run(tmp_path, awaited=True, seconds=0, on=True, during=during)
    assert awaited.shifts == () and awaited.vetoes == () and awaited.hazard > 0.9
    assert own.shifts == ((RUNTIME.name, -3.0),) and own.vetoes == (("kernel", HELD),) and own.hazard == 0.0


def test_a_failed_try_waits_a_minute_before_the_next(tmp_path):
    """Une panne passagère ne brûle pas ses essais en deux secondes : après un essai qui a échoué, la ligne attendue
    patiente une minute (``RETRY``), puis repart d'elle-même — sans qu'aucun événement ne la réveille."""
    async def during(kernel):
        await asyncio.sleep(30)
        return kernel.arbiter.rows(kernel.mind.frame(), record=False)

    started, _calls, rows = _run(tmp_path, awaited=True, seconds=60, fail=True, during=during)
    ended = events_of(KERNEL[0], "episode.ended")
    assert [e.data.outcome for e in ended][:2] == ["failed", "failed"]
    first, second = started[0], started[1]
    assert first.at - START < 5 * US
    assert RETRY_US <= second.at - ended[0].at < RETRY_US + 5 * US, "une minute après l'échec, pas une seconde"
    [row] = rows
    assert row.vetoes == (("kernel", RETRY),) and row.hazard == 0.0


def test_what_someone_waits_for_supplants_her_own_task_on_the_same_resource(tmp_path):
    """Sa tâche d'elle-même tient la ressource (la même conversation, la même boîte) : ce qu'on attend la supplante
    au lieu d'attendre sa fin, et la tâche supplantée l'est par le premier plan (``PREEMPTION_GUARD`` : elle ne
    compte pas d'essai)."""
    own = Row("STEP", "task:jouet:2", (("jouet", "envie", 9.0),), 0.0, (), 1.0, 0.003, resources=frozenset({"fil:1"}))

    async def during(kernel):
        pending = kernel.lanes.submit(EpisodeRequest(kind="STEP", target="task:jouet:2", selected=own, priority=1))
        await asyncio.sleep(2)  # sa tâche a pris le bail et attend le modèle
        ASKED["on"] = True  # en vrai, la demande est un événement, qui fait relire la table
        kernel.arbiter.invalidate()
        kernel.scheduler.poke()
        await asyncio.sleep(20)
        return await pending

    started, _calls, report = _run(tmp_path, awaited=True, seconds=1, on=False, resources=frozenset({"fil:1"}),
                                   during=during, latency=60.0)
    assert report.outcome is Outcome.SUPERSEDED
    ended = {e.data.target: e.data for e in events_of(KERNEL[0], "episode.ended")}
    assert ended["task:jouet:2"].guard == PREEMPTION_GUARD
    asked = [e for e in started if e.data.target == "task:jouet:1"]
    assert asked and asked[0].at - START < 10 * US, "elle n'attend pas la fin de sa tâche (une minute)"


def test_a_task_that_gave_way_did_not_try():
    assert gave_way("preempted") and gave_way("superseded", PREEMPTION_GUARD)
    assert not gave_way("superseded", "baux") and not gave_way("failed") and not gave_way("done")
