"""Ses outils d'agenda (ADR 0309, lot 3a), la famille ``agenda`` — les « MCP internes » : ils passent aussi par le
relais MCP de Claude Code, comme tous ses outils.

- **À qui** : offerts à qui a un agenda à soi ou qu'on lui partage (``rights.offered``, ``ToolSpec.owned``), quand elle
  lui répond, en tête-à-tête ; chacun ne voit que les agendas que les deux portes laissent ici (``rights.here_all`` : le
  propriétaire et le partage, puis le tableau de l'agenda, le canal et le plafond). Jamais dans un salon, jamais pour
  une inconnue.
- **Lire** : ``agenda_list`` (ses agendas ici, et ce qu'elle peut y faire), ``agenda_events`` (une période en mots ou
  en dates, un mot à chercher, un agenda ; chaque événement a sa référence, ``ev<n>`` ou ``ev<n>@<occurrence>``, que
  les autres outils prennent), ``agenda_free`` (des créneaux libres d'une durée donnée, en respectant « occupé » et
  « disponible », dans des heures données). Un événement privé d'une autre personne se lit « Occupé ».
- **Écrire** : ``agenda_create``, ``agenda_edit`` (cet événement, celui-ci et les suivants, tous), ``agenda_delete``,
  ``agenda_respond`` (oui, peut-être, non, un mot). L'outil **propose** (capacité ``agenda.write``, après le commit),
  avec un aperçu que la personne lit (quoi, quand, dans quel agenda, ce qui change) ; selon la ligne du tableau, elle
  part seule (l'outil attend qu'elle soit écrite et le dit), ou après la carte d'accord de la personne en face, ou
  après l'accord du propriétaire (un partage « lire et préparer » : son chat, et la console). Un aperçu changé entre-
  temps (l'événement modifié ailleurs) fait refuser l'accord.
- **Exécutée** (``write``) : le fournisseur écrit, la marque de Mika est posée sur ce qu'elle ajoute
  (``AddedBy(BY_HER, ref de la conversation, at)``), la copie se relit (``sync.reread``). Un refus se dit en mots
  (``AgendaError``) ; ce qui est fait ou raté s'écrit (``agenda.written``, des contenus) et revient dans son prompt
  (``prompt.py``).
- **Ce qu'elle lit** est venu du dehors (titres, lieux, descriptions, noms) : rendu inerte, et l'outil est
  ``outside`` — sa réponse entre citée. Ses phrases sont dans sa voix (``agenda.*``).
- **D'elle-même** (lot 3b), par les mêmes portes : quand elle prévient quelqu'un (une initiative), elle peut lire ses
  agendas — la ligne « quand elle te parle d'elle-même » ; dans la tâche qui prépare la réponse à une invitation
  (``tasks``), elle lit les agendas de la personne invitée que la ligne « elle seule, au travail » ouvre, et ne répond
  qu'à cette invitation-là — toujours sur l'accord de la personne, quoi que dise le tableau (sa carte dans son chat,
  et la console). Écrire reste réservé à la conversation.
- **Inviter et « Mika te le rappelle »** : ``agenda_create`` et ``agenda_edit`` invitent des adresses (une personne
  qui a un compte, dans l'agenda du système, reçoit l'invitation dans le sien) et posent ou retirent le rappel de
  Mika sur l'événement (gardé dans la base seulement, ``AgendaPort.remind``).
- **Une carte d'accord** ne vaut que ``card_within_us`` dans le chat (jamais au-delà du début du rendez-vous) ; la
  proposition, elle, attend jusqu'au début du rendez-vous (``watch``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from mika.contracts import agenda as agenda_c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.kernel.clock import US, instant, local
from mika.kernel.codec import canonical_json
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.operate import Preview
from mika.plugins.agenda import (
    AGENDA,
    BUNDLE,
    CAPABILITY,
    CREATE,
    DELETE,
    DONE,
    EDIT,
    FAILED,
    OPS,
    OWNER,
    PROVENANCE,
    REFUSED,
    RESPOND,
    WRITTEN,
    hers,
    owner,
    params_of,
)
from mika.plugins.agenda.actions import level_of, person_of
from mika.plugins.agenda.rights import Here, approval, here_all
from mika.plugins.agenda.rights import offered as offered_here
from mika.plugins.agenda.sync import reread
from mika.ports.agenda import (
    ALL,
    BY_HER,
    DAY_US,
    FOLLOWING,
    KIND_WORDS,
    MAYBE,
    NO,
    ONE,
    REMINDERS,
    SYSTEM,
    YES,
    AddedBy,
    AgendaError,
    Calendar,
    Event,
    EventChange,
    EventDraft,
    Occurrence,
    Participant,
    Span,
    instance,
    local_days,
    masked,
    occurrences,
    split_calendar_key,
    system_account,
    whole_days,
    zone_of,
)
from mika.ports.errors import describe_error
from mika.ports.preprocess import cite, inert
from mika.vocab.access import (
    ALONE,
    AT_OWNER,
    CARD,
    KEEP_FLOORS,
    KEEP_WORDS,
    OWNER_OK,
    PERSON,
    SHARE_PREPARE,
    SHARE_USE,
    reaches,
    situation,
)
from mika.vocab.access import NO as CLOSED
from mika.vocab.circadian import day_fr
from mika.vocab.episodes import Kind, is_work_target, task_of
from mika.vocab.ownership import OWNED, best_handle, shared_with
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import elided

log = logging.getLogger("mika.agenda")

#: écrire : en lui répondant ; lire : aussi quand elle prévient quelqu'un d'elle-même, et dans la tâche d'une
#: invitation ; répondre à une invitation : en lui répondant, et dans sa tâche
EPISODES = [Kind.REPLY]
READING = [Kind.REPLY, Kind.INITIATIVE, Kind.TASK]
ANSWERING = [Kind.REPLY, Kind.TASK]
#: au plus tant d'événements montrés d'une lecture, de jours lus d'un coup, de créneaux proposés
EVENTS_SHOWN, DAYS_MAX, FREE_SHOWN = 40, 62, 8
#: ce qu'elle lit au plus d'un titre, d'un lieu, d'une description, d'un nom, de participantes nommées
TITLE_SHOWN, PLACE_SHOWN, TEXT_SHOWN, NAME_SHOWN, PEOPLE_SHOWN = 160, 160, 600, 80, 6
#: ses appels par épisode : lire, écrire
READ_CALLS, WRITE_CALLS = 6, 3
#: un rendez-vous d'au plus tant de jours ; une durée par défaut (min)
LONGEST_DAYS, DEFAULT_MINUTES = 14, 60
#: seule, elle attend que ce soit écrit au plus tant de secondes avant de rendre la main
WAIT_S = 20.0
#: la référence d'un événement qu'elle a lu : son numéro, et l'occurrence d'une série
REF = re.compile(r"^ev(\d{1,12})(?:@(\d{8}(?:T\d{6}Z)?))?$")
#: ce qu'une écriture a rendu au runtime : « … (<uid>) »
UID_IN_RESULT = re.compile(r"\(([^()]{1,300})\)\s*$")
#: ce qui fait l'empreinte de ce qui partirait (avec qui décide et l'état de l'événement touché)
PINNED = ("op", "calendar", "uid", "original", "occurrence", "scope", "draft", "change", "response", "comment",
          "keep", "shared", "remind", "why")
#: au plus tant d'adresses invitées d'un coup ; ce qu'on lit au plus d'une raison
INVITED_MAX, WHY_SHOWN = 30, 300
#: « Mika te le rappelle », en mots (la console et l'aperçu : « 15 min avant »…)
REMINDER_WORDS = dict(REMINDERS)
#: une adresse à inviter
ADDRESS = re.compile(r"^[^@\s<>\"']{1,64}@[^@\s<>\"']{1,255}$")
#: la clé des arguments d'une proposition qui porte l'empreinte de ce qui a été montré (``runtime.decisions``)
SEEN = "_apercu"

Remind = Literal["", "non", "15", "30", "60", "veille", "agenda"]
Period = Literal["", "aujourdhui", "demain", "apres_demain", "cette_semaine", "semaine_prochaine", "ce_weekend",
                 "ce_mois", "mois_prochain"]
Scope = Literal["un", "suivants", "tous"]
Answer = Literal["oui", "peut", "non"]
Repeat = Literal["", "jour", "semaine", "mois", "an"]
#: une répétition en mots → sa règle (RFC 5545)
RULES = {"jour": "FREQ=DAILY", "semaine": "FREQ=WEEKLY", "mois": "FREQ=MONTHLY", "an": "FREQ=YEARLY"}


# ── ce qu'un appel voit ───────────────────────────────────────────────────


@dataclass(slots=True)
class _Desk:
    """Ce qu'un appel d'outil voit des agendas ici : la base, les fournisseurs, ce qu'elle fait de chaque agenda
    (``Here``), chaque agenda, et la personne en face."""

    ctx: Any
    store: Any
    providers: Any
    here: dict[str, Here]
    calendars: dict[str, Calendar]
    target: str
    person: str
    #: la tâche d'une invitation (``Invited``) : elle travaille seule, pour la personne invitée
    task: Any = None

    @property
    def frame(self) -> Frame:
        return self.ctx.frame

    @property
    def tz(self) -> ZoneInfo:
        return self.frame.env.tz_of(self.frame.root)

    def holder(self, calendar: str) -> str:
        return owner(params_of(self.frame), split_calendar_key(calendar)[0])

    def mine(self, calendar: str) -> bool:
        """Cet agenda est-il à la personne en face — ou, dans la tâche d'une invitation, à la personne invitée (le sien,
        ou « à toi » pour une de ses propriétaires) ?"""
        holder = self.holder(calendar)
        if self.task is not None:
            return holder == self.task.holder
        kind = self.frame.episode.kind if self.frame.episode is not None else ""
        return holder == PERSON + self.person or (not holder and situation(self.frame.audience, kind) == AT_OWNER)

    def ordered(self) -> list[str]:
        """Ses agendas d'abord (le principal en tête), puis ceux qu'on lui partage ; par nom."""
        return sorted(self.calendars, key=lambda k: (not self.mine(k), not self.calendars[k].primary,
                                                     self.calendars[k].name.casefold(), k))


def _refused(text: str) -> ToolResult:
    return ToolResult(ok=False, content=text)


def invitation_of(frame: Frame) -> Any:
    """L'invitation dont cette tâche prépare la réponse (``Invited``) ; ``None`` hors d'une tâche de l'agenda."""
    ep = frame.episode
    found = task_of(ep.target) if ep is not None and ep.kind == Kind.TASK else None
    if found is None or found[0] != OWNER:
        return None
    return frame.state(OWNER).invitations.get(found[1])


