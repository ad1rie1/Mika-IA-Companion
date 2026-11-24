"""Ce que Mika fait d'un agenda en conversation (ADR 0309, lot 3a), dans le vrai noyau composé, avec la vraie base de
l'agenda et son fournisseur Système.

- ses outils sont offerts à qui a un agenda, pas à une inconnue ni dans un salon ;
- elle sait la journée de la personne en face (aujourd'hui et demain), en tête-à-tête seulement ;
- un événement privé d'une autre personne se lit « Occupé » ;
- un partage « Lire » ne permet pas d'écrire ; « Lire et préparer » écrit après l'accord du propriétaire, dans son chat ;
- écrire dans son propre agenda passe par la carte d'accord de la personne, qui lit l'aperçu ; un aperçu changé
  entre-temps fait refuser l'accord ;
- ce qu'elle écrit seule (une ligne qui le permet) est écrit dans l'agenda du système, marqué d'elle, et relu ;
- un agenda masqué ne sert plus.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

from mika.adapters.agenda import AgendaStore, Providers
from mika.app import composition
from mika.app.mindport import KernelPort
from mika.contracts import runtime as rt
from mika.kernel.frame import Audience
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.agenda import DONE, WRITTEN, AgendaParams
from mika.ports.agenda import BY_HER, EventChange, EventDraft, Participant, Span, whole_days
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.tool_offer import offer
from mika.sim.clock import SimClock, run_virtual
from mika.vocab.access import ALONE, CLOSED_AGENDA, AgendaRule, Table
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from mika.vocab.rights import Rights
from tests.fixtures import backend
from tests.fixtures.mika import AFTERNOON, at_paris, boot, build, connect, said

BEA_CAL, ADRIEN_CAL = "moi:user_2~mon-agenda", "moi:user_1~mon-agenda"
AGENDA_TOOLS = {"agenda_list", "agenda_events", "agenda_free", "agenda_create", "agenda_edit", "agenda_delete",
                "agenda_respond"}


def paris(day: int, hour: int, minute: int = 0) -> int:
    return at_paris(2026, 9, day, hour, minute)


class Script:
    """Un modèle scripté : à tel message, tel appel d'outil (une fois), puis une réponse."""

    def __init__(self) -> None:
        self.calls: dict[str, tuple[str, dict[str, Any]]] = {}

    def __call__(self, req: LLMRequest) -> LLMResponse:
        if req.role != "reply":
            return LLMResponse("{}")
        asked = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        if not any(m.role == "tool" for m in req.messages):
            for trigger, (tool, args) in self.calls.items():
                if trigger in asked:
                    return LLMResponse("", tool_calls=(ToolCall("t1", tool, args),), stop="tool_use")
        return LLMResponse("D'accord. [EMOTION:happy:0.3]")


def live(tmp_path, scenario, *, params: AgendaParams | None = None, rights: Rights | None = None):
    clock = SimClock(AFTERNOON)  # lundi 28 septembre 2026, 14 h à Paris
    store = AgendaStore(backend.target(tmp_path, "agenda"), now=clock.now)
    providers = Providers(store)
    script = Script()
    kernel, clock, llm, _ = build(tmp_path, script, clock=clock, arbitration=ArbitrationPolicy(),
                                  ports={"agenda": store, "agenda_providers": providers},
                                  access_tables=lambda: rights or Rights())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            if params is not None:
                await kernel.set_params("agenda", params)
            return await scenario(kernel, llm, script, store, providers)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def made(providers, person: str, title: str, start: int, minutes: int = 60, **kw):
    conn = providers.connection(f"moi:{person}")
    cal = providers.system.default_calendar(person)
    return await providers.system.create(conn, cal, EventDraft(title, Span(start, start + minutes * 60_000_000,
                                                                           "Europe/Paris"), **kw))


async def ask(kernel, who: str, text: str, **kw):
    perceived = await kernel.perceive(said(who, text, **kw))
    report = await perceived.reply
    await kernel.traces.flush()
    return kernel.traces.get(report.id) if report is not None else None


def replies(llm) -> list[LLMRequest]:
    return [r for r in llm.calls if r.role == "reply"]


def prompt_of(req: LLMRequest) -> str:
    return "\n".join([req.system_stable, req.system_volatile, *(str(m.content) for m in req.messages)])


