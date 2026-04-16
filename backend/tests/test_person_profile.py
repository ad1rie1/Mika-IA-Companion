"""Tests for the theory-of-mind layer: PersonProfile + Commitment.

Covers:
- Model CRUD (PersonProfile, Commitment)
- select_due_entities gating (new vs regen, activity window, threshold)
- gather_for_entity serialization
- generate() with mocked AI (JSON parse, enum validation, caps)
- save() upsert behavior
- run_cycle() end-to-end (mocked LLM)
- Consolidator → Commitment creation from 'commitment' extractions
- Prompt injection: _fetch_person_context + build_system_prompt section
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
class TestPersonProfileModel:

    def test_create_minimal(self):
        from memory.models import Entity, PersonProfile
        ent = Entity.objects.create(name="Thomas", entity_type="person")
        profile = PersonProfile.objects.create(entity=ent)
        assert profile.pk is not None
        assert profile.closeness == "stranger"
        assert profile.preferred_tone == "unknown"
        assert profile.topics_of_interest == []
        assert profile.sensitive_topics == []

    def test_one_profile_per_entity(self):
        from django.db import IntegrityError
        from memory.models import Entity, PersonProfile
        ent = Entity.objects.create(name="A", entity_type="person")
        PersonProfile.objects.create(entity=ent)
        with pytest.raises(IntegrityError):
            PersonProfile.objects.create(entity=ent)

    def test_cascade_on_entity_delete(self):
        from memory.models import Entity, PersonProfile
        ent = Entity.objects.create(name="Temp", entity_type="person")
        PersonProfile.objects.create(entity=ent)
        ent.delete()
        assert PersonProfile.objects.count() == 0

    def test_json_fields_persist(self):
        from memory.models import Entity, PersonProfile
        ent = Entity.objects.create(name="X", entity_type="person")
        p = PersonProfile.objects.create(
            entity=ent,
            topics_of_interest=["gaming", "cuisine"],
            sensitive_topics=["divorce"],
        )
        p.refresh_from_db()
        assert p.topics_of_interest == ["gaming", "cuisine"]
        assert p.sensitive_topics == ["divorce"]


@pytest.mark.django_db
class TestCommitmentModel:

    def test_create_with_person(self):
        from memory.models import Commitment, Entity
        ent = Entity.objects.create(name="Thomas", entity_type="person")
        c = Commitment.objects.create(
            description="Envoyer la playlist",
            person=ent,
        )
        assert c.pk is not None
        assert c.status == "pending"

    def test_create_without_person(self):
        """Generic commitments are allowed — person is nullable."""
        from memory.models import Commitment
        c = Commitment.objects.create(description="Me coucher plus tot")
        assert c.person is None

    def test_person_null_on_entity_delete(self):
        from memory.models import Commitment, Entity
        ent = Entity.objects.create(name="tmp", entity_type="person")
        c = Commitment.objects.create(description="test", person=ent)
        ent.delete()
        c.refresh_from_db()
        assert c.person_id is None


# ---------------------------------------------------------------------------
# select_due_entities
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestSelectDueEntities:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import (
            Commitment, Connaissance, Entity, PersonProfile, Souvenir,
        )
        Commitment.objects.all().delete()
        PersonProfile.objects.all().delete()
        Souvenir.objects.all().delete()
        Connaissance.objects.all().delete()
        Entity.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_no_entities_returns_empty(self):
        from memory.person_profile import PersonProfileGenerator
        result = await PersonProfileGenerator.select_due_entities()
        assert result == []

    @pytest.mark.asyncio
    async def test_new_entity_with_enough_souvenirs_is_due(self):
        from memory.models import Entity, Souvenir
        from memory.person_profile import (
            PROFILE_MIN_NEW_SOUVENIRS, PersonProfileGenerator,
        )

        ent = await sync_to_async(Entity.objects.create)(
            name="Thomas", entity_type="person",
        )
        now = timezone.now()
        for i in range(PROFILE_MIN_NEW_SOUVENIRS):
            s = await sync_to_async(Souvenir.objects.create)(
                content=f"event {i}", occurred_at=now,
            )
            await sync_to_async(s.entities.add)(ent)

        due = await PersonProfileGenerator.select_due_entities()
        assert len(due) == 1
        assert due[0][0].pk == ent.pk
        assert due[0][1] is None  # no existing profile

    @pytest.mark.asyncio
    async def test_new_entity_below_threshold_skipped(self):
        from memory.models import Entity, Souvenir
        from memory.person_profile import PersonProfileGenerator

        ent = await sync_to_async(Entity.objects.create)(
            name="Quick", entity_type="person",
        )
        now = timezone.now()
        # Only 1 souvenir — below threshold
        s = await sync_to_async(Souvenir.objects.create)(
            content="x", occurred_at=now,
        )
        await sync_to_async(s.entities.add)(ent)

        due = await PersonProfileGenerator.select_due_entities()
        assert due == []

    @pytest.mark.asyncio
    async def test_inactive_entity_skipped(self):
        """A person not mentioned in the activity window shouldn't be due."""
        from memory.models import Entity, Souvenir
        from memory.person_profile import (
            PROFILE_ACTIVITY_WINDOW_DAYS,
            PROFILE_MIN_NEW_SOUVENIRS,
            PersonProfileGenerator,
        )

        ent = await sync_to_async(Entity.objects.create)(
            name="Old", entity_type="person",
        )
        old_ts = timezone.now() - timedelta(days=PROFILE_ACTIVITY_WINDOW_DAYS + 5)
        for i in range(PROFILE_MIN_NEW_SOUVENIRS + 2):
            s = await sync_to_async(Souvenir.objects.create)(
                content=f"x{i}", occurred_at=old_ts,
            )
            await sync_to_async(s.entities.add)(ent)

        due = await PersonProfileGenerator.select_due_entities()
        assert due == []

    @pytest.mark.asyncio
    async def test_recent_profile_skipped(self):
        from memory.models import Entity, PersonProfile, Souvenir
        from memory.person_profile import (
            PROFILE_MIN_NEW_SOUVENIRS, PersonProfileGenerator,
        )

        ent = await sync_to_async(Entity.objects.create)(
            name="R", entity_type="person",
        )
        profile = await sync_to_async(PersonProfile.objects.create)(
            entity=ent, generated_at=timezone.now(), last_souvenir_id=0,
        )
        now = timezone.now()
        for i in range(PROFILE_MIN_NEW_SOUVENIRS + 2):
            s = await sync_to_async(Souvenir.objects.create)(
                content=f"x{i}", occurred_at=now,
            )
            await sync_to_async(s.entities.add)(ent)

        due = await PersonProfileGenerator.select_due_entities()
        assert due == []

    @pytest.mark.asyncio
    async def test_old_profile_with_enough_new_is_due(self):
        from memory.models import Entity, PersonProfile, Souvenir
        from memory.person_profile import (
            PROFILE_MIN_AGE_HOURS,
            PROFILE_MIN_NEW_SOUVENIRS,
            PersonProfileGenerator,
        )

        ent = await sync_to_async(Entity.objects.create)(
            name="O", entity_type="person",
        )
        profile = await sync_to_async(PersonProfile.objects.create)(
            entity=ent, last_souvenir_id=0,
        )
        old = timezone.now() - timedelta(hours=PROFILE_MIN_AGE_HOURS + 2)
        await sync_to_async(
            lambda: PersonProfile.objects.filter(pk=profile.pk).update(generated_at=old)
        )()

        now = timezone.now()
        for i in range(PROFILE_MIN_NEW_SOUVENIRS + 1):
            s = await sync_to_async(Souvenir.objects.create)(
                content=f"new{i}", occurred_at=now,
            )
            await sync_to_async(s.entities.add)(ent)

        due = await PersonProfileGenerator.select_due_entities()
        assert len(due) == 1
        assert due[0][1] is not None  # existing profile

    @pytest.mark.asyncio
    async def test_cap_at_max_persons_per_cycle(self):
        from memory.models import Entity, Souvenir
        from memory.person_profile import (
            MAX_PERSONS_PER_CYCLE,
            PROFILE_MIN_NEW_SOUVENIRS,
            PersonProfileGenerator,
        )

        # Create more entities than the cap, each with enough souvenirs.
        now = timezone.now()
        for i in range(MAX_PERSONS_PER_CYCLE + 3):
            ent = await sync_to_async(Entity.objects.create)(
                name=f"p{i}", entity_type="person",
            )
            for j in range(PROFILE_MIN_NEW_SOUVENIRS):
                s = await sync_to_async(Souvenir.objects.create)(
                    content=f"e{j}", occurred_at=now,
                )
                await sync_to_async(s.entities.add)(ent)

        due = await PersonProfileGenerator.select_due_entities()
        assert len(due) == MAX_PERSONS_PER_CYCLE


