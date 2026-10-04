"""Tests for MemoryRetriever — reranking, formatting, time helpers."""

import pytest
from collections import deque
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone


def _make_retriever():
    from old.backend.memory.retrieval.retriever import MemoryRetriever
    return MemoryRetriever(MagicMock())


# ===================================================================
# _rerank_souvenirs
# ===================================================================

class TestRerankSouvenirs:

    def test_last_hour_gets_recency_boost(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": timezone.now() - timedelta(minutes=30), "entities": []}
        result = r._rerank_souvenirs([s], "")
        assert result[0]["_score"] > 0.5  # 0.5 * 1.5

    def test_old_souvenir_no_boost(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": timezone.now() - timedelta(days=30), "entities": []}
        result = r._rerank_souvenirs([s], "")
        assert result[0]["_score"] == pytest.approx(0.5)

    def test_person_id_boost(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": None, "entities": ["alice"]}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] == pytest.approx(0.7)  # 0.5 * 1.4

    def test_person_id_case_insensitive(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": None, "entities": ["ALICE"]}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] > 0.5

    def test_person_id_no_partial_match(self):
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.5, "occurred_at": None, "entities": ["alicia"]}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] == pytest.approx(0.5)  # No boost — exact match only

    def test_sorted_descending(self):
        r = _make_retriever()
        souvenirs = [
            {"content": "a", "relevance": 0.2, "occurred_at": None, "entities": []},
            {"content": "b", "relevance": 0.8, "occurred_at": None, "entities": []},
            {"content": "c", "relevance": 0.5, "occurred_at": None, "entities": []},
        ]
        result = r._rerank_souvenirs(souvenirs, "")
        scores = [s["_score"] for s in result]
        assert scores == sorted(scores, reverse=True)

    def test_no_cap_so_salience_ordering_survives(self):
        """L'ancien plafond à 1.0 saturait : deux souvenirs très bien classés
        finissaient tous deux à 1.0, écrasant justement les écarts. Le score
        n'est qu'une clé de tri — plus de plafond, l'ordre reflète la saillance."""
        r = _make_retriever()
        s = {"content": "x", "relevance": 0.9,
             "occurred_at": timezone.now() - timedelta(minutes=5),
             "entities": ["alice"], "importance": 1.0, "emotion": "love"}
        result = r._rerank_souvenirs([s], "alice")
        assert result[0]["_score"] > 1.0  # n'est plus écrêté


# ===================================================================
# _time_ago
# ===================================================================

class TestTimeAgo:

    def _t(self, dt):
        from old.backend.memory.retrieval.retriever import MemoryRetriever
        return MemoryRetriever._time_ago(dt)

    def test_none(self):
        assert self._t(None) == "?"

    def test_minutes(self):
        assert self._t(timezone.now() - timedelta(minutes=20)) == "il y a quelques minutes"

    def test_hours(self):
        assert "5h" in self._t(timezone.now() - timedelta(hours=5))

    def test_yesterday(self):
        assert self._t(timezone.now() - timedelta(days=1)) == "hier"

    def test_days(self):
        assert "3 jours" in self._t(timezone.now() - timedelta(days=3))

    def test_weeks(self):
        result = self._t(timezone.now() - timedelta(days=14))
        assert "semaine" in result

    def test_months(self):
        assert "mois" in self._t(timezone.now() - timedelta(days=60))


# ===================================================================
# _confidence_label
# ===================================================================

class TestConfidenceLabel:

    def _l(self, c):
        from old.backend.memory.retrieval.retriever import MemoryRetriever
        return MemoryRetriever._confidence_label(c)

    def test_certain(self):
        assert self._l(0.9) == "certain"
        assert self._l(0.8) == "certain"

    def test_probable(self):
        assert self._l(0.7) == "probable"
        assert self._l(0.5) == "probable"

    def test_incertain(self):
        assert self._l(0.3) == "incertain"
        assert self._l(0.0) == "incertain"


# ===================================================================
# _format_context
# ===================================================================

class TestFormatContext:

    def test_header_footer_only_when_there_is_something_to_say(self):
        """Le pin change volontairement : un bloc réduit à son entête est le
        même défaut que « [Quelque chose te revient] » suivi de rien, un cran
        au-dessus — l'encadrement annonce des souvenirs et n'en montre aucun."""
        r = _make_retriever()
        assert r._format_context([], []) == ""

        result = r._format_context(
            [{"content": "Thomas aime le café", "confidence": 0.9,
              "entities": [], "themes": []}],
            [],
        )
        assert "--- TES SOUVENIRS ---" in result
        assert "--- FIN SOUVENIRS ---" in result

    def test_connaissance_in_output(self):
        r = _make_retriever()
        result = r._format_context(
            [{"content": "Thomas aime le café", "confidence": 0.9, "entities": [], "themes": []}],
            []
        )
        assert "Thomas aime le café" in result
        assert "certain" in result

    def test_souvenir_in_output(self):
        r = _make_retriever()
        result = r._format_context([], [{
            "content": "On a joué à Zelda",
            "emotion": "happy",
            "occurred_at": timezone.now() - timedelta(hours=2),
            "entities": [], "themes": [], "importance": 0.8,
        }])
        assert "Zelda" in result
        assert "happy" in result

    def test_output_respects_max_chars(self):
        r = _make_retriever()
        souvenirs = [
            {"content": "x" * 300, "emotion": "neutral", "occurred_at": None,
             "entities": [], "themes": [], "importance": 0.8}
            for _ in range(50)
        ]
        result = r._format_context([], souvenirs)
        assert len(result) <= r.MAX_CONTEXT_CHARS + 200


# ===================================================================
# retrieve — empty store
# ===================================================================

class TestRetrieve:

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_string(self):
        # Le pin change : le retriever ne lit plus `settings` depuis le
        # passage à config_service, donc patcher `retriever.settings` ne
        # patchait plus rien et le vrai `config_service.get` touchait la base
        # sans marque django_db — un échec qui dépendait de l'ordre des tests.
        from old.backend.memory.retrieval.retriever import MemoryRetriever
        mock_store = MagicMock()
        mock_store.search_souvenirs = MagicMock(return_value=[])
        mock_store.search_connaissances = MagicMock(return_value=[])

        vals = {
            "memory.retrieval_souvenirs": 5,
            "memory.retrieval_connaissances": 5,
            "memory.min_importance": 0.3,
            "memory.retrieval_fetch_multiplier": 3,
            "memory.retrieval_exchanges": 0,
        }
        with patch("configs.service.config_service.get",
                   lambda k, *a, **kw: vals.get(k, 0)):
            r = MemoryRetriever(mock_store)
            result = await r.retrieve("quelque chose", person_id="u1")

        assert result == ""


# ===================================================================
# _episodic_lane — la frontière de CONFIDENTIALITÉ de la voie chaude.
#
# Invariant : le rappel épisodique du tour ne remonte QUE les échanges de
# l'identité de l'interlocuteur. Le rappel inter-personnes est réservé aux
# consommateurs internes (conscience, planificateur), jamais au prompt de
# conversation. Sans ces tests, retirer `handles=` de la lane (une fuite du
# verbatim d'autrui dans le prompt) passait toute la suite au vert.
# ===================================================================

class TestEpisodicLanePrivacy:

    async def test_lane_scopes_search_to_the_interlocutors_handles(self):
        r = _make_retriever()
        captured = {}

        async def _fake_search(query, **kwargs):
            captured.update(kwargs)
            return []

        with patch("identity.resolver.identity_resolver.handles_for_person",
                   AsyncMock(return_value=[
                       {"person_id": "web_a"}, {"person_id": "tg_1"},
                   ])), \
             patch("memory.episodic.api.search_exchanges",
                   AsyncMock(side_effect=_fake_search)):
            await r._episodic_lane("le projet", "web_a")

        # Exactement les handles de l'identité, jamais un ensemble élargi.
        assert captured.get("handles") == ["tg_1", "web_a"]

    async def test_unbound_visitor_is_scoped_to_its_own_handle(self):
        r = _make_retriever()
        captured = {}

        async def _fake_search(query, **kwargs):
            captured.update(kwargs)
            return []

        with patch("identity.resolver.identity_resolver.handles_for_person",
                   AsyncMock(return_value=[])), \
             patch("memory.episodic.api.search_exchanges",
                   AsyncMock(side_effect=_fake_search)):
            await r._episodic_lane("q", "web_inconnu")

        assert captured.get("handles") == ["web_inconnu"]

    async def test_internal_person_never_touches_the_episodic_store(self):
        r = _make_retriever()
        search = AsyncMock(return_value=[])
        with patch("memory.episodic.api.search_exchanges", search):
            out = await r._episodic_lane("q", "conscience_mika")
        assert out == []
        search.assert_not_called()

    async def test_disabled_by_config_returns_empty(self):
        r = _make_retriever()
        search = AsyncMock(return_value=[])
        with patch("configs.service.config_service.get", return_value=0), \
             patch("memory.episodic.api.search_exchanges", search):
            out = await r._episodic_lane("q", "web_a")
        assert out == []
        search.assert_not_called()


# ===================================================================
# Saillance du rappel — importance + charge émotionnelle + humeur.
# L'axe qui rend le rappel humain : « ce qui a compté » remonte, pas
# seulement « ce qui ressemble ». Helpers purs + effet sur le classement.
# ===================================================================

class TestSalienceHelpers:

    def test_emotional_charge_neutral_is_zero(self):
        from old.backend.memory.retrieval.retriever import _emotional_charge
        assert _emotional_charge("neutral") == 0.0
        assert _emotional_charge("inconnu") == 0.0

    def test_emotional_charge_strong_emotions_are_high(self):
        from old.backend.memory.retrieval.retriever import _emotional_charge
        assert _emotional_charge("scared") > 0.5
        assert _emotional_charge("love") > 0.5

    def test_mood_congruence_same_direction_high_opposite_low(self):
        from old.backend.emotion import pad
        from old.backend.emotion.types import Emotion
        from old.backend.memory.retrieval.retriever import _mood_congruence
        happy_mood = pad.EMOTION_ANCHORS[Emotion.HAPPY]
        assert _mood_congruence(happy_mood, "happy") > 0.8
        assert _mood_congruence(happy_mood, "sad") < 0.2

    def test_mood_congruence_neutral_has_no_effect(self):
        from old.backend.memory.retrieval.retriever import _mood_congruence
        assert _mood_congruence((0.0, 0.0, 0.0), "happy") == 0.5  # humeur neutre
        assert _mood_congruence(None, "happy") == 0.5             # pas d'humeur
        assert _mood_congruence((0.5, 0.5, 0.5), "neutral") == 0.5  # émotion neutre


class TestSalienceRanking:

    def _s(self, **kw):
        base = {"content": "x", "relevance": 0.5, "occurred_at": None,
                "entities": [], "importance": 0.0, "emotion": "neutral"}
        base.update(kw)
        return base

    def test_importance_promotes_at_equal_relevance(self):
        r = _make_retriever()
        bland = self._s(importance=0.0)
        weighty = self._s(importance=1.0)
        out = r._rerank_souvenirs([bland, weighty], "")
        assert out[0] is weighty

    def test_emotional_charge_promotes_at_equal_relevance(self):
        r = _make_retriever()
        flat = self._s(emotion="neutral")
        charged = self._s(emotion="scared")
        out = r._rerank_souvenirs([flat, charged], "")
        assert out[0] is charged

    def test_a_salient_memory_outranks_a_more_relevant_bland_one(self):
        """Le cœur de l'axe : un souvenir marquant mais lexicalement moins
        proche peut passer devant un souvenir banal mieux matché."""
        r = _make_retriever()
        bland_but_relevant = self._s(relevance=0.9, importance=0.0, emotion="neutral")
        salient_but_distant = self._s(relevance=0.6, importance=1.0, emotion="love")
        out = r._rerank_souvenirs([bland_but_relevant, salient_but_distant], "")
        assert out[0] is salient_but_distant

    def test_zero_weights_reproduce_the_old_behaviour(self):
        from old.backend.memory.retrieval.retriever import _SalienceWeights
        r = _make_retriever()
        w = _SalienceWeights(importance=0.0, emotion=0.0, mood=0.0)
        s = self._s(relevance=0.5, importance=1.0, emotion="love")
        out = r._rerank_souvenirs([s], "", weights=w)
        assert out[0]["_score"] == pytest.approx(0.5)  # que la pertinence

    def test_mood_congruence_boosts_congruent_memories(self):
        from old.backend.emotion import pad
        from old.backend.emotion.types import Emotion
        from old.backend.memory.retrieval.retriever import _SalienceWeights
        r = _make_retriever()
        w = _SalienceWeights(importance=0.0, emotion=0.0, mood=0.5)
        happy_mood = pad.EMOTION_ANCHORS[Emotion.HAPPY]
        happy_mem = self._s(emotion="happy")
        sad_mem = self._s(emotion="sad")
        out = r._rerank_souvenirs([sad_mem, happy_mem], "", mood_pad=happy_mood, weights=w)
        assert out[0] is happy_mem

    def test_negative_mood_damps_congruence_against_spirals(self):
        from old.backend.emotion import pad
        from old.backend.emotion.types import Emotion
        from old.backend.memory.retrieval.retriever import _SalienceWeights
        r = _make_retriever()
        w = _SalienceWeights(importance=0.0, emotion=0.0, mood=0.5, mood_negative_damp=0.5)
        sad_mood = pad.EMOTION_ANCHORS[Emotion.SAD]  # pleasure < 0
        # même souvenir triste : le pull est amorti quand l'humeur est négative.
        full = r._rerank_souvenirs([self._s(emotion="sad")], "",
                                   mood_pad=sad_mood, weights=w)[0]["_score"]
        w_no_damp = _SalienceWeights(importance=0.0, emotion=0.0, mood=0.5, mood_negative_damp=1.0)
        undamped = r._rerank_souvenirs([self._s(emotion="sad")], "",
                                       mood_pad=sad_mood, weights=w_no_damp)[0]["_score"]
        assert full < undamped  # l'amortissement réduit bien le pull


class TestSalienceWiring:

    def test_salience_boost_scales_emotion_and_mood_weights(self):
        r = _make_retriever()
        base = r._salience_weights(boost=0.0)
        boosted = r._salience_weights(boost=1.0)
        assert boosted.emotion == pytest.approx(base.emotion * 2)
        assert boosted.mood == pytest.approx(base.mood * 2)
        # l'importance ne dépend pas de la charge du tour
        assert boosted.importance == pytest.approx(base.importance)

    def test_mood_pad_for_is_side_effect_free_and_skips_internal(self):
        r = _make_retriever()
        # personne interne → jamais d'humeur (et jamais de création d'oscillateur)
        assert r._mood_pad_for("conscience_mika") is None
        assert r._mood_pad_for("") is None


# ===================================================================
# Rappels non-lexicaux — ce que le cosinus ne trouve jamais.
#   · expansion associative « ça me rappelle… » (ancrée, sûre, défaut ON)
#   · intrusion d'un souvenir intense (opt-in, gated sur la charge du tour)
# ===================================================================

async def _sync(fn, *a):
    from asgiref.sync import sync_to_async
    return await sync_to_async(fn)(*a)


@pytest.mark.django_db(transaction=True)
class TestAssociativeExpansion:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Entity, Souvenir, Theme
        Souvenir.objects.all().delete()
        Theme.objects.all().delete()
        Entity.objects.all().delete()
        yield

    def _cfg(self, monkeypatch, **over):
        vals = {
            "memory.assoc_expansion_enabled": True,
            "memory.assoc_expansion_max": 2,
            "memory.assoc_min_importance": 0.5,
        }
        vals.update(over)
        monkeypatch.setattr("configs.service.config_service.get",
                            lambda k, *a, **kw: vals.get(k, 0))

    async def _souvenir(self, content, importance, theme=None):
        from django.utils import timezone
        from old.backend.memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content=content, importance=importance, occurred_at=timezone.now())
        if theme is not None:
            await _sync(s.themes.add, theme)
        return s

    async def test_links_a_thematically_related_memory(self, monkeypatch):
        from old.backend.memory.models import Theme
        self._cfg(monkeypatch)
        r = _make_retriever()
        theme = await Theme.objects.acreate(name="espace")
        anchor = await self._souvenir("on a parlé de la fusée", 0.7, theme)
        linked = await self._souvenir("le rêve d'être astronaute", 0.8, theme)
        out = await r._associative_expansion(
            [{"id": anchor.pk, "themes": ["espace"], "entities": []}], {anchor.pk},
        )
        assert [s["id"] for s in out] == [linked.pk]

    async def test_low_importance_link_is_filtered(self, monkeypatch):
        from old.backend.memory.models import Theme
        self._cfg(monkeypatch)
        r = _make_retriever()
        theme = await Theme.objects.acreate(name="espace")
        anchor = await self._souvenir("la fusée", 0.7, theme)
        await self._souvenir("détail sans importance", 0.2, theme)  # < 0.5
        out = await r._associative_expansion(
            [{"id": anchor.pk, "themes": ["espace"], "entities": []}], {anchor.pk},
        )
        assert out == []

    async def test_already_retrieved_is_not_resurfaced(self, monkeypatch):
        from old.backend.memory.models import Theme
        self._cfg(monkeypatch)
        r = _make_retriever()
        theme = await Theme.objects.acreate(name="espace")
        anchor = await self._souvenir("la fusée", 0.7, theme)
        other = await self._souvenir("astronaute", 0.8, theme)
        out = await r._associative_expansion(
            [{"id": anchor.pk, "themes": ["espace"], "entities": []}],
            {anchor.pk, other.pk},   # les deux déjà dans le résultat
        )
        assert out == []

    async def test_disabled_returns_empty(self, monkeypatch):
        from old.backend.memory.models import Theme
        self._cfg(monkeypatch, **{"memory.assoc_expansion_enabled": False})
        r = _make_retriever()
        theme = await Theme.objects.acreate(name="espace")
        anchor = await self._souvenir("la fusée", 0.7, theme)
        await self._souvenir("astronaute", 0.8, theme)
        out = await r._associative_expansion(
            [{"id": anchor.pk, "themes": ["espace"], "entities": []}], {anchor.pk},
        )
        assert out == []


@pytest.mark.django_db(transaction=True)
class TestImportanceIntrusion:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Souvenir
        Souvenir.objects.all().delete()
        yield

    def _cfg(self, monkeypatch, **over):
        vals = {
            "memory.intrusion_enabled": True,
            "memory.intrusion_charge_threshold": 0.6,
            "memory.intrusion_min_importance": 0.85,
        }
        vals.update(over)
        monkeypatch.setattr("configs.service.config_service.get",
                            lambda k, *a, **kw: vals.get(k, 0))

    async def _souvenir(self, content, importance, emotion="neutral"):
        from django.utils import timezone
        from old.backend.memory.models import Souvenir
        return await Souvenir.objects.acreate(
            content=content, importance=importance, emotion=emotion,
            occurred_at=timezone.now())

    async def test_off_by_default_even_on_a_charged_turn(self, monkeypatch):
        # Défaut du produit : la clef n'est pas activée.
        self._cfg(monkeypatch, **{"memory.intrusion_enabled": False})
        r = _make_retriever()
        await self._souvenir("le grand drame", 0.95, "sad")
        assert await r._importance_intrusion(set(), salience_boost=0.9) == []

    async def test_does_not_fire_on_a_cold_turn(self, monkeypatch):
        self._cfg(monkeypatch)
        r = _make_retriever()
        await self._souvenir("le grand drame", 0.95, "sad")
        assert await r._importance_intrusion(set(), salience_boost=0.3) == []

    async def test_fires_on_a_charged_turn_when_enabled(self, monkeypatch):
        self._cfg(monkeypatch)
        r = _make_retriever()
        s = await self._souvenir("le grand drame", 0.95, "sad")
        out = await r._importance_intrusion(set(), salience_boost=0.9)
        assert [x["id"] for x in out] == [s.pk]

    async def test_picks_the_most_burning_among_the_important(self, monkeypatch):
        self._cfg(monkeypatch)
        r = _make_retriever()
        await self._souvenir("fait marquant mais froid", 0.9, "neutral")
        burning = await self._souvenir("souvenir bouleversant", 0.9, "scared")
        out = await r._importance_intrusion(set(), salience_boost=0.9)
        assert [x["id"] for x in out] == [burning.pk]  # importance × (1+charge)

    async def test_respects_min_importance_and_exclusions(self, monkeypatch):
        self._cfg(monkeypatch)
        r = _make_retriever()
        weak = await self._souvenir("pas assez important", 0.7, "scared")  # < 0.85
        strong = await self._souvenir("assez important", 0.9, "sad")
        assert await r._importance_intrusion({strong.pk}, 0.9) == []  # exclu → rien d'éligible
        _ = weak


# ===================================================================
# Souvenir fantôme — l'entrée ChromaDB dont la ligne ORM a disparu.
#
# `_load_by_pk` distingue « le chargement a échoué » (None) de « la ligne
# n'existe plus » (absente du dict). `_enrich_souvenirs` confondait les deux
# et repliait sur ChromaDB dans les deux cas : un souvenir effacé (décroissance,
# fusion) était donc reservi pour toujours, importance figée — l'oubli décidé
# devenait inoubliable. `_enrich_connaissances` traitait déjà le cas
# correctement ; c'est l'asymétrie qui EST le bug.
# ===================================================================

class TestSouvenirFantome:

    def _hit(self, pk, content="souvenir efface"):
        return {"id": str(pk), "content": content, "distance": 0.2,
                "metadata": {"emotion": "happy", "importance": 0.95}}

    @pytest.mark.asyncio
    async def test_loaded_but_missing_pk_is_dropped_and_evicted(self):
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock()
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value={})):
            out = await r._enrich_souvenirs([self._hit(4242)])

        assert out == []
        r.vector_store.remove_souvenir.assert_called_once_with(4242)

    @pytest.mark.asyncio
    async def test_failed_load_keeps_the_chromadb_fallback(self):
        """Une base verrouillée ne doit pas déclencher un nettoyage vectoriel."""
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock()
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value=None)):
            out = await r._enrich_souvenirs([self._hit(4242)])

        assert [s["id"] for s in out] == [4242]
        r.vector_store.remove_souvenir.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_numeric_id_keeps_the_fallback(self):
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock()
        hit = {"id": "pas-un-pk", "content": "x", "metadata": {}}
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value={})):
            out = await r._enrich_souvenirs([hit])

        assert [s["content"] for s in out] == ["x"]
        r.vector_store.remove_souvenir.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failing_eviction_is_counted_not_raised(self):
        from old.backend.utils.degradation import degradations
        degradations.reset()
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock(side_effect=RuntimeError("chroma"))
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value={})):
            out = await r._enrich_souvenirs([self._hit(7)])

        assert out == []
        assert degradations.count_for("rappel: retrait souvenir fantome") == 1
        degradations.reset()

    @pytest.mark.asyncio
    async def test_souvenirs_and_connaissances_agree_on_a_deleted_row(self):
        """Symétrie : « pk absent après un chargement réussi » se traite de la
        même façon des deux côtés. L'asymétrie était le défaut."""
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock()
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value={})):
            souvenirs = await r._enrich_souvenirs([self._hit(1)])
            connaissances = await r._enrich_connaissances([self._hit(1)])

        assert souvenirs == [] and connaissances == []


