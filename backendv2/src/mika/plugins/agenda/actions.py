"""Ce qu'une personne fait de ses agendas depuis son espace (ADR 0309, lot 4) : les actions de la console
(``@AGENDA.action``), au nom de qui agit (``ctx.by``), que l'API par personne appelle (``app/domains/agenda/api.py``) —
journalisées, dédoublonnées et auditées comme toute action (``moi.agenda.<action>``).

- **À qui.** Chaque action relit ce que la personne qui agit a de l'agenda visé (``level_of``) : le sien (à son nom, ou
  « à toi » pour une de ses propriétaires, la règle de ``vocab.ownership``) ou un partage. Créer, modifier, supprimer,
  dupliquer, répondre à une invitation demandent le sien ou « s'en servir » (la règle du courrier et de Teams : un
  partage qui s'en sert fait comme le propriétaire) ; régler « Mika te le rappelle » d'un événement, créer un agenda,
  synchroniser demandent d'en être le propriétaire (un opérateur synchronise aussi, depuis la console). Un agenda qui
  ne lui est pas ouvert — masqué, sous un compte décoché, ou d'une autre — n'existe pas pour elle. Un événement privé
  d'une autre personne (« Occupé ») ne se modifie, ne se supprime ni ne se copie avec ses mots.
- **Écrire** part chez le fournisseur tout de suite, puis la copie se relit (``sync.reread``) ; un refus du
  fournisseur (un conflit, un événement disparu, une invitation qu'on n'organise pas) se dit en mots. Rien n'est
  journalisé de l'événement lui-même (le monde, pas sa vie) : seulement l'audit du geste.
- **Décider de ce que Mika propose** (``agenda.write``) : seulement qui en décide (son adresse est celle de la
  proposition) — l'accepter tel qu'il a été lu (``seen``), le refuser, ou l'ajouter soi-même avec ses changements
  (« Modifier ») : son événement est marqué « ajouté par Mika », elle l'apprend (``agenda.written``, ``edited``) et sa
  proposition est retirée.
- **Synchroniser maintenant** : ``agenda.sync_asked``, qui réveille ``agenda.sync``.
- **Les rappels du fournisseur** (lot 6 : ``reminders``, « notification:10 », « email:1440 ») partent avec l'événement
  chez Google, Outlook ou le serveur CalDAV, selon ce qu'il sait (``Abilities.reminders``) ; l'agenda du système n'en a
  pas (« Mika te le rappelle » s'en charge). Une invitation garde les siens : ce sont les seuls qu'on y change.
- **Renommer un agenda** (son propriétaire) : celui du système change de nom pour de bon, un agenda branché prend un
  nom à lui dans Mika (``AgendaPort.rename``).

La console (lot 5) ne crée, ne modifie ni ne répond jamais à la place de quelqu'un (ADR 0309) : ces actions
n'atteignent que les agendas de qui agit.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.operate import Decision, Done, Refused
from mika.plugins.agenda import (
    AGENDA,
    CREATE,
    SYNC_ASKED,
    WAITING,
    WRITTEN,
    AgendaParams,
    AgendaState,
    Written,
    hers,
    owner,
    params_of,
)
from mika.plugins.agenda.sync import reread
from mika.ports.agenda import (
    ALERT_METHODS,
    ALERT_MINUTES_MAX,
    ALERTS_MAX,
    ALL,
    BY_HER,
    FOLLOWING,
    MAYBE,
    NO,
    ONE,
    REMINDERS,
    SYSTEM,
    YES,
    AddedBy,
    AgendaError,
    Alert,
    Event,
    EventChange,
    EventDraft,
    Participant,
    Span,
    alerts_of,
    instance,
    masked,
    rule_parts,
    split_calendar_key,
    system_person,
    us_of,
    whole_days,
    zone_of,
)
from mika.ports.errors import describe_error
from mika.vocab.access import PERSON, SHARE_USE, reaches
from mika.vocab.ownership import OWNED, holds
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

#: un champ de modification laissé tel quel
KEEP = "__inchangé__"
#: les bornes d'un événement : un titre, un lieu, une description, un lien, un mot de réponse
TITLE_MAX, PLACE_MAX, TEXT_MAX, LINK_MAX, COMMENT_MAX = 300, 300, 8000, 1000, 500
#: au plus tant de participantes ; un événement minuté dure au plus tant de jours, une journée entière tant
INVITED_MAX, TIMED_DAYS, WHOLE_DAYS = 100, 31, 366
#: une adresse à inviter
ADDRESS = re.compile(r"^[^@\s<>\"',;]{1,64}@[^@\s<>\"',;]{1,255}$")
#: une heure locale (``AAAA-MM-JJTHH:MM``, secondes permises) et une date
LOCAL_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: une règle de répétition qu'un agenda écrit (RFC 5545) : ses parties et leur forme
RULE_PARTS = {"FREQ": re.compile(r"^(DAILY|WEEKLY|MONTHLY|YEARLY)$"), "INTERVAL": re.compile(r"^[1-9]\d{0,2}$"),
              "COUNT": re.compile(r"^[1-9]\d{0,3}$"), "UNTIL": re.compile(r"^\d{8}(T\d{6}Z?)?$"),
              "BYDAY": re.compile(r"^([+-]?\d{0,2}(MO|TU|WE|TH|FR|SA|SU))(,[+-]?\d{0,2}(MO|TU|WE|TH|FR|SA|SU))*$"),
              "BYMONTHDAY": re.compile(r"^-?\d{1,2}(,-?\d{1,2})*$"), "BYMONTH": re.compile(r"^\d{1,2}(,\d{1,2})*$"),
              "BYSETPOS": re.compile(r"^-?\d{1,3}(,-?\d{1,3})*$"), "WKST": re.compile(r"^(MO|TU|WE|TH|FR|SA|SU)$")}
RULE_MAX = 300
#: les réponses, en mots de l'API → celles du port ; les portées
ANSWERS = {"oui": YES, "peut": MAYBE, "non": NO}
SCOPES = {"un": ONE, "suivants": FOLLOWING, "tous": ALL}
#: « Mika te le rappelle » : ses valeurs (vide : le choix de l'agenda)
REMIND_VALUES = ("", *(k for k, _ in REMINDERS))
#: un rappel du fournisseur tel qu'une action le reçoit : « notification:10 », « email:1440 »
ALERT = re.compile(r"^(notification|email):(\d{1,5})$")

log = logging.getLogger("mika.agenda")

GONE = "Cet agenda n'existe pas."
NO_EVENT = "Cet événement n'existe pas."
TOO_LOW = "Cet agenda t'est partagé sans t'en servir : tu le lis, sans y écrire."
ONLY_OWNER = "Seul son propriétaire règle cet agenda."
PRIVATE = "Cet événement est privé : seul son propriétaire le change."
INVITED = "C'est une invitation : seul qui l'organise la modifie ; tu peux y répondre."


# ── qui agit, et ce qu'elle a de l'agenda ─────────────────────────────────


def person_of(frame: Frame, by: str) -> str:
    """La personne derrière l'adresse qui agit (sa clé), telle que l'identité la relie maintenant."""
    return str(frame.get(identity_c.PERSON(by)) or by)


def is_owner(frame: Frame, person: str) -> bool:
    """Une de ses propriétaires : ce qui est « à toi » (sans propriétaire nommé) est à elle."""
    return person in set(frame.get(identity_c.OWNERS) or ())


def level_of(p: AgendaParams, frame: Frame, person: str, calendar: str) -> str:
    """Ce que cette personne (sa clé) a de cet agenda dans son espace : ``OWNED`` (le sien), le niveau d'un partage,
    ou vide. Un agenda partagé masqué, ou sous un compte décoché, n'est plus ouvert qu'à son propriétaire."""
    account, _local = split_calendar_key(calendar)
    if not account:
        return ""
    if holds(owner(p, account), PERSON + person, owner=is_owner(frame, person)):
        return OWNED
    level = p.shares.get(calendar, {}).get(PERSON + person, "")
    return level if level and hers(p, calendar) else ""


def account_level(p: AgendaParams, frame: Frame, person: str, account: str) -> str:
    """Ce que cette personne a d'un compte : ``OWNED`` s'il est à elle (son compte du système compris), sinon rien."""
    return OWNED if holds(owner(p, account), PERSON + person, owner=is_owner(frame, person)) else ""


def operator(frame: Frame, by: str) -> bool:
    seen = frame.get(identity_c.IDENTITY(by))
    return bool(seen.authenticated and seen.operator)


def handles_of(frame: Frame, by: str) -> set[str]:
    """Les adresses de la personne qui agit : ce qu'une proposition nomme pour qui en décide."""
    return {by, *(frame.get(identity_c.HANDLES(person_of(frame, by))) or ())}