def offered(audience: Any, kind: str, frame: Frame | None) -> bool:
    """Ses outils d'agenda servent ici : à qui a un agenda ou en reçoit un partage (``rights.offered``), et dans la
    tâche qui prépare la réponse à une invitation."""
    if kind == Kind.TASK:
        return frame is not None and invitation_of(frame) is not None
    return offered_here(audience, kind, frame)


def task_decider(frame: Frame, holder: str) -> str:
    """Où demander l'accord de la personne invitée : une de ses adresses présente, sinon une où l'on peut lui écrire
    (son chat) ; un agenda « à toi » : la première de ses propriétaires. Vide : nulle part (la console seule)."""
    person = holder[len(PERSON):] if holder.startswith(PERSON) else next(iter(frame.get(identity_c.OWNERS) or ()), "")
    if not person:
        return ""
    return best_handle(list(frame.get(identity_c.HANDLES(person)) or (person,)), set(frame.get(presence_c.PRESENT)),
                       set(frame.get(identity_c.REACHABLE(person))))


def _open_task(ctx: Any, store: Any, providers: Any) -> _Desk | ToolResult:
    """La tâche d'une invitation : les agendas de la personne invitée que la ligne « elle seule, au travail » laisse
    lire (de quoi voir ce qui tombe en même temps) — jamais ceux d'une autre."""
    frame = ctx.frame
    inv = invitation_of(frame)
    if inv is None or inv.status != agenda_c.PENDING:
        return _refused(phrase("agenda.tools.not_here"))
    p = params_of(frame)
    theirs = [c.key for c in store.calendars() if owner(p, split_calendar_key(c.key)[0]) == inv.holder]
    allowed = here_all(frame, theirs)
    calendars = {k: c for k in allowed if (c := store.calendar(k)) is not None}
    if inv.calendar not in calendars:
        return _refused(phrase("agenda.tools.none"))
    decider = task_decider(frame, inv.holder)
    person = inv.holder[len(PERSON):] if inv.holder.startswith(PERSON) else ""
    return _Desk(ctx, store, providers, {k: allowed[k] for k in calendars}, calendars, decider, person, task=inv)


def _open(ctx: Any) -> _Desk | ToolResult:
    """Les agendas qui servent ici, ou pourquoi aucun : en tête-à-tête, avec la personne à qui ils sont ou à qui on
    les partage, dans ce que les tableaux laissent lire (« Mon agenda » de la personne naît au besoin) ; dans la tâche
    d'une invitation, ceux de la personne invitée."""
    frame = ctx.frame
    store, providers = ctx.ports.get("agenda"), ctx.ports.get("agenda_providers")
    if store is None or providers is None:
        return _refused(phrase("agenda.tools.no_port"))
    if frame.episode is not None and frame.episode.kind == Kind.TASK:
        return _open_task(ctx, store, providers)
    ep, audience = frame.episode, frame.audience
    target = (ep.target if ep is not None else None) or ""
    kind = ep.kind if ep is not None else ""
    if not target or is_work_target(target) or audience is None or target not in audience.persons \
            or not shared_with(audience, kind):
        return _refused(phrase("agenda.tools.not_here"))
    person = audience.person or target
    system = getattr(providers, "system", None)
    if system is not None:
        try:
            system.ensure(system_account(person))
        except AgendaError as exc:
            log.warning("agenda : « Mon agenda » n'a pas pu naître : %s", exc)
    allowed = here_all(frame, [c.key for c in store.calendars()])
    calendars = {k: c for k in allowed if (c := store.calendar(k)) is not None}
    if not calendars:
        return _refused(phrase("agenda.tools.none"))
    return _Desk(ctx, store, providers, {k: allowed[k] for k in calendars}, calendars, target, person)


def _calendar_named(desk: _Desk, wanted: str) -> str | None:
    """Un agenda d'ici par sa clé, ou par son nom (sans tenir compte de la casse) ; ``None`` : aucun, ou plusieurs."""
    wanted = wanted.strip()
    if wanted in desk.calendars:
        return wanted
    folded = wanted.casefold()
    named = [k for k, c in desk.calendars.items() if (c.name or "").casefold() == folded]
    return named[0] if len(named) == 1 else None


def _ref(o: Occurrence) -> str:
    """La référence d'une occurrence : la ligne de son événement, et sa clé dans une série."""
    e = o.event
    return f"ev{e.id}@{o.key}" if e.recurring and not e.original and o.key else f"ev{e.id}"


def _event(desk: _Desk, ref: str) -> tuple[Event, str] | ToolResult:
    """L'événement d'une référence (``ev12``, ``ev12@20261124T090000Z``) et la clé de l'occurrence visée ; il est dans
    un agenda d'ici, ou n'existe pas pour l'outil."""
    got = REF.fullmatch(ref.strip().strip("[]"))
    event = desk.store.event(int(got.group(1))) if got else None
    if got is None or event is None or event.calendar not in desk.calendars:
        return _refused(phrase("agenda.tools.unknown_event", ref=inert(ref, 40)))
    return event, got.group(2) or event.original


# ── le temps, en mots et en dates ─────────────────────────────────────────


def hm(dt: datetime) -> str:
    """« 9 h », « 14 h 30 »."""
    return phrase("agenda.words.hour", h=dt.hour) if not dt.minute else \
        phrase("agenda.words.hour_minute", h=dt.hour, m=f"{dt.minute:02d}")


def _midnight(d: date, tz: ZoneInfo) -> int:
    return instant(datetime.combine(d, time(), tzinfo=tz))


def local_span(span: Span, tz: ZoneInfo) -> tuple[int, int]:
    """Quand il occupe, en instants : une journée entière, de minuit à minuit dans ce fuseau (ses instants sont à
    minuit UTC de ses dates)."""
    return local_days(span, tz)


def when_words(span: Span, tz: ZoneInfo) -> str:
    """Quand, en mots : « mardi 24 novembre, 9 h 30 – 10 h 30 », « samedi 28 novembre, toute la journée », « du
    samedi 28 au lundi 30 novembre »."""
    if span.all_day:
        first, last = date.fromisoformat(span.first_day), date.fromisoformat(span.last_day)
        if first == last:
            return phrase("agenda.words.all_day", day=day_fr(first))
        return phrase("agenda.words.days", first=day_fr(first), last=day_fr(last))
    start, end = local(span.start, tz), local(max(span.start, span.end), tz)
    if start.date() == end.date() or (end - start <= timedelta(hours=24) and end.time() == time()):
        return phrase("agenda.words.timed", day=day_fr(start.date()), start=hm(start), end=hm(end))
    return phrase("agenda.words.timed_days", first=day_fr(start.date()), start=hm(start), last=day_fr(end.date()),
                  end=hm(end))