def tool_said(llm) -> str:
    """Ce que l'outil lui a rendu, tel que le modèle l'a lu (la trace ne le garde pas quand rien ne s'en garde)."""
    return next(m.content for m in reversed(replies(llm)[-1].messages) if m.role == "tool")


def pending(kernel) -> dict[int, dict[str, Any]]:
    effects = kernel.mind.frame().state("runtime").effects
    return {p.proposal: json.loads(effects[p.proposal].args_json) for p in kernel.mind.frame().get(rt.PENDING_EFFECTS)}


def test_her_tools_are_offered_to_whoever_has_an_agenda_never_to_a_stranger_or_a_room(tmp_path):
    async def scenario(kernel, llm, script, store, providers):
        await ask(kernel, "user_2", "salut !")
        offered = {t.name for t in replies(llm)[-1].tools}
        frame, reg = kernel.mind.frame(), kernel.mind.registry
        policy = composition.policies()[Kind.REPLY]
        stranger = Audience(persons=("web_9",), channel="web", public=False, trust=ChannelTrust.ACCOUNT.value)
        room = Audience(persons=("user_1", "user_2"), channel="web", room="salon", public=True,
                        trust=ChannelTrust.AUTHENTICATED.value, person="user_2")
        others = [set(offer(reg.tools, policy, Kind.REPLY, aud, frame=frame, rights=Rights(), ports=kernel.ports))
                  for aud in (stranger, room)]
        return offered, others

    offered, (stranger, room) = live(tmp_path, scenario)
    assert AGENDA_TOOLS <= offered  # « Mon agenda » : chaque personne qui a un compte a le sien
    assert not AGENDA_TOOLS & stranger and not AGENDA_TOOLS & room


def test_she_knows_their_day_today_and_tomorrow_only_face_to_face(tmp_path):
    async def scenario(kernel, llm, script, store, providers):
        await made(providers, "user_2", "Dentiste", paris(28, 16), 30, location="Cabinet Martin")
        await made(providers, "user_2", "Revue du budget", paris(29, 9),
                   participants=(Participant("marc@exemple.fr", "Marc"),))
        await made(providers, "user_2", "Piscine", paris(30, 12))
        await made(providers, "user_2", "Café passé", paris(28, 9))
        await ask(kernel, "user_2", "salut !")
        private = prompt_of(replies(llm)[-1])
        await ask(kernel, "user_2", "Mika, salut tout le monde", room="salon", public=True)
        together = prompt_of(replies(llm)[-1])
        return private, together

    private, together = live(tmp_path, scenario)
    assert "SA JOURNÉE DANS SES AGENDAS" in private
    assert "Aujourd'hui, lundi 28 septembre" in private and "Demain, mardi 29 septembre" in private
    assert "16 h – 16 h 30" in private and "« Dentiste »" in private and "Cabinet Martin" in private
    assert "« Revue du budget »" in private and "avec Marc" in private
    assert "Piscine" not in private and "Café passé" not in private  # après-demain, et déjà passé
    assert "SA JOURNÉE DANS SES AGENDAS" not in together and "Dentiste" not in together


def test_a_private_event_of_someone_else_reads_busy(tmp_path):
    params = AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": "lire"}})

    async def scenario(kernel, llm, script, store, providers):
        await made(providers, "user_1", "Rendez-vous médical", paris(28, 17), private=True)
        await made(providers, "user_1", "Course à pied", paris(28, 18))
        script.calls["Adrien"] = ("agenda_events", {"when": "aujourdhui", "calendar": ADRIEN_CAL})
        await ask(kernel, "user_2", "qu'est-ce qu'Adrien fait aujourd'hui ?")
        return tool_said(llm)

    result = live(tmp_path, scenario, params=params)
    assert "Occupé" in result and "Course à pied" in result
    assert "médical" not in result


