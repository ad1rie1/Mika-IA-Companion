import asyncio
import logging
import time as _time
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from memory.extraction.extractor import MemoryExtractor
from memory.storage.vector_store import VectorStore, vector_call
from utils.periodic import PeriodicLoop
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# The retention sweep is bookkeeping on tables measured in days, so once an
# hour is plenty — running it on every 60s tick would be pure query load.
RETENTION_SWEEP_INTERVAL_S = 3600

# Message sources that are module plumbing, not user-facing exchanges.
INTERNAL_MESSAGE_SOURCES = ("module_email", "module_wake")

# Pending commitments older than this are dropped (see _expire_commitments).
COMMITMENT_MAX_AGE_DAYS = 30

# Memory decay is measured in days; sweeping for it every 60s was pure load.
DECAY_INTERVAL_S = 3600

# Écart de valence entre le meilleur et le pire jour au-delà duquel une
# semaine est dite « instable ». 0.4 sépare une semaine régulière d'une
# semaine qui est passée du clairement négatif au clairement positif — la
# tendance d'un jour se mesure à 0.15, mais sur sept jours c'est la
# *dispersion* qui porte l'information, pas le déplacement moyen.
WEEKLY_VOLATILE_SPREAD = 0.4

# Only rows whose decay anchor is at least this old can move by more than the
# write threshold, so the sweep filters on it in SQL instead of reading the
# whole table into RAM. Generous on purpose: a row that turns out not to move
# simply keeps its anchor, and its elapsed time accumulates for the next pass.
DECAY_MIN_AGE = timedelta(hours=1)

