"""Ce que Mika fait d'elle-même avec un agenda (ADR 0309, lot 3b), dans le vrai noyau composé, avec la vraie base de
l'agenda et son fournisseur Système, sous une horloge maîtrisée.

- un rendez-vous dans une demi-heure propose une initiative, et une seule : dite, elle ne revient plus ;
- endormie, l'arbitre la retient ;
- un rendez-vous refusé, ou annulé, ne se rappelle pas ;
- une invitation appelle une tâche, qui propose une réponse sur l'accord de la personne invitée ;
- si la personne répond elle-même, la réponse préparée tombe (« Répondu autrement ») ;
- une carte d'accord ne vaut pas au-delà du début du rendez-vous, et la proposition tombe quand il commence ;
- « Mika te le rappelle » se pose sur un événement, dans la base seulement, et une invitation part à une personne qui a
  un compte.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mika.adapters.agenda import AgendaStore, Providers
from mika.app.mindport import KernelPort
from mika.contracts import agenda as agenda_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Origin
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.agenda import (
    ANSWERED,
    ELSEWHERE,
    EXPIRED,
    INVITATION_NOTICED,
    INVITATION_SETTLED,
    REFUSED,
    REMINDER_DUE,
    WAITING,
)
from mika.ports.agenda import CANCELLED, NEEDS, NO, YES, EventDraft, Participant, Span
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.sim.clock import SimClock, run_virtual
from mika.vocab.access import AGREE, CLOSED_AGENDA, AgendaRule, Table
from mika.vocab.episodes import Kind
from mika.vocab.rights import Rights
from tests.fixtures import backend
from tests.fixtures.mika import AFTERNOON, at_paris, boot, build, connect, said

BEA_CAL, ADRIEN_CAL = "moi:user_2~mon-agenda", "moi:user_1~mon-agenda"
#: ce qui se déclenche en quelques secondes : ses initiatives et ses tâches
FAST = ArbitrationPolicy(thresholds={Kind.INITIATIVE: 9.0, Kind.TASK: 8.0}, max_rates={Kind.INITIATIVE: 1.0,
                                                                                       Kind.TASK: 1.0})
REMINDED = "Ta revue du budget commence bientôt ! [EMOTION:happy:0.3]"


class Model:
    """Un modèle scripté : l'initiative dit son rappel ; la tâche d'une invitation propose sa réponse (une fois) ; une
    réponse appelle l'outil que le message demande (une fois)."""

    def __init__(self) -> None:
        self.respond: dict[str, Any] = {}
        self.calls: dict[str, tuple[str, dict[str, Any]]] = {}

    def __call__(self, req: LLMRequest) -> LLMResponse:
        if req.role == "initiative":
            return LLMResponse(REMINDED if "LE RENDEZ-VOUS QUE TU LUI RAPPELLES" in prompt_of(req) else "Coucou !")
        used = any(m.role == "tool" for m in req.messages)
        if req.role == "step":
            if self.respond and not used:
                return LLMResponse("", tool_calls=(ToolCall("r1", "agenda_respond", self.respond),), stop="tool_use")
            return LLMResponse("Préparé.")
        if req.role != "reply":
            return LLMResponse("{}")
        asked = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        if not used:
            for trigger, (tool, args) in self.calls.items():
                if trigger in asked:
                    return LLMResponse("", tool_calls=(ToolCall("t1", tool, args),), stop="tool_use")
        return LLMResponse("D'accord. [EMOTION:happy:0.3]")


def live(tmp_path, scenario, *, start: int = AFTERNOON, arbitration: ArbitrationPolicy = FAST,
         rights: Rights | None = None):
    clock = SimClock(start)
    store = AgendaStore(backend.target(tmp_path, "agenda"), now=clock.now)
    providers = Providers(store)
    model = Model()
    kernel, clock, llm, _ = build(tmp_path, model, clock=clock, arbitration=arbitration,
                                  ports={"agenda": store, "agenda_providers": providers},
                                  access_tables=lambda: rights or Rights())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            return await scenario(kernel, llm, model, store, providers, clock)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def made(providers, person: str, title: str, start: int, minutes: int = 60, **kw):
    conn = providers.connection(f"moi:{person}")
    cal = providers.system.default_calendar(person)
    return await providers.system.create(conn, cal, EventDraft(title, Span(start, start + minutes * MINUTE,
                                                                           "Europe/Paris"), **kw))


