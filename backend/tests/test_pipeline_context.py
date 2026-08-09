"""Tests for pipeline context gathering.

`gather_context()` assembles memory + emotion + drives + modules + self
concept + per-person context into a single ConversationContext. The
function is pure orchestration: all DB/IO is delegated to singletons we
mock here.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.context import ConversationContext, gather_context


class TestConversationContext:

    def test_all_fields(self):
        ctx = ConversationContext(
            memory_context="mem",
            emotion_context="happy",
            module_context="3 emails",
            history=[{"role": "user", "content": "hi"}],
            tools=[],
            tool_names=["send_email"],
            self_concept="Je suis",
            person_context="C'est Alice",
        )
        assert ctx.memory_context == "mem"
        assert ctx.emotion_context == "happy"
        assert ctx.module_context == "3 emails"
        assert len(ctx.history) == 1
        assert ctx.tools == []
        assert ctx.tool_names == ["send_email"]
        assert ctx.self_concept == "Je suis"
        assert ctx.person_context == "C'est Alice"

    def test_self_concept_and_person_context_default_empty(self):
        ctx = ConversationContext(
            memory_context="", emotion_context="", module_context="",
            history=[], tools=[], tool_names=[],
        )
        assert ctx.self_concept == ""
        assert ctx.person_context == ""


class TestGatherContext:

    def _patch_deps(
        self,
        *,
        memory_ctx: str = "",
        global_mood: str = "",
        drive_ctx: str = "",
        module_ctx: str = "",
        history: list | None = None,
    ):
        mock_mem = MagicMock()
        mock_mem.get_memory_context = AsyncMock(return_value=memory_ctx)
        mock_mem.get_conversation_context = MagicMock(return_value=history or [])

        mock_emo = MagicMock()
        mock_emo.get_global_mood_context = MagicMock(return_value=global_mood)

        mock_drive = MagicMock()
        mock_drive.get_context = MagicMock(return_value=drive_ctx)

        mock_mod = MagicMock()
        mock_mod.collect_context = MagicMock(return_value=module_ctx)
        mock_mod.collect_tools = MagicMock(return_value=[])

        return mock_mem, mock_emo, mock_drive, mock_mod

    def _apply_patches(self, mock_mem, mock_emo, mock_drive, mock_mod):
        """Use ExitStack-like context stacking via nested `with`."""
        return [
            patch("pipeline.context.memory_manager", mock_mem),
            patch("pipeline.context.emotion_engine", mock_emo),
            patch("pipeline.context.drive_engine", mock_drive),
            patch("pipeline.context.module_manager", mock_mod),
            # Self-concept + person-context fetches are DB calls; stub them.
            patch("pipeline.context._fetch_self_concept",
                  new_callable=AsyncMock, return_value=""),
            patch("pipeline.context._fetch_person_context",
                  new_callable=AsyncMock, return_value=""),
        ]

    @pytest.mark.asyncio
    async def test_assembles_all_parts(self):
        mocks = self._patch_deps(
            memory_ctx="souvenir",
            global_mood="Tu te sens excitee",
            drive_ctx="Tu as envie de parler",
            module_ctx="emails",
        )
        patches = self._apply_patches(*mocks)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1")
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.memory_context == "souvenir"
        assert "excitee" in ctx.emotion_context
        assert "envie de parler" in ctx.emotion_context  # drives appended
        assert ctx.module_context == "emails"

    @pytest.mark.asyncio
    async def test_memory_failure_returns_empty_string(self):
        mock_mem, mock_emo, mock_drive, mock_mod = self._patch_deps()
        mock_mem.get_memory_context = AsyncMock(side_effect=Exception("DB down"))

        patches = self._apply_patches(mock_mem, mock_emo, mock_drive, mock_mod)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1")
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.memory_context == ""

    @pytest.mark.asyncio
    async def test_include_tools_false_skips_tool_collection(self):
        mocks = self._patch_deps()
        mock_mod = mocks[3]
        mock_mod.collect_tools = MagicMock(return_value=[MagicMock(name="tool")])

        patches = self._apply_patches(*mocks)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1", include_tools=False)
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.tools == []
        assert ctx.tool_names == []
        mock_mod.collect_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_tools_true_collects_tools(self):
        mocks = self._patch_deps()
        mock_mod = mocks[3]
        fake_tool = MagicMock()
        fake_tool.name = "send_email"
        mock_mod.collect_tools = MagicMock(return_value=[fake_tool])

        patches = self._apply_patches(*mocks)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1", include_tools=True)
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.tools == [fake_tool]
        assert ctx.tool_names == ["send_email"]


class TestMemoryFailureIsVisible:
    """Le filet terminal du rappel avalait tout avec un simple logger.

    ChromaDB mort → `memory_context=""` à chaque tour, Mika ne se souvient de
    rien, et la page santé au vert : une panne partielle devenait
    indiscernable d'un fonctionnement normal.
    """

    @pytest.mark.asyncio
    async def test_memory_failure_is_counted(self):
        from utils.degradation import degradations

        mocks = self._deps()
        mocks[0].get_memory_context = AsyncMock(side_effect=Exception("DB down"))
        degradations.reset()

        ctx = await _run_gather(mocks)

        assert ctx.memory_context == ""
        assert degradations.count_for("rappel memoire") == 1

    @pytest.mark.asyncio
    async def test_an_unavailable_recall_is_said_in_the_prompt(self):
        """Sinon elle confabule : rien à retrouver se lit comme rien à dire."""
        mocks = self._deps(memory_ctx="")
        mocks[0].recall_unavailable = True

        ctx = await _run_gather(mocks)

        assert "memoire longue est indisponible" in ctx.memory_context

    @pytest.mark.asyncio
    async def test_an_empty_recall_is_not_announced_as_a_failure(self):
        """Une base jeune ne remonte rien : ce n'est pas une panne."""
        mocks = self._deps(memory_ctx="")
        mocks[0].recall_unavailable = False

        ctx = await _run_gather(mocks)

        assert ctx.memory_context == ""

    _deps = TestGatherContext._patch_deps


