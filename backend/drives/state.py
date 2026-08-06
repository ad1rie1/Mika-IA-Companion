"""Drive state — pure dataclasses, no Django dependency.

Kept pure so the core logic is testable without a DB / event loop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class DriveKind(str, Enum):
    """The four intrinsic drives.

    CURIOSITY  : need to learn, discover, ask questions about the world/person
    SOCIAL     : need for connection, being acknowledged, hearing back
    EXPRESSION : need to share thoughts, opinions, jokes that pop up
    REST       : need for silence, low-stimulation recovery
    """
    CURIOSITY = "curiosity"
    SOCIAL = "social"
    EXPRESSION = "expression"
    REST = "rest"


@dataclass
class DriveParams:
    """Per-drive parameters (clamped to sensible ranges)."""
    growth_rate: float = 0.02         # tension added per second when unsatisfied
    decay_on_satisfy: float = 0.5      # fraction of tension removed when assouvi
    weight: float = 0.25               # contribution to conscience score at tension=1.0
    satisfy_threshold: float = 0.4     # below this, drive doesn't contribute


# Default per-kind parameters. Calibrated so that a drive devient notable
# (~0.5) apres une dizaine de minutes d'inactivite et ne pousse fortement
# (~0.9) qu'au bout de 20 a 25 minutes.
#
# Les taux precedents (0.0030 / 0.0025 / 0.0020) saturaient les trois
# pulsions positives en 8 min 20 au plus tard, cycle de decision tournant
# toutes les 30 s : leur somme restait donc collee a +0.90, le facteur 9
# valait la constante +0.50, et le bloc de prompt repetait indefiniment les
# trois memes phrases en « fortement » sans rien apprendre au modele.
DEFAULT_PARAMS: dict[DriveKind, DriveParams] = {
    DriveKind.CURIOSITY: DriveParams(
        growth_rate=0.0008,
        decay_on_satisfy=0.6,
        weight=0.30,
        satisfy_threshold=0.35,
    ),
    DriveKind.SOCIAL: DriveParams(
        growth_rate=0.0010,
        decay_on_satisfy=0.7,
        weight=0.35,
        satisfy_threshold=0.40,
    ),
    DriveKind.EXPRESSION: DriveParams(
        growth_rate=0.0007,
        decay_on_satisfy=0.8,
        weight=0.25,
        satisfy_threshold=0.45,
    ),
    DriveKind.REST: DriveParams(
        # Rest drive grows only when Mika has been very active recently.
        # It's handled specially — see DriveEngine.on_activity.
        growth_rate=0.0,
        decay_on_satisfy=0.3,
        weight=0.20,
        satisfy_threshold=0.50,
    ),
}


@dataclass
class DriveState:
    """One drive's current tension + bookkeeping."""
    kind: DriveKind
    tension: float = 0.0
    last_update: float = field(default_factory=time.time)
    last_satisfied: float = field(default_factory=time.time)

    def clamp(self) -> None:
        self.tension = max(0.0, min(1.0, self.tension))


def dominant_drive(states: dict[DriveKind, DriveState]) -> DriveState | None:
    """Return the drive with the highest tension, or None if all are quiet."""
    if not states:
        return None
    winner = max(states.values(), key=lambda s: s.tension)
    if winner.tension < 0.2:
        return None
    return winner


def drive_prompt_description(states: dict[DriveKind, DriveState]) -> str:
    """French description of current drive state for the system prompt.

    Keeps only drives above their satisfy_threshold (otherwise they're
    noise). Describes intensity in natural language so Claude can feel
    the pull without seeing numbers.
    """
    active = []
    for kind, state in states.items():
        params = DEFAULT_PARAMS[kind]
        if state.tension < params.satisfy_threshold:
            continue
        active.append((kind, state.tension))

    if not active:
        return ""

    active.sort(key=lambda x: -x[1])
    lines = []
    for kind, tension in active[:3]:
        lines.append(_describe_drive(kind, tension))

    return "Tes pulsions interieures: " + " ".join(lines)


def _describe_drive(kind: DriveKind, tension: float) -> str:
    adverb = (
        "legerement" if tension < 0.5
        else "clairement" if tension < 0.75
        else "fortement"
    )
    descriptions = {
        DriveKind.CURIOSITY: (
            f"tu ressens {adverb} l'envie d'apprendre, de comprendre, de poser des questions."
        ),
        DriveKind.SOCIAL: (
            f"tu as {adverb} besoin de contact, d'etre reconnue, d'echanger."
        ),
        DriveKind.EXPRESSION: (
            f"tu as {adverb} envie de dire quelque chose, une pensee qui te traverse."
        ),
        DriveKind.REST: (
            f"tu te sens {adverb} fatiguee, tu aimerais un moment de calme."
        ),
    }
    return descriptions[kind]