def test_today_reads_the_whole_days_of_today_not_those_of_yesterday_or_tomorrow(tmp_path):
    async def scenario(kernel, llm, script, store, providers):
        conn, cal = providers.connection("moi:user_2"), providers.system.default_calendar("user_2")
        for title, day in (("Fête d'hier", "2026-09-27"), ("Grève", "2026-09-28"), ("Congé de demain", "2026-09-29")):
            await providers.system.create(conn, cal, EventDraft(title, whole_days(day, day)))
        await made(providers, "user_2", "Dentiste", paris(28, 16), 30)
        script.calls["aujourd'hui"] = ("agenda_events", {"when": "aujourdhui"})
        await ask(kernel, "user_2", "qu'est-ce que j'ai aujourd'hui ?")
        today = tool_said(llm)
        script.calls = {"demain": ("agenda_events", {"when": "demain"})}
        await ask(kernel, "user_2", "et demain ?")
        return today, tool_said(llm)

    today, tomorrow = live(tmp_path, scenario)
    assert "Grève" in today and "Dentiste" in today
    assert "Fête d'hier" not in today and "Congé de demain" not in today
    assert "Congé de demain" in tomorrow and "Grève" not in tomorrow


def test_a_read_share_does_not_let_her_write(tmp_path):
    params = AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": "lire"}})

    async def scenario(kernel, llm, script, store, providers):
        await made(providers, "user_1", "Course à pied", paris(28, 18))
        script.calls["cinéma"] = ("agenda_create", {"title": "Cinéma", "start": "2026-09-30T20:00",
                                                    "calendar": ADRIEN_CAL})
        await ask(kernel, "user_2", "ajoute le cinéma mercredi à l'agenda d'Adrien")
        return tool_said(llm), pending(kernel), [o.event.title for o in store.period([ADRIEN_CAL], 0, 2**62)]

    result, waiting, titles = live(tmp_path, scenario, params=params)
    assert "seulement le lire" in result and waiting == {} and titles == ["Course à pied"]


def test_a_prepare_share_writes_once_the_owner_approves_in_his_chat(tmp_path):
    params = AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": "preparer"}})

    async def scenario(kernel, llm, script, store, providers):
        port = KernelPort(kernel)
        await made(providers, "user_1", "Course à pied", paris(28, 18))
        script.calls["cinéma"] = ("agenda_create", {"title": "Cinéma", "start": "2026-09-30T20:00",
                                                    "minutes": 120, "calendar": ADRIEN_CAL})
        await ask(kernel, "user_2", "ajoute le cinéma mercredi à l'agenda d'Adrien")
        said_then = tool_said(llm)
        (proposal, args), = pending(kernel).items()
        hers, his = await port.approval_cards("user_2"), await port.approval_cards("user_1")
        before = [o.event.title for o in store.period([ADRIEN_CAL], 0, 2**62)]
        status = await port.decide_card("user_1", proposal, True, his[0]["digest"])
        await asyncio.sleep(5)
        after = [o.event for o in store.period([ADRIEN_CAL], 0, 2**62)]
        write = kernel.mind.frame().state("agenda").writes[proposal]
        written = [kernel.mind.decode(e).data for e in kernel.mind.store.read(types={WRITTEN.name})]
        return said_then, args, hers, his, before, status, after, write, written

    result, args, hers, his, before, status, after, write, written = live(tmp_path, scenario, params=params)
    assert "Adrien" in result and "rien n'est encore écrit" in result
    assert args[rt.DECIDER] == "user_1" and hers == [] and len(his) == 1
    assert "Ajouter à « Mon agenda »" in his[0]["text"] and "Cinéma" in his[0]["text"]
    assert "mercredi 30 septembre, 20 h – 22 h" in his[0]["text"]
    assert before == ["Course à pied"] and status == "approved"
    cinema = next(e for e in after if e.title == "Cinéma")
    assert cinema.added is not None and cinema.added.by == BY_HER and cinema.added.ref.startswith("chat:user_2")
    assert write.status == DONE and write.uid == cinema.uid
    assert [w.ok for w in written] == [True] and written[0].about == ("user_2", "user_1")


def test_a_private_invitation_of_someone_else_is_answered_by_no_share(tmp_path):
    params = AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": "servir"}})

    async def scenario(kernel, llm, script, store, providers):
        mine_ = await made(providers, "user_1", "Psy", paris(29, 9), private=True)
        invited = replace(store.find(ADRIEN_CAL, mine_.uid), response="attente",
                          organizer=Participant("cabinet@roux.example", "Roux"))
        store.save([invited])
        script.calls["Adrien"] = ("agenda_respond", {"ref": f"ev{invited.id}", "answer": "non"})
        await ask(kernel, "user_2", "réponds non à l'invitation d'Adrien")
        return tool_said(llm), pending(kernel)

    said_then, waiting = live(tmp_path, scenario, params=params)
    assert "privé" in said_then and waiting == {}  # comme supprimer : rien ne se propose