def prompt_of(req: LLMRequest) -> str:
    return "\n".join([req.system_stable, req.system_volatile, *(str(m.content) for m in req.messages)])


def events(kernel, event_type) -> list:
    return [kernel.mind.decode(s) for s in kernel.mind.store.read(types={event_type.name})]


def pending(kernel) -> dict[int, dict[str, Any]]:
    effects = kernel.mind.frame().state("runtime").effects
    return {p.proposal: json.loads(effects[p.proposal].args_json) for p in kernel.mind.frame().get(rt.PENDING_EFFECTS)}


def reminded(kernel) -> list:
    return [e for e in events(kernel, rt.EPISODE_STARTED) if (e.data.subject or "").startswith(
        agenda_c.REMINDER_PREFIX)]


def test_an_appointment_in_half_an_hour_proposes_one_initiative_and_only_one(tmp_path):
    async def scenario(kernel, llm, model, store, providers, clock):
        event = await made(providers, "user_2", "Revue du budget", clock.now() + 20 * MINUTE, location="Bureau 3")
        await asyncio.sleep(3 * MINUTE / US)
        due = events(kernel, REMINDER_DUE)
        started = reminded(kernel)
        said_it = [e for e in events(kernel, rt.UTTERANCE) if e.data.kind == Kind.INITIATIVE
                   and any(p.startswith(agenda_c.REMINDER_PREFIX) for p in e.data.provenance)]
        initiatives = [r for r in llm.calls if r.role == "initiative" and "RAPPELLES" in prompt_of(r)]
        await asyncio.sleep(10 * MINUTE / US)  # dit : plus rien, même à l'approche du rendez-vous
        return event, due, started, said_it, initiatives, reminded(kernel), kernel.mind.frame().state("agenda")

    event, due, started, said_it, initiatives, later, state = live(tmp_path, scenario)
    [d] = due
    assert (d.data.person, d.data.calendar, d.data.event, d.data.delay) == ("user_2", BEA_CAL, event.id, "30")
    [ep] = started
    assert ep.data.kind == Kind.INITIATIVE and ep.data.target == "user_2"
    assert ep.data.subject == agenda_c.reminder_subject(d.data.key)
    # elle compose elle-même, le rendez-vous sous les yeux (cité), avec la consigne d'un fait
    prompt = prompt_of(initiatives[0])
    assert "LE RENDEZ-VOUS QUE TU LUI RAPPELLES" in prompt and "Revue du budget" in prompt and "Bureau 3" in prompt
    assert "son agenda te demande de le lui rappeler" in prompt
    assert [u.data.target for u in said_it] == ["user_2"]
    assert agenda_c.reminder_subject(d.data.key) in said_it[0].data.provenance
    r = state.reminders[d.data.key]
    assert r.status == agenda_c.TOLD and r.told_to == "user_2" and r.attempts == 1
    assert len(later) == 1, "une fois par occurrence"


def test_asleep_the_arbiter_holds_her_reminder_back(tmp_path):
    async def scenario(kernel, llm, model, store, providers, clock):
        await made(providers, "user_2", "Train de nuit", clock.now() + 25 * MINUTE)
        await asyncio.sleep(2 * MINUTE / US)
        rows = [r for r in kernel.arbiter.rows(kernel.mind.frame(), record=False)
                if any(reason == agenda_c.REMIND for _o, reason, _e in r.parts)]
        return kernel.mind.frame().get(body_c.SLEEP), events(kernel, REMINDER_DUE), rows, reminded(kernel)

    asleep, due, rows, started = live(tmp_path, scenario, start=at_paris(2026, 9, 29, 3, 0))
    assert asleep is not body_c.SleepPhase.AWAKE
    assert len(due) == 1  # dû…
    [row] = rows
    assert ("body", body_c.ASLEEP) in row.vetoes and row.hazard == 0.0  # … mais elle dort
    assert not started


def test_no_reminder_when_her_table_does_not_let_her_read_it_of_her_own_accord(tmp_path):
    """Le tableau de « Mon agenda » de Béa ne garde que la conversation : d'elle-même, elle ne le lit pas."""
    replying = Table[AgendaRule](lines=(AgendaRule(who=("personne:user_2",), when=("conversation",), read=True,
                                                   write=AGREE),), default=CLOSED_AGENDA)

    async def scenario(kernel, llm, model, store, providers, clock):
        await made(providers, "user_2", "Revue du budget", clock.now() + 20 * MINUTE)
        await asyncio.sleep(3 * MINUTE / US)
        rows = [r for r in kernel.arbiter.rows(kernel.mind.frame(), record=False)
                if any(reason == agenda_c.REMIND for _o, reason, _e in r.parts)]
        return events(kernel, REMINDER_DUE), rows, reminded(kernel)

    due, rows, started = live(tmp_path, scenario, rights=Rights(agendas={BEA_CAL: replying}))
    assert len(due) == 1 and not rows and not started


