"""Les résumés émotionnels — le jour, et la semaine cumulée par-dessus.

``EmotionalSummary`` déclarait ``period_type="weekly"`` depuis toujours et le
consolidateur n'en écrivait **jamais** : l'onglet Affect d'une fiche personne,
dont le filtre est par défaut sur la semaine, était structurellement vide.

Deux propriétés portent l'essentiel de ce que le cumul hebdomadaire promet :

- il est construit **depuis les résumés du jour**, pas depuis les relevés
  bruts. Ce n'est pas un choix de style : ``emotion.snapshot_retention_days``
  vaut 2 par défaut, donc à la fin d'une semaine cinq de ses sept jours ont
  été élagués. Lire les relevés produirait une ligne intitulée « semaine » qui
  ne couvre que l'avant-veille.
- une semaine est dite **instable quand ses jours se contredisent**, pas quand
  elle contient beaucoup d'émotions différentes. La règle du jour (« plus de
  quatre émotions distinctes ») est vraie sur quelques heures et fausse sur
  sept jours, où cinq émotions distinctes sont le cas normal.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async

# Un jeudi : la semaine ISO en cours commence le lundi 27/07/2026.
JEUDI = date(2026, 7, 30)
LUNDI = date(2026, 7, 27)


def _consolidator():
    from memory.storage.consolidator import MemoryConsolidator

    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c.vector_store = MagicMock()
    c.extractor = MagicMock()
    return c


async def _jour(person_id, jour, distribution, *, intensite=0.5, releves=1):
    from memory.models import EmotionalSummary

    return await sync_to_async(EmotionalSummary.objects.create)(
        person_id=person_id, period_type="daily", period_start=jour,
        dominant_emotion=max(distribution, key=distribution.get),
        dominant_intensity=intensite, emotion_distribution=distribution,
        trend="stable", snapshot_count=releves,
    )


async def _semaine(person_id, lundi, distribution, *, releves=1):
    from memory.models import EmotionalSummary

    return await sync_to_async(EmotionalSummary.objects.create)(
        person_id=person_id, period_type="weekly", period_start=lundi,
        dominant_emotion=max(distribution, key=distribution.get),
        dominant_intensity=0.5, emotion_distribution=distribution,
        trend="stable", snapshot_count=releves,
    )


async def _lire_semaine(person_id, lundi=LUNDI):
    from memory.models import EmotionalSummary

    return await sync_to_async(EmotionalSummary.objects.get)(
        person_id=person_id, period_type="weekly", period_start=lundi,
    )


@pytest.mark.django_db(transaction=True)
class TestCumulHebdomadaire:

    @pytest.fixture(autouse=True)
    def _propre(self):
        from memory.models import EmotionalSummary
        EmotionalSummary.objects.all().delete()
        yield
        EmotionalSummary.objects.all().delete()

    @pytest.mark.asyncio
    async def test_la_ligne_porte_le_lundi_de_la_semaine_iso(self):
        """Un jeudi doit alimenter la semaine du lundi qui le précède."""
        await _jour("p", JEUDI, {"happy": 1.0})
        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)

        semaine = await _lire_semaine("p")
        assert semaine.period_start == LUNDI
        assert semaine.period_start.weekday() == 0

    @pytest.mark.asyncio
    async def test_les_jours_sont_melanges_au_prorata_de_leur_volume(self):
        """Une journée chargée pèse plus qu'un relevé isolé.

        Sans pondération, un unique relevé un dimanche calme pèserait autant
        qu'une centaine un lundi — la semaine dirait l'inverse de ce qu'elle a
        été.
        """
        await _jour("p", LUNDI, {"sad": 1.0}, intensite=0.4, releves=2)
        await _jour("p", LUNDI + timedelta(days=2), {"happy": 1.0},
                    intensite=0.8, releves=6)

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        semaine = await _lire_semaine("p")

        assert semaine.emotion_distribution == {"sad": 0.25, "happy": 0.75}
        assert semaine.dominant_emotion == "happy"
        # (0.4×2 + 0.8×6) / 8
        assert semaine.dominant_intensity == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_le_nombre_de_releves_est_une_somme_exacte(self):
        """Le seul champ recombinable sans perte — il doit l'être vraiment."""
        await _jour("p", LUNDI, {"happy": 1.0}, releves=2)
        await _jour("p", LUNDI + timedelta(days=1), {"happy": 1.0}, releves=6)
        await _jour("p", LUNDI + timedelta(days=2), {"sad": 1.0}, releves=5)

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        assert (await _lire_semaine("p")).snapshot_count == 13

    @pytest.mark.asyncio
    async def test_les_jours_hors_semaine_sont_ignores(self):
        """Le cumul s'arrête au lundi, sinon « la semaine » ne veut rien dire."""
        await _jour("p", LUNDI - timedelta(days=1), {"angry": 1.0}, releves=50)
        await _jour("p", LUNDI, {"happy": 1.0}, releves=1)

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        semaine = await _lire_semaine("p")

        assert "angry" not in semaine.emotion_distribution
        assert semaine.snapshot_count == 1

    @pytest.mark.asyncio
    async def test_relancer_rafraichit_la_ligne_sans_la_dupliquer(self):
        """Rafraîchie à chaque passe, comme la ligne du jour : la semaine en
        cours existe dès le lundi au lieu d'apparaître le dimanche soir."""
        from memory.models import EmotionalSummary

        await _jour("p", LUNDI, {"sad": 1.0}, releves=1)
        await _consolidator()._aggregate_weekly_summaries(["p"], LUNDI)
        assert (await _lire_semaine("p")).dominant_emotion == "sad"

        await _jour("p", LUNDI + timedelta(days=1), {"happy": 1.0}, releves=9)
        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)

        lignes = await sync_to_async(
            lambda: EmotionalSummary.objects.filter(
                person_id="p", period_type="weekly",
            ).count()
        )()
        assert lignes == 1
        assert (await _lire_semaine("p")).dominant_emotion == "happy"

    @pytest.mark.asyncio
    async def test_une_personne_sans_jour_ne_produit_pas_de_ligne(self):
        from memory.models import EmotionalSummary

        await _consolidator()._aggregate_weekly_summaries(["fantome"], JEUDI)

        existe = await sync_to_async(
            lambda: EmotionalSummary.objects.filter(person_id="fantome").exists()
        )()
        assert not existe