# ===================================================================
# Anti-répétition — les deux voies non-lexicales sont déterministes, donc
# « ça me rappelle… » se répétait mot pour mot d'un tour à l'autre.
# ===================================================================

class TestAntiRepetition:

    def _s(self, pk, **kw):
        base = {"id": pk, "content": "x", "relevance": 0.5, "occurred_at": None,
                "entities": [], "importance": 0.0, "emotion": "neutral"}
        base.update(kw)
        return base

    def test_demoted_memory_falls_behind_an_equivalent_one(self):
        r = _make_retriever()
        frais, deja_vu = self._s(1), self._s(2)
        out = r._rerank_souvenirs([deja_vu, frais], "", demote_pks={2})
        assert out[0] is frais
        assert out[1]["_score"] < out[0]["_score"]

    def test_memo_unions_the_last_turns_and_forgets_the_oldest(self):
        from old.backend.memory.retrieval.retriever import RECALL_MEMO_TURNS
        r = _make_retriever()
        for tour in range(RECALL_MEMO_TURNS):
            with patch("pipeline.tracing.get_request_id", return_value=f"r{tour}"):
                r._noter_servis("web_a", {tour})
        assert r._deja_servis("web_a") == set(range(RECALL_MEMO_TURNS))

        with patch("pipeline.tracing.get_request_id", return_value="rN"):
            r._noter_servis("web_a", {99})
        assert 0 not in r._deja_servis("web_a")
        assert 99 in r._deja_servis("web_a")

    def test_two_recalls_of_one_turn_consume_a_single_bucket(self):
        """Un tour réel lance deux rappels (spéculatif puis dirigé) : sans la
        fusion sur le request_id, un seul tour viderait le mémo."""
        r = _make_retriever()
        with patch("pipeline.tracing.get_request_id", return_value="abc123"):
            r._noter_servis("web_a", {1})
            r._noter_servis("web_a", {2})
        assert len(r._servis["web_a"]) == 1
        assert r._deja_servis("web_a") == {1, 2}

    def test_memo_is_bounded_by_an_lru(self):
        from old.backend.memory.retrieval.retriever import RECALL_MEMO_MAX_PERSONS
        r = _make_retriever()
        for i in range(RECALL_MEMO_MAX_PERSONS + 5):
            r._noter_servis(f"web_{i}", {i})
        assert len(r._servis) == RECALL_MEMO_MAX_PERSONS
        assert r._deja_servis("web_0") == set()

    def test_unknown_person_has_no_memo(self):
        r = _make_retriever()
        assert r._deja_servis("jamais_vu") == set()

    @pytest.mark.asyncio
    async def test_retrieve_multi_feeds_the_memo_to_both_lanes(self):
        """Le câblage : le mémo démote la voie directe ET exclut durement les
        deux voies « surprise », puis ce qui vient d'être servi est noté."""
        from old.backend.memory.retrieval.retriever import MemoryRetriever

        store = MagicMock()
        store.search_souvenirs = MagicMock(return_value=[
            {"id": "7", "content": "déjà dit", "distance": 0.1, "metadata": {}},
        ])
        store.search_connaissances = MagicMock(return_value=[])
        r = MemoryRetriever(store)
        r._servis["web_a"] = deque([("r0", {7, 42})], maxlen=3)

        vus = {}

        def _rerank(souvenirs, boost_name, **kw):
            vus["demote"] = kw.get("demote_pks")
            return souvenirs

        async def _assoc(souvenirs, exclude_pks, **_kw):
            vus["assoc_exclude"] = set(exclude_pks)
            return []

        async def _intru(exclude_pks, boost, **_kw):
            vus["intru_exclude"] = set(exclude_pks)
            return []

        vals = {
            "memory.retrieval_souvenirs": 5,
            "memory.retrieval_connaissances": 5,
            "memory.min_importance": 0.3,
            "memory.retrieval_fetch_multiplier": 3,
            "memory.retrieval_exchanges": 0,
        }
        # Une clé non modélisée rend le défaut que l'appelant a déclaré, pas 0 :
        # les réglages de l'anti-répétition (`memory.recall_*`) passent par
        # `configs.runtime`, qui transmet toujours son repli en `default=`, et
        # un 0 forfaitaire y ferait passer la démotion pour une exclusion.
        with patch("configs.service.config_service.get",
                   lambda k, *a, **kw: vals.get(k, kw.get("default", 0))), \
             patch.object(r, "_enrich_souvenirs",
                          AsyncMock(return_value=[{"id": 7, "content": "déjà dit"}])), \
             patch.object(r, "_enrich_connaissances", AsyncMock(return_value=[])), \
             patch.object(r, "_person_boost_name", AsyncMock(return_value="")), \
             patch.object(r, "_rerank_souvenirs", _rerank), \
             patch.object(r, "_associative_expansion", _assoc), \
             patch.object(r, "_importance_intrusion", _intru):
            await r.retrieve_multi(["une question"], person_id="web_a")

        # La voie directe reçoit désormais des FACTEURS gradués par
        # l'ancienneté du service, plus un ensemble plat : à égalité de
        # pénalité l'ordre ne bougeait pas, donc le bloc sortait identique
        # d'un tour à l'autre. Les deux voies non-lexicales, elles, restent
        # sur une exclusion dure.
        assert set(vus["demote"]) == {7, 42}
        assert all(0 < f < 1 for f in vus["demote"].values())
        assert {7, 42} <= vus["assoc_exclude"]
        assert {7, 42} <= vus["intru_exclude"]
        assert 7 in r._deja_servis("web_a")

    async def test_la_penalite_s_attenue_avec_la_distance_en_tours(self):
        """Ce qu'elle vient de dire recule plus que ce qu'elle a dit avant."""
        from old.backend.memory.retrieval.retriever import MemoryRetriever

        r = MemoryRetriever(MagicMock())
        r._servis["web_a"] = deque(
            [("r0", {1}), ("r1", {2}), ("r2", {3})], maxlen=3)
        p = r._penalites_repetition("web_a")
        assert p[3] < p[2] < p[1], "le plus récemment servi doit reculer le plus"
        assert p[1] <= 1.0


