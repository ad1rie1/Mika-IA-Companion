"""Indexeur épisodique — boucle de fond qui alimente la collection `echanges`.

Boucle **dédiée** plutôt qu'une étape du tick consolidateur : celui-ci bloque
jusqu'à 45 s sur l'appel LLM d'extraction, et la promesse de l'étage 1 est la
trouvabilité *au fil de l'eau*. Un tick sans nouveaux messages coûte un seul
SELECT indexé qui ne renvoie rien.

Checkpoint propre (``EpisodicIndexLog``), ceiling-first comme le
consolidateur, et **le checkpoint n'avance que si l'upsert ChromaDB a
réussi** : un chunk raté serait introuvable jusqu'à sa purge, alors qu'un
retry est gratuit (upsert idempotent par id).
"""

from __future__ import annotations

import logging
import time as _time

from asgiref.sync import sync_to_async
from django.utils import timezone

from old.backend.configs.runtime import cfg_int
from old.backend.memory.episodic.chunker import build_chunks
from old.backend.memory.storage.vector_store import exchange_metadata, vector_call
from old.backend.memory.storage.window import user_facing_messages
from old.backend.utils.degradation import degradations
from old.backend.utils.periodic import PeriodicLoop

logger = logging.getLogger(__name__)

# Les deux valeurs ci-dessous sont réglables (``memory.episodic_*``) ; elles
# restent ici comme repli quand le registre est hors d'atteinte.
# Un backlog après indisponibilité est absorbé sur plusieurs ticks plutôt
# qu'en un seul encode géant.
MAX_MSGS_PER_TICK = 500

# La purge de rétention est un balayage horaire, comme la décroissance.
PRUNE_INTERVAL_S = 3600


class EpisodicIndexer:
    def __init__(self, vector_store, interval_seconds: int | None = None):
        from old.backend.configs.service import config_service

        self.vector_store = vector_store
        if interval_seconds is None:
            try:
                interval_seconds = int(config_service.get("memory.episodic_index_interval"))
            except Exception:
                interval_seconds = 60
        self.interval = interval_seconds
        self._last_processed_id = 0
        self._last_prune = 0.0
        self._loop = PeriodicLoop("EpisodicIndexer", self._tick, self.interval)

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self):
        await self._load_checkpoint()
        await self._loop.start(self.interval)
        logger.info(
            "EpisodicIndexer démarré (checkpoint=%d, période=%ds)",
            self._last_processed_id, self.interval,
        )

    async def stop(self):
        await self._loop.stop()

    # ── Checkpoint ───────────────────────────────────────────────

    async def _load_checkpoint(self):
        from old.backend.memory.models import EpisodicIndexLog

        try:
            last = await sync_to_async(
                lambda: EpisodicIndexLog.objects.order_by("-pk").first()
            )()
            if last:
                self._last_processed_id = last.last_message_id
        except Exception as exc:
            degradations.record("episodic: checkpoint read", exc)

    async def _save_checkpoint(self, last_id: int, chunks_created: int):
        from old.backend.memory.models import EpisodicIndexLog

        await sync_to_async(EpisodicIndexLog.objects.create)(
            last_message_id=last_id, chunks_created=chunks_created,
        )
        self._last_processed_id = last_id

    # ── Tick ─────────────────────────────────────────────────────

    async def _tick(self):
        try:
            await self._index_new_messages()
        except Exception as exc:
            degradations.record("episodic: tick", exc)
        # La purge tourne même quand rien de neuf n'arrive.
        try:
            await self._prune_if_due()
        except Exception as exc:
            degradations.record("episodic: purge", exc)

    async def _index_new_messages(self):
        from old.backend.configs.service import config_service
        from old.backend.memory.models import Message

        # Plafond lu AVANT les messages : un tour persisté entre les deux
        # requêtes serait sinon compté par le checkpoint sans être indexé.
        ceiling_id = await sync_to_async(
            lambda: Message.objects.filter(id__gt=self._last_processed_id)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        )()
        if not ceiling_id:
            return

        lot_max = cfg_int(
            "memory.episodic_max_msgs_per_tick", MAX_MSGS_PER_TICK,
            mini=10, maxi=5000,
        )
        messages = await sync_to_async(list)(
            user_facing_messages(
                Message.objects.filter(
                    id__gt=self._last_processed_id, id__lte=ceiling_id,
                )
            )
            .order_by("created_at", "pk")
            .values(
                "id", "role", "content", "created_at",
                "source", "person_id", "conversation_id",
            )[:lot_max]
        )

        # Fenêtre bornée : si le lot est plein, le plafond effectif est le
        # dernier message lu, pas le plafond global.
        if len(messages) == lot_max:
            ceiling_id = messages[-1]["id"]

        if not messages:
            # Fenêtre entièrement interne/technique : on avance quand même,
            # sinon elle serait relue à chaque tick pour toujours.
            await self._save_checkpoint(ceiling_id, 0)
            return

        try:
            max_chars = int(config_service.get("memory.episodic_chunk_max_chars"))
            flush_age = int(config_service.get("memory.episodic_flush_age_s"))
        except Exception:
            max_chars, flush_age = 600, 600

        chunks, consumed_up_to = build_chunks(
            messages, max_chars=max_chars, flush_age_s=flush_age, now=timezone.now(),
        )

        if chunks:
            entries = [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.text,
                    "metadata": exchange_metadata(
                        conversation_id=c.conversation_id,
                        first_message_id=c.first_message_id,
                        last_message_id=c.last_message_id,
                        handle=c.handle,
                        ts=c.ts,
                    ),
                }
                for c in chunks
            ]
            try:
                await vector_call(self.vector_store.add_exchanges)(entries)
            except Exception as exc:
                # Checkpoint GELÉ : le lot sera rejoué au prochain tick.
                degradations.record("episodic: indexation chromadb", exc)
                return

        new_checkpoint = consumed_up_to if consumed_up_to is not None else ceiling_id
        if new_checkpoint > self._last_processed_id:
            await self._save_checkpoint(new_checkpoint, len(chunks))
            if chunks:
                logger.debug(
                    "Episodic: %d chunk(s) indexé(s), checkpoint=%d",
                    len(chunks), new_checkpoint,
                )

    # ── Rétention (Chroma-only) ──────────────────────────────────

    async def _prune_if_due(self):
        now = _time.monotonic()
        periode = cfg_int(
            "memory.episodic_prune_interval_s", PRUNE_INTERVAL_S,
            mini=60, maxi=86400,
        )
        if now - self._last_prune < periode:
            return
        self._last_prune = now
        await self.prune_expired()

    async def prune_expired(self):
        """Purge les chunks au-delà de la rétention.

        `memory/retention.py` ne parle qu'à l'ORM ; l'étage épisodique n'a
        pas de ligne ORM par chunk, donc il porte son propre chemin de purge.
        Le SQL, lui, garde tout.
        """
        from datetime import timedelta

        from old.backend.configs.service import config_service

        try:
            days = int(config_service.get("memory.episodic_retention_days"))
        except Exception:
            days = 75
        cutoff_ts = (timezone.now() - timedelta(days=days)).timestamp()
        removed = await vector_call(self.vector_store.prune_exchanges_before)(cutoff_ts)
        if removed:
            logger.info("Episodic: %d chunk(s) purgé(s) (> %d jours)", removed, days)