@pytest.mark.django_db(transaction=True)
class TestTendanceHebdomadaire:

    @pytest.fixture(autouse=True)
    def _propre(self):
        from memory.models import EmotionalSummary
        EmotionalSummary.objects.all().delete()
        yield
        EmotionalSummary.objects.all().delete()

    @pytest.mark.asyncio
    async def test_une_semaine_plus_positive_que_la_precedente_se_rechauffe(self):
        await _semaine("p", LUNDI - timedelta(days=7), {"sad": 1.0})
        await _jour("p", LUNDI, {"happy": 1.0})

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        assert (await _lire_semaine("p")).trend == "warming"

    @pytest.mark.asyncio
    async def test_une_semaine_plus_negative_que_la_precedente_se_refroidit(self):
        await _semaine("p", LUNDI - timedelta(days=7), {"happy": 1.0})
        await _jour("p", LUNDI, {"sad": 1.0})

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        assert (await _lire_semaine("p")).trend == "cooling"

    @pytest.mark.asyncio
    async def test_une_semaine_est_instable_quand_ses_jours_se_contredisent(self):
        """Un lundi franchement mauvais et un mercredi franchement bon.

        Le cumul ne bouge pas d'une semaine à l'autre — mais la semaine s'est
        bel et bien passée en dents de scie, et c'est ça qu'on veut lire.
        """
        await _semaine("p", LUNDI - timedelta(days=7), {"happy": 0.5, "sad": 0.5})
        await _jour("p", LUNDI, {"sad": 1.0}, releves=5)
        await _jour("p", LUNDI + timedelta(days=2), {"happy": 1.0}, releves=5)

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        assert (await _lire_semaine("p")).trend == "volatile"

    @pytest.mark.asyncio
    async def test_beaucoup_d_emotions_distinctes_ne_suffit_pas_a_dire_instable(self):
        """La règle du jour, appliquée telle quelle, aurait tamponné
        « instable » sur presque toutes les lignes hebdomadaires : cinq
        émotions distinctes sur sept jours, c'est le cas normal. Ici les cinq
        sont réparties uniformément sur des jours qui se ressemblent."""
        repartition = {
            "happy": 0.2, "amused": 0.2, "curious": 0.2,
            "thinking": 0.2, "hopeful": 0.2,
        }
        await _semaine("p", LUNDI - timedelta(days=7), repartition)
        for decalage in range(3):
            await _jour("p", LUNDI + timedelta(days=decalage), repartition,
                        releves=4)

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        assert (await _lire_semaine("p")).trend == "stable"

    @pytest.mark.asyncio
    async def test_sans_semaine_precedente_l_instabilite_reste_mesurable(self):
        """Il n'y a pas de tendance à mesurer, mais l'écart entre les jours,
        lui, s'observe dès la première semaine."""
        await _jour("p", LUNDI, {"sad": 1.0}, releves=5)
        await _jour("p", LUNDI + timedelta(days=2), {"happy": 1.0}, releves=5)

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        assert (await _lire_semaine("p")).trend == "volatile"

    @pytest.mark.asyncio
    async def test_la_regle_du_jour_est_inchangee(self):
        """Le calcul quotidien passait par la même fonction ; la généraliser
        ne doit pas l'avoir déplacée."""
        c = _consolidator()
        veille = JEUDI - timedelta(days=1)

        await _jour("hausse", veille, {"sad": 1.0})
        assert await c._compute_emotion_trend(
            "hausse", {"happy": 1.0}, veille, period_type="daily",
        ) == "warming"

        # Plus de quatre émotions distinctes + un déplacement de valence trop
        # petit pour être une tendance (+0.1) : la définition quotidienne de
        # l'instabilité, conservée telle quelle.
        # Valence de la veille : 0.4. Celle du jour : 0.6 − 0.1 = 0.5.
        await _jour("dents", veille, {"happy": 0.4, "curious": 0.6})
        assert await c._compute_emotion_trend(
            "dents",
            {"happy": 0.5, "amused": 0.1, "curious": 0.1,
             "thinking": 0.2, "sad": 0.1},
            veille, period_type="daily",
        ) == "volatile"

    @pytest.mark.asyncio
    async def test_sans_periode_precedente_un_jour_est_stable(self):
        c = _consolidator()
        assert await c._compute_emotion_trend(
            "p", {"happy": 1.0}, JEUDI - timedelta(days=1), period_type="daily",
        ) == "stable"


