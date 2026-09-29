"""Telegram, de bout en bout (faux robot, vrai noyau).

- un salon non autorisé ne laisse aucune trace, et on le lui dit — une fois ;
- au-delà de la limite par compte, on le dit ;
- en privé elle répond dans la conversation privée ; dans un groupe elle
  entend tout mais ne répond qu'à ce qui lui est adressé, dans le groupe ;
- un message relivré par Telegram n'est traité qu'une fois ;
- seules les conversations privées deviennent des adresses où lui écrire.
"""

from __future__ import annotations

from types import SimpleNamespace

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


def setup(tmp_path, config=None):
    router = Router(Deliveries())
    kernel, clock, llm, _ = build(tmp_path, respond, ports={"delivery": router})
    bot = FakeBot()
    t = [0.0]
    channel = TelegramChannel(KernelPort(kernel), bot, config or TelegramConfig(), monotonic=lambda: t[0],
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

    out, sent = run(tmp_path, scenario, TelegramConfig(rate=(20, 10.0)))
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
