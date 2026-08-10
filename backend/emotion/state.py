from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from emotion import pad
from emotion.dynamics import OscillatorState
from emotion.types import Emotion


# Libellés d'affichage pour la prose du prompt. Recopiés de
# ``GestionSysteme/formatting.py::EMOTION_FR`` plutôt qu'importés : l'app
# d'administration dépend du domaine, l'importer ici inverserait le sens (ce
# module est chargé par ``emotion.engine``, lui-même par ``conscience``,
# ``pipeline`` et ``projects``). Même arbitrage que la copie déjà assumée dans
# ``emotion/config_schema.py`` ; un test vérifie que les deux tables restent
# alignées.
#
# Un seul écart volontaire : ``bored`` s'affiche « s'ennuie », un verbe, qui
# n'entre pas dans « tu te sens … ».
EMOTION_PROMPT_FR: dict[str, str] = {
    "neutral": "neutre",
    "happy": "contente",
    "excited": "excitée",
    "love": "amoureuse",
    "proud": "fière",
    "grateful": "reconnaissante",
    "playful": "joueuse",
    "amused": "amusée",
    "hopeful": "pleine d'espoir",
    "relieved": "soulagée",
    "sad": "triste",
    "angry": "en colère",
    "scared": "effrayée",
    "disgusted": "dégoûtée",
    "frustrated": "frustrée",
    "lonely": "seule",
    "anxious": "anxieuse",
    "bored": "lasse",
    "jealous": "jalouse",
    "surprised": "surprise",
    "thinking": "pensive",
    "confused": "confuse",
    "embarrassed": "gênée",
    "nostalgic": "nostalgique",
    "dreamy": "rêveuse",
    "determined": "déterminée",
    "mischievous": "malicieuse",
    "curious": "curieuse",
    "melancholic": "mélancolique",
}

#: Au-delà, l'humeur ne se lit plus « dans la pente naturelle ».
MARKED_INTENSITY = 0.6


#: Pendant combien de temps « ce qu'elle vient de déclarer » reste ce qu'elle
#: éprouve. Calé sur la constante de temps de l'oscillateur au tempérament par
#: défaut (~11 min 30) : au-delà, l'état a réellement bougé et c'est la
#: position qui dit vrai.
DECLARED_WINDOW_S: float = 700.0


def _fr(emotion: Emotion) -> str:
    return EMOTION_PROMPT_FR.get(emotion.value, emotion.value)


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
        f" Mais il y a aussi une nuance de {_fr(secondary)} "
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
    #: Point de repos propre à cette personne : une moyenne lissée de ce
    #: qu'elle a déjà provoqué, jamais une lecture instantanée. ``None`` tant
    #: qu'elle n'a rien provoqué — l'oscillateur revient alors au repos
    #: circadien commun, comme pour un inconnu.
    anchor: pad.Vec3 | None = None
    #: Ce que le dernier tour a DÉCLARÉ éprouver envers cette personne, et
    #: quand (`time.time()`).
    #:
    #: La balise `[EMOTION:]` est ce qu'elle a ressenti en écrivant ; la
    #: position PAD dit où en est la relation. Les deux sont vrais et ne
    #: répondent pas à la même question. Les confondre faisait dire au prompt
    #: une émotion qu'elle n'avait jamais prononcée : l'impulsion ne parcourt
    #: que la moitié de la distance à l'ancre déclarée, et le vecteur mélangé
    #: qui en résulte a souvent pour plus proche voisin une TROISIÈME émotion.
    #: Mesuré : sur cinq états de départ réalistes, « embarrassed » revenait
    #: en « effrayée », « amused » en « love », « grateful » en « excited ».
    last_declared: tuple[Emotion, float] | None = None
    last_declared_at: float = 0.0

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

    def fresh_declaration(
        self, window_s: float = DECLARED_WINDOW_S,
    ) -> tuple[Emotion, float] | None:
        """Ce qu'elle vient de déclarer, si c'est encore récent.

        Au-delà de la fenêtre, ce n'est plus ce qu'elle éprouve : c'est un
        souvenir de tour, et c'est l'oscillateur qui reprend la parole.
        """
        if self.last_declared is None:
            return None
        if time.time() - self.last_declared_at > window_s:
            return None
        return self.last_declared

    def to_prompt_description(
        self, declared_window_s: float = DECLARED_WINDOW_S,
    ) -> str:
        """Ce que le prompt lui dit éprouver envers cette personne.

        Priorité à ce qu'elle vient de DÉCLARER : c'est le seul énoncé dont on
        soit sûr qu'il correspond à quelque chose qu'elle a pensé. L'oscillateur
        fournit alors la nuance (l'ambivalence de fond) mais ne renomme plus le
        sentiment principal. Passé la fenêtre, la déclaration n'est plus
        d'actualité et la position redevient la source — c'est bien elle qui
        porte « où en est la relation ».
        """
        declaree = self.fresh_declaration(declared_window_s)
        if declaree is not None:
            label, intensity = declaree
        else:
            label, intensity = pad.pad_to_label(self.dynamic.position)
            if intensity < 0.1:
                return "Tu n'as pas de sentiment particulier envers cette personne."

        intensity_word = _intensity_label(intensity)
        base = (
            f"Envers cette personne, tu te sens {intensity_word} {_fr(label)}."
        )
        # La nuance vient de la position, mais on ne l'énonce que si elle
        # apporte VRAIMENT autre chose : citer « une nuance de X » quand X est
        # déjà le sentiment principal ne dit rien, et la citer alors qu'elle
        # contredit la balise est exactement le renommage qu'on vient de retirer.
        blend = [
            (emo, poids)
            for emo, poids in pad.pad_to_blend(self.dynamic.position, top_k=3)
            if emo is not label
        ]
        if declaree is not None:
            blend = blend[:1]
            if blend and blend[0][1] >= 0.25:
                # Tournure choisie pour marcher avec les 29 adjectifs sans
                # élision : « un fond de effrayée » n'est pas du français.
                return base + (
                    f" Et en dessous, tu te sens aussi un peu {_fr(blend[0][0])} — "
                    "ton humeur n'est pas mono-couleur."
                )
            return base
        return base + _format_blend_phrase(
            pad.pad_to_blend(self.dynamic.position, top_k=2)
        )


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
        # Brancher sur le seul libellé disait « comme d'habitude » aussi bien
        # d'un tempérament à peine teinté que d'une euphorie pleine : avec le
        # défaut ``happy``, toute l'amplitude dans la direction du personnage
        # était muette dans le prompt pendant que le visage la montrait.
        if intensity < 0.1:
            base = f"Ton humeur générale est {_fr(default_mood)}, comme d'habitude."
        elif label != default_mood:
            base = (
                f"Ton humeur générale en ce moment est "
                f"{_intensity_label(intensity)} {_fr(label)}, "
                f"alors que normalement tu es plutôt {_fr(default_mood)}."
            )
        elif intensity >= MARKED_INTENSITY:
            base = (
                f"Ton humeur générale est {_fr(label)}, nettement plus "
                "que d'habitude."
            )
        else:
            base = (
                f"Ton humeur générale est {_intensity_label(intensity)} "
                f"{_fr(label)}, dans ta pente naturelle."
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
            return f"{_intensity_label(self.intensity)} {_fr(self.emotion)}"
        if not self.is_ambivalent():
            primary, weight = self.blend[0]
            return f"{_intensity_label(weight)} {_fr(primary)}"
        primary, _ = self.blend[0]
        secondary, _ = self.blend[1]
        return (
            f"principalement {_fr(primary)}, "
            f"avec une nuance de {_fr(secondary)}"
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
