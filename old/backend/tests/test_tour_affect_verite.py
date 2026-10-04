"""Ce qu'un tour porte comme vérité affective, et ce qui le réveille.

Trois questions distinctes, longtemps confondues par le processor :

1. **Ce qu'un tour déclare.** Sans balise, il ne déclare RIEN. L'ancre PAD de
   NEUTRAL est l'origine, donc appliquer un `EmotionData(NEUTRAL, 0.5)` par
   défaut n'était pas neutre : ça tirait la colère qu'on venait de provoquer
   vers zéro, et l'oscillateur sous-amorti dépassait de l'autre côté.
2. **Ce que la frame annonce.** L'oscillateur n'absorbe qu'une part de ce qui
   vient d'être dit, et il n'y a pas de tick entre l'impulsion et la lecture :
   la frame rendait donc un état plus proche de celui d'AVANT le tour que de
   ce que la réponse déclarait — un message bouleversant se persistait
   `neutral:0.00`. La balise est la vérité du tour ; l'oscillateur dit où en
   est la relation, ce qui est une autre question.
3. **Quand elle se réveille.** Sur la perception, pas sur une réponse réussie.

Plus le rêve, seul effet irréversible qu'un tour raté produisait encore.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from old.backend.emotion.types import Emotion, EmotionData


def _fake_context(**kwargs):
    from old.backend.pipeline.context import ConversationContext

    return ConversationContext(**kwargs)


def _reply(text="ok", emotion=None):
    return (text, emotion, [])


@pytest.fixture
def _stub_turn():
    """Coupe tout ce qu'un tour touche hors du sujet testé ici."""
    from old.backend.configs.service import config_service
    from old.backend.pipeline import processor

    with patch.object(config_service, "get", return_value=60), \
         patch.object(processor.emotion_engine, "ensure_person_loaded",
                      new=AsyncMock()), \
         patch.object(processor.emotion_engine, "save_snapshot",
                      new=AsyncMock()), \
         patch.object(processor, "persist_user_message",
                      new=AsyncMock(return_value=1)), \
         patch.object(processor, "persist_assistant_message",
                      new=AsyncMock(return_value=2)), \
         patch.object(processor, "emit_communication_event", new=AsyncMock()), \
         patch.object(processor, "publish_turn_completed", new=AsyncMock()), \
         patch.object(processor, "identity_resolver", MagicMock(
             ingest_message=AsyncMock())):
        yield


# ---------------------------------------------------------------------------
# S1 — ce qu'un tour déclare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCeQueLeTourDeclare:

    async def _run(self, pid, reply, **kwargs):
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        with patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(return_value=reply)), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            return await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id=pid),
                **kwargs,
            )

    async def test_un_tour_sans_tag_ne_touche_pas_l_oscillateur(self, _stub_turn):
        from old.backend.emotion.engine import emotion_engine

        pid = "web_sans_tag"
        emotion_engine.person_moods.pop(pid, None)
        emotion_engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), pid)
        mood = emotion_engine.person_moods[pid]
        position = tuple(mood.dynamic.position)
        velocity = tuple(mood.dynamic.velocity)

        await self._run(pid, _reply("je ne sais pas quoi dire", None))

        # Les deux, pas seulement l'intensité : l'impulsion s'écrit sur la
        # vitesse, donc une position inchangée ne prouve rien.
        assert tuple(emotion_engine.person_moods[pid].dynamic.position) == position
        assert tuple(emotion_engine.person_moods[pid].dynamic.velocity) == velocity

    async def test_un_tag_neutral_explicite_reste_une_impulsion(self, _stub_turn):
        """La garde qui empêche de « corriger » S1 en ignorant tout NEUTRAL."""
        from old.backend.emotion.engine import emotion_engine

        pid = "web_tag_neutre"
        emotion_engine.person_moods.pop(pid, None)
        emotion_engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), pid)
        position = tuple(emotion_engine.person_moods[pid].dynamic.position)

        await self._run(
            pid, _reply("d'accord", EmotionData(Emotion.NEUTRAL, 0.5)),
        )

        assert tuple(emotion_engine.person_moods[pid].dynamic.position) != position

    async def test_un_tour_en_echec_ne_declare_rien(self, _stub_turn):
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        with patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(side_effect=RuntimeError("llm broke"))), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor.emotion_engine, "process_emotion") as impulse, \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            output = await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id="web_ko"),
            )

        assert output.emotion_data is None
        # Seule l'anxiété que Mika s'adresse à elle-même a le droit de passer.
        for call in impulse.call_args_list:
            assert call.args[1] == "conscience_mika"


