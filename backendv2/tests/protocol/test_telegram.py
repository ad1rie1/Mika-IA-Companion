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
- une question abandonnée parce qu'il était trop tard reçoit, en privé, une
  excuse honnête (pas « réessaie dans un instant » des heures après) ; dans un
  salon, rien ;
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
        #: (conversation, texte, message cité) — seulement ce qui en cite un
        self.quoted: list[tuple[int, str, int]] = []

    async def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None:
        self.sent.append((chat_id, text))
        if reply_to is not None:
            self.quoted.append((chat_id, text, reply_to))

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


async def test_a_question_abandoned_too_late_gets_an_honest_apology_in_private_and_nothing_in_a_room():
    """INT-7 : « Désolée, je n'arrive pas à te répondre là tout de suite… Réessaie dans un instant ? » des heures
    après la question serait faux ; se taire laisserait la personne sans rien. En privé, elle s'excuse de n'avoir
    pas pu répondre plus tôt et invite à redire ; dans un salon, la conversation est passée à autre chose : rien.
    Contre-exemple : une panne sur le moment dit toujours « réessaie dans un instant »."""
    from mika.adapters.telegram.channel import FAILED, LATE
    from mika.ports import delivery as delivery_p

    bot = FakeBot()
    channel = TelegramChannel(None, bot, OPEN)  # type: ignore[arg-type]
    late = {"kind": delivery_p.REPLY_FAILED, "reply_to": 3}
    assert await channel.deliver(_delivery("trop tard pour répondre", key="k1", **late))
    assert await channel.deliver(_delivery("trop tard pour répondre", key="k2", room="tg_chat_-100", **late))
    assert await channel.deliver(_delivery("TimeoutError()", key="k3", **late))
    assert bot.sent == [(42, LATE), (42, FAILED)]


def test_the_engine_says_too_late_the_way_telegram_reads_it(tmp_path):
    """Le lien entre le moteur et l'adaptateur : une question posée sur Telegram, un arrêt d'une heure, et la
    reprise l'abandonne « trop tard » — la livraison qui en part est lue par Telegram comme telle."""
    from mika.adapters.telegram.channel import LATE
    from mika.app import composition
    from mika.ports import delivery as delivery_p
    from mika.sim.clock import SimClock
    from mika.sim.llm.scripted import ScriptedLLM
    from mika.sim.world import Driver
    from tests.fixtures.mika import AFTERNOON

    clock = SimClock(AFTERNOON)
    llm = ScriptedLLM(clock, lambda r: LLMResponse("me revoilà [EMOTION:happy:0.5]"),
                      latency=lambda r: 20.0 if r.role == "reply" else 1.0)
    driver = Driver(tmp_path, composition.for_simulation(), llm, clock)
    told: list = []

    async def main():
        await driver.boot()
        assert driver.transport is not None
        heard = driver.transport.deliver

        async def deliver(d):
            told.append(d)
            return await heard(d)

        driver.transport.deliver = deliver  # type: ignore[method-assign]
        await driver.say("tg_7", "t'es là ?", wait=False)
        await asyncio.sleep(2)
        await driver.crash()
        await asyncio.sleep(3600)  # une heure d'arrêt
        await driver.boot()
        await asyncio.sleep(5)
        await driver.stop()

    run_virtual(clock, main)
    failed = [d for d in told if d.kind == delivery_p.REPLY_FAILED and d.target == "tg_7"]
    assert failed, [d.kind for d in told]
    bot = FakeBot()
    channel = TelegramChannel(None, bot, OPEN)  # type: ignore[arg-type]
    assert asyncio.run(channel.deliver(failed[-1]))
    assert bot.sent == [(7, LATE)]


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


# ── Elle a l'air là, elle lit tout, et on l'appaire (ADR 0057) ─────────────


class TypingBot(FakeBot):
    """Un robot qui sait montrer « en train d'écrire… »."""

    def __init__(self) -> None:
        super().__init__()
        self.typing: list[int] = []

    async def send_typing(self, chat_id: int) -> None:
        self.typing.append(chat_id)


class FakePort:
    """Le cœur réduit à l'admission : il accepte — ou, endormie, retient la réponse pour son réveil."""

    def __init__(self, *, held: bool = False) -> None:
        self.held = held
        self.seen: list = []

    async def perceive(self, p, *, dedupe_key=None):
        from mika.contracts.entry import Admission

        self.seen.append(p)
        return Admission("accepted", seq=len(self.seen), held=self.held)


def virtual_sleep(t: list[float]):
    async def sleep(seconds: float) -> None:
        t[0] += seconds
        await asyncio.sleep(0)

    return sleep


