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
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from mika.kernel.inspect import Swatch

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


# ── La balise déclarée, et le texte prêt à livrer ─────────────────────────

#: Sans intensité, une balise vaut « net » sur l'échelle donnée au modèle
#: (0,2 une nuance · 0,5 net · 0,8 fort et rare).
DEFAULT_TAG_INTENSITY = 0.5

_VALUE = r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<pct>%)?"
_MD = r"[*_`~]*"
#: ``[EMOTION:nom:intensité]`` et ses variantes réelles : crochets doublés,
#: parenthèses, accolades, ``=`` ou ``,`` comme séparateurs, ``60%``, échelles
#: 0–10 et 0–100, point final parasite, balise non fermée en fin de ligne,
#: débris de markdown autour (``**[EMOTION:…]**``).
TAG = re.compile(
    r"(?P<pre>" + _MD + r")(?:\[\[|\(\(|\{\{|[\[({])\s*[ÉE]MOTIONS?\s*[:=]\s*"
    r"(?P<name>[^\W\d_][\w'’ \-]*?)\s*(?:[:,=/|;]\s*" + _VALUE + r")?[\s.]*"
    r"(?:\]\]|\)\)|\}\}|[\])}]|(?=\n|$))(?P<post>" + _MD + r")",
    re.IGNORECASE)
#: La forme abrégée : ``[playful:0.8]``, ``[SAD]``, ``[triste]``. Jamais un
#: lien markdown (``[curious](https://…)``).
SHORT_TAG = re.compile(
    r"(?P<pre>" + _MD + r")\[\s*(?P<name>[^\W\d_][\w'’\- ]{0,30}?)\s*(?::\s*" + _VALUE + r")?\s*\](?!\()"
    r"(?P<post>" + _MD + r")")
#: La forme en toutes lettres, en toute fin de texte : ``Émotion : happy (0.6)``.
TEXT_TAG = re.compile(
    r"(?P<pre>" + _MD + r")\b[ÉE]motion\s*:\s*(?P<name>[^\W\d_][\w'’\-]*(?: [^\W\d_][\w'’\-]*)?)\s*"
    r"(?:\(\s*" + _VALUE + r"\s*\))?(?P<post>" + _MD + r")[\s.]*$",
    re.IGNORECASE)
#: Ce qui reste d'une balise mal formée (``[EMOTION ?]``) : jamais livré.
TAG_DEBRIS = re.compile(r"\[\s*[ÉE]MOTIONS?\b[^\]\n]*\]", re.IGNORECASE)
#: Les jetons prosodiques, dans la grammaire exacte du frontend : pour la voix
#: seulement (le frontend les cale sur l'audio). Partout ailleurs — fil relu
#: par le modèle, mémoire, messages écrits — ce sont des didascalies parasites.
PROSODY = re.compile(r"\[(?:SIGH|LAUGH|BREATH|PAUSE:\d+)\]")
#: Le silence : un autre étage le reconnaît ; on ne l'abîme jamais.
SILENCE_TOKEN = "[SILENCE]"
_SILENCE = re.compile(_MD.replace("P<", "") + r"\[\s*silence\s*\]" + _MD, re.IGNORECASE)
_BRACKET = re.compile(r"\[\s*([^\[\]\n]{1,40}?)\s*\](?!\()")
_SHOUTED = re.compile(r"[^\W\d_a-zß-ÿ][^\Wa-zß-ÿ]*(?:[ _:.,'’!\-]+[^\Wa-zß-ÿ]+)*[.!]?")
_PAUSE = re.compile(r"pause\s*(?:[:= ]\s*(\d+(?:[.,]\d+)?)\s*(ms|s|sec|secs|secondes?|seconds?)?)?", re.IGNORECASE)
_THINKING = re.compile(r"<\s*(thinking|think|reasoning)\b[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_THINKING_END = re.compile(r"^.*?<\s*/\s*(?:thinking|think|reasoning)\s*>", re.IGNORECASE | re.DOTALL)
_SPEAKER = re.compile(r"^\s*(?:\*\*|__)?(?:Mika|Assistant)(?:\*\*|__)?\s*[:：]\s*", re.IGNORECASE)
_STARRED = re.compile(r"(?<![*\w])(\*{1,2}|_)(?!\s)([^*_\n]{1,60}?)(?<!\s)\1(?![*\w])")
_PARENS = re.compile(r"\(\s*([^()\n]{1,40}?)\s*\)")
#: Les émojis (pictogrammes, symboles, drapeaux, sélecteurs de variante, liants) : sa parole est lue à voix haute, et
#: la consigne de style les interdit — un modèle qui en met quand même ne les fait pas lire (sonde réelle du
#: 2026-10-02 : « bisous Chloé ! 😊 »). Les flèches, les lettres et la ponctuation françaises ne sont pas touchées.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U0000FE0F\U0000200D"
                    "\U00002B50\U00002B55\U00002B1B\U00002B1C\U0000203C\U00002049]")
