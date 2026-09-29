"""Vocabulaire affectif : les 29 émotions, l'espace PAD, la balise déclarée.

Une émotion est un point de l'espace Plaisir–Activation–Dominance (chaque axe
dans [−1, 1]). Le nom discret ne sert qu'aux entrées et sorties (la balise que
le modèle écrit, les trames du visage, la prose du prompt) ; l'état vit dans
l'espace continu.

Deux lectures d'une position, qui ne répondent pas à la même question :

- ``label`` nomme la position **absolue** (le visage montre la teinte du jour) ;
- ``felt`` nomme l'**écart au repos** : au repos elle ne ressent « rien de
  particulier », et un petit pas vers la tristesse se lit « triste » même si
  le repos, positif, est deux fois plus long que le pas.
"""

from __future__ import annotations

import enum
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

Vec3 = tuple[float, float, float]
ORIGIN: Vec3 = (0.0, 0.0, 0.0)


class Emotion(enum.StrEnum):
    NEUTRAL = "neutral"
    # positives
    HAPPY = "happy"
    EXCITED = "excited"
    LOVE = "love"
    PROUD = "proud"
    GRATEFUL = "grateful"
    PLAYFUL = "playful"
    AMUSED = "amused"
    HOPEFUL = "hopeful"
    RELIEVED = "relieved"
    # négatives
    SAD = "sad"
    ANGRY = "angry"
    SCARED = "scared"
    DISGUSTED = "disgusted"
    FRUSTRATED = "frustrated"
    LONELY = "lonely"
    ANXIOUS = "anxious"
    BORED = "bored"
    JEALOUS = "jealous"
    # complexes
    SURPRISED = "surprised"
    THINKING = "thinking"
    CONFUSED = "confused"
    EMBARRASSED = "embarrassed"
    NOSTALGIC = "nostalgic"
    DREAMY = "dreamy"
    DETERMINED = "determined"
    MISCHIEVOUS = "mischievous"
    CURIOUS = "curious"
    MELANCHOLIC = "melancholic"


def emotion_of(name: str | None) -> Emotion | None:
    """Le nom canonique, ou ``None`` s'il n'est pas l'une des 29."""
    if not name:
        return None
    try:
        return Emotion(name.strip().lower())
    except ValueError:
        return None


ANCHORS: Mapping[Emotion, Vec3] = MappingProxyType({
    Emotion.NEUTRAL: (0.0, 0.0, 0.0),
    Emotion.HAPPY: (0.8, 0.3, 0.3),
    Emotion.EXCITED: (0.7, 0.9, 0.5),
    Emotion.LOVE: (0.9, 0.4, 0.2),
    Emotion.PROUD: (0.7, 0.3, 0.8),
    Emotion.GRATEFUL: (0.7, 0.1, 0.0),
    Emotion.PLAYFUL: (0.7, 0.6, 0.5),
    Emotion.AMUSED: (0.7, 0.4, 0.3),
    Emotion.HOPEFUL: (0.6, 0.2, 0.2),
    Emotion.RELIEVED: (0.5, -0.3, 0.2),
    Emotion.SAD: (-0.7, -0.3, -0.5),
    Emotion.ANGRY: (-0.6, 0.8, 0.6),
    Emotion.SCARED: (-0.7, 0.7, -0.7),
    Emotion.DISGUSTED: (-0.7, 0.3, 0.4),
    Emotion.FRUSTRATED: (-0.5, 0.6, 0.2),
    Emotion.LONELY: (-0.7, -0.4, -0.5),
    Emotion.ANXIOUS: (-0.5, 0.6, -0.5),
    Emotion.BORED: (-0.3, -0.6, -0.2),
    Emotion.JEALOUS: (-0.5, 0.5, -0.2),
    Emotion.SURPRISED: (0.1, 0.8, -0.1),
    Emotion.THINKING: (0.1, 0.1, 0.2),
    Emotion.CONFUSED: (-0.2, 0.3, -0.4),
    Emotion.EMBARRASSED: (-0.3, 0.4, -0.5),
    Emotion.NOSTALGIC: (0.2, -0.2, -0.1),
    Emotion.DREAMY: (0.4, -0.3, -0.2),
    Emotion.DETERMINED: (0.4, 0.5, 0.7),
    Emotion.MISCHIEVOUS: (0.5, 0.5, 0.6),
    Emotion.CURIOUS: (0.4, 0.5, 0.2),
    Emotion.MELANCHOLIC: (-0.5, -0.5, -0.3),
})


