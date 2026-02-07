import asyncio
import logging
import time

from django.conf import settings

from ai.emotion_types import (
    Emotion,
    EmotionCategory,
    EmotionData,
    EMOTION_CATEGORIES,
    OPPOSITE_CATEGORIES,
    TRANSITION_OVERRIDES,
)
from ai.emotion_state import (
    EmotionHistoryEntry,
    GlobalMood,
    MessageEmotion,
    PersonMood,
    Temperament,
)

logger = logging.getLogger(__name__)

DEFAULT_DECAY_RATE = 0.02  # intensity lost per second (before temperament scaling)


class EmotionEngine:
    """Central emotion orchestrator with 3 layers:

    1. Per-person mood (person_moods) - how the VTuber feels about each person
    2. Global mood (global_mood) - overall emotional state affecting all conversations
    3. Message emotion (computed) - blend of person + global for each response
    """

    def __init__(self):
        self.person_moods: dict[str, PersonMood] = {}
        self.global_mood = GlobalMood()
        self.temperament = Temperament()
        self._decay_task: asyncio.Task | None = None
        self._initialized = False
        self._decay_rate = DEFAULT_DECAY_RATE

    async def initialize(self):
        """Load temperament from personality and start decay loop."""
        if self._initialized:
            return

        from config.personality import personality
        self.temperament = personality.temperament

        self._decay_rate = getattr(
            settings, "EMOTION_DECAY_RATE", DEFAULT_DECAY_RATE
        )

        # Set global mood to default
        self.global_mood.emotion = self.temperament.default_mood
        self.global_mood.intensity = 0.0

        self._decay_task = asyncio.create_task(self._decay_loop())
        self._initialized = True
        logger.info(
            "EmotionEngine initialized (temperament: volatility=%.1f, "
            "intensity_base=%.1f, recovery=%.1f, default_mood=%s, bleed=%.1f)",
            self.temperament.volatility,
            self.temperament.intensity_base,
            self.temperament.recovery_speed,
            self.temperament.default_mood.value,
            self.temperament.global_bleed,
        )

    async def shutdown(self):
        if self._decay_task:
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                pass
        logger.info("EmotionEngine shut down")

    # ------------------------------------------------------------------
    # Person mood management
    # ------------------------------------------------------------------

    def _get_person_mood(self, person_id: str) -> PersonMood:
        """Get or create mood state for a person."""
        if person_id not in self.person_moods:
            self.person_moods[person_id] = PersonMood(
                person_id=person_id,
                emotion=self.temperament.default_mood,
                intensity=0.0,
            )
        return self.person_moods[person_id]

    # ------------------------------------------------------------------
    # Core: process a new emotion from Claude
    # ------------------------------------------------------------------

    def process_emotion(
        self, emotion_data: EmotionData, person_id: str
    ) -> PersonMood:
        """Process a new emotion from a Claude response.

        1. Update person mood (transitions, momentum, opposition)
        2. Bleed into global mood
        3. Return updated person mood
        """
        now = time.time()
        person = self._get_person_mood(person_id)
        new_emotion = emotion_data.emotion
        # Scale intensity by temperament
        new_intensity = emotion_data.intensity * self.temperament.intensity_base

        old_emotion = person.emotion
        old_intensity = person.intensity
        old_cat = EMOTION_CATEGORIES.get(old_emotion, EmotionCategory.NEUTRAL_CAT)
        new_cat = EMOTION_CATEGORIES.get(new_emotion, EmotionCategory.NEUTRAL_CAT)

        source = "reinforcement"

        if new_emotion == old_emotion:
            # --- REINFORCEMENT: same emotion → build up ---
            person.intensity = min(1.0, old_intensity * 0.5 + new_intensity * 0.5)
            person.momentum = min(1.0, person.momentum + 0.15)
            source = "reinforcement"

        elif self._are_opposite(old_cat, new_cat) and old_intensity > 0.1:
            # --- OPPOSITION: positive vs negative → counter the current emotion ---
            # The new emotion fights the old one
            opposition_force = new_intensity * self.temperament.volatility
            remaining = old_intensity - opposition_force

            if remaining > 0.05:
                # Old emotion weakened but survives
                person.intensity = remaining
                person.momentum = max(0.0, person.momentum - 0.1)
                source = "opposition_partial"
            else:
                # Old emotion defeated, new one takes over
                person.emotion = new_emotion
                person.intensity = max(0.1, abs(remaining) + new_intensity * 0.3)
                person.momentum = 0.0
                source = "opposition_flip"

        elif new_emotion == Emotion.NEUTRAL and new_intensity >= 0.5:
            # --- ANNULATION: strong neutral → reset to default mood ---
            person.emotion = self.temperament.default_mood
            person.intensity = max(0.0, old_intensity - new_intensity * 0.5)
            person.momentum = max(0.0, person.momentum - 0.2)
            source = "annulation"

        else:
            # --- TRANSITION: different emotion, same or complex category ---
            naturalness = self._get_transition_naturalness(old_emotion, new_emotion)
            momentum_resistance = person.momentum * 0.4
            effective_intensity = (
                new_intensity
                * naturalness
                * self.temperament.volatility
                * (1.0 - momentum_resistance)
            )

            if effective_intensity > old_intensity * 0.3 or old_intensity < 0.15:
                person.emotion = new_emotion
                person.intensity = max(0.1, effective_intensity)
                person.momentum = max(0.0, person.momentum - 0.1)
                source = "transition"
            else:
                # Not strong enough to overcome current emotion
                person.intensity = max(0.0, old_intensity - 0.05)
                source = "transition_resisted"

        person.last_interaction = now
        person.last_update = now
        person.history.append(EmotionHistoryEntry(
            timestamp=now,
            emotion=new_emotion,
            intensity=person.intensity,
            source=source,
        ))

        # Bleed into global mood
        self._bleed_to_global(new_emotion, emotion_data.intensity)

        logger.debug(
            "Emotion [%s]: %s(%.2f) → %s(%.2f) [%s, momentum=%.2f]",
            person_id, old_emotion.value, old_intensity,
            person.emotion.value, person.intensity, source, person.momentum,
        )

        return person

    # ------------------------------------------------------------------
    # Global mood bleed
    # ------------------------------------------------------------------

    def _bleed_to_global(self, emotion: Emotion, raw_intensity: float):
        """Partially propagate a person's emotion to global mood."""
        bleed_amount = raw_intensity * self.temperament.global_bleed

        if bleed_amount < 0.05:
            return

        now = time.time()
        glob = self.global_mood

        if emotion == glob.emotion:
            # Reinforce global
            glob.intensity = min(1.0, glob.intensity + bleed_amount * 0.3)
        else:
            glob_cat = EMOTION_CATEGORIES.get(glob.emotion, EmotionCategory.NEUTRAL_CAT)
            new_cat = EMOTION_CATEGORIES.get(emotion, EmotionCategory.NEUTRAL_CAT)

            if self._are_opposite(glob_cat, new_cat) and glob.intensity > 0.1:
                # Opposition at global level too
                glob.intensity = max(0.0, glob.intensity - bleed_amount * 0.3)
                if glob.intensity < 0.05:
                    glob.emotion = emotion
                    glob.intensity = bleed_amount * 0.2
            elif bleed_amount > glob.intensity:
                # New emotion takes over global
                glob.emotion = emotion
                glob.intensity = bleed_amount * 0.5
            else:
                # Mild influence, not enough to change
                glob.intensity = max(0.0, glob.intensity - bleed_amount * 0.1)

        glob.last_update = now

    # ------------------------------------------------------------------
    # Compute message emotion (blend of person + global)
    # ------------------------------------------------------------------

    def compute_message_emotion(self, person_id: str) -> MessageEmotion:
        """Compute the final emotion for a message by blending person + global.

        Weights: 60% person mood, 40% global mood.
        """
        person = self._get_person_mood(person_id)
        glob = self.global_mood
        default = self.temperament.default_mood

        p_emotion = person.emotion if person.intensity > 0.1 else default
        p_intensity = person.intensity if person.intensity > 0.1 else 0.2

        g_emotion = glob.emotion if glob.intensity > 0.1 else default
        g_intensity = glob.intensity if glob.intensity > 0.1 else 0.1

        # Determine dominant emotion
        person_weight = p_intensity * 0.6
        global_weight = g_intensity * 0.4

        if person_weight >= global_weight:
            final_emotion = p_emotion
        else:
            final_emotion = g_emotion

        # Blend intensity
        final_intensity = min(1.0, person_weight + global_weight)

        # If person and global are opposite categories, dampen the result
        p_cat = EMOTION_CATEGORIES.get(p_emotion, EmotionCategory.NEUTRAL_CAT)
        g_cat = EMOTION_CATEGORIES.get(g_emotion, EmotionCategory.NEUTRAL_CAT)
        if self._are_opposite(p_cat, g_cat):
            final_intensity *= 0.7  # internal conflict dampens expression

        return MessageEmotion(
            emotion=final_emotion,
            intensity=round(final_intensity, 2),
            person_emotion=p_emotion,
            person_intensity=round(p_intensity, 2),
            global_emotion=g_emotion,
            global_intensity=round(g_intensity, 2),
        )

    # ------------------------------------------------------------------
    # System prompt context
    # ------------------------------------------------------------------

    def get_emotion_context(self, person_id: str) -> str:
        """Generate French text describing current emotional state for system prompt."""
        person = self._get_person_mood(person_id)
        default = self.temperament.default_mood

        lines = []
        lines.append(person.to_prompt_description())
        lines.append(self.global_mood.to_prompt_description(default))

        if person.momentum > 0.5:
            lines.append(
                "Cette emotion est bien ancree en toi en ce moment, "
                "tu ne vas pas changer d'humeur facilement."
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
    # Decay loop
    # ------------------------------------------------------------------

    async def _decay_loop(self):
        """Background loop: decay all emotions every second."""
        while True:
            try:
                await asyncio.sleep(1.0)
                self._apply_decay()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Emotion decay loop error")

    def _apply_decay(self):
        """Apply time-based decay to all person moods and global mood."""
        now = time.time()
        decay_base = self._decay_rate * self.temperament.recovery_speed
        default = self.temperament.default_mood

        # Decay person moods
        expired_persons = []
        for pid, person in self.person_moods.items():
            elapsed = now - person.last_update
            if elapsed < 0.5:
                continue

            decay_amount = decay_base * elapsed

            if person.emotion == default:
                # Already at default mood, just decay intensity toward 0
                person.intensity = max(0.0, person.intensity - decay_amount * 0.5)
            else:
                person.intensity -= decay_amount
                if person.intensity <= 0.05:
                    # Emotion fully decayed → revert to default
                    person.emotion = default
                    person.intensity = 0.0
                    person.momentum = 0.0

            # Decay momentum
            person.momentum = max(0.0, person.momentum - decay_amount * 0.3)
            person.last_update = now

            # Clean up persons inactive for 1 hour with no emotion
            if (
                now - person.last_interaction > 3600
                and person.intensity < 0.05
            ):
                expired_persons.append(pid)

        for pid in expired_persons:
            del self.person_moods[pid]

        # Decay global mood
        glob = self.global_mood
        elapsed = now - glob.last_update
        if elapsed >= 0.5:
            g_decay = decay_base * elapsed * 0.5  # global decays slower
            if glob.emotion == default:
                glob.intensity = max(0.0, glob.intensity - g_decay * 0.3)
            else:
                glob.intensity -= g_decay
                if glob.intensity <= 0.05:
                    glob.emotion = default
                    glob.intensity = 0.0
                    glob.momentum = 0.0
            glob.momentum = max(0.0, glob.momentum - g_decay * 0.2)
            glob.last_update = now

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _are_opposite(cat_a: EmotionCategory, cat_b: EmotionCategory) -> bool:
        """Check if two emotion categories are opposite (positive vs negative)."""
        return OPPOSITE_CATEGORIES.get(cat_a) == cat_b

    @staticmethod
    def _get_transition_naturalness(from_e: Emotion, to_e: Emotion) -> float:
        """Get how natural a transition between two emotions is (0.0-1.0)."""
        if from_e == to_e:
            return 1.0
        if to_e == Emotion.NEUTRAL:
            return 0.9

        # Check explicit overrides (both directions)
        if (from_e, to_e) in TRANSITION_OVERRIDES:
            return TRANSITION_OVERRIDES[(from_e, to_e)]
        if (to_e, from_e) in TRANSITION_OVERRIDES:
            return TRANSITION_OVERRIDES[(to_e, from_e)]

        # Default based on category
        from_cat = EMOTION_CATEGORIES.get(from_e, EmotionCategory.NEUTRAL_CAT)
        to_cat = EMOTION_CATEGORIES.get(to_e, EmotionCategory.NEUTRAL_CAT)

        if from_cat == to_cat:
            return 0.75
        if EmotionCategory.NEUTRAL_CAT in (from_cat, to_cat):
            return 0.7
        if EmotionCategory.COMPLEX in (from_cat, to_cat):
            return 0.6
        # Cross positive <-> negative
        return 0.35

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

        # Distribution weighted by intensity
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
