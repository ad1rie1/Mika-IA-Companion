"""Decision scoring — computes whether the conscience should act.

Extracted from ConscienceEngine for testability: the scoring function
is pure (no side effects, no DB, no async) and can be unit-tested
with synthetic DecisionContext values.
"""

from __future__ import annotations

from datetime import datetime

from conscience.types import DecisionContext


def compute_decision_score(
    ctx: DecisionContext,
    greeted_periods: set[str],
    greeted_date: object | None,
) -> tuple[float, str, set[str], object]:
    """Unified scoring. Returns (score, reason, updated_greeted_periods, updated_greeted_date).

    Pure function — no side effects. The caller is responsible for
    persisting the updated greeted state, and for comparing the score against
    the act threshold: this function deliberately doesn't know it. It used to
    take one and never read it, which made the split of responsibility look
    like the opposite of what it is.
    """
    # Cooldown check (in-memory, no DB query)
    if ctx.in_cooldown:
        return 0.0, "cooldown", greeted_periods, greeted_date

    score = 0.0
    parts = []

    # Factor 1: High-pertinence observations
    if ctx.max_pertinence > 0.7:
        s = ctx.max_pertinence * 0.4
        score += s
        parts.append(f"pertinence({ctx.max_pertinence:.2f})")

    # Factor 2: Accumulated urgency
    if ctx.weighted_urgency > 0.5:
        s = min(0.3, ctx.weighted_urgency * 0.3)
        score += s
        parts.append(f"accumulated({ctx.weighted_urgency:.2f})")

    # Factor 3: Mood overflow
    if ctx.global_intensity > 0.7:
        score += 0.25
        parts.append(f"mood({ctx.global_mood}:{ctx.global_intensity:.2f})")

    # Factor 4: Idle time
    idle_minutes = ctx.idle_seconds / 60
    if idle_minutes > 10:
        s = min(0.3, (idle_minutes - 10) / 30 * 0.3)
        score += s
        parts.append(f"idle({idle_minutes:.0f}m)")

    # Factor 5: Time-based greeting
    time_trigger, greeted_periods, greeted_date = check_time_trigger(
        greeted_periods, greeted_date
    )
    if time_trigger:
        score += 0.35
        parts.append(f"time({time_trigger})")

    # Factor 6: Scheduled actions due
    if ctx.scheduled_actions:
        max_priority = max(a.priority for a in ctx.scheduled_actions)
        score += max_priority * 0.5
        parts.append(f"scheduled({len(ctx.scheduled_actions)})")

    # Factor 7: Accumulation pressure (consecutive waits build up)
    if ctx.consecutive_waits >= 3 and ctx.pending_observations:
        pressure = min(0.25, (ctx.consecutive_waits - 2) * 0.035)
        score += pressure
        parts.append(f"pressure({ctx.consecutive_waits}waits)")

    # Factor 8: Self-regulation (reduce score if being ignored)
    if ctx.consecutive_ignored_acts >= 2:
        penalty = min(0.3, ctx.consecutive_ignored_acts * 0.1)
        score -= penalty
        parts.append(f"ignored(-{penalty:.2f})")

    # Factor 9: Intrinsic drives (curiosity / social / expression / rest).
    # drive_bonus is signed: REST subtracts, others add. Clamp to [-0.4, +0.5].
    # La fatigue est retirée *après* le plafond des positives, pas avant :
    # celles-ci somment jusqu'a +0.90, donc le plafond +0.5 avalait la
    # soustraction et REST a 0.0 rendait exactement le meme score que REST a
    # 1.0. `drive_rest_penalty` vaut 0.0 quand personne ne la renseigne, ce
    # qui redonne mot pour mot l'ancien calcul.
    drive_positive = ctx.drive_bonus - ctx.drive_rest_penalty
    drive_contribution = max(
        -0.4, min(0.5, drive_positive) + ctx.drive_rest_penalty
    )
    if abs(drive_contribution) >= 0.02:
        score += drive_contribution
        parts.append(f"drives({ctx.drive_summary or 'mixed'}:{drive_contribution:+.2f})")

    # Factor 10: Rumination pressure — persistent unresolved thoughts
    # push Mika to speak. Caps at +0.3 so rumination alone cannot
    # force action without other signals.
    if ctx.rumination_pressure > 0.2:
        rum_score = min(0.3, ctx.rumination_pressure * 0.35)
        score += rum_score
        parts.append(f"rumination({ctx.rumination_count}×:{rum_score:.2f})")

    # Factor 11: Energy modulation — tired Mika speaks less spontaneously.
    # We DON'T scale the positive contributions above (pertinence, urgency,
    # scheduled actions all need to fire even when tired); we subtract a
    # penalty when energy is below mid-range. Capped at -0.25 so a very
    # pertinent signal still gets through at 3am.
    if ctx.energy < 0.5:
        fatigue_penalty = min(0.25, (0.5 - ctx.energy) * 0.5)
        score -= fatigue_penalty
        parts.append(f"fatigue(-{fatigue_penalty:.2f})")

    # Hard cap: too many ignored acts today -> suppress
    if ctx.acts_today >= 5 and ctx.consecutive_ignored_acts >= 3:
        score = min(score, 0.1)
        parts.append("suppressed(too_many_ignored)")

    reason = ", ".join(parts) if parts else "no_signal"
    return score, reason, greeted_periods, greeted_date


def check_time_trigger(
    greeted_periods: set[str],
    greeted_date: object | None,
) -> tuple[str | None, set[str], object]:
    """Check for time-based greeting triggers (once per period per day).

    Returns (trigger_name_or_None, updated_greeted_periods, updated_greeted_date).
    Pure function.
    """
    now = datetime.now()
    hour = now.hour
    today = now.date()

    # Clear greeted set on new day
    if greeted_date != today:
        greeted_periods = set()
        greeted_date = today

    if 7 <= hour < 10 and "morning" not in greeted_periods:
        greeted_periods = greeted_periods | {"morning"}
        return "morning", greeted_periods, greeted_date

    if 18 <= hour < 20 and "evening" not in greeted_periods:
        greeted_periods = greeted_periods | {"evening"}
        return "evening", greeted_periods, greeted_date

    if 23 <= hour and "night" not in greeted_periods:
        greeted_periods = greeted_periods | {"night"}
        return "night", greeted_periods, greeted_date

    return None, greeted_periods, greeted_date