class _Desk:
    """Ce qu'une écriture lit : la base, les fournisseurs, la personne qui agit et ce qu'elle a de l'agenda."""

    def __init__(self, s: AgendaState, frame: Frame, ctx: Any, calendar: str, need: str) -> None:
        self.frame, self.ctx = frame, ctx
        self.store, self.providers = ctx.ports.get("agenda"), ctx.ports.get("agenda_providers")
        if self.store is None or self.providers is None:
            raise Refused("L'agenda n'est pas branché sur ce serveur.")
        self.p = params_of(frame)
        self.person = person_of(frame, ctx.by)
        self.calendar = calendar
        self.level = level_of(self.p, frame, self.person, calendar)
        self.cal = self.store.calendar(calendar) if calendar else None
        if not self.level or self.cal is None:
            raise Refused(GONE)
        if need == OWNED and self.level != OWNED:
            raise Refused(ONLY_OWNER)
        if need == SHARE_USE and not (self.level == OWNED or reaches(self.level, SHARE_USE)):
            raise Refused(TOO_LOW)
        account, _local = split_calendar_key(calendar)
        self.conn = self.providers.connection(account)
        self.provider = self.providers.of(self.conn.kind) if self.conn is not None else None

    @property
    def owned(self) -> bool:
        return self.level == OWNED

    def writable(self) -> None:
        """Ce qui empêche d'écrire dans cet agenda : en lecture seule chez son fournisseur, un abonnement, un compte
        décoché, une sorte sans fournisseur."""
        account, _local = split_calendar_key(self.calendar)
        if self.conn is None or self.provider is None:
            raise Refused("Ce compte d'agenda n'est pas branché sur ce serveur.")
        if not self.conn.enabled or account in self.p.accounts_off:
            raise Refused("Ce compte d'agenda est décoché : réactive-le dans Paramètres › Agendas pour y écrire.")
        if not self.cal.writable or not self.provider.abilities(self.conn).write:
            raise Refused("Cet agenda est en lecture seule : on n'y écrit pas d'ici.")

    def event(self, event_id: int) -> Event:
        found = self.store.event(event_id) if event_id > 0 else None
        if found is None or found.calendar != self.calendar:
            raise Refused(NO_EVENT)
        return found

    def visible(self, e: Event) -> Event:
        """L'événement tel qu'elle le voit : un privé d'une autre personne, « Occupé »."""
        return masked(e) if e.private and not self.owned else e

    def zone(self) -> str:
        return self.cal.zone or str(getattr(self.frame.env.tz_of(self.frame.root), "key", "") or "")

    async def settle(self, kept: list[Event]) -> None:
        """La copie relue après une écriture ; une panne de la relecture ne défait pas l'écriture (la synchronisation
        suivante la reprendra)."""
        assert self.provider is not None and self.conn is not None
        try:
            await reread(self.store, self.provider, self.conn, self.calendar, self.p, self.ctx.now, kept)
        except Exception as exc:  # noqa: BLE001 — la relecture est un surcroît : l'écriture, elle, est faite
            log.warning("agenda : la copie de %s n'a pas pu être relue : %s", self.calendar[:60], describe_error(exc))

    def made(self, e: Event) -> dict[str, Any]:
        """Ce qu'une écriture rend au client : l'événement tel que la copie le range (sa ligne, son UID)."""
        row = self.store.find(self.calendar, e.uid, e.original)
        return {"calendar": self.calendar, "uid": e.uid, "event": row.id if row is not None else 0}

    async def refused(self, exc: AgendaError) -> Refused:
        """Un refus du fournisseur, en mots ; la copie se relit (un conflit, un événement disparu)."""
        await self.settle([])
        return Refused((str(exc) or "Le fournisseur a refusé cette écriture.")[:300])


