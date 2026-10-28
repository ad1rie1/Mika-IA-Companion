"""Les messages de son téléphone (ADR 0120), par leurs intentions.

- ce que le téléphone pousse s'écrit au journal, un ``phone.received`` par message, dédoublonné : textes et noms en
  contenus personnels, l'expéditeur sous une clé ``phone:<empreinte>:<nom>`` qui garde le nom de la première fois ;
  un message illisible est écarté seul ; seule une propriétaire est admise, et rien quand c'est coupé ;
- elle les lit (``phone_messages``) en tête-à-tête avec la personne dont c'est le téléphone, seulement les siens,
  cités ; un contact se cherche par un morceau de son nom ;
- une réponse préparée à sa place part vers le téléphone (sans accord du serveur : le geste vaut accord), avec sa
  conversation et son texte ; une autre n'est pas préparée tant qu'elle attend ; son sort revient, une seule fois ;
  sans geste à temps, elle expire ;
- la mémoire relit la conversation une fois posée, comme une des siennes : ce qu'elle en garde est confié par
  l'expéditeur **et** par la personne qui le lui montre, entendu par les deux ; ni note sur elle, ni promesse ;
- oublier un contact efface ses textes, ce qu'elle en retenait, et son nom des enveloppes.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from mika.app import composition
from mika.app.phone import PhoneDesk
from mika.contracts import memory as mc
from mika.contracts import phone as c
from mika.contracts import runtime as rt
from mika.faculties.identity import audience_for
from mika.kernel.clock import HOUR, MINUTE
from mika.ports.llm import LLMResponse, ToolCall
from mika.ports.phone import ACCEPTED, DISABLED, FORBIDDEN, IGNORED, SENT
from mika.runtime.effects import with_content
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import SimClock, run_virtual
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import DOC, build, connect
from tests.unit.test_shares import call

US = 1_000_000
START = 1_760_950_000 * US  # le 20 octobre 2026, vers 10 h 46 (Paris)
LEA, MAMAN = "a1" * 16, "b2" * 16
THREAD, FAMILY = "c3" * 16, "d4" * 16


class Phone:
    """Le téléphone, côté serveur : ce que la capacité lui envoie."""

    def __init__(self) -> None:
        self.offers: list[tuple[str, dict]] = []
        self.phones = 1

    async def offer(self, handle: str, body: dict) -> int:
        self.offers.append((handle, body))
        return self.phones


class Model:
    """Le modèle : la relecture d'une conversation lue sur le téléphone garde ce que ``extract`` donne."""

    def __init__(self, extract=None) -> None:
        self.extract = extract
        self.calls: list = []

    def __call__(self, req):
        self.calls.append(req)
        if req.role == "extract":
            args = self.extract(req.messages[-1].content) if self.extract else {}
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", args or {}),), stop="tool_use")
        return LLMResponse("D'accord.")


def message(n: int, text: str, *, sender: str = LEA, name: str = "Léa", thread: str = THREAD, own: bool = False,
            app: str = "whatsapp", group: bool = False, title: str = "", at_us: int = START) -> dict:
    return {"id": f"{n:032x}", "app": app, "thread": thread, "title": title, "group": group,
            "sender": "" if own else sender, "name": "" if own else name, "text": text, "time": at_us // 1000 + n,
            "own": own}


def sleep(us: int):
    return asyncio.sleep(us / US)


def journal(kernel, *types) -> list:
    mind = kernel.mind
    names = {t.name for t in types}
    return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type in names]


def live(tmp_path, scenario, *, model=None, overrides=None):
    clock = SimClock(START)
    phone = Phone()
    model = model or Model()
    kernel, clock, llm, _ = build(tmp_path, model, clock=clock, ports={"phone": phone})
    desk = PhoneDesk()
    desk.port = SimpleNamespace(kernel=kernel)

    async def main():
        await kernel.start(configure=lambda k: composition.configure(k, DOC, overrides or {}))
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            return await scenario(kernel, desk, phone, model)
        finally:
            await kernel.lanes.join()
            await kernel.stop()

    return run_virtual(clock, main)


