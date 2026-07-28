import asyncio
import logging
import random
import time

from django.conf import settings

from emotion import pad
from emotion.dynamics import OscillatorParams
from emotion.pad import Vec3
from emotion.types import Emotion, EmotionData
from emotion.state import (
    TEMPERAMENT_PREFIX,
    EmotionHistoryEntry,
    GlobalMood,
    MessageEmotion,
    PersonMood,
    Temperament,
    load_temperament,
)
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Physics tick period (seconds) used by the decay loop.
_TICK_DT = 1.0
# Maximum sub-step size for stable integration. Semi-implicit Euler is only
# stable when dt · ω₀ < ~π; for our parameter range, 0.5s is always safe.
_MAX_SUBSTEP_DT = 0.5
# Upper bound on the total time advanced in a single _apply_decay call.
# Larger gaps (e.g. after hibernation) are capped to prevent runaway steps.
_MAX_ADVANCE_SECONDS = 30.0
# Probability per tick that the global mood receives a tiny stochastic
# nudge. Without this, a well-rested idle Mika sits exactly on her home
# point — humans don't. Small nudges produce barely-perceptible drift
# ("why am I a bit off today") that the oscillator then metabolizes
# normally. Scoped to the global mood only; per-person moods are always
# reactive, never spontaneous.
_SPONTANEOUS_NUDGE_PROBABILITY: float = 0.04
# Max magnitude of a spontaneous nudge (in PAD units). Tiny — should
# decay back to home in a handful of seconds if nothing else happens.
_SPONTANEOUS_NUDGE_MAX: float = 0.08