def period(when: str, start: str, end: str, today: date) -> tuple[date, date] | None:
    """Une période, du premier jour au lendemain du dernier : en mots (``Period``) ou en dates (``AAAA-MM-JJ``, la
    dernière comprise ; une seule, ce jour-là) ; rien : les sept jours qui viennent. ``None`` : une date illisible, ou
    une fin avant le début. Jamais plus de ``DAYS_MAX`` jours."""
    if start.strip() or end.strip():
        try:
            first = date.fromisoformat((start or end).strip())
            last = date.fromisoformat((end or start).strip())
        except ValueError:
            return None
        if last < first:
            return None
        return first, min(last + timedelta(days=1), first + timedelta(days=DAYS_MAX))
    monday = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    following = (month + timedelta(days=32)).replace(day=1)
    spans = {
        "aujourdhui": (today, today + timedelta(days=1)),
        "demain": (today + timedelta(days=1), today + timedelta(days=2)),
        "apres_demain": (today + timedelta(days=2), today + timedelta(days=3)),
        "cette_semaine": (today, monday + timedelta(days=7)),
        "semaine_prochaine": (monday + timedelta(days=7), monday + timedelta(days=14)),
        "ce_weekend": (max(today, monday + timedelta(days=5)), monday + timedelta(days=7)),
        "ce_mois": (today, following),
        "mois_prochain": (following, (following + timedelta(days=32)).replace(day=1)),
    }
    return spans.get(when, (today, today + timedelta(days=7)))


def period_words(first: date, after: date) -> str:
    last = after - timedelta(days=1)
    return day_fr(first) if first == last else phrase("agenda.words.period", first=day_fr(first), last=day_fr(last))


def _moment(text: str, tz: ZoneInfo) -> datetime | date | None:
    """Une date (``AAAA-MM-JJ``) ou une heure (``AAAA-MM-JJTHH:MM``, dans ce fuseau) ; ``None`` : illisible."""
    text = text.strip().replace(" ", "T")
    if not text:
        return None
    try:
        if "T" not in text:
            return date.fromisoformat(text)
        got = datetime.fromisoformat(text)
    except ValueError:
        return None
    return got.replace(tzinfo=tz) if got.tzinfo is None else got.astimezone(tz)


def span_of(start: str, end: str, minutes: int | None, all_day: bool, tz: ZoneInfo, *,
            current: Span | None = None) -> Span | str | None:
    """La période qu'un outil demande : une journée entière (une date, ou ``all_day``), ou de telle heure à telle
    heure (la fin, sinon une durée, sinon celle de l'événement changé ``current``, sinon une heure). ``None`` : rien
    de demandé ; un texte : pourquoi c'est illisible."""
    if not start.strip() and not end.strip() and minutes is None and current is None:
        return None
    if not start.strip() and current is None:
        return phrase("agenda.tools.bad_time")
    begin = _moment(start, tz) if start.strip() else None
    if begin is None and start.strip():
        return phrase("agenda.tools.bad_time")
    if begin is None:  # on ne change que la fin, ou la durée : depuis le début d'aujourd'hui
        assert current is not None
        begin = date.fromisoformat(current.first_day) if current.all_day else local(current.start, tz)
    finish = _moment(end, tz) if end.strip() else None
    if end.strip() and finish is None:
        return phrase("agenda.tools.bad_time")
    if all_day or (isinstance(begin, date) and not isinstance(begin, datetime)):
        first = begin.date() if isinstance(begin, datetime) else begin
        last = (finish.date() if isinstance(finish, datetime) else finish) if finish is not None else first
        if current is not None and current.all_day and finish is None and not start.strip():
            last = date.fromisoformat(current.last_day)
        if last < first or (last - first).days > LONGEST_DAYS:
            return phrase("agenda.tools.bad_time")
        return whole_days(first.isoformat(), last.isoformat())
    assert isinstance(begin, datetime)
    if isinstance(finish, datetime):
        stop = finish
    elif isinstance(finish, date):
        return phrase("agenda.tools.bad_time")
    elif minutes is not None:
        stop = begin + timedelta(minutes=minutes)
    elif current is not None and not current.all_day:
        stop = begin + timedelta(microseconds=current.end - current.start)
    else:
        stop = begin + timedelta(minutes=DEFAULT_MINUTES)
    if stop <= begin or stop - begin > timedelta(days=LONGEST_DAYS):
        return phrase("agenda.tools.bad_time")
    return Span(instant(begin), instant(stop), getattr(tz, "key", ""), False)


# ── lire ──────────────────────────────────────────────────────────────────


def _whose(desk: _Desk, calendar: str) -> str:
    if desk.mine(calendar):
        return phrase("agenda.words.yours")
    holder = desk.holder(calendar)
    name = identity_c.person_name(desk.frame, holder[len(PERSON):]) if holder.startswith(PERSON) else ""
    return phrase("agenda.words.theirs", name=inert(name, NAME_SHOWN) if name else phrase("agenda.words.someone"))


def _can(desk: _Desk, calendar: str) -> str:
    """Ce qu'elle peut faire de cet agenda ici, en mots."""
    h, cal = desk.here[calendar], desk.calendars[calendar]
    said = [phrase("agenda.can.read")]
    if not cal.writable:
        said.append(phrase("agenda.can.read_only"))
    elif h.write == ALONE:
        said.append(phrase("agenda.can.write_alone"))
    elif h.owner_decides:
        said.append(phrase("agenda.can.write_owner", of=elided(_owner_name(desk, calendar), "de")))
    elif h.write in (CARD, OWNER_OK):
        said.append(phrase("agenda.can.write_card"))
    if cal.writable and h.respond != CLOSED:
        said.append(phrase("agenda.can.respond"))
    said.append(phrase("agenda.can.keep", keep=KEEP_WORDS.get(h.keep, h.keep)))
    return ", ".join(said)


def _owner_name(desk: _Desk, calendar: str) -> str:
    holder = desk.holder(calendar)
    name = identity_c.person_name(desk.frame, holder[len(PERSON):]) if holder.startswith(PERSON) else ""
    return inert(name, NAME_SHOWN) if name else identity_c.keepers(desk.frame)


def _calendar_line(desk: _Desk, calendar: str) -> str:
    cal = desk.calendars[calendar]
    account, _ = split_calendar_key(calendar)
    conn = desk.providers.connection(account)
    kind = KIND_WORDS.get(conn.kind if conn is not None else "", "")
    return phrase("agenda.tools.list.line", key=calendar, name=inert(cal.name or calendar, NAME_SHOWN), kind=kind,
                  whose=_whose(desk, calendar), can=_can(desk, calendar))


class NoArgs(BaseModel):
    pass


def _floor(desk: _Desk, calendars: Sequence[str]) -> dict[str, Any]:
    """Ce que vaut ce qu'elle a lu de ces agendas (ADR 0128) : la garde la plus stricte de leurs lignes."""
    keeps = [desk.here[c].keep for c in calendars]
    return {"floor": max((KEEP_FLOORS.get(k, 0) for k in keeps), default=0), "unkept": "rien" in keeps}


@AGENDA.tool("agenda_list", description=phrase("agenda.tools.list.description"),
             label=phrase("agenda.tools.list.label"), args=NoArgs, bundle=BUNDLE, episodes=READING,
             max_calls_per_episode=READ_CALLS, owner_only=True, owned=offered, outside=True, needs="agenda")
async def agenda_list(args: NoArgs, ctx: Any) -> Any:
    desk = _open(ctx)
    if isinstance(desk, ToolResult):
        return desk
    lines = [_calendar_line(desk, c) for c in desk.ordered()]
    return ToolResult(content="\n".join([phrase("agenda.tools.list.head"), *lines]), **_floor(desk, list(desk.here)))


class EventsArgs(BaseModel):
    when: Period = Field(default="", description=phrase("agenda.tools.args.when"))
    start: str = Field(default="", max_length=10, description=phrase("agenda.tools.args.start_day"))
    end: str = Field(default="", max_length=10, description=phrase("agenda.tools.args.end_day"))
    text: str = Field(default="", max_length=100, description=phrase("agenda.tools.args.text"))
    calendar: str = Field(default="", max_length=200, description=phrase("agenda.tools.args.calendar"))


def _chosen(desk: _Desk, calendar: str) -> list[str] | ToolResult:
    if not calendar.strip():
        return desk.ordered()
    key = _calendar_named(desk, calendar)
    if key is None:
        return _refused(phrase("agenda.tools.unknown_calendar", name=inert(calendar, NAME_SHOWN)))
    return [key]