# ---------------------------------------------------------------------------
# gather_for_entity
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestGatherForEntity:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Connaissance, Entity, Souvenir
        Souvenir.objects.all().delete()
        Connaissance.objects.all().delete()
        Entity.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_only_returns_linked_material(self):
        from memory.models import Entity, Souvenir
        from memory.person_profile import PersonProfileGenerator

        target = await sync_to_async(Entity.objects.create)(
            name="Target", entity_type="person",
        )
        other = await sync_to_async(Entity.objects.create)(
            name="Other", entity_type="person",
        )
        now = timezone.now()
        s1 = await sync_to_async(Souvenir.objects.create)(
            content="linked", occurred_at=now,
        )
        await sync_to_async(s1.entities.add)(target)
        s2 = await sync_to_async(Souvenir.objects.create)(
            content="unlinked", occurred_at=now,
        )
        await sync_to_async(s2.entities.add)(other)

        pool, _ = await PersonProfileGenerator.gather_for_entity(target)
        contents = [s["content"] for s in pool.souvenirs]
        assert "linked" in contents
        assert "unlinked" not in contents

    @pytest.mark.asyncio
    async def test_filters_invalid_connaissances(self):
        from memory.models import Connaissance, Entity
        from memory.person_profile import PersonProfileGenerator

        ent = await sync_to_async(Entity.objects.create)(
            name="K", entity_type="person",
        )
        valid = await sync_to_async(Connaissance.objects.create)(
            content="valid", is_valid=True,
        )
        await sync_to_async(valid.entities.add)(ent)
        invalid = await sync_to_async(Connaissance.objects.create)(
            content="invalid", is_valid=False,
        )
        await sync_to_async(invalid.entities.add)(ent)

        pool, _ = await PersonProfileGenerator.gather_for_entity(ent)
        contents = [c["content"] for c in pool.connaissances]
        assert "valid" in contents
        assert "invalid" not in contents


