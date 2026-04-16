"""Tests for the evolving self-concept narrative.

Covers:
- `should_regenerate()` gating logic (age + new-material threshold)
- `gather_input()` serialization + mood trend summary
- `generate()` with a mocked AI router (JSON parse + result shape)
- `save()` persistence
- End-to-end `run_if_due()` (mocked LLM)
- `build_system_prompt()` injection of self_concept section
- `_fetch_self_concept()` backward compatibility (no narrative yet)
- SelfNarrative model basics
"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


# ---------------------------------------------------------------------------
# Model basics
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSelfNarrativeModel:

    def test_create_with_defaults(self):
        from memory.models import SelfNarrative
        n = SelfNarrative.objects.create(content="Je suis quelqu'un qui apprend.")
        assert n.pk is not None
        assert n.confidence == 0.7
        assert n.key_themes == []
        assert n.key_people == []
        assert n.dominant_mood == ""
        assert n.last_souvenir_id == 0

    def test_ordering_newest_first(self):
        from memory.models import SelfNarrative
        older = SelfNarrative.objects.create(content="older")
        newer = SelfNarrative.objects.create(content="newer")
        # Force distinct created_at ordering
        SelfNarrative.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        first = SelfNarrative.objects.first()
        assert first.pk == newer.pk

    def test_json_fields_persist(self):
        from memory.models import SelfNarrative
        n = SelfNarrative.objects.create(
            content="test",
            key_themes=["gaming", "cooking"],
            key_people=["Thomas"],
        )
        n.refresh_from_db()
        assert n.key_themes == ["gaming", "cooking"]
        assert n.key_people == ["Thomas"]

    def test_str_truncates(self):
        from memory.models import SelfNarrative
        long_text = "a" * 200
        n = SelfNarrative.objects.create(content=long_text)
        s = str(n)
        assert "..." not in s  # we truncate to 80 in __str__, no ellipsis
        assert "aaa" in s


# ---------------------------------------------------------------------------
# should_regenerate gating
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestShouldRegenerate:

    @pytest.fixture(autouse=True)
    def _clean_tables(self):
        """Defensive: other DB tests may leave rows behind when they
        don't use transaction=True. Truncate the two tables we read."""
        from memory.models import SelfNarrative, Souvenir
        SelfNarrative.objects.all().delete()
        Souvenir.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_first_narrative_waits_for_material(self):
        """No narrative yet + no souvenirs → don't regenerate."""
        from memory.narrative import NarrativeGenerator

        due, reason = await NarrativeGenerator.should_regenerate()
        assert due is False
        assert "not_enough_material" in reason

    @pytest.mark.asyncio
    async def test_first_narrative_triggers_at_threshold(self):
        from memory.models import Souvenir
        from memory.narrative import NarrativeGenerator, NARRATIVE_MIN_NEW_SOUVENIRS

        # Create enough source material
        now = timezone.now()
        for i in range(NARRATIVE_MIN_NEW_SOUVENIRS):
            await sync_to_async(Souvenir.objects.create)(
                content=f"s{i}", occurred_at=now,
            )

        due, reason = await NarrativeGenerator.should_regenerate()
        assert due is True
        assert "first_narrative" in reason

    @pytest.mark.asyncio
    async def test_recent_narrative_is_skipped(self):
        from memory.models import SelfNarrative, Souvenir
        from memory.narrative import NarrativeGenerator

        # Fresh narrative just now
        await sync_to_async(SelfNarrative.objects.create)(
            content="Je suis recent",
            last_souvenir_id=0,
        )
        # Plenty of new souvenirs
        now = timezone.now()
        for i in range(20):
            await sync_to_async(Souvenir.objects.create)(
                content=f"s{i}", occurred_at=now,
            )

        due, reason = await NarrativeGenerator.should_regenerate()
        assert due is False
        assert "too_recent" in reason

    @pytest.mark.asyncio
    async def test_old_narrative_without_new_souvenirs_skipped(self):
        from memory.models import SelfNarrative, Souvenir
        from memory.narrative import NarrativeGenerator

        # Create souvenirs FIRST, then point the narrative at their max id
        now = timezone.now()
        souvenir_ids = []
        for i in range(10):
            s = await sync_to_async(Souvenir.objects.create)(
                content=f"s{i}", occurred_at=now,
            )
            souvenir_ids.append(s.id)

        narrative = await sync_to_async(SelfNarrative.objects.create)(
            content="old", last_souvenir_id=max(souvenir_ids),
        )
        # Backdate it so age > 24h
        await sync_to_async(
            lambda: SelfNarrative.objects.filter(pk=narrative.pk).update(
                created_at=timezone.now() - timedelta(hours=48),
            )
        )()

        due, reason = await NarrativeGenerator.should_regenerate()
        assert due is False
        assert "not_enough_new" in reason

    @pytest.mark.asyncio
    async def test_old_narrative_with_enough_new_triggers(self):
        from memory.models import SelfNarrative, Souvenir
        from memory.narrative import NarrativeGenerator, NARRATIVE_MIN_NEW_SOUVENIRS

        # Old narrative pointing at souvenir_id=0 (no snapshot of high-water mark)
        narrative = await sync_to_async(SelfNarrative.objects.create)(
            content="old", last_souvenir_id=0,
        )
        await sync_to_async(
            lambda: SelfNarrative.objects.filter(pk=narrative.pk).update(
                created_at=timezone.now() - timedelta(hours=48),
            )
        )()

        # Create enough NEW souvenirs
        now = timezone.now()
        for i in range(NARRATIVE_MIN_NEW_SOUVENIRS + 2):
            await sync_to_async(Souvenir.objects.create)(
                content=f"s{i}", occurred_at=now,
            )

        due, reason = await NarrativeGenerator.should_regenerate()
        assert due is True
        assert "age=" in reason and "new=" in reason


