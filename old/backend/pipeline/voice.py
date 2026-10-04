"""Voice output as a routed modality, not a frontend detail.

Text and speech leave Mika through the *same* channels. A reply may go out
as text, as an audio clip, or as both, depending on where the recipient is
reachable and whether speaking is appropriate right now.

Three sinks, with genuinely different context rules:

``SCREEN``
    The frontend app. The person is looking at it, so speaking is the
    default — this is today's browser TTS path.

``MESSAGE``
    An asynchronous voice note (Telegram voice, MMS audio). The recipient
    plays it when they choose, so the *time of day is irrelevant*: a voice
    note at 3am is fine, a spoken sentence at 3am is not.

``SPEAKER``
    A physical speaker in a room. This is the one that needs care: it emits
    sound into a shared space with no "play later". It stays silent during
    quiet hours, while Mika is asleep, and when the recipient isn't actually
    in the room.

``decide_voice()`` is a pure function so this policy is testable without a
running system. Synthesis itself is pluggable: no synthesizer is registered
by default (the frontend does its own TTS), and registering one — Piper,
edge-tts, an API — is what lights up MESSAGE and SPEAKER delivery.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from old.backend.configs.runtime import cfg_float, cfg_int

logger = logging.getLogger(__name__)


# ── Sinks ────────────────────────────────────────────────────────


class VoiceSink:
    """Where speech would come out. String constants, not an Enum, so they
    travel in JSON payloads unchanged."""
    SCREEN = "screen"      # the frontend app (browser TTS)
    MESSAGE = "message"    # async voice note (Telegram, SMS)
    SPEAKER = "speaker"    # open-air speaker in a shared room


class VoicePersona:
    """*Whose* voice is speaking — Mika addressing someone, or Mika thinking.

    Her inner monologue ("oh tiens, si j'envoyais un message à...", "mmm,
    mais c'est génial ça") is not speech directed at anyone. Given its own
    vocal identity — quieter, slower, lower, murmured — it reads as thought
    overheard rather than a sentence said to you, which is the whole point
    of letting it out loud at all.
    """
    SPEAKING = "speaking"  # addressed to a person
    INNER = "inner"        # thinking out loud


@dataclass(frozen=True)
class VoiceProfile:
    """Multipliers a TTS applies on top of the emotion modulation."""
    pitch: float
    rate: float
    gain: float


# Repli des réglages ``voice.profile.<persona>.<pitch|rate|gain>`` — mêmes
# valeurs au bit près, servies quand le registre est hors d'atteinte.
VOICE_PROFILES: dict[str, VoiceProfile] = {
    VoicePersona.SPEAKING: VoiceProfile(pitch=1.0, rate=1.0, gain=1.0),
    # Murmured: a touch lower and slower, clearly quieter.
    VoicePersona.INNER: VoiceProfile(pitch=0.94, rate=0.9, gain=0.45),
}


def profile_for(persona: str) -> VoiceProfile:
    """Les multiplicateurs de la persona, tels que configurés.

    Une persona inconnue retombe sur SPEAKING : un profil est un réglage de
    rendu, jamais une raison de ne pas parler.
    """
    if persona not in VOICE_PROFILES:
        persona = VoicePersona.SPEAKING
    repli = VOICE_PROFILES[persona]
    return VoiceProfile(
        pitch=cfg_float(f"voice.profile.{persona}.pitch", repli.pitch, mini=0.0),
        rate=cfg_float(f"voice.profile.{persona}.rate", repli.rate, mini=0.0),
        gain=cfg_float(f"voice.profile.{persona}.gain", repli.gain, mini=0.0),
    )


# Sources that mean "Mika acted on her own initiative", i.e. thinking aloud
# rather than answering. `conscience` is her decision loop; the others are
# module- and drive-driven initiatives routed as INTERNAL_TRIGGER.
INNER_SOURCES = frozenset({"conscience", "drive", "rumination"})


def persona_for_source(source: str, *, addressed: bool = False) -> str:
    """Classify a turn's voice identity from its originating source.

    ``addressed`` marks an initiative that genuinely targets a person (Mika
    decided to *tell* them something) — that is speech, not musing.
    """
    if addressed:
        return VoicePersona.SPEAKING
    return (
        VoicePersona.INNER
        if source in INNER_SOURCES
        else VoicePersona.SPEAKING
    )


# Hours during which a SPEAKER must stay quiet (open-air sound only).
# Replis de ``voice.quiet_hours_start`` / ``voice.quiet_hours_end``.
QUIET_HOURS_START = 22
QUIET_HOURS_END = 8


@dataclass(frozen=True)
class VoiceDecision:
    """Whether to speak on a given sink, and why (the reason is logged and
    surfaced to the frontend so silence is never mysterious)."""
    speak: bool
    reason: str


def in_quiet_hours(hour: int) -> bool:
    """Quiet window wraps midnight: [22h, 08h) par défaut.

    L'expression suppose que la fenêtre **enjambe minuit** (``heure >= début
    OU heure < fin``). Un couple qui ne l'enjambe pas — début 8, fin 22 —
    n'est pas refusé, il inverse le sens : ce sont alors les heures de
    journée qui deviennent calmes. Les deux réglages le disent.
    """
    debut = cfg_int("voice.quiet_hours_start", QUIET_HOURS_START, mini=0, maxi=23)
    fin = cfg_int("voice.quiet_hours_end", QUIET_HOURS_END, mini=0, maxi=23)
    return hour >= debut or hour < fin


def decide_voice(
    sink: str,
    *,
    hour: int,
    sleep_phase: str = "awake",
    person_present: bool = True,
    muted: bool = False,
    persona: str = VoicePersona.SPEAKING,
) -> VoiceDecision:
    """Should Mika speak out loud on ``sink`` right now?

    Pure — every input is passed in. ``person_present`` means the recipient
    is actually reachable at that sink (in the room for a SPEAKER, connected
    for a SCREEN); ``muted`` is an explicit user override; ``persona`` says
    whether this is speech aimed at someone or Mika thinking aloud.
    """
    if muted:
        return VoiceDecision(False, "muted")

    inner = persona == VoicePersona.INNER

    if sink == VoiceSink.MESSAGE:
        # Never push a stray thought to someone's phone. Musing out loud in
        # a room she shares is charming; mailing it is not.
        if inner:
            return VoiceDecision(False, "inner_thought_not_sent")
        # A voice note is consumed on the recipient's terms — the only thing
        # that suppresses it is an explicit mute.
        return VoiceDecision(True, "voice_note")

    if sink == VoiceSink.SPEAKER:
        # Sound in a shared room: the strictest sink.
        if not person_present:
            # Thinking aloud to an empty room is the one case where absence
            # is not a reason to stay silent — nobody is disturbed, and this
            # is exactly how a mind at work sounds.
            if not inner:
                return VoiceDecision(False, "nobody_in_the_room")
        if sleep_phase != "awake":
            return VoiceDecision(False, f"asleep({sleep_phase})")
        if in_quiet_hours(hour):
            return VoiceDecision(False, "quiet_hours")
        return VoiceDecision(True, "inner_speaker_ok" if inner else "speaker_ok")

    if sink == VoiceSink.SCREEN:
        if not person_present:
            return VoiceDecision(False, "no_client_connected")
        # Une pensée murmurée la nuit est cohérente — c'est ce qui rend la
        # nuit habitée plutôt que muette. Une phrase adressée à quelqu'un en
        # plein deep_sleep ne l'est pas : l'avatar a les yeux fermés et la
        # scène est tamisée pendant que le TTS parle. Un vrai message la
        # réveille avant d'arriver ici (router._note_live_interaction), donc
        # une vraie question ne tombe jamais dans cette garde.
        if sleep_phase != "awake" and not inner:
            return VoiceDecision(False, f"asleep({sleep_phase})")
        return VoiceDecision(True, "inner_screen_ok" if inner else "screen_ok")

    return VoiceDecision(False, f"unknown_sink({sink})")


# ── Synthesis (pluggable) ────────────────────────────────────────


@dataclass(frozen=True)
class VoiceClip:
    """A rendered utterance ready to be attached to an outbound message."""
    data: bytes
    mime_type: str
    duration_s: float = 0.0


class SpeechSynthesizer(Protocol):
    """Anything that turns text into audio bytes.

    Implementations live outside this module (a local Piper binary, an HTTP
    TTS API, ...) and are attached with ``register_synthesizer``.
    """

    async def synthesize(
        self,
        text: str,
        *,
        emotion: str = "neutral",
        intensity: float = 0.0,
        profile: VoiceProfile | None = None,
    ) -> VoiceClip | None:
        ...


_synthesizer: SpeechSynthesizer | None = None


def register_synthesizer(synth: SpeechSynthesizer | None) -> None:
    """Install (or clear, with ``None``) the process-wide synthesizer."""
    global _synthesizer
    _synthesizer = synth
    logger.info("Speech synthesizer %s", "registered" if synth else "cleared")


def has_synthesizer() -> bool:
    return _synthesizer is not None


async def synthesize(
    text: str,
    *,
    emotion: str = "neutral",
    intensity: float = 0.0,
    persona: str = VoicePersona.SPEAKING,
) -> VoiceClip | None:
    """Render ``text`` to audio, or ``None`` when no synthesizer is installed.

    Never raises: a failing TTS must degrade to text delivery, not drop the
    message.
    """
    if _synthesizer is None:
        return None
    try:
        return await _synthesizer.synthesize(
            text, emotion=emotion, intensity=intensity,
            profile=profile_for(persona),
        )
    except Exception:
        logger.exception("Speech synthesis failed — falling back to text")
        return None