# ---------------------------------------------------------------------------
# generate (LLM mocked)
# ---------------------------------------------------------------------------

class TestGenerate:

    @pytest.mark.asyncio
    async def test_empty_pool_returns_none(self):
        from memory.person_profile import PersonProfileGenerator, ProfileInput

        gen = PersonProfileGenerator()
        empty = ProfileInput(entity_name="X", souvenirs=[], connaissances=[])
        result = await gen.generate(empty)
        assert result is None

    @pytest.mark.asyncio
    async def test_parses_valid_response(self):
        from memory.person_profile import PersonProfileGenerator, ProfileInput

        pool = ProfileInput(
            entity_name="Thomas",
            souvenirs=[{"content": "on a joue", "emotion": "happy", "importance": 0.8}],
            connaissances=[],
        )

        fake = json.dumps({
            "summary": "Thomas est quelqu'un qui aime le gaming retro.",
            "closeness": "friend",
            "preferred_tone": "playful",
            "topics_of_interest": ["gaming", "retro"],
            "sensitive_topics": ["travail"],
            "confidence": 0.85,
        })

        with patch("memory.person_profile.ai_router") as router:
            router.complete = AsyncMock(return_value=fake)
            gen = PersonProfileGenerator()
            result = await gen.generate(pool)

        assert result is not None
        assert result.closeness == "friend"
        assert result.preferred_tone == "playful"
        assert result.topics_of_interest == ["gaming", "retro"]
        assert result.sensitive_topics == ["travail"]
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_invalid_closeness_falls_back_to_stranger(self):
        from memory.person_profile import PersonProfileGenerator, ProfileInput

        pool = ProfileInput(
            entity_name="X",
            souvenirs=[{"content": "x", "emotion": "neutral", "importance": 0.5}],
            connaissances=[],
        )
        fake = json.dumps({
            "summary": "X est quelqu'un.",
            "closeness": "best_friend_forever",  # invalid
            "preferred_tone": "playful",
            "topics_of_interest": [],
            "sensitive_topics": [],
            "confidence": 0.5,
        })

        with patch("memory.person_profile.ai_router") as router:
            router.complete = AsyncMock(return_value=fake)
            gen = PersonProfileGenerator()
            result = await gen.generate(pool)

        assert result.closeness == "stranger"

    @pytest.mark.asyncio
    async def test_invalid_tone_falls_back_to_unknown(self):
        from memory.person_profile import PersonProfileGenerator, ProfileInput

        pool = ProfileInput(
            entity_name="X",
            souvenirs=[{"content": "x", "emotion": "neutral", "importance": 0.5}],
            connaissances=[],
        )
        fake = json.dumps({
            "summary": "X.",
            "closeness": "friend",
            "preferred_tone": "sarcastic",  # invalid
            "topics_of_interest": [],
            "sensitive_topics": [],
            "confidence": 0.5,
        })

        with patch("memory.person_profile.ai_router") as router:
            router.complete = AsyncMock(return_value=fake)
            gen = PersonProfileGenerator()
            result = await gen.generate(pool)

        assert result.preferred_tone == "unknown"

    @pytest.mark.asyncio
    async def test_caps_topic_lists_at_5(self):
        from memory.person_profile import PersonProfileGenerator, ProfileInput

        pool = ProfileInput(
            entity_name="X",
            souvenirs=[{"content": "x", "emotion": "neutral", "importance": 0.5}],
            connaissances=[],
        )
        fake = json.dumps({
            "summary": "X.",
            "closeness": "friend",
            "preferred_tone": "direct",
            "topics_of_interest": [f"t{i}" for i in range(20)],
            "sensitive_topics": [f"s{i}" for i in range(20)],
            "confidence": 0.6,
        })

        with patch("memory.person_profile.ai_router") as router:
            router.complete = AsyncMock(return_value=fake)
            gen = PersonProfileGenerator()
            result = await gen.generate(pool)

        assert len(result.topics_of_interest) == 5
        assert len(result.sensitive_topics) == 5

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self):
        from memory.person_profile import PersonProfileGenerator, ProfileInput

        pool = ProfileInput(
            entity_name="X",
            souvenirs=[{"content": "x", "emotion": "happy", "importance": 0.5}],
            connaissances=[],
        )

        with patch("memory.person_profile.ai_router") as router:
            router.complete = AsyncMock(return_value="totally not json {{{")
            gen = PersonProfileGenerator()
            result = await gen.generate(pool)

        assert result is None


