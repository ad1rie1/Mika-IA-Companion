"""L'agenda (la base ``agenda``, déclarée dans ``models`` : SQLite pour les tests, MariaDB en service — ADR 0101,
0309) : ses comptes et leur synchro, ses agendas, leurs événements.

- **Ceux du système font foi ici** ; ceux d'un fournisseur en sont la copie (``apply`` : ce qu'une synchronisation
  rapporte, avec son curseur ; un lot complet retire ce qu'il ne nomme plus dans la fenêtre, et ce qui la précède
  part ; une ressource redonnée en entier, ``SyncBatch.replaced``, perd les lignes qu'elle n'a plus). Ce que Mika a
  mis dans un agenda branché reste marqué (``added``) quand le fournisseur le redit sans la marque.
- **Une période** (``period``) se lit sur plusieurs agendas : la base ne rend que ce qui la touche (une série, tant
  qu'elle n'a pas fini ; ses exceptions, même déplacées ailleurs), puis ``ports.agenda.expand`` en développe les
  occurrences. Ce que le compte de l'agenda a refusé ne s'y montre pas, sauf si on le demande.
- **« Mika te le rappelle » pour un événement** (``remind``) ne vit qu'ici : une ligne rangée à nouveau (une
  synchronisation, une écriture, la copie d'une invitation) garde le sien ; seul ``remind`` le change.
- **Le nom d'un agenda** (``rename``, lot 6) : celui d'un agenda du système change pour de bon (sa colonne ``name``) ;
  un agenda branché prend un nom à lui (``alias``), qu'une synchronisation ne touche pas — ``Calendar.name`` le rend,
  ``Calendar.provider_name`` garde celui du fournisseur.
- **L'oubli** (``forget``) :
  - d'une adresse (``mail:<adresse>``) : elle part des participantes de chaque événement ; un événement qu'elle
    organisait garde son créneau, vidé de ce qu'elle y avait écrit (``ports.agenda.blanked`` : titre, lieu,
    description, lien, elle-même) — on sait encore qu'on n'y est pas libre. Son empreinte et l'instant de l'oubli
    restent (``forgotten``) : une synchronisation ne la ramène ni parmi les participantes, ni ses mots, dans ce qui a
    été créé avant ;
  - d'une personne (sa clé) : de même dans les événements du système (elle y est désignée par sa clé) ;
  - jamais dans l'agenda d'un compte à elle (le compte de son adresse, son compte du système, un compte à son nom) :
    il est à elle, comme sa boîte ; il part avec son compte (``drop_account``).

Une seule connexion sous SQLite, partagée sous ``_lock`` ; une écriture est une session courte (``_writing``). Chaque
écriture dit ce qu'elle change, une fois validée (``on_change``, ADR 0308 : le sujet ``agenda``, les comptes et les
agendas touchés) — sauf le curseur d'une synchronisation, que rien ne montre.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import tzinfo
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from mika.adapters.agenda.models import (
    ACCOUNT,
    ADDRESS,
    CALENDAR,
    OCCURRENCE,
    PERSON,
    UID,
    WORD,
    AccountRow,
    AttendeeRow,
    CalendarRow,
    EventRow,
    ForgottenRow,
    SyncNoteRow,
    fit,
)
from mika.adapters.changes import Changes, Listener
from mika.adapters.database import Target, as_target
from mika.ports import changes
from mika.ports.agenda import (
    NEEDS,
    AccountState,
    AddedBy,
    AgendaError,
    Alert,
    Calendar,
    Event,
    Occurrence,
    Participant,
    Recurrence,
    Span,
    SyncBatch,
    SyncNote,
    Window,
    address_print,
    alerts_of,
    blanked,
    expand,
    series_end,
    split_calendar_key,
    system_account,
    system_person,
)
from mika.ports.sql import AGENDA, json_values, upsert
from mika.vocab.access import PERSON as PERSON_PREFIX

ACC, CAL, E, A, N = AccountRow, CalendarRow, EventRow, AttendeeRow, SyncNoteRow

#: une erreur gardée, au plus (caractères)
ERROR_MAX = 2000
#: ce qu'un événement perd quand son organisatrice est oubliée (``ports.agenda.blanked``) : ses mots, elle-même
_BLANKED = ("title", "location", "description", "conference", "raw", "organizer_address", "organizer_name",
            "organizer_person")
#: ce qui se lit d'un coup dans une liste ``IN``
CHUNK = 500


def _now_us() -> int:
    return time.time_ns() // 1000


def _chunks(values: Sequence[Any], size: int = CHUNK) -> Iterator[list[Any]]:
    for i in range(0, len(values), size):
        yield list(values[i:i + size])


def _address(value: str) -> str:
    return fit(value.strip().lower(), ADDRESS)


class AgendaStore:
    """Le port ``agenda``."""

    def __init__(self, path: Path | Target, *, now: Callable[[], int] = _now_us) -> None:
        self._now = now
        self._lock = threading.RLock()
        target = as_target(path)
        target.ensure()
        self._engine = target.engine(shared=True)
        AGENDA.create_all(self._engine)
        self._session = sessionmaker(self._engine, expire_on_commit=False)
        #: ce que ses écritures changent, dit une fois validées (ADR 0308)
        self._changes = Changes()

    # ── ses écritures, et ce qu'elles changent (ADR 0308) ──
    @contextmanager
    def _writing(self) -> Iterator[Session]:
        """Une écriture : une session sous le verrou, validée à la sortie ; ce qu'elle a noté (``_changed``) part
        ensuite, rien si elle est annulée."""
        with self._lock, self._changes.writing(), self._session.begin() as s:
            yield s

    def on_change(self, fn: Listener) -> None:
        """Prévenir ``fn`` de chaque écriture validée : les comptes et les agendas touchés. Appelé dans le fil qui a
        écrit."""
        self._changes.listen(fn)

    def _changed(self, calendars: Iterable[str] = (), accounts: Iterable[str] = ()) -> None:
        keys = tuple(sorted({k for k in calendars if k}))
        owners = {split_calendar_key(k)[0] for k in keys} | {a for a in accounts if a}
        self._changes.note(changes.Change(changes.AGENDA, accounts=tuple(sorted(owners - {""})), keys=keys))

    # ── ses comptes ──
    def accounts(self) -> list[AccountState]:
        with self._lock, self._session() as s:
            return [_account(r) for r in s.scalars(select(ACC).order_by(ACC.key))]

    def account(self, key: str) -> AccountState | None:
        with self._lock, self._session() as s:
            row = s.get(ACC, fit(key, ACCOUNT))
            return _account(row) if row is not None else None

    def keep_account(self, key: str, kind: str, *, owner: str = "", address: str = "",
                     enabled: bool = True) -> AccountState:
        values = {"kind": fit(kind, WORD), "owner": fit(owner, PERSON), "address": _address(address),
                  "enabled": bool(enabled)}
        with self._writing() as s:
            row = s.get(ACC, fit(key, ACCOUNT))
            if row is None:
                row = ACC(key=fit(key, ACCOUNT), created=self._now(), **values)
                s.add(row)
                self._changed(accounts=(row.key,))
            elif any(getattr(row, k) != v for k, v in values.items()):
                for k, v in values.items():
                    setattr(row, k, v)
                self._changed(accounts=(row.key,))
            return _account(row)

    def drop_account(self, key: str) -> int:
        k = fit(key, ACCOUNT)
        with self._writing() as s:
            cals = s.execute(select(CAL.id, CAL.key).where(CAL.account == k)).all()
            n = self._drop_calendars(s, [int(c.id) for c in cals])
            n += int(s.execute(delete(ACC).where(ACC.key == k)).rowcount or 0)
            s.execute(delete(N).where(N.account == k))  # son historique part avec lui
            if n:
                self._changed(calendars=[c.key for c in cals], accounts=(k,))
            return n

    def synced(self, key: str, *, error: str = "", at: int | None = None) -> AccountState:
        at = self._now() if at is None else at
        with self._writing() as s:
            row = s.get(ACC, fit(key, ACCOUNT))
            if row is None:
                raise AgendaError(f"compte d'agenda inconnu : {key[:60]}")
            row.tried_at = at
            if error:
                row.failures = int(row.failures or 0) + 1
                row.error = error[:ERROR_MAX]
            else:
                row.synced_at, row.failures, row.error = at, 0, ""
            self._changed(accounts=(row.key,))
            return _account(row)

    def failing(self) -> list[str]:
        """Les comptes actifs dont la dernière synchronisation a échoué (la santé les nomme)."""
        with self._lock, self._session() as s:
            return list(s.scalars(select(ACC.key).where(ACC.failures > 0, ACC.enabled.is_(True)).order_by(ACC.key)))

    # ── l'historique de sa synchro (lot 5) ──
    def note_sync(self, note: SyncNote, *, keep_us: int = 0) -> None:
        """Une ligne de plus à l'historique de son compte ; ce qui est plus ancien que ``keep_us`` part. Rien ne
        s'en montre en direct : la fiche d'un agenda le relit quand on l'ouvre."""
        at = note.at or self._now()
        with self._writing() as s:
            s.add(N(account=fit(note.account, ACCOUNT), calendar=fit(note.calendar, CALENDAR), at=at,
                    what=fit(note.what, WORD), changed=max(0, int(note.changed)), detail=note.detail[:ERROR_MAX]))
            if keep_us > 0:
                s.execute(delete(N).where(N.at < at - keep_us))

    def _notes_of(self, account: str, calendar: str) -> Any:
        where = [N.account == fit(account, ACCOUNT)]
        if calendar:
            where.append(N.calendar.in_((fit(calendar, CALENDAR), "")))
        return where

    def sync_notes(self, account: str, calendar: str = "", *, limit: int = 50, offset: int = 0) -> list[SyncNote]:
        with self._lock, self._session() as s:
            rows = s.scalars(select(N).where(*self._notes_of(account, calendar))
                             .order_by(N.at.desc(), N.id.desc()).limit(max(1, limit)).offset(max(0, offset)))
            return [SyncNote(r.account, r.calendar, int(r.at or 0), r.what, int(r.changed or 0), r.detail, int(r.id))
                    for r in rows]

    def sync_notes_count(self, account: str, calendar: str = "") -> int:
        with self._lock, self._session() as s:
            return int(s.scalar(select(func.count()).select_from(N).where(*self._notes_of(account, calendar))) or 0)

    # ── ses agendas ──
    def calendars(self, account: str | None = None) -> list[Calendar]:
        with self._lock, self._session() as s:
            q = select(CAL)
            if account is not None:
                q = q.where(CAL.account == fit(account, ACCOUNT))
            return [_calendar(r) for r in s.scalars(q.order_by(CAL.account, CAL.main.desc(), CAL.name, CAL.key))]

    def calendar(self, key: str) -> Calendar | None:
        with self._lock, self._session() as s:
            row = s.scalars(select(CAL).where(CAL.key == fit(key, CALENDAR))).first()
            return _calendar(row) if row is not None else None

    def keep_calendars(self, account: str, found: Sequence[Calendar]) -> list[Calendar]:
        acc = fit(account, ACCOUNT)
        if any(split_calendar_key(c.key)[0] != account for c in found):
            raise AgendaError("un agenda listé n'est pas de ce compte")
        with self._writing() as s:
            existing = {r.key: r for r in s.scalars(select(CAL).where(CAL.account == acc))}
            touched = [c.key for c in found if self._put_calendar(s, c, existing.get(c.key))]
            gone = [r for key, r in existing.items() if key not in {c.key for c in found}]
            self._drop_calendars(s, [int(r.id) for r in gone])
            if touched or gone:
                self._changed(calendars=[*touched, *(r.key for r in gone)], accounts=(acc,))
            s.flush()
            rows = s.scalars(select(CAL).where(CAL.account == acc).order_by(CAL.main.desc(), CAL.name, CAL.key))
            return [_calendar(r) for r in rows]

    def add_calendar(self, calendar: Calendar) -> Calendar:
        account, _local = split_calendar_key(calendar.key)
        if account != calendar.account:
            raise AgendaError("un agenda est sous son compte")
        with self._writing() as s:
            row = s.scalars(select(CAL).where(CAL.key == fit(calendar.key, CALENDAR))).first()
            if self._put_calendar(s, calendar, row):
                self._changed(calendars=(calendar.key,))
            s.flush()
            return _calendar(s.scalars(select(CAL).where(CAL.key == fit(calendar.key, CALENDAR))).one())

    def _put_calendar(self, s: Session, c: Calendar, row: CalendarRow | None) -> bool:
        """Range ce que le fournisseur dit d'un agenda (jamais son curseur : c'est le nôtre) ; vrai s'il change."""
        # le nom du fournisseur (une ligne relue d'ici porte le nom donné dans Mika : le sien est à part)
        values = {"account": fit(c.account, ACCOUNT), "remote": c.remote, "name": c.provider_name or c.name,
                  "color": c.color, "writable": bool(c.writable), "zone": c.zone, "main": bool(c.primary),
                  "selected": bool(c.selected), "reminders": _alerts_json(c.reminders)}
        if row is None:
            s.add(CAL(key=fit(c.key, CALENDAR), created=self._now(), cursor=c.cursor, synced_at=c.synced_at,
                      **values))
            return True
        if all(getattr(row, k) == v for k, v in values.items()):
            return False
        for k, v in values.items():
            setattr(row, k, v)
        return True

    def rename(self, key: str, name: str) -> bool:
        name = name.strip()
        system = bool(system_person(split_calendar_key(key)[0]))
        if system and not name:
            raise AgendaError("un agenda a un nom")
        with self._writing() as s:
            row = s.scalars(select(CAL).where(CAL.key == fit(key, CALENDAR))).first()
            if row is None:
                return False
            field = "name" if system else "alias"
            value = "" if not system and name == row.name else name
            if getattr(row, field) != value:
                setattr(row, field, value)
                self._changed(calendars=(key,))
            return True

    def drop_calendar(self, key: str) -> int:
        with self._writing() as s:
            ids = list(s.scalars(select(CAL.id).where(CAL.key == fit(key, CALENDAR))))
            n = self._drop_calendars(s, [int(i) for i in ids])
            if n:
                self._changed(calendars=(key,))
            return n

    def clear_calendar(self, key: str) -> int:
        """Un agenda qu'on ne suit plus : sa copie part (ses événements, son curseur) ; lui reste, listé."""
        with self._writing() as s:
            row = s.scalars(select(CAL).where(CAL.key == fit(key, CALENDAR))).first()
            if row is None:
                return 0
            n = self._drop_events(s, list(s.scalars(select(E.id).where(E.calendar == row.id))))
            row.cursor, row.synced_at = "", 0
            if n:
                self._changed(calendars=(row.key,))
            return n

    def set_cursor(self, key: str, cursor: str, *, at: int | None = None) -> None:
        with self._writing() as s:
            row = s.scalars(select(CAL).where(CAL.key == fit(key, CALENDAR))).first()
            if row is not None:
                row.cursor, row.synced_at = cursor, self._now() if at is None else at

    def _drop_calendars(self, s: Session, ids: Sequence[int]) -> int:
        if not ids:
            return 0
        n = 0
        for chunk in _chunks(sorted(ids)):
            events = list(s.scalars(select(E.id).where(E.calendar.in_(chunk))))
            n += self._drop_events(s, events)
            n += int(s.execute(delete(CAL).where(CAL.id.in_(chunk))).rowcount or 0)
        return n

    @staticmethod
    def _drop_events(s: Session, ids: Sequence[int]) -> int:
        n = 0
        for chunk in _chunks(sorted(ids)):
            s.execute(delete(A).where(A.event.in_(chunk)))
            n += int(s.execute(delete(E).where(E.id.in_(chunk))).rowcount or 0)
        return n

    # ── ses événements ──
    def event(self, event_id: int) -> Event | None:
        with self._lock, self._session() as s:
            row = s.get(E, int(event_id))
            return self._events(s, [row])[0] if row is not None else None

    def find(self, calendar: str, uid: str, original: str = "") -> Event | None:
        with self._lock, self._session() as s:
            cid = self._cid(s, calendar)
            if cid is None:
                return None
            row = s.scalars(select(E).where(E.calendar == cid, E.uid == fit(uid, UID),
                                            E.original == fit(original, OCCURRENCE))).first()
            return self._events(s, [row])[0] if row is not None else None

    def series(self, calendar: str, uid: str) -> list[Event]:
        with self._lock, self._session() as s:
            cid = self._cid(s, calendar)
            if cid is None:
                return []
            rows = list(s.scalars(select(E).where(E.calendar == cid, E.uid == fit(uid, UID)).order_by(E.original)))
            return self._events(s, rows)

    def copies(self, origin: str, uid: str) -> list[Event]:
        with self._lock, self._session() as s:
            oid = self._cid(s, origin)
            if oid is None:
                return []
            rows = list(s.scalars(select(E).where(E.origin == oid, E.uid == fit(uid, UID))
                                  .order_by(E.calendar, E.original)))
            return self._events(s, rows)

    def save(self, events: Sequence[Event] = (), *,
             removed: Sequence[tuple[str, str, str | None]] = ()) -> list[Event]:
        now = self._now()
        with self._writing() as s:
            touched: set[str] = set()
            for calendar, uid, original in removed:
                cid = self._cid(s, calendar)
                if cid is None:
                    continue
                q = select(E.id).where(E.calendar == cid, E.uid == fit(uid, UID))
                if original is not None:
                    q = q.where(E.original == fit(original, OCCURRENCE))
                if self._drop_events(s, list(s.scalars(q))):
                    touched.add(calendar)
            rows = [self._put_event(s, e, now) for e in events]
            touched |= {e.calendar for e in events}
            if touched:
                self._changed(calendars=touched)
            s.flush()
            return self._events(s, rows)

    def _put_event(self, s: Session, e: Event, now: int, *, created: int | None = None) -> EventRow:
        cid = self._cid(s, e.calendar)
        if cid is None:
            raise AgendaError(f"agenda inconnu : {e.calendar[:80]}")
        oid = (self._cid(s, e.origin) or 0) if e.origin else 0
        row = s.scalars(select(E).where(E.calendar == cid, E.uid == fit(e.uid, UID),
                                        E.original == fit(e.original, OCCURRENCE))).first()
        values = _values(e, cid, oid)
        values["created"] = created if created is not None else (e.created or (row.created if row else 0) or now)
        values["updated"] = e.updated or now
        if row is None:
            row = E(**values)
            s.add(row)
            s.flush()
        else:
            for k, v in values.items():
                setattr(row, k, v)
            s.execute(delete(A).where(A.event == row.id))
        for i, p in enumerate(e.participants):
            s.add(A(event=row.id, position=i, address=_address(p.address), name=p.name, person=fit(p.person, PERSON),
                    response=fit(p.response, WORD), optional=p.optional, me=p.me))
        return row

    def apply(self, calendar: str, batch: SyncBatch, *, window: Window | None = None) -> int:
        now = self._now()
        with self._writing() as s:
            cal = s.scalars(select(CAL).where(CAL.key == fit(calendar, CALENDAR))).first()
            if cal is None:
                raise AgendaError(f"agenda inconnu : {calendar[:80]}")
            acc = s.get(ACC, cal.account)
            own = acc.address if acc is not None else ""
            prints = dict(s.execute(select(ForgottenRow.digest, ForgottenRow.until)).all())
            n = 0
            listed: set[tuple[str, str]] = set()
            for e in batch.events:
                e = replace(e, calendar=calendar, id=0)
                found = s.execute(select(E.created, E.added_by, E.added_ref, E.added_at).where(
                    E.calendar == cal.id, E.uid == fit(e.uid, UID), E.original == fit(e.original, OCCURRENCE))).first()
                created = e.created or (found.created if found is not None else 0) or now
                if e.added is None and found is not None and found.added_by:  # ce que Mika y a mis reste marqué
                    e = replace(e, added=AddedBy(found.added_by, found.added_ref, found.added_at))
                self._put_event(s, _scrubbed(replace(e, created=created), prints, own), now, created=created)
                listed.add((fit(e.uid, UID), fit(e.original, OCCURRENCE)))
                n += 1
            for uid, original in batch.removed:
                q = select(E.id).where(E.calendar == cal.id, E.uid == fit(uid, UID))
                if original:
                    q = q.where(E.original == fit(original, OCCURRENCE))
                n += self._drop_events(s, list(s.scalars(q)))
            # ce que le fournisseur redonne en entier (une ressource CalDAV) : ses lignes que le lot ne nomme pas partent
            for chunk in _chunks(sorted({fit(r, UID) for r in batch.replaced if r})):
                stale = s.execute(select(E.id, E.uid, E.original).where(E.calendar == cal.id, E.remote.in_(chunk)))
                n += self._drop_events(s, [int(r.id) for r in stale if (r.uid, r.original) not in listed])
            if window is not None:
                # ce qui a fini avant la fenêtre part ; un lot complet retire ce qu'il ne nomme pas dans la fenêtre
                gone = list(s.scalars(select(E.id).where(E.calendar == cal.id, E.last_end <= window.start)))
                if batch.complete:
                    inside = s.execute(select(E.id, E.uid, E.original).where(
                        E.calendar == cal.id, E.last_end > window.start, E.start_at < window.end)).all()
                    gone += [int(r.id) for r in inside if (r.uid, r.original) not in listed]
                n += self._drop_events(s, gone)
            cal.cursor, cal.synced_at = batch.cursor, now
            if n:
                self._changed(calendars=(calendar,))
            return n

    def period(self, calendars: Collection[str], start: int, end: int, *, declined: bool = False,
               zone: tzinfo | None = None) -> list[Occurrence]:
        with self._lock, self._session() as s:
            ids = list(self._ids(s, calendars).values())
            rows: dict[int, EventRow] = {}
            for chunk in _chunks(ids):
                for r in s.scalars(select(E).where(E.calendar.in_(chunk), E.last_end >= start, E.start_at < end)):
                    rows[r.id] = r
            # les exceptions des séries rendues, même déplacées hors de la période : elles y retirent une occurrence
            series = {(r.calendar, r.uid) for r in rows.values() if not r.original and (r.rule or r.rdates)}
            for chunk in _chunks(sorted(series)):
                cids, uids = sorted({c for c, _ in chunk}), sorted({u for _, u in chunk})
                for r in s.scalars(select(E).where(E.calendar.in_(cids), E.uid.in_(uids), E.original != "")):
                    if (r.calendar, r.uid) in series:
                        rows[r.id] = r
            events = self._events(s, list(rows.values()))
        return expand(events, start, end, declined=declined, zone=zone)

    def remind(self, calendar: str, uid: str, original: str, value: str) -> bool:
        with self._writing() as s:
            cid = self._cid(s, calendar)
            row = s.scalars(select(E).where(E.calendar == cid, E.uid == fit(uid, UID),
                                            E.original == fit(original, OCCURRENCE))).first() if cid else None
            if row is None:
                return False
            value = fit(value, WORD)
            if row.remind != value:
                row.remind = value
                self._changed(calendars=(calendar,))
            return True

    def invitations(self, calendars: Collection[str]) -> list[Event]:
        now = self._now()
        with self._lock, self._session() as s:
            ids = list(self._ids(s, calendars).values())
            rows: list[EventRow] = []
            for chunk in _chunks(ids):
                rows += s.scalars(select(E).where(E.calendar.in_(chunk), E.response == NEEDS, E.last_end > now))
            rows.sort(key=lambda r: (r.start_at, r.id))
            return self._events(s, rows)

    def event_counts(self, calendars: Collection[str]) -> dict[str, int]:
        with self._lock, self._session() as s:
            ids = self._ids(s, calendars)
            keys = {v: k for k, v in ids.items()}
            out = {k: 0 for k in ids}
            for chunk in _chunks(sorted(keys)):
                for cid, n in s.execute(select(E.calendar, func.count()).where(E.calendar.in_(chunk))
                                        .group_by(E.calendar)):
                    out[keys[int(cid)]] = int(n)
            return out

    # ── l'oubli ──
    async def forget(self, subject: str) -> int:
        return await asyncio.to_thread(self.forget_now, subject)

    def forget_now(self, subject: str) -> int:
        """``forget``, dans le fil qui l'appelle. ``mail:<adresse>`` : une adresse (et la personne de cette clé, s'il
        y en a une) ; une autre clé : une personne de l'identité (l'agenda du système la désigne par elle)."""
        subject = (subject or "").strip()
        if not subject:
            return 0
        address = _address(subject[5:]) if subject.startswith("mail:") else ""
        person = fit(subject, PERSON)
        with self._writing() as s:
            own = self._own_calendars(s, address, subject)
            outside = [E.calendar.notin_(own)] if own else []
            who = [A.person == person, *([A.address == address] if address else [])]
            n = 0
            attendees = s.execute(select(A.id, A.event).join(E, E.id == A.event).where(or_(*who), *outside)).all()
            touched = {int(r.event) for r in attendees}
            for chunk in _chunks(sorted(int(r.id) for r in attendees)):
                n += int(s.execute(delete(A).where(A.id.in_(chunk))).rowcount or 0)
            organized = [E.organizer_person == person, *([E.organizer_address == address] if address else [])]
            for row in s.scalars(select(E).where(or_(*organized), *outside)):  # ses mots partent, le créneau reste
                for k in _BLANKED:
                    setattr(row, k, "")
                row.forgotten = True
                touched.add(int(row.id))
                n += 1
            if address:  # même jamais vue : ce qui la ramènerait, créé avant l'oubli, ne la ramène pas
                upsert(s, ForgottenRow, {"digest": address_print(address), "until": self._now()}, keys=("digest",))
            if n:
                cals = sorted({int(c) for c in s.scalars(select(E.calendar).where(E.id.in_(sorted(touched))))})
                self._changed(calendars=self._keys(s, cals).values())
        return n

    def _own_calendars(self, s: Session, address: str, person: str) -> list[int]:
        """Les agendas des comptes que ce sujet tient lui-même : celui de son adresse, son compte du système, un
        compte à son nom — un oubli ne les vide pas."""
        mine = [ACC.owner == fit(PERSON_PREFIX + person, PERSON), *([ACC.address == address] if address else [])]
        accounts = {fit(system_account(person), ACCOUNT), *s.scalars(select(ACC.key).where(or_(*mine)))}
        return sorted({int(i) for i in s.scalars(select(CAL.id).where(CAL.account.in_(sorted(accounts))))})

    # ── lire les lignes ──
    @staticmethod
    def _cid(s: Session, key: str) -> int | None:
        found = s.scalars(select(CAL.id).where(CAL.key == fit(key, CALENDAR))).first()
        return int(found) if found is not None else None

    @staticmethod
    def _ids(s: Session, keys: Collection[str]) -> dict[str, int]:
        wanted = sorted({fit(k, CALENDAR) for k in keys})
        out: dict[str, int] = {}
        for chunk in _chunks(wanted):
            out.update({k: int(i) for k, i in s.execute(select(CAL.key, CAL.id).where(CAL.key.in_(chunk))).all()})
        return out

    @staticmethod
    def _keys(s: Session, ids: Collection[int]) -> dict[int, str]:
        out: dict[int, str] = {}
        for chunk in _chunks(sorted({int(i) for i in ids if i})):
            out.update({int(i): k for i, k in s.execute(select(CAL.id, CAL.key).where(CAL.id.in_(chunk))).all()})
        return out

    def _events(self, s: Session, rows: Sequence[EventRow]) -> list[Event]:
        if not rows:
            return []
        keys = self._keys(s, {r.calendar for r in rows} | {r.origin for r in rows})
        people: dict[int, list[AttendeeRow]] = {}
        for chunk in _chunks(sorted({int(r.id) for r in rows})):
            for a in s.scalars(select(A).where(A.event.in_(chunk)).order_by(A.event, A.position, A.id)):
                people.setdefault(int(a.event), []).append(a)
        return [_event(r, keys.get(r.calendar, ""), keys.get(r.origin, "") if r.origin else "", people.get(r.id, []))
                for r in rows]

    def close(self) -> None:
        with self._lock:
            self._engine.dispose()


