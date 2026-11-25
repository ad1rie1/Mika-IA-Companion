"""Ce que lisent les pages « Agendas » de la console (ADR 0309, lot 5) : Échanges › Agendas (``tabs.py``), la
fiche d'un agenda (``subject.py``), l'onglet « Agendas » de la fiche d'une personne (``person.py``) et
la file « À valider » (``app/handmade/approval_sources.py``).

Chaque agenda est lu tel que la console le montre (``plugins/agenda/inspect/views.py::Shown`` : à qui, sa sorte, sa synchro),
avec sa couleur — celle que son propriétaire a choisie, sinon la plus proche de celle de son fournisseur, sinon une de
la palette (ses huit couleurs ; le rose est à elle). Une période devient une liste d'éléments (``Item``) : les
occurrences de la base (un événement privé d'une autre personne, « Occupé »), ce qu'elle propose d'ajouter et qui
attend un accord (hachuré, tiré de sa proposition), et son agenda à elle (sa mémoire, ``app/domains/agenda/her.py``) pour les
personnes choisies. Ce qu'elle a proposé d'écrire se relit au journal (la proposition, ses arguments) ; rien n'est
recopié.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from mika.app.domains.agenda.her import HerDate, her_agenda, title_of
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.handmade import Look
from mika.contracts import runtime as rt
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI
from mika.kernel.clock import DAY
from mika.plugins.agenda import CREATE, WAITING, AgendaState, Written
from mika.plugins.agenda.inspect.views import (
    HER,
    YOURS,
    Shown,
    is_owner,
    occurrences_of,
    shown_calendars,
)
from mika.plugins.agenda.inspect.views import (
    title_of as event_title,
)
from mika.ports.agenda import BY_HER, NEEDS, Occurrence, day_of
from mika.runtime.boundary import Failed, call
from mika.vocab.people import is_identifiable

#: la palette des agendas (``adapters/agenda/config.py::COLORS``) et ses teintes claires, pour rapprocher la couleur
#: qu'un fournisseur donne ; le rose est à elle
PALETTE: Mapping[str, tuple[int, int, int]] = {
    "indigo": (0x4F, 0x46, 0xE5), "bleu": (0x1F, 0x6F, 0xD0), "sarcelle": (0x0F, 0x8B, 0x80),
    "vert": (0x1E, 0x9A, 0x4B), "ambre": (0xC0, 0x84, 0x06), "orange": (0xE2, 0x6A, 0x1B),
    "violet": (0x8B, 0x5C, 0xF6), "ardoise": (0x66, 0x74, 0x8A)}
ROSE = "rose"


def _rgb(text: str) -> tuple[int, int, int] | None:
    text = text.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def color_of(chosen: str, provider: str, index: int) -> str:
    """La couleur d'un agenda dans la console : celle que son propriétaire a choisie ; sinon la plus proche de celle de
    son fournisseur ; sinon une de la palette, à son rang."""
    if chosen in PALETTE:
        return chosen
    rgb = _rgb(provider) if provider else None
    if rgb is not None:
        return min(PALETTE, key=lambda k: sum((a - b) ** 2 for a, b in zip(PALETTE[k], rgb, strict=True)))
    names = list(PALETTE)
    return names[index % len(names)]


@dataclass(slots=True)
class Read:
    """Ce qu'une page des agendas lit, une fois par rendu."""

    ui: UI
    look: Look
    state: AgendaState | None
    calendars: list[Shown]
    colors: dict[str, str]
    #: « L'agenda de Mika », son nom tiré de sa persona
    her_title: str = ""
    #: le nom que chaque compte branché porte dans les réglages (« Lumen (Outlook pro) »), par sa clé
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def frame(self) -> Any:
        return self.look.frame

    @property
    def ports(self) -> Mapping[str, Any]:
        return self.ui.kernel.ports

    @property
    def now(self) -> int:
        return self.look.now

    def calendar(self, key: str) -> Shown | None:
        return next((c for c in self.calendars if c.key == key), None)

    def whose(self, who: str) -> str:
        """À qui, en mots : « toi », elle par son nom, une personne par son nom."""
        if who == YOURS:
            return "toi"
        if who == HER:
            return self.ui.her_name()
        return self.look.name(who)

    def short(self, who: str) -> str:
        """À qui, court (une puce, un titre de la légende) : « Toi », son nom à elle, le prénom d'une personne."""
        if who == YOURS:
            return "Toi"
        if who == HER:
            return self.ui.her_name()
        name = self.look.name(who)
        return name.split()[0] if name.strip() else who

    def who_of_person(self, person: str) -> str:
        """La clé d'une personne dans « Les agendas de » : ``toi`` pour une de ses propriétaires."""
        person = self.look.person_of(person) or person
        return YOURS if is_owner(self.frame, person) else person