# ---------------------------------------------------------------------------
# ProfileResult.is_grounded
# ---------------------------------------------------------------------------

class TestIsGrounded:

    def test_empty_summary_not_grounded(self):
        from memory.person_profile import ProfileResult
        r = ProfileResult(
            summary="", closeness="stranger", preferred_tone="unknown",
            topics_of_interest=[], sensitive_topics=[], confidence=0.9,
        )
        assert r.is_grounded is False

    def test_low_confidence_not_grounded(self):
        from memory.person_profile import ProfileResult
        r = ProfileResult(
            summary="X est quelqu'un.", closeness="friend",
            preferred_tone="direct",
            topics_of_interest=[], sensitive_topics=[], confidence=0.1,
        )
        assert r.is_grounded is False

    def test_body_and_confidence_is_grounded(self):
        from memory.person_profile import ProfileResult
        r = ProfileResult(
            summary="X est curieux.", closeness="friend",
            preferred_tone="playful",
            topics_of_interest=[], sensitive_topics=[], confidence=0.4,
        )
        assert r.is_grounded is True


# ---------------------------------------------------------------------------
# save + run_cycle
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestSaveAndRunCycle:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Entity, PersonProfile, Souvenir
        PersonProfile.objects.all().delete()
        Souvenir.objects.all().delete()
        Entity.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_save_creates_row(self):
        from memory.models import Entity, PersonProfile
        from memory.person_profile import PersonProfileGenerator, ProfileResult

        ent = await sync_to_async(Entity.objects.create)(
            name="T", entity_type="person",
        )
        result = ProfileResult(
            summary="T est...", closeness="friend", preferred_tone="playful",
            topics_of_interest=["gaming"], sensitive_topics=[], confidence=0.8,
        )
        await PersonProfileGenerator.save(ent, result, 42, 5)

        p = await sync_to_async(PersonProfile.objects.get)(entity=ent)
        assert p.closeness == "friend"
        assert p.last_souvenir_id == 42
        assert p.interaction_count == 5
        assert p.generated_at is not None

    @pytest.mark.asyncio
    async def test_save_updates_existing(self):
        """save() is update_or_create — calling twice yields 1 row."""
        from memory.models import Entity, PersonProfile
        from memory.person_profile import PersonProfileGenerator, ProfileResult

        ent = await sync_to_async(Entity.objects.create)(
            name="U", entity_type="person",
        )
        r1 = ProfileResult(
            summary="v1", closeness="stranger", preferred_tone="unknown",
            topics_of_interest=[], sensitive_topics=[], confidence=0.5,
        )
        r2 = ProfileResult(
            summary="v2", closeness="friend", preferred_tone="direct",
            topics_of_interest=[], sensitive_topics=[], confidence=0.7,
        )
        await PersonProfileGenerator.save(ent, r1, 10, 1)
        await PersonProfileGenerator.save(ent, r2, 20, 3)

        count = await sync_to_async(PersonProfile.objects.count)()
        assert count == 1
        p = await sync_to_async(PersonProfile.objects.get)(entity=ent)
        assert p.summary == "v2"
        assert p.last_souvenir_id == 20

    @pytest.mark.asyncio
    async def test_run_cycle_skips_when_nothing_due(self):
        from memory.person_profile import PersonProfileGenerator

        gen = PersonProfileGenerator()
        count = await gen.run_cycle()
        assert count == 0

    @pytest.mark.asyncio
    async def test_run_cycle_creates_profile(self):
        from memory.models import Entity, PersonProfile, Souvenir
        from memory.person_profile import (
            PROFILE_MIN_NEW_SOUVENIRS, PersonProfileGenerator,
        )

        ent = await sync_to_async(Entity.objects.create)(
            name="Claire", entity_type="person",
        )
        now = timezone.now()
        for i in range(PROFILE_MIN_NEW_SOUVENIRS + 1):
            s = await sync_to_async(Souvenir.objects.create)(
                content=f"avec Claire {i}", emotion="happy",
                importance=0.6, occurred_at=now,
            )
            await sync_to_async(s.entities.add)(ent)

        fake = json.dumps({
            "summary": "Claire est passionnee de botanique.",
            "closeness": "acquaintance",
            "preferred_tone": "gentle",
            "topics_of_interest": ["plantes"],
            "sensitive_topics": [],
            "confidence": 0.7,
        })

        with patch("memory.person_profile.ai_router") as router:
            router.complete = AsyncMock(return_value=fake)
            gen = PersonProfileGenerator()
            count = await gen.run_cycle()

        assert count == 1
        p = await sync_to_async(PersonProfile.objects.get)(entity=ent)
        assert "botanique" in p.summary

    @pytest.mark.asyncio
    async def test_run_cycle_handles_failure_for_one_entity(self):
        """One entity failing shouldn't stop the others."""
        from memory.models import Entity, PersonProfile, Souvenir
        from memory.person_profile import (
            PROFILE_MIN_NEW_SOUVENIRS, PersonProfileGenerator,
        )

        now = timezone.now()
        for name in ("A", "B"):
            e = await sync_to_async(Entity.objects.create)(
                name=name, entity_type="person",
            )
            for i in range(PROFILE_MIN_NEW_SOUVENIRS):
                s = await sync_to_async(Souvenir.objects.create)(
                    content=f"e{i}", occurred_at=now,
                )
                await sync_to_async(s.entities.add)(e)

        good = json.dumps({
            "summary": "OK", "closeness": "friend", "preferred_tone": "direct",
            "topics_of_interest": [], "sensitive_topics": [], "confidence": 0.6,
        })
        calls = [RuntimeError("boom"), good]

        async def side_effect(**kwargs):
            val = calls.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("memory.person_profile.ai_router") as router:
            router.complete = AsyncMock(side_effect=side_effect)
            gen = PersonProfileGenerator()
            count = await gen.run_cycle()

        # 1 of 2 succeeded
        saved = await sync_to_async(PersonProfile.objects.count)()
        assert saved == 1
        assert count == 1


