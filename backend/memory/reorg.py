"""Réorganisation nocturne — la nuit trie le durable, par thème.

Quatrième phase du sommeil (après journal, rêves, digestion) :

1. **Clustering** des chunks épisodiques du jour par similarité cosinus
   (greedy, seuils configurables) — les embeddings sont **réutilisés tels
   quels** depuis ChromaDB, zéro ré-encodage, zéro dépendance nouvelle
   (numpy arrive avec chromadb).
2. **Extraction par cluster** : le verbatim SQL de chaque thème part dans
   son propre appel d'extraction, au lieu du flux linéaire — « il y a eu
   trois conversations aujourd'hui : le projet, la dispute, les vacances ».
   Réutilise ``consolidator.store_extractions`` (dédoublonnage-renforcement
   et contrôles de contradiction gratuits). Ne porte que sur ce qui reste
   **au-dessus du checkpoint du consolidateur** : à 3 h, le fil de l'eau a
   normalement déjà couvert la journée, et re-passer les mêmes chunks créait
   des paraphrases jumelles que le dédoublonnage ne rattrapait qu'à moitié.
   Le chemin reste vivant pour ce que la journée n'a pas pu extraire — un
   provider mort tout l'après-midi laisse justement ce backlog derrière lui.
3. **Dédoublonnage des souvenirs du jour** sans LLM : auto-requête
   vectorielle, paires quasi identiques fusionnées (importance max, M2M
   unis, FK repointées, perdant retiré de Chroma puis supprimé — le pattern
   de ``_decay_souvenirs``). Idempotent, borné par nuit.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time, timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone

from configs.runtime import cfg_int
from memory.storage.vector_store import souvenir_metadata, vector_call
from memory.storage.window import user_facing_messages
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Les quatre valeurs ci-dessous sont réglables (``memory.reorg_*``) ; elles
# restent déclarées ici comme repli quand le registre est hors d'atteinte.
MAX_CLUSTERS = 20
# Volume max de verbatim envoyé à l'extraction pour UN cluster.
MAX_CLUSTER_CHARS = 6000
# Un cluster d'un seul chunk minuscule est du bruit, pas un thème.
MIN_CLUSTER_CHARS = 200
MAX_MERGES_PER_NIGHT = 50


def _cluster_greedy(
    chunks: list[dict], threshold: float, max_clusters: int | None = None,
) -> list[list[dict]]:
    """Clustering greedy cosinus sur embeddings stockés. Pur, déterministe
    (ordre chronologique par ts).

    ``max_clusters`` non fourni = le réglage ``memory.reorg_max_clusters``. Il
    est lu dans le corps et non en défaut d'argument, un défaut étant évalué à
    l'import — donc avant que la base soit joignable.
    """
    import numpy as np

    if max_clusters is None:
        max_clusters = cfg_int(
            "memory.reorg_max_clusters", MAX_CLUSTERS, mini=1, maxi=200,
        )

    ordered = sorted(
        (c for c in chunks if c.get("embedding") is not None),
        key=lambda c: (c.get("metadata") or {}).get("ts", 0.0),
    )
    clusters: list[dict] = []
    for c in ordered:
        v = np.asarray(c["embedding"], dtype=float)
        norm = float(np.linalg.norm(v)) or 1.0
        v = v / norm
        best, best_sim = None, -1.0
        for cl in clusters:
            sim = float(v @ cl["centroid"])
            if sim > best_sim:
                best, best_sim = cl, sim
        if best is not None and (best_sim >= threshold or len(clusters) >= max_clusters):
            best["items"].append(c)
            best["sum"] = best["sum"] + v
            s_norm = float(np.linalg.norm(best["sum"])) or 1.0
            best["centroid"] = best["sum"] / s_norm
        else:
            clusters.append({"centroid": v, "sum": v.copy(), "items": [c]})
    return [cl["items"] for cl in clusters]


class NightlyReorg:

    async def run(self, night: date) -> dict:
        """Une passe complète pour la journée ``night``. Ne lève jamais."""
        stats = {"chunks": 0, "clusters": 0, "extracted": 0, "merges": 0}
        try:
            stats.update(await self._extract_by_theme(night))
        except Exception as exc:
            degradations.record("reorg: extraction par theme", exc)
        try:
            stats["merges"] = await self._dedup_souvenirs(night)
        except Exception as exc:
            degradations.record("reorg: dedoublonnage", exc)
        logger.info(
            "Reorg nocturne (%s): %d chunks, %d clusters, %d extractions, %d fusions",
            night, stats["chunks"], stats["clusters"],
            stats["extracted"], stats["merges"],
        )
        return stats

    # ── Étape 1+2 : clustering + extraction par thème ────────────

    async def _extract_by_theme(self, night: date) -> dict:
        from configs.service import config_service
        from memory.manager import memory_manager

        store = memory_manager.vector_store
        consolidator = memory_manager.consolidator
        extractor = memory_manager.extractor
        if store is None or consolidator is None or extractor is None:
            return {"chunks": 0, "clusters": 0, "extracted": 0}

        start = timezone.make_aware(datetime.combine(night, dt_time.min))
        end = start + timedelta(days=1)
        chunks = await vector_call(store.get_exchanges_between)(
            start.timestamp(), end.timestamp(), include_embeddings=True,
        )
        if not chunks:
            return {"chunks": 0, "clusters": 0, "extracted": 0}

        try:
            threshold = float(config_service.get("memory.reorg_cluster_similarity"))
        except Exception:
            threshold = 0.55

        clusters = await sync_to_async(_cluster_greedy, thread_sensitive=False)(
            chunks, threshold,
        )

        checkpoint = await self._extraction_checkpoint()

        plancher_cluster = cfg_int(
            "memory.reorg_min_cluster_chars", MIN_CLUSTER_CHARS, mini=0, maxi=5000,
        )
        extracted = 0
        used_clusters = 0
        for items in clusters:
            total_chars = sum(len(c.get("content") or "") for c in items)
            if total_chars < plancher_cluster:
                continue
            messages = await self._fetch_cluster_messages(
                items, min_message_id=checkpoint,
            )
            if not messages:
                continue
            used_clusters += 1
            interlocutors = await self._cluster_interlocutors(items)
            msg_dicts = [
                {"role": m["role"], "content": m["content"]} for m in messages
            ]
            try:
                extractions = await extractor.analyze_messages(msg_dicts)
                if extractions is None:
                    continue
                counts = await consolidator.store_extractions(
                    extractions, interlocutors=interlocutors,
                    occurred_at=messages[-1].get("created_at"),
                )
                extracted += sum(counts.values())
            except Exception as exc:
                degradations.record("reorg: extraction cluster", exc)

        return {"chunks": len(chunks), "clusters": used_clusters, "extracted": extracted}

    @staticmethod
    async def _extraction_checkpoint() -> int:
        from memory.models import ConsolidationLog

        return await sync_to_async(
            lambda: ConsolidationLog.objects.order_by("-pk")
            .values_list("last_message_id", flat=True)
            .first()
            or 0
        )()

    @staticmethod
    async def _fetch_cluster_messages(
        items: list[dict], *, min_message_id: int = 0,
    ) -> list[dict]:
        """Verbatim SQL des plages du cluster, borné à MAX_CLUSTER_CHARS.

        ``min_message_id`` = le checkpoint du consolidateur : en dessous, le
        fil de l'eau a déjà extrait, et un cluster entièrement couvert repart
        vide (donc sans appel LLM ni doublon).
        """
        from django.db.models import Q

        from memory.models import Message

        ranges = []
        for c in items:
            meta = c.get("metadata") or {}
            first, last = meta.get("first_message_id"), meta.get("last_message_id")
            if first and last:
                ranges.append((int(first), int(last)))
        if not ranges:
            return []

        plafond = cfg_int(
            "memory.reorg_max_cluster_chars", MAX_CLUSTER_CHARS, mini=500, maxi=50000,
        )

        def _fetch():
            q = Q()
            for first, last in ranges:
                q |= Q(pk__gte=first, pk__lte=last)
            rows = list(
                user_facing_messages(
                    Message.objects.filter(q).filter(pk__gt=min_message_id)
                )
                .order_by("pk")
                .values("id", "role", "content", "person_id", "created_at")
            )
            out, size = [], 0
            for r in rows:
                size += len(r.get("content") or "")
                if size > plafond:
                    break
                out.append(r)
            return out

        return await sync_to_async(_fetch)()

    @staticmethod
    async def _cluster_interlocutors(items: list[dict]) -> list:
        from identity.resolver import identity_resolver
        from identity.trust import is_internal_person

        handles = {
            (c.get("metadata") or {}).get("handle") or "" for c in items
        }
        out, seen = [], set()
        for handle in sorted(handles):
            if not handle or is_internal_person(handle):
                continue
            try:
                entity = await identity_resolver.entity_for_person(handle)
            except Exception:
                entity = None
            if entity is not None and entity.pk not in seen:
                seen.add(entity.pk)
                out.append(entity)
        return out

    # ── Étape 3 : dédoublonnage des souvenirs du jour ────────────

    async def _dedup_souvenirs(self, night: date) -> int:
        from configs.service import config_service
        from memory.manager import memory_manager
        from memory.models import Souvenir

        store = memory_manager.vector_store
        if store is None:
            return 0
        try:
            max_distance = float(config_service.get("memory.reorg_dedup_distance"))
        except Exception:
            max_distance = 0.12

        # ``__gte`` et non ``=`` : les copies écrites par la passe en cours
        # portent ``created_at`` = nuit+1, donc le dédoublonnage ne voyait
        # jamais ce que la nuit venait de produire — ni les souvenirs
        # réflexifs de la digestion, écrits juste avant.
        todays = await sync_to_async(
            lambda: list(
                Souvenir.objects.filter(created_at__date__gte=night)
                .order_by("pk")
                .values("id", "content", "importance")
            )
        )()

        max_fusions = cfg_int(
            "memory.reorg_max_merges_per_night", MAX_MERGES_PER_NIGHT,
            mini=0, maxi=1000,
        )
        merges = 0
        merged_away: set[int] = set()
        for row in todays:
            if merges >= max_fusions:
                break
            if row["id"] in merged_away:
                continue
            try:
                hits = await vector_call(store.search_souvenirs)(
                    row["content"], n=3, min_importance=0.0,
                )
            except Exception as exc:
                degradations.record("reorg: recherche dedup", exc)
                break
            for h in hits:
                try:
                    other_pk = int(h["id"])
                except (TypeError, ValueError):
                    continue
                distance = h.get("distance")
                if (
                    other_pk == row["id"]
                    or other_pk in merged_away
                    or distance is None
                    or distance >= max_distance
                ):
                    continue
                loser_pk = await self._merge_pair(row["id"], other_pk)
                if loser_pk:
                    merged_away.add(loser_pk)
                    merges += 1
                    try:
                        await vector_call(store.remove_souvenir)(loser_pk)
                    except Exception as exc:
                        degradations.record("reorg: retrait chroma", exc)
                    # Le gagnant a changé d'importance (max + 0.05) : la
                    # métadonnée ChromaDB — le filtre du rappel — doit suivre.
                    keeper_pk = other_pk if loser_pk == row["id"] else row["id"]
                    await memory_manager.reindex_souvenirs([keeper_pk])
                break
        return merges

    @staticmethod
    async def _merge_pair(pk_a: int, pk_b: int) -> int | None:
        """Fusionne deux souvenirs quasi identiques. Renvoie le pk supprimé.

        Gagnant = importance max (égalité : pk le plus bas). Toutes les
        références au perdant sont repointées avant suppression.
        """
        from django.db import transaction

        from conscience.models import Observation
        from memory.models import Commitment, Connaissance, Souvenir

        def _merge() -> int | None:
            with transaction.atomic():
                rows = list(Souvenir.objects.filter(pk__in=[pk_a, pk_b]))
                if len(rows) != 2:
                    return None
                rows.sort(key=lambda s: (-s.importance, s.pk))
                keeper, loser = rows
                keeper.themes.add(*loser.themes.all())
                keeper.entities.add(*loser.entities.all())
                Commitment.objects.filter(source_souvenir=loser).update(
                    source_souvenir=keeper)
                Connaissance.objects.filter(source_souvenir=loser).update(
                    source_souvenir=keeper)
                Observation.objects.filter(souvenir=loser).update(souvenir=keeper)
                for dream in loser.dreams.all():
                    dream.source_souvenirs.add(keeper)
                keeper.importance = min(1.0, max(keeper.importance, loser.importance) + 0.05)
                keeper.save(update_fields=["importance"])
                loser_pk = loser.pk
                loser.delete()
                return loser_pk

        return await sync_to_async(_merge)()


nightly_reorg = NightlyReorg()