def test_a_declined_or_cancelled_appointment_is_not_reminded(tmp_path):
    async def scenario(kernel, llm, model, store, providers, clock):
        soon = clock.now() + 20 * MINUTE
        await made(providers, "user_1", "Point d'équipe", soon, participants=(Participant(person="user_2"),))
        await made(providers, "user_2", "Dentiste", soon + 5 * MINUTE, status=CANCELLED)
        conn, cal = providers.connection("moi:user_2"), providers.system.default_calendar("user_2")
        [copy] = [o.event for o in store.period([BEA_CAL], clock.now(), soon + 2 * 3600 * US, declined=True)]
        await providers.system.respond(conn, cal, copy, "", NO)
        await asyncio.sleep(3 * MINUTE / US)
        return events(kernel, REMINDER_DUE)

    due = live(tmp_path, scenario)
    assert [d.data.calendar for d in due] == [ADRIEN_CAL], "ni le refusé de Béa, ni son annulé"


async def _invited(kernel, providers, store, clock, model):
    """Adrien invite Béa (agenda du système) ; la tâche de Béa prépare un « non », avec un mot et sa raison."""
    start = clock.now() + 26 * 3600 * US
    await made(providers, "user_1", "Afterwork", start, participants=(Participant(person="user_2"),))
    await made(providers, "user_2", "Escalade", start - 30 * MINUTE, minutes=120)
    [copy] = [o.event for o in store.period([BEA_CAL], start - 1, start + 1) if o.event.response == NEEDS]
    model.respond = {"ref": f"ev{copy.id}", "answer": "non", "comment": "Désolée, j'ai escalade !",
                     "why": "Son escalade tombe à la même heure."}
    await asyncio.sleep(5 * MINUTE / US)
    return copy


def test_an_invitation_calls_one_task_that_proposes_a_reply_with_the_invitee_s_accord(tmp_path):
    async def scenario(kernel, llm, model, store, providers, clock):
        copy = await _invited(kernel, providers, store, clock, model)
        tasks = [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == Kind.TASK]
        steps = [r for r in llm.calls if r.role == "step"]
        await asyncio.sleep(30 * MINUTE / US)  # une invitation, une tâche
        again = [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == Kind.TASK]
        return copy, events(kernel, INVITATION_NOTICED), tasks, steps, again, pending(kernel), \
            kernel.mind.frame().state("agenda")

    copy, noticed, tasks, steps, again, waiting, state = live(tmp_path, scenario)
    [n] = noticed
    assert (n.data.calendar, n.data.event, n.data.holder) == (BEA_CAL, copy.id, "personne:user_2")
    [task] = tasks
    assert task.data.target == f"task:agenda:{n.data.key}" and len(again) == 1
    prompt = prompt_of(steps[0])
    assert "L'INVITATION À LAQUELLE TU PRÉPARES UNE RÉPONSE" in prompt and "Afterwork" in prompt
    assert "Escalade" in prompt  # ce qui tombe en même temps
    [(proposal, args)] = waiting.items()
    assert args["op"] == "repondre" and args["response"] == NO and args["invitation"] == n.data.key
    assert args[rt.DECIDER] == "user_2" and args["target"] == "user_2"  # sa carte, dans son chat
    assert args["why"] == "Son escalade tombe à la même heure." and args["comment"] == "Désolée, j'ai escalade !"
    assert rt.arg_int(args, rt.EXPIRES) <= rt.arg_int(args, "starts")
    w = state.writes[proposal]
    assert w.status == WAITING and w.approval and w.invitation == n.data.key
    assert state.invitations[n.data.key].proposal == proposal


