"""La carte de l'index : chaque vecteur à une place sur la sphère, près de ses voisins de sens.

Rien n'y est inventé. La direction d'un point se tire de ses **plus proches voisins dans l'espace des
plongements** (le produit scalaire de l'index, sur des vecteurs normalisés) : deux souvenirs proches au sens finissent
proches sur la sphère, et les filaments qu'on trace sont ces voisins-là — calculés en pleine dimension, jamais ceux de
la projection, qui déforme forcément. La profondeur n'est pas décidée ici : c'est l'écran qui la choisit (l'âge, la
vivacité), sur une direction unitaire.

L'algorithme est celui des plongements de voisinage (UMAP, t-SNE) ramené à l'essentiel et posé sur la sphère : un
départ par les trois axes principaux, puis des passes où chaque point est tiré vers ses voisins et repoussé par
quelques points tirés au sort. Numpy seul, graine fixe : la même mémoire donne la même carte. Une carte précédente sert
de départ à la suivante (``previous``) : ce qui était là bouge à peine, ce qui arrive se pose près de ses voisins.

Au-delà de ``EXACT_MAX`` vecteurs, les voisins se cherchent dans un espace réduit (``REDUCED_DIMS`` axes principaux) :
le coût d'une recherche exacte en pleine dimension croît au carré.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

#: les voisins d'un point qui le tirent vers eux
NEIGHBORS = 10
#: les voisins d'un point qu'on montre (les filaments)
SHOWN_NEIGHBORS = 2
#: jusqu'à tant de vecteurs, les voisins se cherchent en pleine dimension
EXACT_MAX = 8_000
#: au-delà, dans tant d'axes principaux
REDUCED_DIMS = 48
#: les points tirés au sort qui repoussent chaque point, à chaque passe
NEGATIVES = 6
#: ce qu'on garde de la mémoire de travail d'un bloc de similarités (en nombre de flottants)
_BLOCK_FLOATS = 4_000_000
#: un départ de la carte se calcule sur au plus tant de lignes (l'ACP d'un échantillon régulier)
_PCA_SAMPLE = 4_000
#: la netteté du voisinage : le poids d'un voisin croît comme ``exp(_SHARPNESS · similarité)``
_SHARPNESS = 12.0
#: la force qui écarte deux points (réglée sur 400 phrases réelles : 73 % des dix voisins de sens restent parmi les
#: dix voisins sur la sphère, et la sphère est couverte sans côté vide), et sa portée
_PUSH = 0.072
_SOFT = 0.005
_SEED = 20261012


@dataclass(frozen=True, slots=True)
class Layout:
    """Une carte : une direction unitaire par ligne de la matrice, et les voisins qui l'ont placée."""

    #: (n, 3) : la direction de chaque point sur la sphère unité
    dirs: np.ndarray
    #: (n, k) : les indices de ses plus proches voisins dans l'espace des plongements (-1 : il en a moins)
    neighbors: np.ndarray
    #: (n, k) : leurs similarités (produit scalaire)
    sims: np.ndarray

    def edges(self, shown: int = SHOWN_NEIGHBORS) -> tuple[np.ndarray, np.ndarray]:
        """Les filaments : chaque point relié à ses ``shown`` plus proches voisins, une fois par paire.
        Rend (paires (m, 2), similarités (m,))."""
        n, k = self.neighbors.shape if self.neighbors.ndim == 2 else (0, 0)
        take = min(shown, k)
        if not n or not take:
            return np.zeros((0, 2), dtype=np.int32), np.zeros(0, dtype=np.float32)
        src = np.repeat(np.arange(n, dtype=np.int64), take)
        dst = self.neighbors[:, :take].astype(np.int64).ravel()
        sim = self.sims[:, :take].ravel()
        ok = dst >= 0
        src, dst, sim = src[ok], dst[ok], sim[ok]
        lo, hi = np.minimum(src, dst), np.maximum(src, dst)
        pairs = lo * n + hi
        _, first = np.unique(pairs, return_index=True)
        first.sort()
        return np.stack([lo[first], hi[first]], axis=1).astype(np.int32), sim[first].astype(np.float32)


def normalized(mat: np.ndarray) -> np.ndarray:
    """Les lignes ramenées à la norme 1 (une ligne nulle reste nulle)."""
    m = np.asarray(mat, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms > 0, norms, 1.0)