@pytest.mark.django_db(transaction=True)
class TestAntiRepetitionSurLesVoiesSurprise:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Entity, Souvenir, Theme
        Souvenir.objects.all().delete()
        Theme.objects.all().delete()
        Entity.objects.all().delete()
        yield

    def _cfg(self, monkeypatch, **over):
        vals = {
            "memory.assoc_expansion_enabled": True,
            "memory.assoc_expansion_max": 2,
            "memory.assoc_min_importance": 0.5,
            "memory.intrusion_enabled": True,
            "memory.intrusion_charge_threshold": 0.6,
            "memory.intrusion_min_importance": 0.85,
        }
        vals.update(over)
        monkeypatch.setattr("configs.service.config_service.get",
                            lambda k, *a, **kw: vals.get(k, 0))

    async def _souvenir(self, content, importance, theme=None, emotion="neutral"):
        from django.utils import timezone
        from old.backend.memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content=content, importance=importance, emotion=emotion,
            occurred_at=timezone.now())
        if theme is not None:
            await _sync(s.themes.add, theme)
        return s

    async def test_the_same_association_is_not_served_twice(self, monkeypatch):
        from old.backend.memory.models import Theme
        self._cfg(monkeypatch)
        r = _make_retriever()
        theme = await Theme.objects.acreate(name="espace")
        anchor = await self._souvenir("la fusée", 0.7, theme)
        linked = await self._souvenir("le rêve d'être astronaute", 0.8, theme)
        hits = [{"id": anchor.pk, "themes": ["espace"], "entities": []}]

        premier = await r._associative_expansion(hits, {anchor.pk})
        assert [s["id"] for s in premier] == [linked.pk]
        r._noter_servis("web_a", {anchor.pk, linked.pk})

        second = await r._associative_expansion(
            hits, {anchor.pk} | r._deja_servis("web_a"),
        )
        assert second == []

    async def test_the_same_intrusion_does_not_impose_itself_twice(self, monkeypatch):
        self._cfg(monkeypatch)
        r = _make_retriever()
        brulant = await self._souvenir("le grand drame", 0.95, emotion="sad")

        premier = await r._importance_intrusion(set(), salience_boost=0.9)
        assert [x["id"] for x in premier] == [brulant.pk]
        r._noter_servis("web_a", {brulant.pk})

        second = await r._importance_intrusion(r._deja_servis("web_a"), 0.9)
        assert second == []


