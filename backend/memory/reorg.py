"""Réorganisation nocturne — la nuit fusionne ce que le jour a écrit en double.

Quatrième phase du sommeil (après journal, rêves, digestion) : un
**dédoublonnage des souvenirs du jour** sans LLM — auto-requête vectorielle,
paires quasi identiques fusionnées (importance max, M2M unis, FK repointées,
perdant retiré de Chroma puis supprimé — le pattern de ``_decay_souvenirs``).
Idempotent, borné par nuit.

Elle portait deux étapes de plus, un clustering des chunks épisodiques du
jour et une extraction par thème de ce qui restait au-dessus du checkpoint
du consolidateur — sans jamais faire avancer ce checkpoint. Or le
consolidateur possède déjà ce backlog correctement (son curseur n'avance que
sur un succès réel, il relit la fenêtre gelée jusqu'au retour du provider,
ses tranches sont bornées) : ce que la nuit rattrapait, son tick suivant le
réextrayait, et l'étape ne produisait que des paraphrases jumelles.
Restreindre la nuit à ce qui est SOUS le checkpoint aurait réextrait ce que
le jour venait de faire — la régression que ce module documentait. Sa seule
valeur propre était le découpage *par thème* plutôt qu'en ordre linéaire, et
rien ne justifiait de la réserver au rattrapage nocturne : elle vit
désormais dans ``MemoryConsolidator._extract_and_store`` (via
``memory/themes.py``), sur toute fenêtre assez grosse pour être découpée,
avec un checkpoint qui suit. La nuit ne garde que ce qu'elle seule sait
faire — relire la journée entière et fusionner.
"""

from __future__ import annotations

import logging
from datetime import date

from asgiref.sync import sync_to_async

from configs.runtime import cfg_int
from memory.storage.vector_store import vector_call
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Réglable (``memory.reorg_max_merges_per_night``) ; déclaré ici comme repli
# quand le registre est hors d'atteinte.
MAX_MERGES_PER_NIGHT = 50


class NightlyReorg:

    async def run(self, night: date) -> dict:
        """Une passe complète pour la journée ``night``. Ne lève jamais."""
        stats = {"merges": 0}
        try:
            stats["merges"] = await self._dedup_souvenirs(night)
        except Exception as exc:
            degradations.record("reorg: dedoublonnage", exc)
        logger.info("Reorg nocturne (%s): %d fusion(s)", night, stats["merges"])
        return stats

    # ── Dédoublonnage des souvenirs du jour ──────────────────────

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
