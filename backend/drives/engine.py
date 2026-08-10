"""DriveEngine — singleton managing intrinsic motivation.

Design notes:
  - Snapshotted to the DB (`DriveSnapshot`), restored at boot. L'état a
    longtemps été purement en RAM, justifié par « on ne se réveille pas
    avec la tension exacte de la veille » — mais ce qui disparaissait au
    redémarrage, ce n'était pas une nuance de fatigue : c'était la nuit
    mentale entière (le gate de sommeil lisait REST) et toute échelle de
    temps au-delà d'une session (SOCIAL lit `last_satisfied`). L'intuition
    reste vraie et reste servie : `restore_state()` repose les horodatages
    et laisse `update()` rejouer le temps d'arrêt.
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

from configs.runtime import cfg_float
from drives.state import (
    DriveKind,
    DriveState,
    dominant_drive,
    drive_prompt_description,
    log_growth,
    params_for,
)
from utils.degradation import degradations

logger = logging.getLogger(__name__)


# Les constantes qui suivent restent le REPLI des clés ``drives.*`` (section
# « Pulsions » du dashboard) : même valeur, servie quand le registre est hors
# d'atteinte. Voir ``configs/runtime.py``.
#
# Activity tracking for REST drive.
# REST grows proportionally to "activity density" in the last window.
_ACTIVITY_WINDOW_SECONDS = 600.0   # 10 min rolling window
_REST_PRESSURE_PER_EVENT = 0.04    # each act/observation adds this to rest
# Décroissance naturelle de REST, par seconde. Calibrée CONTRE le gate
# d'entrée du cycle de sommeil (`memory/sleep.py`), qui exige 900 s sans
# interaction PUIS `rest_tension >= 0.5` : pendant ces 900 s la tension ne
# fait que baisser, donc ce coefficient borne mécaniquement ce qu'elle peut
# encore valoir quand le gate s'ouvre. À 0.0008 elle perdait 0.72 sur la
# fenêtre — une tension pleine retombait à 0.28, le seuil de 0.5 était
# inatteignable et le cycle de sommeil entier ne s'exécutait jamais (aucun
# journal, aucun rêve, aucune digestion de ruminations). À 0.0001 la perte
# tombe à 0.09 sur la fenêtre (~2 h 45 pour vider une tension pleine) et le
# sommeil redevient la voie principale de récupération, ce que le
# commentaire de `SLEEP_REST_RECOVERY` affirmait déjà.
_REST_NATURAL_DECAY = 0.0001

# Mélange des deux sources d'énergie : energie = circadien × 0.7 + (1 − REST)
# × 0.3. C'étaient deux littéraux nus au milieu de `energy_level`, alors que
# ce sont eux qui décident si Mika est « une personne qui a des journées » ou
# « une personne qui a des coups de fatigue ».
ENERGY_CIRCADIAN_WEIGHT = 0.7
ENERGY_REST_WEIGHT = 0.3


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
            params = params_for(kind)

            if kind is DriveKind.REST:
                # Always consume pending activity events, even if dt=0.
                pressure = self._rest_pressure(now)
                decay = cfg_float(
                    "drives.rest.natural_decay_per_second",
                    _REST_NATURAL_DECAY, mini=0.0,
                ) * dt
                state.tension += pressure - decay
            elif params.growth_horizon:
                # `max` et non `=` : après un assouvissement partiel
                # `last_satisfied` repart de zéro, donc la cible aussi — le
                # résidu de tension est conservé jusqu'à ce que la courbe le
                # rattrape. Idempotent comme la branche linéaire.
                cible = log_growth(
                    now - state.last_satisfied,
                    params.growth_tau,
                    params.growth_horizon,
                )
                state.tension = max(state.tension, cible)
            elif dt > 0:
                state.tension += params.growth_rate * dt
            # else: no time passed → nothing to do for this drive

            state.clamp()
            state.last_update = now

        # Prune old activity events outside the window
        cutoff = now - cfg_float(
            "drives.activity_window_seconds", _ACTIVITY_WINDOW_SECONDS, mini=0.0,
        )
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
        pression = cfg_float(
            "drives.rest.pressure_per_event", _REST_PRESSURE_PER_EVENT, mini=0.0,
        )
        for t, w in self._activity:
            # Consume: this event contributes once.
            total += pression * w
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
        params = params_for(kind)
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
            params = params_for(kind)
            if state.tension < params.satisfy_threshold:
                continue

            if kind is DriveKind.REST:
                # Fatigue pulls away from action — negative contribution.
                contribution = self.rest_penalty()
            else:
                # How much "above threshold" are we? 0..1
                above = (state.tension - params.satisfy_threshold) / (
                    1.0 - params.satisfy_threshold
                )
                contribution = params.weight * above

            bonus += contribution
            parts.append(f"{kind.value}:{state.tension:.2f}")

        label = ",".join(parts) if parts else ""
        return bonus, label

    def rest_penalty(self) -> float:
        """Ce que la fatigue REST retire au score de conscience — toujours ≤ 0.

        Exposé à part de la somme signée que renvoie
        `conscience_contribution()` parce que le facteur 9 du scoring
        plafonne à +0.5 : les trois pulsions positives montent ensemble
        jusqu'à +0.90, donc une fois soustraite *avant* ce plafond la
        fatigue disparaissait entièrement — +0.90 et +0.70 étaient tous
        deux ramenés à exactement +0.50, et REST à 0.0 valait REST à 1.0.
        Le scoring l'applique donc après avoir plafonné les positives.
        """
        self.update()
        params = params_for(DriveKind.REST)
        tension = self.states[DriveKind.REST].tension
        if tension < params.satisfy_threshold:
            return 0.0

        above = (tension - params.satisfy_threshold) / (
            1.0 - params.satisfy_threshold
        )
        return -(params.weight * above)

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

        combined = (
            cfg_float("drives.energy.circadian_weight",
                      ENERGY_CIRCADIAN_WEIGHT, mini=0.0) * circadian_energy
            + cfg_float("drives.energy.rest_weight",
                        ENERGY_REST_WEIGHT, mini=0.0) * rest_energy
        )
        return max(0.0, min(1.0, combined))

    # ── Persistence ───────────────────────────────────────────────

    async def save_state(self) -> None:
        """Écrase l'instantané de chaque pulsion. Ne lève jamais."""
        from asgiref.sync import sync_to_async

        from drives.models import DriveSnapshot

        self.update()
        try:
            from datetime import datetime, timezone as dt_timezone

            def _write() -> None:
                for kind, state in self.states.items():
                    DriveSnapshot.objects.update_or_create(
                        kind=kind.value,
                        defaults={
                            "tension": state.tension,
                            "last_satisfied": datetime.fromtimestamp(
                                state.last_satisfied, dt_timezone.utc
                            ),
                        },
                    )

            await sync_to_async(_write)()
        except Exception as exc:
            degradations.record("drives.save_state", exc)

    async def restore_state(self) -> None:
        """Relit l'instantané, puis laisse `update()` rejouer le temps d'arrêt.

        Sans ce rejeu, une coupure de trois heures rendrait la fatigue de la
        veille intacte ; avec lui, REST retombe et les pulsions positives
        montent exactement comme si le processus n'avait pas coupé.
        `_activity` n'est pas persisté : c'est une fenêtre glissante de 10 min
        d'événements déjà consommés.
        """
        from asgiref.sync import sync_to_async

        from drives.models import DriveSnapshot

        try:
            rows = await sync_to_async(
                lambda: {r.kind: r for r in DriveSnapshot.objects.all()}
            )()
        except Exception as exc:
            degradations.record("drives.restore_state", exc)
            return

        for kind, state in self.states.items():
            row = rows.get(kind.value)
            if row is None:
                continue
            state.tension = max(0.0, min(1.0, row.tension))
            if row.last_satisfied is not None:
                state.last_satisfied = row.last_satisfied.timestamp()
            state.last_update = row.saved_at.timestamp()

        self.update()
        logger.info("Drives restored from %d snapshot(s)", len(rows))

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
