"""DriveEngine — singleton managing intrinsic motivation.

Design notes:
  - Purely in-RAM. Drives are ephemeral — if Mika restarts, she starts
    with fresh drives. This matches human intuition: you don't wake up
    with the exact tension you had when you fell asleep.
  - No background loop needed: tensions are computed lazily via
    `update()` each time the conscience queries them. This keeps the
    engine cheap and race-free.
  - Satisfaction is signaled by the rest of the system: `on_act()` when
    the conscience speaks, `on_conversation()` when a message arrives,
    `on_observation()` when a rich signal is processed.
"""
from __future__ import annotations

import logging
import time

from drives.state import (
    DEFAULT_PARAMS,
    DriveKind,
    DriveState,
    dominant_drive,
    drive_prompt_description,
)

logger = logging.getLogger(__name__)


# Activity tracking for REST drive.
# REST grows proportionally to "activity density" in the last window.
_ACTIVITY_WINDOW_SECONDS = 600.0   # 10 min rolling window
_REST_PRESSURE_PER_EVENT = 0.04    # each act/observation adds this to rest
_REST_NATURAL_DECAY = 0.0008       # rest tension naturally decays per second


class DriveEngine:
    """Singleton. Tracks all four intrinsic drives."""

    def __init__(self) -> None:
        self.states: dict[DriveKind, DriveState] = {
            kind: DriveState(kind=kind) for kind in DriveKind
        }
        # Activity events, (timestamp, intensity) pairs, used by REST drive.
        self._activity: list[tuple[float, float]] = []

    # ── Tension updates ───────────────────────────────────────────

    def update(self, now: float | None = None) -> None:
        """Advance all drive tensions based on elapsed time.

        Idempotent — can be called as often as desired. Uses `last_update`
        per drive to avoid double-counting. REST is handled specially:
        activity-event pressure always applies (discrete events), while
        natural decay is scaled by elapsed time.
        """
        if now is None:
            now = time.time()

        for kind, state in self.states.items():
            dt = max(0.0, now - state.last_update)
            params = DEFAULT_PARAMS[kind]

            if kind is DriveKind.REST:
                # Always consume pending activity events, even if dt=0.
                pressure = self._rest_pressure(now)
                decay = _REST_NATURAL_DECAY * dt
                state.tension += pressure - decay
            elif dt > 0:
                state.tension += params.growth_rate * dt
            # else: no time passed → nothing to do for this drive

            state.clamp()
            state.last_update = now

        # Prune old activity events outside the window
        cutoff = now - _ACTIVITY_WINDOW_SECONDS
        self._activity = [(t, w) for t, w in self._activity if t >= cutoff]

    def _rest_pressure(self, now: float) -> float:
        """REST tension increment from recent activity density.

        High activity in the last 10 min → REST climbs fast. Idle period
        → REST naturally drifts down (via `_REST_NATURAL_DECAY`).
        Returns a per-call *increment* (not per-second), because activity
        events are discrete.
        """
        # We don't re-apply events already counted. Instead, activity
        # events are "one-shot" — added here when first seen, then drained.
        total = 0.0
        remaining: list[tuple[float, float]] = []
        for t, w in self._activity:
            # Consume: this event contributes once.
            total += _REST_PRESSURE_PER_EVENT * w
            # Keep it in the history for context reporting (not re-counted)
            remaining.append((t, 0.0))
        self._activity = remaining
        return total

    # ── Satisfaction signals ──────────────────────────────────────

    def satisfy(self, kind: DriveKind, amount: float = 1.0) -> None:
        """Reduce tension on one drive. `amount` scales decay_on_satisfy.

        `amount=1.0` = full satisfaction (apply decay_on_satisfy as-is).
        `amount=0.5` = half-satisfaction (partial relief).
        """
        self.update()
        state = self.states[kind]
        params = DEFAULT_PARAMS[kind]
        decay = params.decay_on_satisfy * max(0.0, min(1.0, amount))
        state.tension *= (1.0 - decay)
        state.clamp()
        state.last_satisfied = time.time()
        logger.debug(
            "Drive %s satisfied by %.2f → tension=%.2f",
            kind.value, amount, state.tension,
        )

    def on_conversation(self, from_person: bool = True) -> None:
        """Called when a conversation message arrives or is sent.

        Incoming message from a person → large SOCIAL satisfaction,
        modest CURIOSITY relief (someone shared something).
        """
        if from_person:
            self.satisfy(DriveKind.SOCIAL, 0.8)
            self.satisfy(DriveKind.CURIOSITY, 0.3)
        # Mika speaking (outgoing) is handled by on_act()

    def on_act(self, had_tools: bool = False, word_count: int = 0) -> None:
        """Called when the conscience acts (speaks spontaneously).

        - Expression need is satisfied by speaking at all.
        - Curiosity is partially satisfied if tools were used (exploring).
        - Activity event raised → REST will climb.
        """
        self.satisfy(DriveKind.EXPRESSION, 1.0)
        if had_tools:
            self.satisfy(DriveKind.CURIOSITY, 0.5)

        # Longer messages = more active = more rest pressure
        intensity = min(2.0, 1.0 + word_count / 50)
        self._register_activity(intensity)

    def on_reply(self, word_count: int = 0) -> None:
        """Called when Mika answers someone (reactive speech).

        Answering expresses less than speaking up on her own initiative
        — partial EXPRESSION relief — but it *is* speech: without this, a
        Mika who chatted all day still carried full expression tension
        and was pushed to speak spontaneously as if she'd been silent.
        It is also activity, so REST pressure climbs like for any act.
        """
        self.satisfy(DriveKind.EXPRESSION, 0.4)
        intensity = min(2.0, 1.0 + word_count / 50)
        self._register_activity(intensity)

    def on_observation(self, pertinence: float) -> None:
        """Called when a pertinent signal is observed (email, RSS, etc.)."""
        if pertinence > 0.6:
            # Learning about the world satisfies curiosity a bit.
            self.satisfy(DriveKind.CURIOSITY, pertinence * 0.4)

        # Activity contributes to REST pressure.
        self._register_activity(pertinence)

    def _register_activity(self, intensity: float) -> None:
        self._activity.append((time.time(), max(0.1, min(2.0, intensity))))

    # ── Scoring contribution ──────────────────────────────────────

    def conscience_contribution(self) -> tuple[float, str]:
        """How much drives push toward acting, and which one dominates.

        Returns (score_bonus, dominant_drive_name_or_empty).

        Only drives above their satisfy_threshold contribute. REST is
        inverted: high REST tension → *reduces* the push to act.
        """
        self.update()
        bonus = 0.0
        parts = []

        for kind, state in self.states.items():
            params = DEFAULT_PARAMS[kind]
            if state.tension < params.satisfy_threshold:
                continue

            # How much "above threshold" are we? 0..1
            above = (state.tension - params.satisfy_threshold) / (
                1.0 - params.satisfy_threshold
            )
            contribution = params.weight * above

            if kind is DriveKind.REST:
                # Fatigue pulls away from action — negative contribution.
                contribution = -contribution
            bonus += contribution
            parts.append(f"{kind.value}:{state.tension:.2f}")

        label = ",".join(parts) if parts else ""
        return bonus, label

    # ── Prompt context ────────────────────────────────────────────

    def get_context(self) -> str:
        """French sentence(s) for the system prompt."""
        self.update()
        return drive_prompt_description(self.states)

    def get_dominant(self) -> DriveState | None:
        """Drive with highest tension (or None if all quiet)."""
        self.update()
        return dominant_drive(self.states)

    def to_dict(self) -> dict:
        self.update()
        return {
            kind.value: {
                "tension": round(state.tension, 3),
                "last_satisfied": state.last_satisfied,
            }
            for kind, state in self.states.items()
        }

    # ── Energy ────────────────────────────────────────────────────

    def energy_level(self) -> float:
        """Aggregate "how energized is Mika right now" in [0, 1].

        Combines two independent sources:
          - **Circadian phase** (emotion/circadian.py): a cosine curve
            over 24h that peaks early afternoon. Gives Mika "mornings,
            afternoons, evenings, nights" without manual tuning.
          - **REST drive tension**: accumulates with activity (each act,
            each observation) and drains slowly during idle. Models short-
            term fatigue on top of the daily baseline.

        The result is used by:
          - the conscience scoring (tired Mika has a higher effective
            threshold, speaks less spontaneously)
          - the system prompt (the LLM sees "energie basse" and adjusts tone)
          - the frontend panel (visible energy gauge)

        Formula: energy = 0.7 × circadian + 0.3 × (1 - rest_tension)
        Both terms in [0, 1]; output clipped to [0, 1].
        """
        from emotion import circadian

        try:
            from config.personality import personality
            profile = personality.circadian_profile
        except Exception:
            profile = None

        circadian_energy = circadian.energy_level(profile=profile)

        self.update()
        rest_tension = self.states[DriveKind.REST].tension
        rest_energy = max(0.0, 1.0 - rest_tension)

        combined = 0.7 * circadian_energy + 0.3 * rest_energy
        return max(0.0, min(1.0, combined))

    # ── Test / admin helpers ──────────────────────────────────────

    def reset(self) -> None:
        """Reset all drives to zero tension. For tests and /reset endpoints."""
        now = time.time()
        for state in self.states.values():
            state.tension = 0.0
            state.last_update = now
            state.last_satisfied = now
        self._activity.clear()


# Module-level singleton
drive_engine = DriveEngine()