_QUOTES = (("«", "»"), ("“", "”"), ('"', '"'))

#: Les didascalies qui ont une voix : un rire, un soupir, une respiration.
_VOICED = {
    "[LAUGH]": ("rit", "rire", "rires", "ris", "rigole", "rigolant", "pouffe", "glousse", "ricane", "petit_rire",
                "eclate_de_rire", "eclat_de_rire", "laugh", "laughs", "laughing", "laughter", "giggle", "giggles",
                "giggling", "chuckle", "chuckles", "chuckling"),
    "[SIGH]": ("soupir", "soupirs", "soupire", "soupirant", "petit_soupir", "long_soupir", "grand_soupir", "sigh",
               "sighs", "sighing"),
    "[BREATH]": ("breath", "breaths", "breathe", "breathes", "breathing", "inhale", "inhales", "exhale", "exhales",
                 "inspire", "respire", "souffle", "respiration", "inspiration", "grande_inspiration",
                 "prend_une_inspiration", "prend_une_grande_inspiration"),
}
_VOICE_OF = {word: token for token, words in _VOICED.items() for word in words}
#: Les autres gestes de théâtre : retirés (le visage et le corps les jouent déjà).
_GESTURES = (
    "sourit", "sourire", "souriante", "souriant", "smile", "smiles", "smiling", "grin", "grins", "grinning",
    "rougit", "rougissant", "rougissante", "blush", "blushes", "blushing", "hausse_les_epaules", "shrug", "shrugs",
    "clin_d_oeil", "fait_un_clin_d_oeil", "wink", "winks", "hoche_la_tete", "nod", "nods", "secoue_la_tete",
    "tousse", "toussote", "baille", "s_etire", "se_gratte_la_tete", "penche_la_tete", "hesite", "reflechit",
    "fronce_les_sourcils", "grimace", "tire_la_langue", "croise_les_bras", "leve_les_yeux_au_ciel", "murmure",
    "chuchote", "whispers", "tape_du_pied", "applaudit", "se_mord_la_levre", "regarde_ailleurs", "cligne_des_yeux",
    "fait_la_moue", "boude", "pense", "thinks", "sighs_softly", "hugs", "calin", "fait_un_calin",
)
_GESTURE = frozenset(_GESTURES)
#: Ce qui peut suivre un geste sans changer sa nature (« rit doucement »).
_MANNER = frozenset(("doucement", "nerveusement", "timidement", "tristement", "malicieusement", "legerement",
                     "un_peu", "fort", "aux_eclats", "en_coin", "gene", "genee", "betement", "tendrement", "softly",
                     "nervously", "gently", "quietly", "a_bit", "encore", "franchement", "jaune"))


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
    """Le résultat de l'analyse : le texte prêt à livrer, ce qui a été déclaré
    (``None`` : rien d'utilisable), et le nom inconnu éventuel."""

    text: str
    declared: Declared | None
    unknown: str | None = None


