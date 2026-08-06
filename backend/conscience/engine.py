"""ConscienceEngine — Mika's waking brain.

Sits above modules. Observes all events, interprets them, maintains
memory, and decides when to speak or act. Tightly coupled to memory
with full R/W access.

Lifecycle (managed by ASGI lifespan):
  1. initialize()   — start decision loop
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
from conscience.scoring import compute_decision_score
from conscience.types import DecisionContext, InterpretedSignal
from drives.engine import drive_engine
from emotion.engine import emotion_engine
from modules.types import ModuleEvent, ModuleNotification
from utils.degradation import degradations

logger = logging.getLogger(__name__)


class ConscienceEngine:
    """Singleton. Mika's waking consciousness.

    Short-term buffer: recent Observations (in DB, queried on sliding window).
    Long-term memory: R/W via MemoryBridge.
    """

    def __init__(self):
        self.interpreter = SignalInterpreter()
        self.memory = MemoryBridge()

        # State
        self._decision_task: asyncio.Task | None = None
        self._decision_lock = asyncio.Lock()
        # Detached high-pertinence decision cycles, held so they aren't GC'd.
        self._fastpath_tasks: set[asyncio.Task] = set()
        self._last_activity: float = time.time()
        self._last_action_time: float = 0.0
        self._greeted_periods: set[str] = set()
        self._greeted_date: object = None  # date of last greeting reset
        # Tentative greeting state from the last scoring pass, committed by
        # _commit_greeting() only when the decision is "act".
        self._pending_greeted: tuple[set[str], object] | None = None
        self._initialized = False
        self._consecutive_waits: int = 0
        # Horodatages monotones des balayages d'entretien etrangles (voir
        # _CLEANUP_INTERVAL_S). En RAM : perdre la cadence au redemarrage ne
        # coute qu'un passage supplementaire.
        self._last_cleanup: float = 0.0
        self._last_stale_sweep: float = 0.0

        # Config (loaded from settings on initialize)
        self._decision_interval: int = 30
        self._cooldown_seconds: int = 300
        self._threshold: float = 0.5

    # ── Lifecycle ─────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self._initialized:
            return

        from configs.service import config_service
        self._decision_interval = config_service.get("conscience.decision_interval")
        self._cooldown_seconds = config_service.get("conscience.cooldown_seconds")
        self._threshold = config_service.get("conscience.act_threshold")

        # Hot-reload: update live parameters when the user edits them in
        # the dashboard. Decision interval requires a loop restart so we
        # flag it; threshold + cooldown take effect on the next tick.
        config_service.on_change("conscience.act_threshold",
                                 lambda k, v: setattr(self, "_threshold", v))
        config_service.on_change("conscience.cooldown_seconds",
                                 lambda k, v: setattr(self, "_cooldown_seconds", v))

        # Restore cooldown from last "act" decision log (survives restarts)
        await self._restore_cooldown()

        # Subscribe to the event bus rather than being installed into it by
        # ModuleManager.set_conscience(). The conscience is the thing that
        # wants to see every signal; the emitter should not have to know that.
        #
        # AWAIT at observer priority reproduces the previous ordering exactly:
        # she interprets and files her Observation before any module reacts,
        # and downstream code reads that row. The expensive part — deciding
        # whether to *act* on it — is already spawned inside observe().
        from pipeline.signals import TURN_COMPLETED
        from utils.eventbus import PRIORITY_OBSERVER, DeliveryMode, event_bus
        event_bus.subscribe(
            self.observe,
            name="conscience",
            mode=DeliveryMode.AWAIT,
            priority=PRIORITY_OBSERVER,
        )

        # Second, separate subscription: the post-action audit. It was an
        # inline call at the tail of process_message, so the pipeline had to
        # know that a rumination is what follows an emotionally marked reply.
        #
        # Deliberately not folded into observe(): a turn Mika just spoke is
        # not a signal about the world, and interpreting her own reply as an
        # external stimulus would cost an LLM call and file an Observation
        # every single turn. The internal `_turn.*` namespace is invisible
        # to the wildcard `observe` subscription for exactly that reason.
        event_bus.subscribe(
            self._audit_completed_turn,
            name="conscience.audit",
            pattern=TURN_COMPLETED,
            # Detached: it writes a Rumination and has nothing the turn is
            # waiting on. Awaiting it added DB work to every reply.
            mode=DeliveryMode.SPAWN,
        )

        self._decision_task = asyncio.create_task(self._decision_loop())
        self._initialized = True

        logger.info(
            "Conscience initialized (interval=%ds, cooldown=%ds, threshold=%.1f)",
            self._decision_interval,
            self._cooldown_seconds,
            self._threshold,
        )

    async def _restore_cooldown(self) -> None:
        """Restore _last_action_time from the most recent 'act' ConscienceLog.

        This ensures the cooldown survives process restarts — without it,
        the conscience would act immediately after every restart.
        """
        from conscience.models import ConscienceLog

        try:
            last_act = await sync_to_async(
                lambda: ConscienceLog.objects.filter(decision="act")
                .order_by("-created_at")
                .first()
            )()
            if last_act:
                self._last_action_time = last_act.created_at.timestamp()
                elapsed = time.time() - self._last_action_time
                if elapsed < self._cooldown_seconds:
                    logger.info(
                        "Conscience cooldown restored: %ds remaining",
                        int(self._cooldown_seconds - elapsed),
                    )
                else:
                    logger.debug("Last conscience action was %ds ago (cooldown expired)", int(elapsed))
        except Exception as exc:
            degradations.record("conscience: could not restore cooldown", exc)

    async def shutdown(self) -> None:
        # Detach before cancelling the loop: an event arriving mid-shutdown
        # would otherwise be interpreted by an engine that is on its way out.
        from utils.eventbus import event_bus
        event_bus.unsubscribe("conscience")
        event_bus.unsubscribe("conscience.audit")

        if self._decision_task:
            self._decision_task.cancel()
            try:
                await self._decision_task
            except asyncio.CancelledError:
                pass

        self._initialized = False
        logger.info("Conscience shut down")

    # ── 1. OBSERVE ────────────────────────────────────────────────

    async def observe(self, event: ModuleEvent) -> None:
        """Receive a module event, interpret it, store it.

        Called by the event bus (ModuleManager.emit_event callback).
        If the signal is important enough, immediately creates a souvenir.
        Emotional reactions from interpreted signals feed into the EmotionEngine
        so the VTuber actually *feels* what she observes.
        """
        signal = await self.interpreter.interpret(event)
        observation = await self._store_observation(event, signal)

        # Feed emotional reaction into the EmotionEngine
        if signal.emotional_reaction and signal.emotional_intensity > 0.1:
            self._feed_emotion(signal)

        # Immediate memory action for high-pertinence signals
        if signal.should_remember and signal.pertinence > 0.5:
            souvenir = await self.memory.create_souvenir_from_signal(signal)
            if souvenir and observation:
                observation.souvenir = souvenir
                await sync_to_async(observation.save)(update_fields=["souvenir"])

        # Track activity for idle detection
        if event.event_type in ("chat.message", "telegram.message"):
            self._last_activity = time.time()
            # L'assouvissement de SOCIAL/CURIOSITY par un message n'est plus
            # décidé ici : c'est une politique des pulsions, déclarée dans
            # drives/apps.py sur `_turn.completed`, donc valable pour tout
            # canal d'entrée et non pour les seuls noms d'événements listés
            # ci-dessus.
        else:
            # External signal (email, RSS, schedule) — feeds curiosity
            # proportionally to pertinence.
            drive_engine.on_observation(signal.pertinence)

        logger.debug(
            "Observed: %s/%s → %s (p=%.1f)",
            event.source_module, event.event_type,
            signal.category, signal.pertinence,
        )

        # Fast-path: critical signals trigger an immediate decision cycle.
        # Scheduled, not awaited: observe() is called from inside
        # ModuleManager.emit_event, which the email/RSS pollers await. Running
        # the decision inline blocked the emitting module's loop for the two
        # LLM calls (_act's recipient selection + the full pipeline) that a
        # pertinent signal triggers.
        if signal.pertinence > 0.85:
            logger.info(
                "High-pertinence signal (%.2f), triggering immediate decision",
                signal.pertinence,
            )
            self._spawn_decision()

    @staticmethod
    def _feed_emotion(signal: InterpretedSignal) -> None:
        """Inject an interpreted signal's emotional reaction into the EmotionEngine.

        Uses person_id "conscience_mika" — the VTuber feeling something
        from her own observation, not from a conversation partner.
        """
        from emotion.types import Emotion, EmotionData

        try:
            emotion = Emotion(signal.emotional_reaction)
        except ValueError:
            logger.debug(
                "Unknown emotion from signal: %s", signal.emotional_reaction
            )
            return

        data = EmotionData(emotion=emotion, intensity=signal.emotional_intensity)
        emotion_engine.process_emotion(data, "conscience_mika")
        logger.debug(
            "Fed emotion %s:%.2f from observation into EmotionEngine",
            emotion.value, signal.emotional_intensity,
        )

    async def _store_observation(self, event, signal):
        """Persist an observation to DB."""
        from conscience.models import Observation

        try:
            # Les themes produits par l'interpretation n'ont pas de champ
            # dedie : ils sont fusionnes dans raw_data, seul endroit ou
            # _memory_maintenance et _promote_stale_to_ruminations vont les
            # relire. Aucun emetteur d'evenement ne pose de cle "themes",
            # donc sans cette fusion les deux lectures renvoient toujours [].
            raw_data = dict(event.data or {})
            raw_data["themes"] = signal.themes

            return await sync_to_async(Observation.objects.create)(
                source=event.source_module,
                event_type=event.event_type,
                raw_data=raw_data,
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
        """Periodic evaluation: decide and act."""
        while True:
            try:
                await asyncio.sleep(self._decision_interval)

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
        Note: locked() check is safe in asyncio (single-threaded event loop,
        no preemption between check and acquire within the same coroutine step).
        """
        if self._decision_lock.locked():
            logger.debug("Decision already in progress, skipping")
            return

        async with self._decision_lock:
            await self._decide_inner()

    def _spawn_decision(self) -> None:
        """Run a decision cycle detached from the caller's await chain.

        A strong reference is kept until completion: a bare create_task can be
        garbage-collected mid-flight, and exceptions in a dropped task vanish
        silently.
        """
        task = asyncio.create_task(self._decide())
        self._fastpath_tasks.add(task)
        task.add_done_callback(self._fastpath_tasks.discard)
        task.add_done_callback(self._log_fastpath_result)

    @staticmethod
    def _log_fastpath_result(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Fast-path decision failed: %r", exc, exc_info=exc)

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

        # Update consecutive wait counter. An "act" only clears the
        # accumulated pressure once it has actually been delivered — see below.
        if decision == "wait":
            self._consecutive_waits += 1
        elif decision == "skip":
            self._consecutive_waits = 0

        if decision == "act":
            spoke = await self._act(ctx, reason)
            if spoke:
                # The greeting is spent only now that Mika really speaks.
                self._commit_greeting()
                self._consecutive_waits = 0
            else:
                # L'appel IA a echoue : rien n'a ete dit, donc rien n'est
                # committe. Journalise "failed" plutot que "act", sans quoi
                # un acte jamais delivre gonfle acts_today et, ne pouvant
                # recevoir aucune reponse, compte comme un acte ignore — trois
                # pannes suffisaient alors a brider la Conscience (scoring.py)
                # pour le reste de la journee.
                decision = "failed"
        elif decision == "skip" or decision == "wait":
            # Mark old pending observations as skipped (older than 30 min
            # won't be picked up again anyway)
            await self._mark_stale_observations()

        # Log the decision — written after the act, whose outcome is part of
        # what the cycle decided (and what _introspect / _restore_cooldown read).
        await self._log_decision(ctx, decision, reason, score, memory_actions)

        # Periodic cleanup of old observations
        await self._cleanup_old_observations()

    async def _introspect(self) -> tuple[int, int]:
        """Query recent ConscienceLogs for self-awareness.

        Returns:
            (acts_today, consecutive_ignored_acts)
        """
        from conscience.models import ConscienceLog, Observation
        from django.utils import timezone as tz
        from datetime import timedelta

        today_start = tz.now().replace(hour=0, minute=0, second=0, microsecond=0)

        def _query() -> tuple[int, int]:
            # One round-trip for the whole introspection. This runs on every
            # decision cycle (30s by default, forever, whether or not anyone
            # is talking), and the old shape was 2 queries plus one
            # `.exists()` per recent act — each its own sync_to_async thread
            # hop — to answer a question about at most 5 rows.
            acts_today = ConscienceLog.objects.filter(
                decision="act", created_at__gte=today_start,
            ).count()

            recent_act_times = list(
                ConscienceLog.objects.filter(decision="act")
                .order_by("-created_at")
                .values_list("created_at", flat=True)[:5]
            )
            if not recent_act_times:
                return acts_today, 0

            # Fetch every user reply since the oldest act in the window once,
            # then answer "was this act followed by a reply within 10 min?"
            # in Python. The window is bounded by definition — 5 acts.
            oldest = recent_act_times[-1]
            newest_window_end = recent_act_times[0] + timedelta(minutes=10)
            replies = list(
                Observation.objects.filter(
                    event_type__in=("chat.message", "telegram.message"),
                    created_at__gt=oldest,
                    created_at__lte=newest_window_end,
                ).values_list("created_at", flat=True)
            )

            consecutive_ignored = 0
            for act_time in recent_act_times:
                deadline = act_time + timedelta(minutes=10)
                if any(act_time < reply <= deadline for reply in replies):
                    break
                consecutive_ignored += 1
            return acts_today, consecutive_ignored

        try:
            return await sync_to_async(_query)()
        except Exception as exc:
            degradations.record("conscience: introspection", exc)
            return 0, 0

    async def _build_context(self) -> DecisionContext:
        """Gather all context needed for a decision."""
        from conscience.models import Observation


        now = time.time()

        # Pending observations (not acted upon, last 30 minutes)
        from django.utils import timezone as tz
        from datetime import timedelta

        cutoff = tz.now() - timedelta(minutes=30)
        pending = await sync_to_async(
            lambda: list(
                Observation.objects.filter(
                    status="pending",
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

        # Poll due scheduled actions
        scheduled = await self._poll_scheduled_actions()

        # Introspection: query own recent behavior
        acts_today, consecutive_ignored_acts = await self._introspect()

        # Drives: intrinsic motivation pressure
        drive_bonus, drive_summary = drive_engine.conscience_contribution()
        drive_rest_penalty = drive_engine.rest_penalty()

        # Rumination: persistent unresolved thoughts
        rum_pressure, rum_count = await self._rumination_snapshot()

        # Energy: combines circadian phase with REST drive. Tired Mika
        # speaks less spontaneously (see scoring Factor 11).
        energy = drive_engine.energy_level()

        return DecisionContext(
            pending_observations=pending,
            global_mood=glob.emotion.value,
            global_intensity=glob.intensity,
            idle_seconds=idle,
            in_cooldown=in_cooldown,
            max_pertinence=max_p,
            weighted_urgency=min(1.0, weighted),
            scheduled_actions=scheduled,
            consecutive_waits=self._consecutive_waits,
            acts_today=acts_today,
            consecutive_ignored_acts=consecutive_ignored_acts,
            drive_bonus=drive_bonus,
            drive_summary=drive_summary,
            drive_rest_penalty=drive_rest_penalty,
            rumination_pressure=rum_pressure,
            rumination_count=rum_count,
            energy=energy,
        )

    async def _rumination_snapshot(self) -> tuple[float, int]:
        """Aggregate pressure from active (non-resolved) ruminations.

        Returns (total_pressure_clamped_01, count). Fault-tolerant — if
        the Rumination model isn't migrated yet, returns (0.0, 0).
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return 0.0, 0

        try:
            active = await sync_to_async(
                lambda: list(
                    Rumination.objects
                    .filter(status="active")
                    .values_list("intensity", flat=True)[:20]
                )
            )()
        except Exception as exc:
            # Table may not exist yet (migration pending) — silencieux, mais
            # compté : sans ça le Facteur 10 du scoring tombe a 0.0 et une
            # panne totale ressemble a "elle n'a rien qui lui trotte en tete".
            degradations.record("conscience: rumination pressure snapshot", exc)
            return 0.0, 0

        if not active:
            return 0.0, 0
        total = sum(active)
        return min(1.0, total), len(active)

    async def _resolve_ruminations_after_act(self) -> None:
        """When Mika speaks up, every active rumination loses half its charge.

        The relief is *unconditional*, not matched against what she actually
        said: the model here is "she got it off her chest", and the act of
        breaking her own silence is what does it, whatever the subject.
        Anything falling below 0.1 afterwards is marked resolved.

        The docstring used to promise theme-matching against the response
        text, and the signature carried a ``response_text`` nothing ever
        read — describing a behaviour the code has never had.
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return

        try:
            active = await sync_to_async(
                lambda: list(Rumination.objects.filter(status="active")[:20])
            )()
        except Exception as exc:
            degradations.record("conscience: ruminations to relieve", exc)
            return

        for r in active:
            r.intensity *= 0.5
            if r.intensity < 0.1:
                r.status = "resolved"
            try:
                await sync_to_async(r.save)(
                    update_fields=["intensity", "status"]
                )
            except Exception as exc:
                degradations.record("conscience: rumination relief save", exc)

    # Emotional drift map for aging ruminations. A thought doesn't stay
    # the same shape forever — frustration that lingers becomes anxiety,
    # an unresolved excitement fades into melancholy, etc. Keyed by the
    # initial emotion, value is the label the rumination drifts toward
    # once it's been "turning over" long enough (cycle count threshold).
    _RUMINATION_DRIFT: dict[str, str] = {
        "frustrated": "anxious",
        "angry": "melancholic",
        "excited": "nostalgic",
        "happy": "nostalgic",
        "grateful": "nostalgic",
        "sad": "melancholic",
        "scared": "anxious",
        "jealous": "sad",
        "hopeful": "anxious",
        "curious": "confused",
        "surprised": "thinking",
        "embarrassed": "anxious",
        "lonely": "melancholic",
    }
    # Cycles (~30s each by default) before emotional drift kicks in.
    _RUMINATION_DRIFT_THRESHOLD: int = 4

    async def _decay_ruminations(self) -> None:
        """Every cycle: active ruminations lose ~5% intensity and may
        bleed their emotional charge into the global mood.

        Models the fact that unresolved thoughts color humor over time:
        a lingering frustration keeps you a bit frustrated. Bleed is
        proportional to intensity so only strong ruminations tint mood.

        Emotional drift: ruminations that have been "turning over" for
        several cycles shift their emotional tint toward a drift target
        (frustration → anxious, excitement → nostalgic, etc.). Thoughts
        mutate; humans don't stay angry at the same thing indefinitely,
        they start *worrying* about it instead.
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return

        try:
            active = await sync_to_async(
                lambda: list(Rumination.objects.filter(status="active")[:30])
            )()
        except Exception as exc:
            degradations.record("conscience: ruminations to decay", exc)
            return

        if not active:
            return

        # Import inside to avoid circulars
        from django.utils import timezone as tz
        from emotion.types import Emotion, EmotionData

        now_tz = tz.now()
        for r in active:
            # 5% intensity decay per cycle
            r.intensity *= 0.95
            update_fields = ["intensity", "status"]

            # Emotional drift: after several cycles, shift the label
            # toward a softer / more introspective neighbor.
            if r.emotion:
                age_cycles = int(
                    (now_tz - r.updated_at).total_seconds()
                    / max(1, self._decision_interval)
                )
                drift_target = self._RUMINATION_DRIFT.get(r.emotion)
                if (
                    drift_target
                    and age_cycles >= self._RUMINATION_DRIFT_THRESHOLD
                    and drift_target != r.emotion
                ):
                    logger.debug(
                        "Rumination #%s drift: %s -> %s",
                        r.pk, r.emotion, drift_target,
                    )
                    r.emotion = drift_target
                    update_fields.append("emotion")

            # Emotional bleed: if rumination has an associated emotion,
            # re-inject a small fraction into the global mood.
            if r.emotion and r.intensity > 0.3:
                try:
                    emo = Emotion(r.emotion)
                    data = EmotionData(emotion=emo, intensity=r.intensity * 0.15)
                    emotion_engine.process_emotion(data, "conscience_mika")
                except ValueError:
                    # Unknown emotion label on a stale rumination — skip.
                    pass
                except Exception as exc:
                    degradations.record("conscience: rumination emotional bleed failed for #", exc)

            if r.intensity < 0.1:
                r.status = "faded"

            try:
                await sync_to_async(r.save)(update_fields=update_fields)
            except Exception as exc:
                degradations.record("conscience: rumination decay save", exc)

    async def _promote_stale_to_ruminations(self) -> None:
        """Convert recent skipped/stale pertinent observations into ruminations.

        Called from _mark_stale_observations when observations age out.
        An observation with pertinence >= 0.5 that was never acted upon
        becomes a Rumination — Mika keeps thinking about it.
        """
        try:
            from conscience.models import Observation, Rumination
        except ImportError:
            return

        from django.utils import timezone as tz
        from datetime import timedelta

        cutoff = tz.now() - timedelta(minutes=30)
        window_start = tz.now() - timedelta(hours=2)

        try:
            pertinent_stale = await sync_to_async(
                lambda: list(
                    Observation.objects.filter(
                        status="skipped",
                        pertinence__gte=0.5,
                        created_at__gte=window_start,
                        created_at__lt=cutoff,
                    ).exclude(
                        id__in=Rumination.objects.filter(
                            observation__isnull=False
                        ).values_list("observation_id", flat=True)
                    )[:5]
                )
            )()
        except Exception as exc:
            degradations.record("conscience: stale observations to promote", exc)
            return

        for obs in pertinent_stale:
            try:
                await sync_to_async(Rumination.objects.create)(
                    summary=obs.summary,
                    themes=obs.raw_data.get("themes", []),
                    intensity=min(1.0, obs.pertinence),
                    emotion=obs.emotional_reaction or "",
                    observation=obs,
                    status="active",
                )
                logger.debug(
                    "Promoted observation %d to rumination (p=%.2f)",
                    obs.id, obs.pertinence,
                )
            except Exception as exc:
                degradations.record("conscience: rumination creation", exc)

    async def _poll_scheduled_actions(self) -> list:
        """Query scheduled actions that are due (scheduled_at <= now)."""
        from conscience.models import ScheduledAction
        from django.utils import timezone as tz

        try:
            return await sync_to_async(
                lambda: list(
                    ScheduledAction.objects.filter(
                        status="pending",
                        scheduled_at__lte=tz.now(),
                    ).order_by("scheduled_at")[:10]
                )
            )()
        except Exception as exc:
            degradations.record("conscience: poll scheduled actions", exc)
            return []

    async def _get_upcoming_actions(self, limit: int = 5) -> list[tuple]:
        """Get future pending actions (not yet due). Returns [(action, minutes_until), ...]."""
        from conscience.models import ScheduledAction
        from django.utils import timezone as tz

        now = tz.now()
        try:
            actions = await sync_to_async(
                lambda: list(
                    ScheduledAction.objects.filter(
                        status="pending",
                        scheduled_at__gt=now,
                    ).order_by("scheduled_at")[:limit]
                )
            )()
            return [(a, int((a.scheduled_at - now).total_seconds() / 60)) for a in actions]
        except Exception as exc:
            degradations.record("conscience: upcoming scheduled actions", exc)
            return []

    def _compute_score(self, ctx: DecisionContext) -> tuple[float, str]:
        """Unified scoring. Delegates to conscience.scoring for testability.

        The greeting state computed here is only *tentative*: scoring marks a
        period as greeted, but the greeting is worth 0.35 against a 0.5
        threshold, so committing it right away would burn the day's greeting
        on a cycle that decided to stay silent. ``_commit_greeting()`` is
        called by the caller once the decision is actually "act".
        """
        score, reason, periods, date = compute_decision_score(
            ctx, self._greeted_periods, self._greeted_date,
        )
        self._pending_greeted = (periods, date)
        return score, reason

    def _commit_greeting(self) -> None:
        """Persist the tentative greeting state produced by the last scoring."""
        pending = getattr(self, "_pending_greeted", None)
        if pending is not None:
            self._greeted_periods, self._greeted_date = pending
            self._pending_greeted = None

    # ── 3. MEMORY MAINTENANCE ─────────────────────────────────────

    # Marque posee dans raw_data une fois l'observation passee par la
    # maintenance. Observation n'a pas de champ dedie, et raw_data porte
    # deja les themes de l'interpretation (voir _store_observation) : la
    # meme convention evite une migration pour un drapeau interne.
    _MAINTENANCE_FLAG = "maintenance_done"

    async def _memory_maintenance(self, ctx: DecisionContext) -> list[str]:
        """Modify memory based on accumulated observations.

        Runs every decision cycle — the Conscience can reshape memory
        even without speaking.

        Une observation n'est maintenue **qu'une fois**. Elle reste
        `pending` jusqu'a un acte ou sa peremption (30 min), et
        `_build_context` la reselectionne a chaque cycle : sans cette
        marque, un signal pertinent repayait a chaque tour une recherche
        vectorielle plus jusqu'a cinq appels IA de validation — soit une
        soixantaine de fois a l'intervalle par defaut, en serie et
        `_decision_lock` tenu, ce qui court-circuitait aussi bien les
        ticks periodiques que le fast-path haute pertinence. Le boost
        d'importance, lui, se cumulait a chaque passage.
        """
        actions = []

        for obs in ctx.pending_observations:
            if obs.raw_data.get(self._MAINTENANCE_FLAG):
                continue

            # Marquee avant le travail, pas apres : la marque dit "cette
            # observation est passee par la maintenance", pas "la
            # maintenance a reussi". La poser apres laisserait une panne
            # transitoire rejouer exactement la boucle qu'on supprime ici.
            await self._mark_maintained(obs)

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

    async def _mark_maintained(self, obs) -> None:
        """Poser durablement la marque de maintenance sur une observation.

        En base, pas en RAM : les observations sont relues a chaque cycle
        et un redemarrage relancerait sinon la meme maintenance. Si
        l'ecriture echoue, la marque n'existe pas et l'observation
        repassera au cycle suivant — degradation comptee, pas de blocage.
        """
        try:
            obs.raw_data[self._MAINTENANCE_FLAG] = True
            await sync_to_async(obs.save)(update_fields=["raw_data"])
        except Exception as exc:
            degradations.record("conscience: mark observation maintained", exc)

    # Meme decalage d'echelle que la purge, en plus court : le seuil est a 30
    # minutes et le seul lecteur du statut "skipped" est la promotion en
    # rumination, qui lit une fenetre de 2h. Une granularite de 5 minutes ne
    # change donc rien d'observable — le scoring, lui, ne voit jamais ces
    # lignes, `_build_context` bornant sa selection aux 30 dernieres minutes.
    _STALE_SWEEP_INTERVAL_S = 300
    _STALE_SWEEP_BATCH = 1000

    async def _mark_stale_observations(self) -> None:
        """Mark pending observations older than 30 min as skipped.

        Pertinent stale observations are promoted to Ruminations — Mika
        keeps thinking about them even after the short-term buffer empties.

        L'UPDATE est etrangle a `_STALE_SWEEP_INTERVAL_S` et borne a
        `_STALE_SWEEP_BATCH` lignes ; la promotion et la decroissance des
        ruminations, elles, restent a chaque cycle (5% par cycle est leur
        definition).
        """
        from conscience.models import Observation
        from django.utils import timezone as tz
        from datetime import timedelta

        now = time.monotonic()
        if (not self._last_stale_sweep
                or (now - self._last_stale_sweep) >= self._STALE_SWEEP_INTERVAL_S):
            self._last_stale_sweep = now
            cutoff = tz.now() - timedelta(minutes=30)

            def _perimer() -> int:
                ids = list(
                    Observation.objects.filter(
                        status="pending",
                        created_at__lt=cutoff,
                    ).values_list("pk", flat=True)[:self._STALE_SWEEP_BATCH]
                )
                if not ids:
                    return 0
                return Observation.objects.filter(pk__in=ids).update(
                    status="skipped")

            try:
                count = await sync_to_async(_perimer)()
                if count:
                    logger.debug("Marked %d stale observations as skipped", count)
                if count >= self._STALE_SWEEP_BATCH:
                    self._last_stale_sweep = 0.0
            except Exception as exc:
                degradations.record("conscience: mark stale observations", exc)

        # Promote pertinent skipped observations to ruminations.
        await self._promote_stale_to_ruminations()
        # Decay existing ruminations over each cycle.
        await self._decay_ruminations()

    # Cadence et taille de lot de la purge. La donnee visee a 48h, le cycle de
    # decision tourne toutes les 30s : un passage par heure suffit, sur la
    # forme deja retenue par `_apply_decay` du consolidateur. Le lot borne la
    # transaction d'ecriture — `Rumination.observation` est une FK SET_NULL,
    # donc chaque suppression traine ses UPDATE, et sur SQLite un ecrivain
    # bloque tous les lecteurs le temps de la transaction.
    _CLEANUP_INTERVAL_S = 3600
    _CLEANUP_BATCH = 1000

    async def _cleanup_old_observations(self) -> None:
        """Delete observations older than 48h that are no longer pending.

        Etranglee a `_CLEANUP_INTERVAL_S` et bornee a `_CLEANUP_BATCH` lignes
        par passage. Rien n'est perdu : ce qui deborde du lot reste eligible,
        et un lot plein reprogramme le passage suivant au cycle d'apres plutot
        que dans une heure — sans quoi un pic (premier polling RSS, module
        forge bavard) mettrait des heures a se resorber.
        """
        from conscience.models import Observation
        from django.utils import timezone as tz
        from datetime import timedelta

        now = time.monotonic()
        if self._last_cleanup and (now - self._last_cleanup) < self._CLEANUP_INTERVAL_S:
            return
        self._last_cleanup = now

        cutoff = tz.now() - timedelta(hours=48)
        # `status__in` plutot que `exclude(status="pending")` : l'index
        # ["status", "-created_at"] a sa colonne de tete filtree par `!=`
        # dans la seconde forme, donc inexploitable — c'etait un balayage
        # complet de la table a chaque passage. La liste est derivee des
        # choix du modele, pour ne pas oublier un statut ajoute plus tard.
        closed = [s for s in Observation.Status.values
                  if s != Observation.Status.PENDING]

        def _purger() -> int:
            # Suppression par liste de pk (motif de memory/retention.py) :
            # `.delete()` sur un queryset tranche n'est pas portable, et cela
            # garde l'instruction bornee.
            ids = list(
                Observation.objects.filter(
                    status__in=closed,
                    created_at__lt=cutoff,
                ).values_list("pk", flat=True)[:self._CLEANUP_BATCH]
            )
            if not ids:
                return 0
            # .delete() returns (total, {model: count}) tuple
            return Observation.objects.filter(pk__in=ids).delete()[0]

        try:
            count = await sync_to_async(_purger)()
        except Exception as exc:
            degradations.record("conscience: observation cleanup", exc)
            return

        if count:
            logger.info("Cleaned up %d old observations", count)
        if count >= self._CLEANUP_BATCH:
            self._last_cleanup = 0.0

    # ── 4. ACT ────────────────────────────────────────────────────

    async def _act(self, ctx: DecisionContext, reason: str) -> bool:
        """Generate a spontaneous response using accumulated context.

        Builds an INTERNAL_TRIGGER Perception and hands it to the pipeline
        processor directly (context is pre-assembled with relevant-module
        tools, so we bypass the router's dispatch logic here — the intent
        is already "Mika acts, no event to loop back").

        Returns True only if something was actually said: the caller commits
        the day's greeting and the decision log from that answer."""
        from modules.manager import module_manager
        from pipeline.context import ConversationContext, gather_context
        from pipeline.perception import Perception
        from pipeline.processor import process_message

        self._last_action_time = time.time()

        # Recall relevant memories
        queries = [o.summary for o in ctx.pending_observations if o.pertinence > 0.3]
        memory_context = await self.memory.recall_for_context(queries)

        # Determine which modules are relevant based on observation sources
        relevant_modules = self._pick_relevant_modules(ctx)

        # Build prompt with capabilities summary
        capabilities_summary = module_manager.collect_capabilities_summary()
        prompt = await self._build_action_prompt(ctx, reason, capabilities_summary)

        # Decide WHOM to address (pass 1). If a concerned, reachable person is
        # chosen, the response is composed with THEIR context and delivered to
        # them; otherwise it stays Mika's internal/broadcast voice.
        target = await self._select_recipient(ctx)
        person_id = target or "conscience_mika"

        try:
            # Build filtered context with only relevant modules' tools.
            # La memoire n'est demandee ici que si le rappel sur les
            # observations n'a rien donne : sinon `memory_context` ecrase le
            # champ juste en dessous, et l'embedding + la requete ChromaDB
            # faits sur le prompt d'action etaient payes pour rien.
            base_context = await gather_context(
                prompt, person_id,
                include_tools=False,
                include_memory=not memory_context,
            )

            # Override with relevant-only tools
            if relevant_modules:
                tools = module_manager.get_tools_for_modules(relevant_modules)
            else:
                tools = []
            tool_names = [t.name for t in tools]

            context = ConversationContext(
                memory_context=memory_context if memory_context else base_context.memory_context,
                emotion_context=base_context.emotion_context,
                module_context=base_context.module_context,
                history=base_context.history,
                tools=tools,
                tool_names=tool_names,
                self_concept=base_context.self_concept,
                person_context=base_context.person_context,
                circadian_context=base_context.circadian_context,
                fatigue_fog=base_context.fatigue_fog,
                rumination_context=base_context.rumination_context,
                user_mood_hint=base_context.user_mood_hint,
                dream_context=base_context.dream_context,
                project_context=base_context.project_context,
                project_suppresses_emotion=base_context.project_suppresses_emotion,
                project_id=base_context.project_id,
            )

            perception = Perception.from_internal_trigger(
                prompt,
                source="conscience",
                person_id=person_id,
                metadata={"reason": reason, "relevant_modules": relevant_modules},
            )

            output = await process_message(
                perception,
                context=context,
                emit_event=False,
            )

            if output.ai_failed:
                # The AI call failed (unconfigured role, quota, timeout...):
                # nothing was actually said. Leave observations pending and
                # scheduled actions unexecuted so they retry after cooldown,
                # and don't satisfy drives with a phantom act.
                logger.warning(
                    "Conscience act aborted [%s]: AI call failed — will retry "
                    "after cooldown", reason,
                )
                return False

            # Mark observations as acted
            for obs in ctx.pending_observations:
                obs.status = "acted"
                obs.action_response = output.text[:200]
                await sync_to_async(obs.save)(
                    update_fields=["status", "action_response"]
                )

            # Mark scheduled actions as executed
            if ctx.scheduled_actions:
                from django.utils import timezone as tz
                now_tz = tz.now()
                for action in ctx.scheduled_actions:
                    action.status = "executed"
                    action.executed_at = now_tz
                    await sync_to_async(action.save)(
                        update_fields=["status", "executed_at"]
                    )
                logger.info(
                    "Executed %d scheduled action(s)", len(ctx.scheduled_actions)
                )

            if output.tool_calls:
                logger.info(
                    "Conscience tool calls: %s",
                    [str(tc)[:120] for tc in output.tool_calls],
                )

            # Satisfy drives now that Mika has spoken.
            drive_engine.on_act(
                had_tools=bool(output.tool_calls),
                word_count=len(output.text.split()),
            )

            # Speaking at all fades every active rumination by half.
            await self._resolve_ruminations_after_act()

            logger.info(
                "Conscience acted [%s] (modules=%s, tools=%d): %s",
                reason, relevant_modules, len(output.tool_calls),
                output.text[:80],
            )
            return True

        except Exception:
            logger.exception("Conscience act failed")
            # Mark observations as failed so they don't retry indefinitely
            for obs in ctx.pending_observations:
                try:
                    obs.status = "failed"
                    await sync_to_async(obs.save)(update_fields=["status"])
                except Exception:
                    logger.warning(
                        "Could not mark observation #%s as failed",
                        getattr(obs, "pk", "?"), exc_info=True,
                    )
            return False

    # Budget de la passe 1, alignee sur les 15 s de l'interpreteur : meme role
    # (SIGNAL_INTERPRETATION), meme travail — classer un signal court — et le
    # meme cadre, une boucle sans superviseur. La borne routee
    # (`ai.call_timeout_seconds`, 120 s) est celle d'un tour de conversation :
    # la depenser ici immobilise `_decision_lock` pour quatre cycles avant
    # meme que `_act` n'ait commence a composer sa reponse. Ne rien dire a
    # personne est un resultat valide, donc l'expiration se replie sur le
    # broadcast interne plutot que d'annuler l'acte.
    _RECIPIENT_TIMEOUT_S = 15

    async def _select_recipient(self, ctx: DecisionContext) -> str | None:
        """Pass 1 of proactive speech: pick whom to address, or no one.

        Routing is memory-grounded (``who_is_concerned``) then confirmed by Mika
        via a ``[TO:person_id]`` tag. The candidate prompt is privacy-safe — only
        names + channels, never another person's private memory content.
        Returns a reachable ``person_id`` or None (keep it internal/broadcast).
        """
        from conscience.recipients import parse_to_tag

        signal = " ".join(
            o.summary for o in ctx.pending_observations if o.pertinence > 0.3
        ).strip()
        if not signal:
            return None

        candidates = await self.memory.who_is_concerned(signal, n=5)
        if not candidates:
            return None

        lines: list[str] = []
        allowed: list[str] = []
        for c in candidates[:5]:
            handles = c.get("handles") or []
            if not handles:
                continue
            pid = handles[0]["person_id"]
            channel = handles[0]["channel"]
            allowed.append(pid)
            lines.append(f"  [{pid}] {c['name']} ({channel})")

        if not allowed:
            return None

        prompt = (
            "Un evenement te concerne. Voici les personnes joignables qu'il "
            "pourrait interesser :\n"
            + "\n".join(lines)
            + "\n\nVeux-tu en parler a quelqu'un ? Reponds UNIQUEMENT par "
            "[TO:person_id] avec un id de la liste, ou [TO:none] si tu preferes "
            "ne rien dire a personne pour l'instant."
        )

        try:
            from ai.client import ai_client
            from ai.router import AIRole

            raw = await asyncio.wait_for(
                ai_client.complete(
                    system_prompt="Tu choisis a qui t'adresser. Reponds uniquement avec un tag [TO:...].",
                    user_prompt=prompt,
                    role=AIRole.SIGNAL_INTERPRETATION,
                ),
                timeout=self._RECIPIENT_TIMEOUT_S,
            )
        except asyncio.TimeoutError as exc:
            degradations.record("conscience: choix du destinataire expire", exc)
            logger.warning(
                "Recipient selection timed out after %ds; staying internal",
                self._RECIPIENT_TIMEOUT_S,
            )
            return None
        except Exception as exc:
            degradations.record("conscience: choix du destinataire", exc)
            logger.exception("Recipient selection failed; staying internal")
            return None

        target = parse_to_tag(raw, allowed)
        logger.info(
            "Conscience recipient selection: target=%s (candidates=%s)",
            target, allowed,
        )
        return target

    def _pick_relevant_modules(self, ctx: DecisionContext) -> list[str]:
        """Determine which modules are relevant based on pending observations."""
        sources = {obs.source for obs in ctx.pending_observations}

        # Always include modules whose events triggered this decision
        relevant = list(sources)

        # Add wake if we might want to self-schedule or have scheduled actions.
        # ``conscience_tools`` va avec : programmer, lister ou annuler une
        # action differee se fait par ses outils, pas par ceux du wake.
        if (
            ctx.scheduled_actions
            or any(obs.pertinence > 0.6 for obs in ctx.pending_observations)
        ):
            for name in ("wake", "conscience_tools"):
                if name not in relevant:
                    relevant.append(name)

        return relevant

    async def _build_action_prompt(
        self,
        ctx: DecisionContext,
        reason: str,
        capabilities_summary: str = "",
    ) -> str:
        """Construire le prompt de ce qui est propre a CETTE decision.

        Volontairement muet sur l'humeur, les pulsions, les ruminations et le
        contexte memoire : le `ConversationContext` monte par `_act()` porte
        deja les quatre dans le prompt systeme
        (`--- TON ETAT EMOTIONNEL ACTUEL ---` contient l'humeur globale suivie
        de `drive_engine.get_context()`, `--- CE QUI TE TROTTE DANS LA TETE ---`
        les memes trois ruminations, et la memoire est ajoutee brute en fin de
        prompt). Les redire ici envoyait plusieurs centaines de tokens en
        double a chaque acte — le chemin le plus cher du moteur, repaye a
        chaque tour de la boucle d'outils.

        Ce qui reste est ce que rien d'autre ne sait : les actions programmees
        dues, les observations, la raison du declenchement, l'auto-evaluation
        et les actions futures.
        """
        import json as _json

        parts = []

        # Scheduled actions due (highest priority — these are self-assigned tasks)
        if ctx.scheduled_actions:
            action_lines = []
            for act in ctx.scheduled_actions[:3]:
                action_lines.append(f"- {act.prompt[:200]}")
                if act.context_data:
                    action_lines.append(
                        f"  Contexte: {_json.dumps(act.context_data, ensure_ascii=False)[:200]}"
                    )
            parts.append(
                "Actions que tu avais programmees et qui sont maintenant dues:\n"
                + "\n".join(action_lines)
                + "\nExecute ces actions dans ta reponse."
            )

        # What you've observed
        if ctx.pending_observations:
            obs_lines = []
            for obs in ctx.pending_observations[:5]:
                obs_lines.append(f"- [{obs.source}] {obs.summary} (pertinence: {obs.pertinence:.1f})")
            parts.append(
                "Ce que tu as observe recemment:\n" + "\n".join(obs_lines)
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

        # Self-awareness
        if ctx.acts_today > 0:
            parts.append(f"Tu as deja pris la parole {ctx.acts_today} fois aujourd'hui.")
        if ctx.consecutive_ignored_acts >= 2:
            parts.append(
                f"Tes {ctx.consecutive_ignored_acts} dernieres interventions "
                "n'ont recu aucune reponse. Sois plus discrete ou change d'approche."
            )

        # Available capabilities (what you CAN do)
        if capabilities_summary:
            parts.append(
                "Ce que tu peux faire (utilise les outils si pertinent):\n"
                + capabilities_summary
            )

        # Upcoming scheduled actions (so Claude knows what's already planned)
        upcoming = await self._get_upcoming_actions()
        if upcoming:
            upcoming_lines = [f"- Dans {mins}min: {a.prompt[:80]}" for a, mins in upcoming]
            parts.append(
                "Tu as deja programme ces actions futures:\n"
                + "\n".join(upcoming_lines)
            )

        # Instructions
        parts.append(
            "\nExprime-toi naturellement et spontanement, "
            "en accord avec ce que tu observes et ressens. "
            "Sois breve (1-3 phrases max). "
            "Tu peux utiliser tes outils si la situation le demande."
        )

        return "\n\n".join(parts)

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
        except Exception as exc:
            degradations.record("conscience: log decision", exc)

        if decision != "skip":
            logger.info(
                "Conscience decision: %s (score=%.2f, reason=%s, obs=%d, memory_actions=%d)",
                decision, score, reason,
                len(ctx.pending_observations), len(memory_actions),
            )

    # ── Context for modules ───────────────────────────────────────

    def get_idle_seconds(self) -> float:
        return time.time() - self._last_activity

    # ── Post-action self-audit ────────────────────────────────────

    # Emotions that trigger a post-action micro-rumination. Strong
    # expressions — positive or negative — are the ones that leave a
    # trace: after saying something bold or anxious, a human replays it
    # mentally. Neutral mid-range responses don't need an audit.
    _AUDIT_EMOTIONS: dict[str, tuple[str, str]] = {
        # emotion_name : (rumination_emotion, template)
        "angry":        ("embarrassed", "Tu repenses a ta reponse un peu vive : \"{excerpt}\"."),
        "frustrated":   ("anxious",     "Tu repenses a ta reponse tendue : \"{excerpt}\". Etait-ce trop ?"),
        "proud":        ("proud",       "Tu te rejouis un peu de ta reponse : \"{excerpt}\"."),
        "excited":      ("hopeful",     "Tu es restee sur ton elan apres avoir dit : \"{excerpt}\"."),
        "embarrassed":  ("anxious",     "Tu repenses gene a ce que tu viens de dire : \"{excerpt}\"."),
        "scared":       ("anxious",     "Tu n'es pas sure que ta reaction etait juste : \"{excerpt}\"."),
        "disgusted":    ("embarrassed", "Tu t'es peut-etre emportee : \"{excerpt}\"."),
        "love":         ("grateful",    "Tu gardes en tete la chaleur de l'echange autour de : \"{excerpt}\"."),
        "jealous":      ("melancholic", "Ta reaction te reste un peu sur le coeur : \"{excerpt}\"."),
    }

    async def _audit_completed_turn(self, event) -> None:
        """Bus adapter for ``post_action_audit``.

        Holds the one piece of policy the pipeline used to hold on the
        conscience's behalf: a project in professional mode produces no
        lingering self-doubt about a work email. That is a statement about
        ruminations, so it belongs to the conscience, not to the processor.
        """
        data = event.data
        if data.get("project_suppresses_emotion"):
            return
        await self.post_action_audit(
            response_text=data.get("text", ""),
            emotion_name=data.get("emotion_name", ""),
            intensity=data.get("emotion_intensity", 0.0),
            person_id=data.get("person_id", ""),
        )

    async def post_action_audit(
        self,
        response_text: str,
        emotion_name: str,
        intensity: float,
        person_id: str,
    ) -> None:
        """After Mika speaks, maybe create a micro-rumination capturing
        self-evaluation of what she just said.

        Fires only for emotionally marked responses (in _AUDIT_EMOTIONS)
        with intensity >= 0.55. Creates a low-intensity Rumination that
        will decay over the next few cycles — a brief "did I say that
        right?" beat. Cheap, heuristic, no LLM call.

        Skipped for internal-trigger speech (conscience already acted,
        would cause a feedback loop of self-ruminations).
        """
        if intensity < 0.55:
            return
        if person_id == "conscience_mika":
            return
        template_data = self._AUDIT_EMOTIONS.get(emotion_name)
        if not template_data:
            return

        rumination_emotion, template = template_data
        excerpt = response_text.strip()[:80].replace("\n", " ")
        if not excerpt:
            return
        summary = template.format(excerpt=excerpt)
        # Intensity starts modest — a normal person doesn't obsess, just
        # replays once or twice. Scales with how emotional the reply was.
        rumination_intensity = round(min(0.45, 0.2 + (intensity - 0.55) * 0.5), 3)

        try:
            from conscience.models import Rumination
        except ImportError:
            return

        try:
            await sync_to_async(Rumination.objects.create)(
                summary=summary,
                themes=[],
                intensity=rumination_intensity,
                emotion=rumination_emotion,
                observation=None,
                status="active",
            )
            logger.debug(
                "Post-action audit created rumination (%s, %.2f): %s",
                rumination_emotion, rumination_intensity, excerpt[:40],
            )
        except Exception as exc:
            degradations.record("conscience: post-action audit", exc)


# Singleton
conscience_engine = ConscienceEngine()
