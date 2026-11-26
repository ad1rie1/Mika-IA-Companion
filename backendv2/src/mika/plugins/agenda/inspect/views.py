"""L'agenda dans la console (ADR 0309, lot 5) : Échanges › Agendas, la fiche d'un agenda, l'onglet « Agendas » de la
fiche d'une personne, et ce qu'un opérateur y fait.

- **Échanges › Agendas** (``SECTION``) : « Tous les agendas » — ceux de chaque personne, choisis par personne
  (``?qui=`` : ``toi``, la clé d'une personne, ``mika`` ; plusieurs, séparés par des virgules), une période (``?du=``,
  ``?vue=`` : semaine, mois ou liste), le compte à reconnecter en bandeau ; « Comptes » ; « Ce qu'elle en fait » (ses
  rappels, ce qu'elle a proposé d'ajouter, les réponses d'invitation qu'elle a préparées, ce qu'elle a ajouté seule) ;
  « L'agenda de <son nom> » (sa mémoire montrée comme un agenda, lue par la console : ``app/domains/agenda/her.py``). Ces vues sont la
  source de la console en MCP et du repli ; la console les dessine à sa façon (``app/domains/agenda/console/tabs.py``).
- **La fiche d'un agenda** (``KIND``, sa clé ``<compte>~<clé courte>``) : son en-tête (l'état de sa synchro, sa sorte,
  à qui il est, ses partages), ses événements (paginés, à venir ou passés), ses partages dans Mika, son tableau de
  droits, sa synchronisation (son historique, ``AgendaPort.sync_notes``).
- **Ce qu'un opérateur y fait** (ADR 0309) : il lit — un événement privé d'une autre personne reste « Occupé » —,
  synchronise (« Synchroniser maintenant »), déconnecte un compte (Google ou Microsoft : sa connexion oubliée ; CalDAV
  ou un abonnement : décoché), retire un agenda de Mika (sa copie part, rien chez son fournisseur), retire un partage
  (Réglages › Droits) ; il ne se reconnecte qu'à ses propres comptes. Il ne crée, ne modifie ni ne répond jamais à la
  place de quelqu'un : aucune action ici n'écrit dans un agenda. Ce qui change les réglages passe par le port
  ``agenda_desk`` (``app/domains/agenda/store.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import agenda as agenda_c
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.kernel.clock import MINUTE, instant, local
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    VIEWER,
    ActionSlot,
    Badge,
    Block,
    Column,
    Fields,
    Found,
    Head,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Param,
    Ref,
    Row,
    Table,
    Text,
    Toolbar,
    When,
    paginate,
    plural,
)
from mika.kernel.operate import ActionContext, Done, Refused
from mika.plugins.agenda import (
    AGENDA,
    APPROVED,
    CREATE,
    DONE,
    FAILED,
    REFUSED,
    RESPOND,
    SYNC_ASKED,
    WAITING,
    AgendaState,
    Written,
    owner,
    params_of,
    reminder,
)
from mika.plugins.agenda.actions import account_level, level_of, operator, person_of
from mika.plugins.agenda.rights import table_of
from mika.plugins.agenda.when import midnight
from mika.ports.agenda import (
    BY_HER,
    CALDAV,
    GOOGLE,
    ICAL,
    KIND_WORDS,
    MICROSOFT,
    NEEDS,
    REMINDERS,
    SYNC_DROPPED,
    SYNC_FAILED,
    SYNC_FULL,
    SYNC_READ,
    SYNC_RECOVERED,
    SYNC_WRITTEN,
    SYSTEM,
    AccountState,
    AgendaError,
    Calendar,
    Event,
    Occurrence,
    follows,
    masked,
    split_calendar_key,
    system_person,
)
from mika.ports.mail import SIGNED_IN, SIGNIN_PENDING
from mika.vocab.access import KEEP_WORDS, PERSON, SHARES, WRITE_WORDS, canal_words, when_words, who_words
from mika.vocab.ownership import OWNED
from mika.vocab.people import ACCOUNT_PREFIX
from mika.vocab.rights import rights_of

#: la destination de la console, la fiche d'un agenda
SECTION, KIND = "agendas", "agenda"
#: « Les agendas de » (``?qui=``) : toi (ce qui est à toi, et à une de ses propriétaires), une personne par sa clé, elle
WHOSE, YOURS, HER = "qui", "toi", "mika"
#: la vue de Tous les agendas, la période (le premier jour), l'événement ouvert, les agendas qu'on ne montre pas
VIEW, FROM, OPEN, HIDDEN = "vue", "du", "ev", "masques"
WEEK, MONTH, LIST = "semaine", "mois", "liste"
VIEWS = ((WEEK, "Semaine"), (MONTH, "Mois"), (LIST, "Liste"))
#: la fiche d'un agenda : ses événements à venir ou passés
PERIOD, UPCOMING, PAST = "periode", "a_venir", "passes"
PERIODS = ((UPCOMING, "À venir"), (PAST, "Passés"))
#: par page : les événements d'un agenda, les comptes, l'historique de sa synchro, ce qu'elle a fait
EVENTS_PAGE, ACCOUNTS_PAGE, NOTES_PAGE, DONE_PAGE = 10, 50, 25, 30
#: un événement privé d'une autre personne, tel que la console le dit
BUSY = "Occupé · privé"
NO_PORT = "L'agenda n'est pas branché sur ce serveur."
#: une sorte en mots courts, pour une étiquette
KIND_SHORT = {SYSTEM: "Système", GOOGLE: "Google Agenda", MICROSOFT: "Outlook.com", CALDAV: "CalDAV",
              ICAL: "Abonnement iCal"}
#: comment chaque sorte se relit
SYNC_MODE = {SYSTEM: "rien à relire : il est sur ce serveur", GOOGLE: "le jeton de synchro de Google",
             MICROSOFT: "le delta de Graph", CALDAV: "sync-collection, sinon l'étiquette de chaque événement",
             ICAL: "le fichier entier"}
#: l'historique de la synchro, en mots
NOTE_WORDS = {SYNC_READ: ("relu", ""), SYNC_FULL: ("relu en entier", "info"), SYNC_WRITTEN: ("écrit, puis relu", ""),
              SYNC_FAILED: ("erreur", "warn"), SYNC_RECOVERED: ("reprise", "ok"),
              SYNC_DROPPED: ("plus suivi : sa copie est partie", "")}
#: « Mika te le rappelle », en mots
REMINDER_WORDS = {k: v.lower() for k, v in REMINDERS}
#: ce qu'elle a proposé d'écrire, en mots
WRITE_STATUS = {WAITING: ("attend un accord", "warn"), APPROVED: ("accepté, en cours", "info"),
                REFUSED: ("refusé", ""), DONE: ("fait", "ok"), FAILED: ("raté", "danger")}
OP_WORDS = {CREATE: "ajouter", "modifier": "modifier", "supprimer": "supprimer", RESPOND: "répondre"}
#: un rappel, en mots
REMINDED_WORDS = {agenda_c.DUE: ("dû", "warn"), agenda_c.TOLD: ("dit", "ok"), agenda_c.DROPPED: ("tombé", "")}
DROPPED_WHY = {"deplace": "le rendez-vous a bougé", "parti": "le rendez-vous est parti (supprimé, annulé, refusé)",
               "coupe": "son agenda ne le demande plus"}


# ── ce que la console lit d'un agenda ──


def is_owner(frame: Frame, person: str) -> bool:
    """Une de ses propriétaires (ce qui est « à toi » est à elle)."""
    return person in set(frame.get(identity_c.OWNERS) or ())


def name_of(frame: Frame, person: str) -> str:
    return identity_c.person_name(frame, person) or str(
        getattr(frame.get(identity_c.IDENTITY(person)), "name", "") or person)


def who_of(frame: Frame, holder: str) -> str:
    """Sa clé dans « Les agendas de » : ``toi`` pour ce qui est à toi ou à une de ses propriétaires, sinon la clé de la
    personne."""
    if not holder:
        return YOURS
    person = holder[len(PERSON):]
    return YOURS if is_owner(frame, person) else person


def whose_words(frame: Frame, who: str) -> str:
    """À qui, en mots : « toi », le nom d'une personne."""
    return "toi" if who == YOURS else name_of(frame, who)


