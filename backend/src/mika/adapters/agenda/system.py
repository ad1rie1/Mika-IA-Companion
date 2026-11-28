"""Le fournisseur Système (ADR 0309) : l'agenda de ce serveur, dont les événements font foi dans la base ``agenda``.

- **Chaque personne qui a un compte a le sien** (``ports.agenda.system_account`` : ``moi:<sa clé>``, à elle), avec
  « Mon agenda » d'office (``ensure``, à la première lecture) ; elle en crée d'autres (``create_calendar``).
- **Une série** (une RRULE) se change par occurrence (``ONE`` : une exception, ``ports.agenda.instance``), à partir
  d'une occurrence (``FOLLOWING`` : la série coupée en deux, ``ports.agenda.split_rule``, la seconde sous un nouvel
  UID) ou en entier (``ALL``). Une exception suit ce qui change dans sa série, champ par champ, là où elle avait
  encore la valeur de la série (``_inherit``) ; un changement d'heure de la série déplace aussi les clés de ses
  exceptions et ses EXDATE.
- **Les invitations entre personnes qui ont un compte** : une participante désignée par sa clé de personne reçoit une
  copie de l'événement dans son « Mon agenda » (``origin`` : l'agenda de l'organisatrice ; ``response`` : sa réponse,
  en attente d'abord), sans e-mail. Les copies se déduisent des lignes de l'organisatrice (``_fan_out``) : elles sont
  réécrites à chaque changement, dans la même écriture. Sa réponse revient à l'organisatrice (sa ligne de
  participante), pour la série ou pour une occurrence ; supprimer une invitation de son agenda, c'est la refuser ;
  une invitation ne se modifie que chez qui l'organise. Une participante retirée d'une occurrence y voit cette
  occurrence annulée ; retirée de la série, sa copie part.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace

from mika.adapters.agenda.store import AgendaStore
from mika.ports.agenda import (
    ALL,
    CANCELLED,
    DEFAULT_CALENDAR,
    DEFAULT_CALENDAR_NAME,
    FOLLOWING,
    MAYBE,
    NEEDS,
    NO,
    ONE,
    SYSTEM,
    YES,
    Abilities,
    AgendaError,
    Calendar,
    Connection,
    Event,
    EventChange,
    EventDraft,
    Participant,
    Recurrence,
    Span,
    SyncBatch,
    Window,
    calendar_key,
    instance,
    key_instant,
    occurrence_key,
    occurrences,
    shifted_key,
    split_rule,
    system_account,
    system_person,
)
from mika.vocab.access import PERSON

#: ce qu'une exception reprend de sa série quand elle en avait encore la valeur
_INHERITED = ("title", "location", "description", "conference", "busy", "private", "status", "reminders",
              "participants")
#: ce qu'un changement peut dire (``EventChange``), hors de la période et de la règle
_SIMPLE = ("title", "location", "description", "conference", "busy", "private", "status", "reminders", "added")


def _new_id() -> str:
    return uuid.uuid4().hex


class SystemProvider:
    """Un ``CalendarProvider`` sur la base elle-même."""

    kind = SYSTEM

    def __init__(self, store: AgendaStore, *, new_id: Callable[[], str] = _new_id) -> None:
        self.store = store
        self._new_id = new_id
        #: une écriture à la fois (lire la série, la changer, l'écrire avec ses copies) : deux fils ne s'y croisent pas
        self._lock = threading.RLock()

    def abilities(self, account: Connection) -> Abilities:
        return Abilities(write=True, invite=True, incremental=True, calendars=True)

    # ── ses agendas ──
    def ensure(self, account: str) -> list[Calendar]:
        """Les agendas d'un compte du système, « Mon agenda » compris (né à la première lecture)."""
        person = system_person(account)
        if not person:
            raise AgendaError(f"pas un compte du système : {account[:60]}")
        found = self.store.calendars(account)
        if any(c.primary for c in found):
            return found
        self.store.keep_account(account, SYSTEM, owner=PERSON + person)
        self.store.add_calendar(Calendar(calendar_key(account, DEFAULT_CALENDAR), account, DEFAULT_CALENDAR,
                                         DEFAULT_CALENDAR_NAME, primary=True))
        return self.store.calendars(account)

    def default_calendar(self, person: str) -> Calendar:
        """« Mon agenda » de cette personne (né au besoin) : où ses invitations arrivent."""
        return next(c for c in self.ensure(system_account(person)) if c.primary)

    async def calendars(self, account: Connection) -> list[Calendar]:
        return self.ensure(account.key)

    async def create_calendar(self, account: Connection, name: str) -> Calendar:
        name = name.strip()
        if not name:
            raise AgendaError("un agenda a un nom")
        self.ensure(account.key)
        local = "a" + self._new_id()[:12]
        return self.store.add_calendar(Calendar(calendar_key(account.key, local), account.key, local, name[:200]))

    async def sync(self, account: Connection, calendar: Calendar, cursor: str, window: Window) -> SyncBatch:
        """Rien à relire : ses événements font foi dans la base."""
        return SyncBatch(cursor=cursor)

    # ── écrire : une opération à la fois ──
    async def create(self, account: Connection, calendar: Calendar, draft: EventDraft) -> Event:
        with self._lock:
            return self._create(account, calendar, draft)

    async def edit(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, change: EventChange,
                   scope: str = ALL) -> Event:
        with self._lock:
            return self._edit(account, calendar, event, occurrence, change, scope)

    async def delete(self, account: Connection, calendar: Calendar, event: Event, occurrence: str,
                     scope: str = ALL) -> int:
        with self._lock:
            return self._delete(account, calendar, event, occurrence, scope)

    async def respond(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, response: str,
                      scope: str = ALL, comment: str = "") -> Event:
        """``comment`` : le système n'envoie rien, il ne se garde pas."""
        with self._lock:
            return self._respond(account, calendar, event, occurrence, response, scope)

    def _create(self, account: Connection, calendar: Calendar, draft: EventDraft) -> Event:
        person = self._writable(account, calendar)
        if not draft.title.strip():
            raise AgendaError("un événement a un titre")
        if draft.span.end < draft.span.start:
            raise AgendaError("un événement finit après avoir commencé")
        event = Event(calendar=calendar.key, uid=f"{self._new_id()}@mika", span=draft.span, title=draft.title.strip(),
                      location=draft.location, description=draft.description, conference=draft.conference,
                      recurrence=Recurrence(draft.rule) if draft.rule else None, status=draft.status,
                      busy=draft.busy, private=draft.private, organizer=Participant(person=person, me=True),
                      participants=_invited(draft.participants, person),
                      added=draft.added)
        self._commit(calendar.key, person, [event], [event.uid])
        return self._one(calendar.key, event.uid, "")

    def _edit(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, change: EventChange,
              scope: str) -> Event:
        person = self._writable(account, calendar)
        if event.origin:
            raise AgendaError("une invitation se modifie chez qui l'organise : on y répond")
        rows = self._rows(calendar.key, event.uid)
        master = next((r for r in rows if not r.original), None)
        key = occurrence or event.original
        if master is None or not master.recurring:
            target = next((r for r in rows if r.original == event.original), event)
            self._commit(calendar.key, person, [_with(target, change, person)], [event.uid])
            return self._one(calendar.key, event.uid, event.original)
        if scope == ONE and key:
            current = _occurring(master, rows, key)
            self._commit(calendar.key, person, [_with(current, replace(change, rule=None), person)], [event.uid])
            return self._one(calendar.key, event.uid, key)
        if scope == FOLLOWING and key and key != _first_key(master):
            _occurring(master, rows, key)
            return self._split(calendar.key, person, master, rows, key, change)
        if change.span is not None and key:  # depuis une occurrence : la série garde son premier jour, prend l'heure
            moved = change.span.start - instance(master, key).span.start
            length = change.span.end - change.span.start
            change = replace(change, span=Span(master.span.start + moved, master.span.start + moved + length,
                                               change.span.zone, change.span.all_day))
        self._whole(calendar.key, person, master, rows, change)
        return self._one(calendar.key, event.uid, "")

    def _whole(self, calendar: str, person: str, master: Event, rows: Sequence[Event], change: EventChange) -> None:
        """Toute la série : elle change, ses exceptions suivent ce qu'elles tenaient d'elle ; une heure changée
        déplace leurs clés et ses EXDATE ; sa règle retirée, ses exceptions partent."""
        after = _with(master, change, person)
        delta = after.span.start - master.span.start
        if after.recurrence is not None and delta:
            rec = after.recurrence
            after = replace(after, recurrence=replace(rec, exdates=tuple(shifted_key(k, delta) for k in rec.exdates),
                                                      rdates=tuple(shifted_key(k, delta) for k in rec.rdates)))
        removed: list[tuple[str, str, str | None]] = []
        kept: list[Event] = []
        for row in rows:
            if not row.original:
                continue
            if delta or not after.recurring:  # sa clé change, ou la série n'en a plus : l'ancienne ligne part
                removed.append((calendar, row.uid, row.original))
            if after.recurring:
                kept.append(_inherit(row, master, after, shifted_key(row.original, delta) if delta else row.original))
        self._commit(calendar, person, [after, *kept], [master.uid], removed=removed)

    def _split(self, calendar: str, person: str, master: Event, rows: Sequence[Event], key: str,
               change: EventChange) -> Event:
        """Celui-ci et les suivants : la série finit juste avant cette occurrence ; une nouvelle série, sous un nouvel
        UID, commence à elle avec ce qui change, et emporte les exceptions et les EXDATE qui la suivent."""
        before_rule, after_rule = split_rule(master, key)
        at = key_instant(key)
        rec = master.recurrence or Recurrence()
        old = replace(master, recurrence=Recurrence(
            before_rule, tuple(k for k in rec.exdates if key_instant(k) < at),
            tuple(k for k in rec.rdates if key_instant(k) < at)))
        uid = f"{self._new_id()}@mika"
        start = replace(instance(master, key), uid=uid, original="", recurrence=Recurrence(
            after_rule, tuple(k for k in rec.exdates if key_instant(k) >= at),
            tuple(k for k in rec.rdates if key_instant(k) >= at)))
        new = _with(start, change, person)
        delta = new.span.start - start.span.start
        removed: list[tuple[str, str, str | None]] = []
        moved: list[Event] = []
        for row in rows:
            if row.original and key_instant(row.original) >= at:
                removed.append((calendar, row.uid, row.original))
                moved.append(_inherit(replace(row, uid=uid, id=0), start, new,
                                      shifted_key(row.original, delta) if delta else row.original))
        self._commit(calendar, person, [old, new, *moved], [master.uid, uid], removed=removed)
        return self._one(calendar, uid, "")

    def _delete(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, scope: str) -> int:
        if event.origin:  # une invitation qu'on retire de son agenda : refusée
            self._respond(account, calendar, event, occurrence, NO, scope if scope != FOLLOWING else ALL)
            return 1
        person = self._writable(account, calendar)
        rows = self._rows(calendar.key, event.uid)
        master = next((r for r in rows if not r.original), None)
        key = occurrence or event.original
        if master is None or not master.recurring or scope == ALL or not key \
                or (scope == FOLLOWING and key == _first_key(master)):
            self._commit(calendar.key, person, [], [event.uid], removed=[(calendar.key, event.uid, None)])
            return len(rows) or 1
        rec = master.recurrence or Recurrence()
        at = key_instant(key)
        if scope == ONE:
            kept = replace(master, recurrence=replace(rec, exdates=tuple(dict.fromkeys((*rec.exdates, key)))))
            gone = [(calendar.key, event.uid, key)]
        else:  # FOLLOWING
            before_rule, _after = split_rule(master, key)
            kept = replace(master, recurrence=Recurrence(before_rule, tuple(k for k in rec.exdates
                                                                            if key_instant(k) < at),
                                                         tuple(k for k in rec.rdates if key_instant(k) < at)))
            gone = [(calendar.key, r.uid, r.original) for r in rows if r.original and key_instant(r.original) >= at]
        self._commit(calendar.key, person, [kept], [event.uid], removed=gone)
        return len(gone) or 1

    def _respond(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, response: str,
                 scope: str) -> Event:
        """Sa réponse revient à l'organisatrice (sa ligne de participante dans la série, ou dans une occurrence) ; sa
        copie suit."""
        if response not in (YES, MAYBE, NO):
            raise AgendaError("une réponse est oui, peut-être ou non")
        if scope == FOLLOWING:
            raise AgendaError("une réponse vaut pour cet événement ou pour toute la série")
        if calendar.account != account.key:
            raise AgendaError("cet agenda n'est pas de ce compte")
        if not event.origin:
            raise AgendaError("seule une invitation se répond")
        person = system_person(account.key)
        rows = self.store.series(event.origin, event.uid)
        master = next((r for r in rows if not r.original), None)
        if not rows:
            raise AgendaError("cette invitation n'existe plus chez qui l'organise")
        organizer = (master or rows[0]).organizer
        key = occurrence or event.original
        if master is not None and master.recurring and scope == ONE and key:
            changed = [_answered(_occurring(master, rows, key), person, response)]
        else:  # toute la série : chaque ligne où elle est invitée
            changed = [_answered(r, person, response) for r in rows if any(p.person == person for p in r.participants)]
            if not changed:
                raise AgendaError("cette personne n'est pas invitée")
        self._commit(event.origin, organizer.person if organizer else "", changed, [event.uid])
        return self._one(calendar.key, event.uid, key if scope == ONE else "")

    # ── une écriture, et ses copies ──
    def _rows(self, calendar: str, uid: str) -> list[Event]:
        """Les lignes d'un événement tel qu'il est maintenant (jamais une copie périmée, qui le ferait renaître)."""
        rows = self.store.series(calendar, uid)
        if not rows:
            raise AgendaError("cet événement n'existe plus")
        return rows

    def _writable(self, account: Connection, calendar: Calendar) -> str:
        person = system_person(account.key)
        if account.kind != SYSTEM or not person:
            raise AgendaError("pas un compte du système")
        if calendar.account != account.key:
            raise AgendaError("cet agenda n'est pas de ce compte")
        if not calendar.writable:
            raise AgendaError(f"« {calendar.name} » est en lecture seule")
        return person

    def _commit(self, calendar: str, organizer: str, events: Sequence[Event], uids: Sequence[str], *,
                removed: Sequence[tuple[str, str, str | None]] = ()) -> None:
        """Ces lignes de l'organisatrice et ce qu'elles retirent, avec les copies de ses invitées, en une écriture."""
        after = self._after(calendar, events, uids, removed)
        copies, gone = self._fan_out(calendar, organizer, after, uids)
        self.store.save([*events, *copies], removed=[*removed, *gone])

    def _after(self, calendar: str, events: Sequence[Event], uids: Sequence[str],
               removed: Sequence[tuple[str, str, str | None]]) -> list[Event]:
        """Ses lignes de ces séries telles qu'elles seront : ce qui reste, moins ce qui part, plus ce qui s'écrit."""
        rows: dict[tuple[str, str], Event] = {}
        for uid in uids:
            for r in self.store.series(calendar, uid):
                rows[(r.uid, r.original)] = r
        for _cal, uid, original in removed:
            for k in [k for k in rows if k[0] == uid and (original is None or k[1] == original)]:
                del rows[k]
        for e in events:
            rows[(e.uid, e.original)] = e
        return list(rows.values())

    def _fan_out(self, calendar: str, organizer: str, rows: Sequence[Event],
                 uids: Sequence[str]) -> tuple[list[Event], list[tuple[str, str, str | None]]]:
        """Les copies que ces lignes donnent dans le « Mon agenda » de chaque invitée (et celles qui partent)."""
        wanted: dict[tuple[str, str, str], Event] = {}
        masters = {r.uid: r for r in rows if not r.original}
        for row in rows:
            for p in row.participants:
                if p.person and p.person != organizer:
                    target = self.default_calendar(p.person)
                    wanted[(target.key, row.uid, row.original)] = _copy(row, target.key, p.person, p.response)
        for uid, master in masters.items():  # retirée d'une occurrence : elle l'y voit annulée
            invited = {p.person for p in master.participants if p.person and p.person != organizer}
            for row in rows:
                if row.uid != uid or not row.original:
                    continue
                for who in invited - {p.person for p in row.participants}:
                    target = self.default_calendar(who)
                    wanted[(target.key, uid, row.original)] = replace(
                        _copy(row, target.key, who, NEEDS), status=CANCELLED)
        gone: list[tuple[str, str, str | None]] = []
        for uid in uids:
            for c in self.store.copies(calendar, uid):
                if (c.calendar, c.uid, c.original) not in wanted:
                    gone.append((c.calendar, c.uid, c.original))
        return list(wanted.values()), gone

    def _one(self, calendar: str, uid: str, original: str) -> Event:
        found = self.store.find(calendar, uid, original) or self.store.find(calendar, uid, "")
        if found is None:
            raise AgendaError("l'événement n'a pas été gardé")
        return found