def _failed(exc: Exception) -> Refused:
    return Refused(f"L'agenda n'a pas répondu : {describe_error(exc)}"[:300])


# ── ce qu'on écrit ────────────────────────────────────────────────────────


def _text(value: str, limit: int, field: str) -> str:
    text = value.strip()
    if len(text) > limit:
        raise Refused(f"{limit} caractères au plus.", {field: f"{limit} caractères au plus"})
    return text


def _local(text: str, zone: str, field: str) -> datetime:
    if not LOCAL_TIME.fullmatch(text):
        raise Refused("Une heure s'écrit AAAA-MM-JJTHH:MM.", {field: "AAAA-MM-JJTHH:MM"})
    try:
        return datetime.fromisoformat(text.replace(" ", "T")).replace(tzinfo=zone_of(zone))
    except ValueError:
        raise Refused("Cette heure n'existe pas.", {field: "une heure qui existe"}) from None


def _day(text: str, field: str) -> date:
    if not DAY.fullmatch(text):
        raise Refused("Une date s'écrit AAAA-MM-JJ.", {field: "AAAA-MM-JJ"})
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise Refused("Cette date n'existe pas.", {field: "une date qui existe"}) from None


def span_of(start: str, end: str, all_day: bool, zone: str) -> Span:
    """Quand : une journée entière, du premier jour au dernier (compris : ``end`` vide, un seul jour) ; sinon de
    ``start`` à ``end`` (heures locales du fuseau ``zone`` ; ``end`` vide : une heure)."""
    start, end = start.strip(), end.strip()
    if all_day:
        first = _day(start[:10], "start")
        last = _day(end[:10], "end") if end else first
        if last < first:
            raise Refused("La fin vient avant le début.", {"end": "après le début"})
        if (last - first).days >= WHOLE_DAYS:
            raise Refused(f"Un événement dure au plus {WHOLE_DAYS} jours.", {"end": f"{WHOLE_DAYS} jours au plus"})
        return whole_days(first.isoformat(), last.isoformat())
    begin = _local(start, zone, "start")
    finish = _local(end, zone, "end") if end else begin + timedelta(hours=1)
    if finish <= begin:
        raise Refused("La fin vient avant le début.", {"end": "après le début"})
    if finish - begin > timedelta(days=TIMED_DAYS):
        raise Refused(f"Un événement dure au plus {TIMED_DAYS} jours.", {"end": f"{TIMED_DAYS} jours au plus"})
    return Span(us_of(begin), us_of(finish), zone)


def rule_of(text: str) -> str:
    """Une règle de répétition (RFC 5545, sans « RRULE: ») telle qu'un agenda l'écrit : ``FREQ`` quotidienne,
    hebdomadaire, mensuelle ou annuelle, et ses parties connues ; vide : il ne se répète pas."""
    text = text.strip().removeprefix("RRULE:").upper()
    if not text:
        return ""
    parts = rule_parts(text)
    names = [k for k, _ in parts]
    bad = len(text) > RULE_MAX or "FREQ" not in names or len(set(names)) != len(names) \
        or ("COUNT" in names and "UNTIL" in names) \
        or any(k not in RULE_PARTS or not RULE_PARTS[k].fullmatch(v) for k, v in parts)
    if bad:
        raise Refused("Cette répétition ne se lit pas.", {"rule": "une règle RFC 5545 (FREQ=WEEKLY;BYDAY=MO…)"})
    return ";".join(f"{k}={v}" for k, v in parts)


def _remind(value: str) -> str:
    if value not in REMIND_VALUES:
        raise Refused("Un rappel inconnu.", {"remind": "vide, non, 15, 30, 60 ou veille"})
    return value


def alerts_arg(values: tuple[str, ...] | None) -> tuple[Alert, ...] | None:
    """Les rappels du fournisseur d'une action (« notification:10 », « email:1440 ») ; ``None`` : ceux de l'agenda
    chez lui (une création) ou tels quels (une modification)."""
    if values is None:
        return None
    out = []
    for raw in values:
        found = ALERT.fullmatch(raw.strip())
        if found is None or found.group(1) not in ALERT_METHODS or int(found.group(2)) > ALERT_MINUTES_MAX:
            raise Refused("Un rappel se dit « notification:10 » ou « email:1440 » (minutes avant, quatre semaines au "
                          "plus).", {"reminders": "notification ou email, et les minutes avant"})
        out.append(Alert(int(found.group(2)), found.group(1)))
    return alerts_of(out)


def _flag(value: str, field: str) -> bool | None:
    if value in ("", KEEP):
        return None
    if value not in ("oui", "non"):
        raise Refused("oui ou non.", {field: "oui ou non"})
    return value == "oui"