# ── des lignes aux valeurs, et retour ────────────────────────────────────


def _values(e: Event, calendar: int, origin: int) -> dict[str, Any]:
    rec = e.recurrence if e.recurring else None
    org = e.organizer or Participant()
    added = e.added
    return {
        "calendar": calendar, "uid": fit(e.uid, UID), "original": fit(e.original, OCCURRENCE), "origin": origin,
        "title": e.title, "location": e.location, "description": e.description, "conference": e.conference,
        "start_at": e.span.start, "end_at": e.span.end, "all_day": e.span.all_day, "zone": e.span.zone,
        "last_end": series_end(e), "rule": rec.rule if rec else "",
        "exdates": json.dumps(list(rec.exdates)) if rec and rec.exdates else "",
        "rdates": json.dumps(list(rec.rdates)) if rec and rec.rdates else "",
        "status": fit(e.status, WORD), "busy": e.busy, "private": e.private, "response": fit(e.response, WORD),
        "organizer_address": _address(org.address), "organizer_name": org.name,
        "organizer_person": fit(org.person, PERSON),
        "reminders": _alerts_json(e.reminders), "reminders_default": bool(e.reminders_default),
        "added_by": fit(added.by, WORD) if added else "", "added_ref": added.ref if added else "",
        "added_at": added.at if added else 0,
        "remote": fit(e.remote, UID), "etag": e.etag, "raw": e.raw, "sequence": e.sequence,
        "forgotten": e.forgotten,
    }