class TestMoodHintReadsOnlyRealMessages:
    """`user_mood_hint` était gardé par person_id, pas par intent.

    Un `INTERNAL_TRIGGER` visant Thomas porte SON handle, donc
    `is_internal_person` est faux : le brief d'action que Mika s'est écrit à
    elle-même passait dans `detect_user_mood_hint` et ressortait sous
    `--- CE QUE TU PERCOIS DE SON ETAT ---` — « besoin de vider son sac » à
    propos d'un texte que personne n'a envoyé.
    """

    # Les briefs d'action dépassent régulièrement le seuil des 80 mots.
    BRIEF = " ".join(["Tu n'as pas parle a Thomas depuis un moment"] * 12)

    _deps = TestGatherContext._patch_deps

    @pytest.mark.asyncio
    async def test_le_mood_hint_ne_lit_pas_un_declencheur_interne(self):
        from pipeline.perception import Intent

        ctx = await _run_gather(
            self._deps(), message=self.BRIEF, person_id="web_thomas",
            intent=Intent.INTERNAL_TRIGGER,
        )
        assert ctx.user_mood_hint == ""

    @pytest.mark.asyncio
    async def test_le_mood_hint_lit_toujours_un_vrai_message(self):
        ctx = await _run_gather(
            self._deps(), message=self.BRIEF, person_id="web_thomas",
        )
        assert ctx.user_mood_hint != ""