# ---------------------------------------------------------------------------
# B2 + S2 — ce que la frame annonce
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCeQueLaFrameAnnonce:

    async def _frame(self, pid, reply, context=None):
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        sent = {}

        async def _capture(output, source, person_id=None):
            sent["output"] = output

        with patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(return_value=reply)), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=context or _fake_context())), \
             patch.object(processor, "broadcast_to_websocket", new=_capture):
            await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id=pid),
            )
            # La diffusion vit dans une chaîne détachée (délai « réflexion »
            # hors du worker) : on la vide avant de lire ce qui est parti.
            await processor.flush_delayed_broadcasts()
        return sent["output"]

    async def test_la_frame_speech_porte_le_tag_du_tour(self, _stub_turn):
        from old.backend.emotion.engine import emotion_engine

        pid = "web_frame_tag"
        emotion_engine.person_moods.pop(pid, None)

        output = await self._frame(
            pid, _reply("je suis furieuse", EmotionData(Emotion.ANGRY, 0.8)),
        )

        assert output.emotion_name == "angry"
        assert output.emotion_intensity == pytest.approx(0.8)
        # La frame et son blend ne peuvent pas se contredire : la porte
        # d'ambivalence du frontend lit exactement cette paire.
        assert output.emotion_blend[0]["emotion"] == "angry"

    async def test_un_tour_sans_tag_retombe_sur_l_oscillateur(self, _stub_turn):
        from old.backend.emotion.engine import emotion_engine

        pid = "web_frame_sans_tag"
        emotion_engine.person_moods.pop(pid, None)
        emotion_engine.process_emotion(EmotionData(Emotion.SAD, 0.9), pid)
        attendu = emotion_engine.compute_message_emotion(pid)

        output = await self._frame(pid, _reply("hmm", None))

        assert output.emotion_name == attendu.emotion.value

    async def test_le_mode_professionnel_ne_laisse_pas_le_tag_colorer_la_frame(
        self, _stub_turn,
    ):
        from old.backend.emotion.engine import emotion_engine

        pid = "web_pro"
        emotion_engine.person_moods.pop(pid, None)
        ctx = _fake_context(
            project_context="Titre : audit", project_suppresses_emotion=True,
        )

        output = await self._frame(
            pid, _reply("c'est fait", EmotionData(Emotion.EXCITED, 0.9)), ctx,
        )

        assert not (
            output.emotion_name == "excited"
            and output.emotion_intensity == pytest.approx(0.9)
        )
        # Le tag brut reste lisible pour qui veut savoir ce que le modèle a
        # dit — ce n'est pas la même question que ce que la frame annonce.
        assert output.emotion_data == EmotionData(Emotion.EXCITED, 0.9)

    async def test_un_tour_en_echec_n_invente_pas_d_emotion(self, _stub_turn):
        from old.backend.emotion.engine import emotion_engine
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        pid = "web_frame_ko"
        emotion_engine.person_moods.pop(pid, None)
        emotion_engine.process_emotion(EmotionData(Emotion.SAD, 0.7), pid)
        attendu = emotion_engine.compute_message_emotion(pid)

        sent = {}

        async def _capture(output, source, person_id=None):
            sent["output"] = output

        with patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(side_effect=RuntimeError("llm broke"))), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "broadcast_to_websocket", new=_capture):
            await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id=pid),
            )
            await processor.flush_delayed_broadcasts()

        assert sent["output"].emotion_name == attendu.emotion.value


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestLeSnapshotPorteLeTag:

    async def test_le_snapshot_porte_le_tag_du_tour(self):
        from old.backend.configs.service import config_service
        from old.backend.memory.manager import memory_manager
        from old.backend.memory.models import Conversation, EmotionSnapshot
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        conversation = await Conversation.objects.acreate()
        memory_manager.conversation = conversation
        pid = "web_snapshot"
        processor.emotion_engine.person_moods.pop(pid, None)
        processor.emotion_engine._last_snapshot_time.pop(pid, None)
        # Une stance opposée bien installée : l'oscillateur n'absorbe qu'une
        # part de l'impulsion, donc sans la balise le snapshot garderait la
        # couleur d'avant le tour.
        processor.emotion_engine.process_emotion(
            EmotionData(Emotion.HAPPY, 1.0), pid,
        )

        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor.emotion_engine, "ensure_person_loaded",
                          new=AsyncMock()), \
             patch.object(processor, "call_ai_and_parse", new=AsyncMock(
                 return_value=_reply("je suis furieuse",
                                     EmotionData(Emotion.ANGRY, 0.8)))), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=1)), \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=2)), \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()), \
             patch.object(processor, "identity_resolver", MagicMock(
                 ingest_message=AsyncMock())), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id=pid),
            )

        snap = await EmotionSnapshot.objects.filter(person_id=pid).alast()
        assert snap is not None
        assert snap.primary_emotion == "angry"
        assert snap.primary_intensity == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# M1 — le rêve n'est pas brûlé par un tour raté
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLeReveSurvitAUnEchec:

    async def _turn(self, dream, *, fails, pid="web_reve"):
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        ctx = _fake_context(
            dream_context="Tu as fait cette nuit un reve doux.",
            pending_dream_recall=dream,
        )
        ai = (
            AsyncMock(side_effect=RuntimeError("llm broke")) if fails
            else AsyncMock(return_value=_reply("salut", None))
        )
        with patch.object(processor, "call_ai_and_parse", new=ai), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=ctx)), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            return await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id=pid),
            )

    async def test_un_tour_en_echec_ne_brule_pas_le_reve(self, _stub_turn):
        from old.backend.memory import read

        dream = MagicMock()
        with patch.object(read, "mark_dream_recalled", new=AsyncMock()) as mark:
            await self._turn(dream, fails=True)
        mark.assert_not_called()

    async def test_un_tour_reussi_consomme_le_reve(self, _stub_turn):
        from old.backend.memory import read

        dream = MagicMock()
        with patch.object(read, "mark_dream_recalled", new=AsyncMock()) as mark:
            await self._turn(dream, fails=False)
        mark.assert_awaited_once_with(dream)

    async def test_un_marquage_qui_echoue_ne_coute_pas_le_tour(self, _stub_turn):
        from old.backend.memory import read
        from old.backend.utils.degradation import degradations

        degradations.reset()
        dream = MagicMock()
        with patch.object(read, "mark_dream_recalled",
                          new=AsyncMock(side_effect=RuntimeError("db down"))):
            output = await self._turn(dream, fails=False)

        assert output.text == "salut"
        assert degradations.count_for("turn: marquage du reve") == 1


