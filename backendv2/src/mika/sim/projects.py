"""Le scénario des projets (ADR 0031).

- **S16** un projet confié : sa propriétaire le lui confie en conversation ; elle
  écrit et teste un programme dans l'atelier du projet (isolé), l'objectif
  aboutit avec une preuve, un commit par exécution qui a changé quelque chose,
  et elle le raconte à qui le lui a confié.
- **S23** elle se fabrique un outil (ADR 0104) : sa propriétaire lui dit qu'il
  serait bien qu'elle suive un cours ; elle ouvre un projet à elle avec la Forge,
  y écrit une app et l'essaie (la preuve) ; l'app relève le cours chaque heure et
  ce qu'elle trouve concerne Adrien ; le site tombe, l'app aussi, et son projet
  ouvre de lui-même un objectif « Réparer » qu'une exécution mène au bout ; et
  quand Adrien demande des nouvelles, elle lit la page de son app.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from mika.contracts import forge as forge_c
from mika.contracts import projects as projects_c
from mika.kernel.clock import HOUR, MINUTE
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


WATCH = "ce serait bien que tu suives le cours de bourse, moi je n'ai jamais le temps de le regarder"


async def s23(driver: Driver, rng: RngTree, res: Result) -> None:
    driver.operators.add("user_1")
    day0 = at_paris(2026, 9, 28, 0, 0)
    await until(driver, day0 + 9 * HOUR + 30 * MINUTE)
    await driver.connect("user_1", "Adrien")
    await driver.say("user_1", WATCH)
    await until(driver, day0 + 11 * HOUR)
    built = driver.read_events()
    driver.web.down = True  # le site tombe : l'app fragile tombe avec lui
    await until(driver, day0 + 17 * HOUR)
    driver.web.down = False
    await until(driver, day0 + 18 * HOUR)
    await driver.say("user_1", "alors, le cours ?")
    events = driver.read_events()
    isolated = shutil.which("bwrap") is not None
    created = [e for e in _of(events, projects_c.PROJECT_CREATED.name) if e.data.authority == projects_c.SELF]
    pid = created[0].seq if created else 0
    apps = {a.name: a for a in driver.kernel.mind.frame().get(forge_c.APPS)} if driver.kernel else {}
    closed = [e for e in _of(events, projects_c.OBJECTIVE_CLOSED.name) if e.data.project == pid]
    reports = [e for e in _of(events, projects_c.RUN_REPORTED.name) if e.data.project == pid]
    signals = [s for s in _of(events, forge_c.SIGNALED.name) if s.data.app == "cours"]
    broken = [s for s in signals if s.data.kind == forge_c.APP_BROKEN]
    found = [s for s in signals if s.data.kind == forge_c.APP_SIGNAL]
    peeked = [m.content for c in driver.llm.calls if c.role == "reply"  # type: ignore[attr-defined]
              for m in c.messages if m.role == "tool" and m.name == "cours_pages"]
    built_apps = [e for e in _of(built, "forge.written") if e.data.app == "cours"]
    res.metrics.update({"projets à elle": len(created), "objectifs clos": len(closed), "signaux": len(signals),
                        "appels web": len(driver.web.calls)})
    res.checks += [
        expect.invariant("une suggestion de sa propriétaire devient un projet à elle, avec la Forge",
                         len(created) == 1 and "forge" in created[0].data.bundles,
                         "elle s'en donne les moyens plutôt que de dire qu'elle n'a pas accès"),
        expect.invariant("l'app est écrite dans son projet, et essayée avant d'être dite faite", not isolated or (
            bool(built_apps) and apps.get("cours") is not None and apps["cours"].project == pid
            and any(r.data.proof == "outil" and r.data.verdict == projects_c.DONE for r in reports)),
            "écrire ne suffit pas : l'essai réussi est la preuve", f"{[r.data.proof for r in reports]}"),
        expect.invariant("ce que trouve l'app concerne qui le projet concerne", not isolated or (
            bool(found) and found[0].data.about == ("user_1",)), "un signal adressé à Adrien, au niveau du projet",
            f"{[s.data.about for s in found]}"),
        expect.invariant("le site tombe : l'app tombe, son projet la répare", not isolated or (
            bool(broken) and any("Réparer" in (r.data.summary.text or "") or r.data.proof == "outil"
                                 for r in reports[1:])
            and len([c for c in closed if c.data.status == projects_c.DONE]) >= 2
            and not apps["cours"].broken), "un objectif « Réparer », une exécution, une app qui tourne de nouveau",
            f"{len(broken)} panne(s), {[c.data.status for c in closed]}"),
        expect.invariant("quand Adrien demande, elle lit la page de son app", not isolated or (
            bool(peeked) and "cours" in peeked[-1]), "un outil à elle, en conversation, sans promotion",
            f"{peeked[-1:] if peeked else peeked}"),
    ]


PROJECTS: tuple[Plan, ...] = (
    Plan("S16 un projet confié", s16, persona_llm, at_paris(2026, 9, 28, 14, 0)),
    Plan("S23 elle se fabrique un outil", s23, persona_llm, at_paris(2026, 9, 28, 9, 0)),
)