def invitees(frame: Frame, desk: _Desk, addresses: tuple[str, ...], kept: tuple[Participant, ...] = ()) \
        -> tuple[Participant, ...]:
    """Les participantes, par leurs adresses : celles qui y étaient gardent leur réponse ; dans un agenda du
    système, une personne qui a un compte est invitée par sa clé — l'invitation arrive dans son agenda à elle."""
    if len(addresses) > INVITED_MAX:
        raise Refused(f"{INVITED_MAX} participantes au plus.", {"invite": f"{INVITED_MAX} au plus"})
    known = {(x.address or "").lower(): x for x in kept if x.address and not x.me}
    system = desk.conn is not None and desk.conn.kind == SYSTEM
    out: dict[str, Participant] = {}
    for raw in addresses:
        address = raw.strip().lower()
        if not address:
            continue
        if not ADDRESS.fullmatch(address):
            raise Refused(f"« {raw[:80]} » n'est pas une adresse.", {"invite": "des adresses, nom@exemple.fr"})
        if address in known:
            out[address] = known[address]
            continue
        person = ""
        if system:
            found = str(frame.get(identity_c.PERSON(f"mail:{address}")) or "")
            if found and not found.startswith("mail:") and found != desk.person and any(
                    frame.get(identity_c.IDENTITY(h)).authenticated
                    for h in frame.get(identity_c.HANDLES(found)) or ()):
                person = found
        out[address] = Participant(address=address, person=person)
    me = tuple(x for x in kept if x.me)
    return (*me, *out.values())


class EventArgs(BaseModel):
    """Un événement tel qu'on le crée."""

    calendar: Annotated[str, Knob(label="Agenda", widget="hidden")] = Field(min_length=1, max_length=200)
    title: Annotated[str, Knob(label="Titre", advanced=False)] = Field(min_length=1, max_length=TITLE_MAX)
    start: Annotated[str, Knob(label="Début", help="AAAA-MM-JJTHH:MM, ou AAAA-MM-JJ pour une journée entière.",
                               advanced=False)] = Field(min_length=10, max_length=25)
    end: Annotated[str, Knob(label="Fin", help="Vide : une heure (une journée, pour une journée entière).",
                             advanced=False)] = Field(default="", max_length=25)
    all_day: Annotated[bool, Knob(label="Journée entière", advanced=False)] = False
    zone: Annotated[str, Knob(label="Fuseau", help="Vide : celui de l'agenda.")] = Field(default="", max_length=60)
    location: Annotated[str, Knob(label="Lieu", advanced=False)] = Field(default="", max_length=PLACE_MAX)
    description: Annotated[str, Knob(label="Description", widget="textarea")] = Field(default="", max_length=TEXT_MAX)
    conference: Annotated[str, Knob(label="Lien de visio")] = Field(default="", max_length=LINK_MAX)
    rule: Annotated[str, Knob(label="Répétition", help="Une règle RFC 5545 (FREQ=WEEKLY;BYDAY=MO) ; vide : une "
                                                      "fois.")] = Field(default="", max_length=RULE_MAX)
    invite: Annotated[tuple[str, ...], Knob(label="Participants", help="Leurs adresses.")] = \
        Field(default=(), max_length=INVITED_MAX)
    free: Annotated[bool, Knob(label="Afficher comme disponible")] = False
    private: Annotated[bool, Knob(label="Privé")] = False
    remind: Annotated[str, Knob(label="Elle te le rappelle", help="Vide : le choix de l'agenda.")] = \
        Field(default="", max_length=10)
    reminders: Annotated[tuple[str, ...] | None, Knob(
        label="Rappels du fournisseur", help="« notification:10 », « email:1440 » ; vide : ceux de l'agenda chez "
                                             "lui.")] = Field(default=None, max_length=ALERTS_MAX)


def _zone(text: str) -> str:
    """Un fuseau IANA donné (``Europe/Paris``) ; inconnu : refusé."""
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        raise Refused("Un fuseau inconnu.", {"zone": "un fuseau IANA (Europe/Paris)"}) from None
    return text


def _provider_alerts(desk: _Desk, alerts: tuple[Alert, ...] | None) -> tuple[Alert, ...] | None:
    """Des rappels du fournisseur pour cet agenda : refusés là où il n'en écrit pas (l'agenda du système : « Mika te le
    rappelle » s'en charge)."""
    if alerts and desk.provider is not None and desk.conn is not None and not desk.provider.abilities(desk.conn).reminders:
        raise Refused("Cet agenda n'envoie pas de rappel lui-même : c'est elle qui te le rappelle.",
                      {"reminders": "aucun rappel du fournisseur ici"})
    return alerts


def _draft(frame: Frame, desk: _Desk, args: EventArgs, added: AddedBy | None = None) -> EventDraft:
    zone = _zone(args.zone.strip()) if args.zone.strip() else desk.zone()
    return EventDraft(_text(args.title, TITLE_MAX, "title"), span_of(args.start, args.end, args.all_day, zone),
                      location=_text(args.location, PLACE_MAX, "location"),
                      description=_text(args.description, TEXT_MAX, "description"),
                      conference=_text(args.conference, LINK_MAX, "conference"), rule=rule_of(args.rule),
                      participants=invitees(frame, desk, args.invite), busy=not args.free, private=args.private,
                      reminders=_provider_alerts(desk, alerts_arg(args.reminders)), added=added)


async def _create(desk: _Desk, draft: EventDraft, remind: str) -> Event:
    if remind:
        _owner_reminds(desk)
    desk.writable()
    assert desk.provider is not None
    try:
        made = await desk.provider.create(desk.conn, desk.cal, draft)
    except AgendaError as exc:
        raise await desk.refused(exc) from None
    except Exception as exc:  # noqa: BLE001 — un fournisseur en panne, quelle qu'elle soit, se dit en mots
        raise _failed(exc) from None
    await desk.settle([made])
    if remind:
        desk.store.remind(desk.calendar, made.uid, made.original, remind)
    return made


