"""PAD (Pleasure-Arousal-Dominance) representation of emotions.

Each of the 29 emotions is mapped to a point in 3D continuous space.
The engine's internal state lives in this space; the discrete `Emotion`
enum is only used as I/O vocabulary (Claude tags, frontend blendshapes).

Axes (all in [-1, 1]):
    P (Pleasure/Valence) : negative ↔ positive
    A (Arousal)          : calm     ↔ excited
    D (Dominance)        : submissive ↔ in control
"""
from __future__ import annotations

import math

from emotion.types import Emotion


Vec3 = tuple[float, float, float]


EMOTION_ANCHORS: dict[Emotion, Vec3] = {
    Emotion.NEUTRAL:     ( 0.0,  0.0,  0.0),

    # --- Positive ---
    Emotion.HAPPY:       ( 0.8,  0.3,  0.3),
    Emotion.EXCITED:     ( 0.7,  0.9,  0.5),
    Emotion.LOVE:        ( 0.9,  0.4,  0.2),
    Emotion.PROUD:       ( 0.7,  0.3,  0.8),
    Emotion.GRATEFUL:    ( 0.7,  0.1,  0.0),
    Emotion.PLAYFUL:     ( 0.7,  0.6,  0.5),
    Emotion.AMUSED:      ( 0.7,  0.4,  0.3),
    Emotion.HOPEFUL:     ( 0.6,  0.2,  0.2),
    Emotion.RELIEVED:    ( 0.5, -0.3,  0.2),

    # --- Negative ---
    Emotion.SAD:         (-0.7, -0.3, -0.5),
    Emotion.ANGRY:       (-0.6,  0.8,  0.6),
    Emotion.SCARED:      (-0.7,  0.7, -0.7),
    Emotion.DISGUSTED:   (-0.7,  0.3,  0.4),
    Emotion.FRUSTRATED:  (-0.5,  0.6,  0.2),
    Emotion.LONELY:      (-0.7, -0.4, -0.5),
    Emotion.ANXIOUS:     (-0.5,  0.6, -0.5),
    Emotion.BORED:       (-0.3, -0.6, -0.2),
    Emotion.JEALOUS:     (-0.5,  0.5, -0.2),

    # --- Complex ---
    Emotion.SURPRISED:   ( 0.1,  0.8, -0.1),
    Emotion.THINKING:    ( 0.1,  0.1,  0.2),
    Emotion.CONFUSED:    (-0.2,  0.3, -0.4),
    Emotion.EMBARRASSED: (-0.3,  0.4, -0.5),
    Emotion.NOSTALGIC:   ( 0.2, -0.2, -0.1),
    Emotion.DREAMY:      ( 0.4, -0.3, -0.2),
    Emotion.DETERMINED:  ( 0.4,  0.5,  0.7),
    Emotion.MISCHIEVOUS: ( 0.5,  0.5,  0.6),
    Emotion.CURIOUS:     ( 0.4,  0.5,  0.2),
    Emotion.MELANCHOLIC: (-0.5, -0.5, -0.3),
}

# Maximum norm of an anchor — used to normalize "intensity" when reading state.
# Computed once: max over anchors of sqrt(p² + a² + d²).
_MAX_ANCHOR_NORM = max(
    math.sqrt(p * p + a * a + d * d) for (p, a, d) in EMOTION_ANCHORS.values()
)


def zero() -> Vec3:
    return (0.0, 0.0, 0.0)


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(v: Vec3, k: float) -> Vec3:
    return (v[0] * k, v[1] * k, v[2] * k)


def norm(v: Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def distance(a: Vec3, b: Vec3) -> float:
    return norm(sub(a, b))


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def clamp_component(v: Vec3, limit: float = 1.0) -> Vec3:
    return (
        max(-limit, min(limit, v[0])),
        max(-limit, min(limit, v[1])),
        max(-limit, min(limit, v[2])),
    )


def valence(emotion: Emotion) -> float:
    """P-axis (pleasure/valence) of an emotion's anchor. >0 positive, <0 negative."""
    return EMOTION_ANCHORS[emotion][0]


def label_to_pad(emotion: Emotion, intensity: float) -> Vec3:
    """Convert a discrete (emotion, intensity) pair to a PAD point.

    The anchor is scaled by intensity so that intensity=0 is the origin
    (neutral) and intensity=1 is the full anchor position.
    """
    anchor = EMOTION_ANCHORS[emotion]
    return scale(anchor, max(0.0, min(1.0, intensity)))


def pad_to_label(position: Vec3) -> tuple[Emotion, float]:
    """Find the nearest-direction anchor and report intensity = norm/max_norm.

    We compare the direction of `position` to each anchor's direction
    (cosine similarity) and pick the best match, then report the raw
    magnitude as intensity. For a zero vector we return NEUTRAL at 0.

    Intensity is normalized so that reaching the furthest anchor = 1.0.
    """
    mag = norm(position)
    if mag < 1e-6:
        return Emotion.NEUTRAL, 0.0

    # Cosine similarity (direction match) against every anchor
    best_emotion = Emotion.NEUTRAL
    best_score = -2.0
    for emotion, anchor in EMOTION_ANCHORS.items():
        anchor_mag = norm(anchor)
        if anchor_mag < 1e-6:
            continue  # NEUTRAL — handled by the mag < threshold above
        score = dot(position, anchor) / (mag * anchor_mag)
        if score > best_score:
            best_score = score
            best_emotion = emotion

    intensity = min(1.0, mag / _MAX_ANCHOR_NORM)
    return best_emotion, intensity


def pad_to_blend(
    position: Vec3,
    top_k: int = 2,
    similarity_floor: float = 0.35,
) -> list[tuple[Emotion, float]]:
    """Project a PAD point onto the top-K *compatible* anchors.

    This exposes emotional ambivalence: a position can be read as
    "mostly grateful, a bit nostalgic" instead of forcing a single label.

    Each returned weight is (cosine_similarity × normalized_magnitude),
    clamped to [0, 1]. Returned list is length 0..top_k, sorted by weight
    descending. Anchors below `similarity_floor` cosine similarity are
    excluded — they'd be misleading (orthogonal emotions shouldn't
    appear in a blend).

    Behavior:
      - zero vector  → empty list
      - pure single-anchor direction → list of length 1 (others filtered out)
      - mixed direction (e.g. 0.6*HAPPY + 0.4*NOSTALGIC) → two entries
    """
    if top_k <= 0:
        return []

    mag = norm(position)
    if mag < 1e-6:
        return []

    intensity = min(1.0, mag / _MAX_ANCHOR_NORM)

    similarities: list[tuple[Emotion, float]] = []
    for emotion, anchor in EMOTION_ANCHORS.items():
        anchor_mag = norm(anchor)
        if anchor_mag < 1e-6:
            continue
        cos = dot(position, anchor) / (mag * anchor_mag)
        if cos < similarity_floor:
            continue
        similarities.append((emotion, cos))

    similarities.sort(key=lambda x: -x[1])
    top = similarities[:top_k]
    if not top:
        return []

    # Weight = similarity × intensity, rescaled so the top match always
    # equals its full intensity (so "pure happy at 0.8" stays "happy 0.8").
    max_cos = top[0][1]
    return [
        (emotion, round((cos / max_cos) * intensity, 3))
        for emotion, cos in top
    ]
