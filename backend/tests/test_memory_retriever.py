"""Tests for MemoryRetriever — reranking, formatting, time helpers."""

import pytest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone


def _make_retriever():
    from memory.retrieval.retriever import MemoryRetriever
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
        from memory.retrieval.retriever import MemoryRetriever
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
        from memory.retrieval.retriever import MemoryRetriever
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

    def test_always_has_header_footer(self):
        r = _make_retriever()
        result = r._format_context([], [])
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
        from memory.retrieval.retriever import MemoryRetriever
        mock_store = MagicMock()
        mock_store.search_souvenirs = MagicMock(return_value=[])
        mock_store.search_connaissances = MagicMock(return_value=[])

        with patch("memory.retrieval.retriever.settings") as ms:
            ms.MEMORY_RETRIEVAL_SOUVENIRS = 5
            ms.MEMORY_RETRIEVAL_CONNAISSANCES = 5
            ms.MEMORY_MIN_IMPORTANCE = 0.3
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
        from memory.retrieval.retriever import _emotional_charge
        assert _emotional_charge("neutral") == 0.0
        assert _emotional_charge("inconnu") == 0.0

    def test_emotional_charge_strong_emotions_are_high(self):
        from memory.retrieval.retriever import _emotional_charge
        assert _emotional_charge("scared") > 0.5
        assert _emotional_charge("love") > 0.5

    def test_mood_congruence_same_direction_high_opposite_low(self):
        from emotion import pad
        from emotion.types import Emotion
        from memory.retrieval.retriever import _mood_congruence
        happy_mood = pad.EMOTION_ANCHORS[Emotion.HAPPY]
        assert _mood_congruence(happy_mood, "happy") > 0.8
        assert _mood_congruence(happy_mood, "sad") < 0.2

    def test_mood_congruence_neutral_has_no_effect(self):
        from memory.retrieval.retriever import _mood_congruence
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
        from memory.retrieval.retriever import _SalienceWeights
        r = _make_retriever()
        w = _SalienceWeights(importance=0.0, emotion=0.0, mood=0.0)
        s = self._s(relevance=0.5, importance=1.0, emotion="love")
        out = r._rerank_souvenirs([s], "", weights=w)
        assert out[0]["_score"] == pytest.approx(0.5)  # que la pertinence

    def test_mood_congruence_boosts_congruent_memories(self):
        from emotion import pad
        from emotion.types import Emotion
        from memory.retrieval.retriever import _SalienceWeights
        r = _make_retriever()
        w = _SalienceWeights(importance=0.0, emotion=0.0, mood=0.5)
        happy_mood = pad.EMOTION_ANCHORS[Emotion.HAPPY]
        happy_mem = self._s(emotion="happy")
        sad_mem = self._s(emotion="sad")
        out = r._rerank_souvenirs([sad_mem, happy_mem], "", mood_pad=happy_mood, weights=w)
        assert out[0] is happy_mem

    def test_negative_mood_damps_congruence_against_spirals(self):
        from emotion import pad
        from emotion.types import Emotion
        from memory.retrieval.retriever import _SalienceWeights
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
        from memory.models import Entity, Souvenir, Theme
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
        from memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content=content, importance=importance, occurred_at=timezone.now())
        if theme is not None:
            await _sync(s.themes.add, theme)
        return s

    async def test_links_a_thematically_related_memory(self, monkeypatch):
        from memory.models import Theme
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
        from memory.models import Theme
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
        from memory.models import Theme
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
        from memory.models import Theme
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
        from memory.models import Souvenir
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
        from memory.models import Souvenir
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