# ---------------------------------------------------------------------------
# gather_input
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestGatherInput:

    @pytest.fixture(autouse=True)
    def _clean_tables(self):
        from memory.models import Connaissance, Souvenir
        Souvenir.objects.all().delete()
        Connaissance.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_pool(self):
        from memory.narrative import NarrativeGenerator

        pool, max_id = await NarrativeGenerator.gather_input()
        assert pool.souvenirs == []
        assert pool.connaissances == []
        assert max_id == 0

    @pytest.mark.asyncio
    async def test_sorts_by_importance(self):
        from memory.models import Souvenir
        from memory.narrative import NarrativeGenerator

        now = timezone.now()
        await sync_to_async(Souvenir.objects.create)(
            content="low", importance=0.2, occurred_at=now,
        )
        await sync_to_async(Souvenir.objects.create)(
            content="high", importance=0.9, occurred_at=now,
        )

        pool, _ = await NarrativeGenerator.gather_input()
        # Highest importance first
        assert pool.souvenirs[0]["content"] == "high"

    @pytest.mark.asyncio
    async def test_max_id_reflects_pool(self):
        from memory.models import Souvenir
        from memory.narrative import NarrativeGenerator

        now = timezone.now()
        ids = []
        for i in range(3):
            s = await sync_to_async(Souvenir.objects.create)(
                content=f"s{i}", importance=0.5, occurred_at=now,
            )
            ids.append(s.id)

        _, max_id = await NarrativeGenerator.gather_input()
        assert max_id == max(ids)

    @pytest.mark.asyncio
    async def test_connaissances_filtered_by_validity(self):
        from memory.models import Connaissance
        from memory.narrative import NarrativeGenerator

        await sync_to_async(Connaissance.objects.create)(
            content="valid", is_valid=True, confidence=0.9,
        )
        await sync_to_async(Connaissance.objects.create)(
            content="invalid", is_valid=False, confidence=0.9,
        )

        pool, _ = await NarrativeGenerator.gather_input()
        contents = [c["content"] for c in pool.connaissances]
        assert "valid" in contents
        assert "invalid" not in contents


# ---------------------------------------------------------------------------
# generate (LLM mocked)
# ---------------------------------------------------------------------------