def _components(mat: np.ndarray, dims: int) -> tuple[np.ndarray, np.ndarray]:
    """La moyenne et les ``dims`` axes principaux (ACP d'un échantillon régulier : déterministe)."""
    step = max(1, len(mat) // _PCA_SAMPLE)
    sample = mat[::step].astype(np.float64)
    mean = sample.mean(axis=0)
    _, _, vt = np.linalg.svd(sample - mean, full_matrices=False)
    comps = np.zeros((dims, mat.shape[1]), dtype=np.float64)
    comps[: min(dims, len(vt))] = vt[:dims]
    return mean, comps


def knn(mat: np.ndarray, k: int = NEIGHBORS) -> tuple[np.ndarray, np.ndarray]:
    """Les ``k`` plus proches voisins de chaque ligne (produit scalaire, soi exclu), du plus proche au plus lointain,
    ex æquo départagés par l'indice. Au-delà de ``EXACT_MAX`` lignes, dans l'espace des axes principaux.
    Rend (indices (n, k), similarités (n, k)) ; -1 et -inf là où il n'y a pas assez de voisins."""
    n = len(mat)
    idx = np.full((n, k), -1, dtype=np.int32)
    sims = np.full((n, k), -np.inf, dtype=np.float32)
    if n < 2 or k <= 0:
        return idx, sims
    space = mat
    if n > EXACT_MAX and mat.shape[1] > REDUCED_DIMS:
        mean, comps = _components(mat, REDUCED_DIMS)
        space = normalized(((mat - mean) @ comps.T).astype(np.float32))
    space = np.ascontiguousarray(space, dtype=np.float32)
    take = min(k, n - 1)
    block = max(1, _BLOCK_FLOATS // n)
    order = np.arange(n)
    for start in range(0, n, block):
        stop = min(n, start + block)
        s = space[start:stop] @ space.T
        s[np.arange(stop - start), order[start:stop]] = -np.inf  # pas soi-même
        part = np.argpartition(-s, take - 1, axis=1)[:, :take] if take < n else np.argsort(-s, axis=1)[:, :take]
        got = np.take_along_axis(s, part, axis=1)
        # du plus proche au plus lointain, l'indice départage
        rank = np.lexsort((part, -got), axis=1)
        idx[start:stop, :take] = np.take_along_axis(part, rank, axis=1)
        sims[start:stop, :take] = np.take_along_axis(got, rank, axis=1)
    return idx, sims


def _weights(sims: np.ndarray) -> np.ndarray:
    """Le poids de chaque voisin : plus il est proche (par rapport aux autres voisins du même point), plus il tire.
    Une ligne somme à 1."""
    s = np.where(np.isfinite(sims), sims, -np.inf).astype(np.float64)
    top = np.max(np.where(np.isfinite(s), s, -1e9), axis=1, keepdims=True)
    w = np.where(np.isfinite(s), np.exp(_SHARPNESS * (s - top)), 0.0)
    total = w.sum(axis=1, keepdims=True)
    return (w / np.where(total > 0, total, 1.0)).astype(np.float32)


def _sphere(points: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Sur la sphère unité ; un point sans direction en reçoit une au hasard (graine fixe)."""
    norms = np.linalg.norm(points, axis=1, keepdims=True)
    lost = norms[:, 0] < 1e-9
    if lost.any():
        points = points.copy()
        points[lost] = rng.normal(size=(int(lost.sum()), 3))
        norms = np.linalg.norm(points, axis=1, keepdims=True)
    return (points / norms).astype(np.float32)


def _start(mat: np.ndarray, neighbors: np.ndarray, weights: np.ndarray, rng: np.random.Generator,
           previous: np.ndarray | None) -> np.ndarray:
    """Le départ : les trois axes principaux ; ce que la carte précédente plaçait reste à sa place, et ce qui arrive se
    pose au barycentre de ses voisins déjà placés."""
    n = len(mat)
    if n >= 4:
        mean, comps = _components(mat, 3)
        start = ((mat - mean) @ comps.T).astype(np.float32)
    else:
        start = rng.normal(size=(n, 3)).astype(np.float32)
    start = _sphere(start, rng)
    if previous is None:
        return start
    known = np.isfinite(previous).all(axis=1)
    if not known.any():
        return start
    out = start.copy()
    out[known] = previous[known]
    for i in np.flatnonzero(~known):
        nb = neighbors[i]
        ok = (nb >= 0) & known[np.maximum(nb, 0)]
        if ok.any():
            out[i] = (weights[i, ok, None] * previous[nb[ok]]).sum(axis=0)
    return _sphere(out, rng)


def _relax(pos: np.ndarray, neighbors: np.ndarray, weights: np.ndarray, rng: np.random.Generator, *,
           epochs: int, rate: float) -> np.ndarray:
    """Les passes : chaque point tiré vers ses voisins (leurs poids), repoussé par ``NEGATIVES`` points au sort, puis
    reposé sur la sphère. Le pas décroît jusqu'à zéro."""
    n, k = neighbors.shape
    if n < 3 or epochs <= 0:
        return pos
    src = np.repeat(np.arange(n), k)
    dst = neighbors.ravel().astype(np.int64)
    w = weights.ravel()
    ok = dst >= 0
    src, dst, w = src[ok], dst[ok], w[ok]
    # l'attraction est symétrique : être le voisin de quelqu'un tire aussi
    src, dst, w = np.concatenate([src, dst]), np.concatenate([dst, src]), np.concatenate([w, w]) * 0.5
    negatives = min(NEGATIVES, n - 1)
    for epoch in range(epochs):
        step = rate * (1.0 - epoch / epochs)
        pull = (pos[dst] - pos[src]) * w[:, None]
        force = np.stack([np.bincount(src, weights=pull[:, a], minlength=n) for a in range(3)], axis=1)
        others = rng.integers(0, n, size=(n, negatives))
        away = pos[:, None, :] - pos[others]
        dist2 = (away * away).sum(axis=2, keepdims=True)
        push = (away / (dist2 + _SOFT)).mean(axis=1) * (_PUSH * np.sqrt(4000.0 / max(n, 50)))
        pos = pos + step * (force + push).astype(np.float32)
        pos /= np.maximum(np.linalg.norm(pos, axis=1, keepdims=True), 1e-9)
    return pos


def layout(mat: np.ndarray, *, previous: np.ndarray | None = None, k: int = NEIGHBORS) -> Layout:
    """La carte de ces vecteurs (une ligne par point). ``previous`` : (n, 3), la direction de chaque ligne sur la
    carte précédente, ``nan`` pour une ligne nouvelle — le départ de celle-ci, qui ne bouge alors qu'un peu."""
    rng = np.random.default_rng(_SEED)
    mat = normalized(mat)
    n = len(mat)
    if n == 0:
        return Layout(np.zeros((0, 3), dtype=np.float32), np.zeros((0, k), dtype=np.int32),
                      np.zeros((0, k), dtype=np.float32))
    neighbors, sims = knn(mat, k)
    weights = _weights(sims)
    warm = previous is not None and bool(np.isfinite(previous).all(axis=1).any())
    pos = _start(mat, neighbors, weights, rng, previous)
    # repartir de la carte précédente : peu de passes, un petit pas — ce qui était là ne bouge que d'un ou deux degrés
    epochs = (30 if warm else 300) if n <= 20_000 else (20 if warm else 160)
    pos = _relax(pos, neighbors, weights, rng, epochs=epochs, rate=0.06 if warm else 1.0)
    return Layout(pos, neighbors, sims)


def place(vec: np.ndarray, mat: np.ndarray, dirs: np.ndarray, *, k: int = 8) -> tuple[np.ndarray, np.ndarray,
                                                                                       np.ndarray]:
    """Où se pose un vecteur qui n'est pas sur la carte (un message, un souvenir qui naît) : au barycentre de ses
    ``k`` plus proches voisins de la carte, pondérés par leur proximité. Rend (direction (3,), indices, similarités) ;
    une carte vide : une direction nulle."""
    if not len(mat):
        return np.zeros(3, dtype=np.float32), np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float32)
    q = normalized(np.asarray(vec, dtype=np.float32)[None, :])[0]
    sims = mat @ q
    take = min(k, len(sims))
    idx = np.argpartition(-sims, take - 1)[:take]
    idx = idx[np.lexsort((idx, -sims[idx]))]
    got = sims[idx].astype(np.float32)
    return toward(dirs[idx], got), idx.astype(np.int32), got


def toward(dirs: np.ndarray, sims: Sequence[float] | np.ndarray) -> np.ndarray:
    """La direction pondérée de ces points (les plus proches pèsent le plus) ; à défaut, celle du premier."""
    if not len(dirs):
        return np.zeros(3, dtype=np.float32)
    s = np.asarray(sims, dtype=np.float64)
    w = np.exp(_SHARPNESS * (s - s.max()))
    v = (w[:, None] * np.asarray(dirs, dtype=np.float64)).sum(axis=0)
    norm = float(np.linalg.norm(v))
    return (v / norm).astype(np.float32) if norm > 1e-9 else np.asarray(dirs[0], dtype=np.float32)


def carried_over(keys: Sequence[int], previous: Mapping[int, np.ndarray]) -> np.ndarray | None:
    """La carte précédente remise dans l'ordre de ces clés (``nan`` pour une clé nouvelle) ; ``None`` sans carte."""
    if not previous:
        return None
    out = np.full((len(keys), 3), np.nan, dtype=np.float32)
    for i, key in enumerate(keys):
        got = previous.get(int(key))
        if got is not None:
            out[i] = got
    return out