# ── Ce que le téléphone donne ─────────────────────────────────────────────


def test_each_message_is_written_once_with_a_contact_key(tmp_path):
    async def scenario(kernel, desk, phone, model):
        first = await desk.inbox("user_1", {"messages": [
            message(1, "Tu viens samedi ?"), message(2, "On sera chez Inès"),
            message(3, "Oui, j'arrive vers 20 h", own=True),
            {"id": "pas-hex", "app": "whatsapp", "thread": THREAD, "sender": LEA, "text": "x", "time": 1},
            message(4, "   "), message(5, "Une autre appli", app="telegram")]})
        again = await desk.inbox("user_1", {"messages": [message(2, "On sera chez Inès"),
                                                         message(6, "Bisous", name="Léa ❤️ Martin")]})
        return first, again, journal(kernel, c.RECEIVED)

    first, again, received = live(tmp_path, scenario)
    assert first.outcome == ACCEPTED and first.data == {"accepted": 3, "known": 0, "dropped": 3}
    assert again.data == {"accepted": 1, "known": 1, "dropped": 0}
    assert [e.data.text.text for e in received] == ["Tu viens samedi ?", "On sera chez Inès",
                                                    "Oui, j'arrive vers 20 h", "Bisous"]
    lea = received[0].data.sender
    assert lea.startswith("phone:") and lea.endswith(":Léa") and lea.split(":")[1] == c.contact_hash(
        "user_1", "whatsapp", LEA)
    # le nom de la première fois : un contact renommé garde sa clé
    assert [e.data.sender for e in received] == [lea, lea, "", lea]
    own = received[2].data
    assert own.own and own.sender_name is None and own.recipient == "user_1" and own.handle == "user_1"
    assert all(e.data.text.level == int(Sensitivity.PERSONAL) for e in received)
    assert received[0].data.sender_name.text == "Léa" and received[0].data.sent_at == (START // 1000 + 1) * 1000


def test_only_an_owner_and_never_when_it_is_off(tmp_path):
    async def scenario(kernel, desk, phone, model):
        stranger = await desk.inbox("user_2", {"messages": [message(1, "coucou")]})
        return stranger, journal(kernel, c.RECEIVED)

    stranger, received = live(tmp_path, scenario)
    assert stranger.outcome == FORBIDDEN and received == []

    async def off(kernel, desk, phone, model):
        return await desk.inbox("user_1", {"messages": [message(1, "coucou")]}), journal(kernel, c.RECEIVED)

    got, received = live(tmp_path / "off", off, overrides={"phone": {"enabled": False}})
    assert got.outcome == DISABLED and received == []


# ── Les consulter ─────────────────────────────────────────────────────────


def test_she_reads_them_only_with_their_owner(tmp_path):
    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [
            message(1, "Tu viens samedi ?"), message(2, "Le repas est à 13 h", sender=MAMAN, name="Maman",
                                                     thread=FAMILY, group=True, title="Famille")]})
        frame = kernel.mind.frame()
        stranger = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="user_2"))
        room = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="user_1", room="salon"))
        return (await call(kernel, "phone_messages", "user_1"), await call(kernel, "phone_messages", "user_1",
                                                                           contact="fami"),
                await call(kernel, "phone_messages", "user_2", audience=stranger),
                await call(kernel, "phone_messages", "user_1", audience=room),
                await call(kernel, "phone_messages", "user_1", contact="personne"), journal(kernel, c.RECEIVED))

    everything, family, stranger, room, nobody, received = live(tmp_path, scenario)
    lea, maman = received
    assert everything.startswith(phrase("phone.tools.messages.data"))
    assert f"[p{lea.seq}]" in everything and "WhatsApp · Léa : Tu viens samedi ?" in everything
    assert "Maman (groupe « Famille ») : Le repas est à 13 h" in everything
    assert f"[p{maman.seq}]" in family and f"[p{lea.seq}]" not in family
    for refused in (stranger, room):
        assert not refused.ok and refused.content == phrase("phone.tools.messages.not_here")
    assert nobody.content == phrase("phone.tools.messages.none_for", contact="personne")


