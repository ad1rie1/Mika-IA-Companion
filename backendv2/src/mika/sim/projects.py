"""Le scénario des projets (ADR 0031).

- **S16** un projet confié : sa propriétaire le lui confie en conversation ; elle
  écrit et teste un programme dans l'atelier du projet (isolé), l'objectif
  aboutit avec une preuve, un commit par exécution qui a changé quelque chose,
  et elle le raconte à qui le lui a confié.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from mika.contracts import projects as projects_c
from mika.kernel.clock import HOUR
from mika.sim import expect
from mika.sim.inner import until
from mika.sim.lane import Plan, Result, at_paris, persona_llm
from mika.sim.rng import RngTree
from mika.sim.world import Driver


def _of(events: list[Any], name: str) -> list[Any]:
    return [e for e in events if e.type.name == name]


def _shares(driver: Driver) -> list[tuple[str, str]]:
    return [(c.meta.get("target"), c.messages[-1].content) for c in driver.llm.calls  # type: ignore[attr-defined]
            if c.role == "initiative" and "MENÉ À BOUT" in c.messages[-1].content]


CONFIDE = ("je te confie un projet : Un script de bonjour. Écrire bonjour.py avec une fonction bonjour(nom), "
           "et la tester.")


async def s16(driver: Driver, rng: RngTree, res: Result) -> None:
    driver.operators.add("user_1")
    day0 = at_paris(2026, 9, 28, 0, 0)
    await until(driver, day0 + 15 * HOUR)
    await driver.connect("user_1", "Adrien")
    await driver.say("user_1", CONFIDE)
    await until(driver, day0 + 17 * HOUR)
    events = driver.read_events()
    created = _of(events, projects_c.PROJECT_CREATED.name)
    closed = [e for e in _of(events, projects_c.OBJECTIVE_CLOSED.name) if created and e.data.project == created[0].seq]
    ran = [m.content for c in driver.llm.calls if c.role == "project"  # type: ignore[attr-defined]
           for m in c.messages if m.role == "tool" and "python3" in m.content]
    isolated = shutil.which("bwrap") is not None
    log = ""
    if created:
        folder = driver.root / "ateliers" / f"projet-{created[0].seq}"
        if (folder / ".git").exists():
            log = subprocess.run(["git", "-C", str(folder), "log", "--format=%s"], capture_output=True,
                                 text=True, check=False).stdout
    res.metrics.update({"projets": len(created), "commits": log.splitlines(), "isolé": isolated})
    res.checks += [
        expect.invariant("un projet confié par sa propriétaire", len(created) == 1
                         and created[0].data.authority == projects_c.USER, "elle accepte le cadre qu'on lui confie"),
        expect.invariant("écrit et testé dans l'atelier", not isolated or (
            bool(closed) and closed[0].data.status == projects_c.DONE and any("code 0" in r for r in ran)),
            "le test a réellement tourné, isolé, avant qu'elle ne dise fait", f"{ran[-1:] if ran else ran}"),
        expect.invariant("un commit par exécution qui a changé quelque chose", not isolated or (
            len(log.splitlines()) == 2 and log.splitlines()[-1] == "atelier ouvert"),
            "l'amorce, puis le travail", f"{log.splitlines()}"),
        expect.invariant("et elle le raconte à qui le lui a confié", not isolated or any(
            who == "user_1" for who, _ in _shares(driver)), "un travail confié se rend"),
    ]


PROJECTS: tuple[Plan, ...] = (
    Plan("S16 un projet confié", s16, persona_llm, at_paris(2026, 9, 28, 14, 0)),
)