# ===================================================================
# Entêtes de section vides — « [Quelque chose te revient] » suivi de RIEN
# est, sur petit modèle, une invitation à confabuler le souvenir manquant.
# ===================================================================

class TestEntetesVides:

    TITRES = [
        "[Ce que tu sais]", "[Tes souvenirs vecus]", "[Ça t'évoque aussi]",
        "[Echanges recents (mot pour mot)]", "[Quelque chose te revient]",
    ]

    def _souvenir(self, content):
        return {"content": content, "emotion": "neutral", "occurred_at": None,
                "entities": [], "themes": [], "importance": 0.5}

    def _echange(self, content):
        return type("Hit", (), {"ts": 0, "content": content})()

    def _appel(self, r, cap):
        return r._format_context(
            [{"content": "C" * 400, "confidence": 0.9, "entities": [], "themes": []}],
            [self._souvenir("S" * 400)],
            exchanges=[self._echange("E" * 400)],
            associations=[self._souvenir("A" * 400)],
            intrusions=[self._souvenir("I" * 400)],
            max_chars=cap,
        )

    def test_no_title_ever_appears_without_a_line_under_it(self):
        r = _make_retriever()
        out = self._appel(r, 460)
        for titre in self.TITRES:
            if titre in out:
                suite = out.split(titre, 1)[1].lstrip("\n")
                assert suite.startswith("  - "), f"{titre} sans contenu"

    def test_an_intrusion_that_does_not_fit_takes_its_title_with_it(self):
        r = _make_retriever()
        assert "[Quelque chose te revient]" not in self._appel(r, 460)

    def test_a_partially_fitting_section_keeps_its_title(self):
        r = _make_retriever()
        out = r._format_context(
            [], [self._souvenir("S" * 100) for _ in range(5)], max_chars=300,
        )
        assert "[Tes souvenirs vecus]" in out
        assert out.count("  - ") >= 1

    def test_everything_cut_yields_no_block_at_all(self):
        r = _make_retriever()
        assert self._appel(r, 30) == ""

    def test_the_cap_is_not_exceeded_by_the_size_of_a_title(self):
        r = _make_retriever()
        out = self._appel(r, 460)
        assert len(out) <= 460 + len("\n--- FIN SOUVENIRS ---")