def test_her_own_agenda_asks_her_card_and_a_changed_preview_is_refused(tmp_path):
    async def scenario(kernel, llm, script, store, providers):
        port = KernelPort(kernel)
        dentist = await made(providers, "user_2", "Dentiste", paris(28, 16), 30)
        script.calls["décale"] = ("agenda_edit", {"ref": f"ev{dentist.id}", "start": "2026-09-28T17:00"})
        await ask(kernel, "user_2", "décale le dentiste à 17 h")
        result = tool_said(llm)
        cards = await port.approval_cards("user_2")
        conn, cal = providers.connection("moi:user_2"), providers.system.default_calendar("user_2")
        await providers.system.edit(conn, cal, dentist, "", EventChange(location="Cabinet Martin"))
        (proposal,) = pending(kernel)
        status = await port.decide_card("user_2", proposal, True, cards[0]["digest"])
        return result, cards, status, store.find(BEA_CAL, dentist.uid)

    result, cards, status, dentist = live(tmp_path, scenario)
    assert "votre conversation" in result
    assert len(cards) == 1 and "Modifier dans « Mon agenda »" in cards[0]["text"]
    assert "« Dentiste », lundi 28 septembre, 16 h – 16 h 30" in cards[0]["text"]
    assert "Quand : lundi 28 septembre, 17 h – 17 h 30" in cards[0]["text"]
    assert status == "changed" and dentist.span.start == paris(28, 16)  # rien n'est parti


def test_what_she_writes_alone_lands_in_the_system_agenda_marked_hers(tmp_path):
    alone = Table[AgendaRule](lines=(AgendaRule(who=("personne:user_2",), when=("conversation",), read=True,
                                                write=ALONE, keep="perso"),), default=CLOSED_AGENDA)

    async def scenario(kernel, llm, script, store, providers):
        script.calls["piscine"] = ("agenda_create", {"title": "Piscine", "start": "2026-09-30T12:00", "minutes": 45})
        await ask(kernel, "user_2", "note la piscine mercredi midi")
        result = tool_said(llm)
        found = [o.event for o in store.period([BEA_CAL], paris(30, 0), paris(30, 23))]
        return result, pending(kernel), found

    result, waiting, found = live(tmp_path, scenario, rights=Rights(agendas={BEA_CAL: alone}))
    assert waiting == {} and "C'est écrit dans son agenda" in result
    (piscine,) = found
    assert piscine.title == "Piscine" and piscine.span.end - piscine.span.start == 45 * 60_000_000
    assert piscine.added is not None and piscine.added.by == BY_HER and piscine.added.ref.startswith("chat:user_2:")


def test_a_hidden_agenda_no_longer_serves_her(tmp_path):
    async def scenario(kernel, llm, script, store, providers):
        await made(providers, "user_2", "Dentiste", paris(28, 16), 30)
        await ask(kernel, "user_2", "salut !")
        req = replies(llm)[-1]
        return {t.name for t in req.tools}, prompt_of(req)

    offered, text = live(tmp_path, scenario, params=AgendaParams(hidden=(BEA_CAL,)))
    assert not AGENDA_TOOLS & offered and "Dentiste" not in text


def test_a_share_withdrawn_before_the_owner_decides_blocks_the_write(tmp_path):
    params = AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": "preparer"}})

    async def scenario(kernel, llm, script, store, providers):
        port = KernelPort(kernel)
        await made(providers, "user_1", "Course à pied", paris(28, 18))
        script.calls["cinéma"] = ("agenda_create", {"title": "Cinéma", "start": "2026-09-30T20:00",
                                                    "calendar": ADRIEN_CAL})
        await ask(kernel, "user_2", "ajoute le cinéma mercredi à l'agenda d'Adrien")
        (proposal,) = pending(kernel)
        digest = (await port.approval_cards("user_1"))[0]["digest"]
        await kernel.set_params("agenda", AgendaParams())  # Adrien a retiré le partage
        cards = await port.approval_cards("user_1")
        status = await port.decide_card("user_1", proposal, True, digest)
        return cards, status, [o.event.title for o in store.period([ADRIEN_CAL], 0, 2**62)]

    cards, status, titles = live(tmp_path, scenario, params=params)
    assert "plus partagé" in cards[0]["blocked"] and status == "blocked" and titles == ["Course à pied"]
