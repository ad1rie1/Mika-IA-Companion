"""La voix, une modalité routée : parler ou non, sur quel support, avec
quelle voix. Politique pure — l'heure, la phase de sommeil et la présence
sont passées en argument.

- ``screen`` : l'application (synthèse du navigateur) ; parle par défaut.
- ``message`` : note vocale asynchrone ; l'heure n'y fait rien, une pensée
  intérieure n'est jamais envoyée.
- ``speaker`` : haut-parleur dans une pièce partagée ; silencieux la nuit,
  pendant son sommeil, et quand la personne n'est pas là.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

SCREEN = "screen"
MESSAGE = "message"
SPEAKER = "speaker"

SPEAKING = "speaking"  # adressée à quelqu'un
INNER = "inner"  # elle pense tout haut


@dataclass(frozen=True, slots=True)
class Profile:
    pitch: float
    rate: float
    gain: float

    def to_dict(self) -> dict[str, float]:
        return {"pitch": self.pitch, "rate": self.rate, "gain": self.gain}


PROFILES: Mapping[str, Profile] = MappingProxyType({
    SPEAKING: Profile(1.0, 1.0, 1.0),
    INNER: Profile(0.94, 0.9, 0.45),
})


def profile_for(persona: str) -> Profile:
    return PROFILES.get(persona, PROFILES[SPEAKING])


@dataclass(frozen=True, slots=True)
class Decision:
    speak: bool
    reason: str


def quiet(hour: int, start: int = 22, end: int = 8) -> bool:
    return hour >= start or hour < end


def decide(sink: str, *, hour: int, sleep_phase: str = "awake", present: bool = True, muted: bool = False,
           persona: str = SPEAKING) -> Decision:
    if muted:
        return Decision(False, "muted")
    inner = persona == INNER
    if sink == MESSAGE:
        return Decision(False, "inner_thought_not_sent") if inner else Decision(True, "voice_note")
    if sink == SPEAKER:
        if not present and not inner:
            return Decision(False, "nobody_in_the_room")
        if sleep_phase != "awake":
            return Decision(False, f"asleep({sleep_phase})")
        if quiet(hour):
            return Decision(False, "quiet_hours")
        return Decision(True, "inner_speaker_ok" if inner else "speaker_ok")
    if sink == SCREEN:
        if not present:
            return Decision(False, "no_client_connected")
        if sleep_phase != "awake" and not inner:
            return Decision(False, f"asleep({sleep_phase})")
        return Decision(True, "inner_screen_ok" if inner else "screen_ok")
    return Decision(False, f"unknown_sink({sink})")