class TestGenerate:

    @pytest.mark.asyncio
    async def test_empty_pool_returns_none(self):
        from memory.narrative import NarrativeGenerator, NarrativeInput

        gen = NarrativeGenerator()
        empty = NarrativeInput(souvenirs=[], connaissances=[], mood_trend="")
        result = await gen.generate(empty)
        assert result is None

    @pytest.mark.asyncio
    async def test_parses_valid_json_response(self):
        from memory.narrative import NarrativeGenerator, NarrativeInput

        pool = NarrativeInput(
            souvenirs=[{"content": "one event", "emotion": "happy", "importance": 0.8}],
            connaissances=[],
            mood_trend="happy (stable)",
        )

        fake_response = json.dumps({
            "narrative": "Je suis quelqu'un qui aime apprendre.",
            "key_themes": ["apprentissage"],
            "key_people": ["Thomas"],
            "dominant_mood": "happy",
            "confidence": 0.85,
        })

        with patch("memory.narrative.ai_router") as mock_router:
            mock_router.complete = AsyncMock(return_value=fake_response)
            gen = NarrativeGenerator()
            result = await gen.generate(pool)

        assert result is not None
        assert result.content.startswith("Je suis")
        assert result.key_themes == ["apprentissage"]
        assert result.key_people == ["Thomas"]
        assert result.dominant_mood == "happy"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_handles_markdown_json_wrapper(self):
        from memory.narrative import NarrativeGenerator, NarrativeInput

        pool = NarrativeInput(
            souvenirs=[{"content": "x", "emotion": "happy", "importance": 0.5}],
            connaissances=[],
            mood_trend="",
        )

        wrapped = "```json\n" + json.dumps({
            "narrative": "Je test.",
            "key_themes": [],
            "key_people": [],
            "dominant_mood": "neutral",
            "confidence": 0.5,
        }) + "\n```"

        with patch("memory.narrative.ai_router") as mock_router:
            mock_router.complete = AsyncMock(return_value=wrapped)
            gen = NarrativeGenerator()
            result = await gen.generate(pool)

        assert result is not None
        assert result.content == "Je test."

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self):
        from memory.narrative import NarrativeGenerator, NarrativeInput

        pool = NarrativeInput(
            souvenirs=[{"content": "x", "emotion": "happy", "importance": 0.5}],
            connaissances=[],
            mood_trend="",
        )

        with patch("memory.narrative.ai_router") as mock_router:
            mock_router.complete = AsyncMock(return_value="not even json {{{")
            gen = NarrativeGenerator()
            result = await gen.generate(pool)

        assert result is None

    @pytest.mark.asyncio
    async def test_caps_key_lists(self):
        """Prevents prompt bloat: key_themes/key_people cap at 8."""
        from memory.narrative import NarrativeGenerator, NarrativeInput

        pool = NarrativeInput(
            souvenirs=[{"content": "x", "emotion": "happy", "importance": 0.5}],
            connaissances=[],
            mood_trend="",
        )

        fake = json.dumps({
            "narrative": "Je test.",
            "key_themes": [f"t{i}" for i in range(20)],
            "key_people": [f"p{i}" for i in range(20)],
            "dominant_mood": "happy",
            "confidence": 0.7,
        })

        with patch("memory.narrative.ai_router") as mock_router:
            mock_router.complete = AsyncMock(return_value=fake)
            gen = NarrativeGenerator()
            result = await gen.generate(pool)

        assert len(result.key_themes) == 8
        assert len(result.key_people) == 8

    @pytest.mark.asyncio
    async def test_confidence_clamped_01(self):
        from memory.narrative import NarrativeGenerator, NarrativeInput

        pool = NarrativeInput(
            souvenirs=[{"content": "x", "emotion": "happy", "importance": 0.5}],
            connaissances=[],
            mood_trend="",
        )

        for raw, expected_min, expected_max in [(-0.5, 0.0, 0.0), (2.5, 1.0, 1.0)]:
            fake = json.dumps({
                "narrative": "Je test.",
                "key_themes": [], "key_people": [],
                "dominant_mood": "",
                "confidence": raw,
            })
            with patch("memory.narrative.ai_router") as mock_router:
                mock_router.complete = AsyncMock(return_value=fake)
                gen = NarrativeGenerator()
                result = await gen.generate(pool)
            assert expected_min <= result.confidence <= expected_max


# ---------------------------------------------------------------------------
# NarrativeResult.is_grounded
# ---------------------------------------------------------------------------

class TestIsGrounded:

    def test_empty_content_not_grounded(self):
        from memory.narrative import NarrativeResult
        r = NarrativeResult(
            content="", key_themes=[], key_people=[],
            dominant_mood="", confidence=0.8,
        )
        assert r.is_grounded is False

    def test_low_confidence_not_grounded(self):
        from memory.narrative import NarrativeResult
        r = NarrativeResult(
            content="Je suis.", key_themes=[], key_people=[],
            dominant_mood="", confidence=0.1,
        )
        assert r.is_grounded is False

    def test_whitespace_only_not_grounded(self):
        from memory.narrative import NarrativeResult
        r = NarrativeResult(
            content="   \n  ", key_themes=[], key_people=[],
            dominant_mood="", confidence=0.9,
        )
        assert r.is_grounded is False

    def test_body_plus_confidence_is_grounded(self):
        from memory.narrative import NarrativeResult
        r = NarrativeResult(
            content="Je suis curieuse.", key_themes=[], key_people=[],
            dominant_mood="", confidence=0.5,
        )
        assert r.is_grounded is True


