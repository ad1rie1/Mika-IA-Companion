"""Decision scoring — computes whether the conscience should act.

Extracted from ConscienceEngine for testability: the scoring function
is pure (no side effects, no DB, no async) and can be unit-tested
with synthetic DecisionContext values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from conscience.types import DecisionContext

# Même barre que le fast-path de `ConscienceEngine.observe`.
SLEEP_WAKE_PERTINENCE = 0.85
SLEEP_PENALTY = 0.30


@dataclass(frozen=True)
class ScoringTuning:
    """Les onze facteurs, nommés, avec les valeurs d'origine pour défauts.

    Ce module reste **pur** : il ne lit ni base ni registre de configuration.
    Les valeurs rapatriées dans la configuration sont résolues au bord — par
    ``ConscienceEngine._scoring_tuning()`` — et passées ici. Un ``ScoringTuning()``
    sans argument reproduit mot pour mot le calcul d'avant, ce qui laisse aux
    tests unitaires leur sens : ils mesurent la calibration *déclarée*, pas ce
    que la base de la machine qui les exécute contient.

    **Invariant** : ``idle_cap`` (+0.30), ``drives_cap`` (+0.50) et
    ``ignored_cap`` (−0.30) somment exactement au seuil d'action (0.50),
    comparé avec ``>=``. Voir ``conscience/config_schema.py``.
    """

    # Facteur 12 (veto) et malus de sommeil
    sleep_wake_pertinence: float = SLEEP_WAKE_PERTINENCE
    sleep_penalty: float = SLEEP_PENALTY
    # F1 pertinence
    pertinence_gate: float = 0.7
    pertinence_weight: float = 0.4
    # F2 urgence accumulée
    urgency_gate: float = 0.5
    urgency_weight: float = 0.3
    urgency_cap: float = 0.3
    # F3 débordement d'humeur
    mood_gate: float = 0.7
    mood_bonus: float = 0.25
    # F4 inactivité
    idle_gate_minutes: float = 10
    idle_ramp_minutes: float = 30
    idle_cap: float = 0.3
    # F5 salutation
    greeting_bonus: float = 0.35
    # F6 action programmée
    scheduled_weight: float = 0.5
    # F7 pression
    pressure_min_waits: int = 3
    pressure_per_wait: float = 0.035
    pressure_cap: float = 0.25
    # F8 « on m'ignore »
    ignored_min_acts: int = 2
    ignored_per_act: float = 0.1
    ignored_cap: float = 0.3
    # F9 pulsions
    drives_floor: float = -0.4
    drives_cap: float = 0.5
    drives_deadband: float = 0.02
    # F10 ruminations
    rumination_gate: float = 0.2
    rumination_weight: float = 0.35
    rumination_cap: float = 0.3
    # F11 fatigue
    fatigue_gate: float = 0.5
    fatigue_slope: float = 0.5
    fatigue_cap: float = 0.25
    # Frein quotidien
    daily_acts_cap: int = 5
    suppress_after_ignored: int = 3
    suppressed_score: float = 0.1
    # Salutations (bornes de fin exclues)
    morning_start: int = 7
    morning_end: int = 10
    evening_start: int = 18
    evening_end: int = 20
    night_start: int = 23


#: Réglage par défaut, partagé : le construire une fois évite de rebâtir la
#: dataclasse à chaque appel des tests et du repli.
DEFAULT_TUNING = ScoringTuning()


def compute_decision_score(
    ctx: DecisionContext,
    greeted_periods: set[str],
    greeted_date: object | None,
    tuning: ScoringTuning | None = None,
) -> tuple[float, str, set[str], object]:
    """Unified scoring. Returns (score, reason, updated_greeted_periods, updated_greeted_date).

    Pure function — no side effects. The caller is responsible for
    persisting the updated greeted state, and for comparing the score against
    the act threshold: this function deliberately doesn't know it. It used to
    take one and never read it, which made the split of responsibility look
    like the opposite of what it is.

    ``tuning`` follows the same rule: the weights are configurable, but they
    are *resolved by the caller* and handed over. Omitting it reproduces the
    historical calculation exactly.
    """
    t = tuning or DEFAULT_TUNING
    # Cooldown check (in-memory, no DB query)
    if ctx.in_cooldown:
        return 0.0, "cooldown", greeted_periods, greeted_date

    # Facteur 12 : elle dort. Aucun facteur au-dessus ne le savait, et dormir
    # *vide* REST — donc annule la pénalité de fatigue : la nuit la rendait
    # mécaniquement plus bavarde que la veille au soir. Un acte non urgent est
    # ici un réveil, pas une initiative. Le veto passe avant le Facteur 5 :
    # `check_time_trigger` marque une période comme saluée dès la passe de
    # scoring, et le salut de 23 h ne doit pas être brûlé par un cycle endormi.
    asleep = ctx.sleep_phase != "awake"
    if asleep and not (
        ctx.max_pertinence >= t.sleep_wake_pertinence or ctx.scheduled_actions
    ):
        return 0.0, f"asleep({ctx.sleep_phase})", greeted_periods, greeted_date

    score = 0.0
    parts = []

    # Factor 1: High-pertinence observations
    if ctx.max_pertinence > t.pertinence_gate:
        s = ctx.max_pertinence * t.pertinence_weight
        score += s
        parts.append(f"pertinence({ctx.max_pertinence:.2f})")

    # Factor 2: Accumulated urgency
    if ctx.weighted_urgency > t.urgency_gate:
        s = min(t.urgency_cap, ctx.weighted_urgency * t.urgency_weight)
        score += s
        parts.append(f"accumulated({ctx.weighted_urgency:.2f})")

    # Factor 3: Mood overflow
    if ctx.global_intensity > t.mood_gate:
        score += t.mood_bonus
        parts.append(f"mood({ctx.global_mood}:{ctx.global_intensity:.2f})")

    # Factor 4: Idle time
    idle_minutes = ctx.idle_seconds / 60
    if idle_minutes > t.idle_gate_minutes:
        s = min(
            t.idle_cap,
            (idle_minutes - t.idle_gate_minutes) / t.idle_ramp_minutes * t.idle_cap,
        )
        score += s
        parts.append(f"idle({idle_minutes:.0f}m)")

    # Factor 5: Time-based greeting
    time_trigger, greeted_periods, greeted_date = check_time_trigger(
        greeted_periods, greeted_date, t,
    )
    if time_trigger:
        score += t.greeting_bonus
        parts.append(f"time({time_trigger})")

    # Factor 6: Scheduled actions due
    if ctx.scheduled_actions:
        max_priority = max(a.priority for a in ctx.scheduled_actions)
        score += max_priority * t.scheduled_weight
        parts.append(f"scheduled({len(ctx.scheduled_actions)})")

    # Factor 7: Accumulation pressure (consecutive waits build up)
    if ctx.consecutive_waits >= t.pressure_min_waits and ctx.pending_observations:
        pressure = min(
            t.pressure_cap,
            (ctx.consecutive_waits - (t.pressure_min_waits - 1)) * t.pressure_per_wait,
        )
        score += pressure
        parts.append(f"pressure({ctx.consecutive_waits}waits)")

    # Factor 8: Self-regulation (reduce score if being ignored)
    if ctx.consecutive_ignored_acts >= t.ignored_min_acts:
        penalty = min(t.ignored_cap, ctx.consecutive_ignored_acts * t.ignored_per_act)
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
        t.drives_floor, min(t.drives_cap, drive_positive) + ctx.drive_rest_penalty
    )
    if abs(drive_contribution) >= t.drives_deadband:
        score += drive_contribution
        parts.append(f"drives({ctx.drive_summary or 'mixed'}:{drive_contribution:+.2f})")

    # Factor 10: Rumination pressure — persistent unresolved thoughts
    # push Mika to speak. Caps at +0.3 so rumination alone cannot
    # force action without other signals.
    if ctx.rumination_pressure > t.rumination_gate:
        rum_score = min(
            t.rumination_cap, ctx.rumination_pressure * t.rumination_weight
        )
        score += rum_score
        parts.append(f"rumination({ctx.rumination_count}×:{rum_score:.2f})")

    # Factor 11: Energy modulation — tired Mika speaks less spontaneously.
    # We DON'T scale the positive contributions above (pertinence, urgency,
    # scheduled actions all need to fire even when tired); we subtract a
    # penalty when energy is below mid-range. Capped at -0.25 so a very
    # pertinent signal still gets through at 3am.
    if ctx.energy < t.fatigue_gate:
        fatigue_penalty = min(
            t.fatigue_cap, (t.fatigue_gate - ctx.energy) * t.fatigue_slope
        )
        score -= fatigue_penalty
        parts.append(f"fatigue(-{fatigue_penalty:.2f})")

    if asleep:
        score -= t.sleep_penalty
        parts.append(f"sommeil(-{t.sleep_penalty:.2f})")

    # Hard cap: too many ignored acts today -> suppress
    if (ctx.acts_today >= t.daily_acts_cap
            and ctx.consecutive_ignored_acts >= t.suppress_after_ignored):
        score = min(score, t.suppressed_score)
        parts.append("suppressed(too_many_ignored)")

    reason = ", ".join(parts) if parts else "no_signal"
    return score, reason, greeted_periods, greeted_date


def check_time_trigger(
    greeted_periods: set[str],
    greeted_date: object | None,
    tuning: ScoringTuning | None = None,
) -> tuple[str | None, set[str], object]:
    """Check for time-based greeting triggers (once per period per day).

    Returns (trigger_name_or_None, updated_greeted_periods, updated_greeted_date).
    Pure function — the period bounds come in with the tuning, they are never
    read from the config here.
    """
    t = tuning or DEFAULT_TUNING
    now = datetime.now()
    hour = now.hour
    today = now.date()

    # Clear greeted set on new day
    if greeted_date != today:
        greeted_periods = set()
        greeted_date = today

    if t.morning_start <= hour < t.morning_end and "morning" not in greeted_periods:
        greeted_periods = greeted_periods | {"morning"}
        return "morning", greeted_periods, greeted_date

    if t.evening_start <= hour < t.evening_end and "evening" not in greeted_periods:
        greeted_periods = greeted_periods | {"evening"}
        return "evening", greeted_periods, greeted_date

    if t.night_start <= hour and "night" not in greeted_periods:
        greeted_periods = greeted_periods | {"night"}
        return "night", greeted_periods, greeted_date

    return None, greeted_periods, greeted_date
