"""Telegram, de bout en bout (faux robot, vrai noyau).

- fermé par défaut : la conversation privée des propriétaires, la liste
  blanche, ou une ouverture explicite ;
- un salon non admis ne laisse aucune trace ; si on s'adresse à elle, on le
  lui dit — une fois ; le bavardage, lui, est ignoré sans un mot ;
- au-delà de la limite par compte, on le dit ;
- en privé elle répond dans la conversation privée ; dans un groupe elle
  entend tout mais ne répond qu'à ce qui lui est adressé, dans le groupe ;
- un message relivré par Telegram n'est traité qu'une fois, une édition jamais ;
- un texte long est découpé, sans jetons de voix ; une pensée ne part jamais en
  message ; sans robot, une livraison est à réessayer ;
- seules les conversations privées deviennent des adresses où lui écrire.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.adapters.preprocess import LocalPreprocessor
from mika.adapters.telegram import Inbound, Media, TelegramChannel, TelegramConfig
from mika.adapters.telegram.channel import REFUSED, TOO_FAST
from mika.adapters.telegram.ptb import inbound_from_update
from mika.app.delivery import Router
from mika.app.mindport import KernelPort
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.ports.llm import LLMResponse
from mika.runtime.effects import with_content
from mika.sim.clock import run_virtual
from tests.fixtures.mika import Deliveries, boot, build


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.files: dict[str, bytes] = {}
        self.downloaded: list[str] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    async def download(self, file_id: str) -> bytes:
        self.downloaded.append(file_id)
        return self.files[file_id]


def respond(req):
    if req.role in ("extract", "profile"):
        return LLMResponse("{}")
    return LLMResponse("coucou toi [EMOTION:happy:0.6]")


#: ces scénarios-ci parlent de ce qui se passe une fois admis : ouvert explicitement
OPEN = TelegramConfig(open_to_all=True)


def setup(tmp_path, config=None):
    router = Router(Deliveries())
    kernel, clock, llm, _ = build(tmp_path, respond, ports={"delivery": router})
    bot = FakeBot()
    t = [0.0]
    channel = TelegramChannel(KernelPort(kernel), bot, config or OPEN, monotonic=lambda: t[0],
                              preprocess=LocalPreprocessor(None))
    router.telegram = channel
    return kernel, clock, bot, channel, t


def msg(update_id, text, *, chat=1, user=1, kind="private", name="Alice", **kw):
    return Inbound(update_id, chat, kind, user, name, text, **kw)


def perceptions(kernel):
    return [e for e in kernel.mind.store.read() if e.type == rt.PERCEPTION_RECEIVED.name]


def run(tmp_path, scenario, config=None):
    kernel, clock, bot, channel, t = setup(tmp_path, config)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, bot, channel, t)
        finally:
            await kernel.lanes.join()
            await kernel.stop()

    return run_virtual(clock, main)


def test_a_chat_outside_the_allow_list_leaves_no_trace_and_is_told_once(tmp_path):
    async def scenario(kernel, bot, channel, t):
        first = await channel.receive(msg(1, "salut", chat=99, user=99))
        second = await channel.receive(msg(2, "t'es là ?", chat=99, user=99))
        s = kernel.mind.root.slices["identity"]
        return first, second, perceptions(kernel), "tg_99" in s.handles, list(bot.sent)

    first, second, seen, known, sent = run(tmp_path, scenario, TelegramConfig(allowed_chats=frozenset({1})))
    assert (first, second) == ("refused", "refused")
    assert not seen and not known
    assert sent == [(99, REFUSED)]


def test_too_many_messages_are_refused_out_loud(tmp_path):
    async def scenario(kernel, bot, channel, t):
        out = [await channel.receive(msg(i, f"message {i}")) for i in range(21)]
        return out, list(bot.sent)

    out, sent = run(tmp_path, scenario, TelegramConfig(rate=(20, 10.0), open_to_all=True))
    assert out[:20] == ["accepted"] * 20 and out[20] == "rate_limited"
    assert (1, TOO_FAST) in sent


def test_a_private_message_is_answered_in_the_private_chat(tmp_path):
    async def scenario(kernel, bot, channel, t):
        status = await channel.receive(msg(1, "salut Mika", chat=42, user=42))
        await kernel.lanes.join()
        frame = kernel.mind.frame()
        return status, list(bot.sent), frame.get(identity_c.REACHABLE("tg_42"))

    status, sent, reachable = run(tmp_path, scenario)
    assert status == "accepted"
    assert sent == [(42, "coucou toi")]  # sans la balise d'émotion
    assert reachable == ("tg_42",)


def test_in_a_group_she_hears_everything_but_answers_only_when_addressed_and_in_the_group(tmp_path):
    async def scenario(kernel, bot, channel, t):
        await channel.receive(msg(1, "vous avez vu le match ?", chat=-5, user=7, kind="group", name="Bob"))
        await kernel.lanes.join()
        quiet = list(bot.sent)
        await channel.receive(msg(2, "Mika, t'en penses quoi ?", chat=-5, user=7, kind="group", name="Bob"))
        await kernel.lanes.join()
        frame = kernel.mind.frame()
        return quiet, list(bot.sent), len(perceptions(kernel)), frame.get(identity_c.REACHABLE("tg_7"))

    quiet, sent, heard, reachable = run(tmp_path, scenario)
    assert quiet == []  # entendu, pas adressé : pas de réponse
    assert heard == 2
    assert sent == [(-5, "coucou toi")]  # la réponse part dans le groupe, pas en privé
    assert reachable == ()  # un groupe n'est pas une adresse où lui écrire d'elle-même


def test_a_redelivered_update_is_handled_once(tmp_path):
    async def scenario(kernel, bot, channel, t):
        a = await channel.receive(msg(7, "salut"))
        b = await channel.receive(msg(7, "salut"))
        await kernel.lanes.join()
        return a, b, len(perceptions(kernel)), list(bot.sent)

    a, b, n, sent = run(tmp_path, scenario)
    assert (a, b) == ("accepted", "duplicate") and n == 1 and len(sent) == 1


def test_inbound_from_a_real_update_shape():
    me = 555
    update = SimpleNamespace(update_id=3, message=SimpleNamespace(
        text="hey @MikaBot tu dors ?", chat=SimpleNamespace(id=-10, type="supergroup"),
        from_user=SimpleNamespace(id=7, is_bot=False, first_name="Bob", last_name="L", username="bobl"),
        reply_to_message=None))
    got = inbound_from_update(update, me, "MikaBot")
    assert got == Inbound(3, -10, "supergroup", 7, "Bob L", "hey @MikaBot tu dors ?", mentions_me=True)
    reply = SimpleNamespace(update_id=4, message=SimpleNamespace(
        text="oui", chat=SimpleNamespace(id=-10, type="group"),
        from_user=SimpleNamespace(id=7, is_bot=False, first_name="Bob", last_name="", username=""),
        reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=me))))
    assert inbound_from_update(reply, me, "MikaBot").reply_to_me
    robot = SimpleNamespace(update_id=5, message=SimpleNamespace(
        text="bip", chat=SimpleNamespace(id=1, type="private"),
        from_user=SimpleNamespace(id=9, is_bot=True, first_name="X", last_name="", username=""),
        reply_to_message=None))
    assert inbound_from_update(robot, me, "MikaBot") is None


def test_attachments_are_fetched_only_once_admitted_and_read_at_the_edge(tmp_path):
    async def scenario(kernel, bot, channel, t):
        bot.files = {"doc1": "Liste : café, pain".encode(), "doc2": b"x", "big": b"y"}
        note = Media("doc1", "courses.txt", "text/plain", 20)
        await channel.receive(msg(1, "regarde", media=(note,)))  # privé : lu
        await channel.receive(msg(2, "", chat=-5, kind="group", media=(Media("doc2", "a.txt", "text/plain", 1),)))
        await channel.receive(msg(3, "tiens", media=(Media("big", "film.mp4", "video/mp4", 50_000_000),)))
        await kernel.lanes.join()
        texts = [with_content(kernel.mind, kernel.mind.decode(e)).data for e in perceptions(kernel)]
        return texts, list(bot.downloaded)

    texts, downloaded = run(tmp_path, scenario)
    assert downloaded == ["doc1"]  # le bavardage d'un groupe et un fichier trop gros ne sont pas téléchargés
    first = texts[0]
    assert "regarde" in first.text.text and "café, pain" in first.text.text and first.attachments[0].extracted
    assert "trop gros" in texts[-1].text.text and not texts[-1].attachments[0].extracted


def test_a_refused_chat_downloads_nothing(tmp_path):
    async def scenario(kernel, bot, channel, t):
        bot.files = {"p": b"\xff\xd8"}
        status = await channel.receive(msg(1, "", chat=42, media=(Media("p", "photo.jpg", "image/jpeg", 2),)))
        return status, list(bot.downloaded)

    status, downloaded = run(tmp_path, scenario, TelegramConfig(allowed_chats=frozenset({1})))
    assert status == "refused" and downloaded == []


def test_media_from_a_real_update_shape():
    update = SimpleNamespace(update_id=9, message=SimpleNamespace(
        text=None, caption="mon chat", chat=SimpleNamespace(id=1, type="private"),
        from_user=SimpleNamespace(id=7, is_bot=False, first_name="Bob", last_name="", username=""),
        reply_to_message=None, voice=None, audio=None, document=None,
        photo=[SimpleNamespace(file_id="small", file_size=10), SimpleNamespace(file_id="large", file_size=900)]))
    got = inbound_from_update(update, 555, "MikaBot")
    assert got is not None and got.text == "mon chat" and got.media == (Media("large", "photo.jpg", "image/jpeg", 900),)


# ── Fermé par défaut ──────────────────────────────────────────────────────


def test_closed_by_default_only_an_owners_private_chat_is_heard(tmp_path):
    """Sans liste blanche ni ouverture explicite : la propriétaire en privé, personne d'autre. Le
    bavardage d'un groupe inconnu est ignoré sans un mot ; s'y adresser à elle reçoit un refus, une fois."""
    async def scenario(kernel, bot, channel, t):
        owner = await channel.receive(msg(1, "salut", chat=42, user=42))
        stranger = await channel.receive(msg(2, "salut", chat=99, user=99))
        chatter = [await channel.receive(msg(10 + i, "on mange où ?", chat=-7, user=8, kind="group", name="Bob"))
                   for i in range(3)]
        after_chatter = list(bot.sent)
        called = await channel.receive(msg(20, "Mika, t'es là ?", chat=-7, user=8, kind="group", name="Bob"))
        await kernel.lanes.join()
        return owner, stranger, chatter, after_chatter, called, list(bot.sent), len(perceptions(kernel))

    owner, stranger, chatter, after_chatter, called, sent, heard = run(
        tmp_path, scenario, TelegramConfig(owners=frozenset({42})))
    assert owner == "accepted" and stranger == "refused" and called == "refused"
    assert chatter == ["refused"] * 3 and heard == 1
    assert (99, REFUSED) in sent
    assert (-7, REFUSED) not in after_chatter  # le bavardage d'un groupe non admis : pas un mot
    assert sent.count((-7, REFUSED)) == 1  # s'adresser à elle : un refus
    assert TelegramConfig().closed and not TelegramConfig(owners=frozenset({1})).closed


def test_an_edited_message_gets_no_second_answer_and_a_message_is_deduplicated_by_its_id(tmp_path):
    user = SimpleNamespace(id=7, is_bot=False, first_name="Zoé", last_name="", username="zoe")
    chat = SimpleNamespace(id=7, type="private")

    def message(text):
        return SimpleNamespace(message_id=55, text=text, caption=None, from_user=user, chat=chat,
                               reply_to_message=None, photo=None, voice=None, audio=None, document=None)

    edited = SimpleNamespace(update_id=101, message=None, edited_message=message("tu viens ce soir ? (à 20h)"))
    assert inbound_from_update(edited, 999, "mika_bot") is None  # une édition n'est pas un nouveau message

    async def scenario(kernel, bot, channel, t):
        first = inbound_from_update(SimpleNamespace(update_id=100, message=message("tu viens ce soir ?")), 999,
                                    "mika_bot")
        again = inbound_from_update(SimpleNamespace(update_id=102, message=message("tu viens ce soir ?")), 999,
                                    "mika_bot")  # relivré sous un autre numéro de mise à jour
        out = [await channel.receive(first), await channel.receive(again)]
        await kernel.lanes.join()
        return out, len(perceptions(kernel)), list(bot.sent)

    out, n, sent = run(tmp_path, scenario)
    assert out == ["accepted", "duplicate"] and n == 1 and len(sent) == 1


def test_mentions_are_read_from_the_message_entities():
    MessageEntity = pytest.importorskip("telegram").MessageEntity  # l'extra [telegram] : le vrai type

    user = SimpleNamespace(id=7, is_bot=False, first_name="Bob", last_name="", username="bob")
    group = SimpleNamespace(id=-5, type="supergroup")

    def update(text, entities):
        return SimpleNamespace(update_id=1, message=SimpleNamespace(
            message_id=3, text=text, caption=None, from_user=user, chat=group, reply_to_message=None,
            photo=None, voice=None, audio=None, document=None, entities=entities, caption_entities=None))

    other = update("regardez @mika_bot_officiel", [MessageEntity(MessageEntity.MENTION, 9, 18)])
    me = update("@mika_bot tu dors ?", [MessageEntity(MessageEntity.MENTION, 0, 9)])
    by_id = update("Mika tu dors ?", [MessageEntity(MessageEntity.TEXT_MENTION, 0, 4,
                                                    user=SimpleNamespace(id=999))])
    assert not inbound_from_update(other, 999, "mika_bot").mentions_me
    assert inbound_from_update(me, 999, "mika_bot").mentions_me
    assert inbound_from_update(by_id, 999, "mika_bot").mentions_me


def test_she_answers_to_her_own_name_in_a_group():
    zoe = TelegramChannel(None, FakeBot(), TelegramConfig(name="Zoé", open_to_all=True))  # type: ignore[arg-type]
    assert zoe.addressed(msg(1, "Zoé, t'en penses quoi ?", chat=-5, kind="group"))
    assert not zoe.addressed(msg(2, "Mika, t'en penses quoi ?", chat=-5, kind="group"))
    assert not zoe.addressed(msg(3, "Zoéline est là", chat=-5, kind="group"))


def test_start_is_an_arrival(tmp_path):
    user = SimpleNamespace(id=42, is_bot=False, first_name="Léa", last_name="", username="")
    command = SimpleNamespace(update_id=5, message=SimpleNamespace(
        message_id=1, text="/start", caption=None, from_user=user, chat=SimpleNamespace(id=42, type="private"),
        reply_to_message=None, photo=None, voice=None, audio=None, document=None))

    async def scenario(kernel, bot, channel, t):
        status = await channel.receive(inbound_from_update(command, 999, "mika_bot", opened=True))
        await kernel.lanes.join()
        texts = [with_content(kernel.mind, kernel.mind.decode(e)).data.text.text for e in perceptions(kernel)]
        return status, texts, list(bot.sent)

    status, texts, sent = run(tmp_path, scenario)
    assert status == "accepted" and "ouvrir la conversation" in texts[0] and "/start" not in texts[0]
    assert sent  # elle répond à l'arrivée


# ── Livrer ────────────────────────────────────────────────────────────────


def _delivery(text, **kw):
    from mika.ports.delivery import Delivery

    return Delivery(key=kw.pop("key", "k1"), target=kw.pop("target", "tg_42"), channel="telegram",
                    room=kw.pop("room", None), text=text, message_id=1, **kw)


async def test_a_long_reply_is_split_never_cut_and_carries_no_voice_tokens():
    bot = FakeBot()
    channel = TelegramChannel(None, bot, OPEN)  # type: ignore[arg-type]
    long = " ".join(f"Phrase numéro {i}, assez longue pour remplir." for i in range(300))
    assert await channel.deliver(_delivery("[SIGH] Bon [PAUSE:500ms]. " + long + " [EMOTION:happy:0.6]"))
    parts = [text for _chat, text in bot.sent]
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts)
    joined = " ".join(parts)
    assert "Phrase numéro 299, assez longue pour remplir." in joined
    assert "[" not in joined and joined.startswith("Bon.")


async def test_a_thought_never_leaves_as_a_message_and_a_failure_is_said_plainly():
    from mika.adapters.telegram.channel import FAILED
    from mika.ports import delivery as delivery_p

    bot = FakeBot()
    channel = TelegramChannel(None, bot, OPEN)  # type: ignore[arg-type]
    assert await channel.deliver(_delivery("tiens, si je lui écrivais", persona="inner"))
    assert await channel.deliver(_delivery("", key="k2", kind=delivery_p.REPLY_ABSTAINED, reply_to=3))
    assert bot.sent == []
    assert await channel.deliver(_delivery("TimeoutError()", key="k3", kind=delivery_p.REPLY_FAILED, reply_to=3))
    assert bot.sent == [(42, FAILED)]  # jamais le détail technique


async def test_without_the_robot_a_telegram_delivery_is_retried_not_dropped():
    class Web:
        def __init__(self) -> None:
            self.got: list = []

        async def deliver(self, d):
            self.got.append(d)
            return True

    web = Web()
    router = Router(web)
    assert await router.deliver(_delivery("coucou")) is False  # le robot n'est pas (encore) là : à réessayer
    assert await router.deliver(_delivery("une pensée", persona="inner")) is True
    assert [d.text for d in web.got] == ["une pensée"]  # une pensée passe par l'écran, jamais en message


async def test_updates_run_in_parallel_across_chats_and_in_order_within_one():
    """Une photo qui se télécharge dans une conversation ne retient pas les autres ; dans une même
    conversation, les messages passent dans l'ordre (un verrou par chat)."""
    from mika.adapters.telegram.ptb import ChatLocks, Poller

    order: list[tuple[str, int]] = []

    class Slow:
        async def receive(self, m):
            order.append(("début", m.update_id))
            await asyncio.sleep(0.2 if m.update_id == 1 else 0.0)
            order.append(("fin", m.update_id))
            return "accepted"

    poller = Poller.__new__(Poller)
    poller.channel, poller.locks = Slow(), ChatLocks()
    await asyncio.gather(poller._handle(msg(1, "regarde", chat=5, user=5)),
                         poller._handle(msg(2, "alors ?", chat=5, user=5)),
                         poller._handle(msg(3, "salut", chat=6, user=6)))
    assert order.index(("fin", 1)) < order.index(("début", 2))  # même conversation : dans l'ordre
    assert order.index(("fin", 3)) < order.index(("fin", 1))  # une autre conversation n'attend pas
