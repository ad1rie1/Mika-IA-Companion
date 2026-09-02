"""Ce que le processeur retient du transport, et ce qu'il rend au canal.

Deux sorties d'un même fait — « d'où vient ce tour, et que prouve-t-il » :
``transport_meta`` écrit avec la question pour la reprise après redémarrage,
``SpeechOutput.reply_ref`` rendu à la diffusion pour la réponse réactive.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _contexte():
    from pipeline.context import ConversationContext

    return ConversationContext()


@pytest.mark.asyncio
class TestLeProcesseurRetientLeTransport:

    @pytest.fixture(autouse=True)
    def _no_db(self):
        from configs.service import config_service
        from pipeline import processor

        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor.identity_resolver, "ingest_message",
                          new=AsyncMock()), \
             patch.object(processor.emotion_engine, "ensure_person_loaded",
                          new=AsyncMock()), \
             patch.object(processor.emotion_engine, "save_snapshot",
                          new=AsyncMock()):
            yield

    async def _tour(self, perception):
        from emotion.types import Emotion, EmotionData
        from pipeline import processor

        ok = ("ok", EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0), [])
        with patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(return_value=ok)), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=_contexte())), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=1)) as persist_q, \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=2)), \
             patch.object(processor, "emit_communication_event",
                          new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed",
                          new=AsyncMock()), \
             patch.object(processor, "broadcast_to_websocket",
                          new=AsyncMock()) as diffusion:
            output = await processor.process_message(perception)
        return output, persist_q, diffusion

    async def test_les_drapeaux_du_tour_sont_ecrits_avec_la_question(self):
        from pipeline.perception import Perception

        perception = Perception.from_text(
            "c'est quoi mon secret ?", source="telegram", person_id="tg_9",
            metadata={
                "authenticated": False, "is_public": True,
                "reply_ref": "-100777",
            },
        )
        _, persist_q, _ = await self._tour(perception)

        assert persist_q.call_args.kwargs["transport_meta"] == {
            "authenticated": False, "is_public": True, "reply_ref": "-100777",
        }

    async def test_une_session_verifiee_est_notee_comme_telle(self):
        from pipeline.perception import Perception

        perception = Perception.from_text(
            "salut", source="frontend", person_id="user_5",
            metadata={"authenticated": True, "channel": "web"},
        )
        _, persist_q, _ = await self._tour(perception)

        meta = persist_q.call_args.kwargs["transport_meta"]
        assert meta["authenticated"] is True
        assert meta["is_public"] is False
        assert "reply_ref" not in meta

    async def test_le_salon_d_origine_arrive_a_la_diffusion(self):
        from pipeline.perception import Perception

        perception = Perception.from_text(
            "hop", source="telegram", person_id="tg_9",
            metadata={"authenticated": False, "is_public": True,
                      "reply_ref": "-100777"},
        )
        output, _, diffusion = await self._tour(perception)

        assert output.reply_ref == "-100777"
        assert diffusion.call_args.args[0].reply_ref == "-100777"

    async def test_un_tour_sans_salon_ne_declare_rien(self):
        from pipeline.perception import Perception

        perception = Perception.from_text(
            "salut", source="frontend", person_id="web_x",
            metadata={"authenticated": False, "channel": "web"},
        )
        output, _, _ = await self._tour(perception)

        assert output.reply_ref is None

    async def test_un_brief_interne_n_ecrit_aucun_transport(self):
        """Un brief n'est jamais rejoué : rien à retenir de son transport."""
        from pipeline.perception import Perception

        perception = Perception.from_internal_trigger(
            "Un visiteur vient de se connecter.", source="frontend",
            person_id="web_x",
        )
        _, persist_q, _ = await self._tour(perception)

        assert persist_q.call_args.kwargs["transport_meta"] is None


class TestLeSalonEstBorne:

    def test_un_salon_demesure_est_coupe(self):
        from pipeline.perception import Perception
        from pipeline.processor import _reply_ref

        perception = Perception.from_text(
            "x", source="telegram", person_id="tg_9",
            metadata={"reply_ref": "9" * 10_000},
        )
        assert len(_reply_ref(perception)) == 64

    def test_un_salon_absent_ou_vide_vaut_rien(self):
        from pipeline.perception import Perception
        from pipeline.processor import _reply_ref

        assert _reply_ref(Perception.from_text(
            "x", source="telegram", person_id="tg_9",
        )) is None
        assert _reply_ref(Perception.from_text(
            "x", source="telegram", person_id="tg_9",
            metadata={"reply_ref": ""},
        )) is None
