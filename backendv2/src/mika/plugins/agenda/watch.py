"""Ce qu'elle voit venir dans les agendas, d'elle-même (ADR 0309, lot 3b) : le processus ``agenda.watch``, qui relit la
base à chaque passage — au plus une minute d'écart, et à l'instant où quelque chose devient dû.

- **Les rappels** : pour chaque agenda dont elle se sert (``hers``) et chaque rendez-vous des trente heures qui
  viennent, « Mika te le rappelle » (celui de l'événement, sinon celui de l'agenda : ``reminder``) dit quand le
  rappeler — tant de minutes avant, ou la veille au soir (``eve_hour``) ; une journée entière ne se rappelle que la
  veille. Dû et pas encore commencé, il devient ``agenda.reminder_due`` (une fois par occurrence : sa clé porte son
  agenda, son événement, sa clé dans une série et son début — déplacée, c'en est une autre), pour la personne à qui
  est l'agenda (ses propriétaires, pour un agenda « à toi »). Ni un refusé, ni un annulé (la base ne les rend pas).
  Un rappel dû qui n'a plus lieu d'être (le rendez-vous a bougé, est parti, ou son agenda ne le demande plus) tombe
  (``agenda.reminder_dropped``). Qui le dit, quand, et si le tableau le permet : ``remind``.
- **Les invitations** : dans un agenda où la ligne « elle seule, au travail » laisse répondre (``rights.at_work``),
  et qui sait répondre, une invitation qui attend sa réponse devient ``agenda.invitation_noticed`` (une fois) ; une
  tâche la prépare (``tasks``). Répondue (par la personne, ou par ce qu'elle a préparé), partie, ou commencée, elle
  est réglée (``agenda.invitation_settled``).
- **Ce qui attend un accord** ne vit pas indéfiniment : une proposition d'agenda qui attend tombe quand son rendez-vous
  commence (ou a disparu, été annulé) — refusée au nom du délai (``EXPIRED``) ; une réponse d'invitation tombe quand la
  personne a répondu elle-même, dans l'écran ou chez le fournisseur — « Répondu autrement » (``ELSEWHERE``), comme
  pour Teams (ADR 0199). La carte du chat, elle, ne vaut que ``card_within_us`` (``tools.propose``) : passé ce délai,
  la proposition reste à décider dans l'Agenda jusqu'au début du rendez-vous.

Rien n'y est écrit en mots : les titres, les lieux, les noms restent dans la base.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any

from mika.contracts import agenda as agenda_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE, instant, local
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Superseded
from mika.plugins.agenda import (
    AGENDA,
    ANSWERED,
    BEGUN,
    CAPABILITY,
    CREATE,
    ELSEWHERE,
    EXPIRED,
    GONE,
    INVITATION_NOTICED,
    INVITATION_SETTLED,
    LEFT,
    MOVED,
    OFF,
    OWNER,
    REMINDER_DROPPED,
    REMINDER_DUE,
    RESPOND,
    WAITING,
    AgendaParams,
    AgendaState,
    Invited,
    Reminded,
    Written,
    hers,
    owner,
    params_of,
    reminder,
)
from mika.plugins.agenda.rights import at_work
from mika.ports.agenda import (
    CANCELLED,
    DAY_US,
    NEEDS,
    REMINDERS,
    AgendaPort,
    Event,
    Occurrence,
    Span,
    day_of,
    occurrences,
    split_calendar_key,
)
from mika.vocab.access import NO, PERSON
from mika.vocab.phrasebook import phrase
from mika.vocab.rights import closeness_of, rights_of

log = logging.getLogger("mika.agenda")

#: au plus tant entre deux passages : un rendez-vous ajouté se voit au plus tard alors
SCAN_EVERY = MINUTE
#: ce qu'un passage lit devant lui : la veille au soir d'un rendez-vous du surlendemain matin compris
LOOKAHEAD = 30 * HOUR
#: « la veille au soir »
EVE = "veille"
#: les délais de « Mika te le rappelle » qui rappellent (« non » n'en est pas un)
DELAYS = frozenset(k for k, _ in REMINDERS) - {"non"}
#: une invitation se lit au plus si loin devant (sa prochaine occurrence)
INVITATION_AHEAD = 400 * DAY


def digest(*parts: object) -> str:
    """Une clé courte et stable : jamais un titre ni une adresse."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8", "surrogatepass")).hexdigest()[:20]