def _shown(desk: _Desk, o: Occurrence) -> Event:
    """L'événement tel qu'elle peut le lire : celui d'une autre personne, privé, se lit « Occupé »."""
    e = o.event
    h = desk.here.get(e.calendar)
    return masked(e) if e.private and (h is None or not h.owned) else e


def event_line(desk: _Desk, o: Occurrence) -> str:
    """Une occurrence en une ligne : sa référence, quand, son titre (« Occupé » sans titre), son lieu, avec qui, son
    agenda, et ce qui compte (provisoire, une invitation, sa réponse, ajouté par elle) — rendus inertes."""
    e, tz = _shown(desk, o), desk.tz
    title = inert(e.title, TITLE_SHOWN) if e.title.strip() else phrase("agenda.words.busy")
    parts = [f"[{_ref(o)}] {when_words(o.span, tz)}", phrase("agenda.words.title", title=title)]
    if e.location.strip():
        parts.append(phrase("agenda.words.where", place=inert(e.location, PLACE_SHOWN)))
    names = [inert(p.name or p.address or p.person, NAME_SHOWN) for p in e.participants if not p.me]
    if names:
        more = len(names) - PEOPLE_SHOWN
        parts.append(phrase("agenda.words.with", who=", ".join(names[:PEOPLE_SHOWN]))
                     + (phrase("agenda.words.more_people", n=more) if more > 0 else ""))
    if e.organizer is not None and not e.organizer.me and e.response:
        who = e.organizer.name or e.organizer.address or e.organizer.person
        if who:
            parts.append(phrase("agenda.words.from", who=inert(who, NAME_SHOWN)))
    if len(desk.calendars) > 1:
        parts.append(phrase("agenda.words.in", name=inert(desk.calendars[e.calendar].name or e.calendar, NAME_SHOWN)))
    if e.response:
        parts.append(phrase(f"agenda.words.answer.{e.response}"))
    if e.status == "provisoire":
        parts.append(phrase("agenda.words.tentative"))
    if not e.busy:
        parts.append(phrase("agenda.words.free"))
    if e.recurring or e.original:
        parts.append(phrase("agenda.words.recurring"))
    if e.added is not None and e.added.by == BY_HER:
        parts.append(phrase("agenda.words.by_her"))
    if o.event.remind:
        parts.append(phrase("agenda.words.remind", delay=REMINDER_WORDS.get(o.event.remind, o.event.remind)))
    return "- " + " · ".join(parts)


def _matches(e: Event, text: str) -> bool:
    folded = text.casefold()
    return any(folded in (v or "").casefold() for v in (e.title, e.location, e.description))


@AGENDA.tool("agenda_events", description=phrase("agenda.tools.events.description"),
             label=phrase("agenda.tools.events.label"), args=EventsArgs, bundle=BUNDLE, episodes=READING,
             max_calls_per_episode=READ_CALLS, owner_only=True, owned=offered, outside=True, needs="agenda")
async def agenda_events(args: EventsArgs, ctx: Any) -> Any:
    desk = _open(ctx)
    if isinstance(desk, ToolResult):
        return desk
    chosen = _chosen(desk, args.calendar)
    if isinstance(chosen, ToolResult):
        return chosen
    days = period(args.when, args.start, args.end, desk.frame.local().date())
    if days is None:
        return _refused(phrase("agenda.tools.bad_period"))
    first, after = days
    found = desk.store.period(chosen, _midnight(first, desk.tz), _midnight(after, desk.tz), zone=desk.tz)
    if args.text.strip():
        found = [o for o in found if _matches(_shown(desk, o), args.text.strip())]
    head = phrase("agenda.tools.events.head", period=period_words(first, after))
    if not found:
        return ToolResult(content=head + "\n" + phrase("agenda.tools.events.nothing"), **_floor(desk, chosen))
    lines = [event_line(desk, o) for o in found[:EVENTS_SHOWN]]
    if len(found) > EVENTS_SHOWN:
        lines.append(phrase("agenda.tools.events.more", n=len(found) - EVENTS_SHOWN))
    return ToolResult(content="\n".join([head, *lines]), **_floor(desk, chosen))


class FreeArgs(BaseModel):
    minutes: int = Field(ge=5, le=24 * 60, description=phrase("agenda.tools.args.minutes"))
    when: Period = Field(default="", description=phrase("agenda.tools.args.when"))
    start: str = Field(default="", max_length=10, description=phrase("agenda.tools.args.start_day"))
    end: str = Field(default="", max_length=10, description=phrase("agenda.tools.args.end_day"))
    from_hour: int = Field(default=9, ge=0, le=23, description=phrase("agenda.tools.args.from_hour"))
    to_hour: int = Field(default=19, ge=1, le=24, description=phrase("agenda.tools.args.to_hour"))
    calendar: str = Field(default="", max_length=200, description=phrase("agenda.tools.args.calendar_free"))