# ---------------------------------------------------------------------------
# P1 — un déclencheur interne n'a pas de « ton » à lire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLeMoodHintDUnContextePreAssemble:

    async def test_un_contexte_preassemble_perd_son_mood_hint(self, _stub_turn):
        """Le chemin conscience : elle assemble son contexte elle-même.

        `_act` vise une vraie personne, donc le person_id n'est pas interne et
        la garde de `gather_context` ne protège rien — et ici elle ne tourne
        même pas.
        """
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        vu = {}

        async def _capture(context, message):
            vu["context"] = context
            return _reply("coucou", None)

        ctx = _fake_context(user_mood_hint="besoin de vider son sac")
        with patch.object(processor, "call_ai_and_parse", new=_capture), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            await processor.process_message(
                Perception.from_internal_trigger(
                    "il est temps de lui ecrire", source="conscience",
                    person_id="web_thomas",
                ),
                context=ctx,
            )

        assert vu["context"].user_mood_hint == ""

    async def test_une_vraie_question_garde_son_mood_hint(self, _stub_turn):
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        vu = {}

        async def _capture(context, message):
            vu["context"] = context
            return _reply("coucou", None)

        ctx = _fake_context(user_mood_hint="besoin de vider son sac")
        with patch.object(processor, "call_ai_and_parse", new=_capture), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            await processor.process_message(
                Perception.from_text("hey", source="frontend",
                                     person_id="web_thomas"),
                context=ctx,
            )

        assert vu["context"].user_mood_hint == "besoin de vider son sac"


