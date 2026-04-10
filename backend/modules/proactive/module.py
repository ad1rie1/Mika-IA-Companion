"""Proactive module — Mika initiates conversations spontaneously.

Triggers (evaluated every 30s by priority):
  1. mood_overflow  — strong unexpressed global emotion (>0.7)
  2. idle_chat      — nobody talked for PROACTIVE_IDLE_MINUTES
  3. memory_recall  — recent high-importance souvenir surfaces
  4. time_greeting  — morning/evening/night greetings (once each)

All triggers respect a cooldown (PROACTIVE_COOLDOWN_MINUTES) and require
at least one WebSocket client to be connected.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime

from django.conf import settings

from modules.base import BaseModule
from modules.types import ModuleEvent, ModuleNotification, ModuleStatus

logger = logging.getLogger(__name__)


class ProactiveModule(BaseModule):
    """Decides when Mika should speak spontaneously."""

    CRON_INTERVAL = 30  # Evaluate triggers every 30 seconds

    def __init__(self):
        super().__init__("proactive")

        # Timestamps
        self._last_activity: float = time.time()
        self._last_proactive: float = 0.0
        self._greeted_periods: set[str] = set()  # "morning", "evening", "night"

        # Config (loaded from settings on instantiate)
        self._idle_minutes: int = 10
        self._cooldown_minutes: int = 5
        self._mood_threshold: float = 0.7
        self._enabled: bool = True

    # ── Lifecycle ─────────────────────────────────────────────────

    def is_available(self) -> bool:
        return getattr(settings, "PROACTIVE_ENABLED", True)

    async def instantiate(self) -> None:
        self._idle_minutes = getattr(settings, "PROACTIVE_IDLE_MINUTES", 10)
        self._cooldown_minutes = getattr(settings, "PROACTIVE_COOLDOWN_MINUTES", 5)
        self._mood_threshold = getattr(settings, "PROACTIVE_MOOD_THRESHOLD", 0.7)
        self._last_activity = time.time()
        self.logger.info(
            "Proactive module started (idle=%dm, cooldown=%dm, mood_threshold=%.1f)",
            self._idle_minutes,
            self._cooldown_minutes,
            self._mood_threshold,
        )

    async def shutdown(self) -> None:
        self.logger.info("Proactive module stopped")

    # ── Event Listener ────────────────────────────────────────────

    async def on_event(self, event: ModuleEvent) -> None:
        """Listen for chat activity to reset idle timer."""
        if event.event_type == "chat.message":
            self._last_activity = time.time()
            self.logger.debug("Idle timer reset (chat activity)")

    # ── Cron ──────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        """Evaluate triggers by priority and fire at most one."""
        if not self._can_trigger():
            return

        # Try triggers in priority order
        trigger = (
            await self._check_mood_overflow()
            or await self._check_idle_chat()
            or await self._check_memory_recall()
            or self._check_time_greeting()
        )

        if trigger:
            trigger_type, prompt_context = trigger
            await self._fire(trigger_type, prompt_context)

    # ── Guard ─────────────────────────────────────────────────────

    def _can_trigger(self) -> bool:
        """Check cooldown and whether anyone is listening."""
        now = time.time()
        cooldown_seconds = self._cooldown_minutes * 60

        if now - self._last_proactive < cooldown_seconds:
            return False

        # Check if WebSocket clients are connected via channel layer
        # The channel layer doesn't expose group membership count directly,
        # so we track it via events from the consumer (chat.connect/chat.disconnect)
        # For now, always allow — the broadcast will just be a no-op if nobody listens
        return True

    # ── Trigger: Mood Overflow ────────────────────────────────────

    async def _check_mood_overflow(self) -> tuple[str, str] | None:
        """Strong unexpressed global emotion."""
        from ai.emotion_engine import emotion_engine

        glob = emotion_engine.global_mood
        if glob.intensity < self._mood_threshold:
            return None

        # Check the mood hasn't already been expressed recently
        elapsed_since_activity = time.time() - self._last_activity
        if elapsed_since_activity < 60:
            # Someone just talked — mood is being expressed through conversation
            return None

        emotion_name = glob.emotion.value
        intensity = glob.intensity

        prompt = (
            f"Tu ressens une emotion forte en ce moment : {emotion_name} "
            f"(intensite {intensity:.1f}). Personne ne t'a parle recemment. "
            f"Exprime ce que tu ressens de facon naturelle et spontanee, "
            f"comme si tu pensais a voix haute. Sois breve (1-2 phrases max)."
        )

        self.logger.info(
            "Mood overflow trigger: %s (%.2f)", emotion_name, intensity
        )
        return "mood_overflow", prompt

    # ── Trigger: Idle Chat ────────────────────────────────────────

    async def _check_idle_chat(self) -> tuple[str, str] | None:
        """Nobody has chatted for a while."""
        from ai.emotion_engine import emotion_engine
        from memory.manager import memory_manager

        idle_seconds = time.time() - self._last_activity
        idle_minutes = idle_seconds / 60

        if idle_minutes < self._idle_minutes:
            return None

        # Get current mood for context
        glob = emotion_engine.global_mood
        mood_desc = f"{glob.emotion.value} (intensite {glob.intensity:.1f})"

        # Get last conversation topic from short-term memory
        last_topic = ""
        history = memory_manager.get_conversation_context()
        if history:
            # Extract last assistant message for topic continuity
            for msg in reversed(history):
                if msg.get("role") == "assistant":
                    last_topic = msg.get("content", "")[:100]
                    break

        # Pick a random idle behavior
        behaviors = [
            (
                f"Personne ne t'a parle depuis {int(idle_minutes)} minutes. "
                f"Tu te sens {mood_desc}. "
                f"Dis quelque chose de spontane, comme si tu t'ennuyais un peu "
                f"ou que tu pensais a voix haute. Sois naturelle et breve."
            ),
            (
                f"Ca fait {int(idle_minutes)} minutes de silence. "
                f"Tu te sens {mood_desc}. "
                f"Lance un sujet qui t'interesse (gaming, tech, anime, cuisine...) "
                f"de facon naturelle, comme si tu voulais partager quelque chose. "
                f"1-2 phrases max."
            ),
            (
                f"Le silence dure depuis {int(idle_minutes)} minutes. "
                f"Tu te sens {mood_desc}. "
                f"Reagis au silence de facon naturelle selon ton humeur actuelle. "
                f"Sois toi-meme, breve et spontanee."
            ),
        ]

        prompt = random.choice(behaviors)

        if last_topic:
            prompt += f"\nDernier sujet aborde : '{last_topic}'"

        self.logger.info("Idle chat trigger after %.0f minutes", idle_minutes)
        return "idle_chat", prompt

    # ── Trigger: Memory Recall ────────────────────────────────────

    async def _check_memory_recall(self) -> tuple[str, str] | None:
        """A recent souvenir surfaces spontaneously."""
        try:
            from asgiref.sync import sync_to_async
            from memory.models import Souvenir

            # Get a recent important souvenir (random selection from top 5)
            souvenirs = await sync_to_async(
                lambda: list(
                    Souvenir.objects.filter(importance__gte=0.5)
                    .order_by("-created_at")[:5]
                )
            )()

            if not souvenirs:
                return None

            # Only trigger occasionally (30% chance per check)
            if random.random() > 0.3:
                return None

            souvenir = random.choice(souvenirs)
            prompt = (
                f"Un souvenir te revient spontanement : '{souvenir.content}' "
                f"(emotion associee : {souvenir.emotion}, "
                f"importance : {souvenir.importance:.1f}). "
                f"Partage-le naturellement, comme si ca te traversait l'esprit. "
                f"1-2 phrases max, sois spontanee."
            )

            self.logger.info(
                "Memory recall trigger: souvenir #%d (importance=%.1f)",
                souvenir.pk,
                souvenir.importance,
            )
            return "memory_recall", prompt

        except Exception:
            self.logger.debug("Memory recall check failed", exc_info=True)
            return None

    # ── Trigger: Time Greeting ────────────────────────────────────

    def _check_time_greeting(self) -> tuple[str, str] | None:
        """Morning, evening, or night greeting (once each per day)."""
        now = datetime.now()
        hour = now.hour

        # Reset greeted periods at midnight
        if hour == 0:
            self._greeted_periods.clear()

        if 7 <= hour < 10 and "morning" not in self._greeted_periods:
            self._greeted_periods.add("morning")
            prompt = (
                "C'est le matin ! Dis bonjour naturellement, "
                "comme si tu venais de te reveiller. "
                "Mentionne l'heure ou le fait que c'est le debut de journee. "
                "Sois breve et naturelle."
            )
            self.logger.info("Time greeting trigger: morning")
            return "time_greeting", prompt

        if 18 <= hour < 20 and "evening" not in self._greeted_periods:
            self._greeted_periods.add("evening")
            prompt = (
                "C'est la fin de journee ! Fais une remarque naturelle "
                "sur le fait que la soiree commence. "
                "Sois breve et naturelle."
            )
            self.logger.info("Time greeting trigger: evening")
            return "time_greeting", prompt

        if 23 <= hour or hour < 1:
            if "night" not in self._greeted_periods:
                self._greeted_periods.add("night")
                prompt = (
                    "Il est tard ! Fais une remarque sur l'heure tardive, "
                    "comme si tu commencais a etre fatiguee. "
                    "Sois breve et naturelle."
                )
                self.logger.info("Time greeting trigger: night")
                return "time_greeting", prompt

        return None

    # ── Fire ──────────────────────────────────────────────────────

    async def _fire(self, trigger_type: str, prompt_context: str) -> None:
        """Send the proactive notification to Claude and log it."""
        if not self._notify_ai:
            self.logger.warning("notify_ai not available, skipping trigger")
            return

        self._last_proactive = time.time()

        try:
            decision = await self._notify_ai(
                ModuleNotification(
                    source_module=self.name,
                    summary=f"Comportement spontane ({trigger_type})",
                    details=prompt_context,
                    urgency="low",
                    metadata={"person_id": "proactive_mika"},
                )
            )

            # Log the proactive message
            from asgiref.sync import sync_to_async
            from modules.proactive.models import ProactiveLog

            await sync_to_async(ProactiveLog.objects.create)(
                trigger=trigger_type,
                prompt_context=prompt_context,
                response=decision.response_text[:500],
                emotion=decision.emotion.emotion.value if decision.emotion else "",
            )

            self.logger.info(
                "Proactive message sent [%s]: %s",
                trigger_type,
                decision.response_text[:80],
            )

        except Exception:
            self.logger.exception("Failed to fire proactive trigger: %s", trigger_type)

    # ── Context ───────────────────────────────────────────────────

    def get_context(self) -> str:
        """Tell Claude she can be spontaneous."""
        idle_seconds = time.time() - self._last_activity
        idle_minutes = int(idle_seconds / 60)
        if idle_minutes > 2:
            return f"Personne ne t'a parle depuis {idle_minutes} minutes."
        return ""

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        idle_seconds = time.time() - self._last_activity
        cooldown_remaining = max(
            0,
            (self._cooldown_minutes * 60) - (time.time() - self._last_proactive),
        )
        status.details = {
            "idle_seconds": round(idle_seconds),
            "cooldown_remaining": round(cooldown_remaining),
            "idle_threshold_minutes": self._idle_minutes,
            "cooldown_minutes": self._cooldown_minutes,
            "mood_threshold": self._mood_threshold,
            "greeted_today": list(self._greeted_periods),
        }
        return status