class TestPhraseEcart:
    """Le temps se dit en prose. « depuis 1814400s » n'aide aucun modèle."""

    def test_sous_le_plancher_rien_n_est_dit(self):
        from pipeline.context import _phrase_ecart

        assert _phrase_ecart(0) == ""
        assert _phrase_ecart(3600) == ""
        assert _phrase_ecart(5 * 3600) == ""

    def test_les_paliers_sont_de_la_prose(self):
        from pipeline.context import _phrase_ecart

        attendus = {
            8 * 3600: "plus tot dans la journee",
            30 * 3600: "hier",
            3 * 86400: "trois jours",
            9 * 86400: "une semaine",
            21 * 86400: "trois semaines",
            40 * 86400: "un mois",
            95 * 86400: "trois mois",
        }
        for seconds, fragment in attendus.items():
            phrase = _phrase_ecart(seconds)
            assert fragment in phrase, (seconds, phrase)

    def test_aucune_sortie_ne_porte_de_secondes(self):
        import re

        from pipeline.context import _phrase_ecart

        for jours in range(0, 200):
            phrase = _phrase_ecart(jours * 86400 + 7 * 3600)
            assert not re.search(r"\d+\s*s\b", phrase), phrase
            assert "gap" not in phrase


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestDerniereInteractionDansLeBlocPersonne:
    """Sans ça, « tu m'as manqué » est une confabulation.

    Le prompt ne portait que l'heure courante et « hier » : l'écart depuis le
    dernier contact n'existait nulle part.
    """

    async def _bloc(self, *, may_disclose=True, person_id="web_a"):
        from pipeline import context as ctx_mod

        identity_ctx = MagicMock(
            person_id=person_id, is_internal=False, may_disclose=may_disclose,
        )
        with patch.object(ctx_mod, "emotion_engine", MagicMock(
                 get_person_affect_context=MagicMock(return_value=""))), \
             patch.object(ctx_mod.identity_resolver, "handles_for_person",
                          new=AsyncMock(return_value=[{"person_id": person_id}])), \
             patch.object(ctx_mod.identity_resolver, "entity_for_person",
                          new=AsyncMock(return_value=None)):
            return await ctx_mod._fetch_person_context(identity_ctx)

    async def _message(self, *, days_ago: float, person_id="web_a"):
        from datetime import timedelta

        from django.utils import timezone
        from memory.models import Conversation, Message

        conv = await Conversation.objects.acreate()
        msg = await Message.objects.acreate(
            conversation=conv, role="user", content="salut",
            person_id=person_id,
        )
        # `update()` contourne `auto_now_add`.
        await Message.objects.filter(pk=msg.pk).aupdate(
            created_at=timezone.now() - timedelta(days=days_ago),
        )

    async def test_le_bloc_dit_depuis_quand_on_ne_s_est_pas_parle(self):
        await self._message(days_ago=21)
        assert "trois semaines" in await self._bloc()

    async def test_pas_de_ligne_quand_la_conversation_est_continue(self):
        await self._message(days_ago=0)
        assert "depuis" not in await self._bloc()

    async def test_pas_de_ligne_quand_rien_n_a_jamais_ete_dit(self):
        """Dire « c'est la premiere fois » contredirait une identité liée qui
        revient sur un nouveau handle."""
        assert await self._bloc() == ""

    async def test_l_ecart_survit_sous_le_seuil_de_divulgation(self):
        # C'est un fait sur l'échange avec CE handle, pas un extrait de la
        # fiche d'un tiers.
        await self._message(days_ago=21)
        assert "trois semaines" in await self._bloc(may_disclose=False)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestHorodatageDesSegmentsDHistorique:
    """Un fil réhydraté après trois semaines se lisait comme la suite de la
    conversation d'il y a cinq minutes : le tampon ne porte aucune date et
    `ChatPrompt.chat_messages()` ne rend que `{role, content}`.
    """

    async def _history(self, *ages_en_jours):
        from datetime import timedelta

        from django.utils import timezone
        from memory.models import Conversation, Message

        conv = await Conversation.objects.acreate()
        entries = []
        for age in ages_en_jours:
            msg = await Message.objects.acreate(
                conversation=conv, role="user", content=f"m{age}",
            )
            await Message.objects.filter(pk=msg.pk).aupdate(
                created_at=timezone.now() - timedelta(days=age),
            )
            entries.append({"id": msg.pk, "role": "user", "content": f"m{age}"})
        return entries

    async def test_les_segments_sont_horodates_apres_un_trou(self):
        from pipeline.context import _stamp_history_gaps

        history = await self._history(20, 20, 0)
        stamped = await _stamp_history_gaps(history)

        assert not stamped[0]["content"].startswith("[il y a ")
        assert not stamped[1]["content"].startswith("[il y a ")
        assert stamped[2]["content"].startswith("[il y a ")
        assert "m0" in stamped[2]["content"]

    async def test_un_fil_continu_n_est_pas_horodate(self):
        from pipeline.context import _stamp_history_gaps

        history = await self._history(0, 0, 0)
        stamped = await _stamp_history_gaps(history)

        assert all("[il y a " not in m["content"] for m in stamped)

    async def test_l_horodatage_ne_mute_pas_le_tampon(self):
        """Les dicts sont partagés avec `MemoryManager.short_term`."""
        from pipeline.context import _stamp_history_gaps

        history = await self._history(20, 0)
        avant = [dict(m) for m in history]
        await _stamp_history_gaps(history)

        assert history == avant


async def _run_gather(mocks, *, message="test", person_id="u1", **kwargs):
    patches = TestGatherContext._apply_patches(TestGatherContext, *mocks)
    for p in patches:
        p.start()
    try:
        return await gather_context(message, person_id=person_id, **kwargs)
    finally:
        for p in reversed(patches):
            p.stop()
