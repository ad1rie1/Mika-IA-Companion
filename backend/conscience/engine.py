"""ConscienceEngine — Mika's waking brain.

Sits above modules. Observes all events, interprets them, maintains
memory, and decides when to speak or act. Tightly coupled to memory
with full R/W access.

Lifecycle (managed by ASGI lifespan):
  1. initialize()   — start decision loop + observers
  2. observe(event)  — called by event bus for every module event
  3. _decision_loop  — periodic evaluation (every 30s)
  4. shutdown()      — stop everything
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime

from asgiref.sync import sync_to_async
from django.conf import settings

from conscience.interpreter import SignalInterpreter
from conscience.memory_bridge import MemoryBridge
from conscience.observer import ObserverRegistry
from conscience.types import DecisionContext, InterpretedSignal
from modules.types import ModuleEvent, ModuleNotification

logger = logging.getLogger(__name__)


class ConscienceEngine:
    """Singleton. Mika's waking consciousness.

    Short-term buffer: recent Observations (in DB, queried on sliding window).
    Long-term memory: R/W via MemoryBridge.
    """

    def __init__(self):
        self.interpreter = SignalInterpreter()
        self.memory = MemoryBridge()
        self.observer_registry = ObserverRegistry()

        # State
        self._decision_task: asyncio.Task | None = None
        self._decision_lock = asyncio.Lock()
        self._last_activity: float = time.time()
        self._last_action_time: float = 0.0
        self._greeted_periods: set[str] = set()
        self._initialized = False

        # Config (loaded from settings on initialize)
        self._decision_interval: int = 30
        self._cooldown_seconds: int = 300
        self._threshold: float = 0.5

    # ── Lifecycle ─────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self._initialized:
            return

        self._decision_interval = getattr(settings, "CONSCIENCE_DECISION_INTERVAL", 30)
        self._cooldown_seconds = getattr(settings, "CONSCIENCE_COOLDOWN_SECONDS", 300)
        self._threshold = getattr(settings, "CONSCIENCE_ACT_THRESHOLD", 0.5)

        await self.observer_registry.start_all()
        self._decision_task = asyncio.create_task(self._decision_loop())
        self._initialized = True

        logger.info(
            "Conscience initialized (interval=%ds, cooldown=%ds, threshold=%.1f)",
            self._decision_interval,
            self._cooldown_seconds,
            self._threshold,
        )

    async def shutdown(self) -> None:
        if self._decision_task:
            self._decision_task.cancel()
            try:
                await self._decision_task
            except asyncio.CancelledError:
                pass

        await self.observer_registry.stop_all()
        self._initialized = False
        logger.info("Conscience shut down")

    # ── 1. OBSERVE ────────────────────────────────────────────────

    async def observe(self, event: ModuleEvent) -> None:
        """Receive a module event, interpret it, store it.

        Called by the event bus (ModuleManager.emit_event callback).
        If the signal is important enough, immediately creates a souvenir.
        """
        signal = await self.interpreter.interpret(event)
        observation = await self._store_observation(event, signal)

        # Immediate memory action for high-pertinence signals
        if signal.should_remember and signal.pertinence > 0.5:
            souvenir = await self.memory.create_souvenir_from_signal(signal)
            if souvenir and observation:
                observation.souvenir = souvenir
                await sync_to_async(observation.save)(update_fields=["souvenir"])

        # Track activity for idle detection
        if event.event_type in ("chat.message", "telegram.message"):
            self._last_activity = time.time()

        logger.debug(
            "Observed: %s/%s → %s (p=%.1f)",
            event.source_module, event.event_type,
            signal.category, signal.pertinence,
        )

        # Fast-path: critical signals trigger an immediate decision cycle
        if signal.pertinence > 0.85:
            logger.info(
                "High-pertinence signal (%.2f), triggering immediate decision",
                signal.pertinence,
            )
            await self._decide()

    async def _store_observation(self, event, signal):
        """Persist an observation to DB."""
        from conscience.models import Observation

        try:
            return await sync_to_async(Observation.objects.create)(
                source=event.source_module,
                event_type=event.event_type,
                raw_data=event.data,
                summary=signal.summary,
                category=signal.category,
                pertinence=signal.pertinence,
                emotional_reaction=signal.emotional_reaction,
                emotional_intensity=signal.emotional_intensity,
            )
        except Exception:
            logger.exception("Failed to store observation")
            return None

    # ── 2. DECISION LOOP ──────────────────────────────────────────

    async def _decision_loop(self) -> None:
        """Periodic evaluation: observe external sources, decide, act."""
        while True:
            try:
                await asyncio.sleep(self._decision_interval)

                # Poll external observers
                now = time.time()
                external_events = await self.observer_registry.poll_due(now)
                for event in external_events:
                    await self.observe(event)

                # Run decision cycle
                await self._decide()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Conscience decision loop error")

    async def _decide(self) -> None:
        """Core decision: evaluate accumulated signals, maintain memory, maybe act.

        Protected by _decision_lock to prevent concurrent decisions from
        the periodic loop and high-pertinence fast-path racing.
        """
        if self._decision_lock.locked():
            logger.debug("Decision already in progress, skipping")
            return

        async with self._decision_lock:
            await self._decide_inner()

    async def _decide_inner(self) -> None:
        """Inner decision logic (caller must hold _decision_lock)."""
        ctx = await self._build_context()

        # Memory maintenance (runs every cycle, even without acting)
        memory_actions = await self._memory_maintenance(ctx)

        # Compute decision score
        score, reason = self._compute_score(ctx)

        # Determine decision outcome
        if score >= self._threshold:
            decision = "act"
        elif not ctx.pending_observations:
            decision = "skip"
        else:
            decision = "wait"

        # Log the decision
        await self._log_decision(ctx, decision, reason, score, memory_actions)

        if decision == "act":
            await self._act(ctx, reason)

    async def _build_context(self) -> DecisionContext:
        """Gather all context needed for a decision."""
        from conscience.models import Observation

        from ai.emotion_engine import emotion_engine

        now = time.time()

        # Pending observations (not acted upon, last 30 minutes)
        from django.utils import timezone as tz
        from datetime import timedelta

        cutoff = tz.now() - timedelta(minutes=30)
        pending = await sync_to_async(
            lambda: list(
                Observation.objects.filter(
                    acted_upon=False,
                    created_at__gte=cutoff,
                ).order_by("-pertinence")[:20]
            )
        )()

        # Cooldown check: use in-memory timestamp (faster, no DB query, no race)
        now_ts = time.time()
        in_cooldown = (
            self._last_action_time > 0
            and (now_ts - self._last_action_time) < self._cooldown_seconds
        )

        # Emotional state
        glob = emotion_engine.global_mood
        idle = now - self._last_activity

        # Compute aggregate scores
        pertinences = [o.pertinence for o in pending]
        max_p = max(pertinences) if pertinences else 0.0
        weighted = sum(p * 0.5 for p in pertinences if p > 0.3)

        return DecisionContext(
            pending_observations=pending,
            global_mood=glob.emotion.value,
            global_intensity=glob.intensity,
            idle_seconds=idle,
            in_cooldown=in_cooldown,
            max_pertinence=max_p,
            weighted_urgency=min(1.0, weighted),
        )

    def _compute_score(self, ctx: DecisionContext) -> tuple[float, str]:
        """Unified scoring. Returns (score, reason_string)."""

        # Cooldown check (in-memory, no DB query)
        if ctx.in_cooldown:
            return 0.0, "cooldown"

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
        time_trigger = self._check_time_trigger()
        if time_trigger:
            score += 0.35
            parts.append(f"time({time_trigger})")

        reason = ", ".join(parts) if parts else "no_signal"
        return score, reason

    def _check_time_trigger(self) -> str | None:
        """Check for time-based greeting triggers (once per period per day)."""
        now = datetime.now()
        hour = now.hour
        today = now.date()

        # Clear greeted set on new day (date-based, not hour-based — avoids midnight race)
        if not hasattr(self, "_greeted_date") or self._greeted_date != today:
            self._greeted_periods.clear()
            self._greeted_date = today

        if 7 <= hour < 10 and "morning" not in self._greeted_periods:
            self._greeted_periods.add("morning")
            return "morning"

        if 18 <= hour < 20 and "evening" not in self._greeted_periods:
            self._greeted_periods.add("evening")
            return "evening"

        if 23 <= hour and "night" not in self._greeted_periods:
            self._greeted_periods.add("night")
            return "night"

        return None

    # ── 3. MEMORY MAINTENANCE ─────────────────────────────────────

    async def _memory_maintenance(self, ctx: DecisionContext) -> list[str]:
        """Modify memory based on accumulated observations.

        Runs every decision cycle — the Conscience can reshape memory
        even without speaking.
        """
        actions = []

        for obs in ctx.pending_observations:
            # Boost related souvenirs for pertinent signals
            if obs.pertinence > 0.7:
                themes = obs.raw_data.get("themes", [])
                if themes:
                    count = await self.memory.boost_related_souvenirs(themes, 0.1)
                    if count:
                        actions.append(f"boosted {count} souvenirs (themes: {themes})")

            # Check contradictions for high-pertinence communication signals
            if obs.pertinence > 0.8 and obs.category == "communication":
                contradictions = await self.memory.check_contradictions(obs.summary)
                for c in contradictions:
                    if not c["still_valid"]:
                        actions.append(
                            f"invalidated connaissance #{c['connaissance_id']}"
                        )

        return actions

    # ── 4. ACT ────────────────────────────────────────────────────

    async def _act(self, ctx: DecisionContext, reason: str) -> None:
        """Generate a spontaneous response using accumulated context.

        Only loads tools from modules relevant to the current observations,
        not all 70+ tools. The Conscience uses capabilities to decide
        which modules are needed.
        """
        from modules.manager import module_manager

        self._last_action_time = time.time()

        # Recall relevant memories
        queries = [o.summary for o in ctx.pending_observations if o.pertinence > 0.3]
        memory_context = await self.memory.recall_for_context(queries)

        # Determine which modules are relevant based on observation sources
        relevant_modules = self._pick_relevant_modules(ctx)

        # Build prompt with capabilities summary
        capabilities_summary = module_manager.collect_capabilities_summary()
        prompt = self._build_action_prompt(ctx, reason, memory_context, capabilities_summary)

        try:
            # Build filtered MCP server with only relevant modules' tools
            if relevant_modules:
                mcp_server, tool_names = module_manager.build_mcp_server_for(
                    relevant_modules
                )
            else:
                mcp_server, tool_names = None, []

            from ai.client import claude_client
            from ai.emotion_engine import emotion_engine
            from ai.emotion_types import EmotionData, Emotion
            from memory.manager import memory_manager

            person_id = "conscience_mika"
            emotion_context = emotion_engine.get_emotion_context(person_id)
            module_context = module_manager.collect_context()
            history = memory_manager.get_conversation_context()

            if mcp_server and tool_names:
                response_text, emotion_data, tool_calls = (
                    await claude_client.chat_with_tools(
                        message=prompt,
                        conversation_history=history,
                        memory_context=memory_context,
                        emotion_context=emotion_context,
                        module_context=module_context,
                        mcp_server=mcp_server,
                        tool_names=tool_names,
                    )
                )
            else:
                response_text, emotion_data = await claude_client.chat(
                    message=prompt,
                    conversation_history=history,
                    memory_context=memory_context,
                    emotion_context=emotion_context,
                )
                tool_calls = []

            # Process emotion
            emotion_engine.process_emotion(emotion_data, person_id)

            # Store in memory
            await memory_manager.add_message("user", prompt, source="conscience")
            await memory_manager.add_message("assistant", response_text)

            # Broadcast to WebSocket
            from channels.layers import get_channel_layer
            from chat.consumers import BROADCAST_GROUP

            msg_emotion = emotion_engine.compute_message_emotion(person_id)
            channel_layer = get_channel_layer()
            await channel_layer.group_send(
                BROADCAST_GROUP,
                {
                    "type": "chat.broadcast",
                    "data": {
                        "type": "speech",
                        "text": response_text,
                        "emotion": msg_emotion.emotion.value,
                        "emotion_intensity": msg_emotion.intensity,
                        "emotion_state": emotion_engine.get_state_dict(person_id),
                        "source": "conscience",
                    },
                },
            )

            # Mark observations as acted upon
            for obs in ctx.pending_observations:
                obs.acted_upon = True
                obs.status = "acted"
                obs.action_response = response_text[:200]
                await sync_to_async(obs.save)(
                    update_fields=["acted_upon", "status", "action_response"]
                )

            if tool_calls:
                logger.info(
                    "Conscience tool calls: %s",
                    [str(tc)[:120] for tc in tool_calls],
                )

            logger.info(
                "Conscience acted [%s] (modules=%s, tools=%d): %s",
                reason, relevant_modules, len(tool_calls),
                response_text[:80],
            )

        except Exception:
            logger.exception("Conscience act failed")
            # Mark observations as failed so they don't retry indefinitely
            for obs in ctx.pending_observations:
                try:
                    obs.status = "failed"
                    await sync_to_async(obs.save)(update_fields=["status"])
                except Exception:
                    pass

    def _pick_relevant_modules(self, ctx: DecisionContext) -> list[str]:
        """Determine which modules are relevant based on pending observations."""
        sources = {obs.source for obs in ctx.pending_observations}

        # Always include modules whose events triggered this decision
        relevant = list(sources)

        # Add wake if we might want to self-schedule
        if any(obs.pertinence > 0.6 for obs in ctx.pending_observations):
            if "wake" not in relevant:
                relevant.append("wake")

        return relevant

    def _build_action_prompt(
        self,
        ctx: DecisionContext,
        reason: str,
        memory_context: str,
        capabilities_summary: str = "",
    ) -> str:
        """Build a rich prompt from accumulated observations + memory + capabilities."""
        parts = []

        # What you've observed
        if ctx.pending_observations:
            obs_lines = []
            for obs in ctx.pending_observations[:5]:
                obs_lines.append(f"- [{obs.source}] {obs.summary} (pertinence: {obs.pertinence:.1f})")
            parts.append(
                "Ce que tu as observe recemment:\n" + "\n".join(obs_lines)
            )

        # Current mood
        parts.append(
            f"Tu te sens {ctx.global_mood} (intensite {ctx.global_intensity:.1f})."
        )

        # Idle time
        idle_minutes = int(ctx.idle_seconds / 60)
        if idle_minutes > 2:
            parts.append(f"Personne ne t'a parle depuis {idle_minutes} minutes.")

        # Trigger reason
        if "morning" in reason:
            parts.append("C'est le matin ! Dis bonjour naturellement.")
        elif "evening" in reason:
            parts.append("C'est la soiree. Fais une remarque naturelle.")
        elif "night" in reason:
            parts.append("Il est tard. Mentionne l'heure tardive.")
        elif "mood" in reason:
            parts.append(
                "Tu as une emotion forte non exprimee. "
                "Dis ce que tu ressens comme si tu pensais a voix haute."
            )

        # Available capabilities (what you CAN do)
        if capabilities_summary:
            parts.append(
                "Ce que tu peux faire (utilise les outils si pertinent):\n"
                + capabilities_summary
            )

        # Memory context
        if memory_context:
            parts.append(f"\n{memory_context}")

        # Instructions
        parts.append(
            "\nExprime-toi naturellement et spontanement, "
            "en accord avec ce que tu observes et ressens. "
            "Sois breve (1-3 phrases max). "
            "Tu peux utiliser tes outils si la situation le demande."
        )

        return "\n\n".join(parts)

    @staticmethod
    def _urgency_from_score(ctx: DecisionContext) -> str:
        if ctx.max_pertinence > 0.9:
            return "high"
        if ctx.max_pertinence > 0.7:
            return "normal"
        return "low"

    # ── Decision Logging ──────────────────────────────────────────

    async def _log_decision(
        self,
        ctx: DecisionContext,
        decision: str,
        reason: str,
        score: float,
        memory_actions: list[str],
    ) -> None:
        from conscience.models import ConscienceLog

        try:
            await sync_to_async(ConscienceLog.objects.create)(
                observations_count=len(ctx.pending_observations),
                max_pertinence=ctx.max_pertinence,
                global_mood=ctx.global_mood,
                global_intensity=ctx.global_intensity,
                idle_seconds=int(ctx.idle_seconds),
                decision=decision,
                reason=f"{reason} (score={score:.2f})",
                memory_actions=memory_actions,
            )
        except Exception:
            logger.debug("Failed to log decision", exc_info=True)

        if decision != "skip":
            logger.info(
                "Conscience decision: %s (score=%.2f, reason=%s, obs=%d, memory_actions=%d)",
                decision, score, reason,
                len(ctx.pending_observations), len(memory_actions),
            )

    # ── Context for modules ───────────────────────────────────────

    def get_idle_seconds(self) -> float:
        return time.time() - self._last_activity


# Singleton
conscience_engine = ConscienceEngine()