def fold(text: str) -> str:
    """Une clé de comparaison : minuscules sans accents, espaces, tirets et
    apostrophes en ``_``."""
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[\s\-'’]+", "_", plain).strip("_")


def emotion_named(name: str | None) -> Emotion | None:
    """Une émotion d'après un nom écrit par un modèle : le nom canonique, un
    adjectif ou un nom français (« triste », « colère »), un synonyme anglais,
    un intensif devant (``very_happy``, « un peu triste ») ; ``None`` sinon."""
    if not name:
        return None
    key = fold(name)
    found = _SYNONYMS.get(key)
    if found is not None or not key:
        return found
    for prefix in _INTENSIFIERS:
        if key.startswith(prefix + "_"):
            return _SYNONYMS.get(key[len(prefix) + 1:])
    return None


def tag_intensity(raw: str | None, percent: bool = False) -> float:
    """``0.6``, ``0,6``, ``60%``, ``6`` (sur 10), ``60`` (sur 100) → 0,6."""
    if not raw:
        return DEFAULT_TAG_INTENSITY
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return DEFAULT_TAG_INTENSITY
    if not math.isfinite(value):
        return DEFAULT_TAG_INTENSITY
    if percent:
        value /= 100.0
    elif value > 1.0:
        value = value / 10.0 if value <= 10.0 else value / 100.0
    return max(0.0, min(1.0, value))


def _drop_thinking(text: str) -> str:
    text = _THINKING.sub("", text)
    return _THINKING_END.sub("", text)


def _found(m: re.Match[str]) -> tuple[int, int, str, str | None, bool]:
    return m.start(), m.end(), m.group("name").strip(), m.group("value"), bool(m.group("pct"))


def _is_cue(text: str, m: re.Match[str]) -> bool:
    """Une forme abrégée est une balise si elle a une intensité, si elle est
    en tout début ou en toute fin de texte, ou si elle est écrite en
    minuscules ou en capitales — « J'ai lancé [Curious] le jeu » est un titre."""
    name = m.group("name").strip()
    if emotion_named(name) is None or _voice_token(name) is not None or _is_silence_word(name):
        return False
    if m.group("value") or name.islower() or name.isupper():
        return True
    before, after = text[:m.start()].strip(), text[m.end():]
    return not before or not re.sub(r"[\s.!?…]|\[[^\]\n]*\]", "", after)


def _is_silence_word(inner: str) -> bool:
    return fold(inner) == "silence"


def _voice_token(inner: str) -> str | None:
    """Un jeton de voix dans la grammaire exacte du frontend, ou ``None``."""
    m = _PAUSE.fullmatch(inner.strip())
    if m is not None:
        if m.group(1) is None:
            return "[PAUSE:500]"
        value = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "").lower()
        ms = value * 1000.0 if unit.startswith("s") or (not unit and value < 10) else value
        return f"[PAUSE:{max(100, min(5000, round(ms)))}]"
    head = fold(inner.split(":", 1)[0])
    return _VOICE_OF.get(head)


def _stage(inner: str, *, narrow: bool) -> str | None:
    """Une didascalie (« rit doucement », « sourit ») : son jeton de voix, ou
    ``""`` (retirée) ; ``None`` si ce n'en est pas une. ``narrow`` : entre
    parenthèses, on n'ôte que les gestes sûrs, suivis au plus d'une manière."""
    words = fold(inner).split("_")
    if not words or not words[0]:
        return None
    for n in range(min(len(words), 6), 0, -1):
        head = "_".join(words[:n])
        rest = words[n:]
        if head not in _VOICE_OF and head not in _GESTURE:
            continue
        tail = "_".join(rest)
        manner = not rest or tail in _MANNER or (len(rest) == 1 and rest[0].endswith("ment"))
        if narrow and not manner:
            return None
        if not narrow and not manner and len(rest) > 3:
            return None
        return _VOICE_OF.get(head, "")
    return None