def reminder_key(o: Occurrence) -> str:
    """L'occurrence telle qu'elle est : son agenda, son événement, sa clé dans une série, son début — déplacée, une
    autre."""
    e = o.event
    return digest(e.calendar, e.uid, o.key or e.original, o.span.start)


def invitation_key(e: Event) -> str:
    return digest(e.calendar, e.uid, e.original)


def remind_at(start: int, all_day: bool, delay: str, tz: Any, eve_hour: int) -> int | None:
    """Quand rappeler un rendez-vous à ce délai : tant de minutes avant ; la veille au soir, à ``eve_hour`` (une
    journée entière : la veille de son premier jour). Une journée entière ne se rappelle qu'ainsi : ``None``."""
    if delay == EVE:
        first = date.fromisoformat(day_of(start)) if all_day else local(start, tz).date()
        return instant(datetime.combine(first - timedelta(days=1), time(eve_hour), tzinfo=tz))
    if all_day or delay not in DELAYS or not delay.isdigit():
        return None
    return start - int(delay) * MINUTE


def starts_at(span: Span, tz: Any) -> int:
    """L'instant où commence une occurrence, dans ce fuseau (une journée entière : à minuit de son premier jour)."""
    if not span.all_day:
        return span.start
    return instant(datetime.combine(date.fromisoformat(day_of(span.start)), time(), tzinfo=tz))


def delay_of(store: AgendaPort, o: Occurrence, fallback: str) -> str:
    """« Mika te le rappelle » pour cette occurrence : celui de sa ligne, sinon celui de sa série (une exception),
    sinon celui de son agenda."""
    e = o.event
    if e.remind:
        return e.remind
    if e.original:
        master = store.find(e.calendar, e.uid, "")
        if master is not None and master.remind:
            return master.remind
    return fallback


def people(frame: Frame, holder: str) -> list[str]:
    """Qui prévenir d'un rendez-vous de cet agenda : la personne à qui il est ; « à toi » : ses propriétaires."""
    if holder.startswith(PERSON):
        return [holder[len(PERSON):]]
    return [str(o) for o in frame.get(identity_c.OWNERS)]


# ── les rappels ───────────────────────────────────────────────────────────


def _kind(ports: Any, calendar: str) -> str | None:
    """La sorte du compte de cet agenda ; ``None`` : un compte décoché ou inconnu."""
    providers = ports.get("agenda_providers")
    conn = providers.connection(split_calendar_key(calendar)[0]) if providers is not None else None
    return conn.kind if conn is not None and conn.enabled else None


def due_reminders(store: AgendaPort, ports: Any, frame: Frame, p: AgendaParams,
                  s: AgendaState) -> tuple[list[Any], list[int]]:
    """Les rappels devenus dus (des brouillons d'``agenda.reminder_due``) et les instants où d'autres le deviendront."""
    now, tz = frame.now, frame.env.tz_of(frame.root)
    drafts: list[Any] = []
    later: list[int] = []
    for cal in store.calendars():
        if not hers(p, cal.key):
            continue
        kind = _kind(ports, cal.key)
        if kind is None:
            continue
        fallback = reminder(p, cal.key, kind)
        persons = people(frame, owner(p, split_calendar_key(cal.key)[0]))
        if not persons:
            continue
        for o in store.period([cal.key], now, now + LOOKAHEAD):
            if o.event.status == CANCELLED or o.event.declined:
                continue
            delay = delay_of(store, o, fallback)
            start = starts_at(o.span, tz)
            at = remind_at(o.span.start, o.span.all_day, delay, tz, p.eve_hour)
            if at is None or start <= now:
                continue
            if at > now:
                later.append(at)
                continue
            key = reminder_key(o)
            for person in persons:
                k = digest(key, person) if len(persons) > 1 else key
                if k in s.reminders:
                    continue
                drafts.append(REMINDER_DUE.draft(
                    key=k, person=person, calendar=cal.key, event=o.event.id, occurrence=o.key, start=start,
                    end=o.span.end, all_day=o.span.all_day, delay=delay, about=(person,),
                    dedupe_key=f"agenda-rappel:{k}"))
    return drafts, later


