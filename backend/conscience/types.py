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
