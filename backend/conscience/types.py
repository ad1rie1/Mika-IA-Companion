"""Type definitions for the Conscience layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InterpretedSignal:
    """Result of the interpretation pipeline (Haiku or heuristic)."""

    summary: str
    category: str           # Observation.Category value
    pertinence: float       # 0.0 (noise) to 1.0 (critical)
    emotional_reaction: str  # Emotion name or ""
    emotional_intensity: float
    themes: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    should_remember: bool = False


@dataclass
class DecisionContext:
    """All context gathered for a decision cycle."""

    pending_observations: list  # Observation instances
    global_mood: str
    global_intensity: float
    idle_seconds: float
    in_cooldown: bool           # True if last action was within cooldown window
    max_pertinence: float
    weighted_urgency: float     # Accumulated pertinence score
    scheduled_actions: list = field(default_factory=list)  # Due ScheduledAction instances
    consecutive_waits: int = 0          # Consecutive "wait" decisions (accumulation pressure)
    acts_today: int = 0                  # How many "act" decisions today
    consecutive_ignored_acts: int = 0    # Recent acts with no user response
    # Drives: intrinsic motivation. Signed — REST drive contributes negatively.
    drive_bonus: float = 0.0
    drive_summary: str = ""
    # Rumination: unresolved thoughts that persist beyond observations.
    rumination_pressure: float = 0.0   # 0..1, sum of active rumination intensities
    rumination_count: int = 0
    # Energy level from DriveEngine.energy_level() — combines circadian
    # phase + REST drive. Low energy = less likely to speak spontaneously.
    energy: float = 1.0
