"""Préparer la réponse à une invitation (ADR 0309, lot 3b) : une tâche silencieuse (``Kind.TASK``), comme celles de
Teams et du courrier.

- **Quand** : une invitation qui attend sa réponse (``agenda.invitation_noticed``, que ``watch`` pose dans un agenda où
  la ligne « elle seule, au travail » laisse répondre) appelle une tâche — une seule : quand sa réponse est proposée,
  refusée ou partie, plus rien ; une tâche qui n'a rien proposé se retente au plus ``prepare_attempts`` fois ; au plus
  ``prepare_per_day`` par jour ; jamais une invitation commencée ou réglée (sa garde, ``agenda.INVITATION``).
- **Ce qu'elle lit** : « L'INVITATION À LAQUELLE TU PRÉPARES UNE RÉPONSE » — l'invitation (quand, son titre, son lieu,
  qui l'organise, avec qui, sa note), et ce qui tombe en même temps dans les agendas de la personne invitée que la
  ligne « au travail » laisse lire — tout venu du dehors, cité. Ses outils : le lot ``agenda`` (lire ces agendas,
  ``agenda_respond`` sur cette invitation seule), sa mémoire et l'identité, comme pour un courrier : ce qu'elle sait
  de la personne (« tu lui as dit jeudi vouloir le passer avant la fin du mois »).
- **Ce qui en sort** : une réponse proposée (oui, peut-être, non), un mot pour qui l'organise, et pourquoi (pour la
  personne, jamais envoyé) — toujours sur l'accord de la personne invitée : sa carte dans son chat, et la console
  (``tools.propose``). Si elle répond elle-même entre-temps, la proposition tombe (« Répondu autrement », ``watch``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import agenda as agenda_c
from mika.contracts import identity as identity_c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.agenda import AGENDA, OWNER, AgendaState, Invited, owner, params_of
from mika.plugins.agenda.rights import at_work
from mika.plugins.agenda.tools import (
    NAME_SHOWN,
    PEOPLE_SHOWN,
    PLACE_SHOWN,
    TEXT_SHOWN,
    TITLE_SHOWN,
    invitation_of,
    local_span,
    when_words,
)
from mika.ports.agenda import CANCELLED, Event, Occurrence, masked, occurrences, split_calendar_key
from mika.ports.preprocess import inert
from mika.vocab.access import NO as CLOSED
from mika.vocab.access import PERSON
from mika.vocab.episodes import Kind, task_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.rights import closeness_of, rights_of
from mika.vocab.words import elided

#: les lots d'une tâche d'invitation : l'agenda, sa mémoire, l'identité (comme pour un courrier)
BUNDLES = "agenda,memory,identity"
#: au plus tant de rendez-vous qui tombent en même temps, montrés
CLASHES_SHOWN = 6


@AGENDA.fact(agenda_c.INVITATION)
def _invitation(s: AgendaState, cx: Any, key: str) -> str:
    inv = s.invitations.get(key)
    return inv.status if inv is not None else ""


def _still(key: str) -> Guard:
    """La tâche ne vaut que tant que l'invitation attend (réglée entre-temps : plus rien à préparer)."""
    return Guard("invitation", predicate=lambda view, k=key: view.get(agenda_c.INVITATION(k)) == agenda_c.PENDING)


def holder_name(frame: Frame, holder: str) -> str:
    """La personne invitée, comme elle la nomme : son prénom ; un agenda « à toi » : qui s'occupe d'elle."""
    if holder.startswith(PERSON):
        return identity_c.person_name(frame, holder[len(PERSON):]) or phrase("agenda.words.someone")
    return identity_c.keepers(frame)


def _today(s: AgendaState, now: int) -> int:
    """Les tâches d'invitation des dernières vingt-quatre heures (essayées, ou qui ont proposé)."""
    return sum(1 for i in s.invitations.values() if (i.attempts or i.proposal) and now - i.at < DAY)


@AGENDA.propose(kinds=[Kind.TASK], reasons={agenda_c.PREPARE: (0.0, 14.0)},
                reads=[agenda_c.INVITATION, identity_c.IDENTITY, identity_c.OWNERS])
def _prepare(s: AgendaState, frame: Frame) -> list[Candidate]:
    p = params_of(frame)
    budget = p.prepare_per_day - _today(s, frame.now)
    out: list[Candidate] = []
    for inv in sorted(s.invitations.values(), key=lambda i: (i.start, i.key)):
        if budget <= 0:
            break
        if inv.status != agenda_c.PENDING or inv.proposal or inv.attempts >= p.prepare_attempts \
                or inv.start <= frame.now:
            continue
        who = holder_name(frame, inv.holder)
        brief = phrase("agenda.task.brief", who=who, of=elided(who, "de"), ref=f"ev{inv.event}")
        out.append(Candidate(Kind.TASK, task_target(OWNER, inv.key), agenda_c.PREPARE, p.prepare_evidence,
                             resources=frozenset({f"agenda:{inv.calendar}"}), guards=(_still(inv.key),),
                             args=FrozenDict({"bundles": BUNDLES, "brief:agenda": brief, "invitation": inv.key})))
        budget -= 1
    return out


