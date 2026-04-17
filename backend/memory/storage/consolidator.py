import asyncio
import logging
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from memory.extraction.extractor import MemoryExtractor
from memory.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    """Background task that periodically processes raw messages into
    structured memories. Like human dreams consolidating short-term
    into long-term memory.

    Every N seconds:
    1. Fetch unprocessed Messages from Django ORM
    2. Send to Claude for extraction (souvenirs + connaissances)
    3. Create ORM records + index in ChromaDB
    4. Apply decay to old souvenirs
    """

    def __init__(
        self,
        extractor: MemoryExtractor,
        vector_store: VectorStore,
        interval_seconds: int | None = None,
    ):
        self.extractor = extractor
        self.vector_store = vector_store
        from configs.service import config_service
        self.interval = interval_seconds or config_service.get("memory.consolidation_interval")
        self._task: asyncio.Task | None = None
        self._last_processed_id: int = 0
        self._running = False

    async def start(self):
        """Start the consolidation background loop."""
        await self._load_last_processed_id()
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Consolidator started (interval=%ds, last_id=%d)",
            self.interval,
            self._last_processed_id,
        )

    async def stop(self):
        """Stop the loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Consolidator stopped")

    async def force_consolidate(self):
        """Run consolidation immediately (e.g. on disconnect/shutdown)."""
        logger.info("Force consolidation triggered")
        await self._consolidate()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _loop(self):
        """Main loop: consolidate every N seconds."""
        tick = 0
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                if self._running:
                    tick += 1
                    logger.info("Consolidation tick #%d (last_id=%d)", tick, self._last_processed_id)
                    await self._consolidate()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Consolidation loop error")

    async def _load_last_processed_id(self):
        """Resume from last consolidation checkpoint."""
        from memory.models import ConsolidationLog

        try:
            last_log = await sync_to_async(
                lambda: ConsolidationLog.objects.order_by("-pk").first()
            )()
            if last_log:
                self._last_processed_id = last_log.last_message_id
        except Exception:
            logger.debug("No previous consolidation log found")

    async def _consolidate(self):
        """Process new messages since last checkpoint."""
        from memory.models import (
            Commitment,
            Connaissance,
            ConsolidationLog,
            Entity,
            Message,
            Souvenir,
            Theme,
        )

        # 1. Fetch unprocessed messages
        #    Exclude module notifications (not user-facing exchanges).
        #    For conscience: exclude internal prompts (role=user) but keep
        #    speech output (role=assistant) so Mika remembers her own initiatives.
        INTERNAL_SOURCES = ("module_email", "module_wake")
        messages = await sync_to_async(list)(
            Message.objects.filter(id__gt=self._last_processed_id)
            .exclude(source__in=INTERNAL_SOURCES)
            .exclude(source="conscience", role="user")
            .order_by("created_at")
            .values("id", "role", "content", "created_at", "source")
        )

        # Also get the absolute max message ID (including internal) to advance checkpoint
        all_max_id = await sync_to_async(
            lambda: Message.objects.filter(id__gt=self._last_processed_id)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        )()

        if not messages:
            # Advance checkpoint past internal-only messages
            if all_max_id:
                self._last_processed_id = all_max_id
            logger.info("Consolidation: no new user messages (last_id=%d)", self._last_processed_id)
            await self._apply_decay()
            # Even with no new messages, the sleep cycle should get its
            # chance — nights are precisely the low-traffic window where
            # journaling / dreaming / digestion need to happen.
            try:
                from memory.sleep import sleep_cycle
                await sleep_cycle.run_if_due()
            except Exception:
                logger.exception("Sleep cycle failed in idle path (non-fatal)")
            # Project runner also runs in the idle path — that's where
            # interval/cron/idle schedules most often fire.
            try:
                from projects.runner import project_runner
                await project_runner.tick()
            except Exception:
                logger.exception("Project runner failed in idle path (non-fatal)")
            return

        logger.info("Consolidating %d new messages (skipped internal)", len(messages))

        # 2. Format for Claude
        msg_dicts = [{"role": m["role"], "content": m["content"]} for m in messages]

        # 3. Extract via Claude
        extractions = await self.extractor.analyze_messages(msg_dicts)

        souvenirs_created = 0
        connaissances_created = 0
        commitments_created = 0
        now = timezone.now()

        for extraction in extractions:
            try:
                # Resolve themes
                theme_objs = []
                for theme_name in extraction.get("themes", []):
                    theme, _ = await sync_to_async(Theme.objects.get_or_create)(
                        name=theme_name.lower().strip()
                    )
                    theme_objs.append(theme)

                # Resolve entities
                entity_objs = []
                for ent in extraction.get("entities", []):
                    entity, _ = await sync_to_async(Entity.objects.get_or_create)(
                        name=ent["name"].strip(),
                        entity_type=ent.get("type", "concept"),
                    )
                    entity_objs.append(entity)

                if extraction["type"] == "souvenir":
                    emotion = extraction.get("emotion", "neutral")
                    souvenir = await sync_to_async(Souvenir.objects.create)(
                        content=extraction["content"],
                        emotion=emotion,
                        importance=1.0,
                        occurred_at=now,
                    )
                    if theme_objs:
                        await sync_to_async(souvenir.themes.set)(theme_objs)
                    if entity_objs:
                        await sync_to_async(souvenir.entities.set)(entity_objs)

                    # Index in ChromaDB (protected — ORM record exists even if indexing fails)
                    try:
                        await sync_to_async(self.vector_store.add_souvenir)(
                            souvenir_id=souvenir.pk,
                            content=extraction["content"],
                            metadata={
                                "importance": 1.0,
                                "emotion": emotion,
                                "occurred_at": now.isoformat(),
                                "themes": ",".join(t.name for t in theme_objs),
                            },
                        )
                    except Exception:
                        logger.warning("ChromaDB indexing failed for souvenir #%d", souvenir.pk)

                    souvenirs_created += 1
                    logger.info(
                        "Souvenir created: [%s] %s",
                        emotion, extraction["content"][:120],
                    )

                elif extraction["type"] == "connaissance":
                    # Check if new info contradicts existing connaissances
                    await self._check_contradictions(extraction["content"])

                    # Check for duplicate connaissances
                    existing = await self._find_similar_connaissance(
                        extraction["content"]
                    )
                    if existing:
                        # Update confidence of existing
                        existing.confidence = min(1.0, existing.confidence + 0.1)
                        await sync_to_async(existing.save)()
                        try:
                            await sync_to_async(self.vector_store.add_connaissance)(
                                connaissance_id=existing.pk,
                                content=existing.content,
                                metadata={
                                    "confidence": existing.confidence,
                                    "is_valid": existing.is_valid,
                                },
                            )
                        except Exception:
                            logger.warning("ChromaDB indexing failed for connaissance #%d", existing.pk)
                        logger.info(
                            "Connaissance reinforced (confidence=%.2f): %s",
                            existing.confidence, existing.content[:120],
                        )
                    else:
                        connaissance = await sync_to_async(
                            Connaissance.objects.create
                        )(
                            content=extraction["content"],
                            confidence=1.0,
                            is_valid=True,
                        )
                        if theme_objs:
                            await sync_to_async(connaissance.themes.set)(theme_objs)
                        if entity_objs:
                            await sync_to_async(connaissance.entities.set)(entity_objs)

                        try:
                            await sync_to_async(self.vector_store.add_connaissance)(
                                connaissance_id=connaissance.pk,
                                content=extraction["content"],
                                metadata={
                                    "confidence": 1.0,
                                    "is_valid": True,
                                    "themes": ",".join(t.name for t in theme_objs),
                                },
                            )
                        except Exception:
                            logger.warning("ChromaDB indexing failed for connaissance #%d", connaissance.pk)

                        connaissances_created += 1
                        logger.info(
                            "Connaissance created: %s",
                            extraction["content"][:120],
                        )

                elif extraction["type"] == "commitment":
                    # Resolve target person if named (Entity type=person).
                    # Extractor may omit for generic commitments.
                    target_person = None
                    person_name = (extraction.get("person") or "").strip()
                    if person_name:
                        target_person, _ = await sync_to_async(
                            Entity.objects.get_or_create
                        )(name=person_name, entity_type="person")

                    await sync_to_async(Commitment.objects.create)(
                        description=extraction["content"],
                        person=target_person,
                        status="pending",
                    )
                    commitments_created += 1
                    logger.info(
                        "Commitment created [to=%s]: %s",
                        person_name or "—",
                        extraction["content"][:120],
                    )

            except Exception:
                logger.exception("Failed to process extraction: %s", extraction)

        # 4. Update checkpoint atomically (transaction protects against crash
        #    between in-memory update and DB write)
        max_id = all_max_id or messages[-1]["id"]

        @sync_to_async
        def _save_checkpoint():
            with transaction.atomic():
                ConsolidationLog.objects.create(
                    messages_processed=len(messages),
                    souvenirs_created=souvenirs_created,
                    connaissances_created=connaissances_created,
                    last_message_id=max_id,
                )

        await _save_checkpoint()
        self._last_processed_id = max_id

        logger.info(
            "Consolidation complete: %d souvenirs, %d connaissances, %d commitments from %d messages",
            souvenirs_created,
            connaissances_created,
            commitments_created,
            len(messages),
        )

        # 5. Apply decay
        await self._apply_decay()

        # 6. Aggregate emotion snapshots into summaries
        await self._aggregate_emotion_snapshots()

        # 7. Regenerate self-concept narrative if due.
        #    Gated by time + volume so it fires on the order of once/day,
        #    not every consolidation tick. Failures are swallowed — the
        #    narrative is best-effort, the memory pipeline is the priority.
        try:
            from memory.narrative import narrative_generator
            await narrative_generator.run_if_due()
        except Exception:
            logger.exception("Self-narrative generation failed (non-fatal)")

        # 8. Regenerate per-person profiles (theory of mind) for active
        #    entities. Capped per-cycle so we don't burst LLM spend.
        try:
            from memory.person_profile import person_profile_generator
            await person_profile_generator.run_cycle()
        except Exception:
            logger.exception("Person profile generation failed (non-fatal)")

        # 9. Sleep cycle — night-time creative/narrative/healing work.
        #    Self-gated: no-op outside the night phase or if Mika is
        #    still active. Runs on the same cadence as consolidation
        #    but skips quickly when not eligible, so negligible cost.
        try:
            from memory.sleep import sleep_cycle
            await sleep_cycle.run_if_due()
        except Exception:
            logger.exception("Sleep cycle failed (non-fatal)")

        # 10. Project runner — advance any projects whose schedule is due.
        #     Cheap no-op when nothing is due. Max 3 advances per tick
        #     to avoid LLM bursts.
        try:
            from projects.runner import project_runner
            await project_runner.tick()
        except Exception:
            logger.exception("Project runner failed (non-fatal)")

    async def _apply_decay(self):
        """Reduce importance of old souvenirs and confidence of old connaissances.
        Remove those below threshold."""
        await self._decay_souvenirs()
        await self._decay_connaissances()

    async def _decay_souvenirs(self):
        """Reduce importance of old souvenirs. Remove those below threshold."""
        from memory.models import Souvenir

        from configs.service import config_service
        decay_rate = config_service.get("memory.decay_rate")
        min_importance = config_service.get("memory.min_importance")
        now = timezone.now()

        souvenirs = await sync_to_async(list)(
            Souvenir.objects.filter(importance__gt=min_importance)
        )

        for souvenir in souvenirs:
            # Use occurred_at (when it happened) not created_at (when it was stored)
            ref_date = souvenir.occurred_at or souvenir.created_at
            days_old = (now - ref_date).total_seconds() / 86400
            new_importance = decay_rate ** days_old
            if new_importance < min_importance:
                try:
                    await sync_to_async(self.vector_store.remove_souvenir)(souvenir.pk)
                except Exception:
                    logger.debug("ChromaDB remove failed for souvenir #%d", souvenir.pk)
                await sync_to_async(souvenir.delete)()
                logger.debug("Pruned souvenir #%d (too old)", souvenir.pk)
            elif abs(new_importance - souvenir.importance) > 0.01:
                souvenir.importance = round(new_importance, 3)
                await sync_to_async(souvenir.save)(update_fields=["importance"])
                try:
                    await sync_to_async(self.vector_store.add_souvenir)(
                        souvenir_id=souvenir.pk,
                        content=souvenir.content,
                        metadata={
                            "importance": souvenir.importance,
                            "occurred_at": ref_date.isoformat(),
                        },
                    )
                except Exception:
                    logger.debug("ChromaDB update failed for souvenir #%d", souvenir.pk)

    async def _decay_connaissances(self):
        """Slowly reduce confidence of old connaissances that haven't been reinforced.

        Unlike souvenirs, connaissances are not deleted — they become 'incertain'
        (low confidence) but stay valid. Only the Conscience can invalidate them.

        Decay rate: ~2% per week after 7 days without reinforcement.
        This is gentler than souvenir decay (0.95^days) because knowledge
        is more durable than episodic memory.
        """
        from memory.models import Connaissance

        now = timezone.now()
        min_confidence = 0.2  # Floor — don't decay below this

        connaissances = await sync_to_async(list)(
            Connaissance.objects.filter(is_valid=True, confidence__gt=min_confidence)
        )

        for conn in connaissances:
            days_since_update = (now - conn.updated_at).total_seconds() / 86400
            if days_since_update < 7:
                continue  # Recently reinforced — skip

            # Gentle decay: lose ~2% confidence per week after 7 days
            weeks_past = days_since_update / 7
            decay = 0.02 * weeks_past
            new_confidence = max(min_confidence, conn.confidence - decay)

            if abs(new_confidence - conn.confidence) > 0.01:
                conn.confidence = round(new_confidence, 3)
                await sync_to_async(conn.save)(update_fields=["confidence"])
                logger.debug(
                    "Decayed connaissance #%d confidence to %.2f",
                    conn.pk, conn.confidence,
                )

    # ------------------------------------------------------------------
    # Emotional memory aggregation
    # ------------------------------------------------------------------

    POSITIVE_EMOTIONS = frozenset({
        "happy", "excited", "love", "proud", "grateful",
        "playful", "amused", "hopeful", "relieved",
    })
    NEGATIVE_EMOTIONS = frozenset({
        "sad", "angry", "scared", "disgusted", "frustrated",
        "lonely", "anxious", "bored", "jealous",
    })

    async def _aggregate_emotion_snapshots(self) -> None:
        """Aggregate raw EmotionSnapshots into EmotionalSummary records.

        Runs after each consolidation cycle. Groups today's snapshots
        by person_id, computes weighted emotion distribution, dominant
        emotion, and trend vs yesterday. Then prunes old snapshots.
        """
        from memory.models import EmotionalSummary, EmotionSnapshot

        now = timezone.now()
        today = now.date()

        # Get distinct person_ids with snapshots from today (exclude __global__)
        person_ids = await sync_to_async(
            lambda: list(
                EmotionSnapshot.objects.filter(
                    created_at__date=today,
                ).exclude(
                    person_id="__global__",
                ).values_list("person_id", flat=True).distinct()
            )
        )()

        if not person_ids:
            return

        for pid in person_ids:
            snapshots = await sync_to_async(
                lambda p=pid: list(
                    EmotionSnapshot.objects.filter(
                        person_id=p, created_at__date=today,
                    ).values("primary_emotion", "primary_intensity")
                )
            )()
            if not snapshots:
                continue

            # Weighted distribution: sum intensity per emotion
            distribution: dict[str, float] = {}
            for s in snapshots:
                emotion = s["primary_emotion"]
                intensity = s["primary_intensity"]
                distribution[emotion] = distribution.get(emotion, 0.0) + intensity

            total = sum(distribution.values()) or 1.0
            normalized = {k: round(v / total, 3) for k, v in distribution.items()}
            dominant = max(distribution, key=distribution.get)
            dominant_intensity = round(distribution[dominant] / len(snapshots), 2)

            # Compute trend vs yesterday
            trend = await self._compute_emotion_trend(pid, normalized, today)

            await sync_to_async(
                lambda p=pid, d=dominant, di=dominant_intensity, n=normalized, t=trend, sc=len(snapshots): (
                    EmotionalSummary.objects.update_or_create(
                        person_id=p,
                        period_type="daily",
                        period_start=today,
                        defaults={
                            "dominant_emotion": d,
                            "dominant_intensity": di,
                            "emotion_distribution": n,
                            "trend": t,
                            "snapshot_count": sc,
                        },
                    )
                )
            )()

        # Prune old snapshots (keep last N days for aggregation overlap)
        from configs.service import config_service
        retention_days = config_service.get("emotion.snapshot_retention_days")
        cutoff = now - timedelta(days=retention_days)
        deleted = await sync_to_async(
            lambda: EmotionSnapshot.objects.filter(created_at__lt=cutoff).delete()
        )()
        if deleted and deleted[0]:
            logger.info("Pruned %d old emotion snapshots", deleted[0])

        logger.debug(
            "Emotion aggregation: %d person(s) for %s", len(person_ids), today,
        )

    async def _compute_emotion_trend(
        self, person_id: str, today_dist: dict, today_date
    ) -> str:
        """Compare today's emotional distribution against yesterday's.

        Returns: 'warming', 'cooling', 'volatile', or 'stable'.
        """
        from memory.models import EmotionalSummary

        yesterday = today_date - timedelta(days=1)
        try:
            prev = await sync_to_async(
                EmotionalSummary.objects.get
            )(person_id=person_id, period_type="daily", period_start=yesterday)
        except EmotionalSummary.DoesNotExist:
            return "stable"

        def pos_neg_ratio(dist: dict) -> float:
            pos = sum(dist.get(e, 0) for e in self.POSITIVE_EMOTIONS)
            neg = sum(dist.get(e, 0) for e in self.NEGATIVE_EMOTIONS)
            return pos - neg

        today_ratio = pos_neg_ratio(today_dist)
        prev_ratio = pos_neg_ratio(prev.emotion_distribution)
        delta = today_ratio - prev_ratio

        if delta > 0.15:
            return "warming"
        elif delta < -0.15:
            return "cooling"
        elif len(today_dist) > 4 and abs(delta) > 0.05:
            return "volatile"
        return "stable"

    # ------------------------------------------------------------------
    # Contradiction checking
    # ------------------------------------------------------------------

    async def _check_contradictions(self, new_content: str) -> None:
        """Check if new connaissance contradicts existing ones.

        Uses vector search to find semantically related connaissances,
        then validates each with LLM. Invalidates contradicted ones.
        """
        from memory.models import Connaissance

        try:
            raw = await sync_to_async(self.vector_store.search_connaissances)(
                new_content, n=5
            )
            if not raw:
                return

            for r in raw:
                try:
                    pk = int(r["id"])
                    conn = await sync_to_async(Connaissance.objects.get)(
                        pk=pk, is_valid=True
                    )
                except (Connaissance.DoesNotExist, ValueError):
                    continue

                # Skip if very similar (duplicate, not contradiction)
                if r.get("distance") is not None and r["distance"] < 0.15:
                    continue

                try:
                    still_valid, new_confidence = (
                        await self.extractor.check_connaissance_validity(
                            conn.content, new_content
                        )
                    )
                except Exception:
                    logger.warning(
                        "Validity check failed for connaissance #%d", conn.pk
                    )
                    continue

                if not still_valid:
                    conn.is_valid = False
                    await sync_to_async(conn.save)(update_fields=["is_valid"])
                    try:
                        await sync_to_async(self.vector_store.add_connaissance)(
                            connaissance_id=conn.pk,
                            content=conn.content,
                            metadata={
                                "confidence": conn.confidence,
                                "is_valid": False,
                            },
                        )
                    except Exception:
                        pass
                    logger.info(
                        "Consolidator invalidated connaissance #%d: %s (contradicted by: %s)",
                        conn.pk, conn.content[:80], new_content[:80],
                    )
                elif abs(new_confidence - conn.confidence) > 0.05:
                    conn.confidence = new_confidence
                    await sync_to_async(conn.save)(update_fields=["confidence"])

        except Exception:
            logger.debug("Contradiction check failed", exc_info=True)

    async def _find_similar_connaissance(self, content: str):
        """Check if a similar connaissance already exists via vector search."""
        from memory.models import Connaissance

        results = await sync_to_async(self.vector_store.search_connaissances)(content, n=1)
        if results and results[0]["distance"] is not None and results[0]["distance"] < 0.15:
            # Very similar — treat as duplicate
            try:
                pk = int(results[0]["id"])
                return await sync_to_async(Connaissance.objects.get)(pk=pk)
            except (Connaissance.DoesNotExist, ValueError):
                pass
        return None