# ── Répondre à sa place ───────────────────────────────────────────────────


def test_a_reply_goes_to_the_phone_and_its_fate_comes_back_once(tmp_path):
    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Tu viens samedi ?")]})
        [m] = journal(kernel, c.RECEIVED)
        made = await call(kernel, "phone_draft", "user_1", message=f"[p{m.seq}]", body="Oui, j'arrive vers 20 h !")
        twice = await call(kernel, "phone_draft", "user_1", message=f"p{m.seq}", body="Encore ?")
        await sleep(MINUTE)
        offered = kernel.mind.frame().state(c.OWNER)
        [draft] = journal(kernel, c.DRAFTED)
        sent = await desk.settled("user_1", {"items": [{"id": draft.seq, "result": SENT}]})
        late = await desk.settled("user_1", {"items": [{"id": draft.seq, "result": IGNORED},
                                                       {"id": 999_999, "result": SENT}]})
        stranger = await desk.settled("user_2", {"items": [{"id": draft.seq, "result": IGNORED}]})
        return (made, twice, offered, draft, journal(kernel, rt.EFFECT_PROPOSED), sent, late, stranger,
                kernel.mind.frame().state(c.OWNER), list(phone.offers))

    made, twice, offered, draft, proposed, sent, late, stranger, state, offers = live(tmp_path, scenario)
    assert "Oui, j'arrive vers 20 h !" in made and "WhatsApp" in made
    assert not twice.ok and twice.content == phrase("phone.tools.draft.under_way")
    assert draft.data.body.text == "Oui, j'arrive vers 20 h !" and draft.data.to.endswith(":Léa")
    [p] = proposed
    assert p.data.capability == c.SEND and not p.data.approval  # le geste sur le téléphone vaut accord
    assert offered.offers[draft.seq].state == c.OFFERED
    [(handle, body)] = offers
    assert handle == "user_1" and body["id"] == draft.seq and body["thread"] == THREAD and body["to"] == "Léa"
    assert body["text"] == "Oui, j'arrive vers 20 h !" and body["app"] == "whatsapp"
    assert body["exp"] == (draft.at + 2 * HOUR) // 1000
    assert sent.data == {"settled": 1, "unknown": 0} and late.data == {"settled": 1, "unknown": 1}
    assert stranger.outcome == FORBIDDEN  # pas une propriétaire : rien
    assert state.offers[draft.seq].state == SENT  # le premier sort tient


def test_without_a_gesture_in_time_it_expires(tmp_path):
    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Tu viens samedi ?")]})
        [m] = journal(kernel, c.RECEIVED)
        await call(kernel, "phone_draft", "user_1", message=f"p{m.seq}", body="Oui !")
        await sleep(2 * HOUR + MINUTE)
        return kernel.mind.frame().state(c.OWNER), journal(kernel, c.SETTLED)

    state, [settled] = live(tmp_path, scenario)
    assert settled.data.result == c.EXPIRED
    assert [o.state for o in state.offers.values()] == [c.EXPIRED]


def test_no_phone_to_notify_means_it_could_not_leave(tmp_path):
    async def scenario(kernel, desk, phone, model):
        phone.phones = 0
        await desk.inbox("user_1", {"messages": [message(1, "Tu viens samedi ?")]})
        [m] = journal(kernel, c.RECEIVED)
        await call(kernel, "phone_draft", "user_1", message=f"p{m.seq}", body="Oui !")
        await sleep(MINUTE)
        return kernel.mind.frame().state(c.OWNER), journal(kernel, rt.EFFECT_EXECUTED)

    state, [executed] = live(tmp_path, scenario)
    assert not executed.data.ok and executed.data.result == phrase("phone.send.no_phone")
    assert [o.state for o in state.offers.values()] == ["failed"]


# ── Ce qu'elle en retient ─────────────────────────────────────────────────