def chosen(raw: str) -> set[str]:
    """Les personnes choisies (``?qui=``) ; vide : tout le monde."""
    return {x.strip() for x in raw.split(",") if x.strip()}


@dataclass(frozen=True, slots=True)
class Shown:
    """Un agenda tel que la console le montre : sa sorte, à qui il est (``holder`` : vide pour toi), sa clé dans « Les
    agendas de » (``who``), masqué par son propriétaire, son compte décoché, suivi, l'état de son compte, ses partages,
    son rappel."""

    cal: Calendar
    kind: str
    holder: str
    who: str
    hidden: bool
    off: bool
    followed: bool
    state: AccountState | None
    shares: Mapping[str, str]
    reminder: str

    @property
    def key(self) -> str:
        return self.cal.key

    @property
    def account(self) -> str:
        return self.cal.account

    @property
    def name(self) -> str:
        return self.cal.name or split_calendar_key(self.cal.key)[1]

    @property
    def system(self) -> bool:
        return self.kind == SYSTEM

    @property
    def read_only(self) -> bool:
        return self.kind == ICAL or not self.cal.writable


def kind_of(p: Any, store: Any, account: str) -> str:
    if system_person(account):
        return SYSTEM
    if account in p.kinds:
        return str(p.kinds[account])
    state = store.account(account) if store is not None else None
    return state.kind if state is not None else ""


def shown_calendars(ports: Mapping[str, Any], frame: Frame) -> list[Shown]:
    """Chaque agenda du serveur, rangé : les tiens d'abord, puis ceux de chaque personne par son nom ; dans chacun, le
    principal d'abord, puis par nom."""
    store, providers = ports.get("agenda"), ports.get("agenda_providers")
    if store is None:
        return []
    p = params_of(frame)
    states = {a.key: a for a in store.accounts()}
    out = []
    for cal in store.calendars():
        account = cal.account
        holder = owner(p, account)
        conn = providers.connection(account) if providers is not None else None
        kind = kind_of(p, store, account)
        out.append(Shown(cal=cal, kind=kind, holder=holder, who=who_of(frame, holder), hidden=cal.key in p.hidden,
                         off=account in p.accounts_off, followed=follows(conn, cal) if conn is not None else True,
                         state=states.get(account), shares=dict(p.shares.get(cal.key, {})),
                         reminder=reminder(p, cal.key, kind)))
    return sorted(out, key=lambda c: (c.who != YOURS, whose_words(frame, c.who).casefold(), c.kind != SYSTEM,
                                      not c.cal.primary, c.name.casefold()))


def shown_one(ports: Mapping[str, Any], frame: Frame, key: str) -> Shown | None:
    return next((c for c in shown_calendars(ports, frame) if c.key == key), None)


def sees_private(frame: Frame, calendar: str) -> bool:
    """Qui regarde la console (``kernel.inspect.VIEWER``) lit-il les événements privés de cet agenda : en est-il le
    propriétaire ? Un agenda « à toi » est à ses propriétaires, pas à tout opérateur ; sans personne de connu (le
    serveur MCP), personne."""
    viewer = VIEWER.get()
    return bool(viewer) and level_of(params_of(frame), frame, person_of(frame, viewer), calendar) == OWNED


def private_for_console(frame: Frame, shown: Shown, e: Event) -> Event:
    """Un événement tel que la console le montre : privé, « Occupé » pour quiconque n'en est pas propriétaire (ADR
    0309 : l'opérateur lit, un événement privé reste privé)."""
    return masked(e) if e.private and not sees_private(frame, shown.key) else e