def test_when_she_answers_herself_the_prepared_reply_falls(tmp_path):
    async def scenario(kernel, llm, model, store, providers, clock):
        copy = await _invited(kernel, providers, store, clock, model)
        before = dict(pending(kernel))
        conn, cal = providers.connection("moi:user_2"), providers.system.default_calendar("user_2")
        await providers.system.respond(conn, cal, store.event(copy.id), "", YES)  # dans son écran
        await asyncio.sleep(2 * MINUTE / US)
        resolved = [e for e in events(kernel, rt.EFFECT_RESOLVED) if e.data.proposal in before]
        notes = kernel.mind.store.content([e.data.note.ref for e in resolved])
        return before, resolved, notes, pending(kernel), kernel.mind.frame().state("agenda"), \
            events(kernel, INVITATION_SETTLED)

    before, resolved, notes, after, state, settled = live(tmp_path, scenario)
    [proposal] = before
    [r] = resolved
    assert not r.data.approved and r.data.by == ELSEWHERE and notes[r.data.note.ref] == "Répondu autrement"
    assert not after
    assert state.writes[proposal].status == REFUSED and state.writes[proposal].by == ELSEWHERE
    assert [s.data.why for s in settled] == [ANSWERED]


def test_a_card_does_not_outlive_the_appointment_and_falls_when_it_begins(tmp_path):
    async def scenario(kernel, llm, model, store, providers, clock):
        start = clock.now() + 45 * MINUTE
        model.calls["ajoute"] = ("agenda_create", {"title": "Café avec Léa",
                                                    "start": "2026-09-28T14:45", "minutes": 30})
        await (await kernel.perceive(said("user_2", "ajoute le café avec Léa"))).reply
        waiting = dict(pending(kernel))
        await asyncio.sleep(50 * MINUTE / US)
        resolved = [e for e in events(kernel, rt.EFFECT_RESOLVED) if e.data.proposal in waiting]
        return start, waiting, resolved, pending(kernel), kernel.mind.frame().state("agenda")

    start, waiting, resolved, after, state = live(tmp_path, scenario)
    [(proposal, args)] = waiting.items()
    assert args[rt.DECIDER] == "user_2"
    assert rt.arg_int(args, "starts") == start and rt.arg_int(args, rt.EXPIRES) == start
    [r] = resolved
    assert not r.data.approved and r.data.by == EXPIRED and not after
    assert state.writes[proposal].status == REFUSED and state.writes[proposal].by == EXPIRED


def test_she_invites_someone_with_an_account_and_sets_her_reminder_on_the_event(tmp_path):
    async def scenario(kernel, llm, model, store, providers, clock):
        await kernel.mind.append([identity_c.LINKED.draft(handle="mail:bea@exemple.fr", person="user_2",
                                                          by="operator")],
                                 emitter="identity", correlation="opérateur", origin=Origin.EXTERNAL)
        model.calls["réunion"] = ("agenda_create", {
            "title": "Réunion budget", "start": "2026-09-29T10:00", "minutes": 60, "remind": "veille",
            "invite": ["bea@exemple.fr", "Marc@Exemple.fr"]})
        await (await kernel.perceive(said("user_1", "mets la réunion budget demain"))).reply
        [(proposal, args)] = pending(kernel).items()
        port = KernelPort(kernel)
        [card] = await port.approval_cards("user_1")
        got = await port.resolve_effect(proposal, True, by="user_1", seen=card["digest"])
        await asyncio.sleep(5)
        mine = [o.event for o in store.period([ADRIEN_CAL], clock.now(), clock.now() + 2 * 86_400 * US)]
        theirs = [o.event for o in store.period([BEA_CAL], clock.now(), clock.now() + 2 * 86_400 * US)]
        return args, card, got, mine, theirs

    args, card, got, mine, theirs = live(tmp_path, scenario)
    assert args["remind"] == "veille"
    assert [(p["address"], p["person"]) for p in args["draft"]["invite"]] == [
        ("bea@exemple.fr", "user_2"), ("marc@exemple.fr", "")]  # Béa a un compte : invitée par sa clé
    assert "Invités : bea@exemple.fr, marc@exemple.fr" in card["text"] and "la veille au soir" in card["text"].lower()
    assert got == "approved"
    [event] = mine
    assert event.title == "Réunion budget" and event.remind == "veille"  # dans la base, pas chez le fournisseur
    assert {p.address for p in event.participants} == {"bea@exemple.fr", "marc@exemple.fr"}
    [copy] = theirs  # l'invitation arrive dans son agenda à elle, sans le rappel d'Adrien
    assert copy.response == NEEDS and copy.origin == ADRIEN_CAL and copy.remind == ""