def _occurring(master: Event, rows: Sequence[Event], key: str) -> Event:
    """L'occurrence ``key`` de la série telle qu'elle est maintenant : son exception, ou ce que sa règle donne à cet
    instant. Une clé que la règle ne donne plus (la série a changé depuis qu'on l'a lue) est refusée — jamais une
    occurrence fabriquée là où la série n'en a pas ; une clé illisible aussi."""
    found = next((r for r in rows if r.original == key), None)
    if found is not None:
        return found
    try:
        at = key_instant(key)
    except ValueError:
        raise AgendaError("cette occurrence ne se lit pas") from None
    if not any(o.key == key for o in occurrences(master, at, at + 1)):
        raise AgendaError(f"cette occurrence de « {master.title} » n'existe plus (la série a changé)")
    return instance(master, key)


def _first_key(master: Event) -> str:
    first = occurrences(master, master.span.start, master.span.start + 1)
    return first[0].key if first else occurrence_key(master.span.start, master.span.all_day)


def _invited(participants: Sequence[Participant], organizer: str) -> tuple[Participant, ...]:
    """Ses participantes : l'organisatrice marquée (sans réponse), une invitée en attente de la sienne ; deux fois la
    même, une fois."""
    out: dict[str, Participant] = {}
    for p in participants:
        who = p.person or p.address.strip().lower() or p.name.strip()
        if not who or who in out:
            continue
        if p.person and p.person == organizer:
            out[who] = replace(p, response="", me=True)
        else:
            out[who] = replace(p, response=p.response or NEEDS, me=False)
    return tuple(out.values())