def free_slots(busy: Sequence[tuple[int, int]], windows: Sequence[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    """Les créneaux libres d'au moins ``length`` µs dans ces fenêtres, une fois retirés ces moments occupés."""
    taken = sorted(busy)
    out: list[tuple[int, int]] = []
    for lo, hi in windows:
        cursor = lo
        for b0, b1 in taken:
            if b1 <= cursor or b0 >= hi:
                continue
            if b0 - cursor >= length:
                out.append((cursor, b0))
            cursor = max(cursor, b1)
            if cursor >= hi:
                break
        if hi - cursor >= length:
            out.append((cursor, hi))
    return out


@AGENDA.tool("agenda_free", description=phrase("agenda.tools.free.description"),
             label=phrase("agenda.tools.free.label"), args=FreeArgs, bundle=BUNDLE, episodes=READING,
             max_calls_per_episode=READ_CALLS, owner_only=True, owned=offered, outside=True, needs="agenda")
async def agenda_free(args: FreeArgs, ctx: Any) -> Any:
    desk = _open(ctx)
    if isinstance(desk, ToolResult):
        return desk
    chosen = _chosen(desk, args.calendar)
    if isinstance(chosen, ToolResult):
        return chosen
    if args.to_hour <= args.from_hour:
        return _refused(phrase("agenda.tools.bad_hours"))
    tz, now = desk.tz, desk.frame.now
    days = period(args.when, args.start, args.end, desk.frame.local().date())
    if days is None:
        return _refused(phrase("agenda.tools.bad_period"))
    first, after = days
    windows = []
    d = first
    while d < after:
        lo = max(now, instant(datetime.combine(d, time(args.from_hour), tzinfo=tz)))
        hi = _midnight(d + timedelta(days=1), tz) if args.to_hour == 24 else \
            instant(datetime.combine(d, time(args.to_hour), tzinfo=tz))
        if hi > lo:
            windows.append((lo, hi))
        d += timedelta(days=1)
    found = desk.store.period(chosen, _midnight(first, tz), _midnight(after, tz), zone=tz)
    busy = [local_span(o.span, tz) for o in found if o.event.busy and o.event.status != "annule"]
    slots = free_slots(busy, windows, args.minutes * 60 * US)
    head = phrase("agenda.tools.free.head", period=period_words(first, after), minutes=args.minutes)
    if not slots:
        return ToolResult(content=head + "\n" + phrase("agenda.tools.free.nothing"), **_floor(desk, chosen))
    lines = ["- " + when_words(Span(lo, hi), tz) for lo, hi in slots[:FREE_SHOWN]]
    if len(slots) > FREE_SHOWN:
        lines.append(phrase("agenda.tools.free.more", n=len(slots) - FREE_SHOWN))
    return ToolResult(content="\n".join([head, *lines]), **_floor(desk, chosen))


# ── écrire : proposer ce que la capacité fera ────────────────────────────


def _conversation(frame: Frame) -> str:
    """La référence de la conversation où elle l'a fait (ce que la console et l'écran ouvrent) : l'adresse de la
    personne, et le message auquel elle répondait ; la tâche d'une invitation, sa cible."""
    ep = frame.episode
    target = (ep.target if ep is not None else None) or ""
    if ep is not None and ep.kind == Kind.TASK:
        return target
    reply_to = ep.attrs.get("reply_to") if ep is not None else None
    return f"chat:{target}:{reply_to}" if reply_to else f"chat:{target}"


def _span_json(span: Span) -> dict[str, Any]:
    return {"start": span.start, "end": span.end, "zone": span.zone, "all_day": span.all_day}


def _span_from(raw: Mapping[str, Any]) -> Span:
    return Span(int(raw.get("start") or 0), int(raw.get("end") or 0), str(raw.get("zone") or ""),
                bool(raw.get("all_day")))


def _writable(desk: _Desk, calendar: str, level: str) -> ToolResult | None:
    """Ce qui empêche d'écrire dans cet agenda ici : son tableau (ou son partage), le fournisseur, le compte."""
    cal = desk.calendars[calendar]
    if level == CLOSED:
        return _refused(phrase("agenda.tools.cannot_write", name=inert(cal.name or calendar, NAME_SHOWN)))
    if not cal.writable:
        return _refused(phrase("agenda.tools.read_only", name=inert(cal.name or calendar, NAME_SHOWN)))
    conn = desk.providers.connection(split_calendar_key(calendar)[0])
    provider = desk.providers.of(conn.kind) if conn is not None else None
    if conn is None or provider is None or not conn.enabled or not provider.abilities(conn).write:
        return _refused(phrase("agenda.tools.read_only", name=inert(cal.name or calendar, NAME_SHOWN)))
    return None


def _starts(desk: _Desk, event: Event | None, occurrence: str, span: Span | None = None) -> int:
    """Quand commence ce que vise une proposition (une journée entière : à minuit, ici) : le rendez-vous qu'on ajoute,
    l'occurrence visée, sinon la prochaine d'une série ; 0 : il n'en a plus. Passé, la proposition tombe."""
    if span is None and event is not None:
        if occurrence or not event.recurring:
            span = _current(event, occurrence)
        else:
            found = occurrences(event, desk.frame.now, desk.frame.now + 400 * DAY_US, limit=1)
            span = found[0].span if found else None
    return local_span(span, desk.tz)[0] if span is not None else 0


async def propose(desk: _Desk, calendar: str, level: str, payload: dict[str, Any], summary: str, *,
                  starts: int = 0) -> ToolResult:
    """Propose l'écriture (``agenda.write``) : seule, elle part après le commit et l'outil attend qu'elle soit écrite ;
    sinon une carte d'accord (la personne en face, ou le propriétaire), ou la console. L'aperçu est ce qu'on approuve.
    Dans la tâche d'une invitation, toujours l'accord de la personne invitée, quoi que dise le tableau : sa carte dans
    son chat, et la console. Une carte du chat ne vaut que ``card_within_us``, jamais au-delà de ``starts`` (le début
    du rendez-vous) ; la proposition attend jusqu'à ``starts``, où elle tombe (``watch``)."""
    ctx, frame, h = desk.ctx, desk.frame, desk.here[calendar]
    needs = level != ALONE or desk.task is not None
    if desk.task is not None:
        in_chat, decider = bool(desk.target), desk.target
    else:
        in_chat, decider = approval(frame, h, desk.holder(calendar)) if needs else (False, "")
    payload = {**payload, "calendar": calendar, "keep": h.keep, "target": desk.target, "ref": _conversation(frame),
               "starts": starts}
    if not h.owned:  # par un partage : il doit tenir encore quand on décide
        payload["shared"] = PERSON + desk.person
    if desk.task is not None:
        payload["invitation"] = desk.task.key
    if needs and in_chat:
        payload[rt.DECIDER] = decider
        until = frame.now + params_of(frame).card_within_us
        payload[rt.EXPIRES] = min(until, starts) if starts > frame.now else until
    shown = await preview(payload, ctx.ports)
    if shown.blocked:
        return _refused(phrase("agenda.tools.blocked", why=inert(shown.blocked, 200)))
    payload[SEEN] = shown.digest
    about = tuple(dict.fromkeys(x for x in (desk.target, decider) if x))
    commit = await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=CAPABILITY, owner=OWNER, args_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        summary=Content.of(summary[:400], level=int(Sensitivity.PERSONAL)), approval=needs, context=desk.target,
        about=about))
    proposal = commit.seqs[-1]
    told = (f"{PROVENANCE}{proposal}",)
    if needs:
        if h.owner_decides or desk.task is not None:
            who = phrase("agenda.tools.who.owner", of=elided(_owner_name(desk, calendar), "de"))
        elif in_chat:
            who = phrase("agenda.tools.who.card")
        else:
            who = phrase("agenda.tools.who.operator", of=elided(identity_c.keepers(frame), "de"))
        return ToolResult(content="\n".join([phrase("agenda.tools.proposed", who=who), shown.text]), proof=True,
                          **_floor(desk, [calendar]))
    done = await ctx.until(lambda f: _settled(f, proposal), WAIT_S)
    w = (done or ctx.mind.frame()).state(OWNER).writes.get(proposal)
    if w is None or w.status not in (DONE, FAILED):
        return ToolResult(content="\n".join([phrase("agenda.tools.sent"), shown.text]), proof=True,
                          **_floor(desk, [calendar]))
    if w.status == DONE:
        return ToolResult(content="\n".join([phrase("agenda.tools.done"), shown.text]), proof=True, provenance=told,
                          **_floor(desk, [calendar]))
    store = ctx.ports.get("store")
    why = (store.content([w.why_ref]).get(w.why_ref) or "") if store is not None and w.why_ref else ""
    return ToolResult(ok=False, content="\n".join([phrase("agenda.tools.failed"), cite(why, 300) or "", shown.text]),
                      provenance=told)


def _settled(frame: Frame, proposal: int) -> bool:
    w = frame.state(OWNER).writes.get(proposal)
    return w is not None and (w.status == DONE or (w.status == FAILED and bool(w.why_ref)) or w.status == REFUSED)


class CreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300, description=phrase("agenda.tools.args.title"))
    start: str = Field(max_length=25, description=phrase("agenda.tools.args.start"))
    end: str = Field(default="", max_length=25, description=phrase("agenda.tools.args.end"))
    minutes: int | None = Field(default=None, ge=1, le=LONGEST_DAYS * 24 * 60,
                                description=phrase("agenda.tools.args.duration"))
    all_day: bool = Field(default=False, description=phrase("agenda.tools.args.all_day"))
    location: str = Field(default="", max_length=300, description=phrase("agenda.tools.args.location"))
    description: str = Field(default="", max_length=2000, description=phrase("agenda.tools.args.description"))
    calendar: str = Field(default="", max_length=200, description=phrase("agenda.tools.args.calendar_write"))
    repeat: Repeat = Field(default="", description=phrase("agenda.tools.args.repeat"))
    until: str = Field(default="", max_length=10, description=phrase("agenda.tools.args.until"))
    count: int | None = Field(default=None, ge=1, le=500, description=phrase("agenda.tools.args.count"))
    invite: list[str] = Field(default_factory=list, max_length=INVITED_MAX,
                              description=phrase("agenda.tools.args.invite"))
    remind: Remind = Field(default="", description=phrase("agenda.tools.args.remind"))


def _default_calendar(desk: _Desk) -> str | None:
    """L'agenda où ajouter quand elle ne le dit pas : le principal de la personne où elle peut écrire, sinon le premier
    des siens, sinon le premier qu'on lui partage où elle peut écrire."""
    writable = [k for k in desk.ordered() if desk.here[k].write != CLOSED and desk.calendars[k].writable]
    return writable[0] if writable else None


def _invitees(desk: _Desk, calendar: str, addresses: Sequence[str]) -> list[dict[str, str]] | ToolResult:
    """Des adresses à inviter, vérifiées : une personne qui a un compte (une de ses adresses est connectée par son
    compte), dans un agenda du système, est invitée par sa clé — l'invitation arrive dans son agenda à elle."""
    out: dict[str, dict[str, str]] = {}
    system = (getattr(desk.providers.connection(split_calendar_key(calendar)[0]), "kind", "") == SYSTEM)
    for raw in addresses:
        address = raw.strip().lower()
        if not address:
            continue
        if not ADDRESS.fullmatch(address):
            return _refused(phrase("agenda.tools.bad_address", address=inert(raw, 80)))
        person = ""
        if system:
            found = str(desk.frame.get(identity_c.PERSON(f"mail:{address}")) or "")
            if found and not found.startswith("mail:") and any(
                    desk.frame.get(identity_c.IDENTITY(h)).authenticated
                    for h in desk.frame.get(identity_c.HANDLES(found)) or ()):
                person = found
        out.setdefault(address, {"address": address, "person": person})
    return list(out.values())


def _participant_json(x: Participant) -> dict[str, Any]:
    return {"address": x.address, "person": x.person, "name": x.name, "response": x.response,
            "optional": x.optional, "me": x.me}


def _participants(raw: Any) -> tuple[Participant, ...]:
    """Les participantes d'un aperçu (des dictionnaires) ; ce qui ne se lit pas est laissé de côté."""
    out = []
    for x in raw if isinstance(raw, list) else ():
        if isinstance(x, Mapping) and (x.get("address") or x.get("person")):
            out.append(Participant(address=str(x.get("address") or ""), name=str(x.get("name") or ""),
                                   person=str(x.get("person") or ""), response=str(x.get("response") or ""),
                                   optional=bool(x.get("optional")), me=bool(x.get("me"))))
    return tuple(out)