async def _turns(n: int = 6) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def test_she_is_seen_typing_until_she_answers_bounded_and_never_while_she_sleeps():
    """G-4 : de quelques secondes à deux minutes sans signe de vie, elle paraissait absente. Dès qu'un message
    adressé est accepté : « en train d'écrire… », renouvelé jusqu'à sa réponse (ou son silence), borné à deux
    minutes. Endormie, sa réponse attend son réveil : rien ne s'affiche. Contre-exemple : un robot sans
    ``send_typing`` ne casse rien."""
    from mika.adapters.telegram.channel import TYPING_EVERY_S, TYPING_MAX_S
    from mika.ports import delivery as delivery_p

    t = [0.0]
    bot = TypingBot()
    channel = TelegramChannel(FakePort(), bot, OPEN, monotonic=lambda: t[0], sleep=virtual_sleep(t))
    assert await channel.receive(msg(1, "tu fais quoi ?", chat=42, user=42)) == "accepted"
    await _turns()
    assert len(bot.typing) >= 2 and set(bot.typing) == {42}  # renouvelé tant qu'elle compose
    assert await channel.deliver(_delivery("je lis un manga !", target="tg_42"))
    stopped = len(bot.typing)
    await _turns()
    assert len(bot.typing) == stopped  # sa réponse est partie : elle n'écrit plus
    assert await channel.receive(msg(2, "et sinon ?", chat=42, user=42)) == "accepted"
    await _turns(200)  # la réponse ne vient pas
    assert len(bot.typing) - stopped <= TYPING_MAX_S / TYPING_EVERY_S + 1  # borné : deux minutes au plus
    assert await channel.receive(msg(3, "allo ?", chat=42, user=42)) == "accepted"
    await _turns()
    shown = len(bot.typing)
    assert await channel.deliver(_delivery("", key="k9", target="tg_42", kind=delivery_p.REPLY_ABSTAINED,
                                           reply_to=3))
    await _turns()
    assert len(bot.typing) == shown  # elle a choisi de se taire : elle n'écrit plus non plus

    asleep_bot = TypingBot()
    asleep = TelegramChannel(FakePort(held=True), asleep_bot, OPEN, monotonic=lambda: t[0],
                             sleep=virtual_sleep(t))
    assert await asleep.receive(msg(4, "tu dors ?", chat=7, user=7)) == "accepted"
    await _turns()
    assert asleep_bot.typing == []  # endormie : sa réponse attend son réveil

    plain = TelegramChannel(FakePort(), FakeBot(), OPEN, monotonic=lambda: t[0], sleep=virtual_sleep(t))
    assert await plain.receive(msg(5, "coucou", chat=8, user=8)) == "accepted"
    await channel.close()


def test_a_sticker_a_video_and_a_gif_are_perceived_in_one_line_not_ignored(tmp_path):
    """G-4 : un autocollant ne passait pas le filtre, sans un mot — et ils comptent dans une conversation intime.
    Perçu en une ligne, avec son émoji ; une vidéo ou un GIF aussi, jamais téléchargés. Contre-exemple : ce qui
    n'a ni texte, ni fichier, ni rien à percevoir reste ignoré."""
    user = SimpleNamespace(id=42, is_bot=False, first_name="Léa", last_name="", username="")

    def update(i, **kw):
        base = dict(message_id=i, text=None, caption=None, from_user=user, reply_to_message=None, photo=None,
                    voice=None, audio=None, document=None, chat=SimpleNamespace(id=42, type="private"))
        return SimpleNamespace(update_id=i, message=SimpleNamespace(**{**base, **kw}))

    sticker = inbound_from_update(update(1, sticker=SimpleNamespace(emoji="😂")), 999, "mika_bot")
    assert sticker is not None and sticker.noted == "(t'envoie un autocollant 😂)"
    gif = inbound_from_update(update(2, animation=SimpleNamespace(file_id="a"), document=SimpleNamespace(
        file_id="a", file_name="anim.mp4", mime_type="video/mp4", file_size=10)), 999, "mika_bot")
    assert gif is not None and gif.noted.startswith("(t'envoie un GIF") and gif.media == ()  # pas un document
    video = inbound_from_update(update(3, video=SimpleNamespace(file_id="v"), caption="regarde ça"), 999,
                                "mika_bot")
    assert video is not None and video.text == "regarde ça" and "une vidéo" in video.noted
    assert inbound_from_update(update(4), 999, "mika_bot") is None

    async def scenario(kernel, bot, channel, t):
        status = await channel.receive(msg(1, "", chat=42, user=42, noted=sticker.noted))
        captioned = await channel.receive(msg(2, "regarde ça", chat=42, user=42, noted=video.noted))
        texts = [with_content(kernel.mind, kernel.mind.decode(e)).data for e in perceptions(kernel)]
        return status, captioned, texts

    status, captioned, seen = run(tmp_path, scenario)
    assert (status, captioned) == ("accepted", "accepted")
    assert seen[0].text.text == "(t'envoie un autocollant 😂)"
    assert seen[1].text.text == "regarde ça\n(t'envoie une vidéo, que tu ne peux pas regarder)"
    assert seen[1].typed_chars == len("regarde ça")  # ce qu'elle a tapé, à part de ce qu'elle a envoyé