def dropped_reminders(store: AgendaPort, ports: Any, frame: Frame, p: AgendaParams, s: AgendaState) -> list[Any]:
    """Les rappels dus qui n'ont plus lieu d'être : le rendez-vous a bougé (ou est parti, refusé, annulé), son agenda
    ne le demande plus, ou ne lui sert plus."""
    now = frame.now
    out = []
    for r in s.reminders.values():
        if r.status != agenda_c.DUE or r.start <= now:
            continue
        why = _why_dropped(store, ports, frame, p, r)
        if why:
            out.append(REMINDER_DROPPED.draft(key=r.key, why=why, dedupe_key=f"agenda-rappel-tombe:{r.key}"))
    return out


def _why_dropped(store: AgendaPort, ports: Any, frame: Frame, p: AgendaParams, r: Reminded) -> str:
    kind = _kind(ports, r.calendar)
    if not hers(p, r.calendar) or kind is None:
        return OFF
    row = store.event(r.event)
    if row is None or row.calendar != r.calendar:
        return GONE
    found = [o for o in store.period([r.calendar], r.start - DAY_US, r.start + DAY_US)
             if o.event.id == r.event and o.key == r.occurrence]
    if not found:
        return MOVED if row.status != CANCELLED and not row.declined else GONE
    o = found[0]
    if starts_at(o.span, frame.env.tz_of(frame.root)) != r.start:
        return MOVED
    if delay_of(store, o, reminder(p, r.calendar, kind)) not in DELAYS:
        return OFF
    return ""


# ── les invitations ───────────────────────────────────────────────────────


def _answers(ports: Any, calendar: str) -> bool:
    """Ce compte sait-il répondre à une invitation (écrire, et transmettre la réponse) ?"""
    providers = ports.get("agenda_providers")
    conn = providers.connection(split_calendar_key(calendar)[0]) if providers is not None else None
    provider = providers.of(conn.kind) if conn is not None else None
    if conn is None or provider is None or not conn.enabled:
        return False
    able = provider.abilities(conn)
    return bool(able.write and able.invite)


def next_start(e: Event, now: int) -> int:
    """Le début de sa prochaine occurrence (une série : celle qui vient) ; 0 : plus aucune."""
    found = occurrences(e, now, now + INVITATION_AHEAD, limit=1)
    return found[0].span.start if found else 0


def noticed_invitations(store: AgendaPort, ports: Any, frame: Frame, p: AgendaParams, s: AgendaState) -> list[Any]:
    """Les invitations qui attendent une réponse, dans un agenda où elle peut la préparer seule, au travail."""
    rights, close = rights_of(frame.env), closeness_of(frame.env, frame)
    open_ = []
    for cal in store.calendars():
        if not cal.writable or not _answers(ports, cal.key):
            continue
        h = at_work(p, rights, cal.key, close)
        if h is not None and h.respond != NO:
            open_.append(cal.key)
    if not open_:
        return []
    out = []
    for e in store.invitations(open_):
        key = invitation_key(e)
        start = next_start(e, frame.now)
        if key in s.invitations or start <= frame.now or e.status == CANCELLED:
            continue
        holder = owner(p, split_calendar_key(e.calendar)[0])
        out.append(INVITATION_NOTICED.draft(
            key=key, calendar=e.calendar, event=e.id, uid=e.uid, original=e.original, holder=holder, start=start,
            about=tuple(people(frame, holder)), dedupe_key=f"agenda-invitation:{key}"))
    return out


def settled_invitations(store: AgendaPort, frame: Frame, s: AgendaState) -> list[Any]:
    """Les invitations qui n'attendent plus : répondues, parties, commencées."""
    out = []
    for inv in s.invitations.values():
        if inv.status != agenda_c.PENDING:
            continue
        why = _why_settled(store, frame, inv)
        if why:
            out.append(INVITATION_SETTLED.draft(key=inv.key, why=why, dedupe_key=f"agenda-invitation-reglee:{inv.key}"))
    return out