class EmotionEngine:
    """Central emotion orchestrator, PAD-dimensional + damped oscillator.

    Three layers:
    1. Per-person mood  (person_moods)  — one oscillator per person
    2. Global mood       (global_mood)   — one oscillator for overall state
    3. Message emotion   (computed)      — blend of person + global per message

    Persistence strategy (two-tier, backwards-compatible schema):
    - EmotionSnapshot  : (label, intensity) pairs, retained for
                         EMOTION_SNAPSHOT_RETENTION_DAYS. Restored lossy
                         via label_to_pad().
    - EmotionalSummary : daily aggregates built by the consolidator, used
                         as fallback when snapshots were pruned.
    """

    _SNAPSHOT_DECAY_DAYS: int = 2
    _SUMMARY_DECAY_DAYS: int = 30
    # Idle cleanup: remove persons untouched for this long with no emotion.
    _IDLE_EVICTION_SECONDS: int = 3600

    def __init__(self):
        self.person_moods: dict[str, PersonMood] = {}
        self.global_mood = GlobalMood()
        self.temperament = Temperament()
        self._person_params = OscillatorParams()
        self._global_params = OscillatorParams()
        self._decay_task: asyncio.Task | None = None
        self._initialized = False
        self._last_snapshot_time: dict[str, float] = {}
        self._snapshot_interval: int = 30
        # Protects the snapshot-interval check. Without it, two concurrent
        # process_message() calls for the same person_id could both read
        # the old timestamp, both see "enough time has passed", and both
        # insert a snapshot. Cheap lock, always contended briefly only.
        self._snapshot_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self):
        """Load temperament from personality, restore state, start decay loop."""
        if self._initialized:
            return

        from config.personality import personality
        self.temperament = personality.temperament
        self._recompute_params()

        from configs.service import config_service
        self._snapshot_interval = config_service.get("emotion.snapshot_interval")
        self._SNAPSHOT_DECAY_DAYS = config_service.get("emotion.snapshot_retention_days")
        config_service.on_change(
            "emotion.snapshot_interval",
            lambda k, v: setattr(self, "_snapshot_interval", v),
        )
        # Le tempérament est déclaré ``hot_reload`` : les cinq curseurs se
        # règlent en regardant l'humeur qu'ils gouvernent bouger, ce qui n'a
        # aucun sens si la valeur n'est relue qu'au démarrage. Recharger le
        # tempérament ne suffit pas — ``_recompute_params`` en dérive la masse,
        # la raideur et l'amortissement de l'oscillateur, et c'est cela que la
        # boucle lit à chaque pas.
        config_service.on_change(
            TEMPERAMENT_PREFIX, lambda k, v: self._reload_temperament(k),
        )

        restored = await self._restore_state()

        self._decay_task = asyncio.create_task(self._decay_loop())
        self._initialized = True
        logger.info(
            "EmotionEngine initialized (temperament: volatility=%.1f, "
            "intensity_base=%.1f, recovery=%.1f, default_mood=%s, bleed=%.1f)"
            "%s",
            self.temperament.volatility,
            self.temperament.intensity_base,
            self.temperament.recovery_speed,
            self.temperament.default_mood.value,
            self.temperament.global_bleed,
            " [restored from snapshot]" if restored else "",
        )

    async def shutdown(self):
        """Save emotional state and stop decay loop."""
        await self._save_state()

        if self._decay_task:
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                pass
        logger.info("EmotionEngine shut down (state saved)")

    def _reload_temperament(self, key: str) -> None:
        """Re-read the temperament after a dashboard edit and re-derive params."""
        self.temperament = load_temperament()
        self._recompute_params()
        logger.info(
            "Temperament reloaded after %s changed (volatility=%.2f, "
            "intensity_base=%.2f, recovery=%.2f, default_mood=%s, bleed=%.2f)",
            key,
            self.temperament.volatility,
            self.temperament.intensity_base,
            self.temperament.recovery_speed,
            self.temperament.default_mood.value,
            self.temperament.global_bleed,
        )

    def _recompute_params(self) -> None:
        """Derive OscillatorParams from the current temperament.

        Scaling choices:
        - mass = 1/volatility, clamped to [0.25, 4.0]
        - stiffness scaled × 0.15 so impulses aren't immediately annulled by
          the recovery spring — emotions persist for ~10s before fading.
        - damping tuned to be underdamped (ζ≈0.5) for natural-feeling motion.
        - impulse_gain = intensity_base so temperament directly scales reaction.
        """
        t = self.temperament
        mass = max(0.25, min(4.0, 1.0 / max(0.05, t.volatility)))
        self._person_params = OscillatorParams(
            mass=mass,
            stiffness=max(0.02, t.recovery_speed * 0.15),
            damping=0.35 + 0.25 * (1.0 - t.volatility),
            impulse_gain=max(0.1, t.intensity_base),
        )
        # Global mood is lazier: softer spring, heavier mass, slower to react.
        self._global_params = OscillatorParams(
            mass=mass * 1.5,
            stiffness=max(0.015, t.recovery_speed * 0.08),
            damping=0.5,
            impulse_gain=max(0.05, t.global_bleed),
        )

    # ------------------------------------------------------------------
    # State persistence (lossy label-level snapshots, no DB migration)
    # ------------------------------------------------------------------

    async def _save_state(self):
        """Persist current state as (label, intensity) snapshots per person + global."""
        from asgiref.sync import sync_to_async
        from memory.manager import memory_manager
        from memory.models import EmotionSnapshot

        conversation = memory_manager.conversation
        if not conversation:
            return

        try:
            g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)
            await sync_to_async(EmotionSnapshot.objects.create)(
                conversation=conversation,
                person_id="__global__",
                primary_emotion=g_label.value,
                primary_intensity=g_intensity,
                global_emotion=g_label.value,
                global_intensity=g_intensity,
            )

            for pid, mood in self.person_moods.items():
                p_label, p_intensity = pad.pad_to_label(mood.dynamic.position)
                await sync_to_async(EmotionSnapshot.objects.create)(
                    conversation=conversation,
                    person_id=pid,
                    primary_emotion=p_label.value,
                    primary_intensity=p_intensity,
                    global_emotion=g_label.value,
                    global_intensity=g_intensity,
                )

            logger.info(
                "Saved emotion state: global=%s(%.2f), %d person mood(s)",
                g_label.value, g_intensity, len(self.person_moods),
            )
        except Exception:
            logger.exception("Failed to save emotion state")

    async def _restore_state(self) -> bool:
        """Restore state from snapshots (+summary fallback). Lossy reconstruction.

        The oscillator starts at rest (velocity=0) at the reconstructed position,
        and will settle toward home via the decay loop over a few seconds.
        """
        from asgiref.sync import sync_to_async
        from django.db.models import Max
        from memory.models import EmotionSnapshot

        max_age_seconds = self._SNAPSHOT_DECAY_DAYS * 86400

        try:
            now_ts = time.time()

            latest_ids = await sync_to_async(
                lambda: list(
                    EmotionSnapshot.objects
                    .values("person_id")
                    .annotate(latest_id=Max("id"))
                    .values_list("latest_id", flat=True)
                )
            )()

            persons_from_snapshots: set[str] = set()
            restored_persons = 0

            if latest_ids:
                snapshots = await sync_to_async(
                    lambda: list(EmotionSnapshot.objects.filter(id__in=latest_ids))
                )()

                for snap in snapshots:
                    elapsed = now_ts - snap.created_at.timestamp()
                    time_factor = max(0.0, 1.0 - elapsed / max_age_seconds)
                    intensity = snap.primary_intensity * time_factor

                    try:
                        label = Emotion(snap.primary_emotion)
                    except ValueError:
                        label = self.temperament.default_mood

                    position = pad.label_to_pad(label, intensity)

                    if snap.person_id == "__global__":
                        self.global_mood.dynamic.position = position
                        self.global_mood.dynamic.velocity = pad.zero()
                    else:
                        persons_from_snapshots.add(snap.person_id)
                        if intensity < 0.05:
                            continue
                        mood = PersonMood(person_id=snap.person_id)
                        mood.dynamic.position = position
                        self.person_moods[snap.person_id] = mood
                        restored_persons += 1

            summary_restored = await self._restore_from_summaries(
                exclude_persons=persons_from_snapshots
            )
            restored_persons += summary_restored

            if restored_persons == 0 and pad.norm(self.global_mood.dynamic.position) < 0.05:
                return False

            g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)
            logger.info(
                "Restored emotion state: global=%s(%.2f), %d person(s) "
                "[snapshots: %d, summaries: %d]",
                g_label.value, g_intensity,
                restored_persons,
                restored_persons - summary_restored,
                summary_restored,
            )
            return True

        except Exception:
            logger.exception("Failed to restore emotion state")
            return False

    async def _restore_from_summaries(self, exclude_persons: set[str]) -> int:
        """Seed person moods from EmotionalSummary for persons not already loaded."""
        from asgiref.sync import sync_to_async
        from datetime import date
        from django.db.models import Max
        from memory.models import EmotionalSummary

        try:
            latest_rows = await sync_to_async(
                lambda: list(
                    EmotionalSummary.objects
                    .filter(period_type="daily")
                    .exclude(person_id__in=exclude_persons)
                    .values("person_id")
                    .annotate(latest_date=Max("period_start"))
                )
            )()

            if not latest_rows:
                return 0

            today = date.today()
            restored = 0
            for row in latest_rows:
                pid = row["person_id"]
                age_days = (today - row["latest_date"]).days
                if age_days >= self._SUMMARY_DECAY_DAYS:
                    continue

                result = await self._mood_from_summary(pid)
                if result is None:
                    continue

                label, intensity = result
                mood = PersonMood(person_id=pid)
                mood.dynamic.position = pad.label_to_pad(label, intensity)
                self.person_moods[pid] = mood
                restored += 1

            return restored

        except Exception as exc:
            degradations.record("emotion.engine._restore_from_summaries", exc)
            logger.debug("Failed to restore from summaries", exc_info=True)
            return 0

    async def _mood_from_summary(self, person_id: str) -> tuple[Emotion, float] | None:
        """Return (emotion, intensity) seeded from the most recent EmotionalSummary."""
        from asgiref.sync import sync_to_async
        from datetime import date
        from memory.models import EmotionalSummary

        try:
            summary = await sync_to_async(
                lambda: EmotionalSummary.objects
                .filter(person_id=person_id, period_type="daily")
                .order_by("-period_start")
                .first()
            )()

            if not summary:
                return None

            age_days = (date.today() - summary.period_start).days
            if age_days >= self._SUMMARY_DECAY_DAYS:
                return None

            time_factor = max(0.0, 1.0 - age_days / self._SUMMARY_DECAY_DAYS)
            intensity = summary.dominant_intensity * time_factor

            if intensity < 0.05:
                return None

            try:
                emotion = Emotion(summary.dominant_emotion)
            except ValueError:
                return None

            return emotion, intensity

        except Exception as exc:
            degradations.record("emotion.engine._mood_from_summary", exc)
            logger.debug(
                "Failed to load EmotionalSummary for %s", person_id, exc_info=True
            )
            return None

    async def ensure_person_loaded(self, person_id: str) -> None:
        """Hydrate a person's mood from DB if they are not currently in RAM."""
        if person_id in self.person_moods or person_id in ("__global__", "anonymous"):
            return

        max_age_seconds = self._SNAPSHOT_DECAY_DAYS * 86400
        now_ts = time.time()

        try:
            from asgiref.sync import sync_to_async
            from memory.models import EmotionSnapshot

            snap = await sync_to_async(
                lambda: EmotionSnapshot.objects
                .filter(person_id=person_id)
                .order_by("-created_at")
                .first()
            )()

            if snap:
                elapsed = now_ts - snap.created_at.timestamp()
                time_factor = max(0.0, 1.0 - elapsed / max_age_seconds)
                intensity = snap.primary_intensity * time_factor

                if intensity >= 0.05:
                    try:
                        label = Emotion(snap.primary_emotion)
                        mood = PersonMood(person_id=person_id)
                        mood.dynamic.position = pad.label_to_pad(label, intensity)
                        self.person_moods[person_id] = mood
                        logger.debug(
                            "Lazy-loaded mood for %s: %s(%.2f) from snapshot ~%dh ago",
                            person_id, label.value, intensity, int(elapsed / 3600),
                        )
                        return
                    except ValueError:
                        pass

            result = await self._mood_from_summary(person_id)
            if result is not None:
                label, intensity = result
                mood = PersonMood(person_id=person_id)
                mood.dynamic.position = pad.label_to_pad(label, intensity)
                self.person_moods[person_id] = mood
                logger.debug(
                    "Lazy-loaded mood for %s: %s(%.2f) from EmotionalSummary",
                    person_id, label.value, intensity,
                )

        except Exception as exc:
            degradations.record("emotion.engine.ensure_person_loaded", exc)
            logger.debug(
                "Failed to lazy-load mood for %s", person_id, exc_info=True
            )

    # ------------------------------------------------------------------
    # Periodic snapshots (for emotional memory)
    # ------------------------------------------------------------------

    async def _maybe_save_snapshot(self, person_id: str) -> None:
        """Save a snapshot if enough time has passed since the last one.

        Protected against concurrent calls on the same person_id so we
        never double-insert snapshots when a user sends several messages
        in quick succession.
        """
        async with self._snapshot_lock:
            now = time.time()
            last = self._last_snapshot_time.get(person_id, 0)
            if now - last < self._snapshot_interval:
                return
            self._last_snapshot_time[person_id] = now
        await self._save_person_snapshot(person_id)

    async def _save_person_snapshot(self, person_id: str) -> None:
        """Persist a single EmotionSnapshot for one person + current global mood."""
        from asgiref.sync import sync_to_async
        from memory.manager import memory_manager
        from memory.models import EmotionSnapshot

        conversation = memory_manager.conversation
        if not conversation:
            return

        person = self._get_person_mood(person_id)
        p_label, p_intensity = pad.pad_to_label(person.dynamic.position)
        g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)

        try:
            await sync_to_async(EmotionSnapshot.objects.create)(
                conversation=conversation,
                person_id=person_id,
                primary_emotion=p_label.value,
                primary_intensity=p_intensity,
                global_emotion=g_label.value,
                global_intensity=g_intensity,
            )
        except Exception as exc:
            degradations.record("emotion.engine._save_person_snapshot", exc)
            logger.debug("Failed to save snapshot for %s", person_id, exc_info=True)

    # ------------------------------------------------------------------
    # Person mood management
    # ------------------------------------------------------------------

    def _get_person_mood(self, person_id: str) -> PersonMood:
        """Get or create mood state for a person. New persons start at origin."""
        if person_id not in self.person_moods:
            self.person_moods[person_id] = PersonMood(person_id=person_id)
        return self.person_moods[person_id]

    def _home_vector(self) -> Vec3:
        """Home position for all oscillators.

        Combines two contributions:
          - `default_mood` heavily dimmed (magnitude 0.15) — the character's
            stable baseline personality
          - `circadian phase bias` (magnitude ~0.35 per circadian.py) — a
            time-of-day tint that nudges the baseline toward hopeful/playful/
            relieved/dreamy through the day

        Both are small so that emotional impulses still dominate the
        short-term dynamics — but the persistent pull gives Mika a felt
        "daily rhythm" without the character losing its identity.
        """
        from emotion import circadian

        base = pad.label_to_pad(self.temperament.default_mood, 0.15)

        try:
            from config.personality import personality
            profile = personality.circadian_profile
        except Exception as exc:
            degradations.record("emotion.engine._home_vector", exc)
            profile = None

        state = circadian.current_state(profile=profile)
        bias = circadian.phase_bias(state.phase, profile=profile)

        return pad.add(base, bias)

    # ------------------------------------------------------------------
    # Core: process a new emotion from Claude
    # ------------------------------------------------------------------

    def process_emotion(
        self, emotion_data: EmotionData, person_id: str
    ) -> PersonMood:
        """Apply a new emotion as an impulse toward its PAD anchor.

        The physics handles reinforcement (successive impulses accumulate
        velocity), opposition (impulses pointing against current position
        decelerate it), and naturalness (far-away targets produce larger
        impulses but are resisted by mass+damping).
        """
        self._recompute_params()  # in case temperament changed at runtime

        now = time.time()
        person = self._get_person_mood(person_id)

        target = pad.label_to_pad(emotion_data.emotion, emotion_data.intensity)
        person.dynamic.impulse_toward(target, self._person_params)

        # Propagate a fraction of the impulse into the global mood.
        global_target = pad.scale(target, self.temperament.global_bleed)
        self.global_mood.dynamic.impulse_toward(global_target, self._global_params)

        person.last_interaction = now
        person.last_update = now
        self.global_mood.last_update = now

        person.history.append(EmotionHistoryEntry(
            timestamp=now,
            emotion=emotion_data.emotion,
            intensity=emotion_data.intensity,
            source="impulse",
        ))

        logger.debug(
            "Emotion [%s]: impulse toward %s(%.2f)",
            person_id, emotion_data.emotion.value, emotion_data.intensity,
        )

        return person

    # ------------------------------------------------------------------
    # Compute message emotion (blend of person + global)
    # ------------------------------------------------------------------

    def compute_message_emotion(self, person_id: str) -> MessageEmotion:
        """Compute the final emotion for a message by blending PAD positions.

        Weights: 60% person position + 40% global position in PAD space.
        The blend is a weighted mean of the two 3D vectors, then projected
        back onto the top-2 nearest anchors so the output can express
        ambivalence (e.g. "mostly grateful, a touch nostalgic").
        """
        person = self._get_person_mood(person_id)
        default = self.temperament.default_mood

        p_label, p_intensity = pad.pad_to_label(person.dynamic.position)
        g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)

        blended = pad.add(
            pad.scale(person.dynamic.position, 0.6),
            pad.scale(self.global_mood.dynamic.position, 0.4),
        )
        final_label, final_intensity = pad.pad_to_label(blended)
        blend_components = pad.pad_to_blend(blended, top_k=2)

        # If the blended vector is essentially zero, expose the default mood
        # as a weak background so the frontend doesn't get stuck on neutral.
        if final_intensity < 0.05:
            final_label = default
            final_intensity = 0.1
            if not blend_components:
                blend_components = [(default, 0.1)]

        return MessageEmotion(
            emotion=final_label,
            intensity=round(final_intensity, 2),
            person_emotion=p_label if p_intensity > 0.05 else default,
            person_intensity=round(p_intensity, 2),
            global_emotion=g_label if g_intensity > 0.05 else default,
            global_intensity=round(g_intensity, 2),
            blend=tuple(blend_components),
        )

    # ------------------------------------------------------------------
    # System prompt context
    # ------------------------------------------------------------------

    def get_global_mood_context(self) -> str:
        """French description of Mika's *standalone* emotional state.

        This is about Mika alone, independent of the interlocutor. The
        per-person affective stance belongs to `get_person_affect_context()`
        and is injected in the `person_context` block, not here.
        """
        default = self.temperament.default_mood
        return self.global_mood.to_prompt_description(default)

    def get_person_affect_context(self, person_id: str) -> str:
        """French description of how Mika feels *toward this specific person*.

        Covers both the current PersonMood (live PAD oscillator) and the
        "ancrage" marker when the state is actively engaged (high velocity
        and intensity). Returned as a block ready to be concatenated into
        the person_context section.

        Returns "" when the state is effectively neutral — absence is
        more useful than boilerplate ("pas de sentiment particulier")
        for every unfamiliar person. The caller's context block stays
        empty in that case, which keeps the prompt lean.
        """
        person = self._get_person_mood(person_id)
        intensity = pad.norm(person.dynamic.position)
        speed = pad.norm(person.dynamic.velocity)
        # Engagement = enough settled state (position) OR a fresh impulse
        # (velocity). A just-applied impulse hasn't yet moved the position,
        # but the energy is real and should surface in the prompt.
        if intensity < 0.1 and speed < 0.15:
            return ""

        lines: list[str] = [person.to_prompt_description()]

        if speed > 0.3 and intensity > 0.4:
            lines.append(
                "Cette emotion envers cette personne est bien ancree, "
                "elle ne va pas s'estomper facilement."
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # State dict for WebSocket
    # ------------------------------------------------------------------

    def get_state_dict(self, person_id: str) -> dict:
        """Get full emotional state for WebSocket broadcast."""
        person = self._get_person_mood(person_id)
        msg = self.compute_message_emotion(person_id)

        return {
            "person": person.to_dict(),
            "global": self.global_mood.to_dict(),
            "message": msg.to_dict(),
        }

    # ------------------------------------------------------------------
    # Decay loop — pure physics integration
    # ------------------------------------------------------------------

    async def _decay_loop(self):
        """Background loop: advance all oscillators every second."""
        while True:
            try:
                await asyncio.sleep(_TICK_DT)
                self._apply_decay()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Emotion decay loop error")

    @staticmethod
    def _advance(dynamic, home: Vec3, params: OscillatorParams, total_dt: float) -> None:
        """Advance an oscillator by total_dt seconds in stable sub-steps."""
        remaining = min(total_dt, _MAX_ADVANCE_SECONDS)
        while remaining > 1e-6:
            step_dt = min(_MAX_SUBSTEP_DT, remaining)
            dynamic.step(home, params, step_dt)
            remaining -= step_dt

    def _apply_decay(self):
        """Step the physics forward. Sub-divides into stable chunks."""
        now = time.time()
        home = self._home_vector()

        # Step person moods
        expired_persons = []
        for pid, person in self.person_moods.items():
            dt = max(0.0, now - person.last_update)
            if dt <= 0.0:
                continue

            self._advance(person.dynamic, home, self._person_params, dt)
            person.last_update = now

            if (
                now - person.last_interaction > self._IDLE_EVICTION_SECONDS
                and pad.distance(person.dynamic.position, home) < 0.05
            ):
                expired_persons.append(pid)

        for pid in expired_persons:
            del self.person_moods[pid]

        # Step global mood
        dt = max(0.0, now - self.global_mood.last_update)
        if dt > 0.0:
            self._advance(self.global_mood.dynamic, home, self._global_params, dt)
            self.global_mood.last_update = now

        # Spontaneous mood drift: tiny random nudge so the global mood
        # doesn't sit perfectly on its home point when nothing is happening.
        # Scaled by:
        #   - stillness  (only nudge when close to rest — real impulses
        #                 still dominate when something is happening)
        #   - volatility (stoic personas barely drift, explosive ones do
        #                 — matches temperament personality)
        volatility_scale = max(0.0, self.temperament.volatility)
        if volatility_scale > 0.25 and random.random() < _SPONTANEOUS_NUDGE_PROBABILITY:
            distance = pad.distance(self.global_mood.dynamic.position, home)
            stillness = max(0.0, 1.0 - distance * 3.0)  # 0 when far, 1 when at home
            if stillness > 0.2:
                magnitude = (
                    _SPONTANEOUS_NUDGE_MAX
                    * stillness
                    * volatility_scale
                    * random.random()
                )
                nudge: Vec3 = (
                    random.uniform(-1.0, 1.0) * magnitude,
                    random.uniform(-1.0, 1.0) * magnitude,
                    random.uniform(-1.0, 1.0) * magnitude,
                )
                self.global_mood.dynamic.position = pad.clamp_component(
                    pad.add(self.global_mood.dynamic.position, nudge),
                    limit=1.0,
                )

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_analytics(self) -> dict:
        """Compute emotion analytics across all persons."""
        all_entries = []
        for person in self.person_moods.values():
            all_entries.extend(person.history)

        if not all_entries:
            return {
                "total_interactions": 0,
                "distribution": {},
                "dominant_emotion": self.temperament.default_mood.value,
                "persons_tracked": 0,
            }

        distribution: dict[str, float] = {}
        for entry in all_entries:
            key = entry.emotion.value
            distribution[key] = distribution.get(key, 0.0) + entry.intensity

        total = sum(distribution.values()) or 1.0
        distribution = {k: round(v / total, 3) for k, v in distribution.items()}
        dominant = max(distribution, key=distribution.get)

        return {
            "total_interactions": len(all_entries),
            "distribution": distribution,
            "dominant_emotion": dominant,
            "persons_tracked": len(self.person_moods),
        }


# Module-level singleton
emotion_engine = EmotionEngine()
