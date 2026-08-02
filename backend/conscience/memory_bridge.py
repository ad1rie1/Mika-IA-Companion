"""MemoryBridge — the Conscience's R/W interface to long-term memory.

Delegates all operations to memory_manager — single entry point,
uniform guarantees (vector indexing, logging, error handling).
"""

from __future__ import annotations

import logging

from conscience.types import InterpretedSignal

logger = logging.getLogger(__name__)


class MemoryBridge:
    """Read/write interface from the Conscience to long-term memory.

    All operations go through memory_manager — no direct ORM access.
    """

    # ── Read ─────────────────────────────────────────────────────

    async def recall_for_context(self, queries: list[str]) -> str:
        """Retrieve relevant memories for a list of query strings.

        Returns formatted context string or empty.
        """
        from memory.manager import memory_manager

        if not queries:
            return ""

        combined = " ".join(queries[:3])
        try:
            return await memory_manager.get_memory_context(combined)
        except Exception:
            logger.exception("MemoryBridge: recall_for_context failed")
            return ""

    async def get_important_souvenirs(
        self, min_importance: float = 0.5, limit: int = 5
    ) -> list:
        """Get recent important souvenirs."""
        from memory.manager import memory_manager
        return await memory_manager.get_important_souvenirs(min_importance, limit)

    async def who_is_concerned(self, signal_text: str, n: int = 5) -> list[dict]:
        """Who does this signal concern, ranked, with reachable handles.

        Concern-based routing grounded in what conversation has taught:
        1. semantic search souvenirs + connaissances for the signal's topic
        2. collect the *person* entities those memories reference (relevance-weighted)
        3. resolve each name → identity → handles (durable identity layer)
        4. keep only the reachable ones (consumers connected now; modules are
           reachable whenever a durable handle exists — external API is push-capable)

        Returns ``[{"name", "score", "handles": [...]}]`` sorted by score, or [].
        The inclusive (interest) vs exclusive (attribution) decision is left to the
        caller — this returns the candidate field, not the final pick.
        """
        from asgiref.sync import sync_to_async

        from communication.presence import presence_registry
        from identity.resolver import identity_resolver
        from memory.manager import memory_manager

        if not signal_text.strip():
            return []

        souvenirs = await memory_manager.search_related_souvenirs(signal_text, n=n)
        connaissances = await memory_manager.search_related_connaissances(signal_text, n=n)

        names_scores = await sync_to_async(self._person_entities_from_matches)(
            souvenirs, connaissances
        )
        if not names_scores:
            return []

        handle_map = await identity_resolver.handles_for_entity_names(
            list(names_scores)
        )

        results = []
        for name, score in names_scores.items():
            reachable = [
                h for h in handle_map.get(name, [])
                if h["kind"] == "module"  # external API: reachable any time
                or presence_registry.resolve_on(h["person_id"], h["channel"])
            ]
            if reachable:
                results.append(
                    {"name": name, "score": round(score, 3), "handles": reachable}
                )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    @staticmethod
    def _person_entities_from_matches(
        souvenirs: list[dict], connaissances: list[dict]
    ) -> dict[str, float]:
        """Aggregate person-entity names from matched memories, relevance-weighted."""
        from memory.models import Connaissance, Souvenir

        scores: dict[str, float] = {}

        def accumulate(matches, model):
            for r in matches:
                try:
                    pk = int(r["id"])
                except (KeyError, ValueError, TypeError):
                    continue
                distance = r.get("distance")
                relevance = max(0.0, 1.0 - distance) if distance is not None else 0.5
                try:
                    obj = model.objects.prefetch_related("entities").get(pk=pk)
                except model.DoesNotExist:
                    continue
                for entity in obj.entities.all():
                    if entity.entity_type == "person":
                        scores[entity.name] = scores.get(entity.name, 0.0) + relevance

        accumulate(souvenirs, Souvenir)
        accumulate(connaissances, Connaissance)
        return scores

    # ── Write: Create ────────────────────────────────────────────

    async def create_souvenir_from_signal(self, signal: InterpretedSignal):
        """Create a Souvenir from an interpreted signal."""
        from memory.manager import memory_manager

        return await memory_manager.create_souvenir(
            content=signal.summary,
            emotion=signal.emotional_reaction or "neutral",
            importance=signal.pertinence,
        )

    # ── Write: Modify Importance ─────────────────────────────────

    async def boost_importance(self, souvenir_id: int, boost: float) -> None:
        """Increase a souvenir's importance."""
        from memory.manager import memory_manager
        await memory_manager.boost_souvenir(souvenir_id, boost)

    async def reduce_importance(self, souvenir_id: int, reduction: float) -> None:
        """Decrease a souvenir's importance."""
        from memory.manager import memory_manager
        await memory_manager.reduce_souvenir(souvenir_id, reduction)

    async def boost_related_souvenirs(
        self, themes: list[str], boost: float = 0.1
    ) -> int:
        """Boost importance of souvenirs linked to given themes."""
        from memory.manager import memory_manager
        return await memory_manager.boost_souvenirs_by_themes(themes, boost)

    # ── Write: Connaissances ─────────────────────────────────────

    async def invalidate_connaissance(
        self, connaissance_id: int, reason: str = ""
    ) -> None:
        """Mark a knowledge fact as invalid."""
        from memory.manager import memory_manager
        await memory_manager.invalidate_connaissance(connaissance_id, reason)

    async def reinforce_connaissance(
        self, connaissance_id: int, boost: float = 0.1
    ) -> None:
        """Increase confidence of a knowledge fact."""
        from memory.manager import memory_manager
        await memory_manager.reinforce_connaissance(connaissance_id, boost)

    async def check_contradictions(self, new_info: str) -> list[dict]:
        """Check if new information contradicts existing connaissances.

        Uses vector search to find only RELEVANT connaissances (max 5),
        then validates each with an LLM call.

        Returns list of {connaissance_id, content, still_valid, new_confidence}.
        """
        from memory.extraction import MemoryExtractor
        from memory.manager import memory_manager

        results = []
        extractor = MemoryExtractor()

        try:
            candidates = []
            raw = await memory_manager.search_related_connaissances(new_info, n=5)
            for r in raw:
                try:
                    pk = int(r["id"])
                except (ValueError, KeyError):
                    continue
                conn = await memory_manager.get_valid_connaissance(pk)
                if conn:
                    candidates.append(conn)

            if not candidates:
                return results

            for conn in candidates:
                try:
                    still_valid, new_confidence = await extractor.check_connaissance_validity(
                        conn.content, new_info
                    )
                except Exception:
                    logger.warning(
                        "Validity check failed for connaissance #%d", conn.pk
                    )
                    continue

                if not still_valid:
                    await memory_manager.invalidate_connaissance(
                        conn.pk, reason=f"Contradicted by: {new_info[:100]}"
                    )
                    results.append({
                        "connaissance_id": conn.pk,
                        "content": conn.content,
                        "still_valid": False,
                        "new_confidence": new_confidence,
                    })
                elif new_confidence is not None and new_confidence != conn.confidence:
                    await memory_manager.update_connaissance_confidence(
                        conn.pk, new_confidence
                    )
                    results.append({
                        "connaissance_id": conn.pk,
                        "content": conn.content,
                        "still_valid": True,
                        "new_confidence": new_confidence,
                    })

        except Exception:
            logger.exception("check_contradictions failed")

        return results
