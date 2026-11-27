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
- oublier un contact efface ses textes, ce qu'elle en retenait, et son nom des enveloppes ;
- une relecture qu'une panne qui dure, une réponse illisible ou une sortie en partie invalide empêche attend dans la
  file des reprises, comme une des siennes (ADR 0224) : sa source dit d'où viennent ses messages, la mémoire du
  téléphone la reprend (d'elle-même, ou à la demande d'un opérateur), ce qui était valide est gardé, et l'oubli d'un
  expéditeur l'efface ; une panne se retente, et la conversation va dans la file, selon les mêmes réglages que ses
  conversations (« Délai avant de réessayer », « Essais avant de réduire les lots »).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import select

from mika.app import composition
from mika.app.domains.phone.desk import PhoneDesk
from mika.contracts import memory as mc
from mika.contracts import phone as c
from mika.contracts import runtime as rt
from mika.faculties.identity import audience_for
from mika.faculties.memory import tables as tb
from mika.faculties.memory.params import MemoryParams, params
from mika.kernel.clock import HOUR, MINUTE
from mika.plugins.phone import app_name
from mika.plugins.phone import inspect as phone_inspect
from mika.ports.gate import ACCEPTED, DISABLED, FORBIDDEN
from mika.ports.llm import LLMResponse, ToolCall
from mika.ports.phone import APPS, IGNORED, SENT
from mika.runtime.effects import with_content
from mika.runtime.operations import FIXED_FIELD, perform
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import SimClock, run_virtual
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import family, phrase
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
            "promesses": [{"texte": "aider Léa à porter les cartons", "envers": "P1"}],
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


# ── Une relecture empêchée attend dans la file des reprises (ADR 0224) ─────


class Down(Model):
    """Le fournisseur indisponible pour les ``down`` relectures qui viennent, puis de retour."""

    def __init__(self, extract=None, down: int = 0) -> None:
        super().__init__(extract)
        self.down = down

    def __call__(self, req):
        if req.role == "extract" and self.down > 0:
            self.down -= 1
            self.calls.append(req)
            raise RuntimeError("fournisseur indisponible")
        return super().__call__(req)


class Noted(Down):
    """``Down``, qui note l'heure de chaque relecture (``clock`` : l'horloge du noyau, que le scénario lui donne)."""

    def __init__(self, extract=None, down: int = 0) -> None:
        super().__init__(extract, down)
        self.clock = None
        self.at: list[int] = []

    def __call__(self, req):
        if req.role == "extract":
            self.at.append(int(self.clock.now()))
        return super().__call__(req)


#: les pannes de suite avant la file des reprises, par défaut (« Essais avant de réduire les lots »)
ATTEMPTS_MAX = MemoryParams().max_attempts
QUEUE = ("key", "source", "messages", "about", "attempts", "status", "reason")


def queue(kernel) -> list[dict]:
    t = tb.deferred()
    rows = kernel.mind.store.query_mind(select(*(t.c[n] for n in QUEUE)).order_by(t.c.key))
    return [dict(zip(QUEUE, r, strict=True)) for r in rows]


def extracts(model) -> list:
    return [r for r in model.calls if r.role == "extract"]


