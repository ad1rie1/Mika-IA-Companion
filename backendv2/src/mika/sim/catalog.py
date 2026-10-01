"""Le catalogue des scénarios, et la voie rapide."""

from __future__ import annotations

from pathlib import Path

from mika.sim.goals import GOALS
from mika.sim.inner import INNER
from mika.sim.lane import Plan, Result, run_plan
from mika.sim.lane import run_lane as _run_lane
from mika.sim.others import OTHERS
from mika.sim.projects import PROJECTS
from mika.sim.scenarios import BASE
from mika.sim.senses import SENSES
from mika.sim.world import Composition

QUICK: tuple[Plan, ...] = BASE + OTHERS + INNER + GOALS + PROJECTS + SENSES


def run_lane(composition: Composition, root: Path, plans: tuple[Plan, ...] = QUICK) -> list[Result]:
    return _run_lane(composition, root, plans)


__all__ = ["QUICK", "Plan", "Result", "run_lane", "run_plan"]