def _voice(text: str) -> str:
    """Les jetons entre crochets : la prosodie normalisée, le silence intact,
    les gestes et tout autre jeton en capitales retirés."""

    def sub(m: re.Match[str]) -> str:
        inner = m.group(1)
        if _is_silence_word(inner):
            return SILENCE_TOKEN
        token = _voice_token(inner)
        if token is not None:
            return token
        staged = _stage(inner, narrow=False)
        if staged is not None:
            return staged
        if _SHOUTED.fullmatch(inner.strip()) and sum(ch.isalpha() for ch in inner) >= 2:
            return ""
        return m.group(0)

    text = _SILENCE.sub(SILENCE_TOKEN, text)
    return _BRACKET.sub(sub, TAG_DEBRIS.sub("", text))


def _gestures(text: str) -> str:
    """Les didascalies hors crochets : ``*rit*`` (une voix), ``(sourit)``
    (retirée) ; l'emphase (``*vraiment*``) et les vraies parenthèses restent."""

    def starred(m: re.Match[str]) -> str:
        staged = _stage(m.group(2), narrow=False)
        return m.group(0) if staged is None else staged

    def parens(m: re.Match[str]) -> str:
        staged = _stage(m.group(1), narrow=True)
        return m.group(0) if staged is None else staged

    return _PARENS.sub(parens, _STARRED.sub(starred, text))


def _unquote(text: str) -> str:
    for opening, closing in _QUOTES:
        if len(text) >= 2 and text.startswith(opening) and text.endswith(closing):
            inner = text[len(opening):-len(closing)]
            if opening not in inner and closing not in inner:
                return inner.strip()
    return text