def read(ui: UI) -> Read:
    look = Look.of(ui, DAY)
    try:
        state: AgendaState | None = look.frame.state("agenda")
    except KeyError:
        state = None
    calendars = shown_calendars(ui.kernel.ports, look.frame)
    settings = ui.deps.settings
    chosen: dict[str, str] = {}
    labels: dict[str, str] = {}
    if settings is not None:
        try:
            cfg = settings.of(AgendaSettings).agenda()
            labels = {key: account.label for key, account in cfg.accounts.items() if account.label}
            for key, account in cfg.accounts.items():
                for local, setting in account.calendars.items():
                    if setting.color:
                        chosen[f"{key}~{local}"] = setting.color
        except (AttributeError, ValueError):
            chosen = {}
    colors = {c.key: color_of(chosen.get(c.key, ""), c.cal.color, i) for i, c in enumerate(calendars)}
    title = call(title_of, ui.kernel, label="son agenda : son nom")
    return Read(ui, look, state, calendars, colors, ui.her_name() if isinstance(title, Failed) else str(title), labels)


def her_title(ui: UI) -> str:
    """« L'agenda de Mika », son nom tiré de sa persona."""
    return title_of(ui.kernel)


# ── ce qu'elle a proposé d'écrire, relu au journal ──


def proposal_args(ui: UI, proposals: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Les arguments de ces propositions (``effect.proposed``), relus au journal par leur numéro."""
    wanted = sorted({int(p) for p in proposals if p})
    if not wanted:
        return {}
    got = call(ui.kernel.mind.store.get_events, wanted, label="propositions d'agenda")
    out: dict[int, dict[str, Any]] = {}
    for e in [] if isinstance(got, Failed) else got:
        try:
            data = json.loads(e.data) if isinstance(e.data, str) else dict(e.data)
            out[int(e.seq)] = rt.proposal_args(str(data.get("args_json") or "{}"))
        except (TypeError, ValueError):
            continue
    return out


def conversation_of(ui: UI, ref: str) -> str:
    """La conversation d'une référence (``chat:<adresse>[:<message>]``, ou l'adresse d'une tâche) : la fiche de la
    personne, onglet Échanges ; vide si elle ne désigne personne."""
    handle = ref.split(":")[1] if ref.startswith("chat:") else ref
    person = ui.names.person_of(handle) if handle else ""
    return subject_url("person", person, "echanges") if person and is_identifiable(person) else ""


# ── une période, en éléments ──


@dataclass(slots=True)
class Item:
    """Un élément d'une période : une occurrence de la base (``occurrence``), ce qu'elle propose d'ajouter
    (``write``), ou une date de son agenda à elle (``her``) ; sa clé dans l'adresse (``?ev=``), son titre, son agenda,
    sa couleur, à qui, quand (µs, et ses jours locaux), ses marques."""

    key: str
    title: str
    calendar: str
    calendar_name: str
    color: str
    who: str
    start: int
    end: int
    all_day: bool
    first: date
    last: date
    location: str = ""
    invitation: bool = False
    proposed: bool = False
    private: bool = False
    hers: bool = False
    by_her: bool = False
    occurrence: Occurrence | None = None
    write: Written | None = None
    args: dict[str, Any] = field(default_factory=dict)
    date: HerDate | None = None

    @property
    def marked(self) -> bool:
        return self.by_her or self.proposed


def _days(r: Read, start: int, end: int, all_day: bool) -> tuple[date, date]:
    if all_day:
        first = date.fromisoformat(day_of(start))
        last = date.fromisoformat(day_of(max(start, end - DAY)))
        return first, last
    a, b = r.frame.local(start), r.frame.local(max(start, end - 1))
    return a.date(), b.date()


def occurrence_key(o: Occurrence) -> str:
    """La clé d'une occurrence dans l'adresse (``?ev=``) : sa ligne dans la base et sa clé dans une série."""
    return f"{o.event.id}.{o.key}" if o.key else str(o.event.id)


def items(r: Read, picked: set[str], hidden: set[str], start: int, end: int) -> list[Item]:
    """Les éléments de [start, end[ pour les personnes choisies (``picked`` vide : tout le monde ; ``mika`` : son agenda
    à elle) : les occurrences de leurs agendas (sans ceux qu'on ne montre pas : ``hidden``, ou masqués par leur
    propriétaire), ce qu'elle propose d'y ajouter, et ce que son agenda retient pour elles."""
    shown = [c for c in r.calendars if (not picked or c.who in picked) and c.followed]
    out: list[Item] = []
    for c, o in occurrences_of(r.ports, r.frame, [c for c in shown if c.key not in hidden], start, end):
        e = o.event
        first, last = _days(r, o.span.start, o.span.end, o.span.all_day)
        out.append(Item(key=occurrence_key(o), title=event_title(e), calendar=c.key, calendar_name=c.name,
                        color=r.colors.get(c.key, "ardoise"), who=c.who, start=o.span.start, end=o.span.end,
                        all_day=o.span.all_day, first=first, last=last, location=e.location,
                        invitation=e.response == NEEDS, private=e.private and not e.title,
                        by_her=e.added is not None and e.added.by == BY_HER, occurrence=o))
    out += proposed_items(r, [c for c in shown if c.key not in hidden], start, end)
    if HER not in hidden:
        out += her_items(r, picked, start, end)
    out.sort(key=lambda x: (x.first, not x.all_day, x.start, x.title.casefold()))
    return out


def proposed_items(r: Read, calendars: Sequence[Shown], start: int, end: int) -> list[Item]:
    """Ce qu'elle propose d'ajouter à ces agendas et qui attend un accord : hachuré dans la grille, tant qu'on n'en a
    pas décidé (refusé, il disparaît)."""
    if r.state is None:
        return []
    by_key = {c.key: c for c in calendars}
    waiting = [w for w in r.state.writes.values() if w.status == WAITING and w.op == CREATE and w.calendar in by_key]
    args = proposal_args(r.ui, [w.proposal for w in waiting])
    out = []
    for w in waiting:
        a = args.get(w.proposal) or {}
        draft = a.get("draft") or {}
        span = draft.get("span") or {}
        s, e = int(span.get("start") or 0), int(span.get("end") or 0)
        if not s or e <= start or s >= end:
            continue
        all_day = bool(span.get("all_day"))
        first, last = _days(r, s, max(e, s + 1), all_day)
        c = by_key[w.calendar]
        out.append(Item(key=f"p{w.proposal}", title=str(draft.get("title") or "(sans titre)"), calendar=c.key,
                        calendar_name=c.name, color=r.colors.get(c.key, "ardoise"), who=c.who, start=s, end=e,
                        all_day=all_day, first=first, last=last, location=str(draft.get("location") or ""),
                        proposed=True, write=w, args=a))
    return out


def her_items(r: Read, picked: set[str], start: int, end: int) -> list[Item]:
    """Son agenda à elle sur la période : tout si l'on a choisi tout le monde ou elle, sinon ce qu'il retient pour les
    personnes choisies."""
    got = call(lambda: her_agenda(r.ui.kernel, since=start, until=end), label="son agenda")
    if isinstance(got, Failed):
        return []
    out = []
    for d in got:
        whos = {r.who_of_person(p) for p in d.persons}
        if picked and HER not in picked and not (whos & picked):
            continue
        first, last = _days(r, d.start, d.end, False)
        if d.all_day and d.day:
            first = date.fromisoformat(d.day)
        out.append(Item(key=f"m{d.ref.partition(':')[2]}", title=d.title, calendar=HER, calendar_name=r.her_title,
                        color=ROSE, who=HER, start=d.start, end=d.end, all_day=d.all_day, first=first,
                        last=max(first, last), hers=True, date=d))
    return out


def local_time(r: Read, at: int) -> datetime:
    return r.frame.local(at)


__all__ = ["PALETTE", "ROSE", "Item", "Read", "color_of", "conversation_of", "her_items", "her_title", "items",
           "local_time", "occurrence_key", "proposal_args", "proposed_items", "read"]
