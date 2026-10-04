"""Réorganisation nocturne — dédoublonnage des souvenirs, et rien d'autre.

Le clustering et l'extraction par thème ont quitté ce module pour le
consolidateur (voir test_extraction_par_theme.py) : la nuit extrayait
au-dessus du checkpoint sans le faire avancer, et le tick suivant
réextrayait la même fenêtre. Les tests ci-dessous pinent ce qui reste — la
fusion — et le fait que la nuit ne convoque plus l'extracteur.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from old.backend.memory.reorg import NightlyReorg


@pytest.mark.django_db(transaction=True)
class TestDedup:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.conscience.models import Observation
        from old.backend.memory.models import Commitment, Souvenir
        Observation.objects.all().delete()
        Commitment.objects.all().delete()
        Souvenir.objects.all().delete()
        yield

    async def test_merge_keeps_the_important_one_and_repoints(self):
        from django.utils import timezone

        from old.backend.conscience.models import Observation
        from old.backend.memory.models import Souvenir

        keeper = await Souvenir.objects.acreate(
            content="Thomas adore son chat", importance=0.9,
            occurred_at=timezone.now(),
        )
        loser = await Souvenir.objects.acreate(
            content="Thomas aime beaucoup son chat", importance=0.4,
            occurred_at=timezone.now(),
        )
        obs = await Observation.objects.acreate(
            source="web", event_type="chat.message", summary="s",
            souvenir=loser,
        )

        reorg = NightlyReorg()
        removed = await reorg._merge_pair(keeper.pk, loser.pk)
        assert removed == loser.pk
        assert not await Souvenir.objects.filter(pk=loser.pk).aexists()
        await obs.arefresh_from_db()
        assert obs.souvenir_id == keeper.pk
        await keeper.arefresh_from_db()
        assert keeper.importance == pytest.approx(0.95)

    async def test_dedup_pass_merges_close_pairs_and_prunes_chroma(self, monkeypatch):
        from django.utils import timezone

        from old.backend.memory.models import Souvenir

        a = await Souvenir.objects.acreate(
            content="a", importance=0.8, occurred_at=timezone.now())
        b = await Souvenir.objects.acreate(
            content="b", importance=0.2, occurred_at=timezone.now())

        removed_from_chroma = []

        class FakeStore:
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                return [
                    {"id": str(a.pk), "distance": 0.0},
                    {"id": str(b.pk), "distance": 0.05},
                ]

            def remove_souvenir(self, pk):
                removed_from_chroma.append(pk)

        import old.backend.memory.manager as manager_mod
        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore())

        reorg = NightlyReorg()
        merges = await reorg._dedup_souvenirs(date.today())
        assert merges == 1
        assert removed_from_chroma == [b.pk]
        assert not await Souvenir.objects.filter(pk=b.pk).aexists()

        # Idempotence : une seconde passe ne trouve plus de paire.
        class FakeStore2(FakeStore):
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                return [{"id": str(a.pk), "distance": 0.0}]

        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore2())
        assert await reorg._dedup_souvenirs(date.today()) == 0

    async def test_la_dedup_voit_les_souvenirs_ecrits_par_la_nuit_elle_meme(self, monkeypatch):
        """La passe tourne à 3 h et couvre la veille : ce qu'elle vient
        d'écrire porte ``created_at`` = nuit+1, et lui échappait donc."""
        from datetime import timedelta

        from django.utils import timezone

        from old.backend.memory.models import Souvenir

        s = await Souvenir.objects.acreate(
            content="écrit par la passe de cette nuit", importance=0.5,
            occurred_at=timezone.now() - timedelta(days=1),
        )
        interroges = []

        class FakeStore:
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                interroges.append(content)
                return []

        import old.backend.memory.manager as manager_mod
        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore())

        hier = date.today() - timedelta(days=1)
        await NightlyReorg()._dedup_souvenirs(hier)

        assert s.content in interroges


@pytest.mark.django_db(transaction=True)
class TestLaNuitNExtraitPlus:
    """La nuit ne relit plus le verbatim : ni extracteur, ni consolidateur."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Souvenir
        Souvenir.objects.all().delete()
        yield

    async def test_run_ne_convoque_ni_l_extracteur_ni_le_consolidateur(self, monkeypatch):
        from django.utils import timezone

        import old.backend.memory.manager as manager_mod
        from old.backend.memory.models import Souvenir

        # Un souvenir du jour, pour que la passe ait bien quelque chose à
        # parcourir — un run à vide prouverait moins.
        await Souvenir.objects.acreate(
            content="on a parlé du projet fusée", importance=0.5,
            occurred_at=timezone.now(),
        )

        class FakeStore:
            def search_souvenirs(self, content, n=3, min_importance=0.0):
                return []

        fake_extractor = type("X", (), {})()
        fake_extractor.analyze_messages = AsyncMock(return_value=[])
        fake_consolidator = type("C", (), {})()
        fake_consolidator.store_extractions = AsyncMock(return_value={})
        monkeypatch.setattr(manager_mod.memory_manager, "vector_store", FakeStore())
        monkeypatch.setattr(manager_mod.memory_manager, "extractor", fake_extractor)
        monkeypatch.setattr(manager_mod.memory_manager, "consolidator", fake_consolidator)

        stats = await NightlyReorg().run(date.today())

        fake_extractor.analyze_messages.assert_not_awaited()
        fake_consolidator.store_extractions.assert_not_awaited()
        assert stats == {"merges": 0}

    async def test_run_rend_le_nombre_de_fusions_meme_quand_la_dedup_casse(self):
        """Le cycle de sommeil journalise ce que ``run`` rend : la clé doit
        être là même quand la passe a dégradé."""
        reorg = NightlyReorg()
        reorg._dedup_souvenirs = AsyncMock(side_effect=RuntimeError("chroma down"))

        stats = await reorg.run(date.today())

        assert stats == {"merges": 0}

    def test_le_module_ne_reference_plus_l_extraction(self):
        """Garde AST, jamais une recherche de texte : les commentaires de ce
        dépôt nomment précisément ce qu'il ne faut plus faire."""
        source = (Path(__file__).resolve().parent.parent / "memory" / "reorg.py") \
            .read_text(encoding="utf-8")
        arbre = ast.parse(source)
        interdits = {
            "analyze_messages", "store_extractions", "cluster_greedy",
            "_cluster_greedy", "get_exchanges_between", "get_exchanges_for_messages",
        }
        noms = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Attribute):
                noms.add(noeud.attr)
            elif isinstance(noeud, ast.Name):
                noms.add(noeud.id)
            elif isinstance(noeud, ast.ImportFrom):
                assert (noeud.module or "") != "memory.themes", (
                    "la réorg ne regroupe plus : memory.themes appartient "
                    "au consolidateur"
                )
        assert not (noms & interdits), f"la nuit extrait encore : {noms & interdits}"
