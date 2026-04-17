"""Circadian rhythm — Mika has days.

A pure-function layer that maps wall-clock time → a phase enum + a PAD
bias vector + an energy level. The EmotionEngine's `home_vector` picks
up the bias so the oscillator's rest point drifts across the day, and
the DriveEngine reads the energy curve so tiredness follows the night.

Design:
  - Zero side effects, zero state. `current_phase(now)` and
    `phase_bias(phase, profile)` are pure — trivial to test at any hour.
  - The profile is loaded from `personality.yaml::temperament.circadian_profile`
    so a different character (lève-tôt vs noctambule) is a YAML edit,
    not a code change.
  - 4 phases: morning, afternoon, evening, night. A "sleep" window is
    not strictly a 5th phase — it IS the night phase with lowest energy.
  - Energy is a float in [0, 1]. 1 = fresh, 0 = exhausted. Peaks early
    afternoon, troughs 3-5 AM. Cosine-based for smoothness.
  - Bias is a Vec3 in PAD space, NOT a full anchor — it's small (magnitude
    ~0.3) so it nudges the home_vector without overriding the persona's
    default_mood.

Why a cosine for energy:
  A cosine over 24h gives a single peak + single trough with smooth
  transitions. Matches the dominant human circadian rhythm (process-C)
  well enough for a chatbot without needing a real 2-process model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from emotion import pad
from emotion.pad import Vec3
from emotion.types import Emotion


class CircadianPhase(str, Enum):
    MORNING = "morning"      # ~6-11h
    AFTERNOON = "afternoon"  # ~12-17h
    EVENING = "evening"      # ~18-22h
    NIGHT = "night"          # ~23-5h


# Default phase → emotion anchor that biases the home position. Each phase
# nudges the oscillator's rest state toward a "typical" flavor without
# overriding the base personality's default_mood:
#
#   MORNING   → hopeful  (positive valence, mid arousal, slight dominance)
#   AFTERNOON → playful  (mid-high valence, higher arousal)
#   EVENING   → relieved (positive valence, low arousal — winding down)
#   NIGHT     → dreamy   (mid valence, negative arousal — introspective)
#
# Values can be overridden per-character via `temperament.circadian_profile`.
_DEFAULT_PHASE_ANCHORS: dict[CircadianPhase, Emotion] = {
    CircadianPhase.MORNING: Emotion.HOPEFUL,
    CircadianPhase.AFTERNOON: Emotion.PLAYFUL,
    CircadianPhase.EVENING: Emotion.RELIEVED,
    CircadianPhase.NIGHT: Emotion.DREAMY,
}

# How strongly each phase tints the home vector. Small so the base
# default_mood remains recognizable (home = default_mood × 0.15 + bias × 0.35).
_BIAS_MAGNITUDE: float = 0.35

# Default phase boundaries (start hour, inclusive). Can be overridden per
# character — a noctambule's "morning" might start at 10h.
_DEFAULT_PHASE_HOURS: dict[CircadianPhase, int] = {
    CircadianPhase.MORNING: 6,
    CircadianPhase.AFTERNOON: 12,
    CircadianPhase.EVENING: 18,
    CircadianPhase.NIGHT: 23,
}


@dataclass(frozen=True)
class CircadianProfile:
    """Per-character circadian tuning.

    `phase_anchors` lets a grumpy-in-the-morning character swap HOPEFUL
    for BORED in their morning phase. `phase_hours` lets a night-owl
    start their morning at 10h instead of 6h.

    `energy_peak_hour` is where the cosine energy curve hits its maximum
    (defaults to 14h — early afternoon for the average human). The trough
    is automatically at `(peak + 12) % 24`.
    """
    phase_anchors: dict[CircadianPhase, Emotion] = field(
        default_factory=lambda: dict(_DEFAULT_PHASE_ANCHORS)
    )
    phase_hours: dict[CircadianPhase, int] = field(
        default_factory=lambda: dict(_DEFAULT_PHASE_HOURS)
    )
    energy_peak_hour: float = 14.0
    # Amplitude of the circadian energy swing. 1.0 = full swing (0 to 1),
    # 0.5 = swings between 0.25 and 0.75. Low-volatility characters have
    # flatter curves.
    energy_amplitude: float = 0.7
    # Baseline energy (midpoint of the cosine). Nocturnal characters can
    # push this down and shift peak to late evening.
    energy_baseline: float = 0.55


@dataclass(frozen=True)
class CircadianState:
    """Resolved circadian state for a given moment."""
    phase: CircadianPhase
    hour: int
    energy: float     # [0, 1]
    bias_anchor: Emotion


# ── Public API ────────────────────────────────────────────────────


def current_phase(
    now: datetime | None = None,
    profile: CircadianProfile | None = None,
) -> CircadianPhase:
    """Return the circadian phase for the given moment.

    Defaults to ``datetime.now()`` if ``now`` is None, and to the default
    profile (6/12/18/23) if ``profile`` is None.
    """
    now = now or datetime.now()
    profile = profile or CircadianProfile()
    hour = now.hour

    # Sort phase start hours ascending, then map each hour into the
    # interval it belongs to.
    ordered = sorted(profile.phase_hours.items(), key=lambda kv: kv[1])
    # Find the last phase whose start_hour <= current hour, wrapping at midnight.
    current = ordered[-1][0]  # default to the last phase (night wraps past midnight)
    for phase, start in ordered:
        if hour >= start:
            current = phase
    return current


def current_state(
    now: datetime | None = None,
    profile: CircadianProfile | None = None,
) -> CircadianState:
    """Return the full circadian state snapshot (phase + energy + bias anchor)."""
    now = now or datetime.now()
    profile = profile or CircadianProfile()
    phase = current_phase(now, profile)
    return CircadianState(
        phase=phase,
        hour=now.hour,
        energy=energy_level(now, profile),
        bias_anchor=profile.phase_anchors[phase],
    )


def phase_bias(
    phase: CircadianPhase,
    profile: CircadianProfile | None = None,
) -> Vec3:
    """Return a small PAD vector that nudges the home position for this phase.

    Magnitude is bounded by ``_BIAS_MAGNITUDE`` so the character's
    default_mood remains dominant — the phase just colors the baseline.
    """
    profile = profile or CircadianProfile()
    anchor = profile.phase_anchors[phase]
    return pad.label_to_pad(anchor, _BIAS_MAGNITUDE)


def energy_level(
    now: datetime | None = None,
    profile: CircadianProfile | None = None,
) -> float:
    """Cosine-based energy curve over the 24h cycle.

    Peaks at ``profile.energy_peak_hour`` (default 14h) and troughs 12h
    later. Uses the baseline + amplitude from the profile so nocturnal
    characters can be tuned.

    Returns a float in [0, 1].
    """
    now = now or datetime.now()
    profile = profile or CircadianProfile()

    # Current fractional hour (for smoothness: 14:30 ≠ 14:00).
    fractional_hour = now.hour + now.minute / 60.0 + now.second / 3600.0

    # Phase offset so the cosine peaks at energy_peak_hour.
    # cos(2π * (h - peak) / 24) peaks when h == peak.
    delta = fractional_hour - profile.energy_peak_hour
    cosine = math.cos(2 * math.pi * delta / 24.0)

    energy = profile.energy_baseline + (profile.energy_amplitude / 2.0) * cosine
    return max(0.0, min(1.0, energy))


def phase_description_fr(state: CircadianState) -> str:
    """Human-friendly description of the state for the system prompt.

    Example output:
      "Il est 23h. Tu es en phase nuit, l'introspection monte, ton energie est basse (35%)."
    """
    hour_str = f"{state.hour:02d}h"
    phase_label = {
        CircadianPhase.MORNING: "matin",
        CircadianPhase.AFTERNOON: "apres-midi",
        CircadianPhase.EVENING: "soir",
        CircadianPhase.NIGHT: "nuit",
    }[state.phase]

    energy_pct = int(round(state.energy * 100))
    if state.energy >= 0.75:
        energy_word = "tres haute"
    elif state.energy >= 0.55:
        energy_word = "bonne"
    elif state.energy >= 0.35:
        energy_word = "moyenne"
    elif state.energy >= 0.2:
        energy_word = "basse"
    else:
        energy_word = "tres basse"

    tendency = {
        CircadianPhase.MORNING: "tu es dans ta phase la plus tonique et optimiste",
        CircadianPhase.AFTERNOON: "tu es pleinement active, facilement enjouee",
        CircadianPhase.EVENING: "tu te poses, ton ton devient plus doux et chaleureux",
        CircadianPhase.NIGHT: "tu es en mode introspection, plus reveuse et intime",
    }[state.phase]

    return (
        f"Il est {hour_str}. En phase {phase_label}, {tendency}. "
        f"Ton energie est {energy_word} ({energy_pct}%)."
    )


def profile_from_yaml(data: dict) -> CircadianProfile:
    """Build a ``CircadianProfile`` from a personality.yaml ``circadian_profile`` dict.

    All fields are optional — any missing keys fall back to the defaults.
    The YAML schema:

        circadian_profile:
          phase_hours: {morning: 6, afternoon: 12, evening: 18, night: 23}
          phase_anchors: {morning: hopeful, ...}
          energy_peak_hour: 14.0
          energy_amplitude: 0.7
          energy_baseline: 0.55
    """
    profile = CircadianProfile()
    if not data:
        return profile

    anchors = dict(profile.phase_anchors)
    for phase_name, anchor_name in (data.get("phase_anchors") or {}).items():
        try:
            phase = CircadianPhase(phase_name)
            anchors[phase] = Emotion(anchor_name)
        except ValueError:
            continue

    hours = dict(profile.phase_hours)
    for phase_name, start_hour in (data.get("phase_hours") or {}).items():
        try:
            phase = CircadianPhase(phase_name)
            hours[phase] = int(start_hour) % 24
        except (ValueError, TypeError):
            continue

    return CircadianProfile(
        phase_anchors=anchors,
        phase_hours=hours,
        energy_peak_hour=float(
            data.get("energy_peak_hour", profile.energy_peak_hour)
        ),
        energy_amplitude=float(
            data.get("energy_amplitude", profile.energy_amplitude)
        ),
        energy_baseline=float(
            data.get("energy_baseline", profile.energy_baseline)
        ),
    )