def test_a_reading_the_provider_keeps_failing_waits_in_the_queue_then_is_read(tmp_path):
    model = Down(lea_moves, down=ATTEMPTS_MAX)

    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Je déménage à Lyon en novembre !")]})
        await sleep(55 * MINUTE)  # posée à 20 min ; essais à 20, 30 et 50 min, puis dans la file
        waiting = (queue(kernel), journal(kernel, mc.RELAYED_READ), journal(kernel, mc.BELIEVED),
                   len(extracts(model)), kernel.mind.frame().state("memory"))
        await sleep(20 * MINUTE)  # reprise 10 min après sa mise en file
        return (waiting, queue(kernel), journal(kernel, mc.BELIEVED), journal(kernel, c.RECEIVED),
                journal(kernel, mc.EXTRACTION_DEFERRED), extracts(model))

    (rows, read, none, tried, memory), after, believed, received, deferred, calls = live(
        tmp_path, scenario, model=model)
    lea = received[0].data.sender
    [row] = rows
    assert row["source"] == mc.FROM_RELAYED and row["status"] == "queued" and row["reason"] == "provider_error"
    assert row["key"] == received[0].seq and json.loads(row["messages"]) == [e.seq for e in received]
    # ses personnes, la clé du téléphone comprise : l'oubli de l'une l'atteint
    assert lea.startswith("phone:") and set(json.loads(row["about"])) == {lea, "user_1"}
    [done] = read
    assert done.data.failed and done.data.produced == 0 and memory.relayed == ()  # la file porte ses messages
    assert none == [] and tried == ATTEMPTS_MAX
    # reprise par la mémoire du téléphone (pas par la consolidation, qui ne lit que le fil) : relue, elle est faite
    assert after == [] and len(calls) == ATTEMPTS_MAX + 1
    assert "Je déménage à Lyon en novembre !" in calls[-1].messages[-1].content
    [b] = believed
    assert b.data.text.text == "Léa déménage à Lyon en novembre" and lea in b.data.about
    assert [(d.data.source, d.data.status) for d in deferred] == [(mc.FROM_RELAYED, "queued"),
                                                                 (mc.FROM_RELAYED, "resolved")]


def test_the_retry_settings_reach_the_phone(tmp_path):
    """« Délai avant de réessayer » (``retry_us``) et « Essais avant de réduire les lots » (``max_attempts``), réglés
    autrement que par défaut, valent pour ce qu'on lui montre d'un téléphone comme pour ses conversations : une panne
    est retentée au délai réglé, la conversation va dans la file des reprises après le nombre d'essais réglé, et sa
    reprise vient au délai réglé."""
    retry, tries = 4 * MINUTE, 2
    assert retry != MemoryParams().retry_us and tries != ATTEMPTS_MAX
    model = Noted(lea_moves, down=tries)

    async def scenario(kernel, desk, phone, model):
        model.clock = kernel.mind.clock
        frame = kernel.mind.frame()
        settings = params(frame.env.params_of("memory", frame.root))
        await desk.inbox("user_1", {"messages": [message(1, "Je déménage à Lyon en novembre !")]})
        await sleep(20 * MINUTE + retry + MINUTE)  # posée à 20 min : en panne à 20 min, puis à 24, et dans la file
        waiting = (queue(kernel), journal(kernel, mc.EXTRACTION_DEFERRED), len(extracts(model)))
        await sleep(retry)  # sa reprise, 4 min après sa mise en file
        return (settings, waiting, queue(kernel), journal(kernel, mc.EXTRACTION_DEFERRED),
                journal(kernel, mc.BELIEVED), list(model.at))

    settings, (rows, queued, tried), after, deferred, believed, at = live(
        tmp_path, scenario, model=model, overrides={"memory": {"retry_us": retry, "max_attempts": tries}})
    assert (settings.retry_us, settings.max_attempts) == (retry, tries)  # les réglages sont pris
    # dans la file après le nombre d'essais réglé : deux pannes, pas trois
    assert tried == tries
    assert [(r["source"], r["status"], r["reason"], r["attempts"]) for r in rows] == [
        (mc.FROM_RELAYED, "queued", "provider_error", 1)]
    # chaque essai au délai réglé : le second après la première panne, la reprise après la mise en file
    assert len(at) == tries + 1 and retry - MINUTE < at[1] - at[0] < retry + MINUTE
    assert [d.data.status for d in queued] == ["queued"]
    assert retry - MINUTE < queued[0].data.retry_at - queued[0].at <= retry
    assert retry - MINUTE < at[2] - at[1] < retry + MINUTE
    # relue, elle est faite
    assert after == [] and [(d.data.source, d.data.status) for d in deferred] == [
        (mc.FROM_RELAYED, "queued"), (mc.FROM_RELAYED, "resolved")]
    [b] = believed
    assert b.data.text.text == "Léa déménage à Lyon en novembre"