def _tidy(text: str) -> str:
    text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
    text = re.sub(r"(?<=\w)[ \t]+(?=[,.](?:\s|$))", "", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n[ \t]+(?=\S)", lambda m: "\n" + m.group(0)[1:] if m.group(0)[1:].startswith("    ") else "\n",
                  text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    out, cursor = [], 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        out.append(text[cursor:start])
        out.append(" ")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def parse_tag(text: str) -> Tag:
    """Ce qu'elle a déclaré, et le texte prêt à livrer : prosodie dans la
    grammaire du frontend, didascalies et jetons parasites retirés, préfixe
    « Mika : », guillemets englobants et raisonnement ôtés, ponctuation recollée.

    Pas de balise → ``declared=None`` (aucune impulsion) ; plusieurs balises →
    la **dernière** (c'est ce qu'elle ressent en finissant d'écrire) ; un nom
    hors des 29 (et d'aucune table de synonymes) → ``declared=None`` et
    ``unknown`` renseigné. ``neutral`` reste une déclaration : c'est l'affect
    qui décide qu'elle ne fait rien bouger."""
    raw = _drop_thinking(text or "")
    found = [_found(m) for m in TAG.finditer(raw)]
    taken = [(s, e) for s, e, *_ in found]
    for m in SHORT_TAG.finditer(raw):
        if _is_cue(raw, m) and not any(s < m.end() and m.start() < e for s, e in taken):
            found.append(_found(m))
    tail = TEXT_TAG.search(raw)
    if tail is not None and emotion_named(tail.group("name")) is not None and \
            not any(s < tail.end() and tail.start() < e for s, e, *_ in found):
        found.append(_found(tail))
    found.sort()
    clean = _cut(raw, [(s, e) for s, e, *_ in found])
    clean = _EMOJI.sub("", _gestures(_voice(clean)))
    clean = _unquote(_tidy(_SPEAKER.sub("", _tidy(clean))))
    declared: Declared | None = None
    unknown: str | None = None
    for _s, _e, name, value, pct in reversed(found):
        emotion = emotion_named(name)
        if emotion is not None:
            declared = Declared(emotion, tag_intensity(value, pct))
            break
    if declared is None and found:
        unknown = found[-1][2].lower()
    return Tag(clean, declared, unknown)


def strip_prosody(text: str) -> str:
    """Le texte sans voix : pour le fil relu par le modèle, la mémoire, un
    message écrit. Les variantes sont reconnues (un texte ancien n'a pas été
    normalisé) ; le silence reste."""
    if not text:
        return text
    return _tidy(PROSODY.sub("", _voice(text)))


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


#: Le nom de l'émotion, pour dire ce qu'il y a « en dessous » : « un peu de
#: colère », « un peu de soulagement » (voir ``partitive``).
NOUN: Mapping[Emotion, str] = MappingProxyType({
    Emotion.NEUTRAL: "calme",
    Emotion.HAPPY: "joie",
    Emotion.EXCITED: "excitation",
    Emotion.LOVE: "tendresse",
    Emotion.PROUD: "fierté",
    Emotion.GRATEFUL: "reconnaissance",
    Emotion.PLAYFUL: "espièglerie",
    Emotion.AMUSED: "amusement",
    Emotion.HOPEFUL: "espoir",
    Emotion.RELIEVED: "soulagement",
    Emotion.SAD: "tristesse",
    Emotion.ANGRY: "colère",
    Emotion.SCARED: "peur",
    Emotion.DISGUSTED: "dégoût",
    Emotion.FRUSTRATED: "frustration",
    Emotion.LONELY: "solitude",
    Emotion.ANXIOUS: "inquiétude",
    Emotion.BORED: "lassitude",
    Emotion.JEALOUS: "jalousie",
    Emotion.SURPRISED: "surprise",
    Emotion.THINKING: "réflexion",
    Emotion.CONFUSED: "confusion",
    Emotion.EMBARRASSED: "gêne",
    Emotion.NOSTALGIC: "nostalgie",
    Emotion.DREAMY: "rêverie",
    Emotion.DETERMINED: "détermination",
    Emotion.MISCHIEVOUS: "malice",
    Emotion.CURIOUS: "curiosité",
    Emotion.MELANCHOLIC: "mélancolie",
})


def partitive(emotion: Emotion) -> str:
    """« de colère », « d'amusement » : ce qui suit « un peu »."""
    noun = NOUN[emotion]
    return f"d'{noun}" if fold(noun)[:1] in "aeiouyh" else f"de {noun}"


#: Les noms qu'écrivent les modèles, rabattus sur les 29 (clés : ``fold``).
_ALIASES: Mapping[Emotion, tuple[str, ...]] = MappingProxyType({
    Emotion.NEUTRAL: ("neutre", "calme", "calm", "neutral", "rien", "none"),
    Emotion.HAPPY: ("content", "heureuse", "heureux", "joyeuse", "joyeux", "joie", "bonheur", "ravie", "ravi",
                    "joy", "joyful", "glad", "cheerful", "pleased", "happiness", "contentement"),
    Emotion.EXCITED: ("excite", "excitation", "enthousiaste", "enthousiasme", "surexcitee", "excitement",
                      "enthusiastic", "thrilled"),
    Emotion.LOVE: ("amour", "amoureux", "tendresse", "tendre", "affection", "affectueuse", "loving", "affectionate",
                   "tender", "warm", "warmth", "caring"),
    Emotion.PROUD: ("fier", "fierte", "pride"),
    Emotion.GRATEFUL: ("reconnaissant", "reconnaissance", "gratitude", "thankful", "touchee", "touche", "touched"),
    Emotion.PLAYFUL: ("joueur", "espiegle", "taquine", "taquin", "enjouee", "enjoue", "fun", "silly"),
    Emotion.AMUSED: ("amuse", "amusement", "funny", "entertained", "rieuse"),
    Emotion.HOPEFUL: ("espoir", "pleine_d_espoir", "plein_d_espoir", "optimiste", "hope", "optimistic"),
    Emotion.RELIEVED: ("soulage", "soulagement", "relief", "apaisee", "apaise", "serene", "sereine"),
    Emotion.SAD: ("tristesse", "chagrin", "peinee", "peine", "sadness", "unhappy", "down", "upset", "sorrow"),
    Emotion.ANGRY: ("colere", "en_colere", "fachee", "fache", "enervee", "enerve", "furieuse", "furieux", "anger",
                    "mad", "furious", "rage"),
    Emotion.SCARED: ("effraye", "peur", "apeuree", "terrifiee", "fear", "afraid", "frightened", "terrified"),
    Emotion.DISGUSTED: ("degoute", "degout", "ecoeuree", "disgust", "grossed_out"),
    Emotion.FRUSTRATED: ("frustre", "frustration", "agacee", "agace", "irritee", "irrite", "annoyed", "irritated",
                         "agacement"),
    Emotion.LONELY: ("seul", "solitude", "isolee", "alone", "loneliness"),
    Emotion.ANXIOUS: ("anxieux", "anxiete", "inquiete", "inquiet", "inquietude", "stressee", "stresse", "angoissee",
                      "nerveuse", "anxiety", "worried", "nervous", "stressed", "worry"),
    Emotion.BORED: ("las", "ennui", "ennuyee", "ennuye", "blasee", "boredom", "fatiguee", "tired", "weary"),
    Emotion.JEALOUS: ("jaloux", "jalousie", "envieuse", "jealousy", "envious"),
    Emotion.SURPRISED: ("surpris", "surprise", "etonnee", "etonne", "stupefaite", "surprised", "shocked",
                        "astonished", "amazed"),
    Emotion.THINKING: ("pensif", "reflechie", "songeuse", "songeur", "reflexion", "thoughtful", "pensive",
                       "reflective", "contemplative"),
    Emotion.CONFUSED: ("confus", "confusion", "perdue", "perplexe", "puzzled", "confusion"),
    Emotion.EMBARRASSED: ("genee", "gene", "embarrassee", "embarrasse", "timide", "gene", "embarrassment", "shy",
                          "awkward"),
    Emotion.NOSTALGIC: ("nostalgie", "nostalgia"),
    Emotion.DREAMY: ("reveur", "reverie", "dreaming", "rever"),
    Emotion.DETERMINED: ("determine", "determination", "motivee", "motive", "resolue", "motivated", "resolute"),
    Emotion.MISCHIEVOUS: ("malicieux", "malice", "coquine", "coquin", "espiegle_malicieuse", "cheeky", "teasing",
                          "mischief", "sly"),
    Emotion.CURIOUS: ("curieux", "curiosite", "intriguee", "intrigue", "curiosity", "intrigued", "interested"),
    Emotion.MELANCHOLIC: ("melancolie", "melancolique", "melancholy", "morose", "cafardeuse", "blue"),
})


def _synonyms() -> dict[str, Emotion]:
    table: dict[str, Emotion] = {}
    for emotion in Emotion:
        table[emotion.value] = emotion
        table.setdefault(fold(FR[emotion]), emotion)
        table.setdefault(fold(NOUN[emotion]), emotion)
    for emotion, words in _ALIASES.items():
        for word in words:
            table.setdefault(fold(word), emotion)
    return table


_SYNONYMS: Mapping[str, Emotion] = MappingProxyType(_synonyms())
#: Ce qu'un modèle écrit parfois devant le nom (``very_happy``, « un peu triste »).
_INTENSIFIERS = ("very", "really", "super", "so", "slightly", "a_bit", "a_little", "quite", "tres", "un_peu",
                 "plutot", "assez", "legerement", "vraiment", "trop", "hyper", "un_brin", "un_poil", "bien")


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


def emotion_cell(emotion: Emotion | str | None, intensity: float | None = None) -> Swatch | str:
    """Une émotion pour la console : sa pastille de couleur, son nom en français,
    son intensité (« — » si elle est inconnue)."""
    e = emotion if isinstance(emotion, Emotion) else emotion_of(emotion)
    if e is None:
        return "—"
    return Swatch(FR[e], "emotion", e.value, intensity)
