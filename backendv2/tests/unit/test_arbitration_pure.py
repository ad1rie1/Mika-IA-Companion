"""Preuve M0 — arbitrage pur : cumul, ANY, veto, aucun déclenchement sans intensité."""

from __future__ import annotations

import random

from mika.kernel.arbitration import Anyone, Candidate, Modulation, pool, rate_bound, sigmoid, thin
from mika.kernel.registry import ArbitrationPolicy

POLICY = ArbitrationPolicy(thresholds={"INITIATIVE": 1.0}, max_rates={"INITIATIVE": 1 / 600})


def no_mod(view):
    return []


def test_two_weak_reasons_pool_over_the_threshold():
    alone = pool([("social", Candidate("INITIATIVE", "alice", "salut", 0.6))], POLICY, no_mod)
    both = pool(
        [("social", Candidate("INITIATIVE", "alice", "salut", 0.6)),
         ("needs", Candidate("INITIATIVE", "alice", "ennui", 0.6))],
        POLICY, no_mod,
    )
    assert alone[0].score < 0 < both[0].score
    assert both[0].hazard > alone[0].hazard


def test_any_supports_every_targeted_row_of_its_kind():
    rows = pool(
        [("needs", Candidate("INITIATIVE", Anyone.ANY, "envie_de_parler", 0.8)),
         ("social", Candidate("INITIATIVE", "alice", "manque", 0.3)),
         ("social", Candidate("INITIATIVE", "bob", "manque", 0.3))],
        POLICY, no_mod,
    )
    assert {r.target for r in rows} == {"alice", "bob"}
    assert all(abs(r.evidence - 1.1) < 1e-9 for r in rows)


def test_veto_wins_and_shifts_add():
    def mod(view):
        return [("body", Modulation(veto="nuit")), ("agency", Modulation(shift=-0.5))]

    rows = pool([("social", Candidate("INITIATIVE", "alice", "manque", 3.0))], POLICY, mod)
    assert rows[0].hazard == 0.0 and rows[0].vetoes == (("body", "nuit"),)
    assert abs(rows[0].shift + 0.5) < 1e-12


def test_thin_never_fires_without_intensity_and_respects_proportions():
    rows = pool([("social", Candidate("INITIATIVE", "alice", "manque", -50.0))], POLICY, no_mod)
    bound = rate_bound(rows, POLICY)
    rng = random.Random(1)
    assert all(thin(rows, bound, rng)[0] is None for _ in range(1000))

    rows = pool(
        [("social", Candidate("INITIATIVE", "alice", "manque", 5.0)),
         ("social", Candidate("INITIATIVE", "bob", "manque", 1.0))],
        POLICY, no_mod,
    )
    bound = rate_bound(rows, POLICY)
    picks = [thin(rows, bound, rng)[0] for _ in range(20000)]
    fired = [p.target for p in picks if p is not None]
    share_alice = fired.count("alice") / len(fired)
    expected = sigmoid(4.0) / (sigmoid(4.0) + sigmoid(0.0))
    assert abs(share_alice - expected) < 0.02