# ── Arithmétique ──────────────────────────────────────────────────────────


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(v: Vec3, k: float) -> Vec3:
    return (v[0] * k, v[1] * k, v[2] * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(v: Vec3) -> float:
    return math.sqrt(dot(v, v))


def distance(a: Vec3, b: Vec3) -> float:
    return norm(sub(a, b))


def clamp(v: Vec3, limit: float = 1.0) -> Vec3:
    return (max(-limit, min(limit, v[0])), max(-limit, min(limit, v[1])), max(-limit, min(limit, v[2])))


def lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """``a`` rapproché de ``b`` d'une part ``t`` du chemin."""
    return add(scale(a, 1.0 - t), scale(b, t))


def cap_norm(v: Vec3, limit: float) -> Vec3:
    n = norm(v)
    return v if n <= limit else scale(v, limit / n)


MAX_ANCHOR_NORM = max(norm(a) for a in ANCHORS.values())
#: Plancher des lectures d'intensité : la plus courte des ancres négatives
#: (``bored``). Sans lui, une humeur ordinaire dans le cône d'une émotion à
#: ancre courte (``thinking``, ``nostalgic``) lirait 1,0.
INTENSITY_FLOOR = norm(ANCHORS[Emotion.BORED])


def to_pad(emotion: Emotion, intensity: float = 1.0) -> Vec3:
    """Le point PAD d'une émotion à une intensité (0 = origine, 1 = ancre)."""
    return scale(ANCHORS[emotion], max(0.0, min(1.0, intensity)))


def valence(emotion: Emotion) -> float:
    return ANCHORS[emotion][0]


def arousal(emotion: Emotion) -> float:
    return ANCHORS[emotion][1]


# ── Lectures ──────────────────────────────────────────────────────────────


def label(position: Vec3) -> tuple[Emotion, float]:
    """L'ancre la plus proche en direction, et la norme rapportée à la plus
    longue ancre (lecture absolue : ce que montre le visage)."""
    mag = norm(position)
    if mag < 1e-6:
        return Emotion.NEUTRAL, 0.0
    best, best_score = Emotion.NEUTRAL, -2.0
    for emotion, anchor in ANCHORS.items():
        n = norm(anchor)
        if n < 1e-6:
            continue
        score = dot(position, anchor) / (mag * n)
        if score > best_score:
            best, best_score = emotion, score
    return best, min(1.0, mag / MAX_ANCHOR_NORM)


def felt(position: Vec3, home: Vec3, *, floor: float | None = None) -> tuple[Emotion, float]:
    """Ce que dit l'écart au repos : l'émotion vers laquelle il pointe, et la
    part du chemin parcourue vers elle.

    La direction se compare aux **rayons** ``ancre − repos``, pas aux ancres :
    une impulsion déplace la position depuis le repos vers une ancre, donc
    l'écart est colinéaire à ce rayon. Le neutre n'est jamais candidat.
    """
    gap = sub(position, home)
    mag = norm(gap)
    if mag < 1e-6:
        return Emotion.NEUTRAL, 0.0
    best, best_score, best_len = Emotion.NEUTRAL, -2.0, 1.0
    for emotion, anchor in ANCHORS.items():
        if emotion is Emotion.NEUTRAL:
            continue
        ray = sub(anchor, home)
        length = norm(ray)
        if length < 1e-6:
            continue
        score = dot(gap, ray) / (mag * length)
        if score > best_score:
            best, best_score, best_len = emotion, score, length
    ref = max(best_len, INTENSITY_FLOOR if floor is None else floor)
    return best, min(1.0, mag / ref)


def overflow(position: Vec3, home: Vec3 | None = None) -> float:
    """L'intensité que lisent les portes (débordement, détresse).

    Avec un repos : l'écart au repos (``felt``). Sans : la norme rapportée à
    l'ancre la plus proche, bornée par le plancher — l'échelle même de la
    balise (``to_pad(sad, 0.8)`` lit 0,8).
    """
    if home is not None:
        return felt(position, home)[1]
    mag = norm(position)
    if mag < 1e-6:
        return 0.0
    emotion, _ = label(position)
    return min(1.0, mag / max(norm(ANCHORS[emotion]), INTENSITY_FLOOR))


def blend(
    position: Vec3,
    top_k: int = 2,
    *,
    similarity_floor: float = 0.35,
    residual_floor: float = 0.15,
    home: Vec3 | None = None,
) -> list[tuple[Emotion, float]]:
    """Décomposition d'une position en émotions, par poursuite du résidu.

    La table des ancres est dense (``happy``/``hopeful`` à 0,999 de cosinus) :
    classer par cosinus ferait de la deuxième entrée un quasi-synonyme de la
    première, et toute position pure paraîtrait ambivalente. On mesure plutôt
    ce que la dominante **n'explique pas** : le poids d'une seconde entrée est
    nul sur une position pure et ne monte que si la position s'en écarte.
    Avec ``home``, la décomposition porte sur l'écart au repos.
    """
    if top_k <= 0:
        return []
    vec = sub(position, home) if home is not None else position
    mag = norm(vec)
    if mag < 1e-6:
        return []
    intensity = min(1.0, mag / MAX_ANCHOR_NORM) if home is None else felt(position, home)[1]

    candidates: list[tuple[Emotion, Vec3, float, float]] = []
    for emotion, anchor in ANCHORS.items():
        if emotion is Emotion.NEUTRAL:
            continue
        direction = sub(anchor, home) if home is not None else anchor
        n = norm(direction)
        if n < 1e-6:
            continue
        unit = scale(direction, 1.0 / n)
        cos = dot(vec, unit) / mag
        if cos < similarity_floor:
            continue
        # Un rayon court (``thinking`` depuis un repos positif) attirerait
        # tout résidu sombre : sa part est amortie par sa longueur.
        damp = 1.0 if home is None else min(1.0, n / INTENSITY_FLOOR)
        candidates.append((emotion, unit, cos, damp))
    if not candidates:
        return []
    candidates.sort(key=lambda c: (-c[2], c[0].value))
    primary, primary_unit, _, _ = candidates.pop(0)
    primary_coeff = dot(vec, primary_unit)
    out: list[tuple[Emotion, float]] = [(primary, round(intensity, 3))]
    if primary_coeff <= 1e-6:
        return out
    residual = sub(vec, scale(primary_unit, primary_coeff))
    previous = intensity
    while candidates and len(out) < top_k:
        best_i, best_coeff, best_score = -1, 0.0, 0.0
        for i, (_, unit, _, damp) in enumerate(candidates):
            coeff = dot(residual, unit)
            if coeff * damp > best_score:
                best_i, best_coeff, best_score = i, coeff, coeff * damp
        if best_i < 0:
            break
        ratio = best_score / primary_coeff
        if ratio < residual_floor:
            break
        emotion, unit, _, _ = candidates.pop(best_i)
        weight = min(previous, ratio * intensity)
        out.append((emotion, round(weight, 3)))
        residual = sub(residual, scale(unit, best_coeff))
        previous = weight
    return out


def is_ambivalent(parts: list[tuple[Emotion, float]], ratio: float = 0.4) -> bool:
    return len(parts) >= 2 and parts[1][1] >= ratio * parts[0][1]


# ── La balise déclarée ────────────────────────────────────────────────────

#: ``[EMOTION:nom]`` ou ``[EMOTION:nom:intensité]`` ; tolère la casse, les
#: espaces et la virgule décimale. Seule la première balise compte ; toutes
#: sont retirées du texte.
TAG = re.compile(r"\[\s*EMOTION\s*:\s*([A-Za-z_]+)\s*(?::\s*(\d+(?:[.,]\d+)?))?\s*\]", re.IGNORECASE)
#: La forme abrégée qu'écrivent souvent les modèles : ``[playful:0.8]``,
#: ``[SAD]`` — reconnue seulement quand le nom est l'une des 29 émotions
#: (``[PAUSE:500]`` ou ``[LAUGH]`` sont des jetons de voix, pas des émotions).
SHORT_TAG = re.compile(r"\[\s*([A-Za-z_]+)\s*(?::\s*(\d+(?:[.,]\d+)?))?\s*\]")
#: Les jetons prosodiques : pour la voix seulement (le frontend les cale sur
#: l'audio). Partout ailleurs — fil relu par le modèle, mémoire, Telegram —
#: ce sont des didascalies parasites.
PROSODY = re.compile(r"\[(?:SIGH|LAUGH|BREATH|PAUSE(?::\s*\d+)?)\]", re.IGNORECASE)
DEFAULT_TAG_INTENSITY = 0.7


@dataclass(frozen=True, slots=True)
class Declared:
    emotion: Emotion
    intensity: float

    def encode(self) -> str:
        return f"{self.emotion.value}:{self.intensity:.3f}"

    @classmethod
    def decode(cls, raw: str | None) -> Declared | None:
        if not raw:
            return None
        name, _, value = raw.partition(":")
        emotion = emotion_of(name)
        if emotion is None:
            return None
        try:
            intensity = float(value) if value else DEFAULT_TAG_INTENSITY
        except ValueError:
            return None
        if not math.isfinite(intensity):
            return None
        return cls(emotion, max(0.0, min(1.0, intensity)))


@dataclass(frozen=True, slots=True)
class Tag:
    """Le résultat de l'analyse : le texte sans balise, ce qui a été déclaré
    (``None`` : rien d'utilisable), et le nom inconnu éventuel."""

    text: str
    declared: Declared | None
    unknown: str | None = None


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def parse_tag(text: str) -> Tag:
    """Pas de balise → ``declared=None`` (aucune impulsion) ; nom hors des 29
    → ``declared=None`` et ``unknown`` renseigné ; ``neutral`` explicite est
    une déclaration comme une autre (une impulsion vers l'origine)."""
    text = text or ""
    short = [m for m in SHORT_TAG.finditer(text) if emotion_of(m.group(1)) is not None]
    match = TAG.search(text) or (short[0] if short else None)
    if match is None:
        return Tag(text.strip(), None)
    clean = SHORT_TAG.sub(lambda m: "" if emotion_of(m.group(1)) is not None else m.group(0), TAG.sub("", text))
    clean = _tidy(clean)
    emotion = emotion_of(match.group(1))
    if emotion is None:
        return Tag(clean, None, match.group(1).lower())
    raw = match.group(2)
    intensity = float(raw.replace(",", ".")) if raw else DEFAULT_TAG_INTENSITY
    return Tag(clean, Declared(emotion, max(0.0, min(1.0, intensity))))


def strip_prosody(text: str) -> str:
    if not text:
        return text
    return _tidy(PROSODY.sub("", text))


# ── Français ──────────────────────────────────────────────────────────────

#: L'adjectif qui suit « tu te sens » (au féminin : c'est elle).
FR: Mapping[Emotion, str] = MappingProxyType({
    Emotion.NEUTRAL: "neutre",
    Emotion.HAPPY: "contente",
    Emotion.EXCITED: "excitée",
    Emotion.LOVE: "amoureuse",
    Emotion.PROUD: "fière",
    Emotion.GRATEFUL: "reconnaissante",
    Emotion.PLAYFUL: "joueuse",
    Emotion.AMUSED: "amusée",
    Emotion.HOPEFUL: "pleine d'espoir",
    Emotion.RELIEVED: "soulagée",
    Emotion.SAD: "triste",
    Emotion.ANGRY: "en colère",
    Emotion.SCARED: "effrayée",
    Emotion.DISGUSTED: "dégoûtée",
    Emotion.FRUSTRATED: "frustrée",
    Emotion.LONELY: "seule",
    Emotion.ANXIOUS: "anxieuse",
    Emotion.BORED: "lasse",
    Emotion.JEALOUS: "jalouse",
    Emotion.SURPRISED: "surprise",
    Emotion.THINKING: "pensive",
    Emotion.CONFUSED: "confuse",
    Emotion.EMBARRASSED: "gênée",
    Emotion.NOSTALGIC: "nostalgique",
    Emotion.DREAMY: "rêveuse",
    Emotion.DETERMINED: "déterminée",
    Emotion.MISCHIEVOUS: "malicieuse",
    Emotion.CURIOUS: "curieuse",
    Emotion.MELANCHOLIC: "mélancolique",
})


def intensity_word(x: float) -> str:
    if x >= 0.8:
        return "très"
    if x >= 0.5:
        return "assez"
    if x >= 0.3:
        return "légèrement"
    return "à peine"


@dataclass(frozen=True, slots=True)
class Appraisal:
    """Ce qu'un événement lui fait ressentir, déclaré par le propriétaire de
    l'événement (un but atteint : de la fierté ; une attente comblée : du
    soulagement). ``toward`` : une personne (sa posture envers elle) ; sinon
    elle-même (son humeur)."""

    emotion: Emotion
    intensity: float
    toward: str | None = None
    reason: str = ""
    #: né d'une relation (une pensée sur ce que quelqu'un a dit) : suit la
    #: contagion du tempérament, comme ce que vit une relation
    relational: bool = False
