"""La santé (M8) dit ce qui ne va pas, sans qu'on le lui souffle : un
processus qui échoue d'affilée, un effet qui n'a pas pu partir, une boucle
morte — et redevient « ok » quand ça passe."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select

from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Origin, Payload
from mika.kernel.faculty import Faculty
from mika.ports.journal import JournalOutbox
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


@FLAKY.process("flaky.tick", max_quantum_s=60)
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
        await kernel.mind.append([REPAIRED.draft()], emitter="flaky", correlation="t", origin=Origin.KERNEL)
        await asyncio.sleep(2 * MINUTE / US)
        repaired = health.report(kernel)
        for i in range(6):  # un effet qui échoue à chaque tentative (réessais datés, avec recul) : abandonné
            await kernel.mind.append([PING.draft(n=i)], emitter="flaky", correlation="t", origin=Origin.KERNEL)
            await asyncio.sleep(1)
        await asyncio.sleep(15 * MINUTE / US)
        abandoned = health.report(kernel)
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
    # le premier échoue après ses réessais ; les suivants, au même destinataire, attendent derrière lui
    assert "1 départ à traiter : 1 échoué" in next(c for c in abandoned.checks if c.name == "outbox").summary
    assert states(repaired)["processes"] == "ok"  # un succès remet le compte à zéro
    assert states(dead)["loops"] == "ko" and dead.status == "ko"
    assert stopped.public()["ready"] is False and stopped.status == "stopped"
    public = failing.public()
    assert set(public) == {"status", "ready", "checks"}
    assert set(public["checks"].values()) <= {"ok", "degraded", "ko"}  # des états, jamais un résumé
    assert "la page a changé" not in str(public)  # le détail n'est jamais public


@dataclass(frozen=True, slots=True)
class QuietState:
    pass


QUIET = Faculty("quiet", state=QuietState, init=lambda p: QuietState())
SENT = QUIET.event("sent", Ping)


@QUIET.effect(SENT)
async def _deliver(e, ports):
    return None


def test_what_is_to_handle_is_counted_as_the_outbox_page_counts_it(tmp_path):
    """« À traiter » a une seule définition, celle de la File de sortie : une parole périmée ou un effet orphelin
    récents dégradent la santé, et le constat les compte avec les mots de la page ; un échec de plus de 24 h y reste
    dit, le contrôle restant « ok » (la sonde publique ne reste pas dégradée pour un vieux départ que personne n'a
    marqué). Le détail dit « événement n° N », jamais « seq »."""
    kernel, clock, _ = build(tmp_path, [QUIET])

    async def main():
        await kernel.start()
        for i in range(3):
            await kernel.mind.append([SENT.draft(n=i)], emitter="quiet", correlation="t", origin=Origin.KERNEL)
            await asyncio.sleep(1)
        store = kernel.mind.store
        rows = store.query_mind(select(JournalOutbox.key, JournalOutbox.seq).order_by(JournalOutbox.seq))
        (stale, stale_seq), (orphan, _), _sent = rows
        await store.mark_outbox(stale, "stale", "trop tard : elle ne le dit plus")
        await store.mark_outbox(orphan, "orphan", "aucun gestionnaire")
        fresh = health._outbox(kernel)
        await store.mark_outbox(stale, "seen", "trop tard : elle ne le dit plus")
        await store.mark_outbox(orphan, "failed", "TimeoutError()")
        clock.advance_to(clock.now() + DAY + HOUR)
        old = health._outbox(kernel)
        await kernel.mind.append([SENT.draft(n=9)], emitter="quiet", correlation="t", origin=Origin.KERNEL)
        await asyncio.sleep(1)
        newest = store.query_mind(select(JournalOutbox.key).order_by(JournalOutbox.seq.desc()).limit(1))[0][0]
        await store.mark_outbox(newest, "interrupted", "délai dépassé : coupée au bout de 900 s")
        mixed = health._outbox(kernel)
        await kernel.stop()
        return fresh, old, mixed, stale_seq

    fresh, old, mixed, stale_seq = run_virtual(clock, main)
    assert fresh.state == "degraded"
    assert fresh.summary == "2 départs à traiter : 1 orphelin, 1 périmé (pas dit)"  # le troisième est parti
    assert f"quiet:quiet.sent (événement n° {stale_seq}) : périmé (pas dit) — trop tard : elle ne le dit plus" \
        in fresh.detail
    assert not any("seq" in d for d in (*fresh.detail, *old.detail, *mixed.detail))
    assert old.state == "ok"  # rien de neuf : la sonde publique n'en reste pas dégradée
    assert old.summary == "1 départ à traiter depuis plus de 24 h : 1 échoué"
    assert any(d.endswith(": échoué — délai dépassé") for d in old.detail)
    assert mixed.state == "degraded"
    assert mixed.summary == "2 départs à traiter, dont 1 depuis plus de 24 h : 1 échoué, 1 interrompu (à vérifier)"
    assert "abandonné" not in " ".join((fresh.summary, old.summary, mixed.summary))


def test_a_port_that_says_it_is_failing_degrades_health():
    """Un branchement qui sait dire ce qui est en panne chez lui (un serveur d'outils extérieurs coupé par son
    disjoncteur, ADR 0064) dégrade la santé ; un port qui ne dit rien, ou qui va bien, ne compte pas."""
    from types import SimpleNamespace

    class Hub:
        def __init__(self, failing):
            self._failing = failing

        def failing(self):
            return self._failing

    def kernel(**ports):
        return SimpleNamespace(deps=SimpleNamespace(ports=ports))

    assert health._ports(kernel(mcp=Hub([]), store=object())).state == "ok"
    down = health._ports(kernel(mcp=Hub(["meteo"])))
    assert down.state == "degraded" and "meteo" in down.summary and "mcp" in down.summary
    assert health._ports(kernel()).state == "ok"


def test_the_checks_speak_in_event_numbers_and_say_the_gesture():
    """Les constats parlent en mots : un numéro d'événement se dit « n° N », jamais « seq » ; le journal dit de
    combien d'événements date son dernier instantané (avant : « 135 événements, dernier instantané 134 derrière ») ;
    une boucle arrêtée dit le geste, aucune page ne la montrant mieux que sa tuile (audit du 2026-11-05, C8-14 et
    C8-10)."""
    from types import SimpleNamespace

    def journal(head: int, snap: int | None, gaps=()) -> health.Check:
        store = SimpleNamespace(latest_snapshot=lambda: SimpleNamespace(seq=snap) if snap is not None else None)
        mind = SimpleNamespace(store=store, head=head, gaps=list(gaps))
        return health._journal(SimpleNamespace(mind=mind, deps=SimpleNamespace(snapshot_every=100)))

    late = journal(135, 1)
    assert late.summary == "135 événements ; le dernier instantané date de 134 événements"
    assert late.detail == ("dernier instantané : n° 1",)
    assert journal(1, 0).summary == "1 événement ; le dernier instantané date de 1 événement"
    assert journal(40, 40).summary == "40 événements ; le dernier instantané est à jour"
    assert journal(3, None).summary == "3 événements ; aucun instantané"
    holes = journal(20, 1, gaps=[(5, 8), (12, 13)])
    assert holes.state == health.KO
    assert "numéros manquants : 5–7, 12 — `mika replay --verify` les liste tous" in holes.detail
    tainted = health._slices(SimpleNamespace(mind=SimpleNamespace(root=SimpleNamespace(tainted={"memory": 42}))))
    assert tainted.detail == ("memory : un réducteur a levé à l'événement n° 42",)
    one = health._loops(SimpleNamespace(dead_loops=lambda: ["ordonnanceur"]))
    assert one.state == health.KO
    assert one.summary == "1 boucle arrêtée (ordonnanceur) : rien ne la relance — redémarre le serveur"
    two = health._loops(SimpleNamespace(dead_loops=lambda: ["ordonnanceur", "projections"]))
    assert two.summary == ("2 boucles arrêtées (ordonnanceur, projections) : rien ne les relance — redémarre le "
                           "serveur")
    held = health._projections(SimpleNamespace(projections=SimpleNamespace(
        lag=lambda: {}, quarantined=[("thread", 9, "boum")])))
    assert held.detail == ("thread : événement n° 9 en quarantaine (boum)",)
    said = [late, holes, tainted, one, two, held]
    assert not any("seq" in x or "derrière" in x for c in said for x in (c.summary, *c.detail))
