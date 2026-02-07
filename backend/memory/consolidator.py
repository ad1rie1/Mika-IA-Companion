import asyncio
import logging
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from memory.extractor import MemoryExtractor
from memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    """Background task that periodically processes raw messages into
    structured memories. Like human dreams consolidating short-term
    into long-term memory.

    Every N seconds:
    1. Fetch unprocessed Messages from Django ORM
    2. Send to Haiku for extraction (souvenirs + connaissances)
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
        self.interval = interval_seconds or settings.CONSOLIDATION_INTERVAL
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
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                if self._running:
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
                lambda: ConsolidationLog.objects.first()
            )()
            if last_log:
                self._last_processed_id = last_log.last_message_id
        except Exception:
            logger.debug("No previous consolidation log found")

    async def _consolidate(self):
        """Process new messages since last checkpoint."""
        from memory.models import (
            Connaissance,
            ConsolidationLog,
            Entity,
            Message,
            Souvenir,
            Theme,
        )

        # 1. Fetch unprocessed messages
        messages = await sync_to_async(list)(
            Message.objects.filter(id__gt=self._last_processed_id)
            .order_by("created_at")
            .values("id", "role", "content", "created_at")
        )

        if not messages:
            # Still apply decay even with no new messages
            await self._apply_decay()
            return

        logger.info("Consolidating %d new messages", len(messages))

        # 2. Format for Haiku
        msg_dicts = [{"role": m["role"], "content": m["content"]} for m in messages]

        # 3. Extract via Haiku
        extractions = await self.extractor.analyze_messages(msg_dicts)

        souvenirs_created = 0
        connaissances_created = 0
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

                    # Index in ChromaDB
                    self.vector_store.add_souvenir(
                        souvenir_id=souvenir.pk,
                        content=extraction["content"],
                        metadata={
                            "importance": 1.0,
                            "emotion": emotion,
                            "occurred_at": now.isoformat(),
                            "themes": ",".join(t.name for t in theme_objs),
                        },
                    )
                    souvenirs_created += 1

                elif extraction["type"] == "connaissance":
                    # Check for duplicate connaissances
                    existing = await self._find_similar_connaissance(
                        extraction["content"]
                    )
                    if existing:
                        # Update confidence of existing
                        existing.confidence = min(1.0, existing.confidence + 0.1)
                        await sync_to_async(existing.save)()
                        self.vector_store.add_connaissance(
                            connaissance_id=existing.pk,
                            content=existing.content,
                            metadata={
                                "confidence": existing.confidence,
                                "is_valid": existing.is_valid,
                            },
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

                        self.vector_store.add_connaissance(
                            connaissance_id=connaissance.pk,
                            content=extraction["content"],
                            metadata={
                                "confidence": 1.0,
                                "is_valid": True,
                                "themes": ",".join(t.name for t in theme_objs),
                            },
                        )
                        connaissances_created += 1

            except Exception:
                logger.exception("Failed to process extraction: %s", extraction)

        # 4. Update checkpoint
        max_id = messages[-1]["id"]
        self._last_processed_id = max_id

        await sync_to_async(ConsolidationLog.objects.create)(
            messages_processed=len(messages),
            souvenirs_created=souvenirs_created,
            connaissances_created=connaissances_created,
            last_message_id=max_id,
        )

        logger.info(
            "Consolidation complete: %d souvenirs, %d connaissances from %d messages",
            souvenirs_created,
            connaissances_created,
            len(messages),
        )

        # 5. Apply decay
        await self._apply_decay()

    async def _apply_decay(self):
        """Reduce importance of old souvenirs. Remove those below threshold."""
        from memory.models import Souvenir

        decay_rate = settings.MEMORY_DECAY_RATE
        min_importance = settings.MEMORY_MIN_IMPORTANCE
        now = timezone.now()

        souvenirs = await sync_to_async(list)(
            Souvenir.objects.filter(importance__gt=min_importance)
        )

        for souvenir in souvenirs:
            days_old = (now - souvenir.created_at).total_seconds() / 86400
            new_importance = decay_rate ** days_old
            if new_importance < min_importance:
                # Remove from ChromaDB and delete
                self.vector_store.remove_souvenir(souvenir.pk)
                await sync_to_async(souvenir.delete)()
                logger.debug("Pruned souvenir #%d (too old)", souvenir.pk)
            elif abs(new_importance - souvenir.importance) > 0.01:
                souvenir.importance = round(new_importance, 3)
                await sync_to_async(souvenir.save)(update_fields=["importance"])
                # Update metadata in ChromaDB
                self.vector_store.add_souvenir(
                    souvenir_id=souvenir.pk,
                    content=souvenir.content,
                    metadata={
                        "importance": souvenir.importance,
                        "occurred_at": souvenir.occurred_at.isoformat(),
                    },
                )

    async def _find_similar_connaissance(self, content: str):
        """Check if a similar connaissance already exists via vector search."""
        from memory.models import Connaissance

        results = self.vector_store.search_connaissances(content, n=1)
        if results and results[0]["distance"] is not None and results[0]["distance"] < 0.15:
            # Very similar — treat as duplicate
            try:
                pk = int(results[0]["id"])
                return await sync_to_async(Connaissance.objects.get)(pk=pk)
            except (Connaissance.DoesNotExist, ValueError):
                pass
        return None
