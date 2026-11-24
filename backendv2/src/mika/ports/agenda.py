"""Le port de l'agenda (ADR 0309) : ses comptes, ses agendas, leurs événements — ceux du système, qui font foi dans
leur base, et ceux d'un fournisseur (Google, Microsoft, un serveur CalDAV, un abonnement iCal), dont la base garde la
copie.

« Journaliser l'esprit, pas le monde » : les événements vivent dans leur base (``agenda``), hors du journal, comme le
courrier, Teams et l'annuaire.

- **Un compte** (``Connection`` pour qui le joint, ``AccountState`` pour ce que la base en sait) est une connexion à un
  fournisseur, d'une sorte (``KINDS``), à quelqu'un (la règle de ``vocab/ownership.py`` : vide, à toi ;
  ``personne:<clé>``, à une personne). Chaque personne qui a un compte a le sien dans le système sans rien faire :
  ``system_account`` (``moi:<sa clé>``), à elle seule (``owner_of``), qui porte « Mon agenda » (``DEFAULT_CALENDAR``).
- **Un agenda** (``Calendar``) est sous son compte ; sa clé (``calendar_key`` : ``<compte>~<clé courte>``) se tire de
  l'identifiant que le fournisseur lui donne (``local_key``) : la même à chaque synchronisation, et jamais une adresse
  dans le journal (les réglages d'un agenda y vont, ADR 0309).
- **Un événement** (``Event``) : un titre, une période (``Span`` : des instants en UTC et le nom du fuseau où il se
  vit ; une journée entière reste une date, ses instants à minuit UTC, la fin exclue comme le dit la RFC 5545), un
  lieu, une description, un lien de réunion, ses participants et leur réponse, son organisateur, son état, « occupé »
  ou « disponible », privé ou non, les rappels du fournisseur, ce que Mika y a mis (``AddedBy`` : ``by`` elle, la
  référence de la conversation), et « Mika te le rappelle » pour cet événement (``remind`` : gardé dans la base
  seulement, jamais chez le fournisseur ; vide, le choix de son agenda). Un événement qui revient porte sa règle (``Recurrence`` : RRULE, EXDATE, RDATE) ;
  une occurrence changée est une exception (``original`` : la clé de l'occurrence qu'elle remplace, son
  RECURRENCE-ID). Une invitation entre deux personnes qui ont un compte est une copie dans l'agenda de l'invitée
  (``origin`` : l'agenda de l'organisatrice) ; ``response`` y dit sa réponse à elle.
- **Les occurrences d'une période** se développent par une fonction pure (``occurrences``, avec ``dateutil``) : à la
  même heure de son fuseau d'une occurrence à l'autre (l'heure d'été n'y change rien), moins ses EXDATE et ses
  exceptions, plus ses RDATE. ``split_rule`` coupe une série en deux (« celui-ci et les suivants »), ``instance``
  matérialise une occurrence en exception (« cet événement »).
- **Le magasin** (``AgendaPort``) : les comptes et agendas connus, l'état de la synchro de chacun, les événements, la
  lecture d'une période sur plusieurs agendas (``period``, rapide même avec des milliers d'événements : la base ne
  rend que ce qui touche la période, les séries se développent ensuite), les curseurs de synchro, l'oubli.
- **Un fournisseur** (``CalendarProvider``) liste ses agendas, se synchronise depuis un curseur (``SyncBatch``),
  crée, modifie (``Scope`` : cet événement, celui-ci et les suivants, tous), supprime, répond à une invitation, et dit
  ce qu'il sait faire (``Abilities``). ``AgendaProviders`` les tient par sorte, avec les comptes des réglages.
"""

from __future__ import annotations

import functools
import hashlib
import itertools
import logging
import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, rrulestr

from mika.vocab.access import PERSON

log = logging.getLogger("mika.agenda")

# ── les sortes de compte ────────────────────────────────────────────────────

#: le système (ce serveur : ses événements font foi dans la base), Google Agenda, Outlook.com / Microsoft 365, un
#: serveur CalDAV, un abonnement iCal (en lecture seule)
SYSTEM, GOOGLE, MICROSOFT, CALDAV, ICAL = "systeme", "google", "microsoft", "caldav", "ical"
KINDS = (SYSTEM, GOOGLE, MICROSOFT, CALDAV, ICAL)
Kind = Literal["systeme", "google", "microsoft", "caldav", "ical"]
KIND_WORDS = {SYSTEM: "Agenda du système", GOOGLE: "Google Agenda", MICROSOFT: "Outlook.com / Microsoft 365",
              CALDAV: "CalDAV", ICAL: "Abonnement iCal"}

#: le compte du système d'une personne qui a un compte : ``moi:<sa clé>``, à elle seule
SYSTEM_PREFIX = "moi:"
#: la clé courte de « Mon agenda », l'agenda que chaque compte du système a d'office
DEFAULT_CALENDAR = "mon-agenda"
#: son nom, tant que la personne ne l'a pas renommé
DEFAULT_CALENDAR_NAME = "Mon agenda"


def system_account(person: str) -> str:
    """Le compte du système de cette personne (sa clé dans l'identité, sans ``personne:``)."""
    return SYSTEM_PREFIX + person.removeprefix(PERSON)


def system_person(account: str) -> str:
    """La personne d'un compte du système (vide : ce n'en est pas un)."""
    return account[len(SYSTEM_PREFIX):] if account.startswith(SYSTEM_PREFIX) else ""


def owner_of(account: str, owners: Mapping[str, str]) -> str:
    """À qui est ce compte (la règle de ``vocab/ownership.py``) : le compte du système d'une personne est à elle
    (``personne:<clé>``) ; un autre, à qui les réglages le disent (``owners`` ; absent, à toi)."""
    person = system_person(account)
    return PERSON + person if person else owners.get(account, "")


# ── les agendas ─────────────────────────────────────────────────────────────

#: entre le compte et la clé courte d'un agenda (une clé courte n'en a jamais)
CALENDAR_SEP = "~"
#: la clé courte d'un agenda : l'identifiant du fournisseur quand il est court et sage, sinon son empreinte
_LOCAL = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
LOCAL_MAX = 40


def local_key(remote: str) -> str:
    """La clé courte d'un agenda, tirée de l'identifiant que son fournisseur lui donne : telle quelle si elle est
    courte et faite de minuscules, de chiffres, de « - » et de « _ » ; sinon ``h`` et 15 chiffres de son empreinte —
    jamais une adresse (l'agenda principal de Google porte celle de son compte), et la même à chaque synchronisation."""
    remote = remote.strip()
    if _LOCAL.fullmatch(remote):
        return remote
    return "h" + hashlib.sha256(remote.encode("utf-8", "surrogatepass")).hexdigest()[:15]


def calendar_key(account: str, local: str) -> str:
    return f"{account}{CALENDAR_SEP}{local}"


