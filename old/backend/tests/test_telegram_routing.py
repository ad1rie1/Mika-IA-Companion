"""Où repart une réponse Telegram — le salon de la question, pas le dernier vu.

La réponse était routée par l'adresse mémorisée dans le registre de présence,
réécrite à chaque message entrant : « le dernier salon où ce compte a été
vu ». Thomas pose une question en privé ; elle attend derrière l'unique
worker ; il écrit dans un groupe avant qu'elle soit traitée — et la réponse
privée, composée avec tout son contexte, partait dans le groupe.

Deux règles, pinées séparément :

- une réponse RÉACTIVE repart vers le salon d'où sa question est venue
  (``reply_ref`` du tour, porté jusqu'à la diffusion) ;
- l'adresse mémorisée pour un envoi PROACTIF n'est jamais un groupe.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

PERSON = "tg_4242"
DM_CHAT = 4242
GROUP_CHAT = -100777


def _update(text, *, chat_id, chat_type, user_id=4242):
    msg = SimpleNamespace(
        text=text,
        chat_id=chat_id,
        chat=SimpleNamespace(type=chat_type),
        from_user=SimpleNamespace(id=user_id, full_name="Thomas"),
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(message=msg)


class _FakeTelegram:
    """Le livreur : note le salon qu'on lui remet, ne parle à personne.

    Même contrat que ``TelegramChannel.deliver`` : sans ``chat_id`` il
    n'envoie rien et le dit.
    """

    is_running = True

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def deliver(self, output, interlocutor) -> bool:
        if not interlocutor.delivery_ref:
            return False
        self.sent.append((interlocutor.delivery_ref, output.text))
        return True


@pytest.fixture
def canal():
    """Un canal Telegram sans bot, et un registre de présence propre après."""
    from old.backend.communication.channels import telegram as tg_module
    from old.backend.communication.delivery import register_channel, unregister_channel
    from old.backend.communication.presence import presence_registry
    from old.backend.identity.resolver import identity_resolver

    fake = _FakeTelegram()
    register_channel("telegram", fake)
    presence_registry.unregister(PERSON, "telegram")
    tg_module._msg_timestamps.pop(PERSON, None)
    with patch.object(tg_module, "_allowed_senders", return_value=set()), \
         patch.object(identity_resolver, "link_handle",
                      new=AsyncMock(return_value=object())) as link:
        yield SimpleNamespace(
            channel=tg_module.TelegramChannel(), fake=fake, link=link,
        )
    unregister_channel("telegram")
    presence_registry.unregister(PERSON, "telegram")


async def _handle(canal, update):
    """Passe un update au handler et rend la perception confiée à la file."""
    captured = {}
    with patch(
        "pipeline.turns.turn_queue.submit",
        side_effect=lambda p: (captured.setdefault("p", p), True)[1],
    ):
        await canal.channel._handle_message(update, context=None)
    return captured["p"]


def _stubs_de_diffusion():
    """Le vrai ``broadcast_to_websocket``, sans couche Channels ni base."""
    from old.backend.pipeline import broadcast

    class _Layer:
        async def group_send(self, group, payload):
            pass

    return (
        patch.object(broadcast, "get_channel_layer", return_value=_Layer()),
        patch.object(
            broadcast, "_collect_inner_state", new=AsyncMock(return_value={}),
        ),
    )


async def _repondre(perception, texte="réponse privée"):
    """Le tour complet — processeur réel, diffusion réelle, modèle factice."""
    from old.backend.configs.service import config_service
    from old.backend.emotion.types import Emotion, EmotionData
    from old.backend.pipeline import processor
    from old.backend.pipeline.context import ConversationContext

    ok = (texte, EmotionData(emotion=Emotion.HAPPY, intensity=0.5), [])
    layer, inner = _stubs_de_diffusion()
    with patch.object(config_service, "get", return_value=60), \
         patch.object(processor.identity_resolver, "ingest_message",
                      new=AsyncMock()), \
         patch.object(processor.emotion_engine, "ensure_person_loaded",
                      new=AsyncMock()), \
         patch.object(processor.emotion_engine, "save_snapshot",
                      new=AsyncMock()), \
         patch.object(processor, "gather_context",
                      new=AsyncMock(return_value=ConversationContext())), \
         patch.object(processor, "call_ai_and_parse",
                      new=AsyncMock(return_value=ok)), \
         patch.object(processor, "persist_user_message",
                      new=AsyncMock(return_value=1)), \
         patch.object(processor, "persist_assistant_message",
                      new=AsyncMock(return_value=2)), \
         patch.object(processor, "emit_communication_event", new=AsyncMock()), \
         patch.object(processor, "publish_turn_completed", new=AsyncMock()), \
         patch.object(processor, "_compute_thinking_delay", return_value=0.0), \
         layer, inner:
        return await processor.process_message(perception)


def _parole_proactive(texte="tu me manques"):
    """Ce que la conscience produit : une sortie sans salon d'origine."""
    from old.backend.emotion.types import Emotion, EmotionData
    from old.backend.pipeline.processor import SpeechOutput

    return SpeechOutput(
        text=texte,
        emotion_data=EmotionData(emotion=Emotion.HAPPY, intensity=0.3),
        emotion_name="happy", emotion_intensity=0.3, emotion_state={},
        tool_calls=[],
    )