def _owner_reminds(desk: _Desk) -> None:
    """« Mika te le rappelle » est à son propriétaire (ADR 0309, lot 4) : un partage qui s'en sert écrit dans l'agenda
    sans régler ce rappel, qui ferait prévenir le propriétaire par une initiative due."""
    if not desk.owned:
        raise Refused(ONLY_OWNER, {"remind": "seul son propriétaire règle ce rappel"})


def _where(desk: _Desk) -> str:
    return f"« {desk.cal.name or desk.calendar} »"


@AGENDA.action("creer", title="Ajouter un événement", args=EventArgs, emits=[],
               description="Il part tout de suite chez le fournisseur de l'agenda.")
async def _create_event(s: AgendaState, frame: Frame, args: EventArgs, ctx: Any) -> Done:
    desk = _Desk(s, frame, ctx, args.calendar, SHARE_USE)
    made = await _create(desk, _draft(frame, desk, args), _remind(args.remind))
    return Done(message=f"Ajouté à {_where(desk)}.", show=(desk.made(made),))


class EditArgs(BaseModel):
    """Ce qu'on change d'un événement : un champ laissé tel quel (``KEEP``) ne change pas."""

    calendar: Annotated[str, Knob(label="Agenda", widget="hidden")] = Field(min_length=1, max_length=200)
    event: Annotated[int, Knob(label="Événement", widget="hidden")] = Field(ge=1)
    occurrence: Annotated[str, Knob(label="Occurrence", widget="hidden")] = Field(default="", max_length=20)
    scope: Annotated[str, Knob(label="Portée", help="un, suivants ou tous.")] = Field(default="un", max_length=10)
    title: Annotated[str, Knob(label="Titre")] = Field(default=KEEP, max_length=TITLE_MAX)
    start: Annotated[str, Knob(label="Début")] = Field(default=KEEP, max_length=25)
    end: Annotated[str, Knob(label="Fin")] = Field(default=KEEP, max_length=25)
    all_day: Annotated[str, Knob(label="Journée entière", help="oui, non ; vide : telle quelle.")] = \
        Field(default="", max_length=3)
    zone: Annotated[str, Knob(label="Fuseau")] = Field(default=KEEP, max_length=60)
    location: Annotated[str, Knob(label="Lieu")] = Field(default=KEEP, max_length=PLACE_MAX)
    description: Annotated[str, Knob(label="Description", widget="textarea")] = Field(default=KEEP, max_length=TEXT_MAX)
    conference: Annotated[str, Knob(label="Lien de visio")] = Field(default=KEEP, max_length=LINK_MAX)
    rule: Annotated[str, Knob(label="Répétition", help="Vide : il ne se répète plus.")] = \
        Field(default=KEEP, max_length=RULE_MAX)
    invite: Annotated[tuple[str, ...] | None, Knob(label="Participants", help="Toutes leurs adresses.")] = \
        Field(default=None, max_length=INVITED_MAX)
    free: Annotated[str, Knob(label="Afficher comme disponible", help="oui, non ; vide : tel quel.")] = \
        Field(default="", max_length=3)
    private: Annotated[str, Knob(label="Privé", help="oui, non ; vide : tel quel.")] = Field(default="", max_length=3)
    remind: Annotated[str, Knob(label="Elle te le rappelle", help="Vide : le choix de l'agenda.")] = \
        Field(default=KEEP, max_length=12)
    reminders: Annotated[tuple[str, ...] | None, Knob(
        label="Rappels du fournisseur", help="Tous : « notification:10 », « email:1440 » ; aucun : une liste vide ; "
                                             "vide : tels quels.")] = Field(default=None, max_length=ALERTS_MAX)


def _target(desk: _Desk, event_id: int, occurrence: str) -> tuple[Event, str]:
    """La ligne visée et l'occurrence : une occurrence d'une série se nomme par sa clé (vide : la série) ; une
    exception est sa propre ligne ; un événement simple n'en a pas."""
    e = desk.event(event_id)
    if e.original:
        return e, e.original
    return e, occurrence.strip() if e.recurring else ""


def _scope(e: Event, occurrence: str, scope: str) -> str:
    if scope not in SCOPES:
        raise Refused("Une portée inconnue.", {"scope": "un, suivants ou tous"})
    if not occurrence or not (e.recurring or e.original):
        return ALL
    return SCOPES[scope]


def _current(e: Event, occurrence: str) -> Span:
    if occurrence and e.recurring and not e.original:
        return instance(e, occurrence).span
    return e.span


def _invited(e: Event) -> bool:
    """Une invitation : un événement qu'elle n'organise pas, où son compte est invité."""
    return bool(e.origin) or (e.organizer is not None and not e.organizer.me and bool(e.response))


def _change(frame: Frame, desk: _Desk, e: Event, occurrence: str, args: EditArgs) -> EventChange:
    changes: dict[str, Any] = {}
    if args.title != KEEP:
        changes["title"] = _text(args.title, TITLE_MAX, "title")
        if not changes["title"]:
            raise Refused("Un événement a un titre.", {"title": "un titre"})
    for name, limit in (("location", PLACE_MAX), ("description", TEXT_MAX), ("conference", LINK_MAX)):
        value = getattr(args, name)
        if value != KEEP:
            changes[name] = _text(value, limit, name)
    if args.start != KEEP or args.end != KEEP or args.zone != KEEP or args.all_day:
        if args.start == KEEP:
            raise Refused("Donne son début.", {"start": "requis quand on change le moment"})
        current = _current(e, occurrence)
        all_day = _flag(args.all_day, "all_day")
        all_day = current.all_day if all_day is None else all_day
        zone = (_zone(args.zone.strip()) if args.zone != KEEP and args.zone.strip() else "") or current.zone \
            or desk.zone()
        changes["span"] = span_of(args.start, "" if args.end == KEEP else args.end, all_day, zone)
    if args.rule != KEEP:
        changes["rule"] = rule_of(args.rule)
    if args.invite is not None:
        changes["participants"] = invitees(frame, desk, args.invite, e.participants)
    free, private = _flag(args.free, "free"), _flag(args.private, "private")
    if free is not None:
        changes["busy"] = not free
    if private is not None:
        changes["private"] = private
    alerts = _provider_alerts(desk, alerts_arg(args.reminders))
    if alerts is not None:
        changes["reminders"] = alerts
    return EventChange(**changes)