def split_calendar_key(key: str) -> tuple[str, str]:
    """(compte, clé courte) d'une clé d'agenda ; ``("", "")`` si ce n'en est pas une."""
    account, sep, local = key.rpartition(CALENDAR_SEP)
    return (account, local) if sep and account and local else ("", "")


# ── ce que dit un événement ─────────────────────────────────────────────────

#: son état : confirmé, provisoire, annulé (une occurrence annulée d'une série ne se montre pas)
CONFIRMED, TENTATIVE, CANCELLED = "confirme", "provisoire", "annule"
STATUSES = (CONFIRMED, TENTATIVE, CANCELLED)
#: la réponse d'une participante : en attente, oui, peut-être, non (PARTSTAT : NEEDS-ACTION, ACCEPTED, TENTATIVE,
#: DECLINED) ; vide : elle n'est pas invitée (l'organisatrice, un événement à soi)
NEEDS, YES, MAYBE, NO = "attente", "oui", "peut", "non"
RESPONSES = (NEEDS, YES, MAYBE, NO)
Response = Literal["attente", "oui", "peut", "non"]
#: ce qu'on change d'un événement qui revient : cet événement, celui-ci et les suivants, tous
ONE, FOLLOWING, ALL = "un", "suivants", "tous"
Scope = Literal["un", "suivants", "tous"]
#: « Mika te le rappelle » (par agenda) : non, 15 min avant, 30 min, 1 h, la veille au soir
REMINDERS = (("non", "Non"), ("15", "15 min avant"), ("30", "30 min avant"), ("60", "1 h avant"),
             ("veille", "La veille au soir"))
Reminder = Literal["non", "15", "30", "60", "veille"]
#: le rappel de Mika d'un agenda neuf, par sorte : 30 min avant pour le système ; coupé chez un fournisseur (il a les
#: siens) et pour un abonnement (ADR 0309)
DEFAULT_REMINDERS: Mapping[str, str] = {SYSTEM: "30", GOOGLE: "non", MICROSOFT: "non", CALDAV: "non", ICAL: "non"}
#: ce que Mika y a mis : ``elle`` (vide : la personne, ou le fournisseur)
BY_HER = "elle"
#: un rappel du fournisseur (lot 6) : une notification de son application, ou un e-mail qu'il envoie
NOTIFY, EMAIL = "notification", "email"
ALERT_METHODS = (NOTIFY, EMAIL)
#: au plus tant de rappels du fournisseur par événement, au plus tant de minutes avant (quatre semaines, comme Google)
ALERTS_MAX, ALERT_MINUTES_MAX = 10, 60 * 24 * 28

#: une fin de série qui ne vient jamais (µs) : une règle sans COUNT ni UNTIL
FOREVER = 2 ** 62
#: au plus tant d'occurrences d'une série dans une période (une règle folle ne remplit pas la mémoire)
OCCURRENCES_MAX = 5000
#: au plus tant de périodes d'une règle (des heures pour HOURLY, des jours pour DAILY…) parcourues d'un coup : depuis
#: le début d'une série bornée par COUNT (au-delà, elle ne donne plus rien), et pour juger qu'une règle donne quelque
#: chose ; une période se parcourt en une microseconde environ
_STEPS_MAX = 20_000
#: au plus tant de dates ajoutées (RDATE), et tant de retirées (EXDATE), lues d'une série
DATES_MAX = 2000
#: la période d'une règle, par fréquence (fois son INTERVAL) : en mois, ou en durée à l'heure de son fuseau.
#: SECONDLY et MINUTELY, qu'aucun agenda n'écrit, ne se développent pas (la première occurrence seule)
_MONTHS = {"YEARLY": 12, "MONTHLY": 1}
_STEPS = {"WEEKLY": timedelta(weeks=1), "DAILY": timedelta(days=1), "HOURLY": timedelta(hours=1)}

US_PER_S = 1_000_000
DAY_US = 86_400 * US_PER_S
#: l'origine des instants : leurs calculs restent en entiers (jamais un flottant qui perd une microseconde)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_US = timedelta(microseconds=1)
#: les instants que ``datetime`` sait écrire dans tout fuseau (µs UTC)
_EARLIEST = (datetime(1, 1, 2, tzinfo=UTC) - EPOCH) // _ONE_US
_LATEST = (datetime(9999, 12, 30, tzinfo=UTC) - EPOCH) // _ONE_US


def default_reminder(kind: str, *, system: str = "", provider: str = "") -> str:
    """Le rappel de Mika d'un agenda de cette sorte quand la personne n'en a pas choisi : ceux du serveur (``system``,
    ``provider``, réglés dans la console) s'ils sont dits, sinon ``DEFAULT_REMINDERS``."""
    if kind == SYSTEM and system:
        return system
    if kind in (GOOGLE, MICROSOFT, CALDAV) and provider:
        return provider
    return DEFAULT_REMINDERS.get(kind, "non")


@dataclass(frozen=True, slots=True)
class Span:
    """Quand : du début (inclus) à la fin (exclue), en µs UTC, et le fuseau où il se vit (un nom IANA ; vide : UTC).
    Une journée entière (``all_day``) a ses instants à minuit UTC de ses dates : la fin est le lendemain du dernier
    jour, comme DTEND d'une date dans la RFC 5545."""

    start: int
    end: int
    zone: str = ""
    all_day: bool = False

    @property
    def first_day(self) -> str:
        """La date du premier jour (AAAA-MM-JJ) d'une journée entière ; vide sinon."""
        return day_of(self.start) if self.all_day else ""

    @property
    def last_day(self) -> str:
        """La date du dernier jour (compris) d'une journée entière ; vide sinon."""
        return day_of(max(self.start, self.end - DAY_US)) if self.all_day else ""


def at_us(us: int, zone: tzinfo = UTC) -> datetime:
    """Un instant (µs UTC) dans un fuseau."""
    return (EPOCH + timedelta(microseconds=us)).astimezone(zone)


def us_of(d: datetime) -> int:
    """L'instant (µs UTC) d'une date avec fuseau."""
    return (d - EPOCH) // _ONE_US


def day_of(us: int) -> str:
    return at_us(us).strftime("%Y-%m-%d")


def day_at(day: str) -> int:
    """Minuit UTC d'une date (AAAA-MM-JJ ou AAAAMMJJ), en µs."""
    return us_of(datetime.strptime(day.replace("-", "")[:8], "%Y%m%d").replace(tzinfo=UTC))


def whole_days(first: str, last: str) -> Span:
    """Une journée entière, ou plusieurs : du premier jour au dernier, compris."""
    return Span(day_at(first), day_at(last) + DAY_US, all_day=True)


