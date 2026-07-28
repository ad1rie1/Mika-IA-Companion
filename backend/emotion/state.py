import time
from collections import deque
from dataclasses import dataclass, field

from emotion import pad
from emotion.dynamics import OscillatorState
from emotion.types import Emotion


def _format_blend_phrase(blend: list[tuple[Emotion, float]]) -> str:
    """Compact French phrase expressing an ambivalent PAD blend.

    Returns '' if the blend is not meaningfully ambivalent.
    """
    if len(blend) < 2:
        return ""
    primary, p_w = blend[0]
    secondary, s_w = blend[1]
    if s_w < 0.4 * p_w:
        return ""
    return (
        f" Mais il y a aussi une nuance de {secondary.value} ({s_w:.1f}) "
        "en sous-texte — ton humeur n'est pas mono-couleur."
    )


@dataclass(frozen=True)
class Temperament:
    """Personality-driven parameters mapped to oscillator physics.

    - volatility       : how easily the state moves (inverse mass)
    - intensity_base   : impulse gain scaling
    - recovery_speed   : spring stiffness pulling back to default_mood
    - global_bleed     : coupling from person moods into the global mood
    - default_mood     : home position of the oscillator (set via its anchor)
    """
    volatility: float = 0.7
    intensity_base: float = 0.6
    recovery_speed: float = 0.5
    default_mood: Emotion = Emotion.HAPPY
    global_bleed: float = 0.3


#: Préfixe des clés de configuration qui portent le tempérament. Publié parce
#: que le moteur s'y abonne pour recharger à chaud.
TEMPERAMENT_PREFIX = "emotion.temperament."


def load_temperament() -> Temperament:
    """Le tempérament effectif, lu depuis la configuration.

    Unique source : les cinq ``emotion.temperament.*`` du registre. Ce bloc
    vivait auparavant dans ``personality.yaml``, où il ne se modifiait qu'en
    éditant un fichier puis en redémarrant — alors que c'est un réglage, pas
    une description du personnage : les quatre nombres ne se lisent pas, ils
    s'essaient. Le YAML garde ce qui se rédige (ton, traits, manies), la
    configuration prend ce qui se règle.

    Ne lève jamais : la lecture peut arriver avant que la base ne soit
    joignable, et un moteur d'émotion qui refuse de démarrer parce qu'un
    curseur est illisible coûte plus cher que le curseur par défaut.
    """
    from configs.service import config_service

    def value(name, fallback):
        try:
            got = config_service.get(f"{TEMPERAMENT_PREFIX}{name}")
        except Exception:
            return fallback
        return fallback if got is None else got

    defaults = Temperament()
    try:
        default_mood = Emotion(value("default_mood", defaults.default_mood.value))
    except ValueError:
        default_mood = defaults.default_mood

    def number(name, fallback):
        try:
            return float(value(name, fallback))
        except (TypeError, ValueError):
            return fallback

    return Temperament(
        volatility=number("volatility", defaults.volatility),
        intensity_base=number("intensity_base", defaults.intensity_base),
        recovery_speed=number("recovery_speed", defaults.recovery_speed),
        default_mood=default_mood,
        global_bleed=number("global_bleed", defaults.global_bleed),
    )


@dataclass
class EmotionHistoryEntry:
    """Single entry in an emotion timeline."""
    timestamp: float
    emotion: Emotion
    intensity: float
    source: str  # "impulse", "decay"


