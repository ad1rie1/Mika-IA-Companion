"""Une décision d'initiative s'explique entière : ``kernel.selected`` garde la
ligne choisie même quand l'amincissement l'a tirée loin derrière les
premières, le seuil, le vieillissement et le décalage de chaque modulateur
(leur somme est le décalage de la ligne), la borne et l'intensité totale. Un
journal écrit avant ces champs se relit tel quel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mika.kernel.arbitration import Candidate, Modulation
from mika.kernel.codec import canonical_json
from mika.kernel.faculty import Faculty
from mika.kernel.registry import ArbitrationPolicy, Registry
from mika.runtime.state import RUNTIME
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build, events_of


@dataclass(frozen=True, slots=True)
class Nothing:
    pass


PINGER = Faculty("pinger", state=Nothing, init=lambda p: Nothing())
CALM = Faculty("calm", state=Nothing, init=lambda p: Nothing())
MOOD = Faculty("mood", state=Nothing, init=lambda p: Nothing())

EVIDENCE = {"a": 3.0, "b": 0.0, "c": -1.0}


@PINGER.propose(kinds=["PING"], reasons={"envie": (-5.0, 5.0)})
def _propose(s, frame):
    return [Candidate("PING", who, "envie", ev) for who, ev in EVIDENCE.items()]


@CALM.modulate(kinds=["PING"])
def _calm(s, frame, view):
    return Modulation(shift=-0.25)


@MOOD.modulate(kinds=["PING"])
def _mood_a(s, frame, view):
    return Modulation(shift=0.1)


@MOOD.modulate(kinds=["PING"])
def _mood_b(s, frame, view):
    return Modulation(shift=0.05)


@MOOD.modulate(kinds=["PING"])
def _mood_nothing(s, frame, view):
    return Modulation()  # ne décale rien : n'apparaît pas


POLICY = ArbitrationPolicy(thresholds={"PING": 0.5}, max_rates={"PING": 1 / 60}, aging_per_hour={"PING": 0.3},
                           top_k=1)


def test_every_selection_explains_itself_even_when_it_fired_far_down(tmp_path):
    # « PING » n'a pas de politique d'épisode : la décision est l'événement
    # lui-même, rien ne met la ligne en file — elle reste tirable
    kernel, clock, _ = build(tmp_path, [PINGER, CALM, MOOD], arbitration=POLICY)

    async def main():
        await kernel.start()
        await asyncio.sleep(3600)
        selected = [e.data for e in events_of(kernel, "kernel.selected")]
        live = list(kernel.arbiter.last_rows)
        await kernel.stop()
        return selected, live

    selected, live = run_virtual(clock, main)
    assert len(selected) > 20
    far = [s for s in selected if s.fired[0] != f"{s.rows[0].kind}:{s.rows[0].target}"]
    assert far, "l'amincissement tire aussi des lignes hors du haut de la table"
    for s in selected:
        keys = [f"{r.kind}:{r.target}" for r in s.rows]
        assert s.fired[0] in keys, "la ligne choisie est toujours journalisée"
        assert s.candidates == 3 and 0 < s.total <= s.bound and s.draw * s.bound < s.total
        for r in s.rows:
            assert r.shifts == (("calm", -0.25), ("mood", 0.15))
            assert abs(sum(v for _, v in r.shifts) - r.shift) < 1e-6
            assert r.threshold == 0.5 and r.aging >= 0.0
            assert abs(sum(p[2] for p in r.parts) + r.shift + r.aging - r.threshold - r.score) < 1e-5
    assert all(len(s.rows) == 2 for s in far)
    assert max(r.aging for s in selected for r in s.rows) > 0.2, "une heure d'attente se voit"
    assert {r.target for r in live} == {"a", "b", "c"}, "la dernière table vivante, entière"


def test_a_journal_written_before_these_fields_still_decodes():
    registry = Registry([RUNTIME])
    old = ('{"draw":0.42,"fired":["INITIATIVE:alice"],"rows":[{"hazard":0.01,"kind":"INITIATIVE",'
           '"parts":[["social","manque",1.2]],"score":0.2,"shift":-0.5,"target":"alice","vetoes":[]}]}')
    _, data = registry.events.decode("kernel.selected", 1, old)
    assert data.candidates == 0 and data.bound == 0.0 and data.total == 0.0
    row = data.rows[0]
    assert row.shifts == () and row.threshold == 0.0 and row.aging == 0.0 and row.shift == -0.5
    # et un événement d'aujourd'hui fait l'aller-retour
    t, again = registry.events.decode("kernel.selected", 1, canonical_json(data))
    assert again == data