@dataclass(frozen=True, slots=True)
class Recurrence:
    """La règle d'une série (RFC 5545) : sa RRULE (``FREQ=WEEKLY;BYDAY=MO``, sans « RRULE: »), les occurrences
    retirées (EXDATE) et ajoutées (RDATE), chacune par sa clé (``occurrence_key``)."""

    rule: str = ""
    exdates: tuple[str, ...] = ()
    rdates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Participant:
    """Une participante, ou l'organisatrice : son adresse, son nom, sa clé de personne quand elle a un compte (l'agenda
    du système désigne par elle), sa réponse, si elle est facultative, et si c'est le compte de l'agenda lui-même
    (``me``)."""

    address: str = ""
    name: str = ""
    person: str = ""
    response: str = ""
    optional: bool = False
    me: bool = False


@dataclass(frozen=True, slots=True, order=True)
class Alert:
    """Un rappel du fournisseur (lot 6) : tant de minutes avant le début, par une notification de son application
    (``NOTIFY``) ou un e-mail qu'il envoie (``EMAIL``). Ce n'est pas « Mika te le rappelle » (``Event.remind``) : c'est
    Google, Outlook ou le serveur CalDAV qui le fait ; l'agenda du système n'en a pas (Mika rappelle), un abonnement
    les lit seulement."""

    minutes: int
    method: str = NOTIFY


def alerts_of(alerts: Iterable[Alert]) -> tuple[Alert, ...]:
    """Des rappels du fournisseur rangés : sans doublon, dans les bornes (``ALERT_MINUTES_MAX``), une méthode connue,
    du plus proche du rendez-vous au plus lointain, ``ALERTS_MAX`` au plus."""
    kept = {Alert(int(a.minutes), a.method) for a in alerts
            if a.method in ALERT_METHODS and 0 <= int(a.minutes) <= ALERT_MINUTES_MAX}
    return tuple(sorted(kept))[:ALERTS_MAX]


@dataclass(frozen=True, slots=True)
class AddedBy:
    """Ce que Mika a mis dans un agenda : par elle (``by``), dans quelle conversation (``ref`` : la référence de la
    conversation, ce que la console et l'écran ouvrent), quand."""

    by: str = BY_HER
    ref: str = ""
    at: int = 0


@dataclass(frozen=True, slots=True)
class Event:
    """Un événement, une série (sa règle), ou une exception d'une série (``original`` : la clé de l'occurrence qu'elle
    remplace). ``calendar`` est la clé de son agenda ; ``uid`` le désigne chez tous (l'UID de la RFC 5545) ; ``remote``,
    ``etag`` et ``raw`` sont ce que son fournisseur en dit (pour le réécrire sans rien perdre). ``origin`` : la copie
    d'une invitation du système, l'agenda de l'organisatrice ; ``response`` : la réponse du compte de cet agenda (vide :
    il n'est pas invité). ``forgotten`` : son organisatrice a été oubliée, il ne garde que son créneau."""

    calendar: str
    uid: str
    span: Span
    title: str = ""
    original: str = ""
    location: str = ""
    description: str = ""
    conference: str = ""
    recurrence: Recurrence | None = None
    status: str = CONFIRMED
    busy: bool = True
    private: bool = False
    organizer: Participant | None = None
    participants: tuple[Participant, ...] = ()
    response: str = ""
    #: les rappels du fournisseur (lot 6) ; ``reminders_default`` : il suit ceux de son agenda (Google), que
    #: ``Calendar.reminders`` dit — ``reminders`` est alors vide
    reminders: tuple[Alert, ...] = ()
    reminders_default: bool = False
    added: AddedBy | None = None
    origin: str = ""
    remote: str = ""
    etag: str = ""
    sequence: int = 0
    created: int = 0
    updated: int = 0
    forgotten: bool = False
    raw: str = field(default="", repr=False)
    #: sa ligne dans la base (0 : pas encore rangé)
    id: int = 0
    #: « Mika te le rappelle » pour cet événement (``REMINDERS`` ; vide : le choix de son agenda) — une série entière,
    #: ou une seule fois quand c'est une exception. Il ne vit que dans la base (``AgendaPort.remind``) : ni une
    #: synchronisation ni une écriture chez le fournisseur ne le touchent.
    remind: str = ""

    @property
    def recurring(self) -> bool:
        return self.recurrence is not None and bool(self.recurrence.rule or self.recurrence.rdates)

    @property
    def declined(self) -> bool:
        return self.response == NO


@dataclass(frozen=True, slots=True)
class Occurrence:
    """Une occurrence d'une période : l'événement d'où elle vient (la série, une exception, ou l'événement simple), sa
    clé dans la série (vide : un événement simple) et quand elle a lieu."""

    event: Event
    key: str
    span: Span


@dataclass(frozen=True, slots=True)
class EventDraft:
    """Un événement à créer (ce qu'un outil ou un écran demande)."""

    title: str
    span: Span
    location: str = ""
    description: str = ""
    conference: str = ""
    rule: str = ""
    participants: tuple[Participant, ...] = ()
    busy: bool = True
    private: bool = False
    status: str = CONFIRMED
    #: les rappels du fournisseur ; ``None`` : ceux de l'agenda chez lui (Google : ses rappels par défaut ; Outlook :
    #: le sien ; CalDAV : aucun)
    reminders: tuple[Alert, ...] | None = None
    added: AddedBy | None = None


@dataclass(frozen=True, slots=True)
class EventChange:
    """Ce qu'on change d'un événement : chaque champ laissé à ``None`` reste tel quel. ``rule`` vide retire la
    règle (il ne revient plus)."""

    title: str | None = None
    span: Span | None = None
    location: str | None = None
    description: str | None = None
    conference: str | None = None
    rule: str | None = None
    participants: tuple[Participant, ...] | None = None
    busy: bool | None = None
    private: bool | None = None
    status: str | None = None
    #: les rappels du fournisseur (vide : aucun)
    reminders: tuple[Alert, ...] | None = None
    added: AddedBy | None = None


@dataclass(frozen=True, slots=True)
class Calendar:
    """Un agenda : sa clé (``calendar_key``), son compte, son identifiant chez le fournisseur, son nom, sa couleur chez
    lui (un indice : celle que la personne choisit est dans les réglages), si on peut y écrire, son fuseau, s'il est
    l'agenda principal du compte, si le fournisseur le coche (suivi par défaut), où sa synchro en est, et les rappels
    que le fournisseur pose sur un événement qui suit ceux de l'agenda (``reminders`` : les ``defaultReminders`` de
    Google). ``name`` est celui qu'on lui voit : le nom que la personne lui a donné dans Mika (lot 6 : un agenda
    branché garde alors celui de son fournisseur dans ``provider_name``), sinon celui du fournisseur."""

    key: str
    account: str
    remote: str
    name: str = ""
    color: str = ""
    writable: bool = True
    zone: str = ""
    primary: bool = False
    selected: bool = True
    cursor: str = ""
    synced_at: int = 0
    reminders: tuple[Alert, ...] = ()
    provider_name: str = ""