@AGENDA.action("modifier", title="Modifier un événement", args=EditArgs, emits=[],
               description="Cet événement, celui-ci et les suivants, ou tous : il part tout de suite chez le "
                           "fournisseur.")
async def _edit_event(s: AgendaState, frame: Frame, args: EditArgs, ctx: Any) -> Done:
    desk = _Desk(s, frame, ctx, args.calendar, SHARE_USE)
    e, occurrence = _target(desk, args.event, args.occurrence)
    if e.private and not desk.owned:
        raise Refused(PRIVATE)
    change = _change(frame, desk, e, occurrence, args)
    remind = _remind(args.remind) if args.remind != KEEP else None
    if remind is not None:  # avant toute écriture chez le fournisseur : rien ne part à moitié
        _owner_reminds(desk)
    if change == EventChange() and remind is None:
        return Done(message="Rien à changer.", tone="info")
    if change != EventChange():
        if _invited(e) and replace(change, reminders=None) != EventChange():
            raise Refused(INVITED)  # une invitation ne garde à elle que ses rappels
        desk.writable()
        assert desk.provider is not None
        try:
            got = await desk.provider.edit(desk.conn, desk.cal, e, occurrence, change, _scope(e, occurrence,
                                                                                               args.scope))
        except AgendaError as exc:
            raise await desk.refused(exc) from None
        except Exception as exc:  # noqa: BLE001 — un fournisseur en panne, quelle qu'elle soit, se dit en mots
            raise _failed(exc) from None
        await desk.settle([got])
        e = got
    if remind is not None:
        desk.store.remind(desk.calendar, e.uid, e.original, remind)
    return Done(message=f"Modifié dans {_where(desk)}.")


class TargetArgs(BaseModel):
    calendar: Annotated[str, Knob(label="Agenda", widget="hidden")] = Field(min_length=1, max_length=200)
    event: Annotated[int, Knob(label="Événement", widget="hidden")] = Field(ge=1)
    occurrence: Annotated[str, Knob(label="Occurrence", widget="hidden")] = Field(default="", max_length=20)
    scope: Annotated[str, Knob(label="Portée", help="un, suivants ou tous.")] = Field(default="un", max_length=10)


@AGENDA.action("supprimer", title="Supprimer un événement", args=TargetArgs, emits=[], danger=True,
               description="Il disparaît aussi chez le fournisseur ; supprimer une invitation, c'est la refuser.")
async def _delete_event(s: AgendaState, frame: Frame, args: TargetArgs, ctx: Any) -> Done:
    desk = _Desk(s, frame, ctx, args.calendar, SHARE_USE)
    e, occurrence = _target(desk, args.event, args.occurrence)
    if e.private and not desk.owned:
        raise Refused(PRIVATE)
    desk.writable()
    assert desk.provider is not None
    try:
        await desk.provider.delete(desk.conn, desk.cal, e, occurrence, _scope(e, occurrence, args.scope))
    except AgendaError as exc:
        raise await desk.refused(exc) from None
    except Exception as exc:  # noqa: BLE001 — un fournisseur en panne, quelle qu'elle soit, se dit en mots
        raise _failed(exc) from None
    await desk.settle([])
    return Done(message=f"Supprimé de {_where(desk)}.")


class DuplicateArgs(BaseModel):
    calendar: Annotated[str, Knob(label="Agenda", widget="hidden")] = Field(min_length=1, max_length=200)
    event: Annotated[int, Knob(label="Événement", widget="hidden")] = Field(ge=1)
    occurrence: Annotated[str, Knob(label="Occurrence", widget="hidden")] = Field(default="", max_length=20)
    to: Annotated[str, Knob(label="Dans l'agenda", help="Vide : le même.")] = Field(default="", max_length=200)


@AGENDA.action("dupliquer", title="Dupliquer un événement", args=DuplicateArgs, emits=[],
               description="Une copie de cette occurrence, dans le même agenda ou un autre où tu écris.")
async def _duplicate_event(s: AgendaState, frame: Frame, args: DuplicateArgs, ctx: Any) -> Done:
    source = _Desk(s, frame, ctx, args.calendar, "")
    e, occurrence = _target(source, args.event, args.occurrence)
    shown = source.visible(e)
    to = args.to.strip() or args.calendar
    desk = _Desk(s, frame, ctx, to, SHARE_USE)
    title = shown.title.strip() or phrase("agenda.words.busy")
    if to == args.calendar:
        title = f"{title} (copie)"
    draft = EventDraft(title[:TITLE_MAX], _current(e, occurrence), location=shown.location,
                       description=shown.description, conference=shown.conference, busy=e.busy,
                       private=e.private and source.owned and desk.owned)
    made = await _create(desk, draft, "")
    return Done(message=f"Copié dans {_where(desk)}.", show=(desk.made(made),))