# Nombre maximum de candidats confrontés au LLM par connaissance créée. La
# recherche vectorielle en remonte 5, triés par distance croissante : au-delà
# des deux plus proches, la contradiction devient improbable et chaque
# vérification est un appel LLM séquentiel de plus dans un tick de 60 s — sur
# un backend à un créneau, ils entrent en concurrence avec le tour de
# conversation en cours.
MAX_CONTRADICTION_CHECKS = 2

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
        self._last_processed_id: int = 0
        self._tick_count = 0
        self._loop = PeriodicLoop("Consolidator", self._tick, self.interval)

    async def start(self):
        """Start the consolidation background loop."""
        await self._load_last_processed_id()
        await self._loop.start(self.interval)
        logger.info("Consolidator resumed at last_id=%d", self._last_processed_id)

    async def stop(self):
        """Stop the loop gracefully."""
        await self._loop.stop()

    async def force_consolidate(self):
        """Run consolidation immediately (e.g. on disconnect/shutdown)."""
        logger.info("Force consolidation triggered")
        await self._consolidate()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _tick(self):
        """One scheduled pass. The counter is purely for reading logs."""
        self._tick_count += 1
        logger.info(
            "Consolidation tick #%d (last_id=%d)",
            self._tick_count, self._last_processed_id,
        )
        await self._consolidate()

    async def _load_last_processed_id(self):
        """Resume from last consolidation checkpoint."""
        from memory.models import ConsolidationLog

        try:
            last_log = await sync_to_async(
                lambda: ConsolidationLog.objects.order_by("-pk").first()
            )()
            if last_log:
                self._last_processed_id = last_log.last_message_id
        except Exception as exc:
            # The old message here was "No previous consolidation log found",
            # which this handler never meant: `.first()` returns None on an
            # empty table without raising, so reaching this line is a real DB
            # failure — and one that silently restarts consolidation from the
            # beginning of history.
            degradations.record("consolidator: checkpoint read", exc)

    async def _consolidate(self):
        """Process new messages since last checkpoint.

        Four steps, each its own method: select the window, turn it into
        memories, checkpoint, then run the periodic maintenance that has to
        happen whether or not anything was said.
        """
        messages, ceiling_id = await self._select_window()

        if not messages:
            # Advance past internal-only messages so the window doesn't
            # re-scan them forever.
            if ceiling_id:
                self._last_processed_id = ceiling_id
            logger.info(
                "Consolidation: no new user messages (last_id=%d)",
                self._last_processed_id,
            )
            await self._run_maintenance(regenerate=False)
            return

        logger.info("Consolidating %d new messages (skipped internal)", len(messages))

        counts = await self._extract_and_store(messages)

        max_id = ceiling_id or messages[-1]["id"]
        await self._save_checkpoint(max_id, len(messages), counts)
        self._last_processed_id = max_id

        logger.info(
            "Consolidation complete: %d souvenirs, %d connaissances, "
            "%d commitments from %d messages",
            counts["souvenirs"], counts["connaissances"], counts["commitments"],
            len(messages),
        )

        await self._run_maintenance(regenerate=True)

    # ── Step 1: pick the window ───────────────────────────────────

    async def _select_window(self) -> tuple[list[dict], int | None]:
        """Messages to consolidate, and the id ceiling they were read under.

        The ceiling is picked FIRST, then messages are read below it. Reading
        the messages first and taking the max id afterwards would let a turn
        persisted between the two queries be counted by the checkpoint but
        never extracted — that exchange would be skipped forever.
        """
        from memory.models import Message

        ceiling_id = await sync_to_async(
            lambda: Message.objects.filter(id__gt=self._last_processed_id)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        )()
        if not ceiling_id:
            return [], None

        # Exclude module notifications (not user-facing exchanges) and
        # everything flagged as machinery: the scaffolding prompt of an
        # internal trigger, and the fallback a failed turn returned. Mika's
        # real replies (role=assistant, is_internal=False) stay in, so she
        # still remembers her own initiatives.
        messages = await sync_to_async(list)(
            Message.objects.filter(
                id__gt=self._last_processed_id, id__lte=ceiling_id,
            )
            .exclude(source__in=INTERNAL_MESSAGE_SOURCES)
            .exclude(is_internal=True)
            .exclude(source="conscience", role="user")
            .order_by("created_at")
            .values("id", "role", "content", "created_at", "source", "person_id")
        )
        return messages, ceiling_id

    # ── Step 2: turn the window into memories ─────────────────────

    async def _extract_and_store(self, messages: list[dict]) -> dict[str, int]:
        """Run the extraction LLM over the window and persist what comes back.

        Returns per-type creation counts for the checkpoint log.
        """
        from memory.models import Commitment

        msg_dicts = [{"role": m["role"], "content": m["content"]} for m in messages]

        # Open commitments ride along so the same call can notice one being
        # honored in the window ("voila la playlist !") — the autonomous half
        # of the commitment lifecycle; the explicit half is the
        # memory_resolve_commitment tool.
        pending_commitments = await sync_to_async(
            lambda: list(
                Commitment.objects.filter(status="pending")
                .order_by("-created_at")
                .values("id", "description")[:10]
            )
        )()
        extractions = await self.extractor.analyze_messages(
            msg_dicts, pending_commitments=pending_commitments,
        )

        # Who Mika was talking to, as memory entities. The extractor names
        # entities from the *content* ("Thomas said…"), which misses the most
        # basic fact about an exchange: whom it was with. A conversation where
        # nobody says their own name produced souvenirs attached to nobody, so
        # PersonProfile never had material and theory-of-mind stayed empty.
        interlocutors = await self._resolve_interlocutors(messages)

        counts = {"souvenirs": 0, "connaissances": 0, "commitments": 0}
        handlers = {
            "souvenir": self._store_souvenir,
            "connaissance": self._store_connaissance,
            "commitment": self._store_commitment,
            "commitment_resolved": self._resolve_commitment,
        }

        for extraction in extractions:
            handler = handlers.get(extraction.get("type"))
            if handler is None:
                logger.debug("Unknown extraction type: %s", extraction.get("type"))
                continue
            try:
                themes, entities = await self._resolve_tags(extraction)
                created = await handler(
                    extraction, themes=themes, entities=entities,
                    interlocutors=interlocutors,
                )
                if created:
                    counts[created] += 1
            except Exception:
                # One malformed extraction must not cost the whole window.
                logger.exception("Failed to process extraction: %s", extraction)

        return counts

    @staticmethod
    async def _resolve_tags(extraction: dict) -> tuple[list, list]:
        """Get-or-create the Themes and Entities an extraction refers to."""
        from memory.models import Entity, Theme

        themes = []
        for name in extraction.get("themes", []):
            theme, _ = await sync_to_async(Theme.objects.get_or_create)(
                name=name.lower().strip()
            )
            themes.append(theme)

        entities = []
        for ent in extraction.get("entities", []):
            entity, _ = await sync_to_async(Entity.objects.get_or_create)(
                name=ent["name"].strip(),
                entity_type=ent.get("type", "concept"),
            )
            entities.append(entity)
        return themes, entities

    async def _store_souvenir(
        self, extraction: dict, *, themes: list, entities: list,
        interlocutors: list,
    ) -> str | None:
        from memory.models import Souvenir

        now = timezone.now()
        emotion = extraction.get("emotion", "neutral")
        souvenir = await sync_to_async(Souvenir.objects.create)(
            content=extraction["content"], emotion=emotion,
            importance=1.0, occurred_at=now,
        )
        if themes:
            await sync_to_async(souvenir.themes.set)(themes)
        # An episode always involves whoever Mika was talking to, whether or
        # not the extractor thought to name them.
        linked = _merge_entities(entities, interlocutors)
        if linked:
            await sync_to_async(souvenir.entities.set)(linked)

        await self._index(
            self.vector_store.add_souvenir, "souvenir", souvenir.pk,
            souvenir_id=souvenir.pk,
            content=extraction["content"],
            metadata={
                "importance": 1.0,
                "emotion": emotion,
                "occurred_at": now.isoformat(),
                "themes": ",".join(t.name for t in themes),
            },
        )
        logger.info(
            "Souvenir created: [%s] %s", emotion, extraction["content"][:120],
        )
        return "souvenirs"

    async def _store_connaissance(
        self, extraction: dict, *, themes: list, entities: list,
        interlocutors: list,
    ) -> str | None:
        from memory.models import Connaissance

        content = extraction["content"]

        # Le doublon d'abord : en régime établi c'est le cas courant (un fait
        # déjà connu re-extrait), et la vérification de contradiction coûte un
        # appel LLM par candidat. Les dépenser avant de découvrir qu'aucune
        # ligne ne sera créée, c'est les dépenser pour rien — les
        # contradictions autour de ce contenu ont déjà été vérifiées quand il
        # a été enregistré la première fois.
        existing = await self._find_similar_connaissance(content)
        if existing:
            # Saying the same thing twice is evidence, not a duplicate row.
            existing.confidence = min(1.0, existing.confidence + 0.1)
            await sync_to_async(existing.save)()
            await self._index(
                self.vector_store.add_connaissance, "connaissance", existing.pk,
                connaissance_id=existing.pk,
                content=existing.content,
                metadata={
                    "confidence": existing.confidence,
                    "is_valid": existing.is_valid,
                },
            )
            logger.info(
                "Connaissance reinforced (confidence=%.2f): %s",
                existing.confidence, existing.content[:120],
            )
            return None

        await self._check_contradictions(content)

        connaissance = await sync_to_async(Connaissance.objects.create)(
            content=content, confidence=1.0, is_valid=True,
        )
        if themes:
            await sync_to_async(connaissance.themes.set)(themes)
        if entities:
            await sync_to_async(connaissance.entities.set)(entities)

        await self._index(
            self.vector_store.add_connaissance, "connaissance", connaissance.pk,
            connaissance_id=connaissance.pk,
            content=content,
            metadata={
                "confidence": 1.0,
                "is_valid": True,
                "themes": ",".join(t.name for t in themes),
            },
        )
        logger.info("Connaissance created: %s", content[:120])
        return "connaissances"

    @staticmethod
    async def _store_commitment(
        extraction: dict, *, themes: list, entities: list, interlocutors: list,
    ) -> str | None:
        from memory.models import Commitment, Entity

        # The extractor may omit the target for a generic promise — in that
        # case it was almost certainly made to whoever Mika was talking to,
        # so fall back to the interlocutor rather than filing it against
        # nobody (which is how a commitment becomes unresolvable).
        target_person = None
        person_name = (extraction.get("person") or "").strip()
        if person_name:
            target_person, _ = await sync_to_async(Entity.objects.get_or_create)(
                name=person_name, entity_type="person",
            )
        elif len(interlocutors) == 1:
            target_person = interlocutors[0]

        await sync_to_async(Commitment.objects.create)(
            description=extraction["content"], person=target_person,
            status="pending",
        )
        logger.info(
            "Commitment created [to=%s]: %s",
            person_name or (target_person.name if target_person else "—"),
            extraction["content"][:120],
        )
        return "commitments"

    @staticmethod
    async def _resolve_commitment(
        extraction: dict, *, themes: list, entities: list, interlocutors: list,
    ) -> str | None:
        from memory.models import Commitment

        resolution = extraction.get("resolution", "honored")
        if resolution not in ("honored", "dropped"):
            resolution = "honored"
        updated = await sync_to_async(
            lambda: Commitment.objects.filter(
                pk=extraction.get("commitment_id"), status="pending",
            ).update(status=resolution, resolved_at=timezone.now())
        )()
        if updated:
            logger.info(
                "Commitment #%s resolved (%s) from conversation",
                extraction.get("commitment_id"), resolution,
            )
        return None

    @staticmethod
    async def _index(fn, kind: str, pk: int, **kwargs) -> None:
        """Push a row into ChromaDB, tolerating failure.

        Indexing is best-effort by design: the ORM record is the source of
        truth, and losing a vector entry costs recall, not the memory itself.
        """
        try:
            await vector_call(fn)(**kwargs)
        except Exception:
            logger.warning("ChromaDB indexing failed for %s #%d", kind, pk)

    # ── Step 3: checkpoint ────────────────────────────────────────

    @staticmethod
    async def _save_checkpoint(
        max_id: int, processed: int, counts: dict[str, int],
    ) -> None:
        """Record the window as done, atomically.

        The transaction protects against a crash between the in-memory
        update and the DB write.
        """
        from memory.models import ConsolidationLog

        def _write():
            with transaction.atomic():
                ConsolidationLog.objects.create(
                    messages_processed=processed,
                    souvenirs_created=counts["souvenirs"],
                    connaissances_created=counts["connaissances"],
                    last_message_id=max_id,
                )

        await sync_to_async(_write)()

    # ── Step 4: periodic maintenance ──────────────────────────────

    async def _run_maintenance(self, *, regenerate: bool) -> None:
        """Decay, aggregation, and the two LLM-backed regenerations.

        Runs on both consolidation paths — an install nobody talks to still
        needs its decay and its retention sweep. ``regenerate`` gates the
        narrative and profile passes, which have nothing new to work from
        when no message was consolidated.

        Sleep cycle and project runner have their own dedicated loops (wired
        at lifespan startup), so a long LLM call in either never delays this.
        """
        await self._apply_decay()
        await self._aggregate_emotion_snapshots()

        if not regenerate:
            return

        # Both are best-effort: the memory pipeline is the priority, and a
        # failed narrative must not cost the consolidation that produced it.
        try:
            from memory.narrative import narrative_generator
            await narrative_generator.run_if_due()
        except Exception:
            logger.exception("Self-narrative generation failed (non-fatal)")

        try:
            from memory.person_profile import person_profile_generator
            await person_profile_generator.run_cycle()
        except Exception:
            logger.exception("Person profile generation failed (non-fatal)")

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
            except Exception as exc:
                degradations.record("consolidator: interlocutor resolution failed for", exc)
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
        The rest of the loop stays row-by-row because each row decays from
        its own anchor, which no bulk UPDATE can express.

        Les ré-indexations, elles, sont regroupées en un seul upsert de fin de
        passe : un encode par ligne coûtait jusqu'à ``DECAY_BATCH`` encodes
        consécutifs, là où SentenceTransformer traite un lot en une fois. La
        ligne ORM reste la source de vérité, donc un lot perdu coûte du rappel
        jusqu'à la passe suivante, jamais le souvenir lui-même.
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

        reindex: list[dict] = []
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
                    await vector_call(self.vector_store.remove_souvenir)(souvenir.pk)
                except Exception as exc:
                    degradations.record("consolidator: chromadb remove failed for souvenir #", exc)
                await sync_to_async(souvenir.delete)()
                logger.debug("Pruned souvenir #%d (too old)", souvenir.pk)
            elif abs(new_importance - souvenir.importance) > 0.01:
                # Below that delta we leave the anchor alone so the elapsed
                # time keeps accumulating instead of being silently dropped.
                souvenir.importance = round(new_importance, 3)
                souvenir.decayed_at = now
                await sync_to_async(souvenir.save)(
                    update_fields=["importance", "decayed_at"])
                reindex.append({
                    "souvenir_id": souvenir.pk,
                    "content": souvenir.content,
                    "metadata": {
                        "importance": souvenir.importance,
                        "occurred_at": ref_date.isoformat(),
                    },
                })

        if reindex:
            try:
                await vector_call(self.vector_store.add_souvenirs)(reindex)
            except Exception as exc:
                degradations.record("consolidator: chromadb update failed for souvenir #", exc)

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
            trend = await self._compute_emotion_trend(
                pid, normalized, today - timedelta(days=1), period_type="daily",
            )

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

        # The week in progress, rebuilt from the days just refreshed. Must
        # happen before the prune below: it reads daily rows, not snapshots,
        # but keeping the two aggregations adjacent is what stops one being
        # updated without the other.
        await self._aggregate_weekly_summaries(person_ids, today)

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

    async def _aggregate_weekly_summaries(self, person_ids, today) -> None:
        """Roll the week in progress up from its daily summaries.

        **Built from the daily rows, not from raw snapshots** — and that is
        forced, not a preference: ``emotion.snapshot_retention_days`` defaults
        to **2**, so by the time a week ends five of its seven days have been
        pruned. Reading raw here would produce a row labelled "semaine" that
        covers the last two days, which is worse than no row at all.

        Refreshed in place on every pass, exactly like the daily row, so the
        current week exists from Monday rather than appearing on Sunday night.
        Driving it off *today's* ``person_ids`` is sufficient: a daily row can
        only have changed for someone who was seen today, and every other
        person's weekly row already covers their whole week.

        Two combining rules worth stating, since neither is recoverable from
        the stored daily fields:

        - the distributions are mixed **weighted by ``snapshot_count``**, so a
          busy Monday outweighs one relevé on a quiet Sunday. Exact mixing
          would need each day's total intensity, which the daily row does not
          keep — this is the faithful stand-in, not the same number.
        - ``dominant_intensity`` is the same weighted mean of the dailies'.
          ``snapshot_count`` alone is exact: it is a sum.
        """
        from memory.models import EmotionalSummary

        if not person_ids:
            return

        # Lundi de la semaine ISO en cours — le jour que porte la ligne.
        week_start = today - timedelta(days=today.weekday())

        for pid in person_ids:
            days = await sync_to_async(
                lambda p=pid: list(
                    EmotionalSummary.objects.filter(
                        person_id=p, period_type="daily",
                        period_start__gte=week_start, period_start__lte=today,
                    ).order_by("period_start")
                )
            )()
            if not days:
                continue

            distribution: dict[str, float] = {}
            weight_total = 0.0
            intensity_total = 0.0
            snapshot_total = 0
            for day in days:
                weight = float(day.snapshot_count or 0) or 1.0
                for emotion, share in (day.emotion_distribution or {}).items():
                    distribution[emotion] = (
                        distribution.get(emotion, 0.0) + share * weight
                    )
                intensity_total += (day.dominant_intensity or 0.0) * weight
                weight_total += weight
                snapshot_total += day.snapshot_count or 0

            total = sum(distribution.values()) or 1.0
            normalized = {k: round(v / total, 3) for k, v in distribution.items()}
            dominant = max(distribution, key=distribution.get)
            dominant_intensity = round(intensity_total / (weight_total or 1.0), 2)

            trend = await self._compute_emotion_trend(
                pid, normalized, week_start - timedelta(days=7),
                period_type="weekly",
                sub_ratios=[
                    self._valence(d.emotion_distribution or {}) for d in days
                ],
            )

            await sync_to_async(
                lambda p=pid, ws=week_start, d=dominant, di=dominant_intensity,
                       n=normalized, t=trend, sc=snapshot_total: (
                    EmotionalSummary.objects.update_or_create(
                        person_id=p,
                        period_type="weekly",
                        period_start=ws,
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

        logger.debug(
            "Weekly emotion rollup: %d person(s) for week of %s",
            len(person_ids), week_start,
        )

    def _valence(self, dist: dict) -> float:
        """Positif moins négatif — l'axe sur lequel une tendance se mesure."""
        pos = sum(dist.get(e, 0) for e in self.POSITIVE_EMOTIONS)
        neg = sum(dist.get(e, 0) for e in self.NEGATIVE_EMOTIONS)
        return pos - neg

    async def _compute_emotion_trend(
        self, person_id: str, dist: dict, previous_start, *,
        period_type: str = "daily", sub_ratios: list[float] | None = None,
    ) -> str:
        """Compare a period's emotional distribution against the one before.

        Returns: 'warming', 'cooling', 'volatile', or 'stable'.

        ``sub_ratios`` carries the valence of each sub-period (the days making
        up a week) and is how volatility is measured for anything longer than
        a day. The daily rule — "more than four distinct emotions plus a small
        valence shift" — is a proxy for choppiness that only holds over a few
        hours: **over a week five distinct emotions is the normal case**, so
        reusing it would have stamped "instable" on nearly every weekly row.
        A week is volatile when its *days* disagree, which is a thing we can
        actually measure.
        """
        from memory.models import EmotionalSummary

        try:
            prev = await sync_to_async(EmotionalSummary.objects.get)(
                person_id=person_id, period_type=period_type,
                period_start=previous_start,
            )
            delta = self._valence(dist) - self._valence(prev.emotion_distribution)
        except EmotionalSummary.DoesNotExist:
            # Sans période précédente il n'y a pas de tendance à mesurer —
            # mais un écart entre les jours, lui, reste observable.
            delta = 0.0
            if not sub_ratios:
                return "stable"

        if delta > 0.15:
            return "warming"
        if delta < -0.15:
            return "cooling"
        if sub_ratios is not None:
            spread = max(sub_ratios) - min(sub_ratios) if sub_ratios else 0.0
            return "volatile" if spread > WEEKLY_VOLATILE_SPREAD else "stable"
        if len(dist) > 4 and abs(delta) > 0.05:
            return "volatile"
        return "stable"

    # ------------------------------------------------------------------
    # Contradiction checking
    # ------------------------------------------------------------------

    async def _check_contradictions(self, new_content: str) -> None:
        """Check if new connaissance contradicts existing ones.

        Uses vector search to find semantically related connaissances,
        then validates the closest ones with LLM (at most
        MAX_CONTRADICTION_CHECKS). Invalidates contradicted ones.
        """
        from memory.models import Connaissance

        try:
            raw = await vector_call(self.vector_store.search_connaissances)(
                new_content, n=5
            )
            if not raw:
                return

            checked = 0
            for r in raw:
                if checked >= MAX_CONTRADICTION_CHECKS:
                    break

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

                checked += 1
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
                        await vector_call(self.vector_store.add_connaissance)(
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
                # Seulement a la baisse, comme le bridge : remonter la confiance
                # ici annulerait la decroissance que ce meme consolidateur
                # applique par ailleurs.
                elif new_confidence is not None and conn.confidence - new_confidence > 0.05:
                    conn.confidence = new_confidence
                    await sync_to_async(conn.save)(update_fields=["confidence"])

        except Exception as exc:
            degradations.record("consolidator: contradiction check", exc)

    async def _find_similar_connaissance(self, content: str):
        """Check if a similar connaissance already exists via vector search."""
        from memory.models import Connaissance

        results = await vector_call(self.vector_store.search_connaissances)(content, n=1)
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