@dataclass(frozen=True, slots=True)
class AccountState:
    """Ce que la base sait d'un compte : sa sorte, à qui il est, son adresse à lui et s'il est actif (tels que les
    réglages les disent), et sa synchro — la dernière réussie, le dernier essai, combien d'échecs de suite, l'erreur en
    mots (vide : en état)."""

    key: str
    kind: str
    owner: str = ""
    address: str = ""
    synced_at: int = 0
    tried_at: int = 0
    failures: int = 0
    error: str = ""
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class Connection:
    """Un compte tel que les réglages le disent, pour qui le joint : ses identifiants ouverts (jamais au journal, jamais
    dans un ``repr``), ce qu'on suit de ses agendas (``followed`` : clé courte → suivi ; absent, ce que le fournisseur
    coche). Un compte Microsoft peut déclarer son application (``oauth_client_id`` ; vide : celle de l'instance) et
    son annuaire (``oauth_tenant``) ; son jeton, comme celui d'un compte Google, est gardé à part (lot 2). ``internet`` :
    réglé par une personne qui n'est pas opératrice, son serveur (CalDAV, un abonnement) n'est joint que sur Internet,
    revérifié à chaque requête et joint à l'adresse vérifiée (pas seulement à l'enregistrement)."""

    key: str
    kind: str
    owner: str = ""
    label: str = ""
    address: str = ""
    enabled: bool = True
    url: str = field(default="", repr=False)
    username: str = ""
    secret: str = field(default="", repr=False)
    followed: Mapping[str, bool] = field(default_factory=dict)
    oauth_client_id: str = ""
    oauth_tenant: str = "consumers"
    internet: bool = False


def follows(connection: Connection, calendar: Calendar) -> bool:
    """Ce compte suit-il cet agenda ? Ce que la personne a dit, sinon ce que le fournisseur coche (son principal
    toujours)."""
    _account, local = split_calendar_key(calendar.key)
    said = connection.followed.get(local)
    return bool(said) if said is not None else (calendar.selected or calendar.primary)


@dataclass(frozen=True, slots=True)
class Window:
    """La fenêtre que la copie d'un fournisseur tient à jour (µs UTC)."""

    start: int
    end: int


#: la fenêtre d'une synchronisation : 90 jours derrière, un an devant (au-delà, on demande au fournisseur)
WINDOW_PAST_US = 90 * DAY_US
WINDOW_AHEAD_US = 365 * DAY_US


def sync_window(now: int, past_us: int = WINDOW_PAST_US, ahead_us: int = WINDOW_AHEAD_US) -> Window:
    return Window(now - past_us, now + ahead_us)


@dataclass(frozen=True, slots=True)
class SyncBatch:
    """Ce qu'une synchronisation rapporte d'un agenda : les événements neufs ou changés (des lignes : séries,
    exceptions, événements simples), ceux qui ne sont plus (``removed`` : (uid, clé d'occurrence) ; une clé vide, la
    série entière), le curseur d'après. ``replaced`` : ce que le fournisseur redonne en entier, par son identifiant chez
    lui (``Event.remote`` : une ressource CalDAV) — ses lignes que le lot ne nomme pas partent (la ressource
    supprimée, ou qui a perdu une exception). ``complete`` : une relecture entière de la fenêtre, pas un delta (ce qui
    n'y est pas part) ; ``more`` : il en reste, à demander avec ce curseur."""

    events: tuple[Event, ...] = ()
    removed: tuple[tuple[str, str], ...] = ()
    cursor: str = ""
    complete: bool = False
    more: bool = False
    replaced: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Abilities:
    """Ce qu'un fournisseur sait faire d'un compte : y écrire, inviter (et répondre), se synchroniser par delta,
    créer un agenda ; combien de rappels à lui un événement garde (``reminders`` : 0, il n'en écrit pas) et s'il sait
    en envoyer par e-mail (``email_reminders``)."""

    write: bool = False
    invite: bool = False
    incremental: bool = False
    calendars: bool = False
    reminders: int = 0
    email_reminders: bool = False


class AgendaError(RuntimeError):
    """Ce qu'un fournisseur ou le magasin refuse, en mots (la santé et la fiche du compte le disent)."""


#: ce que garde l'historique de la synchro (lot 5) : une relecture qui a changé quelque chose (``SYNC_READ``), une
#: relecture entière (``SYNC_FULL`` : sans curseur, la première ou après un curseur perdu), la copie relue après une
#: écriture (``SYNC_WRITTEN``), une panne (``SYNC_FAILED`` : la première, ou une autre erreur), sa fin
#: (``SYNC_RECOVERED``), un agenda qu'on ne suit plus (``SYNC_DROPPED`` : sa copie est partie)
SYNC_READ, SYNC_FULL, SYNC_WRITTEN, SYNC_FAILED, SYNC_RECOVERED, SYNC_DROPPED = \
    "relu", "entier", "ecrit", "erreur", "reprise", "retire"
SYNC_WHATS = (SYNC_READ, SYNC_FULL, SYNC_WRITTEN, SYNC_FAILED, SYNC_RECOVERED, SYNC_DROPPED)


@dataclass(frozen=True, slots=True)
class SyncNote:
    """Une ligne de l'historique de la synchro d'un compte (l'onglet Synchronisation de la fiche d'un agenda, ADR 0309,
    lot 5) : son agenda (vide : tout le compte — une panne, sa reprise), quand, ce que c'était (``SYNC_WHATS``),
    combien d'événements elle a rangés ou retirés, et ce qu'on en dit (l'erreur en mots ; jamais un titre ni une
    adresse : l'oubli n'a pas à venir les y chercher). Ce qui n'a rien changé n'y est pas."""

    account: str
    calendar: str
    at: int
    what: str
    changed: int = 0
    detail: str = ""
    id: int = 0


# ── les clés d'occurrence ───────────────────────────────────────────────────


def occurrence_key(start: int, all_day: bool) -> str:
    """La clé d'une occurrence, son instant d'origine comme le dit RECURRENCE-ID : une date (``20261123``) pour une
    journée entière, un instant UTC (``20261123T070000Z``) sinon."""
    d = at_us(start - start % US_PER_S)
    return d.strftime("%Y%m%d") if all_day else d.strftime("%Y%m%dT%H%M%SZ")


def key_instant(key: str) -> int:
    """L'instant (µs UTC) d'une clé d'occurrence."""
    if "T" not in key:
        return day_at(key)
    return us_of(datetime.strptime(key.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=UTC))


def readable_key(key: str) -> bool:
    """Une clé d'occurrence qui se lit (``occurrence_key``) : ce qu'un écran ou un outil renvoie peut être n'importe
    quoi."""
    try:
        key_instant(key)
    except ValueError:
        return False
    return True


def shifted_key(key: str, delta: int) -> str:
    return occurrence_key(key_instant(key) + delta, "T" not in key)


# ── les règles (RFC 5545) ───────────────────────────────────────────────────