class RespondArgs(BaseModel):
    calendar: Annotated[str, Knob(label="Agenda", widget="hidden")] = Field(min_length=1, max_length=200)
    event: Annotated[int, Knob(label="Événement", widget="hidden")] = Field(ge=1)
    occurrence: Annotated[str, Knob(label="Occurrence", widget="hidden")] = Field(default="", max_length=20)
    answer: Annotated[str, Knob(label="Réponse", help="oui, peut ou non.", advanced=False)] = \
        Field(min_length=2, max_length=4)
    comment: Annotated[str, Knob(label="Un mot", widget="textarea")] = Field(default="", max_length=COMMENT_MAX)
    scope: Annotated[str, Knob(label="Portée", help="un ou tous.")] = Field(default="tous", max_length=10)


@AGENDA.action("repondre", title="Répondre à une invitation", args=RespondArgs, emits=[],
               description="La réponse repart par l'agenda (Google, Outlook, CalDAV) vers qui l'organise.")
async def _respond(s: AgendaState, frame: Frame, args: RespondArgs, ctx: Any) -> Done:
    desk = _Desk(s, frame, ctx, args.calendar, SHARE_USE)
    e, occurrence = _target(desk, args.event, args.occurrence)
    if e.private and not desk.owned:
        raise Refused(PRIVATE)  # comme la supprimer, qui revient à la refuser
    if not e.response:
        raise Refused("Ce n'est pas une invitation : il n'y a rien à répondre.")
    if args.answer not in ANSWERS:
        raise Refused("Une réponse inconnue.", {"answer": "oui, peut ou non"})
    if args.scope not in ("un", "tous"):
        raise Refused("Une portée inconnue.", {"scope": "un ou tous"})
    desk.writable()
    assert desk.provider is not None
    scope = ONE if args.scope == "un" and occurrence else ALL
    try:
        got = await desk.provider.respond(desk.conn, desk.cal, e, occurrence, ANSWERS[args.answer], scope,
                                          _text(args.comment, COMMENT_MAX, "comment"))
    except AgendaError as exc:
        raise await desk.refused(exc) from None
    except Exception as exc:  # noqa: BLE001 — un fournisseur en panne, quelle qu'elle soit, se dit en mots
        raise _failed(exc) from None
    await desk.settle([got])
    said = {"oui": "Accepté", "peut": "Répondu peut-être", "non": "Refusé"}[args.answer]
    return Done(message=f"{said} : la réponse est partie.")


class RemindArgs(BaseModel):
    calendar: Annotated[str, Knob(label="Agenda", widget="hidden")] = Field(min_length=1, max_length=200)
    event: Annotated[int, Knob(label="Événement", widget="hidden")] = Field(ge=1)
    value: Annotated[str, Knob(label="Elle te le rappelle", help="Vide : le choix de l'agenda.")] = \
        Field(default="", max_length=10)


@AGENDA.action("rappel", title="Régler son rappel d'un événement", args=RemindArgs, emits=[],
               description="« Elle te le rappelle » pour cet événement, ou le choix de son agenda ; il reste sur ce "
                           "serveur, jamais chez le fournisseur.")
async def _remind_event(s: AgendaState, frame: Frame, args: RemindArgs, ctx: Any) -> Done:
    desk = _Desk(s, frame, ctx, args.calendar, OWNED)
    e = desk.event(args.event)
    desk.store.remind(desk.calendar, e.uid, e.original, _remind(args.value))
    return Done(message="Rappel réglé.")


class CalendarArgs(BaseModel):
    account: Annotated[str, Knob(label="Compte", widget="hidden")] = Field(min_length=1, max_length=200)
    name: Annotated[str, Knob(label="Nom", advanced=False)] = Field(min_length=1, max_length=200)


@AGENDA.action("nouvel_agenda", title="Créer un agenda", args=CalendarArgs, emits=[],
               description="Un agenda de plus dans ce compte (sur ce serveur, ou chez son fournisseur s'il le sait).")
async def _new_calendar(s: AgendaState, frame: Frame, args: CalendarArgs, ctx: Any) -> Done:
    store, providers = ctx.ports.get("agenda"), ctx.ports.get("agenda_providers")
    if store is None or providers is None:
        raise Refused("L'agenda n'est pas branché sur ce serveur.")
    p = params_of(frame)
    if account_level(p, frame, person_of(frame, ctx.by), args.account) != OWNED:
        raise Refused(GONE)
    conn = providers.connection(args.account)
    provider = providers.of(conn.kind) if conn is not None else None
    if conn is None or provider is None or not provider.abilities(conn).calendars:
        raise Refused("Ce compte ne crée pas d'agenda d'ici.")
    name = _text(args.name, 200, "name")
    try:
        made = await provider.create_calendar(conn, name)
    except AgendaError as exc:
        raise Refused((str(exc) or "Le fournisseur a refusé.")[:300]) from None
    except Exception as exc:  # noqa: BLE001 — un fournisseur en panne, quelle qu'elle soit, se dit en mots
        raise _failed(exc) from None
    if provider.kind != SYSTEM:
        store.add_calendar(made)
    return Done(message=f"Agenda « {made.name or name} » créé.", show=({"calendar": made.key},))


class RenameArgs(BaseModel):
    calendar: Annotated[str, Knob(label="Agenda", widget="hidden")] = Field(min_length=1, max_length=200)
    name: Annotated[str, Knob(label="Nom", advanced=False,
                              help="Un agenda branché : vide, il reprend le nom de son fournisseur.")] = \
        Field(default="", max_length=200)


@AGENDA.action("renommer", title="Renommer un agenda", args=RenameArgs, emits=[],
               description="Un agenda du système change de nom ; un agenda branché prend un nom à lui ici, sans rien "
                           "changer chez son fournisseur.")