def _remind_choice(value: str) -> str | None:
    """« Mika te le rappelle » demandé : ``None`` sans rien dire ; « agenda » : revenir au choix de son agenda (vide)."""
    if not value:
        return None
    return "" if value == "agenda" else value


def _rule(repeat: str, until: str, count: int | None) -> str | None:
    """La règle d'une répétition (RFC 5545) ; ``None`` : une date de fin illisible."""
    if not repeat:
        return ""
    parts = [RULES[repeat]]
    if until.strip():
        try:
            parts.append("UNTIL=" + date.fromisoformat(until.strip()).strftime("%Y%m%d"))
        except ValueError:
            return None
    elif count is not None:
        parts.append(f"COUNT={count}")
    return ";".join(parts)


@AGENDA.tool("agenda_create", acts=True, description=phrase("agenda.tools.create.description"),
             label=phrase("agenda.tools.create.label"), args=CreateArgs, bundle=BUNDLE, episodes=EPISODES,
             max_calls_per_episode=WRITE_CALLS, owner_only=True, owned=offered, outside=True, needs="agenda")
async def agenda_create(args: CreateArgs, ctx: Any) -> Any:
    desk = _open(ctx)
    if isinstance(desk, ToolResult):
        return desk
    calendar = _calendar_named(desk, args.calendar) if args.calendar.strip() else _default_calendar(desk)
    if calendar is None and args.calendar.strip():
        return _refused(phrase("agenda.tools.unknown_calendar", name=inert(args.calendar, NAME_SHOWN)))
    if calendar is None:
        return _refused(phrase("agenda.tools.nowhere"))
    h = desk.here[calendar]
    refused = _writable(desk, calendar, h.write)
    if refused is not None:
        return refused
    tz = zone_of(desk.calendars[calendar].zone) if desk.calendars[calendar].zone else desk.tz
    span = span_of(args.start, args.end, args.minutes, args.all_day, tz)
    if not isinstance(span, Span):
        return _refused(span or phrase("agenda.tools.bad_time"))
    rule = _rule(args.repeat, args.until, args.count)
    if rule is None:
        return _refused(phrase("agenda.tools.bad_time"))
    invitees = _invitees(desk, calendar, args.invite)
    if isinstance(invitees, ToolResult):
        return invitees
    draft = {"title": args.title.strip(), "span": _span_json(span), "location": args.location.strip(),
             "description": args.description.strip(), "rule": rule, "invite": invitees}
    summary = phrase("agenda.summary.create", title=inert(args.title, TITLE_SHOWN),
                     name=inert(desk.calendars[calendar].name or calendar, NAME_SHOWN),
                     when=when_words(span, desk.tz))
    payload: dict[str, Any] = {"op": CREATE, "draft": draft}
    remind = _remind_choice(args.remind)
    if remind is not None:
        payload["remind"] = remind
    return await propose(desk, calendar, h.write, payload, summary, starts=_starts(desk, None, "", span))


class EditArgs(BaseModel):
    ref: str = Field(min_length=3, max_length=40, description=phrase("agenda.tools.args.ref"))
    scope: Scope = Field(default="un", description=phrase("agenda.tools.args.scope"))
    title: str = Field(default="", max_length=300, description=phrase("agenda.tools.args.new_title"))
    start: str = Field(default="", max_length=25, description=phrase("agenda.tools.args.new_start"))
    end: str = Field(default="", max_length=25, description=phrase("agenda.tools.args.end"))
    minutes: int | None = Field(default=None, ge=1, le=LONGEST_DAYS * 24 * 60,
                                description=phrase("agenda.tools.args.duration"))
    all_day: bool | None = Field(default=None, description=phrase("agenda.tools.args.all_day"))
    location: str | None = Field(default=None, max_length=300, description=phrase("agenda.tools.args.new_location"))
    description: str | None = Field(default=None, max_length=2000,
                                    description=phrase("agenda.tools.args.new_description"))
    invite: list[str] = Field(default_factory=list, max_length=INVITED_MAX,
                              description=phrase("agenda.tools.args.invite_more"))
    uninvite: list[str] = Field(default_factory=list, max_length=INVITED_MAX,
                                description=phrase("agenda.tools.args.uninvite"))
    remind: Remind = Field(default="", description=phrase("agenda.tools.args.remind"))


def _current(event: Event, occurrence: str) -> Span:
    """Quand a lieu ce qu'on vise : l'occurrence d'une série, sinon l'événement."""
    if occurrence and event.recurring and not event.original:
        return instance(event, occurrence).span
    return event.span


def _scope(event: Event, occurrence: str, scope: str) -> str:
    """La portée d'un changement : un événement simple ou une série entière, tous ; une occurrence, celle demandée."""
    if not occurrence or not (event.recurring or event.original):
        return ALL
    return {"un": ONE, "suivants": FOLLOWING, "tous": ALL}.get(scope, ONE)


def _target_of(desk: _Desk, event: Event, occurrence: str) -> dict[str, Any]:
    return {"event": event.id, "uid": event.uid, "original": event.original, "occurrence": occurrence}


def _what(desk: _Desk, event: Event, occurrence: str) -> str:
    """L'événement visé, en mots (son titre, quand) : « Occupé » pour un privé d'une autre personne."""
    h = desk.here.get(event.calendar)
    shown = masked(event) if event.private and (h is None or not h.owned) else event
    title = inert(shown.title, TITLE_SHOWN) if shown.title.strip() else phrase("agenda.words.busy")
    return phrase("agenda.words.event", title=title, when=when_words(_current(event, occurrence), desk.tz))


def busy_summary(op: str, event: Event, occurrence: str, name: str, tz: ZoneInfo) -> str:
    """Ce que résume une proposition sur un événement privé, pour qui n'en est ni propriétaire ni ne la décide (un
    partage qui prépare) : « Occupé », quand, dans quel agenda — ni son titre, ni la réponse préparée."""
    what = phrase("agenda.words.event", title=phrase("agenda.words.busy"),
                  when=when_words(_current(event, occurrence), tz))
    if op == RESPOND:
        return phrase("agenda.summary.respond_busy", what=what)
    if op == DELETE:
        return phrase("agenda.summary.delete", what=what, name=inert(name, NAME_SHOWN))
    return phrase("agenda.summary.edit", what=what, name=inert(name, NAME_SHOWN))


@AGENDA.tool("agenda_edit", acts=True, description=phrase("agenda.tools.edit.description"),
             label=phrase("agenda.tools.edit.label"), args=EditArgs, bundle=BUNDLE, episodes=EPISODES,
             max_calls_per_episode=WRITE_CALLS, owner_only=True, owned=offered, outside=True, needs="agenda")
async def agenda_edit(args: EditArgs, ctx: Any) -> Any:
    desk = _open(ctx)
    if isinstance(desk, ToolResult):
        return desk
    found = _event(desk, args.ref)
    if isinstance(found, ToolResult):
        return found
    event, occurrence = found
    h = desk.here[event.calendar]
    refused = _writable(desk, event.calendar, h.write)
    if refused is not None:
        return refused
    if event.origin or (event.organizer is not None and not event.organizer.me and event.response):
        return _refused(phrase("agenda.tools.invited"))
    if event.private and not h.owned:
        return _refused(phrase("agenda.tools.private"))
    change: dict[str, Any] = {}
    if args.title.strip():
        change["title"] = args.title.strip()
    if args.location is not None:
        change["location"] = args.location.strip()
    if args.description is not None:
        change["description"] = args.description.strip()
    if args.start.strip() or args.end.strip() or args.minutes is not None or args.all_day is not None:
        current = _current(event, occurrence)
        tz = zone_of(current.zone) if current.zone else desk.tz
        span = span_of(args.start, args.end, args.minutes, bool(args.all_day), tz, current=current)
        if not isinstance(span, Span):
            return _refused(span or phrase("agenda.tools.bad_time"))
        change["span"] = _span_json(span)
    if args.invite or args.uninvite:
        added = _invitees(desk, event.calendar, args.invite)
        if isinstance(added, ToolResult):
            return added
        gone = {a.strip().lower() for a in args.uninvite}
        kept = [_participant_json(x) for x in event.participants if x.me or (x.address or "").lower() not in gone]
        known = {x["address"] for x in kept if x["address"]} | {x["person"] for x in kept if x["person"]}
        kept += [a for a in added if a["address"] not in known and (a["person"] or "") not in known]
        change["invite"] = kept
    payload: dict[str, Any] = {"op": EDIT, **_target_of(desk, event, occurrence), "scope": _scope(
        event, occurrence, args.scope), "change": change}
    remind = _remind_choice(args.remind)
    if remind is not None:
        payload["remind"] = remind
    if not change and remind is None:
        return _refused(phrase("agenda.tools.no_change"))
    summary = phrase("agenda.summary.edit", what=_what(desk, event, occurrence),
                     name=inert(desk.calendars[event.calendar].name or event.calendar, NAME_SHOWN))
    return await propose(desk, event.calendar, h.write, payload, summary, starts=_starts(desk, event, occurrence))