def lea_moves(prompt: str) -> dict:
    seq = int(prompt.split("[#", 1)[1].split("]", 1)[0])
    return {"croyances": [{"texte": "Léa déménage à Lyon en novembre", "personnes": ["P1"], "messages": [seq],
                           "sensibilite": "personnel", "origine": "observé"}],
            "promesses": [{"texte": "aider Léa à porter les cartons", "a": "P1"}],
            "souvenirs": [{"texte": "J'adore les déménagements", "sur_elle": True, "personnes": [],
                           "messages": []}]}


def test_memory_rereads_the_conversation_once_it_settles(tmp_path):
    model = Model(lea_moves)

    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Je déménage à Lyon en novembre !"),
                                                 message(2, "Trop bien !", own=True)]})
        await sleep(10 * MINUTE)
        early = [r for r in model.calls if r.role == "extract"]
        await sleep(20 * MINUTE)
        return (early, [r for r in model.calls if r.role == "extract"], journal(kernel, mc.BELIEVED),
                journal(kernel, mc.REMEMBERED), journal(kernel, mc.PROMISE_NOTICED),
                journal(kernel, mc.RELAYED_READ), journal(kernel, c.RECEIVED), kernel.mind.frame().state("memory"))

    early, calls, believed, remembered, promised, read, received, memory = live(tmp_path, scenario, model=model)
    assert early == []  # la conversation n'est pas encore posée
    [req] = calls
    prompt = req.messages[-1].content
    assert "Ce qui est vrai de toi" in req.system_stable  # elle sait qui elle est (ADR 0153)
    assert phrase("memory.extraction.render.relayed", owner="Adrien", app="WhatsApp",
                  who="Léa [P1], Adrien [P2]") in prompt
    assert "Je déménage à Lyon en novembre !" in prompt and "Trop bien !" in prompt
    [b] = believed
    lea = received[0].data.sender
    assert b.data.text.text == "Léa déménage à Lyon en novembre"
    # confié par Léa et par la personne qui le lui montre ; entendu par les deux
    assert set(b.data.told_by) == {lea, "user_1"} and set(b.data.heard_by) == {lea, "user_1"}
    assert lea in b.data.about and b.data.origin == mc.TOLD  # lu : elle ne l'a pas vu
    assert remembered == [] and promised == []  # ni note sur elle, ni promesse d'elle
    [done] = read
    assert set(done.data.seqs) == {e.seq for e in received} and done.data.produced == 1
    assert memory.relayed == ()


def test_forgetting_a_contact_erases_her_texts_and_what_was_kept(tmp_path):
    model = Model(lea_moves)

    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Je déménage à Lyon en novembre !")]})
        await sleep(30 * MINUTE)
        [m] = journal(kernel, c.RECEIVED)
        await kernel.mind.forget(m.data.sender)
        raw = "\n".join(s.data for s in kernel.mind.store.read())
        return (m.data.sender, journal(kernel, c.RECEIVED), raw, kernel.mind.frame().state(c.OWNER),
                await call(kernel, "phone_messages", "user_1"))

    lea, [m], raw, state, read = live(tmp_path, scenario, model=model)
    assert m.data.text.text is None and m.data.sender_name.text is None  # les contenus effacés
    assert lea not in raw and "Léa" not in raw  # la clé, et le nom qu'elle portait, sortis des enveloppes
    assert not state.messages and not state.contacts
    assert read.content == phrase("phone.tools.messages.none")


def test_the_reply_args_name_only_the_draft(tmp_path):
    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Tu viens ?")]})
        [m] = journal(kernel, c.RECEIVED)
        await call(kernel, "phone_draft", "user_1", message=f"p{m.seq}", body="Je ne sais pas encore")
        return journal(kernel, rt.EFFECT_PROPOSED)

    [p] = live(tmp_path, scenario)
    # le texte n'est jamais dans les arguments (ils ne s'oublient pas) : il est dans le brouillon, un contenu
    assert json.loads(p.data.args_json) == {"draft": json.loads(p.data.args_json)["draft"]}
    assert "Je ne sais pas encore" not in p.data.args_json