async def _rename(s: AgendaState, frame: Frame, args: RenameArgs, ctx: Any) -> Done:
    desk = _Desk(s, frame, ctx, args.calendar, OWNED)
    name = _text(args.name, 200, "name")
    system = desk.conn is not None and desk.conn.kind == SYSTEM
    if system and not name:
        raise Refused("Un agenda a un nom.", {"name": "un nom"})
    try:
        desk.store.rename(desk.calendar, name)
    except AgendaError as exc:
        raise Refused(str(exc)[:300], {"name": str(exc)[:200]}) from None
    if system or name:
        return Done(message=f"Renommé « {name} ».")
    return Done(message="Il reprend le nom de son fournisseur.")


class SyncArgs(BaseModel):
    account: Annotated[str, Knob(label="Compte", widget="hidden")] = Field(default="", max_length=200)


@AGENDA.action("synchroniser", title="Synchroniser maintenant", args=SyncArgs, emits=[SYNC_ASKED],
               description="Sans attendre sa cadence (même si elle dort).")
def _sync(s: AgendaState, frame: Frame, args: SyncArgs, ctx: Any) -> Done:
    p = params_of(frame)
    if args.account:
        if system_person(args.account):
            return Done(message="L'agenda du système est toujours à jour.", tone="info")
        mine = account_level(p, frame, person_of(frame, ctx.by), args.account) == OWNED
        if not (mine or operator(frame, ctx.by)) or args.account not in p.kinds:
            raise Refused(GONE)
    elif not operator(frame, ctx.by):
        raise Refused("Nomme le compte à synchroniser.", {"account": "un compte"})
    return Done(drafts=(SYNC_ASKED.draft(account=args.account, by=ctx.by),),
                message="Synchronisation demandée : l'agenda se relit dans quelques secondes.")


# ── ce que Mika propose ───────────────────────────────────────────────────


def waiting_for(s: AgendaState, frame: Frame, by: str, proposal: int) -> Written:
    """Une proposition qui attend, dont qui agit décide (son adresse est celle qu'elle nomme pour décider)."""
    w = s.writes.get(proposal)
    if w is None or w.status != WAITING or not w.approval or not w.decider \
            or w.decider not in handles_of(frame, by):
        raise Refused("Cette proposition n'attend plus ta décision.")
    return w


class DecideArgs(BaseModel):
    proposal: Annotated[int, Knob(label="Proposition", widget="hidden")] = Field(ge=1)
    seen: Annotated[str, Knob(label="Lu", widget="hidden")] = Field(default="", max_length=100)
    note: Annotated[str, Knob(label="Pourquoi", widget="textarea", help="Facultatif : elle le saura.")] = \
        Field(default="", max_length=COMMENT_MAX)


@AGENDA.action("accepter", title="Accepter ce qu'elle propose", args=DecideArgs, emits=[],
               description="Tel que tu l'as lu : il s'écrit dans l'agenda (ou la réponse part).")
def _accept(s: AgendaState, frame: Frame, args: DecideArgs, ctx: Any) -> Done:
    w = waiting_for(s, frame, ctx.by, args.proposal)
    return Done(decide=(Decision(w.proposal, True, seen=args.seen),),
                message="Accepté : c'est en train de s'écrire, tel que tu l'as lu.")


@AGENDA.action("refuser", title="Refuser ce qu'elle propose", args=DecideArgs, emits=[],
               description="Rien ne s'écrit ; elle le saura.")
def _refuse(s: AgendaState, frame: Frame, args: DecideArgs, ctx: Any) -> Done:
    w = waiting_for(s, frame, ctx.by, args.proposal)
    return Done(decide=(Decision(w.proposal, False, note=args.note.strip()),), message="Refusé : elle le saura.")


class AdoptArgs(EventArgs):
    """Ce que Mika proposait d'ajouter, tel que la personne l'a changé (« Modifier », puis « Ajouter »)."""

    proposal: Annotated[int, Knob(label="Proposition", widget="hidden")] = Field(ge=1)
    conversation: Annotated[str, Knob(label="Conversation", widget="hidden")] = Field(default="", max_length=300)


@AGENDA.action("ajouter_modifie", title="Ajouter ce qu'elle propose, avec tes changements", args=AdoptArgs,
               emits=[WRITTEN], description="Ta version s'écrit dans l'agenda choisi, marquée comme ajoutée par elle ; "
                                            "elle apprend ce que tu as changé.")
async def _adopt(s: AgendaState, frame: Frame, args: AdoptArgs, ctx: Any) -> Done:
    w = waiting_for(s, frame, ctx.by, args.proposal)
    if w.op != CREATE:
        raise Refused("Seule une proposition d'ajout se modifie ici : accepte-la ou refuse-la.")
    desk = _Desk(s, frame, ctx, args.calendar, SHARE_USE)
    made = await _create(desk, _draft(frame, desk, args, AddedBy(BY_HER, args.conversation, ctx.now)),
                         _remind(args.remind))
    said = dict(ctx.store.content([w.summary_ref])).get(w.summary_ref, "") \
        if ctx.store is not None and w.summary_ref else ""
    written = WRITTEN.draft(proposal=w.proposal, ok=True, op=CREATE, calendar=desk.calendar,
                            summary=Content.of((said or phrase("agenda.write.lost"))[:400],
                                               level=int(Sensitivity.PERSONAL)),
                            uid=made.uid, edited=True,
                            about=tuple(dict.fromkeys(x for x in (w.target, w.decider) if x)),
                            dedupe_key=f"agenda-ecrit:{w.proposal}")
    return Done(drafts=(written,), guard=rt.still_pending(w.proposal),
                decide=(Decision(w.proposal, False, note=phrase("agenda.fallen.edited")),),
                message=f"Ajouté à {_where(desk)}, avec tes changements.", show=(desk.made(made),))


__all__ = ["ANSWERS", "KEEP", "SCOPES", "account_level", "alerts_arg", "handles_of", "is_owner", "level_of",
           "person_of", "rule_of", "span_of"]
