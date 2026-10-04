"""Intégrité de l'écriture mémoire — checkpoint, datation, palette, horloge.

Quatre propriétés que rien ne défendait, et dont l'échec est *silencieux* :

- une extraction en panne ne doit pas faire avancer le checkpoint (sinon un
  provider mort de 14h à 18h efface définitivement cet après-midi) ;
- chaque chemin de panne de l'extraction doit laisser une ligne au registre
  de dégradation (seul le JSON illisible était compté) ;
- un souvenir est daté du **vécu**, pas de l'instant d'extraction ;
- l'agrégation émotionnelle date de l'heure **locale**, comme son écrivain et
  comme le lookup ``__date`` qu'elle interroge.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


def _make_consolidator(last_id=0):
    from old.backend.memory.storage.consolidator import MemoryConsolidator

    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c.vector_store = MagicMock()
    c.extractor = MagicMock()
    c.extractor.analyze_messages = AsyncMock(return_value=[])
    c._last_processed_id = last_id
    return c


async def _make_message(conv, content, *, created_at=None, role="user"):
    from old.backend.memory.models import Message

    m = await sync_to_async(Message.objects.create)(
        conversation=conv, role=role, source="frontend", content=content,
        person_id="web_a",
    )
    if created_at is not None:
        await sync_to_async(
            lambda: Message.objects.filter(pk=m.pk).update(created_at=created_at))()
    return m


async def _make_conversation():
    from old.backend.memory.models import Conversation

    return await sync_to_async(Conversation.objects.create)()


# ===================================================================
# S13 — le checkpoint n'enjambe pas une extraction en échec
# ===================================================================

@pytest.mark.django_db(transaction=True)
class TestCheckpointExtraction:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import (
            ConsolidationLog, Connaissance, Conversation, Message, Souvenir,
        )
        Message.objects.all().delete()
        ConsolidationLog.objects.all().delete()
        Souvenir.objects.all().delete()
        Connaissance.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_checkpoint_ne_bouge_pas_quand_l_extraction_echoue(self):
        from old.backend.memory.models import ConsolidationLog

        conv = await _make_conversation()
        await _make_message(conv, "j'ai adopté un chat aujourd'hui")

        c = _make_consolidator()
        c.extractor.analyze_messages = AsyncMock(return_value=None)
        await c._consolidate()

        assert await sync_to_async(ConsolidationLog.objects.count)() == 0
        assert c._last_processed_id == 0

    @pytest.mark.asyncio
    async def test_checkpoint_avance_quand_il_n_y_a_rien_a_extraire(self):
        from old.backend.memory.models import ConsolidationLog

        conv = await _make_conversation()
        m = await _make_message(conv, "salut ça va ?")

        c = _make_consolidator()
        c.extractor.analyze_messages = AsyncMock(return_value=[])
        await c._consolidate()

        assert await sync_to_async(ConsolidationLog.objects.count)() == 1
        assert c._last_processed_id == m.pk

    @pytest.mark.asyncio
    async def test_le_checkpoint_s_arrete_a_la_derniere_tranche_reussie(self, monkeypatch):
        """Une tranche en échec au milieu d'un backlog était indistinguable
        des autres : tout le reste de la fenêtre était réputé traité."""
        import old.backend.memory.storage.consolidator as consolidator_mod
        from old.backend.memory.models import ConsolidationLog

        monkeypatch.setattr(consolidator_mod, "EXTRACTION_MAX_CHARS", 10)

        conv = await _make_conversation()
        m1 = await _make_message(conv, "x" * 20)
        m2 = await _make_message(conv, "y" * 20)

        c = _make_consolidator()
        c.extractor.analyze_messages = AsyncMock(side_effect=[[], None])
        await c._consolidate()

        assert c.extractor.analyze_messages.await_count == 2
        assert c._last_processed_id == m1.pk
        assert c._last_processed_id < m2.pk
        log = await sync_to_async(lambda: ConsolidationLog.objects.order_by("-pk").first())()
        assert log.last_message_id == m1.pk

        # La tranche manquée repart au tick suivant.
        c.extractor.analyze_messages = AsyncMock(return_value=[])
        await c._consolidate()
        assert c._last_processed_id == m2.pk


# ===================================================================
# S18 — chaque panne de transport laisse une trace
# ===================================================================

class TestPannesComptees:

    @pytest.mark.asyncio
    async def test_chaque_chemin_transport_de_l_extraction_est_compte(self):
        import asyncio
        from unittest.mock import patch

        from old.backend.ai.router import UnconfiguredRoleError
        from old.backend.memory.extraction.extractor import MemoryExtractor
        from old.backend.utils.degradation import degradations

        async def _lent(*a, **kw):
            await asyncio.sleep(100)
            return "{}"

        cas = [
            (_lent, "extraction: delai depasse"),
            (UnconfiguredRoleError("aucun modèle"), "extraction: role IA non mappe"),
            ("", "extraction: aucune reponse du modele"),
            (Exception("provider mort"), "extraction: appel IA en echec"),
        ]

        for effet, libelle in cas:
            degradations.reset()
            e = MemoryExtractor()
            e._system_prompt = "S"
            with patch("memory.extraction.extractor._call_timeout", lambda: 0.01):
                if effet == "":
                    with patch("ai.router.ai_router.complete",
                               new_callable=AsyncMock, return_value=""):
                        result = await e.analyze_messages([{"role": "user", "content": "t"}])
                elif callable(effet) and not isinstance(effet, BaseException):
                    with patch.object(e, "_query_model", side_effect=effet):
                        result = await e.analyze_messages([{"role": "user", "content": "t"}])
                else:
                    with patch.object(e, "_query_model",
                                      new_callable=AsyncMock, side_effect=effet):
                        result = await e.analyze_messages([{"role": "user", "content": "t"}])

            assert result is None, libelle
            assert degradations.count_for(libelle) == 1, libelle

        degradations.reset()


# ===================================================================
# S6 — la palette est validée à l'écriture
# ===================================================================

@pytest.mark.django_db(transaction=True)
class TestEmotionDesSouvenirs:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Souvenir
        from old.backend.utils.degradation import degradations
        Souvenir.objects.all().delete()
        degradations.reset()
        yield
        degradations.reset()

    async def _store(self, extraction):
        c = _make_consolidator()
        indexed: list[dict] = []
        c.vector_store.add_souvenir = lambda **kw: indexed.append(kw)
        await c.store_extractions([extraction], interlocutors=[])
        return indexed

    @pytest.mark.asyncio
    async def test_une_emotion_inconnue_se_replie_sur_neutral_et_est_comptee(self):
        from old.backend.memory.models import Souvenir
        from old.backend.utils.degradation import degradations

        await self._store({
            "type": "souvenir", "store": True,
            "content": "j'ai eu très peur", "emotion": "peur bleue",
        })

        s = await sync_to_async(lambda: Souvenir.objects.get())()
        assert s.emotion == "neutral"
        assert degradations.count_for("consolidator: emotion de souvenir inconnue") == 1

    @pytest.mark.asyncio
    async def test_une_emotion_canonique_traverse_intacte(self):
        from old.backend.memory.models import Souvenir
        from old.backend.utils.degradation import degradations

        indexed = await self._store({
            "type": "souvenir", "store": True,
            "content": "un bruit dans le couloir", "emotion": "scared",
        })

        s = await sync_to_async(lambda: Souvenir.objects.get())()
        assert s.emotion == "scared"
        assert indexed and indexed[0]["metadata"]["emotion"] == "scared"
        assert degradations.count_for("consolidator: emotion de souvenir inconnue") == 0

    @pytest.mark.asyncio
    async def test_une_extraction_sans_emotion_ne_compte_pas_de_degradation(self):
        from old.backend.memory.models import Souvenir
        from old.backend.utils.degradation import degradations

        await self._store({
            "type": "souvenir", "store": True, "content": "rien de spécial",
        })

        s = await sync_to_async(lambda: Souvenir.objects.get())()
        assert s.emotion == "neutral"
        assert degradations.count_for("consolidator: emotion de souvenir inconnue") == 0


# ===================================================================
# M6 — un souvenir est daté du vécu
# ===================================================================

@pytest.mark.django_db(transaction=True)
class TestDatationDesSouvenirs:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import ConsolidationLog, Conversation, Message, Souvenir
        Message.objects.all().delete()
        ConsolidationLog.objects.all().delete()
        Souvenir.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_le_souvenir_est_date_du_vecu_pas_de_l_extraction(self):
        from old.backend.memory.models import Souvenir

        hier_20h = timezone.now() - timedelta(days=1)
        conv = await _make_conversation()
        await _make_message(conv, "on a joué à Zelda", created_at=hier_20h)

        c = _make_consolidator()
        c.extractor.analyze_messages = AsyncMock(return_value=[
            {"type": "souvenir", "store": True,
             "content": "On a passé la soirée sur Zelda", "emotion": "happy"},
        ])
        await c._consolidate()

        s = await sync_to_async(lambda: Souvenir.objects.get())()
        assert abs((s.occurred_at - hier_20h).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_la_metadonnee_chroma_porte_la_meme_date(self):
        from old.backend.memory.models import Souvenir

        hier = timezone.now() - timedelta(days=1)
        conv = await _make_conversation()
        await _make_message(conv, "on a joué à Zelda", created_at=hier)

        c = _make_consolidator()
        indexed: list[dict] = []
        c.vector_store.add_souvenir = lambda **kw: indexed.append(kw)
        c.extractor.analyze_messages = AsyncMock(return_value=[
            {"type": "souvenir", "store": True, "content": "Zelda", "emotion": "happy"},
        ])
        await c._consolidate()

        s = await sync_to_async(lambda: Souvenir.objects.get())()
        assert indexed and indexed[0]["metadata"]["occurred_at"] == s.occurred_at.isoformat()


# ===================================================================
# M5 — une seule horloge dans le consolidateur
# ===================================================================

@pytest.mark.django_db(transaction=True)
class TestHorlogeDuConsolidateur:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Conversation, EmotionalSummary, EmotionSnapshot
        EmotionSnapshot.objects.all().delete()
        EmotionalSummary.objects.all().delete()
        Conversation.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_l_agregation_emotionnelle_utilise_l_horloge_locale(self, monkeypatch):
        """22h30 UTC = le lendemain 00h30 à Paris.

        Le relevé est rangé par le lookup ``created_at__date`` en heure
        LOCALE (le 10), et la passe cherchait la date UTC (le 09) : aucune
        ligne quotidienne n'était écrite pendant les deux premières heures de
        la journée locale, celles-là même que ses lecteurs interrogent.
        """
        import old.backend.memory.storage.consolidator as consolidator_mod
        from django.utils import timezone as dj_timezone
        from old.backend.memory.models import Conversation, EmotionalSummary, EmotionSnapshot

        instant = datetime(2026, 8, 9, 22, 30, tzinfo=dt_timezone.utc)
        monkeypatch.setattr(dj_timezone, "now", lambda: instant)

        class _DateStub:
            @staticmethod
            def today():
                return date(2026, 8, 10)

        monkeypatch.setattr(consolidator_mod, "date", _DateStub)

        with dj_timezone.override("Europe/Paris"):
            conversation = await sync_to_async(Conversation.objects.create)()
            await sync_to_async(EmotionSnapshot.objects.create)(
                conversation=conversation, person_id="web_test",
                primary_emotion="happy", primary_intensity=0.7,
                global_emotion="happy", global_intensity=0.7,
            )

            await _make_consolidator()._aggregate_emotion_snapshots()

            lignes = await sync_to_async(
                lambda: [
                    (s.period_type, s.period_start)
                    for s in EmotionalSummary.objects.filter(person_id="web_test")
                ]
            )()

        assert ("daily", date(2026, 8, 10)) in lignes

    def test_une_seule_horloge_dans_le_consolidateur(self):
        """``timezone.now().date()`` est la date UTC ; le reste du moteur date
        de ``date.today()`` (heure locale naïve), comme l'exige l'invariant
        « une horloge »."""
        import inspect

        from old.backend.memory.storage import consolidator

        src = inspect.getsource(consolidator)
        assert "timezone.now().date()" not in src
        assert "timezone.localdate(" not in src