def _event(r: EventRow, calendar: str, origin: str, attendees: Sequence[AttendeeRow]) -> Event:
    rec = Recurrence(r.rule, tuple(str(x) for x in json_values(r.exdates)),
                     tuple(str(x) for x in json_values(r.rdates))) if r.rule or r.rdates else None
    organizer = Participant(r.organizer_address, r.organizer_name, r.organizer_person) \
        if r.organizer_address or r.organizer_name or r.organizer_person else None
    return Event(
        calendar=calendar, uid=r.uid, original=r.original, span=Span(r.start_at, r.end_at, r.zone, bool(r.all_day)),
        title=r.title, location=r.location, description=r.description, conference=r.conference, recurrence=rec,
        status=r.status, busy=bool(r.busy), private=bool(r.private), organizer=organizer,
        participants=tuple(Participant(a.address, a.name, a.person, a.response, bool(a.optional), bool(a.me))
                           for a in attendees),
        response=r.response, reminders=_alerts(r.reminders), reminders_default=bool(r.reminders_default),
        added=AddedBy(r.added_by, r.added_ref, r.added_at) if r.added_by else None, origin=origin, remote=r.remote,
        etag=r.etag, sequence=int(r.sequence or 0), created=int(r.created or 0), updated=int(r.updated or 0),
        forgotten=bool(r.forgotten), raw=r.raw, id=int(r.id), remind=r.remind or "")