def _with(event: Event, change: EventChange, organizer: str) -> Event:
    """``event`` avec ce que ``change`` dit (ce qu'il laisse à ``None`` reste tel quel)."""
    out = event
    for name in _SIMPLE:
        value = getattr(change, name)
        if value is not None:
            out = replace(out, **{name: value.strip() if name == "title" else value})
    if change.span is not None:
        if change.span.end < change.span.start:
            raise AgendaError("un événement finit après avoir commencé")
        out = replace(out, span=change.span)
    if change.participants is not None:
        out = replace(out, participants=_invited(change.participants, organizer))
    if change.rule is not None and not out.original:
        rec = out.recurrence or Recurrence()
        out = replace(out, recurrence=replace(rec, rule=change.rule) if change.rule else None)
    if not out.title:
        raise AgendaError("un événement a un titre")
    return replace(out, sequence=event.sequence + 1, updated=0)


def _inherit(row: Event, before: Event, after: Event, key: str) -> Event:
    """Une exception de la série ``before`` devenue ``after`` : elle prend ce qui a changé là où elle avait encore la
    valeur de la série, et sa période suit celle de la série si elle n'avait pas été déplacée."""
    out = replace(row, original=key, id=0)
    for name in _INHERITED:
        if getattr(row, name) == getattr(before, name):
            out = replace(out, **{name: getattr(after, name)})
    if row.span == instance(before, row.original).span:
        out = replace(out, span=instance(after, key).span)
    return out


def _answered(row: Event, person: str, response: str) -> Event:
    if not any(p.person == person for p in row.participants):
        raise AgendaError("cette personne n'est pas invitée")
    return replace(row, participants=tuple(replace(p, response=response) if p.person == person else p
                                           for p in row.participants))


def _copy(row: Event, calendar: str, person: str, response: str) -> Event:
    """La copie d'une ligne de l'organisatrice dans l'agenda d'une invitée : sa réponse à elle, elle marquée parmi les
    participantes ; ni ce que Mika y a mis chez l'organisatrice, ni ce qu'un fournisseur en dirait."""
    organizer = replace(row.organizer, me=False) if row.organizer is not None else None
    return replace(row, calendar=calendar, origin=row.calendar, response=response or NEEDS, organizer=organizer,
                   participants=tuple(replace(p, me=p.person == person) for p in row.participants), added=None,
                   id=0, remote="", etag="", raw="")


__all__ = ["SystemProvider"]