# ── ce qu'elle lit dans sa tâche ──────────────────────────────────────────


def _clashes(store: Any, frame: Frame, inv: Invited, event: Event) -> list[Occurrence]:
    """Ce qui tombe en même temps que sa prochaine occurrence, dans les agendas de la personne invitée que la ligne
    « au travail » laisse lire : occupé, ni refusé ni annulé, pas elle-même."""
    p, rights, close = params_of(frame), rights_of(frame.env), closeness_of(frame.env, frame)
    tz = frame.env.tz_of(frame.root)
    found = occurrences(event, frame.now, inv.start + DAY, limit=1)
    if not found:
        return []
    lo, hi = local_span(found[0].span, tz)
    theirs = [c.key for c in store.calendars() if owner(p, split_calendar_key(c.key)[0]) == inv.holder
              and at_work(p, rights, c.key, close) is not None]
    return [o for o in store.period(theirs, lo, hi) if o.event.busy and o.event.status != CANCELLED
            and (o.event.calendar, o.event.uid) != (event.calendar, event.uid)
            and local_span(o.span, tz)[0] < hi and local_span(o.span, tz)[1] > lo][:CLASHES_SHOWN]


@AGENDA.enricher("agenda_invitation", episodes=[Kind.TASK], deadline_ms=1000, reads=[identity_c.OWNERS])
async def _gather(s: AgendaState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """L'invitation de cette tâche telle que la base la dit, et ce qui tombe en même temps — si la ligne « au
    travail » de son agenda laisse y répondre."""
    inv = invitation_of(frame)
    store = ports.get("agenda")
    if inv is None or store is None:
        return None
    p = params_of(frame)
    h = at_work(p, rights_of(frame.env), inv.calendar, closeness_of(frame.env, frame))
    event, cal = store.find(inv.calendar, inv.uid, inv.original), store.calendar(inv.calendar)
    if h is None or h.respond == CLOSED or event is None or cal is None:
        return None
    names = {c.key: c.name or c.key for c in store.calendars()}
    return {"event": event, "calendar": cal.name or cal.key, "clashes": _clashes(store, frame, inv, event),
            "names": names}


def _line(e: Event, when: str, calendar: str, *, owned: bool = True) -> str:
    """Un rendez-vous en une ligne : quand, son titre (« Occupé » sans), son lieu, son agenda — rendus inertes."""
    shown = masked(e) if e.private and not owned else e
    title = inert(shown.title, TITLE_SHOWN) if shown.title.strip() else phrase("agenda.words.busy")
    parts = [when, phrase("agenda.words.title", title=title)]
    if shown.location.strip():
        parts.append(phrase("agenda.words.where", place=inert(shown.location, PLACE_SHOWN)))
    parts.append(phrase("agenda.words.in", name=inert(calendar, NAME_SHOWN)))
    return "- " + " · ".join(parts)


@AGENDA.section("agenda_invitation", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=90,
                title=phrase("agenda.task.title"), untrusted=True)
def _section(s: AgendaState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """L'invitation dont elle prépare la réponse, et ce qui tombe en même temps dans ses agendas (cité)."""
    inv = invitation_of(frame)
    got = enrich.get("agenda_invitation")
    if inv is None or not got:
        return None
    e, tz = got["event"], frame.env.tz_of(frame.root)
    found = occurrences(e, frame.now, inv.start + DAY, limit=1)
    span = found[0].span if found else e.span
    lines = [phrase("agenda.task.head", ref=f"ev{e.id}"), phrase("agenda.preview.title", title=inert(
        e.title, TITLE_SHOWN) if e.title.strip() else phrase("agenda.words.busy")),
             phrase("agenda.preview.when", when=when_words(span, tz))]
    if e.recurring:
        lines.append(phrase("agenda.task.series"))
    if e.location.strip():
        lines.append(phrase("agenda.preview.where", place=inert(e.location, PLACE_SHOWN)))
    org = e.organizer
    if org is not None and not org.me and (org.name or org.address or org.person):
        lines.append(phrase("agenda.task.from", who=inert(org.name or org.address or org.person, NAME_SHOWN)))
    names = [inert(x.name or x.address or x.person, NAME_SHOWN) for x in e.participants if not x.me]
    if names:
        lines.append(phrase("agenda.remind.with", who=", ".join(names[:PEOPLE_SHOWN])))
    if e.description.strip():
        lines.append(phrase("agenda.preview.note", text=inert(e.description, TEXT_SHOWN)))
    lines.append(phrase("agenda.remind.calendar", name=inert(got["calendar"], NAME_SHOWN)))
    clashes = got["clashes"]
    if clashes:
        lines.append(phrase("agenda.task.clashes"))
        lines += [_line(o.event, when_words(o.span, tz), got["names"].get(o.event.calendar, o.event.calendar))
                  for o in clashes]
    else:
        lines.append(phrase("agenda.task.free"))
    return SectionBody("\n".join(lines), level=int(Sensitivity.PERSONAL), witness=True)


__all__ = ["BUNDLES", "holder_name"]
