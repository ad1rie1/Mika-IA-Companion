"""La carte de l'index (``adapters/vectors/layout.py``) : des voisins de sens qui restent voisins sur la sphère, une
carte qui ne saute pas quand la mémoire grandit, rien d'inventé.

Les données : des grappes gaussiennes en 64 dimensions, chacune un « sujet ». Une carte honnête garde ses voisins
ensemble ; une carte au hasard, non — c'est la référence qui rend chaque mesure non vide.
"""

from __future__ import annotations

import numpy as np
import pytest

from mika.adapters.vectors import layout as lay


def clusters(n: int = 360, topics: int = 9, dims: int = 64, spread: float = 0.6, seed: int = 1):
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(topics, dims))
    labels = np.arange(n) % topics
    return lay.normalized(centers[labels] + spread * rng.normal(size=(n, dims))), labels


def purity(dirs: np.ndarray, labels: np.ndarray, k: int = 10) -> float:
    """La part des dix voisins sur la sphère qui parlent du même sujet."""
    near, _ = lay.knn(lay.normalized(dirs), k)
    return float(np.mean([(labels[near[i]] == labels[i]).mean() for i in range(len(labels))]))


def test_neighbours_of_meaning_stay_neighbours_on_the_sphere():
    mat, labels = clusters()
    got = lay.layout(mat)
    assert got.dirs.shape == (len(mat), 3)
    assert np.allclose(np.linalg.norm(got.dirs, axis=1), 1.0, atol=1e-4)  # sur la sphère unité
    shuffled = np.random.default_rng(0).normal(size=(len(mat), 3))
    assert purity(got.dirs, labels) > 0.9 > 0.3 > purity(shuffled, labels)


def test_the_sphere_is_covered_not_piled_up():
    mat, _ = clusters()
    dirs = lay.layout(mat).dirs
    assert np.linalg.norm(dirs.mean(axis=0)) < 0.25  # pas un côté vide
    nearest = lay.knn(dirs, 1)[1][:, 0]
    assert np.median(np.degrees(np.arccos(np.clip(nearest, -1, 1)))) > 0.3  # pas des points empilés


def test_same_memory_same_map():
    mat, _ = clusters(n=120)
    assert np.array_equal(lay.layout(mat).dirs, lay.layout(mat).dirs)


def test_a_growing_memory_barely_moves_what_was_there():
    mat, labels = clusters(n=400)
    first = lay.layout(mat[:380])
    previous = lay.carried_over(list(range(400)), {k: first.dirs[k] for k in range(380)})
    assert previous is not None and np.isnan(previous[380:]).all() and np.isfinite(previous[:380]).all()
    second = lay.layout(mat, previous=previous)
    moved = np.degrees(np.arccos(np.clip((second.dirs[:380] * first.dirs).sum(axis=1), -1, 1)))
    assert np.median(moved) < 3.0
    # sans la carte précédente, la même mémoire bouge bien plus : c'est ``previous`` qui la tient en place
    cold = lay.layout(mat)
    redone = np.degrees(np.arccos(np.clip((cold.dirs[:380] * first.dirs).sum(axis=1), -1, 1)))
    assert np.median(redone) > 4 * np.median(moved)
    # ce qui arrive se pose parmi les siens
    for i in range(380, 400):
        near = np.argsort(-(second.dirs[:380] @ second.dirs[i]))[:10]
        assert (labels[near] == labels[i]).mean() >= 0.7


def test_filaments_are_the_true_neighbours_once_per_pair():
    mat, _ = clusters(n=100)
    got = lay.layout(mat)
    pairs, sims = got.edges(2)
    assert len(pairs) == len(sims) and (pairs[:, 0] < pairs[:, 1]).all()
    assert len({tuple(p) for p in pairs.tolist()}) == len(pairs)
    exact = mat @ mat.T
    np.fill_diagonal(exact, -np.inf)
    for (a, b), s in zip(pairs.tolist(), sims, strict=True):
        assert s == pytest.approx(exact[a, b], abs=1e-4)  # la similarité en pleine dimension
        top_a, top_b = np.argsort(-exact[a])[:2], np.argsort(-exact[b])[:2]
        assert b in top_a or a in top_b


def test_knn_is_exact_and_sorted():
    mat, _ = clusters(n=80)
    idx, sims = lay.knn(mat, 5)
    exact = mat @ mat.T
    np.fill_diagonal(exact, -np.inf)
    for i in range(len(mat)):
        assert list(idx[i]) == list(np.argsort(-exact[i], kind="stable")[:5])
        assert (np.diff(sims[i]) <= 1e-6).all() and i not in idx[i]


def test_beyond_the_exact_bound_neighbours_come_from_the_main_axes(monkeypatch):
    monkeypatch.setattr(lay, "EXACT_MAX", 50)
    mat, labels = clusters(n=200, dims=64)
    near, _ = lay.knn(mat, 10)
    assert np.mean([(labels[near[i]] == labels[i]).mean() for i in range(200)]) > 0.9


def test_placing_a_new_vector_lands_among_its_nearest():
    mat, labels = clusters(n=200)
    got = lay.layout(mat)
    probe = lay.normalized(mat[labels == 3].mean(axis=0, keepdims=True))[0]
    direction, idx, sims = lay.place(probe, mat, got.dirs)
    assert np.linalg.norm(direction) == pytest.approx(1.0, abs=1e-5)
    assert (labels[idx] == 3).all() and (np.diff(sims) <= 1e-6).all()
    centre = lay.normalized(got.dirs[labels == 3].mean(axis=0, keepdims=True))[0]
    assert float(direction @ centre) > 0.9


def test_degenerate_inputs():
    assert lay.layout(np.zeros((0, 8), dtype=np.float32)).dirs.shape == (0, 3)
    one = lay.layout(np.ones((1, 8), dtype=np.float32))
    assert one.dirs.shape == (1, 3) and one.edges()[0].shape == (0, 2)
    two = lay.layout(np.eye(2, 8, dtype=np.float32))
    assert np.allclose(np.linalg.norm(two.dirs, axis=1), 1.0, atol=1e-5)
    assert lay.carried_over([1, 2], {}) is None
    assert lay.place(np.ones(4), np.zeros((0, 4)), np.zeros((0, 3)))[1].shape == (0,)