class DeleteArgs(BaseModel):
    ref: str = Field(min_length=3, max_length=40, description=phrase("agenda.tools.args.ref"))
    scope: Scope = Field(default="un", description=phrase("agenda.tools.args.scope"))


@AGENDA.tool("agenda_delete", acts=True, description=phrase("agenda.tools.delete.description"),
             label=phrase("agenda.tools.delete.label"), args=DeleteArgs, bundle=BUNDLE, episodes=EPISODES,
             max_calls_per_episode=WRITE_CALLS, owner_only=True, owned=offered, outside=True, needs="agenda")
async def agenda_delete(args: DeleteArgs, ctx: Any) -> Any:
    desk = _open(ctx)
    if isinstance(desk, ToolResult):
        return desk
    found = _event(desk, args.ref)
    if isinstance(found, ToolResult):
        return found
    event, occurrence = found
    h = desk.here[event.calendar]
    refused = _writable(desk, event.calendar, h.write)
    if refused is not None:
        return refused
    if event.private and not h.owned:
        return _refused(phrase("agenda.tools.private"))
    scope = _scope(event, occurrence, args.scope)
    summary = phrase("agenda.summary.delete", what=_what(desk, event, occurrence),
                     name=inert(desk.calendars[event.calendar].name or event.calendar, NAME_SHOWN))
    return await propose(desk, event.calendar, h.write,
                         {"op": DELETE, **_target_of(desk, event, occurrence), "scope": scope}, summary,
                         starts=_starts(desk, event, occurrence))


class RespondArgs(BaseModel):
    ref: str = Field(min_length=3, max_length=40, description=phrase("agenda.tools.args.ref"))
    answer: Answer = Field(description=phrase("agenda.tools.args.answer"))
    comment: str = Field(default="", max_length=500, description=phrase("agenda.tools.args.comment"))
    scope: Literal["un", "tous"] = Field(default="tous", description=phrase("agenda.tools.args.respond_scope"))
    why: str = Field(default="", max_length=WHY_SHOWN, description=phrase("agenda.tools.args.why"))


#: une réponse en mots → celle du port
ANSWERS = {"oui": YES, "peut": MAYBE, "non": NO}


@AGENDA.tool("agenda_respond", acts=True, description=phrase("agenda.tools.respond.description"),
             label=phrase("agenda.tools.respond.label"), args=RespondArgs, bundle=BUNDLE, episodes=ANSWERING,
             max_calls_per_episode=WRITE_CALLS, owner_only=True, owned=offered, outside=True, needs="agenda")
async def agenda_respond(args: RespondArgs, ctx: Any) -> Any:
    desk = _open(ctx)
    if isinstance(desk, ToolResult):
        return desk
    found = _event(desk, args.ref)
    if isinstance(found, ToolResult):
        return found
    event, occurrence = found
    h = desk.here[event.calendar]
    if not event.response:
        return _refused(phrase("agenda.tools.not_invited"))
    if desk.task is not None and (event.calendar, event.uid, event.original) != (
            desk.task.calendar, desk.task.uid, desk.task.original):
        return _refused(phrase("agenda.tools.other_invitation"))  # sa tâche ne répond qu'à son invitation
    refused = _writable(desk, event.calendar, h.respond)
    if refused is not None:
        return refused
    if event.private and not h.owned:  # comme la supprimer, qui revient à la refuser
        return _refused(phrase("agenda.tools.private"))
    scope = ONE if args.scope == "un" and occurrence else ALL
    summary = phrase("agenda.summary.respond", answer=phrase(f"agenda.words.answer.{ANSWERS[args.answer]}"),
                     what=_what(desk, event, occurrence))
    return await propose(desk, event.calendar, h.respond,
                         {"op": RESPOND, **_target_of(desk, event, occurrence), "scope": scope,
                          "response": ANSWERS[args.answer], "comment": args.comment.strip(),
                          "why": args.why.strip()}, summary,
                         starts=_starts(desk, event, occurrence if scope == ONE else ""))


# ── ce qui partirait, et ce qui part ─────────────────────────────────────


def _version(e: Event | None) -> list[Any]:
    """Ce qui, changé ailleurs entre l'aperçu et l'accord, fait que ce n'est plus le même accord."""
    if e is None:
        return []
    return [e.etag, e.sequence, e.updated, e.span.start, e.span.end, e.title, e.location, e.status, e.response,
            e.recurrence.rule if e.recurrence is not None else ""]


def _row(store: Any, args: Mapping[str, Any]) -> Event | None:
    calendar, uid = str(args.get("calendar") or ""), str(args.get("uid") or "")
    found = store.find(calendar, uid, str(args.get("original") or "")) if uid else None
    if found is None and str(args.get("event") or "").isdigit():
        found = store.event(int(args["event"]))
        if found is not None and (found.calendar != calendar or found.uid != uid):
            found = None
    return found


def _invited_line(raw: Any) -> str:
    """Qui sera invité, en mots (leurs adresses, rendues inertes ; une personne qui a un compte le reçoit dans son
    agenda)."""
    people = [inert(p.address or p.name or p.person, NAME_SHOWN) for p in _participants(raw) if not p.me]
    return phrase("agenda.preview.invite", who=", ".join(people) or "—")


def _remind_line(value: Any) -> str:
    if not value:
        return phrase("agenda.preview.remind_agenda")
    return phrase("agenda.preview.remind", delay=REMINDER_WORDS.get(str(value), str(value)))


def _change_lines(change: Mapping[str, Any], tz: ZoneInfo) -> list[str]:
    out = []
    if "span" in change:
        out.append(phrase("agenda.preview.when", when=when_words(_span_from(change["span"]), tz)))
    if "title" in change:
        out.append(phrase("agenda.preview.title", title=inert(str(change["title"]), TITLE_SHOWN)))
    if "location" in change:
        out.append(phrase("agenda.preview.where", place=inert(str(change["location"]), PLACE_SHOWN) or "—"))
    if "description" in change:
        out.append(phrase("agenda.preview.note", text=inert(str(change["description"]), TEXT_SHOWN) or "—"))
    if "invite" in change:
        out.append(_invited_line(change["invite"]))
    return out