# ---------------------------------------------------------------------------
# save + full run_if_due
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestRunIfDue:

    @pytest.fixture(autouse=True)
    def _clean_tables(self):
        from memory.models import SelfNarrative, Souvenir
        SelfNarrative.objects.all().delete()
        Souvenir.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_run_if_due_skips_when_gate_closed(self):
        from memory.narrative import NarrativeGenerator

        gen = NarrativeGenerator()
        result = await gen.run_if_due()
        assert result is None

    @pytest.mark.asyncio
    async def test_run_if_due_creates_row_on_success(self):
        from memory.models import SelfNarrative, Souvenir
        from memory.narrative import NarrativeGenerator, NARRATIVE_MIN_NEW_SOUVENIRS

        now = timezone.now()
        for i in range(NARRATIVE_MIN_NEW_SOUVENIRS + 1):
            await sync_to_async(Souvenir.objects.create)(
                content=f"event {i}", emotion="happy",
                importance=0.7, occurred_at=now,
            )

        fake = json.dumps({
            "narrative": "Je suis quelqu'un qui aime bien les cookies.",
            "key_themes": ["cuisine"],
            "key_people": [],
            "dominant_mood": "happy",
            "confidence": 0.8,
        })

        with patch("memory.narrative.ai_router") as mock_router:
            mock_router.complete = AsyncMock(return_value=fake)
            gen = NarrativeGenerator()
            result = await gen.run_if_due()

        assert result is not None
        count = await sync_to_async(SelfNarrative.objects.count)()
        assert count == 1
        latest = await sync_to_async(SelfNarrative.objects.first)()
        assert "cookies" in latest.content
        assert latest.key_themes == ["cuisine"]
        assert latest.last_souvenir_id > 0

    @pytest.mark.asyncio
    async def test_run_if_due_silent_on_ai_failure(self):
        from memory.models import SelfNarrative, Souvenir
        from memory.narrative import NarrativeGenerator, NARRATIVE_MIN_NEW_SOUVENIRS

        now = timezone.now()
        for i in range(NARRATIVE_MIN_NEW_SOUVENIRS + 1):
            await sync_to_async(Souvenir.objects.create)(
                content=f"x{i}", occurred_at=now,
            )

        with patch("memory.narrative.ai_router") as mock_router:
            mock_router.complete = AsyncMock(side_effect=RuntimeError("boom"))
            gen = NarrativeGenerator()
            result = await gen.run_if_due()

        assert result is None
        count = await sync_to_async(SelfNarrative.objects.count)()
        assert count == 0

    @pytest.mark.asyncio
    async def test_run_if_due_skips_ungrounded_output(self):
        from memory.models import SelfNarrative, Souvenir
        from memory.narrative import NarrativeGenerator, NARRATIVE_MIN_NEW_SOUVENIRS

        now = timezone.now()
        for i in range(NARRATIVE_MIN_NEW_SOUVENIRS + 1):
            await sync_to_async(Souvenir.objects.create)(
                content=f"x{i}", occurred_at=now,
            )

        empty = json.dumps({
            "narrative": "",
            "key_themes": [], "key_people": [],
            "dominant_mood": "", "confidence": 0.0,
        })
        with patch("memory.narrative.ai_router") as mock_router:
            mock_router.complete = AsyncMock(return_value=empty)
            gen = NarrativeGenerator()
            result = await gen.run_if_due()

        assert result is None
        count = await sync_to_async(SelfNarrative.objects.count)()
        assert count == 0


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

class TestPromptInjection:

    def test_build_system_prompt_omits_section_when_empty(self):
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(self_concept="")
        assert "QUI TU ES DEVENUE" not in prompt

    def test_build_system_prompt_includes_section_when_present(self):
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(
            self_concept="Je suis quelqu'un qui code trop tard le soir."
        )
        assert "QUI TU ES DEVENUE" in prompt
        assert "code trop tard" in prompt
        assert "--- FIN ---" in prompt

    def test_self_concept_before_emotion_section(self):
        """Self-concept should come before the dynamic layers."""
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(
            self_concept="Je suis X.",
            emotion_context="Humeur: triste.",
        )
        sc_pos = prompt.index("QUI TU ES DEVENUE")
        em_pos = prompt.index("TON ETAT EMOTIONNEL")
        assert sc_pos < em_pos


# ---------------------------------------------------------------------------
# Backward compatibility — no narrative yet
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestContextBackwardCompat:

    @pytest.fixture(autouse=True)
    def _clean_tables(self):
        from memory.models import SelfNarrative
        SelfNarrative.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_fetch_self_concept_empty_when_no_row(self):
        from pipeline.context import _fetch_self_concept
        sc = await _fetch_self_concept()
        assert sc == ""

    @pytest.mark.asyncio
    async def test_fetch_self_concept_returns_latest_content(self):
        from memory.models import SelfNarrative
        from pipeline.context import _fetch_self_concept

        await sync_to_async(SelfNarrative.objects.create)(content="old")
        # Backdate older
        await sync_to_async(
            lambda: SelfNarrative.objects.filter(content="old").update(
                created_at=timezone.now() - timedelta(days=1),
            )
        )()
        await sync_to_async(SelfNarrative.objects.create)(content="new")

        sc = await _fetch_self_concept()
        assert sc == "new"