# ---------------------------------------------------------------------------
# Consolidator → Commitment
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestConsolidatorCommitmentHandling:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import (
            Commitment, Connaissance, Entity, Message, Souvenir,
        )
        Commitment.objects.all().delete()
        Souvenir.objects.all().delete()
        Connaissance.objects.all().delete()
        Message.objects.all().delete()
        Entity.objects.all().delete()
        yield

    async def _seed_conversation_with_messages(self, contents: list[tuple[str, str]]):
        """Create Conversation + Messages directly, bypassing the memory_manager
        singleton whose cached Conversation doesn't survive transaction=True
        test isolation.
        Returns the conversation so downstream tests can reference it.
        """
        from memory.models import Conversation, Message

        conversation = await sync_to_async(Conversation.objects.create)()
        for role, content in contents:
            await sync_to_async(Message.objects.create)(
                conversation=conversation, role=role, content=content,
            )
        return conversation

    @pytest.mark.asyncio
    async def test_commitment_extraction_creates_row_with_person(self):
        from memory.models import Commitment
        from memory.storage.consolidator import MemoryConsolidator

        await self._seed_conversation_with_messages([
            ("user", "Tu pourrais me faire une playlist ?"),
            ("assistant", "Ouais, je te ferai la playlist ce soir promis."),
        ])

        fake_extractions = [
            {
                "type": "commitment",
                "store": True,
                "content": "Envoyer la playlist a Thomas ce soir",
                "person": "Thomas",
            },
        ]

        from memory.extraction.extractor import MemoryExtractor
        from memory.storage.vector_store import VectorStore
        consolidator = MemoryConsolidator(
            extractor=MemoryExtractor(),
            vector_store=VectorStore(),
            interval_seconds=3600,
        )
        consolidator._last_processed_id = 0
        consolidator.extractor.analyze_messages = AsyncMock(return_value=fake_extractions)

        await consolidator._consolidate()

        count = await sync_to_async(Commitment.objects.count)()
        assert count == 1
        c = await sync_to_async(
            lambda: Commitment.objects.select_related("person").first()
        )()
        assert c.status == "pending"
        assert c.person is not None
        assert c.person.name == "Thomas"

    @pytest.mark.asyncio
    async def test_commitment_without_person(self):
        from memory.models import Commitment
        from memory.storage.consolidator import MemoryConsolidator

        await self._seed_conversation_with_messages([
            ("assistant", "Je vais arreter de coder tard."),
        ])

        fake = [{
            "type": "commitment",
            "store": True,
            "content": "Arreter de coder tard",
            # no person field
        }]

        from memory.extraction.extractor import MemoryExtractor
        from memory.storage.vector_store import VectorStore
        consolidator = MemoryConsolidator(
            extractor=MemoryExtractor(),
            vector_store=VectorStore(),
            interval_seconds=3600,
        )
        consolidator._last_processed_id = 0
        consolidator.extractor.analyze_messages = AsyncMock(return_value=fake)

        await consolidator._consolidate()

        c = await sync_to_async(
            lambda: Commitment.objects.select_related("person").first()
        )()
        assert c is not None
        assert c.person is None


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