def test_a_long_message_is_read_up_to_telegram_s_own_limit(tmp_path):
    """G-4 : au-delà de 2000 caractères, elle répondait « tu peux faire plus court ? » — à un message que Telegram
    permet. Elle lit jusqu'à 4096 (la limite de Telegram) ; seul le prompt coupe."""
    long = "Il faut que je te raconte ma journée. " * 80  # ~3000 caractères

    async def scenario(kernel, bot, channel, t):
        status = await channel.receive(msg(1, long, chat=42, user=42))
        return status, [with_content(kernel.mind, kernel.mind.decode(e)).data.text.text for e in perceptions(kernel)]

    status, texts = run(tmp_path, scenario)
    assert 2000 < len(long) <= 4096
    assert status == "accepted" and texts == [long]


def test_in_a_room_her_answer_quotes_the_message_it_answers(tmp_path):
    """G-4 : dans un salon actif, on ne savait pas à qui elle répondait. Sa réponse cite le message d'origine ;
    en privé, rien à citer."""
    async def scenario(kernel, bot, channel, t):
        await channel.receive(msg(1, "Mika, t'en penses quoi ?", chat=-5, user=7, kind="group", name="Bob",
                                  message_id=77))
        await kernel.lanes.join()
        await channel.receive(msg(2, "salut Mika", chat=42, user=42, message_id=78))
        await kernel.lanes.join()
        return list(bot.sent), list(bot.quoted)

    sent, quoted = run(tmp_path, scenario)
    assert quoted == [(-5, "coucou toi", 77)]
    assert (42, "coucou toi") in sent and not [q for q in quoted if q[0] == 42]


async def test_bold_does_not_leave_as_asterisks_and_without_a_model_she_says_she_is_not_ready():
    """G-4 : « **vraiment** » partait tel quel (le web le met en forme, Telegram non) ; sans modèle configuré, elle
    disait « réessaie dans un instant » indéfiniment. Contre-exemple : une panne passagère dit toujours
    « réessaie »."""
    from mika.adapters.telegram.channel import FAILED, NOT_READY
    from mika.ports import delivery as delivery_p

    bot = FakeBot()
    channel = TelegramChannel(None, bot, OPEN)  # type: ignore[arg-type]
    assert await channel.deliver(_delivery("C'est **vraiment** bien, et *ça* aussi."))
    failed = {"kind": delivery_p.REPLY_FAILED, "reply_to": 3}
    assert await channel.deliver(_delivery("UnconfiguredRole: aucun modèle associé au rôle « reply »", key="k2",
                                           **failed))
    assert await channel.deliver(_delivery("ConnectionError: Failed to connect", key="k3", **failed))
    assert [text for _chat, text in bot.sent] == ["C'est vraiment bien, et *ça* aussi.", NOT_READY, FAILED]


async def test_a_start_code_in_private_pairs_its_sender_as_an_owner_and_she_greets_her():
    """G-3 : fermé par défaut, le robot était inutilisable tant qu'on ne connaissait pas son identifiant. Le code
    d'appairage, envoyé en privé (``/start <code>``), fait de son auteur une propriétaire — et c'est sa première
    arrivée. Contre-exemples : sans code, un faux code, ou dans un groupe, rien n'est perçu ; les essais sont
    bornés (au-delà, le code n'est même plus vérifié)."""
    from mika.adapters.telegram.channel import PAIR_TRIES_PER_ACCOUNT, PAIR_WRONG, PAIRED

    asked: list[tuple[int, str]] = []

    async def pair(user: int, code: str, name: str) -> str:
        asked.append((user, code))
        return "paired" if code == "K7QF-M3XP" else "wrong"

    port, bot = FakePort(), FakeBot()
    channel = TelegramChannel(port, bot, TelegramConfig(), pair=pair)  # type: ignore[arg-type] — fermé : personne
    assert await channel.receive(msg(1, "salut", chat=42, user=42)) == "refused"
    assert await channel.receive(msg(2, "", chat=42, user=42, opened=True, start_arg="AAAA-BBBB")) == "refused"
    assert await channel.receive(msg(3, "", chat=-5, user=42, kind="group", opened=True,
                                     start_arg="K7QF-M3XP")) == "refused"
    assert port.seen == [] and (42, PAIR_WRONG) in bot.sent
    assert await channel.receive(msg(4, "", chat=42, user=42, opened=True, start_arg="K7QF-M3XP")) == "accepted"
    assert 42 in channel.config.owners and (42, PAIRED) in bot.sent
    assert len(port.seen) == 1 and "ouvrir la conversation" in port.seen[0].text.text
    assert "K7QF" not in port.seen[0].text.text  # le code n'entre jamais au journal
    assert await channel.receive(msg(5, "coucou", chat=42, user=42)) == "accepted"  # sa conversation est admise
    before = len(asked)
    for i in range(PAIR_TRIES_PER_ACCOUNT + 3):
        await channel.receive(msg(10 + i, "", chat=50, user=50, opened=True, start_arg=f"ESSAI-{i}"))
    assert len(asked) - before == PAIR_TRIES_PER_ACCOUNT  # borné par compte
