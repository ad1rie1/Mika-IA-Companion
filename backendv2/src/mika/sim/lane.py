"""Le socle d'exécution des scénarios : résultats, plans, une course, une voie.

Un scénario pilote le vrai noyau (même composition que le serveur) dans un
monde simulé, puis ajoute des vérifications ; ``run_plan`` y ajoute les
invariants communs (aucune tranche corrompue, jamais répondu deux fois).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.clock import US, instant
from mika.sim import expect
from mika.sim.clock import SimClock, run_virtual
from mika.sim.expect import Check
from mika.sim.llm.persona import PersonaSimLLM
from mika.sim.metrics import log_metrics
from mika.sim.rng import RngTree
from mika.sim.world import Composition, Driver
from mika.vocab import affect as A

PARIS = ZoneInfo("Europe/Paris")


def at_paris(y: int, m: int, d: int, h: int, mi: int = 0) -> int:
    return instant(datetime(y, m, d, h, mi, tzinfo=PARIS))


@dataclass(slots=True)
class Result:
    name: str
    seed: int
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    day: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


Scenario = Callable[[Driver, RngTree, Result], Awaitable[None]]


def stance(driver: Driver, handle: str) -> affect_c.StanceReading:
    assert driver.kernel is not None
    frame = driver.kernel.mind.frame()
    return frame.get(affect_c.STANCE(frame.get(identity_c.PERSON(handle))))


def mood(driver: Driver) -> affect_c.MoodReading:
    assert driver.kernel is not None
    return driver.kernel.mind.frame().get(affect_c.MOOD)


def valence(s: affect_c.StanceReading) -> float:
    """La valence de ce qu'elle ressent envers la personne : déclaré si frais,
    sinon l'écart à son repos propre."""
    if s.declared is not None:
        return A.valence(s.declared.emotion)
    return A.valence(s.felt) if s.felt_intensity >= 0.1 else 0.0


def deviation(s: affect_c.StanceReading) -> float:
    return A.distance(s.position, s.home)


def prompts_to(driver: Driver, handle: str) -> list[str]:
    """Tout ce qui a été montré au modèle pour parler à cette adresse."""
    return [r.system_stable + "\n".join(m.content for m in r.messages) for r in driver.llm.calls  # type: ignore[attr-defined]
            if r.role in ("reply", "initiative") and r.meta.get("target") == handle]


def recalled(llm: Any, handle: str) -> list[str]:
    """Ce que la section « ce qui te revient » montrait pour parler à ``handle``."""
    out = []
    for req in llm.calls:
        if req.role != "reply" or req.meta.get("target") != handle:
            continue
        last = req.messages[-1].content
        if "CE QUI TE REVIENT" in last:
            out.append(last.split("CE QUI TE REVIENT", 1)[1].split("--- FIN ETAT INTERNE", 1)[0])
    return out


def day_of(driver: Driver, events: list[Any]) -> list[str]:
    """« Une journée de sa vie », en texte : qui a dit quoi, quand."""
    lines = []
    for e in events:
        t = datetime.fromtimestamp(e.at / US, PARIS).strftime("%d/%m %H:%M:%S")
        if e.type.name == rt.PERCEPTION_RECEIVED.name:
            where = f" [{e.data.room}]" if e.data.room else ""
            lines.append(f"{t}  {driver.names.get(e.data.handle, e.data.handle)}{where} : {e.data.text.text}")
        elif e.type.name == rt.UTTERANCE.name and e.data.kind == "STEP":
            lines.append(f"{t}  · (pour elle-même, en travaillant) {e.data.text.text}")
        elif e.type.name == rt.UTTERANCE.name:
            to = driver.names.get(e.data.target or "", e.data.target or "tout le monde")
            where = f" [{e.data.room}]" if e.data.room else ""
            lines.append(f"{t}  Mika → {to}{where} ({e.data.kind.lower()}) : {e.data.text.text}")
        elif e.type.name == rt.EPISODE_ENDED.name and e.data.outcome not in ("done",):
            lines.append(f"{t}  · {e.data.kind.lower()} {e.data.outcome}"
                         + (f" ({e.data.detail[:60]})" if e.data.detail else ""))
        elif e.type.name == "goals.opened":
            lines.append(f"{t}  · but ouvert ({e.data.kind}, {e.data.source}) : {e.data.title.text}")
        elif e.type.name == "goals.step_reported":
            lines.append(f"{t}  · séance du but #{e.data.goal} : {e.data.verdict}"
                         + (" (sans preuve)" if e.data.verdict == "done" and not e.data.proven else "")
                         + f" — {(e.data.summary.text or '')[:80]}")
        elif e.type.name == "goals.closed":
            lines.append(f"{t}  · but #{e.data.goal} clos : {e.data.status}"
                         + (f" ({e.data.reason[:60]})" if e.data.reason else ""))
        elif e.type.name.startswith("identity."):
            lines.append(f"{t}  · identité : {e.type.name.split('.', 1)[1]} {e.data.handle}")
        elif e.type.name == "kernel.boot":
            lines.append(f"{t}  ── démarrage ──")
    return lines


@dataclass(frozen=True, slots=True)
class Plan:
    name: str
    scenario: Scenario
    llm: Callable[[SimClock, int], Any]
    start: int
    seeds: tuple[int, ...] = (1,)


def persona_llm(clock: SimClock, seed: int) -> PersonaSimLLM:
    return PersonaSimLLM(clock, seed=seed, abstain_rate=0.0)


def run_plan(plan: Plan, composition: Composition, root: Path, seed: int) -> Result:
    res = Result(plan.name, seed)
    clock = SimClock(plan.start)
    driver = Driver(root, composition, plan.llm(clock, seed), clock, seed=seed)
    t0 = time.perf_counter()

    async def main() -> None:
        await driver.boot()
        try:
            await plan.scenario(driver, RngTree(seed).child(plan.name), res)
            assert driver.kernel is not None
            await driver.kernel.lanes.join()
            events = driver.read_events()
            for key, value in log_metrics(events, driver).items():
                res.metrics.setdefault(key, value)
            res.day = day_of(driver, events)
            tainted = dict(driver.kernel.mind.root.tainted.items())
            res.checks.append(expect.invariant("aucune tranche corrompue", not tainted,
                                               "un réducteur ne lève jamais", str(tainted)))
            res.checks.append(expect.invariant("jamais répondu deux fois (tous scénarios)",
                                               res.metrics["answered_twice"] == 0, "au plus une réponse par message"))
        finally:
            await driver.stop()

    run_virtual(clock, main)
    res.seconds = time.perf_counter() - t0
    return res


def run_lane(composition: Composition, root: Path, plans: tuple[Plan, ...]) -> list[Result]:
    results = []
    for i, plan in enumerate(plans):
        for seed in plan.seeds:
            d = root / f"{i:02d}-seed{seed}"
            d.mkdir(parents=True, exist_ok=True)
            results.append(run_plan(plan, composition, d, seed))
    return results