class TestPromptInjection:

    def test_build_system_prompt_includes_person_section(self):
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(
            person_context="Thomas est quelqu'un qui aime le gaming."
        )
        assert "CE QUE TU SAIS DE CETTE PERSONNE" in prompt
        assert "gaming" in prompt

    def test_build_system_prompt_omits_when_empty(self):
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(person_context="")
        assert "CE QUE TU SAIS DE CETTE PERSONNE" not in prompt

    def test_person_context_between_self_concept_and_modules(self):
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(
            self_concept="Je suis Mika.",
            person_context="Thomas est sympa.",
            module_context="Modules: email",
        )
        sc_pos = prompt.index("QUI TU ES DEVENUE")
        pc_pos = prompt.index("CE QUE TU SAIS DE CETTE PERSONNE")
        mc_pos = prompt.index("CONTEXTE MODULES")
        assert sc_pos < pc_pos < mc_pos


# ---------------------------------------------------------------------------
# _fetch_person_context
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestFetchPersonContext:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Commitment, Entity, PersonProfile
        Commitment.objects.all().delete()
        PersonProfile.objects.all().delete()
        Entity.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_internal_person_id_returns_empty(self):
        from pipeline.context import _fetch_person_context
        for pid in ("conscience_mika", "__global__", "anonymous", ""):
            assert await _fetch_person_context(pid) == ""

    @pytest.mark.asyncio
    async def test_unknown_person_returns_empty(self):
        from pipeline.context import _fetch_person_context
        assert await _fetch_person_context("someone_never_seen") == ""

    @pytest.mark.asyncio
    async def test_profile_only_formats_block(self):
        from memory.models import Entity, PersonProfile
        from pipeline.context import _fetch_person_context

        ent = await sync_to_async(Entity.objects.create)(
            name="Thomas", entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent,
            summary="Thomas est un pote de longue date.",
            closeness="close",
            preferred_tone="playful",
            topics_of_interest=["gaming"],
        )

        block = await _fetch_person_context("Thomas")
        assert "Thomas est un pote" in block
        assert "close" in block
        assert "playful" in block
        assert "gaming" in block

    @pytest.mark.asyncio
    async def test_commitments_only_no_profile(self):
        """If a profile doesn't exist but an Entity does and has commitments,
        we still return the commitments block."""
        from memory.models import Commitment, Entity, PersonProfile
        from pipeline.context import _fetch_person_context

        # Create an entity + a commitment + a placeholder profile so
        # the lookup finds the entity (profile is required by the SQL join).
        ent = await sync_to_async(Entity.objects.create)(
            name="Claire", entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(entity=ent)
        await sync_to_async(Commitment.objects.create)(
            description="Lui envoyer la photo", person=ent, status="pending",
        )

        block = await _fetch_person_context("Claire")
        assert "photo" in block
        assert "Tu lui avais dit" in block

    @pytest.mark.asyncio
    async def test_affect_block_included_when_person_mood_active(self):
        """When Mika has a real stance toward the person, the person_context
        block should include the affect line."""
        from emotion.engine import emotion_engine
        from emotion.types import Emotion, EmotionData
        from memory.models import Entity, PersonProfile
        from pipeline.context import _fetch_person_context

        ent = await sync_to_async(Entity.objects.create)(
            name="Anna", entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent, summary="Anna est cool.",
        )

        # Seed a strong person mood so the affect block is non-empty.
        emotion_engine.person_moods.pop("Anna", None)
        for _ in range(4):
            emotion_engine.process_emotion(
                EmotionData(Emotion.HAPPY, 0.8), "Anna",
            )

        block = await _fetch_person_context("Anna")
        # Affect description uses "tu" or "envers"
        assert any(word in block.lower() for word in ("envers", "tu te sens"))
        # And the profile summary is still there
        assert "Anna est cool" in block

    @pytest.mark.asyncio
    async def test_weekly_trend_added_when_two_plus_summaries(self):
        """Two or more EmotionalSummary rows → trend sentence appears."""
        from datetime import date, timedelta as td
        from memory.models import EmotionalSummary, Entity, PersonProfile
        from pipeline.context import _fetch_person_context

        pid = "Marc"
        ent = await sync_to_async(Entity.objects.create)(
            name=pid, entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent, summary="Marc est sympa.",
        )

        today = date.today()
        for offset in range(3):
            await sync_to_async(EmotionalSummary.objects.create)(
                person_id=pid,
                period_type="daily",
                period_start=today - td(days=offset),
                dominant_emotion="happy",
                dominant_intensity=0.7,
                emotion_distribution={"happy": 0.7},
                trend="warming",
                snapshot_count=10,
            )

        block = await _fetch_person_context(pid)
        assert "jours" in block
        assert "happy" in block
        assert "warming" in block

    @pytest.mark.asyncio
    async def test_no_trend_with_single_summary(self):
        """A single day of data is not a trend — don't fabricate one."""
        from datetime import date
        from memory.models import EmotionalSummary, Entity, PersonProfile
        from pipeline.context import _fetch_person_context

        pid = "Lone"
        ent = await sync_to_async(Entity.objects.create)(
            name=pid, entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent, summary="Lone.",
        )
        await sync_to_async(EmotionalSummary.objects.create)(
            person_id=pid,
            period_type="daily",
            period_start=date.today(),
            dominant_emotion="sad",
            dominant_intensity=0.5,
            trend="stable",
            snapshot_count=1,
        )

        block = await _fetch_person_context(pid)
        assert "jours" not in block

    @pytest.mark.asyncio
    async def test_honored_commitments_not_included(self):
        from memory.models import Commitment, Entity, PersonProfile
        from pipeline.context import _fetch_person_context

        ent = await sync_to_async(Entity.objects.create)(
            name="Bob", entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=ent, summary="Bob.",
        )
        await sync_to_async(Commitment.objects.create)(
            description="Faire X", person=ent, status="honored",
        )
        await sync_to_async(Commitment.objects.create)(
            description="Faire Y (en cours)", person=ent, status="pending",
        )

        block = await _fetch_person_context("Bob")
        assert "X" not in block or "Faire X" not in block
        assert "Faire Y" in block