@dataclass
class PersonMood:
    """Per-person emotional state. Tracks how the VTuber feels about one specific person.

    The authoritative state is the oscillator (`dynamic`) in PAD space.
    `emotion` / `intensity` are derived labels for display and I/O.
    """
    person_id: str
    dynamic: OscillatorState = field(default_factory=OscillatorState)
    last_interaction: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    history: deque[EmotionHistoryEntry] = field(
        default_factory=lambda: deque(maxlen=100)
    )

    @property
    def emotion(self) -> Emotion:
        label, _ = pad.pad_to_label(self.dynamic.position)
        return label

    @property
    def intensity(self) -> float:
        _, value = pad.pad_to_label(self.dynamic.position)
        return value

    def to_dict(self) -> dict:
        label, intensity = pad.pad_to_label(self.dynamic.position)
        return {
            "emotion": label.value,
            "intensity": round(intensity, 2),
        }

    def to_prompt_description(self) -> str:
        label, intensity = pad.pad_to_label(self.dynamic.position)
        if intensity < 0.1:
            return "Tu n'as pas de sentiment particulier envers cette personne."

        intensity_word = _intensity_label(intensity)
        base = (
            f"Envers cette personne, tu te sens {intensity_word} "
            f"{label.value} (intensite: {intensity:.1f})."
        )
        blend = pad.pad_to_blend(self.dynamic.position, top_k=2)
        return base + _format_blend_phrase(blend)


@dataclass
class GlobalMood:
    """Global emotional state, independent of who is talking."""
    dynamic: OscillatorState = field(default_factory=OscillatorState)
    last_update: float = field(default_factory=time.time)

    @property
    def emotion(self) -> Emotion:
        label, _ = pad.pad_to_label(self.dynamic.position)
        return label

    @property
    def intensity(self) -> float:
        _, value = pad.pad_to_label(self.dynamic.position)
        return value

    def to_dict(self) -> dict:
        label, intensity = pad.pad_to_label(self.dynamic.position)
        return {
            "emotion": label.value,
            "intensity": round(intensity, 2),
        }

    def to_prompt_description(self, default_mood: Emotion) -> str:
        label, intensity = pad.pad_to_label(self.dynamic.position)
        if intensity < 0.1 or label == default_mood:
            base = f"Ton humeur generale est {default_mood.value}, comme d'habitude."
        else:
            intensity_word = _intensity_label(intensity)
            base = (
                f"Ton humeur generale en ce moment est {intensity_word} "
                f"{label.value} (intensite: {intensity:.1f}), "
                f"alors que normalement tu es plutot {default_mood.value}."
            )
        blend = pad.pad_to_blend(self.dynamic.position, top_k=2)
        return base + _format_blend_phrase(blend)


@dataclass(frozen=True)
class MessageEmotion:
    """Computed emotion for a specific message: blend of person + global.

    `emotion` + `intensity` remain the dominant label (backward-compatible
    with the frontend and existing prompts). `blend` exposes the top-K
    emotion components so callers who want ambivalence can consume them.
    """
    emotion: Emotion
    intensity: float
    person_emotion: Emotion
    person_intensity: float
    global_emotion: Emotion
    global_intensity: float
    blend: tuple[tuple[Emotion, float], ...] = ()

    def to_dict(self) -> dict:
        return {
            "emotion": self.emotion.value,
            "intensity": round(self.intensity, 2),
            "blend": [
                {"emotion": e.value, "weight": round(w, 2)}
                for e, w in self.blend
            ],
        }

    def is_ambivalent(self) -> bool:
        """True if at least two anchors have non-trivial weight."""
        if len(self.blend) < 2:
            return False
        # Secondary must be at least 40% of the primary to be meaningful.
        return self.blend[1][1] >= 0.4 * self.blend[0][1]

    def to_prompt_description(self) -> str:
        """Natural-language description that expresses ambivalence if any."""
        if not self.blend:
            return f"{self.emotion.value} (intensite {self.intensity:.1f})"
        if not self.is_ambivalent():
            primary, weight = self.blend[0]
            return f"{primary.value} (intensite {weight:.1f})"
        primary, p_w = self.blend[0]
        secondary, s_w = self.blend[1]
        return (
            f"principalement {primary.value} ({p_w:.1f}), "
            f"mais aussi une nuance de {secondary.value} ({s_w:.1f})"
        )


def _intensity_label(intensity: float) -> str:
    if intensity >= 0.8:
        return "tres"
    elif intensity >= 0.5:
        return "assez"
    elif intensity >= 0.3:
        return "legerement"
    else:
        return "a peine"