def zone_of(name: str) -> tzinfo:
    """Le fuseau d'un nom IANA ; inconnu ou vide : UTC."""
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def rule_parts(rule: str) -> list[tuple[str, str]]:
    """Les parties d'une RRULE (``FREQ=WEEKLY;COUNT=3`` → ``[("FREQ", "WEEKLY"), ("COUNT", "3")]``), dans l'ordre."""
    rule = rule.strip().removeprefix("RRULE:")
    out = []
    for part in rule.split(";"):
        name, sep, value = part.partition("=")
        if sep and name.strip():
            out.append((name.strip().upper(), value.strip()))
    return out


def rule_text(parts: Sequence[tuple[str, str]]) -> str:
    return ";".join(f"{k}={v}" for k, v in parts)


def _until_utc(rule: str, all_day: bool, zone: tzinfo) -> str:
    """La RRULE telle que ``dateutil`` la lit sur un début avec fuseau : son UNTIL en UTC (une date : la fin de ce jour
    dans le fuseau de l'événement ; un instant flottant : dans ce fuseau)."""
    parts = rule_parts(rule)
    out = []
    for name, value in parts:
        if name == "UNTIL":
            value = _until_value(value, all_day, zone)
        out.append((name, value))
    return rule_text(out)


def _until_value(value: str, all_day: bool, zone: tzinfo) -> str:
    raw = value.upper()
    try:
        if raw.endswith("Z"):
            return raw
        if "T" not in raw:  # une date : la fin de ce jour, dans son fuseau
            last = datetime.strptime(raw[:8] + "235959", "%Y%m%d%H%M%S").replace(tzinfo=UTC if all_day else zone)
        else:  # un instant flottant : dans son fuseau
            last = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone)
    except ValueError:
        return value
    return last.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True, slots=True)
class _Rule:
    """Une règle lue sur le début de sa série, qu'on parcourt sans repartir de ce début : ``pinned`` dit ce que
    ``dateutil`` tire de ce début quand la règle ne le dit pas (le jour du mois, de la semaine, l'heure…), pour
    qu'avancer le début d'un nombre entier de périodes ne change aucune occurrence."""

    rule: rrule
    first: datetime
    freq: str
    interval: int
    count: int | None
    pinned: tuple[tuple[str, int], ...]

    def moved(self, k: int) -> datetime:
        """Le début de la série avancé de ``k`` périodes entières (k × INTERVAL), à l'heure de son fuseau."""
        if self.freq in _MONTHS:
            return self.first + relativedelta(months=_MONTHS[self.freq] * self.interval * k)
        return self.first + _STEPS[self.freq] * (self.interval * k)

    def periods(self, to: datetime) -> int:
        """Combien de périodes entières (de INTERVAL) du début de la série à ``to``, à l'heure de son fuseau."""
        there = to.astimezone(self.first.tzinfo)
        if self.freq in _MONTHS:
            months = (there.year - self.first.year) * 12 + there.month - self.first.month
            return months // (_MONTHS[self.freq] * self.interval)
        return (there.replace(tzinfo=None) - self.first.replace(tzinfo=None)) // (_STEPS[self.freq] * self.interval)

    def from_(self, k: int, **more: object) -> rrule:
        """La même règle, son début avancé de ``k`` périodes (pas de COUNT : il compte depuis le vrai début)."""
        if k <= 0 and not more:
            return self.rule
        return self.rule.replace(**({"dtstart": self.moved(k)} if k > 0 else {}), **dict(self.pinned), **more)

    def cap(self) -> datetime:
        """Jusqu'où une série bornée par COUNT se parcourt depuis son début : ``_STEPS_MAX`` périodes."""
        try:
            return self.moved(_STEPS_MAX)
        except (OverflowError, ValueError):
            return datetime(9999, 12, 30, tzinfo=self.first.tzinfo)


def _pinned(parts: Mapping[str, str], freq: str, first: datetime) -> tuple[tuple[str, int], ...]:
    """Ce que ``dateutil`` tire du début de la série quand la règle ne le dit pas (``rrule.__init__``)."""
    out: list[tuple[str, int]] = []
    if not parts.keys() & {"BYWEEKNO", "BYYEARDAY", "BYMONTHDAY", "BYDAY", "BYEASTER"}:
        if freq == "YEARLY":
            out += ([] if "BYMONTH" in parts else [("bymonth", first.month)]) + [("bymonthday", first.day)]
        elif freq == "MONTHLY":
            out.append(("bymonthday", first.day))
        elif freq == "WEEKLY":
            out.append(("byweekday", first.weekday()))
    if "BYHOUR" not in parts and freq != "HOURLY":
        out.append(("byhour", first.hour))
    if "BYMINUTE" not in parts:
        out.append(("byminute", first.minute))
    if "BYSECOND" not in parts:
        out.append(("bysecond", first.second))
    return tuple(out)


@functools.lru_cache(maxsize=4096)
def _parsed(rule: str, start: int, zone: str, all_day: bool) -> _Rule | None:
    """La règle lue par ``dateutil``, sur le début de la série. ``None`` : illisible, trop fine pour un agenda, ou
    qui ne donne jamais rien — ``dateutil`` ne s'arrête qu'à une date qui tombe (ni l'UNTIL ni la fin d'une période
    ne l'arrêtent) : il la parcourrait jusqu'à l'an 9999 à chaque lecture. On le juge une fois, près de cette fin,
    sur ``_STEPS_MAX`` périodes ; rien n'est gardé de ce qu'elle parcourt."""
    if not rule:
        return None
    parts = {k: v for k, v in rule_parts(rule)}
    freq = parts.get("FREQ", "").upper()
    if freq not in _MONTHS and freq not in _STEPS:  # SECONDLY, MINUTELY : trop fines ; le reste, illisible
        return None
    tz = UTC if all_day else zone_of(zone)
    try:
        first = at_us(start, tz)
        parsed = rrulestr(_until_utc(rule, all_day, tz), dtstart=first)
        if not isinstance(parsed, rrule):
            return None
        count = parts.get("COUNT", "")
        read = _Rule(parsed, first, freq, max(1, int(parts.get("INTERVAL") or 1)),
                     int(count) if count.isdigit() else None, _pinned(parts, freq, first))
        near_end = read.periods(datetime(9999, 12, 30, tzinfo=tz)) - _STEPS_MAX
        if next(iter(read.from_(near_end, count=None, until=None)), None) is None:
            log.warning("agenda : une règle de récurrence qui ne donne rien (%s)", rule[:80])
            return None
        return read
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        log.warning("agenda : une règle de récurrence illisible (%s) : %s", rule[:80], exc)
        return None


def _starts(read: _Rule, lo: datetime, hi: datetime) -> Iterator[datetime]:
    """Les débuts de ses occurrences de ``lo`` (inclus) jusqu'à la première après ``hi`` (exclue), dans l'ordre. Une
    règle sans COUNT se parcourt depuis la période qui précède ``lo`` ; une règle bornée par COUNT, depuis le début de
    sa série (il compte de là), sur ``_STEPS_MAX`` périodes au plus."""
    if read.count is None:
        for d in read.from_(read.periods(lo) - 2).xafter(lo, inc=True):
            if d >= hi:
                return
            yield d
        return
    stop = min(hi, read.cap())
    for d in read.rule:
        if d >= stop:
            return
        if d >= lo:
            yield d