# ===================================================================
# Frontière intime — ce qui ne sort PAS sous le seuil de divulgation.
#
# Trois fuites, toutes vérifiées empiriquement : (1) le filtre gardait un
# souvenir partagé avec un tiers dès que l'interlocuteur y figurait aussi ;
# (2) ni les connaissances ni la voie épisodique n'avaient de porte ;
# (3) une base en panne repliait sur ChromaDB brut, en contournant le filtre.
# ===================================================================

@pytest.mark.django_db(transaction=True)
class TestFrontiereIntime:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from old.backend.memory.models import Connaissance, Entity, Souvenir
        Souvenir.objects.all().delete()
        Connaissance.objects.all().delete()
        Entity.objects.all().delete()
        yield

    async def _personne(self, nom):
        from old.backend.memory.models import Entity
        return await Entity.objects.acreate(name=nom, entity_type="person")

    async def _souvenir(self, content, *entites):
        from django.utils import timezone

        from old.backend.memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content=content, importance=0.8, occurred_at=timezone.now())
        for e in entites:
            await _sync(s.entities.add, e)
        return s

    async def _triple(self):
        thomas = await self._personne("Thomas")
        alice = await self._personne("Alice")
        personne = await self._souvenir("J'ai regardé la pluie tomber")
        solo = await self._souvenir("Thomas m'a parlé de son chat", thomas)
        partage = await self._souvenir(
            "Alice m'a confié devant Thomas qu'elle a rechuté", thomas, alice)
        return personne, solo, partage

    async def _pks_retenus(self, boost_name, divulgation=None):
        """Les pks que ``_enrich_souvenirs`` laisse passer sous ce niveau —
        ``FERME`` par défaut, l'ancienne porte binaire fermée. Les lignes
        sont créées sans sensibilité, donc ``personnel`` (le défaut)."""
        from old.backend.identity.divulgation import FERME
        from old.backend.memory.models import Souvenir
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock()
        pks = await _sync(lambda: list(Souvenir.objects.values_list("pk", flat=True)))
        hits = [{"id": str(pk), "content": "x", "distance": 0.1, "metadata": {}}
                for pk in pks]
        out = await r._enrich_souvenirs(
            hits, boost_name=boost_name, divulgation=divulgation or FERME)
        return {s["id"] for s in out}

    # ── (1) le filtre lui-même ───────────────────────────────────────

    async def test_un_souvenir_partage_avec_un_tiers_est_retenu(self):
        """{Thomas, Alice} n'est pas « à Thomas » : c'est aussi la confidence
        d'Alice. L'ancienne forme le gardait dès que Thomas y figurait."""
        personne, solo, partage = await self._triple()
        assert await self._pks_retenus("Thomas") == {personne.pk, solo.pk}

    async def test_un_handle_non_lie_ne_recoit_que_ce_qui_ne_concerne_personne(self):
        personne, solo, partage = await self._triple()
        assert await self._pks_retenus("") == {personne.pk}

    async def test_le_nom_est_compare_sans_la_casse(self):
        personne, solo, partage = await self._triple()
        assert await self._pks_retenus("thomas") == {personne.pk, solo.pk}

    async def test_une_entite_qui_n_est_pas_une_personne_ne_retient_rien(self):
        from old.backend.memory.models import Entity
        lieu = await Entity.objects.acreate(name="Lyon", entity_type="place")
        s = await self._souvenir("Une balade à Lyon", lieu)
        assert await self._pks_retenus("") == {s.pk}

    async def test_le_temoin_recoit_le_partage_au_niveau_avec_temoin(self):
        """Thomas était là quand Alice s'est confiée : la facette
        ``avec_temoin`` s'applique à {Thomas, Alice}, pas à Alice seule."""
        from old.backend.identity.divulgation import Divulgation, Niveau
        personne, solo, partage = await self._triple()
        d = Divulgation(niveau=Niveau.ANODIN, avec_temoin=Niveau.PERSONNEL)
        assert await self._pks_retenus("Thomas", d) == {personne.pk, solo.pk, partage.pk}

    # ── (2) connaissances et voie épisodique derrière la porte ───────

    @staticmethod
    def _hit(pk, content):
        return {"id": str(pk), "content": content, "distance": 0.1,
                "metadata": {"confidence": 0.9}}

    async def test_une_connaissance_sur_un_tiers_ne_sort_pas_sous_le_seuil(self):
        """« (concerne: Alice) » sortait devant n'importe quel handle non lié
        pendant que les souvenirs, eux, étaient déjà filtrés."""
        from old.backend.memory.models import Connaissance
        alice = await self._personne("Alice")
        intime = await Connaissance.objects.acreate(
            content="Alice attend un enfant", confidence=0.9)
        await _sync(intime.entities.add, alice)
        neutre = await Connaissance.objects.acreate(
            content="Le ciel est bleu", confidence=0.9)
        hits = [self._hit(intime.pk, intime.content), self._hit(neutre.pk, neutre.content)]

        from old.backend.identity.divulgation import FERME
        r = _make_retriever()
        ferme = await r._enrich_connaissances(
            hits, boost_name="Thomas", divulgation=FERME)
        ouvert = await r._enrich_connaissances(hits)

        assert [c["content"] for c in ferme] == ["Le ciel est bleu"]
        assert {c["content"] for c in ouvert} == {"Alice attend un enfant", "Le ciel est bleu"}

    async def test_la_voie_episodique_se_ferme_sous_le_seuil(self):
        """Dans un groupe, « l'identité de l'interlocuteur » inclut ses DM :
        le verbatim revenait mot pour mot devant l'audience."""
        from old.backend.identity.divulgation import FERME
        r = _make_retriever()
        search = AsyncMock(return_value=[])
        with patch("identity.resolver.identity_resolver.handles_for_person",
                   AsyncMock(return_value=[
                       {"person_id": "tg_42"}, {"person_id": "web_thomas"},
                   ])), \
             patch("memory.episodic.api.search_exchanges", search):
            out = await r._episodic_lane("hier soir", "tg_42", divulgation=FERME)
        assert out == []
        search.assert_not_called()

    async def test_retrieve_multi_transmet_la_porte_aux_deux_voies(self):
        """Le câblage : la voie épisodique, les échanges du plan et les
        connaissances reçoivent tous la porte du tour."""
        from old.backend.memory.episodic.api import ExchangeHit
        from old.backend.memory.retrieval.retriever import MemoryRetriever

        store = MagicMock()
        store.search_souvenirs = MagicMock(return_value=[])
        store.search_connaissances = MagicMock(return_value=[
            {"id": "3", "content": "x", "distance": 0.1, "metadata": {}},
        ])
        r = MemoryRetriever(store)
        lane = AsyncMock(return_value=[])
        conn = AsyncMock(return_value=[])
        du_plan = ExchangeHit("5", "Thomas: secret", "tg_42", 1, 5, 6, 0.0, 0.2)
        vals = {
            "memory.retrieval_souvenirs": 5,
            "memory.retrieval_connaissances": 5,
            "memory.min_importance": 0.3,
            "memory.retrieval_fetch_multiplier": 3,
            "memory.retrieval_exchanges": 3,
        }
        with patch("configs.service.config_service.get",
                   lambda k, *a, **kw: vals.get(k, kw.get("default", 0))), \
             patch.object(r, "_episodic_lane", lane), \
             patch.object(r, "_enrich_connaissances", conn), \
             patch.object(r, "_enrich_souvenirs", AsyncMock(return_value=[])), \
             patch.object(r, "_person_boost_name", AsyncMock(return_value="")), \
             patch.object(r, "_associative_expansion", AsyncMock(return_value=[])), \
             patch.object(r, "_importance_intrusion", AsyncMock(return_value=[])):
            from old.backend.identity.divulgation import FERME
            bloc = await r.retrieve_multi(
                ["q"], person_id="tg_42", extra_exchanges=[du_plan],
                divulgation=FERME,
            )

        assert lane.await_args.kwargs.get("divulgation") is FERME
        assert conn.await_args.kwargs.get("divulgation") is FERME
        assert "secret" not in bloc

    # ── (3) une base en panne ferme, elle n'ouvre pas ────────────────

    async def test_sous_le_seuil_une_base_en_panne_ne_sert_rien(self):
        """Le repli ChromaDB est la page BRUTE, sans le filtre — qui ne vit
        que dans la requête ORM qui vient d'échouer."""
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock()
        hit = {"id": "4242", "content": "Alice a rechuté", "distance": 0.2,
               "metadata": {"importance": 0.9}}
        from old.backend.identity.divulgation import FERME
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value=None)):
            ferme = await r._enrich_souvenirs([hit], boost_name="", divulgation=FERME)
            ouvert = await r._enrich_souvenirs([hit])

        assert ferme == []
        # En divulgation ouverte, le repli garde sa raison d'être.
        assert [s["id"] for s in ouvert] == [4242]

    async def test_une_connaissance_non_verifiee_n_est_jamais_servie(self):
        """`is_valid` et le filtre intime vivent dans la requête qui a
        échoué : rien de vérifié, rien de servi."""
        r = _make_retriever()
        hit = {"id": "7", "content": "x", "distance": 0.2, "metadata": {"confidence": 0.9}}
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value=None)):
            assert await r._enrich_connaissances([hit]) == []

    async def test_un_identifiant_illisible_ne_sort_pas_sous_le_seuil(self):
        """On ne peut pas vérifier de qui parle une ligne sans pk — même règle
        que l'outil ``memory_search``."""
        r = _make_retriever()
        r.vector_store.remove_souvenir = MagicMock()
        hit = {"id": "pas-un-pk", "content": "x", "metadata": {}}
        from old.backend.identity.divulgation import FERME
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value={})):
            assert await r._enrich_souvenirs([hit], divulgation=FERME) == []
            assert await r._enrich_connaissances([hit], divulgation=FERME) == []

    async def test_l_echec_de_chargement_est_compte(self):
        from old.backend.memory.retrieval.retriever import MemoryRetriever
        from old.backend.utils.degradation import degradations

        degradations.reset()
        qs = MagicMock()
        qs.filter.side_effect = RuntimeError("database is locked")
        assert await MemoryRetriever._load_by_pk(qs, [1]) is None
        assert degradations.count_for("rappel: chargement ORM des lignes") == 1
        degradations.reset()