async def _diffuser(output, person_id=PERSON, source="conscience"):
    from old.backend.pipeline import broadcast

    layer, inner = _stubs_de_diffusion()
    with layer, inner:
        await broadcast.broadcast_to_websocket(output, source, person_id=person_id)


# ── La réponse réactive ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestLaReponseRepartDansSonSalon:

    async def test_une_question_privee_recoit_sa_reponse_en_prive(self, canal):
        """DM puis groupe, même compte : la réponse au DM va au DM.

        C'est le défaut lui-même : la question privée attend derrière le
        worker, un message de groupe arrive entre-temps, et l'adresse
        « dernier salon vu » envoyait la réponse privée dans le groupe.
        """
        en_prive = await _handle(canal, _update(
            "dis-moi un truc perso", chat_id=DM_CHAT, chat_type="private",
        ))
        await _handle(canal, _update(
            "salut tout le monde", chat_id=GROUP_CHAT, chat_type="supergroup",
        ))

        await _repondre(en_prive)

        assert canal.fake.sent == [(str(DM_CHAT), "réponse privée")]

    async def test_un_message_de_groupe_recoit_sa_reponse_dans_le_groupe(self, canal):
        """L'inverse tient aussi : l'adresse privée mémorisée ne détourne
        pas la réponse à une question posée dans le groupe."""
        await _handle(canal, _update(
            "coucou", chat_id=DM_CHAT, chat_type="private",
        ))
        en_groupe = await _handle(canal, _update(
            "et ici ?", chat_id=GROUP_CHAT, chat_type="supergroup",
        ))

        await _repondre(en_groupe, "réponse au groupe")

        assert canal.fake.sent == [(str(GROUP_CHAT), "réponse au groupe")]

    async def test_le_tour_emporte_son_salon(self, canal):
        perception = await _handle(canal, _update(
            "hop", chat_id=GROUP_CHAT, chat_type="supergroup",
        ))
        assert perception.metadata["reply_ref"] == str(GROUP_CHAT)
        assert perception.metadata["is_public"] is True


# ── L'adresse proactive ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestLAdresseProactiveResteLePrive:

    async def test_un_groupe_ne_remplace_pas_l_adresse_privee(self, canal):
        from old.backend.communication.presence import presence_registry

        await _handle(canal, _update(
            "coucou", chat_id=DM_CHAT, chat_type="private",
        ))
        await _handle(canal, _update(
            "hop", chat_id=GROUP_CHAT, chat_type="supergroup",
        ))

        entry = presence_registry.resolve_on(PERSON, "telegram")
        assert entry is not None
        assert entry.delivery_ref == str(DM_CHAT)
        # Le handle persistant non plus : la chaîne vide garde l'existant.
        refs = [c.kwargs["delivery_ref"] for c in canal.link.await_args_list]
        assert refs == [str(DM_CHAT), ""]

    async def test_un_premier_contact_en_groupe_ne_memorise_aucune_adresse(self, canal):
        from old.backend.communication.presence import presence_registry

        await _handle(canal, _update(
            "hop", chat_id=GROUP_CHAT, chat_type="supergroup",
        ))

        entry = presence_registry.resolve_on(PERSON, "telegram")
        assert entry is not None, "la personne reste joignable pour la réponse"
        assert entry.delivery_ref == ""

    async def test_une_parole_proactive_va_au_prive(self, canal):
        """Après DM puis groupe, ce que la conscience dit d'elle-même à
        Thomas part dans le DM — pas dans le dernier salon vu."""
        await _handle(canal, _update(
            "coucou", chat_id=DM_CHAT, chat_type="private",
        ))
        await _handle(canal, _update(
            "hop", chat_id=GROUP_CHAT, chat_type="supergroup",
        ))

        await _diffuser(_parole_proactive())

        assert canal.fake.sent == [(str(DM_CHAT), "tu me manques")]

    async def test_une_parole_proactive_ne_part_jamais_dans_un_groupe(self, canal):
        """Sans adresse privée connue, l'envoi proactif est abandonné —
        jamais posté dans le groupe où le compte a été aperçu."""
        await _handle(canal, _update(
            "hop", chat_id=GROUP_CHAT, chat_type="supergroup",
        ))

        await _diffuser(_parole_proactive())

        assert canal.fake.sent == []


# ── La copie adressée ───────────────────────────────────────────────


class TestAddressed:

    def test_ne_touche_que_le_canal_de_la_question(self):
        from old.backend.communication.presence import Interlocutor
        from old.backend.pipeline.broadcast import _addressed

        tg = Interlocutor(
            person_id="tg_1", channel="telegram", kind="module",
            delivery_ref="111",
        )
        autre = Interlocutor(
            person_id="tg_1", channel="discord", kind="module",
            delivery_ref="d-1",
        )

        assert _addressed(tg, "-222", "telegram").delivery_ref == "-222"
        assert _addressed(autre, "-222", "telegram").delivery_ref == "d-1"
        assert _addressed(tg, None, "telegram").delivery_ref == "111"
        # L'entrée du registre n'est pas modifiée, seule la copie l'est.
        assert tg.delivery_ref == "111"
