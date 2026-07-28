import asyncio
import logging
import time as _time
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from memory.extraction.extractor import MemoryExtractor
from memory.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)

# The retention sweep is bookkeeping on tables measured in days, so once an
# hour is plenty — running it on every 60s tick would be pure query load.
RETENTION_SWEEP_INTERVAL_S = 3600

# Pending commitments older than this are dropped (see _expire_commitments).
COMMITMENT_MAX_AGE_DAYS = 30

# Memory decay is measured in days; sweeping for it every 60s was pure load.
DECAY_INTERVAL_S = 3600

# Only rows whose decay anchor is at least this old can move by more than the
# write threshold, so the sweep filters on it in SQL instead of reading the
# whole table into RAM. Generous on purpose: a row that turns out not to move
# simply keeps its anchor, and its elapsed time accumulates for the next pass.
DECAY_MIN_AGE = timedelta(hours=1)

# Ceiling on rows rewritten per pass. Each write also re-indexes into
# ChromaDB (an embedding call), so a first run over a large backlog stays
# bounded instead of stalling the consolidator; the rest is picked up next
# hour, with no loss — the anchor keeps their elapsed time.
DECAY_BATCH = 500


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

        # 1. Pick the ceiling FIRST, then read below it. Reading the messages
        #    first and taking the max id afterwards would let a turn persisted
        #    between the two queries be counted by the checkpoint but never
        #    extracted — that exchange would be skipped forever.
        all_max_id = await sync_to_async(
            lambda: Message.objects.filter(id__gt=self._last_processed_id)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        )()

        # 2. Fetch unprocessed messages up to that ceiling.
        #    Exclude module notifications (not user-facing exchanges) and the
        #    scaffolding prompts of internal triggers (role=user), while
        #    keeping Mika's own replies (role=assistant) so she remembers her
        #    initiatives.
        INTERNAL_SOURCES = ("module_email", "module_wake")
        messages = []
        if all_max_id:
            messages = await sync_to_async(list)(
                Message.objects.filter(
                    id__gt=self._last_processed_id, id__lte=all_max_id,
                )
                .exclude(source__in=INTERNAL_SOURCES)
                .exclude(role="user", is_internal=True)
                .exclude(source="conscience", role="user")
                .order_by("created_at")
                .values(
                    "id", "role", "content", "created_at", "source", "person_id",
                )
            )

        if not messages:
            # Advance checkpoint past internal-only messages
            if all_max_id:
                self._last_processed_id = all_max_id
            logger.info("Consolidation: no new user messages (last_id=%d)", self._last_processed_id)
            await self._apply_decay()
            # Sleep cycle and project runner now run on their own dedicated
            # loops (wired at lifespan startup) — no longer invoked here so
            # a long LLM call in either never delays consolidation.
            return

        logger.info("Consolidating %d new messages (skipped internal)", len(messages))

        # 3. Format for Claude
        msg_dicts = [{"role": m["role"], "content": m["content"]} for m in messages]

        # 4. Extract via Claude. Open commitments ride along so the same
        #    call can notice one being honored in the conversation window
        #    ("voila la playlist !") — that's the autonomous half of the
        #    commitment lifecycle; the explicit half is the
        #    memory_resolve_commitment tool.
        pending_commitments = await sync_to_async(
            lambda: list(
                Commitment.objects.filter(status="pending")
                .order_by("-created_at")
                .values("id", "description")[:10]
            )
        )()
        extractions = await self.extractor.analyze_messages(
            msg_dicts, pending_commitments=pending_commitments
        )

        # Who Mika was talking to in this window, as memory entities. The
        # extractor names entities from the *content* ("Thomas said…"), which
        # misses the most basic fact about an exchange: whom it was with. A
        # conversation where someone never says their own name produced
        # souvenirs attached to nobody, so PersonProfile never had material to
        # generate from and the theory-of-mind layer stayed empty forever.
        interlocutors = await self._resolve_interlocutors(messages)

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
                    # An episode always involves whoever Mika was talking to,
                    # whether or not the extractor thought to name them.
                    linked = _merge_entities(entity_objs, interlocutors)
                    if linked:
                        await sync_to_async(souvenir.entities.set)(linked)

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
                    # Extractor may omit for generic commitments — in that
                    # case the promise was almost certainly made to whoever
                    # Mika was talking to, so fall back to the interlocutor
                    # rather than filing it against nobody.
                    target_person = None
                    person_name = (extraction.get("person") or "").strip()
                    if person_name:
                        target_person, _ = await sync_to_async(
                            Entity.objects.get_or_create
                        )(name=person_name, entity_type="person")
                    elif len(interlocutors) == 1:
                        target_person = interlocutors[0]

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

                elif extraction["type"] == "commitment_resolved":
                    resolution = extraction.get("resolution", "honored")
                    if resolution not in ("honored", "dropped"):
                        resolution = "honored"
                    updated = await sync_to_async(
                        lambda: Commitment.objects.filter(
                            pk=extraction.get("commitment_id"),
                            status="pending",
                        ).update(status=resolution, resolved_at=timezone.now())
                    )()
                    if updated:
                        logger.info(
                            "Commitment #%s resolved (%s) from conversation",
                            extraction.get("commitment_id"), resolution,
                        )

            except Exception:
                logger.exception("Failed to process extraction: %s", extraction)

        # 5. Update checkpoint atomically (transaction protects against crash
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

        # Sleep cycle and project runner now run on their own dedicated
        # loops (wired at lifespan startup) — no longer invoked here.

    @staticmethod
    async def _resolve_interlocutors(messages: list[dict]) -> list:
        """Memory entities for the people Mika exchanged with in this window.

        Goes through the identity layer, so a person only shows up once Mika
        actually knows who they are — authenticated, or a claim she accepted.
        An unidentified visitor contributes nothing here, which is correct:
        their souvenirs stay unattached until she recognizes them, and
        attaching them to a transport handle would just recreate the
        entity-per-socket problem this replaced.
        """
        from identity.resolver import identity_resolver

        person_ids = {
            (m.get("person_id") or "").strip()
            for m in messages
            if m.get("role") == "user"
        }
        entities: list = []
        seen: set[int] = set()
        for person_id in sorted(p for p in person_ids if p):
            try:
                entity = await identity_resolver.entity_for_person(person_id)
            except Exception:
                logger.debug(
                    "Interlocutor resolution failed for %s", person_id,
                    exc_info=True,
                )
                continue
            if entity is not None and entity.pk not in seen:
                seen.add(entity.pk)
                entities.append(entity)
        return entities

    async def _apply_decay(self):
        """Reduce importance of old souvenirs and confidence of old connaissances.
        Remove those below threshold.

        Throttled to ``DECAY_INTERVAL_S``. Memory decay is measured in days,
        so running it on every 60s tick was 1440 full-table sweeps a day to
        apply changes that only become visible after hours — and it ran on
        the "no new messages" path too, so an install nobody talks to paid
        the full cost forever. Correctness is unaffected: decay is anchored
        on each row's ``decayed_at``, so a longer gap just means a larger
        (still exact) step.
        """
        now = _time.monotonic()
        last = getattr(self, "_last_decay", 0.0)
        if last and (now - last) < DECAY_INTERVAL_S:
            # Commitment expiry is a pair of cheap indexed UPDATEs and is
            # what stops a stale promise being re-asserted in every prompt,
            # so it keeps running on its own cadence.
            await self._expire_commitments()
            await self._sweep_retention()
            return
        self._last_decay = now

        await self._decay_souvenirs()
        await self._decay_connaissances()
        await self._expire_commitments()
        await self._sweep_retention()

    async def _expire_commitments(self):
        """Age out stale promises — the "dropped" half of the lifecycle.

        A commitment past its ``due_at``, or pending for more than
        COMMITMENT_MAX_AGE_DAYS, stops being re-asserted in every prompt
        as "tu lui avais dit que..." — after a month it's not a plan
        anymore, it's guilt. Cheap UPDATEs, safe to run every tick.
        """
        from memory.models import Commitment

        now = timezone.now()
        try:
            dropped = await sync_to_async(
                lambda: Commitment.objects.filter(
                    status="pending", due_at__isnull=False, due_at__lt=now,
                ).update(status="dropped", resolved_at=now)
            )()
            cutoff = now - timedelta(days=COMMITMENT_MAX_AGE_DAYS)
            dropped += await sync_to_async(
                lambda: Commitment.objects.filter(
                    status="pending", created_at__lt=cutoff,
                ).update(status="dropped", resolved_at=now)
            )()
            if dropped:
                logger.info("Dropped %d stale commitment(s)", dropped)
        except Exception:
            logger.exception("Commitment expiry failed (non-fatal)")

    async def _sweep_retention(self):
        """Cap the append-only audit tables. Hourly, not every tick.

        Reached from both consolidation paths (with and without new
        messages), so it keeps running on an install nobody talks to — which
        is precisely when ConscienceLog grows fastest relative to content.
        """
        import time as _time

        now = _time.monotonic()
        last = getattr(self, "_last_retention_sweep", 0.0)
        if last and (now - last) < RETENTION_SWEEP_INTERVAL_S:
            return
        self._last_retention_sweep = now
        try:
            from memory.retention import run_sweep
            await run_sweep()
        except Exception:
            logger.exception("Retention sweep failed (non-fatal)")

    async def _decay_souvenirs(self):
        """Reduce importance of old souvenirs. Remove those below threshold.

        Only rows whose anchor is older than ``DECAY_MIN_AGE`` are read: a
        souvenir touched minutes ago cannot move by more than the write
        threshold, so loading it just to skip it was the bulk of the work.
        The rest of the loop stays row-by-row because each write also
        re-indexes into ChromaDB, which no bulk UPDATE can do.
        """
        from django.db.models import Q
        from memory.models import Souvenir

        from configs.service import config_service
        decay_rate = config_service.get("memory.decay_rate")
        min_importance = config_service.get("memory.min_importance")
        now = timezone.now()
        cutoff = now - DECAY_MIN_AGE

        souvenirs = await sync_to_async(list)(
            Souvenir.objects.filter(importance__gt=min_importance)
            .filter(Q(decayed_at__isnull=True) | Q(decayed_at__lt=cutoff))
            .order_by("decayed_at")[:DECAY_BATCH]
        )
        if not souvenirs:
            return

        for souvenir in souvenirs:
            # Use occurred_at (when it happened) not created_at (when it was stored)
            ref_date = souvenir.occurred_at or souvenir.created_at
            # Decay multiplicatively from the CURRENT value since the last pass.
            # Recomputing an absolute rate**age would wipe every conscience
            # boost and inflate freshly-created low-importance souvenirs to ~1.0.
            anchor = souvenir.decayed_at or ref_date
            days_since = max(0.0, (now - anchor).total_seconds() / 86400)
            new_importance = souvenir.importance * (decay_rate ** days_since)
            if new_importance < min_importance:
                try:
                    await sync_to_async(self.vector_store.remove_souvenir)(souvenir.pk)
                except Exception:
                    logger.debug("ChromaDB remove failed for souvenir #%d", souvenir.pk)
                await sync_to_async(souvenir.delete)()
                logger.debug("Pruned souvenir #%d (too old)", souvenir.pk)
            elif abs(new_importance - souvenir.importance) > 0.01:
                # Below that delta we leave the anchor alone so the elapsed
                # time keeps accumulating instead of being silently dropped.
                souvenir.importance = round(new_importance, 3)
                souvenir.decayed_at = now
                await sync_to_async(souvenir.save)(
                    update_fields=["importance", "decayed_at"])
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

        Decay is measured from ``decayed_at``, not ``updated_at``. The latter
        is ``auto_now``, and Django only refreshes an ``auto_now`` field when
        it is among the columns being written — ``save(update_fields=
        ["confidence"])`` never is. So the anchor never advanced and every
        pass re-subtracted the *entire* elapsed decay: at a 60s tick, a fact
        a month old lost ~0.086 per tick and hit the floor in about ten
        minutes. Measured, not theorised: three simulated passes on a 30-day
        row went 1.0 → 0.914 → 0.828 → 0.742.

        This is the same relative-vs-absolute bug already fixed for
        ``Souvenir.decayed_at``; connaissances were simply never migrated.
        """
        from django.db.models import Q
        from memory.models import Connaissance

        now = timezone.now()
        min_confidence = 0.2  # Floor — don't decay below this
        # Nothing reinforced in the last week can have accrued a full week of
        # decay, so the 7-day grace period is expressed in SQL rather than by
        # loading the table and skipping most of it in Python.
        grace_cutoff = now - timedelta(days=7)
        anchor_cutoff = now - DECAY_MIN_AGE

        connaissances = await sync_to_async(list)(
            Connaissance.objects.filter(
                is_valid=True,
                confidence__gt=min_confidence,
                updated_at__lt=grace_cutoff,
            )
            .filter(Q(decayed_at__isnull=True) | Q(decayed_at__lt=anchor_cutoff))
            .order_by("decayed_at")[:DECAY_BATCH]
        )

        for conn in connaissances:
            # First pass for this row: fall back to updated_at, which is when
            # it was last reinforced — the correct starting point.
            anchor = conn.decayed_at or conn.updated_at
            days_since = max(0.0, (now - anchor).total_seconds() / 86400)

            # Gentle decay: lose ~2% confidence per week since the anchor.
            decay = 0.02 * (days_since / 7)
            new_confidence = max(min_confidence, conn.confidence - decay)

            if abs(new_confidence - conn.confidence) > 0.01:
                conn.confidence = round(new_confidence, 3)
                conn.decayed_at = now
                await sync_to_async(conn.save)(
                    update_fields=["confidence", "decayed_at"])
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
                        logger.warning(
                            "Failed to update ChromaDB for invalidated connaissance #%d",
                            conn.pk, exc_info=True,
                        )
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


def _merge_entities(extracted: list, interlocutors: list) -> list:
    """Union of extractor-named entities and the people actually present.

    Order matters only for readability; de-duplication is by pk because the
    two sources routinely produce the same row (someone who says their own
    name mid-conversation is both).
    """
    merged = list(extracted)
    seen = {e.pk for e in merged}
    for entity in interlocutors:
        if entity.pk not in seen:
            seen.add(entity.pk)
            merged.append(entity)
    return merged