def signin_of(ports: Mapping[str, Any], kind: str, account: str) -> Any:
    """Où en est la connexion Google ou Microsoft d'un compte (``None`` : il n'en a pas)."""
    providers = ports.get("agenda_providers")
    if providers is None or kind not in (GOOGLE, MICROSOFT):
        return None
    signin = getattr(providers.of(kind), "signin", None)
    conn = providers.connection(account)
    if signin is None or conn is None:
        return None
    try:
        return signin.state(account) if kind == GOOGLE else signin.state(account, conn)
    except (AgendaError, OSError, RuntimeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class Synced:
    """L'état de la synchro d'un compte, en mots : son ton (``ok``, ``warn``…), son étiquette, quand, l'erreur en mots,
    s'il est à reconnecter."""

    tone: str
    label: str
    when: str
    error: str = ""
    reconnect: bool = False


def synced(ports: Mapping[str, Any], frame: Frame, c: Any, when: Any) -> Synced:
    """La synchro du compte de cet agenda (un ``Shown``) ou de ce compte (un ``Account``), dite ; ``when`` : un instant
    en mots (``ctx.when``)."""
    s = c.state
    if c.kind == SYSTEM:
        return Synced("ok", "à jour", "sur ce serveur")
    if c.off:
        return Synced("", "décoché", "ne se synchronise plus ; ce qui est gardé reste, figé")
    signed = signin_of(ports, c.kind, c.account)
    if signed is not None and signed.state != SIGNED_IN:
        last = f"dernière synchro réussie {when(s.synced_at)}" if s is not None and s.synced_at else "jamais relu"
        pending = signed.state == SIGNIN_PENDING
        said = (s.error if s is not None and s.error else signed.error) if s is not None and s.synced_at else \
            "Jamais connecté : son propriétaire le connecte dans son espace (Paramètres › Agendas)."
        return Synced("warn", "connexion en cours" if pending else "à reconnecter", last, said, reconnect=True)
    if s is None or not s.tried_at:
        return Synced("", "pas encore relu", "au prochain passage")
    if s.failures:
        last = f"dernière synchro réussie {when(s.synced_at)}" if s.synced_at else "jamais relu"
        return Synced("warn", "en panne", last, s.error)
    return Synced("ok", "relu" if c.kind == ICAL else "synchronisé", when(s.synced_at))


@dataclass(frozen=True, slots=True)
class Account:
    """Un compte d'agenda tel que la console le montre : sa clé, sa sorte, à qui il est (``holder``, ``who``), son
    état, décoché, ses agendas (ceux de la base ; un compte jamais relu n'en a pas encore)."""

    account: str
    kind: str
    holder: str
    who: str
    state: AccountState | None
    off: bool
    calendars: tuple[Shown, ...]

    @property
    def system(self) -> bool:
        return self.kind == SYSTEM


def shown_accounts(ports: Mapping[str, Any], frame: Frame, calendars: Sequence[Shown] | None = None) -> list[Account]:
    """Chaque compte d'agenda : ceux qu'ont ses agendas, et ceux des réglages qui n'en ont pas encore (jamais relus,
    une connexion à faire)."""
    store = ports.get("agenda")
    if store is None:
        return []
    p = params_of(frame)
    cals = list(calendars) if calendars is not None else shown_calendars(ports, frame)
    keys = list(dict.fromkeys([c.cal.account for c in cals] + sorted(p.kinds)))
    out = []
    for key in keys:
        holder = owner(p, key)
        mine = tuple(c for c in cals if c.cal.account == key)
        out.append(Account(account=key, kind=kind_of(p, store, key), holder=holder, who=who_of(frame, holder),
                           state=mine[0].state if mine else store.account(key), off=key in p.accounts_off,
                           calendars=mine))
    return sorted(out, key=lambda a: (a.who != YOURS, whose_words(frame, a.who).casefold(), a.kind != SYSTEM,
                                      a.account))


def count_events(ports: Mapping[str, Any], keys: Sequence[str]) -> dict[str, int]:
    store = ports.get("agenda")
    return store.event_counts(keys) if store is not None and keys else {}


# ── Échanges › Agendas : les vues de la destination ──


def view_link(view: str, text: str = "", **params: str) -> Ref:
    return Ref.view(AGENDA.name, view, text, **{k: v for k, v in params.items() if v})


def people_nav(frame: Frame, calendars: Sequence[Shown], ctx: InspectContext, view: str, *,
               her: bool = True) -> Nav:
    """« Les agendas de » : tout le monde, toi, chaque personne qui a un agenda, elle."""
    picked = chosen(ctx.param(WHOSE))
    keys = list(dict.fromkeys(c.who for c in calendars))
    if YOURS not in keys:
        keys.insert(0, YOURS)
    items = [NavItem("Tout le monde", view_link(view), active=not picked)]
    for who in [*keys, *((HER,) if her else ())]:
        text = "Toi" if who == YOURS else "Elle" if who == HER else name_of(frame, who)
        items.append(NavItem(text, view_link(view, "", qui=who), active=who in picked))
    return Nav(tuple(items), title="Les agendas de")


def _shown_to(calendars: Sequence[Shown], picked: set[str]) -> list[Shown]:
    return [c for c in calendars if not picked or c.who in picked]


def reconnect_notes(ports: Mapping[str, Any], frame: Frame, accounts: Sequence[Account], when: Any) -> list[Note]:
    """Un bandeau par compte à reconnecter ou en panne, parmi ceux qu'on montre."""
    out = []
    for a in accounts:
        said = synced(ports, frame, a, when)
        if said.tone == "warn":
            out.append(Note(f"{said.label.capitalize()} : {said.when}. {said.error}".strip(), tone="warn",
                            title=f"Un compte de {whose_words(frame, a.who)}"))
    return out


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def period_of(ctx: InspectContext, frame: Frame) -> tuple[date, date]:
    """La période de Tous les agendas : la semaine (ou le mois) du jour demandé (``?du=``), sinon d'aujourd'hui."""
    tz = frame.env.tz_of(frame.root)
    try:
        day = date.fromisoformat(ctx.param(FROM)) if ctx.param(FROM) else local(frame.now, tz).date()
    except ValueError:
        day = local(frame.now, tz).date()
    if ctx.param(VIEW) == MONTH:
        first = day.replace(day=1)
        start = week_of(first)
        last = (first.replace(year=first.year + 1, month=1) if first.month == 12
                else first.replace(month=first.month + 1)) - timedelta(days=1)
        return start, week_of(last) + timedelta(days=6)
    start = week_of(day)
    return start, start + timedelta(days=6)


def bounds(frame: Frame, first: date, last: date) -> tuple[int, int]:
    tz = frame.env.tz_of(frame.root)
    return midnight(first, tz), midnight(last + timedelta(days=1), tz)


def occurrences_of(ports: Mapping[str, Any], frame: Frame, calendars: Sequence[Shown], start: int,
                   end: int) -> list[tuple[Shown, Occurrence]]:
    """Les occurrences de ces agendas sur [start, end[ (des jours du fuseau du serveur, ``bounds`` : une journée
    entière s'y lit par ses dates), chacune avec son agenda ; un événement privé d'une autre personne, « Occupé »."""
    store = ports.get("agenda")
    if store is None or not calendars:
        return []
    by_key = {c.key: c for c in calendars}
    out = []
    for o in store.period(list(by_key), start, end, zone=frame.env.tz_of(frame.root)):
        c = by_key.get(o.event.calendar)
        if c is not None:
            out.append((c, Occurrence(private_for_console(frame, c, o.event), o.key, o.span)))
    return out


def title_of(e: Event) -> str:
    if e.private and not e.title:
        return BUSY
    return e.title or ("(sans titre)" if not e.forgotten else "Occupé")


def _state_badge(e: Event) -> Badge:
    if e.response == NEEDS:
        return Badge("invitation sans réponse", "warn")
    if e.added is not None and e.added.by == BY_HER:
        return Badge("ajouté par elle", "info")
    if e.private:
        return Badge("privé")
    return Badge("")


@AGENDA.inspect("tous", title="Tous les agendas", section=SECTION, order=10,
                params=(Param(WHOSE, "Les agendas de", "hidden"), Param(FROM, "Du", "hidden"),
                        Param(OPEN, "Événement", "hidden"), Param(HIDDEN, "Agendas masqués", "hidden"),
                        Param(VIEW, "Affichage", "select", VIEWS, default=WEEK)),
                description="Les agendas de chaque personne qui a un compte, et le sien, dans une même vue : choisis "
                            "de qui, coche les agendas à montrer.")
def _all(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if ctx.ports.get("agenda") is None:
        return [Note(NO_PORT, tone="muted")]
    calendars = shown_calendars(ctx.ports, frame)
    picked = chosen(ctx.param(WHOSE))
    shown = _shown_to(calendars, picked)
    first, last = period_of(ctx, frame)
    start, end = bounds(frame, first, last)
    found = occurrences_of(ctx.ports, frame, [c for c in shown if not c.hidden], start, end)

    def row(c: Shown, o: Occurrence) -> Row:
        e = o.event
        return Row((When(o.span.start), Text(title_of(e)), Text(c.name), Text(whose_words(frame, c.who), "muted"),
                    Text(e.location or "—", "muted"), _state_badge(e)),
                   href=Ref.subject(KIND, c.key, c.name))

    blocks: list[Block] = [Toolbar((ActionSlot(f"{AGENDA.name}.synchroniser", title="Tout synchroniser",
                                               presentation="button"),)),
                           people_nav(frame, calendars, ctx, "tous"),
                           *reconnect_notes(ctx.ports, frame, [a for a in shown_accounts(ctx.ports, frame, calendars)
                                                               if not picked or a.who in picked], ctx.when)]
    blocks.append(Table((Column("quand", "fit"), Column("événement", role="title"), Column("agenda"),
                         Column("à qui", "fit"), Column("lieu"), Column("état", "fit", role="badge")),
                        tuple(row(c, o) for c, o in found),
                        title=f"Du {first.isoformat()} au {last.isoformat()} ({len(found)})",
                        empty="rien sur cette période"))
    return blocks


def accounts_badge(s: AgendaState, frame: Frame, ports: Mapping[str, Any]) -> tuple[int, str]:
    """Le badge de l'onglet Comptes : les comptes à reconnecter ou en panne."""
    n = sum(1 for a in shown_accounts(ports, frame) if synced(ports, frame, a, str).tone == "warn")
    return n, plural(n, "compte d'agenda à reconnecter ou en panne", "comptes d'agenda à reconnecter ou en panne")


@AGENDA.inspect("comptes", title="Comptes", section=SECTION, order=20, badge=accounts_badge,
                description="Chaque compte d'agenda branché sur ce serveur : son fournisseur, à qui il est, ses "
                            "agendas, où en est sa synchro, avec qui il est partagé. Chacun branche les siens dans son "
                            "espace (Paramètres › Agendas).")
def _accounts(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if ctx.ports.get("agenda") is None:
        return [Note(NO_PORT, tone="muted")]
    calendars = shown_calendars(ctx.ports, frame)
    picked = chosen(ctx.param(WHOSE))
    rows = []
    for a in shown_accounts(ctx.ports, frame, calendars):
        if picked and a.who not in picked:
            continue
        said = synced(ctx.ports, frame, a, ctx.when)
        shared = sorted({f"{x.name} → {name_of(frame, who[len(PERSON):])}" for x in a.calendars for who in x.shares})
        first = a.calendars[0] if a.calendars else None
        rows.append(Row((Text(account_label(a)), Text(KIND_SHORT.get(a.kind, a.kind), "muted"),
                         Text(whose_words(frame, a.who)), Text(", ".join(x.name for x in a.calendars) or "—"),
                         Badge(said.label, said.tone), Text(said.error or said.when, "muted"),
                         Text(", ".join(shared) or "—", "muted")),
                        href=Ref.subject(KIND, first.key, first.name) if first is not None else None,
                        tone="warn" if said.tone == "warn" else ""))
    page, pager = paginate(rows, ctx.pager(size=ACCOUNTS_PAGE))
    return [Toolbar((ActionSlot(f"{AGENDA.name}.synchroniser", title="Tout synchroniser", presentation="button"),)),
            people_nav(frame, calendars, ctx, "comptes", her=False),
            Table((Column("compte", role="title"), Column("sorte", "fit"), Column("à qui", "fit"),
                   Column("ses agendas"), Column("synchro", "fit", role="badge"), Column("depuis"),
                   Column("partagé ici avec")), tuple(page), title=f"Comptes d'agenda ({len(rows)})",
                  pager=pager, empty="aucun compte d'agenda")]


def account_label(c: Any) -> str:
    """Le nom d'un compte (d'un ``Shown`` ou d'un ``Account``) : « Ce serveur » pour le système, son adresse sinon (ou sa
    clé)."""
    if c.kind == SYSTEM:
        return "Ce serveur"
    return (c.state.address if c.state is not None and c.state.address else "") or c.account


def writes_of(s: AgendaState, *, op: str = "", approval: bool | None = None) -> list[Written]:
    """Ce qu'elle a proposé d'écrire, le plus récent d'abord."""
    return sorted((w for w in s.writes.values() if (not op or w.op == op)
                   and (approval is None or w.approval == approval)), key=lambda w: -w.proposal)


def waiting_count(s: AgendaState, frame: Frame) -> tuple[int, str]:
    """Le badge de « Ce qu'elle en fait » : ce qui attend un accord (une proposition d'ajout, une réponse
    d'invitation…)."""
    n = sum(1 for w in s.writes.values() if w.status == WAITING and w.approval)
    return n, plural(n, "écriture d'agenda attend un accord", "écritures d'agenda attendent un accord")


@AGENDA.inspect("fait", title="Ce qu'elle en fait", section=SECTION, order=30, badge=waiting_count,
                description="Ce qu'elle a fait des agendas : ses rappels, ce qu'elle a proposé d'ajouter, les réponses "
                            "d'invitation qu'elle a préparées, ce qu'elle a ajouté seule — chacun avec la conversation "
                            "d'où il vient.")
def _done(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    names = {c.key: c.name for c in shown_calendars(ctx.ports, frame)}

    def write_row(w: Written) -> Row:
        label, tone = WRITE_STATUS.get(w.status, (w.status, ""))
        return Row((When(w.at), Text(OP_WORDS.get(w.op, w.op)), Text(names.get(w.calendar, w.calendar)),
                    Badge(label, tone), Text(name_of(frame, str(frame.get(identity_c.PERSON(w.target)) or w.target))
                                             if w.target else "—", "muted")))

    reminders = sorted(s.reminders.values(), key=lambda r: -r.due_at)
    rem_rows = [Row((When(r.due_at), Text(names.get(r.calendar, r.calendar)), Badge(*REMINDED_WORDS.get(
        r.status, (r.status, ""))), Text(name_of(frame, r.person), "muted"),
                     Text(DROPPED_WHY.get(r.why, r.why) or REMINDER_WORDS.get(r.delay, r.delay), "muted")))
                for r in reminders[:DONE_PAGE]]
    columns = (Column("quand", "fit"), Column("quoi"), Column("agenda"), Column("où en est", "fit", role="badge"),
               Column("pour", "fit"))
    return [Table((Column("dû", "fit"), Column("agenda"), Column("où en est", "fit", role="badge"),
                   Column("pour", "fit"), Column("délai")), tuple(rem_rows), title="Ses rappels",
                  empty="aucun rappel pour l'instant"),
            Table(columns, tuple(write_row(w) for w in writes_of(s, op=CREATE, approval=True)[:DONE_PAGE]),
                  title="Propositions d'ajout", empty="aucune proposition"),
            Table(columns, tuple(write_row(w) for w in writes_of(s, op=RESPOND)[:DONE_PAGE]),
                  title="Réponses d'invitation", empty="aucune réponse préparée"),
            Table(columns, tuple(write_row(w) for w in writes_of(s, approval=False)[:DONE_PAGE]),
                  title="Ajouté seule", empty="rien d'ajouté sans demander")]


@AGENDA.inspect("mika", title=f"L'agenda de {self_c.NAME_SLOT}", section=SECTION, order=40,
                description="Ce qu'elle a promis pour une date, ce qu'elle voit venir dans la vie de chacun et les "
                            "dates qui reviennent, montrés comme un agenda. Rien n'y est recopié : c'est sa mémoire.")
def _hers(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return [Note("Sa mémoire, montrée comme un agenda : la console la lit (ses promesses datées, les moments de la vie "
                 "de chacun, ce qu'elle voit venir). On ne l'édite pas : on le lui dit.", tone="info"),
            Nav((NavItem("Ses promesses", Ref.view("memory", "promesses", "Ses promesses")),
                 NavItem("La vie des autres", Ref.view("memory", "moments", "La vie des autres"))),
                title="Dans sa mémoire")]


# ── la fiche d'un agenda ──


@AGENDA.subject(KIND, label="Agenda", plural="Agendas", icon="📅")
def _head(s: AgendaState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    c = shown_one(ctx.ports, frame, key)
    if c is None:
        return None
    said = synced(ctx.ports, frame, c, ctx.when)
    badges = [Badge(said.label, said.tone), Badge(KIND_SHORT.get(c.kind, c.kind)),
              Badge(f"à {whose_words(frame, c.who)}", "info")]
    if c.shares:
        badges.append(Badge(f"partagé · {len(c.shares)}", "info"))
    if c.hidden:
        badges.append(Badge("masqué"))
    facts: list[tuple[str, Any]] = [("fournisseur", KIND_WORDS.get(c.kind, c.kind)),
                                    ("compte", account_label(c)),
                                    ("propriétaire", whose_words(frame, c.who))]
    if not c.system:
        facts.append(("dernière synchro", said.when))
    return Head(key=key, title=c.name, badges=tuple(badges), facts=tuple(facts),
                back=view_link("tous", "Tous les agendas"), default_tab="evenements")


@AGENDA.search(KIND)
def _search(s: AgendaState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    words = text.casefold().strip()
    return [Found(c.key, c.name, f"{KIND_SHORT.get(c.kind, c.kind)} · à {whose_words(frame, c.who)}")
            for c in shown_calendars(ctx.ports, frame) if not words or words in c.name.casefold()][:limit]


def event_rows(ports: Mapping[str, Any], frame: Frame, c: Shown, past: bool, ctx: InspectContext) -> list[Occurrence]:
    """Les occurrences d'un agenda dans la fenêtre de la synchro : à venir (de maintenant à un an) ou passées (les 90
    derniers jours, les plus récentes d'abord)."""
    store = ports.get("agenda")
    if store is None:
        return []
    p = params_of(frame)
    now = frame.now
    if past:
        found = store.period([c.key], now - p.past_us, now)
        return [Occurrence(private_for_console(frame, c, o.event), o.key, o.span)
                for o in reversed(found) if o.span.end <= now]
    found = store.period([c.key], now, now + p.ahead_us)
    return [Occurrence(private_for_console(frame, c, o.event), o.key, o.span) for o in found]


@AGENDA.inspect("evenements", title="Événements", subject=KIND, order=10,
                params=(Param(PERIOD, "Période", "select", PERIODS, default=UPCOMING),),
                description="Ses événements dans la fenêtre que la synchro tient (90 jours derrière, un an devant).")
def _events(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    c = shown_one(ctx.ports, frame, ctx.subject)
    if c is None:
        return [Note("Cet agenda n'est plus là.", tone="warn")]
    found = event_rows(ctx.ports, frame, c, ctx.param(PERIOD) == PAST, ctx)
    page, pager = paginate(found, ctx.pager(size=EVENTS_PAGE))
    rows = tuple(Row((When(o.span.start), Text(title_of(o.event)), Text(o.event.location or "—", "muted"),
                      _state_badge(o.event))) for o in page)
    return [Table((Column("quand", "fit"), Column("événement", role="title"), Column("lieu"),
                   Column("état", "fit", role="badge")), rows, title=f"Événements ({len(found)})", pager=pager,
                  empty="aucun événement sur cette période")]


@AGENDA.inspect("partages", title="Partages", subject=KIND, order=20,
                description="Avec qui il est partagé sur ce serveur, et à quel niveau. Un partage chez Google ou "
                            "Microsoft ne passe pas par ici.")
def _shares(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    c = shown_one(ctx.ports, frame, ctx.subject)
    if c is None:
        return [Note("Cet agenda n'est plus là.", tone="warn")]
    levels = dict(SHARES)
    rows = tuple(Row((Text(name_of(frame, who[len(PERSON):])), Badge(levels.get(level, level), "info")),
                     href=Ref.subject("person", who[len(PERSON):], name_of(frame, who[len(PERSON):])))
                 for who, level in sorted(c.shares.items()))
    return [Table((Column("avec", role="title"), Column("niveau", "fit", role="badge")), rows,
                  title=f"Partagé ici ({len(rows)})", empty="partagé avec personne ici")]


def rule_words(frame: Frame, line: Any) -> tuple[str, ...]:
    """Une ligne de son tableau de droits, en mots."""
    return (who_words(line.who, lambda p: name_of(frame, p)) if line.who else "—", canal_words(line.canal),
            when_words(line.when), "oui" if line.read else "non", WRITE_WORDS[line.write],
            WRITE_WORDS[line.respond], KEEP_WORDS[line.keep])


@AGENDA.inspect("droits", title="Droits", subject=KIND, order=30,
                description="Son tableau de droits : qui, par où, quand ; lire, ajouter, répondre aux invitations, ce "
                            "qu'elle en garde. Réglé par son propriétaire, ou par un opérateur dans Réglages › Droits.")
def _rights(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    c = shown_one(ctx.ports, frame, ctx.subject)
    if c is None:
        return [Note("Cet agenda n'est plus là.", tone="warn")]
    table = table_of(params_of(frame), rights_of(frame.env), c.key)
    columns = ("qui", "par où", "quand", "lire", "ajouter, modifier, supprimer", "répondre aux invitations",
               "ce qu'elle en garde")
    rows = tuple(rule_words(frame, line) for line in table.lines)
    return [Table(columns, (*rows, ("Par défaut", "—", "—", *rule_words(frame, table.default)[3:])),
                  title=f"Qui peut quoi sur {c.name}"),
            Note("Son propriétaire le règle dans son espace (Outils › Droits) ; un opérateur, dans Réglages › Droits "
                 "(le détail des accès de cet agenda).", tone="muted")]


@AGENDA.inspect("synchro", title="Synchronisation", subject=KIND, order=40,
                description="Comment il se relit, son historique : les relectures qui ont changé quelque chose, les "
                            "écritures, les pannes et leur reprise.")
def _sync(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    c = shown_one(ctx.ports, frame, ctx.subject)
    if c is None:
        return [Note("Cet agenda n'est plus là.", tone="warn")]
    store = ctx.ports.get("agenda")
    said = synced(ctx.ports, frame, c, ctx.when)
    fields = Fields((("comment", SYNC_MODE.get(c.kind, "—")), ("état", Badge(said.label, said.tone)),
                     ("depuis", said.when), ("erreur", said.error or "—"),
                     ("pannes d'affilée", str(c.state.failures if c.state is not None else 0))))
    total = store.sync_notes_count(c.cal.account, c.key) if store is not None else 0
    pager = ctx.pager(size=NOTES_PAGE, total=total)
    notes = store.sync_notes(c.cal.account, c.key, limit=pager.size, offset=pager.offset) if store is not None else []
    rows = tuple(Row((When(n.at), Badge(*NOTE_WORDS.get(n.what, (n.what, ""))),
                      Text(plural(n.changed, "événement", "événements") if n.changed else "—", "muted"),
                      Text(n.detail or "—", "muted")), tone="warn" if n.what == SYNC_FAILED else "") for n in notes)
    return [fields, Table((Column("quand", "fit"), Column("ce qui s'est passé", "fit", role="badge"),
                           Column("événements", "fit"), Column("le détail")), rows, title="Son historique",
                          pager=pager, empty="rien n'a changé depuis qu'il est branché")]


# ── l'onglet « Agendas » de la fiche d'une personne ──


def person_calendars(ports: Mapping[str, Any], frame: Frame, person: str) -> tuple[list[Shown], list[Shown]]:
    """Ses agendas (à elle ; à toi pour une de ses propriétaires), et ceux qu'on lui partage."""
    every = shown_calendars(ports, frame)
    who = YOURS if is_owner(frame, person) else person
    return [c for c in every if c.who == who], [c for c in every if PERSON + person in c.shares]


def _has_agendas(s: AgendaState, person: str, frame: Frame) -> bool:
    """La fiche d'une personne a l'onglet « Agendas » si elle a un compte (son agenda du système), un compte d'agenda
    à elle, ou un agenda qu'on lui partage."""
    p = params_of(frame)
    holder = PERSON + person
    if holder in p.owners.values() or any(holder in shares for shares in p.shares.values()):
        return True
    return any(str(h).startswith(ACCOUNT_PREFIX) for h in (person, *(frame.get(identity_c.HANDLES(person)) or ())))


@AGENDA.inspect("agendas", title="Agendas", subject="person", order=65, shown=_has_agendas,
                description="Ses agendas, ceux qu'on lui partage, et ce qu'elle partage.")
def _person(s: AgendaState, frame: Frame, ctx: InspectContext) -> list[Block]:
    mine, received = person_calendars(ctx.ports, frame, ctx.subject)
    levels = dict(SHARES)

    def row(c: Shown, level: str = "") -> Row:
        said = synced(ctx.ports, frame, c, ctx.when)
        return Row((Text(c.name), Text(KIND_SHORT.get(c.kind, c.kind), "muted"), Badge(said.label, said.tone),
                    Text(levels.get(level, level) if level else whose_words(frame, c.who), "muted")),
                   href=Ref.subject(KIND, c.key, c.name))

    columns = (Column("agenda", role="title"), Column("sorte", "fit"), Column("synchro", "fit", role="badge"),
               Column("à qui", "fit"))
    return [Table(columns, tuple(row(c) for c in mine), title="Ses agendas", empty="aucun"),
            Table(columns, tuple(row(c, c.shares.get(PERSON + ctx.subject, "")) for c in received),
                  title="Ce qu'on lui partage", empty="rien")]


# ── ce qu'un opérateur fait d'un agenda (la fiche, en haut à droite) ──


class NoArgs(BaseModel):
    pass


class PastedArgs(BaseModel):
    text: Annotated[str, Knob(label="L'adresse de la page qui n'a pas pu s'ouvrir", widget="textarea",
                              help="Après le consentement, Google renvoie vers http://127.0.0.1/…?code=… : colle "
                                   "cette adresse (ou son code).")] = Field(default="", max_length=4000)


def _the(frame: Frame, ports: Mapping[str, Any], key: str) -> Shown:
    c = shown_one(ports, frame, key)
    if c is None:
        raise Refused("Cet agenda n'est plus là.")
    return c


def _operator(frame: Frame, ctx: ActionContext) -> None:
    if not operator(frame, ctx.by):
        raise Refused("Seul un opérateur fait cela, depuis la console.")


def _desk(ctx: ActionContext) -> Any:
    desk = ctx.ports.get("agenda_desk")
    if desk is None:
        raise Refused("Les réglages de l'agenda ne sont pas joignables d'ici.")
    return desk


def _provider_kind(s: AgendaState, frame: Frame, key: str, *, ports: Mapping[str, Any]) -> str:
    c = shown_one(ports, frame, key)
    return c.kind if c is not None else ""


def _relit(s: AgendaState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    """« Synchroniser maintenant » : un compte branché, pas décoché."""
    c = shown_one(ports, frame, key)
    return c is not None and not c.system and not c.off


def _to_reconnect(s: AgendaState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    """« Reconnecter » : un compte Google ou Microsoft dont la connexion n'est pas faite (ou ne vaut plus), un compte
    CalDAV ou un abonnement décoché."""
    c = shown_one(ports, frame, key)
    if c is None or c.system:
        return False
    if c.kind in (CALDAV, ICAL):
        return c.off
    signed = signin_of(ports, c.kind, c.cal.account)
    return signed is not None and signed.state != SIGNED_IN


def _google_pending(s: AgendaState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    """« Finir la connexion Google » : une connexion Google commencée, qui attend l'adresse collée."""
    c = shown_one(ports, frame, key)
    signed = signin_of(ports, GOOGLE, c.cal.account) if c is not None and c.kind == GOOGLE else None
    return signed is not None and signed.state == SIGNIN_PENDING


@AGENDA.action("relire", title="Synchroniser maintenant", args=NoArgs, emits=[SYNC_ASKED], subject=KIND, order=10,
               description="Son compte se relit sans attendre sa cadence, même si elle dort.",
               available=lambda s, frame, key, ports: _relit(s, frame, key, ports))
def _reread(s: AgendaState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    _operator(frame, ctx)
    c = _the(frame, ctx.ports, ctx.subject)
    if c.system:
        return Done(message="L'agenda du système est toujours à jour.", tone="info")
    if c.off:
        raise Refused("Ce compte est décoché : il ne se synchronise plus.")
    return Done(drafts=(SYNC_ASKED.draft(account=c.cal.account, by=ctx.by),),
                message="Synchronisation demandée : l'agenda se relit dans quelques secondes.")


def _own(frame: Frame, ctx: ActionContext, c: Shown) -> None:
    """Se reconnecter demande le compte Google ou Microsoft de son propriétaire : seulement pour les tiens."""
    if account_level(params_of(frame), frame, person_of(frame, ctx.by), c.cal.account) != OWNED:
        raise Refused(f"Seul son propriétaire se reconnecte, dans son espace (Paramètres › Agendas) : "
                      f"ce compte est à {whose_words(frame, c.who)}.")


@AGENDA.action("reconnecter", title="Reconnecter", args=NoArgs, emits=[SYNC_ASKED], subject=KIND, order=20,
               description="Refaire la connexion de son compte — seulement pour un compte à toi : la connexion demande "
                           "ton compte Google ou Microsoft. Un compte CalDAV ou un abonnement décoché se recoche.",
               available=lambda s, frame, key, ports: _to_reconnect(s, frame, key, ports))
async def _reconnect(s: AgendaState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    _operator(frame, ctx)
    c = _the(frame, ctx.ports, ctx.subject)
    _own(frame, ctx, c)
    account = c.cal.account
    if c.kind in (CALDAV, ICAL):
        if not c.off:
            return Done(message="Ce compte n'a pas de connexion à refaire : « Synchroniser maintenant » le relit.",
                        tone="info")
        await _desk(ctx).enable(account, True)
        return Done(drafts=(SYNC_ASKED.draft(account=account, by=ctx.by),),
                    message="Recoché : il se synchronise de nouveau.")
    providers = ctx.ports.get("agenda_providers")
    signin = getattr(providers.of(c.kind), "signin", None) if providers is not None else None
    conn = providers.connection(account) if providers is not None else None
    if signin is None or conn is None:
        raise Refused("La connexion de ce compte ne se fait pas d'ici.")
    try:
        if c.kind == GOOGLE:
            got = signin.start(account, who=ctx.by, hint=conn.address)
            return Done(message="Ouvre l'adresse de Google ci-dessous, consens, puis colle l'adresse de la page qui n'a "
                                "pas pu s'ouvrir dans « Finir la connexion Google ».", tone="info",
                        show=(Fields((("chez Google", Ref.url(got.url, "Se connecter à Google")),),
                                     title="La connexion Google"),))
        got = await signin.start(account, conn)
    except (AgendaError, OSError, RuntimeError, ValueError) as exc:
        raise Refused(f"La connexion n'a pas pu commencer : {exc}"[:300]) from None
    return Done(message=f"Entre le code {got.code} chez Microsoft, avec ce compte : la synchro reprend dès que c'est "
                        "fait.", tone="info",
                show=(Fields((("le code", got.code), ("chez Microsoft", Ref.url(got.url, got.url))),
                             title="La connexion Microsoft"),))


@AGENDA.action("finir_google", title="Finir la connexion Google", args=PastedArgs, emits=[SYNC_ASKED], subject=KIND,
               order=21, description="Après le consentement : l'adresse de la page qui n'a pas pu s'ouvrir.",
               available=lambda s, frame, key, ports: _google_pending(s, frame, key, ports))
async def _finish_google(s: AgendaState, frame: Frame, args: PastedArgs, ctx: ActionContext) -> Done:
    _operator(frame, ctx)
    c = _the(frame, ctx.ports, ctx.subject)
    _own(frame, ctx, c)
    providers = ctx.ports.get("agenda_providers")
    signin = getattr(providers.of(GOOGLE), "signin", None) if providers is not None else None
    if signin is None or not args.text.strip():
        raise Refused("Colle l'adresse de la page qui n'a pas pu s'ouvrir.", {"text": "valeur requise"})
    try:
        await signin.finish(args.text.strip(), key=c.cal.account, who=ctx.by)
    except AgendaError as exc:
        raise Refused(str(exc)[:300], {"text": str(exc)[:200]}) from None
    return Done(drafts=(SYNC_ASKED.draft(account=c.cal.account, by=ctx.by),),
                message="Connecté à Google : l'agenda se synchronise.")


@AGENDA.action("deconnecter", title="Déconnecter le compte", args=NoArgs, emits=[], subject=KIND, order=30,
               danger=True, confirm="Déconnecter ce compte ? Il ne se synchronise plus ; ses événements restent ici, "
                                    "figés. Seul son propriétaire peut le reconnecter.",
               description="Google ou Microsoft : sa connexion est retirée (chez Google aussi) et oubliée, le compte "
                           "reste, à reconnecter. CalDAV ou un abonnement : il est décoché. Rien n'est effacé chez son "
                           "fournisseur.",
               available=lambda s, frame, key, ports: _provider_kind(s, frame, key, ports=ports) not in ("", SYSTEM))
async def _disconnect(s: AgendaState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    _operator(frame, ctx)
    c = _the(frame, ctx.ports, ctx.subject)
    desk = _desk(ctx)
    try:
        if c.kind in (GOOGLE, MICROSOFT):
            await desk.disconnect(c.cal.account)
            return Done(message="Déconnecté : sa connexion est oubliée ; ses événements restent, figés.")
        changed = await desk.enable(c.cal.account, False)
    except ValueError as exc:
        raise Refused(str(exc)[:300]) from None
    return Done(message="Décoché : il ne se synchronise plus ; ses événements restent, figés." if changed else
                "Ce compte était déjà décoché.", tone="ok" if changed else "info")


@AGENDA.action("retirer", title="Supprimer de Mika", args=NoArgs, emits=[SYNC_ASKED], subject=KIND, order=40,
               danger=True, confirm="Retirer cet agenda de ce serveur ? Sa copie part d'ici ; rien n'est effacé chez son "
                                    "fournisseur. Son propriétaire peut le suivre de nouveau dans son espace.",
               description="Il n'est plus suivi : sa copie part d'ici, et elle ne s'en sert plus. Rien n'est effacé "
                           "chez son fournisseur.",
               available=lambda s, frame, key, ports: _provider_kind(s, frame, key, ports=ports) not in ("", SYSTEM))
async def _drop(s: AgendaState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    _operator(frame, ctx)
    c = _the(frame, ctx.ports, ctx.subject)
    if c.system:
        raise Refused("L'agenda du système d'une personne ne se retire pas : ses événements ne sont qu'ici.")
    try:
        await _desk(ctx).follow(c.key, False)
    except ValueError as exc:
        raise Refused(str(exc)[:300]) from None
    store = ctx.ports.get("agenda")
    if store is not None:
        store.clear_calendar(c.key)
    return Done(drafts=(SYNC_ASKED.draft(account=c.cal.account, by=ctx.by),),
                message=f"« {c.name} » n'est plus suivi : sa copie est partie d'ici.",
                go=view_link("tous", "Tous les agendas"))


def planned_reminder(frame: Frame, delay: str, o: Occurrence) -> int | None:
    """Quand elle rappellera cette occurrence à ce délai (``None`` : jamais)."""
    tz = frame.env.tz_of(frame.root)
    p = params_of(frame)
    if delay in ("", "non"):
        return None
    if delay == "veille":
        first = local(o.span.start, tz).date() if not o.span.all_day else date.fromisoformat(o.span.first_day)
        return instant(datetime.combine(first - timedelta(days=1), time(p.eve_hour), tzinfo=tz))
    if o.span.all_day or not delay.isdigit():
        return None
    return o.span.start - int(delay) * MINUTE


__all__ = ["Account", "BUSY", "FROM", "HER", "HIDDEN", "KIND", "KIND_SHORT", "LIST", "MONTH", "NOTE_WORDS", "OPEN",
           "OP_WORDS", "PAST", "PERIOD", "REMINDED_WORDS", "REMINDER_WORDS", "SECTION", "SYNC_MODE", "UPCOMING",
           "VIEW", "VIEWS", "WEEK", "WHOSE", "WRITE_STATUS", "YOURS", "DROPPED_WHY", "Shown", "Synced",
           "account_label", "accounts_badge", "bounds", "chosen", "count_events", "is_owner", "name_of", "occurrences_of", "people_nav",
           "period_of", "person_calendars", "planned_reminder", "private_for_console", "rule_words", "sees_private",
           "shown_accounts", "shown_calendars", "shown_one", "signin_of", "synced", "title_of", "view_link", "waiting_count",
           "week_of", "who_of", "whose_words", "writes_of"]
