"""Un quota retenu n'est pas une panne (ADR 0127) : l'arbitre ne lance pas un épisode que le fournisseur de son rôle
refuserait d'avance (veto ``held``), un épisode refusé quand même se règle en ``preempted`` — un but ne le compte
pas —, et la santé le dit."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mika.kernel.arbitration import Candidate
from mika.kernel.episode import Outcome
from mika.kernel.faculty import Faculty
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import Held, LLMRequest, LLMResponse
from mika.runtime import health
from mika.runtime.pipeline import _failed
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build, events_of


@dataclass(frozen=True, slots=True)
class Nothing:
    pass


WORKER = Faculty("worker", state=Nothing, init=lambda p: Nothing())


@WORKER.propose(kinds=["STEP"], reasons={"envie": (-5.0, 20.0)})
def _propose(s, frame):
    return [Candidate("STEP", "goal:1", "envie", 12.0)]


POLICY = ArbitrationPolicy(thresholds={"STEP": 0.5}, max_rates={"STEP": 1 / 60})
HELD = "abonnement entamé à 85% (seven_day)"


def _hour(tmp_path, *, holds=None, respond=None):
    kernel, clock, llm = build(tmp_path, [WORKER], arbitration=POLICY,
                               **({"respond": respond} if respond is not None else {}))
    if holds is not None:
        llm.holds = holds

    async def main():
        await kernel.start()
        await asyncio.sleep(3600)
        ended = [e.data for e in events_of(kernel, "episode.ended")]
        rows = list(kernel.arbiter.last_rows)
        report = health.report(kernel)
        await kernel.stop()
        return ended, rows, report

    return run_virtual(clock, main)


def test_the_arbiter_does_not_start_a_background_episode_its_provider_would_refuse(tmp_path):
    ended, rows, report = _hour(tmp_path, holds=lambda priority: HELD if priority else "")
    assert ended == []  # aucune séance lancée pour finir en zéro seconde
    assert rows and all(("kernel", "held") in r.vetoes for r in rows)
    llm = next(c for c in report.checks if c.name == "llm")
    assert llm.state == health.DEGRADED and HELD in llm.summary


def test_without_a_hold_the_same_line_runs(tmp_path):
    ended, rows, report = _hour(tmp_path, holds=lambda priority: "")
    assert ended and all(not r.vetoes for r in rows)
    assert next(c for c in report.checks if c.name == "llm").state == health.OK


def test_an_episode_refused_anyway_is_preempted_not_failed(tmp_path):
    """Le refus arrive quand même (le premier appel après un redémarrage, avant tout relevé) : l'épisode n'a rien
    tenté — ``preempted``, que les buts ne comptent pas comme une panne."""
    def refuse(req: LLMRequest) -> LLMResponse:
        raise Held(HELD)

    ended, _rows, _report = _hour(tmp_path, respond=refuse)
    assert ended and {d.outcome for d in ended} == {"preempted"}
    assert all(d.detail.startswith("Held: ") for d in ended)


def test_only_a_held_refusal_is_a_preemption():
    assert _failed(Held(HELD)) is Outcome.PREEMPTED
    assert _failed(RuntimeError("panne")) is Outcome.FAILED