async def preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview:
    """Exactement ce qui partirait — quoi, quand, dans quel agenda, ce qui change — et ce qui l'empêcherait de partir
    tel quel : l'agenda masqué, parti ou en lecture seule, l'événement disparu. L'empreinte porte aussi l'état de
    l'événement touché : changé ailleurs entre-temps, ce n'est plus le même accord."""
    store, providers, frame_of = ports.get("agenda"), ports.get("agenda_providers"), ports.get("frame")
    op, calendar = str(args.get("op") or ""), str(args.get("calendar") or "")
    if store is None or providers is None or frame_of is None or op not in OPS:
        return Preview(phrase("agenda.preview.unavailable"), "", blocked=phrase("agenda.preview.unavailable"))
    frame = frame_of()
    tz = frame.env.tz_of(frame.root)
    cal = store.calendar(calendar)
    row = _row(store, args) if op != CREATE else None
    occurrence = str(args.get("occurrence") or "")
    name = inert(cal.name or calendar, NAME_SHOWN) if cal is not None else inert(calendar, NAME_SHOWN)
    keep = KEEP_WORDS.get(str(args.get("keep") or ""), "—")
    lines: list[str] = []
    if op == CREATE:
        draft = args.get("draft") or {}
        lines.append(phrase("agenda.preview.create", name=name))
        lines.append(phrase("agenda.preview.title", title=inert(str(draft.get("title") or ""), TITLE_SHOWN)))
        lines.append(phrase("agenda.preview.when", when=when_words(_span_from(draft.get("span") or {}), tz)))
        if draft.get("location"):
            lines.append(phrase("agenda.preview.where", place=inert(str(draft["location"]), PLACE_SHOWN)))
        if draft.get("description"):
            lines.append(phrase("agenda.preview.note", text=inert(str(draft["description"]), TEXT_SHOWN)))
        if draft.get("rule"):
            lines.append(phrase("agenda.preview.repeats", rule=str(draft["rule"])))
        if draft.get("invite"):
            lines.append(_invited_line(draft["invite"]))
    elif row is not None:
        # qui décide lit ce qu'il approuve : son propre rendez-vous privé, avec son titre ; un autre, « Occupé »
        decider = str(args.get(rt.DECIDER) or "")
        owns = bool(decider) and level_of(params_of(frame), frame, person_of(frame, decider), calendar) == OWNED
        shown = masked(row) if row.private and not owns else row
        title = inert(shown.title, TITLE_SHOWN) if shown.title.strip() else phrase("agenda.words.busy")
        what = phrase("agenda.words.event", title=title, when=when_words(_current(row, occurrence), tz))
        scope = phrase(f"agenda.preview.scope.{args.get('scope') or ALL}") if (row.recurring or row.original) else ""
        if op == EDIT:
            lines.append(phrase("agenda.preview.edit", name=name, what=what, scope=scope))
            lines += _change_lines(args.get("change") or {}, tz)
        elif op == DELETE:
            lines.append(phrase("agenda.preview.delete", name=name, what=what, scope=scope))
        else:
            lines.append(phrase("agenda.preview.respond", name=name, what=what,
                                answer=phrase(f"agenda.words.answer.{args.get('response') or YES}")))
            if args.get("comment"):
                lines.append(phrase("agenda.preview.comment", text=inert(str(args["comment"]), TEXT_SHOWN)))
            if args.get("why"):
                lines.append(phrase("agenda.preview.why", text=inert(str(args["why"]), WHY_SHOWN)))
    if "remind" in args:
        lines.append(_remind_line(args.get("remind")))
    lines.append(phrase("agenda.preview.keep", keep=keep))
    blocked = ""
    if cal is None:
        blocked = phrase("agenda.preview.gone")
    elif not hers(params_of(frame), calendar):
        blocked = phrase("agenda.preview.hidden")
    elif not cal.writable:
        blocked = phrase("agenda.preview.read_only", name=name)
    elif op != CREATE and row is None:
        blocked = phrase("agenda.preview.event_gone")
    elif rt.arg_int(args, "starts") and frame.now >= rt.arg_int(args, "starts"):
        blocked = phrase("agenda.preview.begun")
    elif args.get("shared") and not reaches(params_of(frame).shares.get(calendar, {}).get(str(args["shared"]), ""),
                                            SHARE_USE if op == RESPOND else SHARE_PREPARE):
        blocked = phrase("agenda.preview.unshared")
    pinned = {k: args.get(k) for k in (*PINNED, rt.DECIDER)}
    digest = hashlib.sha256(canonical_json({"pinned": pinned, "state": _version(row)}).encode()).hexdigest()[:32]
    return Preview("\n".join(lines), digest, blocked)


def _draft(args: Mapping[str, Any], now: int) -> EventDraft:
    raw = args.get("draft") or {}
    return EventDraft(str(raw.get("title") or ""), _span_from(raw.get("span") or {}),
                      location=str(raw.get("location") or ""), description=str(raw.get("description") or ""),
                      rule=str(raw.get("rule") or ""), participants=_participants(raw.get("invite")),
                      added=AddedBy(BY_HER, str(args.get("ref") or ""), now))


def _change(args: Mapping[str, Any]) -> EventChange | None:
    """Ce qui change chez le fournisseur ; ``None`` : rien (seulement « Mika te le rappelle », qui reste ici)."""
    raw = args.get("change") or {}
    if not raw:
        return None
    return EventChange(title=raw.get("title"), location=raw.get("location"), description=raw.get("description"),
                       span=_span_from(raw["span"]) if "span" in raw else None,
                       participants=_participants(raw["invite"]) if "invite" in raw else None)


@AGENDA.capability("write", description=phrase("agenda.write.description"), preview=preview)
async def write(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    """Écrire dans un agenda ce que l'aperçu montrait : chez le fournisseur, la marque de Mika sur ce qu'elle ajoute,
    puis la copie relue. Un refus se dit en mots (``AgendaError``) ; une autre panne, traduite."""
    store, providers, frame_of = ports.get("agenda"), ports.get("agenda_providers"), ports.get("frame")
    if store is None or providers is None or frame_of is None:
        return False, phrase("agenda.preview.unavailable")
    frame = frame_of()
    p = params_of(frame)
    op, calendar = str(args.get("op") or ""), str(args.get("calendar") or "")
    if not hers(p, calendar):
        return False, phrase("agenda.preview.hidden")
    account, _local = split_calendar_key(calendar)
    conn = providers.connection(account)
    provider = providers.of(conn.kind) if conn is not None else None
    cal = store.calendar(calendar)
    if conn is None or provider is None or cal is None:
        return False, phrase("agenda.preview.gone")
    row = _row(store, args) if op != CREATE else None
    if op != CREATE and row is None:
        return False, phrase("agenda.preview.event_gone")
    occurrence, scope = str(args.get("occurrence") or ""), str(args.get("scope") or ALL)
    kept: list[Event] = []
    try:
        if op == CREATE:
            kept.append(await provider.create(conn, cal, _draft(args, frame.now)))
        elif op == EDIT:
            assert row is not None
            change = _change(args)
            if change is not None:
                kept.append(await provider.edit(conn, cal, row, occurrence, change, scope))
        elif op == DELETE:
            assert row is not None
            await provider.delete(conn, cal, row, occurrence, scope)
        elif op == RESPOND:
            assert row is not None
            kept.append(await provider.respond(conn, cal, row, occurrence, str(args.get("response") or YES), scope,
                                               str(args.get("comment") or "")))
        else:
            return False, phrase("agenda.preview.unavailable")
    except AgendaError as exc:
        await _reread(store, provider, conn, calendar, p, frame.now)  # un conflit, un événement disparu : relu
        return False, (str(exc) or phrase("agenda.write.refused"))[:300]
    except Exception as exc:  # noqa: BLE001 — un fournisseur en panne, quelle qu'elle soit, se dit en mots
        return False, describe_error(exc)[:300]
    await _reread(store, provider, conn, calendar, p, frame.now, kept)
    uid = kept[0].uid if kept else (row.uid if row is not None else "")
    if "remind" in args and op in (CREATE, EDIT):  # « Mika te le rappelle » : dans la base seulement
        target = kept[0] if kept else row
        if target is not None:
            store.remind(calendar, target.uid, target.original, str(args.get("remind") or ""))
    return True, phrase("agenda.write.done", uid=uid)


async def _reread(store: Any, provider: Any, conn: Any, calendar: str, p: Any, now: int,
                  kept: Sequence[Event] = ()) -> None:
    """La copie relue après une écriture ; une panne de la relecture ne défait pas l'écriture (la synchronisation
    suivante la reprendra)."""
    try:
        await reread(store, provider, conn, calendar, p, now, kept)
    except Exception as exc:  # noqa: BLE001 — la relecture est un surcroît : l'écriture, elle, est faite ou refusée
        log.warning("agenda : la copie de %s n'a pas pu être relue : %s", calendar[:60], describe_error(exc))


@AGENDA.effect(rt.EFFECT_EXECUTED)
async def _settle(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Ce qu'elle avait proposé d'écrire est fait, ou a raté : elle le sait (``agenda.written``), ce qu'elle a fait en
    mots et, raté, les mots du fournisseur — des contenus, la personne en face pour sujet."""
    frame_of, store = ports.get("frame"), ports.get("store")
    if frame_of is None:
        return None
    w = frame_of().state(OWNER).writes.get(ev.data.proposal)
    if w is None or w.status == DONE or w.why_ref:
        return None
    said = (store.content([w.summary_ref]).get(w.summary_ref) or "") if store is not None and w.summary_ref else ""
    uid = ""
    if ev.data.ok and (got := UID_IN_RESULT.search(ev.data.result or "")):
        uid = got.group(1)
    why = None if ev.data.ok else Content.of((ev.data.result or phrase("agenda.write.refused"))[:300],
                                             level=int(Sensitivity.PERSONAL))
    return [WRITTEN.draft(proposal=w.proposal, ok=ev.data.ok, op=w.op, calendar=w.calendar,
                          summary=Content.of((said or phrase("agenda.write.lost"))[:400],
                                             level=int(Sensitivity.PERSONAL)),
                          uid=uid or w.uid, occurrence=w.occurrence, why=why,
                          about=tuple(dict.fromkeys(x for x in (w.target, w.decider) if x)),
                          dedupe_key=f"agenda-ecrit:{w.proposal}")]


__all__ = ["ANSWERING", "ANSWERS", "EPISODES", "PINNED", "READING", "REF", "event_line", "free_slots", "invitation_of",
           "local_span", "offered", "period", "preview", "propose", "span_of", "task_decider", "when_words", "write"]
