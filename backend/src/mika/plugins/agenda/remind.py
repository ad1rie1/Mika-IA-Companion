"""Ses rappels (ADR 0309, lot 3b) : avant un rendez-vous, au délai que son agenda demande, elle prévient la personne.

- **L'initiative** : un rappel dû (``agenda.reminder_due``, que ``watch`` pose) qui n'est ni dit, ni tombé, ni commencé,
  et qu'elle a essayé moins de ``remind_attempts`` fois, propose une initiative due (``agenda.REMIND``, ``agency.OWED`` :
  ni le plafond du jour, ni la retenue envers qui ne répond pas) vers l'adresse où la joindre maintenant
  (``identity.reach_now``), sur le sujet de cette occurrence (``agenda:rappel:<clé>``). L'arbitre la juge comme les
  autres : endormie, elle attend (sa preuve reste sous la barre de réveil) ; le quota, ce qu'elle fait déjà, aussi. Sa
  garde (``agenda.REMINDER``) la fait tomber si le rappel est dit ou tombé entre-temps.
- **Les mêmes portes** : seulement si la ligne « quand elle te parle d'elle-même » du tableau de l'agenda le laisse lire
  devant cette adresse (``rights.audience_at``, puis ``here``) — et l'épisode le revérifie devant sa vraie audience.
- **Ce qu'elle en sait** : « LE RENDEZ-VOUS DONT TU LA PRÉVIENS », le rendez-vous tel que la base le dit (quand, son
  titre, son lieu, avec qui, son agenda) — venu du dehors, cité en entier ; sa provenance est le sujet du rappel :
  l'énoncé qui la portait le dit (``agenda._uttered``). Elle compose elle-même : la consigne dit un fait (le rendez-vous
  approche, et son agenda lui demande de le rappeler), jamais quoi dire.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from mika.contracts import agenda as agenda_c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import MINUTE, local
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.agenda import AGENDA, AgendaState, Reminded, params_of
from mika.plugins.agenda.rights import audience_at, here, here_all
from mika.plugins.agenda.tools import NAME_SHOWN, PEOPLE_SHOWN, PLACE_SHOWN, TITLE_SHOWN
from mika.plugins.agenda.when import when_words
from mika.ports.agenda import Event, instance, masked
from mika.ports.preprocess import inert
from mika.vocab.access import KEEP_FLOORS
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.rights import closeness_of, rights_of

#: ce que le propose lit (à qui l'adresse, où la joindre, qui lui est proche)
READS = [agenda_c.REMINDER, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, identity_c.PERSON,
         identity_c.SPEAKS_AS_OWNER, presence_c.PRESENT, social_c.CLOSENESS]
#: ce qu'elle lit au plus de la note d'un rendez-vous
NOTE_SHOWN = 300


@AGENDA.fact(agenda_c.REMINDER)
def _reminder(s: AgendaState, cx: Any, key: str) -> str:
    r = s.reminders.get(key)
    return r.status if r is not None else ""


def _still(key: str) -> Guard:
    """L'épisode ne vaut que tant que le rappel est dû (dit, ou tombé entre-temps : plus rien à faire)."""
    return Guard("rappel", predicate=lambda view, k=key: view.get(agenda_c.REMINDER(k)) == agenda_c.DUE)