def lea_moves_and_a_broken_belief(prompt: str) -> dict:
    got = lea_moves(prompt)
    got["croyances"].append({"personnes": ["P1"], "messages": [1]})  # sans texte : invalide
    return got


def test_a_partial_output_keeps_what_is_valid_and_an_operator_can_have_it_read_again(tmp_path):
    outputs = [lea_moves_and_a_broken_belief, lea_moves]
    model = Model(lambda prompt: outputs.pop(0)(prompt))

    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Je déménage à Lyon en novembre !")]})
        await sleep(30 * MINUTE)
        first = (queue(kernel), journal(kernel, mc.BELIEVED), journal(kernel, mc.RELAYED_READ),
                 journal(kernel, mc.EXTRACTION_DEFERRED))
        await sleep(2 * HOUR)  # à examiner : rien ne la reprend seul
        alone = len(extracts(model))
        key = str(first[0][0]["key"])
        done = await perform(kernel, "memory.reprendre", {FIXED_FIELD: ["key"], "key": [key]}, by="user_1")
        await sleep(MINUTE)
        return first, alone, done, queue(kernel), journal(kernel, mc.EXTRACTION_DEFERRED), extracts(model)

    (rows, believed, read, [deferred]), alone, done, after, history, calls = live(tmp_path, scenario, model=model)
    [row] = rows
    assert row["source"] == mc.FROM_RELAYED and row["status"] == "review" and row["reason"] == "invalid_items"
    detail = json.loads(deferred.data.detail.text)
    assert detail["issues"] == ["croyances[1]: missing"] and "Léa déménage à Lyon" in detail["output"]
    [b] = believed  # l'élément valide est gardé
    assert b.data.text.text == "Léa déménage à Lyon en novembre"
    [r] = read
    assert r.data.produced == 1 and not r.data.failed
    assert alone == 1 and done.ok
    # la reprise demandée garde sa source : la mémoire du téléphone la relit, puis la résout
    assert [(d.data.source, d.data.status) for d in history] == [
        (mc.FROM_RELAYED, "review"), (mc.FROM_RELAYED, "queued"), (mc.FROM_RELAYED, "resolved")]
    assert history[1].data.failure_code == "operator_retry"
    assert after == [] and len(calls) == 2
    assert "Je déménage à Lyon en novembre !" in calls[-1].messages[-1].content


def test_forgetting_the_sender_erases_a_reading_waiting_in_the_queue(tmp_path):
    model = Down(lea_moves, down=99)

    async def scenario(kernel, desk, phone, model):
        await desk.inbox("user_1", {"messages": [message(1, "Je déménage à Lyon en novembre !")]})
        await sleep(55 * MINUTE)
        waiting = queue(kernel)
        [m] = journal(kernel, c.RECEIVED)
        await kernel.mind.forget(m.data.sender)
        tried = len(extracts(model))
        await sleep(2 * HOUR)
        return waiting, queue(kernel), journal(kernel, mc.EXTRACTION_DEFERRED), tried, len(extracts(model))

    waiting, after, [deferred], tried, later = live(tmp_path, scenario, model=model)
    assert [r["source"] for r in waiting] == [mc.FROM_RELAYED]
    assert after == [] and deferred.data.detail.text is None  # l'entrée et son détail effacés
    assert later == tried  # plus rien à reprendre


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


def test_each_app_the_phone_reads_is_named_everywhere():
    """Une appli que la porte accepte (Messenger compris, ADR 0299) a son nom dans ses outils, dans la relecture des
    messages et dans la console : sans lui, elle deviendrait « son téléphone »."""
    for app in APPS:
        assert app in family("phone.apps") and app in family("memory.relayed.apps") and app in phone_inspect.APPS
    assert app_name("messenger") == "Messenger"