@pytest.mark.django_db(transaction=True)
class TestSourceDuCumul:

    @pytest.fixture(autouse=True)
    def _propre(self):
        from memory.models import Conversation, EmotionalSummary, EmotionSnapshot
        EmotionSnapshot.objects.all().delete()
        EmotionalSummary.objects.all().delete()
        Conversation.objects.all().delete()
        yield
        EmotionSnapshot.objects.all().delete()
        EmotionalSummary.objects.all().delete()
        Conversation.objects.all().delete()

    @pytest.mark.asyncio
    async def test_le_cumul_ne_lit_jamais_les_releves_bruts(self):
        """La garde qui protège la décision : les relevés ne survivent pas à
        la semaine (rétention par défaut : 2 jours). Un cumul qui les lirait
        couvrirait l'avant-veille en s'intitulant « semaine »."""
        from memory.models import Conversation, EmotionSnapshot

        conversation = await sync_to_async(Conversation.objects.create)()
        await sync_to_async(EmotionSnapshot.objects.create)(
            conversation=conversation, person_id="p",
            primary_emotion="angry", primary_intensity=0.9,
            global_emotion="angry", global_intensity=0.9,
        )
        # Un seul jour déclaré, et il ne dit pas « angry ».
        await _jour("p", LUNDI, {"happy": 1.0}, releves=1)

        await _consolidator()._aggregate_weekly_summaries(["p"], JEUDI)
        semaine = await _lire_semaine("p")

        assert "angry" not in semaine.emotion_distribution, (
            "le cumul doit venir des résumés du jour, pas des relevés"
        )

    @pytest.mark.asyncio
    async def test_la_passe_quotidienne_produit_aussi_la_semaine(self):
        """Bout en bout : des relevés bruts jusqu'aux deux granularités.

        C'est le câblage qui manquait — les deux agrégations existaient
        séparément, aucune ne appelait l'autre.
        """
        from django.utils import timezone

        from memory.models import Conversation, EmotionalSummary, EmotionSnapshot

        conversation = await sync_to_async(Conversation.objects.create)()
        for _ in range(3):
            await sync_to_async(EmotionSnapshot.objects.create)(
                conversation=conversation, person_id="web_test",
                primary_emotion="happy", primary_intensity=0.7,
                global_emotion="happy", global_intensity=0.7,
            )

        await _consolidator()._aggregate_emotion_snapshots()

        aujourdhui = timezone.now().date()
        lundi = aujourdhui - timedelta(days=aujourdhui.weekday())
        lignes = await sync_to_async(
            lambda: {
                (s.period_type, s.period_start): s
                for s in EmotionalSummary.objects.filter(person_id="web_test")
            }
        )()

        assert ("daily", aujourdhui) in lignes
        assert ("weekly", lundi) in lignes, (
            "la passe quotidienne doit entraîner le cumul hebdomadaire"
        )
        assert lignes[("weekly", lundi)].dominant_emotion == "happy"
        assert lignes[("weekly", lundi)].snapshot_count == 3

    @pytest.mark.asyncio
    async def test_le_global_reste_hors_des_resumes(self):
        """``__global__`` est son humeur à elle, pas un interlocuteur — la
        règle valait déjà pour le jour, elle doit tenir pour la semaine."""
        from memory.models import Conversation, EmotionalSummary, EmotionSnapshot

        conversation = await sync_to_async(Conversation.objects.create)()
        await sync_to_async(EmotionSnapshot.objects.create)(
            conversation=conversation, person_id="__global__",
            primary_emotion="happy", primary_intensity=0.7,
            global_emotion="happy", global_intensity=0.7,
        )

        await _consolidator()._aggregate_emotion_snapshots()

        existe = await sync_to_async(
            lambda: EmotionalSummary.objects.filter(person_id="__global__").exists()
        )()
        assert not existe