def _when(r: Reminded, frame: Frame) -> str:
    """Quand il commence, d'ici : dans tant de minutes, aujourd'hui à telle heure, demain."""
    tz = frame.env.tz_of(frame.root)
    start, today = local(r.start, tz), frame.local().date()
    if start.date() == today + timedelta(days=1):
        return phrase("agenda.remind.tomorrow")
    minutes = max(1, -(-(r.start - frame.now) // MINUTE))
    if minutes <= 90:
        return phrase("agenda.remind.in_minutes", n=minutes)
    return phrase("agenda.remind.today")


def due(s: AgendaState, frame: Frame) -> list[Reminded]:
    """Les rappels à dire maintenant : dus, pas commencés, pas trop essayés."""
    p = params_of(frame)
    return sorted((r for r in s.reminders.values() if r.status == agenda_c.DUE and frame.now < r.start
                   and r.attempts < p.remind_attempts), key=lambda r: (r.start, r.key))


@AGENDA.propose(kinds=[Kind.INITIATIVE], reasons={agenda_c.REMIND: (0.0, 14.5)}, reads=READS)
def _remind(s: AgendaState, frame: Frame) -> list[Candidate]:
    p = params_of(frame)
    rights, close = rights_of(frame.env), closeness_of(frame.env, frame)
    out = []
    for r in due(s, frame):
        address = identity_c.reach_now(frame, r.person)
        if not address:
            continue
        if here(p, rights, r.calendar, audience_at(frame, address), Kind.INITIATIVE, close) is None:
            continue  # la ligne « d'elle-même » de son tableau ne le laisse pas lire là
        name = identity_c.person_name(frame, r.person) or identity_c.person_name(frame, address)
        who = f"« {name} »" if name else phrase("expression.person.unnamed")
        out.append(Candidate(
            Kind.INITIATIVE, address, agenda_c.REMIND, p.remind_evidence, resources=frozenset({floor(address)}),
            guards=(_still(r.key),),
            args=FrozenDict({"brief:agenda": phrase("agenda.remind.brief", who=who, when=_when(r, frame)),
                             "subject": agenda_c.reminder_subject(r.key)})))
    return out


# ── ce qu'elle en sait, dans l'initiative ─────────────────────────────────


def _reminded(s: AgendaState, frame: Frame) -> Reminded | None:
    ep = frame.episode
    if ep is None or ep.kind != Kind.INITIATIVE:
        return None
    key = agenda_c.reminder_of(ep.attrs.get("subject"))
    return s.reminders.get(key) if key else None


def _shown(event: Event, r: Reminded, owned: bool) -> Event:
    """L'occurrence telle qu'elle la lit : sa période à elle (une fois d'une série) ; privée et pas à elle, « Occupé »."""
    e = instance(event, r.occurrence) if r.occurrence and event.recurring and not event.original else event
    return masked(e) if e.private and not owned else e


@AGENDA.enricher("agenda_reminder", episodes=[Kind.INITIATIVE], deadline_ms=500,
                 reads=[identity_c.PERSON, identity_c.HANDLES, identity_c.IDENTITY, identity_c.OWNERS,
                        presence_c.PRESENT, social_c.CLOSENESS])
async def _gather(s: AgendaState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Le rendez-vous d'un rappel, tel que la base le dit, si le tableau de son agenda le laisse lire devant qui est en
    face, d'elle-même."""
    r = _reminded(s, frame)
    store = ports.get("agenda")
    if r is None or store is None:
        return None
    allowed = here_all(frame, [r.calendar]).get(r.calendar)
    event, cal = store.event(r.event), store.calendar(r.calendar)
    if allowed is None or event is None or cal is None or event.calendar != r.calendar:
        return None
    return {"event": _shown(event, r, allowed.owned), "calendar": cal.name or cal.key, "keep": allowed.keep}


@AGENDA.section("agenda_reminder", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=88,
                title=phrase("agenda.remind.title"), untrusted=True)
def _section(s: AgendaState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Le rendez-vous dont elle la prévient (cité) ; sa provenance dit le rappel."""
    r = _reminded(s, frame)
    got = enrich.get("agenda_reminder")
    if r is None or not got:
        return None
    e, tz = got["event"], frame.env.tz_of(frame.root)
    title = inert(e.title, TITLE_SHOWN) if e.title.strip() else phrase("agenda.words.busy")
    lines = [phrase("agenda.remind.head"), phrase("agenda.preview.title", title=title),
             phrase("agenda.preview.when", when=when_words(e.span, tz)) + " — " + _when(r, frame)]
    if e.location.strip():
        lines.append(phrase("agenda.preview.where", place=inert(e.location, PLACE_SHOWN)))
    names = [inert(x.name or x.address or x.person, NAME_SHOWN) for x in e.participants if not x.me]
    if names:
        lines.append(phrase("agenda.remind.with", who=", ".join(names[:PEOPLE_SHOWN])))
    if e.description.strip():
        lines.append(phrase("agenda.preview.note", text=inert(e.description, NOTE_SHOWN)))
    lines.append(phrase("agenda.remind.calendar", name=inert(got["calendar"], NAME_SHOWN)))
    keep = got["keep"]
    return SectionBody("\n".join(lines), level=int(Sensitivity.PERSONAL), witness=True,
                       floor=KEEP_FLOORS.get(keep, 0), unkept=keep == "rien",
                       provenance=(agenda_c.reminder_subject(r.key),))


__all__ = ["READS", "due"]