def _until_at(rule: str, all_day: bool, zone: tzinfo) -> datetime | None:
    """L'UNTIL d'une règle, tel que ``dateutil`` le lit (en UTC) ; ``None`` s'il ne se lit pas ainsi."""
    raw = dict(rule_parts(_until_utc(rule, all_day, zone))).get("UNTIL", "").upper()
    try:
        return datetime.strptime(raw[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _at(us: int, zone: tzinfo) -> datetime:
    """Un instant dans ce fuseau, ramené aux dates que ``datetime`` sait écrire (de l'an 1 à l'an 9999)."""
    return at_us(min(max(us, _EARLIEST), _LATEST), zone)


def _overlaps(start: int, end: int, lo: int, hi: int) -> bool:
    """[start, end[ touche-t-il [lo, hi[ ? Un instant sans durée y est s'il y tombe."""
    if end <= start:
        return lo <= start < hi
    return start < hi and end > lo


def local_days(span: Span, zone: tzinfo) -> tuple[int, int]:
    """Quand il occupe, en instants : une journée entière, de minuit à minuit dans ce fuseau (ses instants sont à
    minuit UTC de ses dates) ; un rendez-vous, ses instants."""
    if not span.all_day:
        return span.start, span.end
    first = date.fromisoformat(span.first_day)
    after = date.fromisoformat(span.last_day) + timedelta(days=1)
    return (us_of(datetime.combine(first, time(), tzinfo=zone)),
            us_of(datetime.combine(after, time(), tzinfo=zone)))


def _touches(span: Span, start: int, end: int, zone: tzinfo | None) -> bool:
    """Touche-t-il [start, end[ ? Dans une période faite de jours d'un fuseau (``zone``), une journée entière se
    compare par ses dates : rangée à minuit UTC, elle déborderait sur la veille ou le lendemain."""
    lo, hi = local_days(span, zone) if zone is not None and span.all_day else (span.start, span.end)
    return _overlaps(lo, hi, start, end)


def occurrences(event: Event, start: int, end: int, *, limit: int = OCCURRENCES_MAX,
                zone: tzinfo | None = None) -> list[Occurrence]:
    """Les occurrences de cet événement qui touchent [start, end[ (µs UTC), dans l'ordre. Un événement simple ou une
    exception : la sienne. Une série : celles de sa règle et de ses RDATE, chacune de la durée de la première et à la
    même heure de son fuseau, moins ses EXDATE ; ses exceptions, rangées à part, se retirent et s'ajoutent ailleurs
    (``expand``). Une règle illisible ne donne que la première occurrence. Annulé (une série aussi), il n'en a
    aucune. ``zone`` : [start, end[ va d'un minuit à un autre de ce fuseau, et une journée entière s'y lit par ses
    dates (elle touche toujours ces bornes en UTC, un fuseau ne décalant pas d'un jour entier)."""
    span = event.span
    duration = max(0, span.end - span.start)
    if event.status == CANCELLED and not event.original:  # annulé, série comprise : rien ne se montre
        return []
    if not event.recurring:
        if event.status == CANCELLED or not _overlaps(span.start, span.end, start, end) \
                or not _touches(span, start, end, zone):
            return []
        return [Occurrence(event, event.original, span)]
    rec = event.recurrence
    assert rec is not None
    skip = set(rec.exdates[:DATES_MAX])
    out: dict[str, Occurrence] = {}

    def keep(at: int) -> None:
        key = occurrence_key(at, span.all_day)
        if key not in skip and key not in out and _overlaps(at, at + duration, start, end):
            found = Span(at, at + duration, span.zone, span.all_day)
            if _touches(found, start, end, zone):
                out[key] = Occurrence(event, key, found)

    parsed = _parsed(rec.rule, span.start, span.zone, span.all_day)
    if parsed is None and not rec.rdates:
        keep(span.start)
    elif parsed is not None:
        tz = parsed.first.tzinfo
        for d in itertools.islice(_starts(parsed, _at(max(span.start, start - duration), tz), _at(end, tz)), limit):
            keep(us_of(d))
    for key in rec.rdates[:DATES_MAX]:
        try:
            keep(key_instant(key))
        except ValueError:
            continue
    return sorted(out.values(), key=lambda o: o.span.start)[:limit]


def expand(events: Sequence[Event], start: int, end: int, *, declined: bool = False,
           zone: tzinfo | None = None) -> list[Occurrence]:
    """Les occurrences de [start, end[ de ces lignes (séries, exceptions, événements simples) : une exception remplace
    l'occurrence de sa série qu'elle désigne (annulée, elle la retire) ; ``declined`` faux : ce que le compte de
    l'agenda a refusé ne se montre pas ; ``zone`` : une période de jours de ce fuseau (``occurrences``). Dans l'ordre
    de leur début, puis de leur titre."""
    replaced = {(e.calendar, e.uid, e.original) for e in events if e.original}
    out: list[Occurrence] = []
    for e in events:
        if not declined and e.declined:
            continue
        for o in occurrences(e, start, end, zone=zone):
            if not e.original and (e.calendar, e.uid, o.key) in replaced:
                continue
            out.append(o)
    out.sort(key=lambda o: (o.span.start, o.span.end, o.event.title, o.event.uid, o.key))
    return out


def series_end(event: Event) -> int:
    """La fin de sa dernière occurrence (µs UTC) : la sienne pour un événement simple ; ``FOREVER`` pour une série sans
    fin (ni COUNT ni UNTIL) — ce que la base compare pour ne rendre que ce qui touche une période."""
    span = event.span
    if not event.recurring:
        return span.end
    rec = event.recurrence
    assert rec is not None
    duration = max(0, span.end - span.start)
    last = span.start
    parsed = _parsed(rec.rule, span.start, span.zone, span.all_day)
    if parsed is not None:
        names = {k for k, _ in rule_parts(rec.rule)}
        if not names & {"COUNT", "UNTIL"}:
            return FOREVER
        if parsed.count is not None:  # depuis son début, où COUNT compte, sur ``_STEPS_MAX`` périodes au plus
            cap = parsed.cap()
            for d in parsed.rule:
                if d >= cap:
                    last = max(last, us_of(cap))
                    break
                last = max(last, us_of(d))
        else:  # la dernière avant son UNTIL, cherchée depuis les périodes qui le précèdent
            until = _until_at(rec.rule, span.all_day, parsed.first.tzinfo)
            if until is None:
                return FOREVER
            found = None
            for d in parsed.from_(parsed.periods(until) - 2):
                found = d
            last = max(last, us_of(found if found is not None else until))
    for key in rec.rdates[:DATES_MAX]:
        try:
            last = max(last, key_instant(key))
        except ValueError:
            continue
    return last + duration


def counted_before(event: Event, key: str) -> int:
    """Combien d'occurrences sa règle donne avant celle-ci (EXDATE compris : COUNT les compte, RFC 5545)."""
    rec = event.recurrence
    parsed = _parsed(rec.rule, event.span.start, event.span.zone, event.span.all_day) if rec else None
    if parsed is None:
        return 0
    stop = min(at_us(key_instant(key)), parsed.cap())
    n = 0
    for d in parsed.rule:
        if d >= stop:
            break
        n += 1
    return n


def split_rule(event: Event, key: str) -> tuple[str, str]:
    """Une série coupée à cette occurrence (« celui-ci et les suivants ») : la règle de ce qui la précède (finie juste
    avant elle : UNTIL, sans COUNT) et celle de ce qui commence à elle (le COUNT qui reste, ou le même UNTIL)."""
    rec = event.recurrence
    rule = rec.rule if rec else ""
    parts = rule_parts(rule)
    at = key_instant(key)
    all_day = event.span.all_day
    until = occurrence_key(at - DAY_US, True) if all_day else occurrence_key(at - US_PER_S, False)
    before = [(k, v) for k, v in parts if k not in ("COUNT", "UNTIL")] + [("UNTIL", until)]
    after = list(parts)
    count = dict(parts).get("COUNT")
    if count is not None and count.isdigit():
        left = max(1, int(count) - counted_before(event, key))
        after = [(k, str(left) if k == "COUNT" else v) for k, v in parts]
    return rule_text(before), rule_text(after)


def instance(master: Event, key: str) -> Event:
    """L'occurrence ``key`` d'une série devenue une exception (une ligne à elle, ``original``), telle que la série la
    donne : ce qu'on change ensuite ne touche qu'elle."""
    duration = max(0, master.span.end - master.span.start)
    at = key_instant(key)
    return replace(master, original=key, recurrence=None, span=replace(master.span, start=at, end=at + duration),
                   id=0, remote="", etag="", raw="")


def masked(event: Event) -> Event:
    """Ce qu'on montre d'un événement privé à qui n'est pas son propriétaire : « Occupé », son créneau seul."""
    return replace(event, title="", location="", description="", conference="", organizer=None, participants=(),
                   raw="", reminders=())


def blanked(event: Event) -> Event:
    """Un événement dont l'organisatrice est oubliée : ce qu'elle y avait écrit part (titre, lieu, description, lien),
    elle aussi ; son créneau reste, pour qu'on sache qu'on n'y est pas libre."""
    return replace(event, title="", location="", description="", conference="", organizer=None, raw="",
                   forgotten=True)


def address_print(address: str) -> str:
    """L'empreinte d'une adresse oubliée (jamais l'adresse elle-même) : ce qu'une synchronisation compare."""
    return hashlib.sha256(f"mail:{address.strip().lower()}".encode()).hexdigest()


# ── le magasin, les fournisseurs ────────────────────────────────────────────


class AgendaPort(Protocol):
    """Le magasin de l'agenda (``agenda.db``) : ses comptes et leur synchro, ses agendas, leurs événements. Chaque
    écriture dit ce qu'elle change, une fois validée (``on_change``, ADR 0308)."""

    # ses comptes
    def accounts(self) -> list[AccountState]:
        """Les comptes qu'elle connaît, par clé."""
        ...

    def account(self, key: str) -> AccountState | None: ...

    def keep_account(self, key: str, kind: str, *, owner: str = "", address: str = "",
                     enabled: bool = True) -> AccountState:
        """Le compte tel que les réglages le disent (sa sorte, à qui il est, son adresse, s'il est actif) : né au
        besoin."""
        ...

    def drop_account(self, key: str) -> int:
        """Un compte retiré des réglages : ses agendas, ses événements et sa synchro partent."""
        ...

    def synced(self, key: str, *, error: str = "", at: int | None = None) -> AccountState:
        """Une synchronisation faite (``error`` vide) ou manquée (son erreur en mots : ses échecs se comptent)."""
        ...

    # ses agendas
    def calendars(self, account: str | None = None) -> list[Calendar]: ...

    def calendar(self, key: str) -> Calendar | None: ...

    def keep_calendars(self, account: str, found: Sequence[Calendar]) -> list[Calendar]:
        """Les agendas que le fournisseur liste pour ce compte : rangés (nom, couleur, droits…) ; ceux qui n'y sont
        plus partent avec leurs événements."""
        ...

    def add_calendar(self, calendar: Calendar) -> Calendar:
        """Un agenda de plus (rangé, ou mis à jour s'il y est déjà)."""
        ...

    def drop_calendar(self, key: str) -> int: ...

    def clear_calendar(self, key: str) -> int:
        """Un agenda qu'on ne suit plus : sa copie part (ses événements, son curseur) ; lui reste."""
        ...

    def set_cursor(self, key: str, cursor: str, *, at: int | None = None) -> None:
        """Où la synchro de cet agenda en est."""
        ...

    # ses événements
    def event(self, event_id: int) -> Event | None: ...

    def find(self, calendar: str, uid: str, original: str = "") -> Event | None: ...

    def series(self, calendar: str, uid: str) -> list[Event]:
        """Une série et ses exceptions (la série d'abord), ou un événement simple."""
        ...

    def copies(self, origin: str, uid: str) -> list[Event]:
        """Les copies d'une invitation du système dans les agendas de ses invitées (toutes leurs lignes)."""
        ...

    def save(self, events: Sequence[Event] = (), *,
             removed: Sequence[tuple[str, str, str | None]] = ()) -> list[Event]:
        """En une écriture : ces lignes rangées (remplacées si elles y sont : même agenda, même uid, même occurrence),
        et celles-ci retirées (agenda, uid, clé d'occurrence ; ``None`` : la série entière). Rend les lignes rangées,
        avec leur numéro."""
        ...

    def apply(self, calendar: str, batch: SyncBatch, *, window: Window | None = None) -> int:
        """Ce qu'une synchronisation rapporte, rangé dans la copie de cet agenda, avec son curseur ; un lot complet
        retire ce qu'il ne nomme pas dans la fenêtre, et ce qui la précède part. Ce qu'un oubli a retiré n'y revient
        pas."""
        ...

    def period(self, calendars: Collection[str], start: int, end: int, *, declined: bool = False,
               zone: tzinfo | None = None) -> list[Occurrence]:
        """Les occurrences de [start, end[ (µs UTC) de ces agendas, dans l'ordre ; ``declined`` faux : sans ce que le
        compte de l'agenda a refusé ; ``zone`` : la période est faite de jours de ce fuseau (``start`` et ``end`` à
        ses minuits), où une journée entière se lit par ses dates (``occurrences``)."""
        ...

    def invitations(self, calendars: Collection[str]) -> list[Event]:
        """Ce qui attend une réponse du compte de ces agendas (``response`` en attente), par date."""
        ...

    def event_counts(self, calendars: Collection[str]) -> dict[str, int]:
        """Combien d'événements chacun de ces agendas garde (une série compte pour un, ses exceptions à part) : ce
        que la console en dit (lot 5)."""
        ...

    def remind(self, calendar: str, uid: str, original: str, value: str) -> bool:
        """« Mika te le rappelle » pour cet événement (cette ligne : une série, un événement simple ou une exception) :
        ``REMINDERS``, ou vide pour revenir au choix de son agenda. Gardé dans la base seulement ; faux s'il n'y est
        pas."""
        ...

    def rename(self, key: str, name: str) -> bool:
        """Le nom d'un agenda (lot 6) : celui d'un agenda du système change pour de bon ; un agenda branché prend un nom
        à lui dans Mika (vide : celui de son fournisseur revient), qu'une synchronisation ne touche pas. Faux s'il n'y
        est pas ; ``AgendaError`` pour un agenda du système sans nom."""
        ...

    async def forget(self, subject: str) -> int:
        """L'oubli d'une adresse (``mail:<adresse>``) ou d'une personne (sa clé) : voir ``adapters/agenda/store.py``."""
        ...

    def failing(self) -> list[str]:
        """Les comptes actifs dont la dernière synchronisation a échoué (la santé les nomme)."""
        ...

    # l'historique de sa synchro (lot 5)
    def note_sync(self, note: SyncNote, *, keep_us: int = 0) -> None:
        """Une ligne de plus à l'historique de la synchro de son compte ; ``keep_us`` : ce qui est plus ancien part."""
        ...

    def sync_notes(self, account: str, calendar: str = "", *, limit: int = 50, offset: int = 0) -> list[SyncNote]:
        """L'historique de la synchro d'un compte, le plus récent d'abord ; ``calendar`` : celui de cet agenda et ce
        qui touche tout son compte (une panne, sa reprise)."""
        ...

    def sync_notes_count(self, account: str, calendar: str = "") -> int: ...


class CalendarProvider(Protocol):
    """Un fournisseur d'agendas (une sorte de compte) : ce qu'il sait faire, ses agendas, sa synchronisation et ses
    écritures. Une écriture part chez lui tout de suite et rend l'événement tel qu'il le garde ; la copie se relit à la
    synchronisation suivante. Un refus se dit par ``AgendaError``, en mots."""

    kind: str

    def abilities(self, account: Connection) -> Abilities: ...

    async def calendars(self, account: Connection) -> list[Calendar]:
        """Les agendas de ce compte, tels qu'il les liste."""
        ...

    async def create_calendar(self, account: Connection, name: str) -> Calendar:
        """Un agenda neuf dans ce compte (``Abilities.calendars``)."""
        ...

    async def sync(self, account: Connection, calendar: Calendar, cursor: str, window: Window) -> SyncBatch:
        """Ce qui a changé depuis ce curseur (vide : tout, dans la fenêtre)."""
        ...

    async def create(self, account: Connection, calendar: Calendar, draft: EventDraft) -> Event: ...

    async def edit(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, change: EventChange,
                   scope: str = ALL) -> Event:
        """``event`` : la ligne gardée (la série, une exception, l'événement simple) ; ``occurrence`` : la clé de
        l'occurrence visée d'une série (vide : la série ou l'événement simple) ; ``scope`` : ``ONE``, ``FOLLOWING``,
        ``ALL``."""
        ...

    async def delete(self, account: Connection, calendar: Calendar, event: Event, occurrence: str,
                     scope: str = ALL) -> int: ...

    async def respond(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, response: str,
                      scope: str = ALL, comment: str = "") -> Event:
        """La réponse du compte à une invitation (``YES``, ``MAYBE``, ``NO``)."""
        ...


class AgendaDesk(Protocol):
    """Ce que la console change d'un compte d'agenda dans les réglages, sans jamais écrire dans ses agendas (ADR 0309,
    lot 5) : le décocher ou le recocher, suivre ou ne plus suivre un de ses agendas, oublier sa connexion Google ou
    Microsoft (et la retirer chez Google). Le port ``agenda_desk`` (``app/agenda_desk.py``) : chaque changement est
    écrit sous le verrou des réglages, puis les paramètres du plugin se rejournalisent. Chacun rend vrai s'il a changé
    quelque chose ; ``ValueError`` : un compte ou un agenda inconnu."""

    async def enable(self, account: str, enabled: bool) -> bool: ...

    async def follow(self, calendar: str, followed: bool | None) -> bool: ...

    async def disconnect(self, account: str) -> bool: ...


class AgendaProviders(Protocol):
    """Les fournisseurs, par sorte, et les comptes que les réglages déclarent (leurs identifiants ouverts)."""

    def of(self, kind: str) -> CalendarProvider | None: ...

    def connections(self) -> list[Connection]:
        """Les comptes déclarés dans les réglages (ceux du système d'une personne n'y sont que s'ils ont été
        réglés)."""
        ...

    def connection(self, key: str) -> Connection | None:
        """Un compte, celui du système d'une personne compris (même jamais réglé)."""
        ...


__all__ = [
    "ALERTS_MAX", "ALERT_METHODS", "ALERT_MINUTES_MAX", "ALL", "BY_HER", "CALDAV", "CALENDAR_SEP", "CANCELLED", "CONFIRMED", "DATES_MAX", "DAY_US", "DEFAULT_CALENDAR",
    "DEFAULT_CALENDAR_NAME", "DEFAULT_REMINDERS", "EMAIL", "EPOCH", "FOLLOWING", "FOREVER", "GOOGLE", "ICAL", "KINDS", "KIND_WORDS",
    "LOCAL_MAX", "MAYBE", "MICROSOFT", "NEEDS", "NO", "NOTIFY", "OCCURRENCES_MAX", "ONE", "REMINDERS", "RESPONSES", "STATUSES",
    "SYNC_DROPPED", "SYNC_FAILED", "SYNC_FULL", "SYNC_READ", "SYNC_RECOVERED", "SYNC_WHATS", "SYNC_WRITTEN",
    "SYSTEM", "SYSTEM_PREFIX", "TENTATIVE", "US_PER_S", "WINDOW_AHEAD_US", "WINDOW_PAST_US", "YES",
    "Abilities", "AccountState", "AddedBy", "Alert", "AgendaDesk", "AgendaError", "AgendaPort", "AgendaProviders", "Calendar",
    "CalendarProvider", "Connection", "Event", "EventChange", "EventDraft", "Kind", "Occurrence", "Participant",
    "Recurrence", "Reminder", "Response", "Scope", "Span", "SyncBatch", "SyncNote", "Window",
    "address_print", "alerts_of", "at_us", "blanked", "calendar_key", "counted_before", "day_at", "day_of",
    "default_reminder", "expand", "follows", "instance", "key_instant", "local_days", "local_key", "masked", "occurrence_key",
    "occurrences", "owner_of", "readable_key", "rule_parts", "rule_text", "series_end", "shifted_key", "split_calendar_key",
    "split_rule", "sync_window", "system_account", "system_person", "us_of", "whole_days", "zone_of",
]