def _why_settled(store: AgendaPort, frame: Frame, inv: Invited) -> str:
    row = store.find(inv.calendar, inv.uid, inv.original)
    if row is None or row.status == CANCELLED:
        return LEFT
    if row.response != NEEDS:
        return ANSWERED
    return BEGUN if inv.start <= frame.now else ""


# ── ce qui attend un accord ───────────────────────────────────────────────


def fallen(store: AgendaPort, frame: Frame, w: Written) -> str:
    """Pourquoi une proposition qui attend n'a plus lieu d'être : ``ELSEWHERE`` (la personne a répondu elle-même à
    l'invitation), ``EXPIRED`` (son rendez-vous a commencé, ou il a disparu, été annulé) ; vide : elle attend."""
    if w.op != CREATE:
        row = store.find(w.calendar, w.uid, w.original) if w.uid else None
        if row is None or row.status == CANCELLED:
            return EXPIRED
        if w.op == RESPOND and row.response != NEEDS:
            return ELSEWHERE
    return EXPIRED if w.starts and frame.now >= w.starts else ""


async def _fall(ctx: Any, frame: Frame, w: Written, why: str) -> None:
    """Refuser au nom de ce qui l'a fait tomber (elle le saura comme d'un refus), seulement si personne n'a décidé
    entre-temps."""
    context = next((v.context for v in frame.get(rt.PENDING_EFFECTS) if v.proposal == w.proposal), w.target)
    note = phrase("agenda.fallen.elsewhere") if why == ELSEWHERE else phrase("agenda.fallen.begun")
    draft = rt.EFFECT_RESOLVED.draft(
        proposal=w.proposal, approved=False, by=why, note=Content.of(note), capability=CAPABILITY, owner=OWNER,
        context=context, about=tuple(dict.fromkeys(x for x in (w.target, w.decider) if x)),
        dedupe_key=f"décision:{w.proposal}")
    try:
        await ctx.emit(draft, guard=rt.still_pending(w.proposal), emitter=rt.OWNER)
    except Superseded:  # décidée entre-temps : rien à faire ; toute autre panne remonte, la santé la voit
        return


def waiting(s: AgendaState) -> Iterable[Written]:
    return [w for w in s.writes.values() if w.status == WAITING and w.approval]


@AGENDA.process("agenda.watch", wake_on=[rt.EFFECT_PROPOSED], catch_up=CatchUp.ONCE, max_quantum_s=60, priority=60,
                deadline_s=120)
class Watch:
    def __init__(self) -> None:
        #: le prochain instant où quelque chose deviendra dû (``None`` : pas encore passé)
        self.due: int | None = None

    def next_due(self, s: AgendaState | None, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if self.due is None else max(frame.now, self.due)

    async def run(self, ctx: Any) -> None:
        store = ctx.ports.get("agenda")
        now = ctx.now
        if store is None:
            self.due = now + HOUR
            return
        frame, s = ctx.frame, ctx.state
        p = params_of(frame)
        due, later = due_reminders(store, ctx.ports, frame, p, s)
        drafts = [*due, *dropped_reminders(store, ctx.ports, frame, p, s),
                  *noticed_invitations(store, ctx.ports, frame, p, s), *settled_invitations(store, frame, s)]
        if drafts:
            await ctx.emit(*drafts)
        for w in waiting(ctx.state):
            why = fallen(store, ctx.frame, w)
            if why:
                await _fall(ctx, ctx.frame, w, why)
            elif w.starts > now:
                later.append(w.starts)
        later += [r.start for r in ctx.state.reminders.values() if r.status == agenda_c.DUE and r.start > now]
        self.due = min([now + SCAN_EVERY, *(t for t in later if t > now)])


__all__ = ["EVE", "LOOKAHEAD", "SCAN_EVERY", "Watch", "digest", "due_reminders", "fallen", "invitation_key",
           "next_start", "people", "remind_at", "reminder_key"]
