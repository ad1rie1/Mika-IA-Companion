"""MemoryBridge — the Conscience's R/W interface to long-term memory.

Delegates all operations to memory_manager — single entry point,
uniform guarantees (vector indexing, logging, error handling).
"""

from __future__ import annotations

import asyncio
import logging

from conscience.types import InterpretedSignal
from utils.degradation import degradations

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

    async def who_is_concerned(self, signal_text: str, n: int = 5) -> list[dict]:
        """Who does this signal concern, ranked, with reachable handles.

        Concern-based routing grounded in what conversation has taught:
        1. semantic search souvenirs + connaissances for the signal's topic
        2. collect the *person* entities those memories reference (relevance-weighted)
        3. resolve each name → identity → handles (durable identity layer)
        4. keep only the reachable ones (consumers connected now; modules are
           reachable whenever a durable handle exists — external API is push-capable)

        Ce que ce quatrieme point suppose — qu'un handle module durable a
        toujours son entree de presence — est rendu vrai au demarrage par
        ``identity_resolver.restore_module_presence()`` : sans elle la
        livraison, elle, ne voyait que la presence en RAM et abandonnait
        silencieusement le message compose pour un contact qui n'avait pas
        ecrit depuis le boot.

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
            # Une seule requete par modele, pas une par resultat : `n` est un
            # parametre d'appel qui peut grandir, et un `prefetch_related` sur
            # un `get()` unitaire ajoute un aller-retour au lieu d'en
            # economiser. Les pk disparus sont simplement absents du filtre.
            relevances: dict[int, float] = {}
            for r in matches:
                try:
                    pk = int(r["id"])
                except (KeyError, ValueError, TypeError):
                    continue
                distance = r.get("distance")
                relevance = max(0.0, 1.0 - distance) if distance is not None else 0.5
                relevances[pk] = relevances.get(pk, 0.0) + relevance

            if not relevances:
                return

            for obj in model.objects.filter(
                pk__in=list(relevances)
            ).prefetch_related("entities"):
                relevance = relevances[obj.pk]
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

    async def boost_related_souvenirs(
        self, themes: list[str], boost: float = 0.1
    ) -> int:
        """Boost importance of souvenirs linked to given themes."""
        from memory.manager import memory_manager
        return await memory_manager.boost_souvenirs_by_themes(themes, boost)

    # ── Write: Connaissances ─────────────────────────────────────

    # Budget par appel de validation, et non par lot. `check_connaissance_validity`
    # porte deja `EXTRACTION_TIMEOUT` (45 s), taille pour le consolidateur ; la
    # boucle de decision, elle, valide jusqu'a cinq candidats en serie et le fait
    # `_decision_lock` tenu. Au budget du consolidateur, une seule observation
    # pouvait retenir le verrou pres de quatre minutes, pendant lesquelles tous
    # les cycles suivants — fast-path haute pertinence compris — retombent sur le
    # `return` silencieux de `_decide()`. Un appelant qui borne plus court que la
    # borne routee (`ai.call_timeout_seconds`) gagne toujours.
    _VALIDITY_TIMEOUT_S = 15

    async def check_contradictions(self, new_info: str) -> list[dict]:
        """Check if new information contradicts existing connaissances.

        Uses vector search to find only RELEVANT connaissances (max 5),
        then validates each with an LLM call, bornee a `_VALIDITY_TIMEOUT_S`.

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
                    still_valid, new_confidence = await asyncio.wait_for(
                        extractor.check_connaissance_validity(
                            conn.content, new_info
                        ),
                        timeout=self._VALIDITY_TIMEOUT_S,
                    )
                except asyncio.TimeoutError as exc:
                    degradations.record(
                        "conscience: validation de connaissance expiree", exc
                    )
                    logger.warning(
                        "Validity check timed out after %ds for connaissance #%d",
                        self._VALIDITY_TIMEOUT_S, conn.pk,
                    )
                    continue
                except Exception as exc:
                    degradations.record("conscience: validation de connaissance", exc)
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
                # Seulement a la baisse : un controle qui ne contredit rien
                # n'est pas une reconfirmation, et le modele recopie volontiers
                # la valeur haute de l'exemple. Une remontee effacerait la
                # decroissance lente (`_decay_connaissances`) et les baisses
                # decidees ailleurs, sans laisser de trace dans les resultats.
                # La hausse deliberee, elle, passe par
                # `memory_manager.reinforce_connaissance`.
                elif new_confidence is not None and new_confidence < conn.confidence:
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
