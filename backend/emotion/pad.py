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
    residual_floor: float = 0.15,
) -> list[tuple[Emotion, float]]:
    """Décompose un point PAD sur les top-K ancres, par poursuite du résidu.

    Le blend expose l'ambivalence : une position se lit "surtout grateful,
    un peu nostalgic" au lieu d'être forcée sur un seul libellé.

    **Le classement par cosinus décroissant ne convient pas pour ça.** La
    table des 29 ancres est dense (happy↔hopeful : 0.999, sad↔lonely : 0.995,
    anxious↔scared : 0.996), donc la deuxième meilleure ancre est par
    construction la voisine la plus proche de la première — un quasi-synonyme,
    pas une couleur différente. Une position posée *exactement* sur son ancre
    ressortait alors avec un second à ~0.95 de la dominante, et tout ce qui
    lit ce ratio (`_format_blend_phrase`, `MessageEmotion.is_ambivalent`,
    la porte d'ambivalence des gestes côté frontend) déclarait un tiraillement
    permanent là où l'état est parfaitement mono-couleur.

    On mesure donc ce que la dominante **n'explique pas** : après avoir retenu
    l'ancre la plus proche en direction, on retranche sa projection et on
    cherche l'ancre suivante sur le résidu. Le poids d'une entrée secondaire
    est son coefficient rapporté à celui de la dominante — nul sur une
    position pure (le résidu est nul), il ne monte que quand la position
    s'écarte réellement de sa dominante. Les seuils qui le lisent (0.4 pour la
    prose, 0.85 pour les gestes) gardent ainsi leur valeur et retrouvent leur
    sens.

    Le poids de la dominante reste son intensité pleine ("pure happy at 0.8"
    reste "happy 0.8"), et chaque entrée suivante est bornée par la
    précédente : la liste est toujours triée par poids décroissant.

    Les ancres sous `similarity_floor` de similarité cosinus avec la position
    sont écartées d'emblée — une émotion orthogonale ne décrit rien de ce
    point. `residual_floor` est la part minimale du résidu (relative à la
    dominante) sous laquelle une seconde entrée n'est que du bruit.

    Comportement :
      - vecteur nul                    → liste vide
      - direction d'ancre pure         → une seule entrée
      - direction mixte (0.6*HAPPY + 0.4*NOSTALGIC) → deux entrées
    """
    if top_k <= 0:
        return []

    mag = norm(position)
    if mag < 1e-6:
        return []

    intensity = min(1.0, mag / _MAX_ANCHOR_NORM)

    # Ancres compatibles avec la position, gardées sous forme unitaire :
    # la décomposition qui suit projette sur des directions, pas sur des
    # ancres de normes disparates.
    candidates: list[tuple[Emotion, Vec3, float]] = []
    for emotion, anchor in EMOTION_ANCHORS.items():
        anchor_mag = norm(anchor)
        if anchor_mag < 1e-6:
            continue  # NEUTRAL — pas de direction
        unit = scale(anchor, 1.0 / anchor_mag)
        cos = dot(position, unit) / mag
        if cos < similarity_floor:
            continue
        candidates.append((emotion, unit, cos))

    if not candidates:
        return []

    # Dominante : l'ancre la plus proche en direction, comme pad_to_label.
    candidates.sort(key=lambda c: -c[2])
    primary, primary_unit, _ = candidates.pop(0)
    primary_coeff = dot(position, primary_unit)

    blend: list[tuple[Emotion, float]] = [(primary, round(intensity, 3))]
    if primary_coeff <= 1e-6:
        return blend

    residual = sub(position, scale(primary_unit, primary_coeff))
    previous_weight = intensity

    while candidates and len(blend) < top_k:
        best_index = -1
        best_coeff = 0.0
        for index, (_, unit, _) in enumerate(candidates):
            coeff = dot(residual, unit)
            if coeff > best_coeff:
                best_coeff = coeff
                best_index = index
        if best_index < 0:
            break
        ratio = best_coeff / primary_coeff
        if ratio < residual_floor:
            break
        emotion, unit, _ = candidates.pop(best_index)
        weight = min(previous_weight, ratio * intensity)
        blend.append((emotion, round(weight, 3)))
        residual = sub(residual, scale(unit, best_coeff))
        previous_weight = weight

    return blend