# ---------------------------------------------------------------------------
# P6 — elle se réveille parce qu'on lui parle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLeReveilEstSurLaPerception:

    @pytest.fixture
    def _reveil(self):
        from old.backend.conscience.engine import conscience_engine
        from old.backend.memory import sleep as sleep_module

        with patch.object(conscience_engine, "note_activity") as note, \
             patch.object(sleep_module.sleep_cycle, "note_interaction") as wake:
            yield note, wake

    async def test_une_vraie_question_reveille_avant_l_appel_ia(self, _reveil):
        """« Avant », pas « pendant » — c'est tout le constat.

        La frame est composée pendant le tour : `_collect_inner_state` et
        `_voice_decision` lisent `sleep_cycle.phase` à cet instant-là.
        """
        from old.backend.pipeline import router
        from old.backend.pipeline.perception import Perception

        note, wake = _reveil
        vus = {}

        async def _process(perception, **kwargs):
            vus["note"] = note.call_count
            vus["wake"] = wake.call_count
            return MagicMock()

        with patch("pipeline.processor.process_message", new=_process):
            await router.perceive(
                Perception.from_text("coucou", source="frontend",
                                     person_id="web_a"),
            )

        assert vus["note"] == 1
        assert vus["wake"] == 1

    async def test_un_tour_en_echec_reveille_quand_meme(self, _reveil):
        from old.backend.pipeline import router
        from old.backend.pipeline.perception import Perception

        note, wake = _reveil
        with patch("pipeline.processor.process_message",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(RuntimeError):
                await router.perceive(
                    Perception.from_text("coucou", source="frontend",
                                         person_id="web_a"),
                )

        assert note.call_count == 1
        assert wake.call_count == 1

    async def test_une_observation_ne_reveille_pas(self, _reveil):
        """Une caméra qui bouge n'est pas quelqu'un qui parle."""
        from old.backend.pipeline import router
        from old.backend.pipeline.perception import Intent, Perception

        note, wake = _reveil
        perception = Perception.from_text(
            "mouvement", source="camera", person_id="web_a",
            intent=Intent.OBSERVATION,
        )
        with patch("modules.manager.module_manager.emit_event", new=AsyncMock()):
            await router.perceive(perception)

        note.assert_not_called()
        wake.assert_not_called()

    async def test_un_declencheur_interne_ne_reveille_pas(self, _reveil):
        """Sinon la conscience s'auto-réveille en boucle."""
        from old.backend.pipeline import router
        from old.backend.pipeline.perception import Perception

        note, wake = _reveil
        with patch("pipeline.processor.process_message",
                   new=AsyncMock(return_value=MagicMock())):
            await router.perceive(
                Perception.from_internal_trigger(
                    "dis quelque chose", source="conscience",
                    person_id="web_a",
                ),
            )

        note.assert_not_called()
        wake.assert_not_called()

    async def test_une_personne_interne_ne_reveille_pas(self, _reveil):
        from old.backend.pipeline import router
        from old.backend.pipeline.perception import Perception

        note, wake = _reveil
        with patch("pipeline.processor.process_message",
                   new=AsyncMock(return_value=MagicMock())):
            await router.perceive(
                Perception.from_text("hmm", source="conscience",
                                     person_id="conscience_mika"),
            )

        note.assert_not_called()
        wake.assert_not_called()

    async def test_un_reveil_qui_leve_ne_coute_pas_le_tour(self):
        from old.backend.conscience.engine import conscience_engine
        from old.backend.memory import sleep as sleep_module
        from old.backend.pipeline import router
        from old.backend.pipeline.perception import Perception
        from old.backend.utils.degradation import degradations

        degradations.reset()
        with patch.object(conscience_engine, "note_activity",
                          side_effect=RuntimeError("boom")), \
             patch.object(sleep_module.sleep_cycle, "note_interaction") as wake, \
             patch("pipeline.processor.process_message",
                   new=AsyncMock(return_value="repondu")):
            out = await router.perceive(
                Perception.from_text("coucou", source="frontend",
                                     person_id="web_a"),
            )

        assert out == "repondu"
        assert degradations.count_for("perception: reveil conscience") == 1
        # Une conscience cassée n'empêche pas le réveil du sommeil.
        wake.assert_called_once()