def _account(r: AccountRow) -> AccountState:
    return AccountState(r.key, r.kind, r.owner, r.address, int(r.synced_at or 0), int(r.tried_at or 0),
                        int(r.failures or 0), r.error, bool(r.enabled))


def _calendar(r: CalendarRow) -> Calendar:
    alias = r.alias or ""
    return Calendar(r.key, r.account, r.remote, alias or r.name, r.color, bool(r.writable), r.zone, bool(r.main),
                    bool(r.selected), r.cursor, int(r.synced_at or 0), _alerts(r.reminders or ""),
                    r.name if alias else "")


def _alerts_json(alerts: Sequence[Alert]) -> str:
    return json.dumps([[a.minutes, a.method] for a in alerts]) if alerts else ""


def _alerts(text: str) -> tuple[Alert, ...]:
    """Des rappels du fournisseur gardés en JSON (``[[minutes, méthode], …]``) ; ce qui ne se lit pas est sauté."""
    out = []
    for x in json_values(text):
        if isinstance(x, list) and len(x) == 2 and isinstance(x[0], int) and isinstance(x[1], str):
            out.append(Alert(x[0], x[1]))
    return alerts_of(out)


def _scrubbed(e: Event, prints: dict[str, int], own: str) -> Event:
    """Ce qu'une synchronisation rapporte, sans ce qu'un oubli a retiré : une participante oubliée (sauf le compte
    lui-même), les mots d'une organisatrice oubliée — dans ce qui a été créé avant l'oubli."""

    def forgotten(address: str) -> bool:
        address = address.strip().lower()
        until = prints.get(address_print(address)) if address and address != own else None
        return until is not None and e.created <= until

    org = e.organizer
    if org is not None and org.address and forgotten(org.address):
        e = blanked(e)
    kept = tuple(p for p in e.participants if p.me or not p.address or not forgotten(p.address))
    return replace(e, participants=kept) if len(kept) != len(e.participants) else e


__all__ = ["AgendaStore"]
