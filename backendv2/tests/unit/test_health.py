"""La santé (M8) dit ce qui ne va pas, sans qu'on le lui souffle : un
processus qui échoue d'affilée, un effet abandonné, une boucle morte — et
redevient « ok » quand ça passe."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Origin, Payload
from mika.kernel.faculty import Faculty
from mika.runtime import health
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build


@dataclass(frozen=True, slots=True)
class FlakyState:
    broken: bool = True


class Ping(Payload):
    n: int = 0


class Repaired(Payload):
    pass


FLAKY = Faculty("flaky", state=FlakyState, init=lambda p: FlakyState())
PING = FLAKY.event("ping", Ping)
REPAIRED = FLAKY.event("repaired", Repaired)


@FLAKY.reducer(REPAIRED)
def _repaired(s: FlakyState, e, cx) -> FlakyState:
    return FlakyState(broken=False)


@FLAKY.process("flaky.tick", lane="background", max_quantum_s=60)
class Tick:
    def next_due(self, state: FlakyState, frame, last_run):
        return frame.now if last_run is None else last_run + MINUTE

    async def run(self, ctx) -> None:
        if ctx.state.broken:
            raise RuntimeError("la page a changé")


@FLAKY.effect(PING)
async def _send(e, ports):
    raise ConnectionError("injoignable")


def states(report: health.Health) -> dict[str, str]:
    return {c.name: c.state for c in report.checks}


def test_health_names_what_goes_wrong_and_recovers(tmp_path):
    kernel, clock, _ = build(tmp_path, [FLAKY])

    async def main():
        assert health.report(kernel).public() == {"status": "stopped", "ready": False, "checks": {}}
        await kernel.start()
        fresh = health.report(kernel)
        await asyncio.sleep(4 * MINUTE / US)  # quatre passages ratés d'affilée
        failing = health.report(kernel)
        for i in range(6):  # un effet qui échoue à chaque tentative : abandonné
            await kernel.mind.append([PING.draft(n=i)], emitter="flaky", correlation="t", origin=Origin.KERNEL)
            await asyncio.sleep(1)
        abandoned = health.report(kernel)
        await kernel.mind.append([REPAIRED.draft()], emitter="flaky", correlation="t", origin=Origin.KERNEL)
        await asyncio.sleep(2 * MINUTE / US)
        repaired = health.report(kernel)
        kernel._tasks[0].cancel()  # l'ordonnanceur meurt en marche
        await asyncio.sleep(1)
        dead = health.report(kernel)
        await kernel.stop()
        return fresh, failing, abandoned, repaired, dead, health.report(kernel)

    fresh, failing, abandoned, repaired, dead, stopped = run_virtual(clock, main)
    assert fresh.status == "ok" and fresh.ready
    assert states(failing)["processes"] == "degraded" and failing.status == "degraded"
    detail = next(c for c in failing.checks if c.name == "processes").detail
    assert any("flaky.tick" in d and "la page a changé" in d for d in detail)
    assert states(abandoned)["outbox"] == "degraded"
    assert "abandonné" in next(c for c in abandoned.checks if c.name == "outbox").summary
    assert states(repaired)["processes"] == "ok"  # un succès remet le compte à zéro
    assert states(dead)["loops"] == "ko" and dead.status == "ko"
    assert stopped.public()["ready"] is False and stopped.status == "stopped"
    public = failing.public()
    assert set(public) == {"status", "ready", "checks"}
    assert set(public["checks"].values()) <= {"ok", "degraded", "ko"}  # des états, jamais un résumé
    assert "la page a changé" not in str(public)  # le détail n'est jamais public
