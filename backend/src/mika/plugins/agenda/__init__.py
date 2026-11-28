"""Le plugin ``agenda`` (ADR 0309) : les agendas de chacun — celui du système, et ceux qu'on branche (Google Agenda,
Outlook.com / Microsoft 365, CalDAV, un abonnement iCal), chacun à quelqu'un, partagés agenda par agenda.

- **Le monde, pas sa vie** : les événements vivent dans leur base (le port ``agenda``, ``ports/agenda.py``), hors du
  journal ; ceux du système y font foi, ceux d'un fournisseur en sont la copie, que ``agenda.sync`` tient à jour
  (``sync``). Les fournisseurs, par sorte, et les comptes des réglages sont le port ``agenda_providers``.
- **Ses paramètres** reçoivent des réglages (``adapters/agenda/config.py::AgendaConfig.params``), journalisés comme
  ceux des boîtes : à qui est chaque compte branché (``owners`` ; celui du système d'une personne est à elle,
  ``ports.agenda.owner_of``), sa sorte, ceux qui sont décochés, et par agenda ses partages (``shares``), s'il est
  masqué (``hidden`` : masqué, Mika ne s'en sert plus) et le rappel choisi (``reminders``) ; plus ce que la console
  règle : le rappel par défaut de chaque sorte, la cadence de synchronisation par sorte, la fenêtre (90 jours
  derrière, un an devant), le recul après une panne.
- **Ce qu'elle en fait** (lot 3a) : le tableau de droits de chaque agenda (``rights``, ADR 0309) ; ses outils, la
  famille ``agenda`` (``tools`` : lire une période, trouver un créneau, ajouter, modifier, supprimer, répondre à une
  invitation), offerts à qui a un agenda ou en reçoit un partage ; écrire est une capacité (``agenda.write``), après le
  commit, seule ou sur un accord ; ce qu'elle y a proposé et ce que c'est devenu (``AgendaState.writes``,
  ``agenda.written``) ; elle sait la journée de la personne en face (``prompt``).
- **Ce qu'elle fait d'elle-même** (lot 3b) : le processus ``agenda.watch`` (``watch``) regarde la base — un rendez-vous
  dont le rappel est dû (``reminder`` : le choix de l'agenda, ou celui de l'événement) devient ``agenda.reminder_due``,
  qu'une initiative due dit (``remind``) ; une invitation qui attend sa réponse devient ``agenda.invitation_noticed``,
  qu'une tâche prépare (``tasks``) ; ce qui n'a plus lieu d'être tombe (``reminder_dropped``,
  ``invitation_settled``), et une proposition qui attend un accord tombe quand le rendez-vous commence, ou quand la
  personne a répondu autrement. Ce qui a été dit, préparé, ou est tombé, est dans sa tranche (``reminders``,
  ``invitations``) : la console le montrera.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import agency as agency_c
from mika.contracts import agenda as agenda_c
from mika.contracts import runtime as rt
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Payload
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.agenda import (
    CALDAV,
    GOOGLE,
    ICAL,
    MICROSOFT,
    REMINDERS,
    Reminder,
    default_reminder,
    owner_of,
    split_calendar_key,
)
from mika.vocab.access import PERSON, Share
from mika.vocab.episodes import Kind, gave_way, task_of
from mika.vocab.phrasebook import phrase

OWNER = agenda_c.OWNER
#: sa famille d'outils (ADR 0309)
BUNDLE = agenda_c.BUNDLE
#: écrire dans un agenda : ajouter, modifier, supprimer un événement, répondre à une invitation — une capacité
CAPABILITY = f"{OWNER}.write"
#: ce qu'elle y écrit
CREATE, EDIT, DELETE, RESPOND = "ajouter", "modifier", "supprimer", "repondre"
OPS = (CREATE, EDIT, DELETE, RESPOND)
#: où en est ce qu'elle a proposé : attend un accord, accepté (parti), refusé, fait, raté
WAITING, APPROVED, REFUSED, DONE, FAILED = "attend", "accepte", "refuse", "fait", "rate"
FINAL = frozenset({REFUSED, DONE, FAILED})
#: ce qu'elle garde de ses écritures (les plus anciennes s'effacent)
WRITES_KEPT = 100
#: la provenance d'une écriture qu'elle a dite (``agenda:<proposition>``) : son énoncé l'emporte, elle ne la redit pas
PROVENANCE = "agenda:"
#: qui signe le refus d'une proposition qui n'a plus lieu d'être : la personne a répondu elle-même (ailleurs : dans
#: l'écran, chez le fournisseur), ou le rendez-vous a commencé, est passé, a été annulé ou supprimé (le délai)
ELSEWHERE, EXPIRED = "ailleurs", rt.EXPIRER
#: ce qu'on garde des rappels et des invitations (les plus anciens s'effacent)
REMINDERS_KEPT, INVITATIONS_KEPT = 200, 100
#: pourquoi un rappel tombe : le rendez-vous a bougé, été supprimé, annulé ou refusé ; son agenda ne le demande plus
#: (ou ne lui est plus ouvert)
MOVED, GONE, OFF = "deplace", "parti", "coupe"
#: pourquoi une invitation est réglée : la personne a répondu, elle n'est plus là, elle a commencé
ANSWERED, LEFT, BEGUN = "repondue", "partie", "commencee"


class AgendaParams(BaseModel):
    """Ses comptes et ses agendas tels que les réglages les disent ; leurs rappels par défaut ; leur synchronisation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owners: Annotated[dict[str, str], Knob(
        label="À qui sont ses comptes d'agenda", group="Comptes", readonly=True,
        help="Réglé avec chaque compte : il sert à son propriétaire — une personne (« personne:<clé> ») ; absent, à "
             "toi. Le compte du système d'une personne est à elle.")] = Field(default_factory=dict)
    kinds: Annotated[dict[str, str], Knob(
        label="La sorte de chaque compte", group="Comptes", readonly=True,
        help="Google, Microsoft, CalDAV ou un abonnement iCal : elle dit sa cadence et son rappel par défaut.")] = \
        Field(default_factory=dict)
    accounts_off: Annotated[tuple[str, ...], Knob(
        label="Comptes décochés", group="Comptes", readonly=True,
        help="Ils ne se synchronisent plus et elle ne s'en sert plus ; ce qui est gardé reste.")] = ()
    shares: Annotated[dict[str, dict[str, Share]], Knob(
        label="Avec qui ses agendas sont partagés", group="Agendas", readonly=True,
        help="Réglé par le propriétaire d'un agenda : par agenda, chaque personne (« personne:<clé> ») et ce qu'elle en "
             "a — lire, lire et préparer, s'en servir.")] = Field(default_factory=dict)
    hidden: Annotated[tuple[str, ...], Knob(
        label="Agendas masqués", group="Agendas", readonly=True,
        help="Masqué par son propriétaire : il ne s'affiche plus, et elle ne s'en sert plus.")] = ()
    reminders: Annotated[dict[str, Reminder], Knob(
        label="Le rappel choisi de chaque agenda", group="Agendas", readonly=True,
        help="« Elle te le rappelle », choisi par agenda ; absent, le rappel par défaut de sa sorte (ci-dessous).")] = \
        Field(default_factory=dict)
    system_reminder: Annotated[Reminder, Knob(
        label="Un agenda du système : elle te le rappelle", group="Rappels", choices=REMINDERS,
        help="Son rappel d'un agenda de ce serveur dont la personne n'a pas choisi le sien.")] = "30"
    provider_reminder: Annotated[Reminder, Knob(
        label="Un agenda branché : elle te le rappelle", group="Rappels", choices=REMINDERS,
        help="Son rappel d'un agenda Google, Outlook ou CalDAV dont la personne n'a pas choisi le sien : coupé, "
             "le fournisseur a les siens. Un abonnement iCal n'en a pas.")] = "non"
    google_every_us: Annotated[int, Knob(
        label="Relire Google toutes les", group="Synchronisation", lo=MINUTE, hi=DAY,
        help="Un compte Google se relit à ce rythme (par delta : seulement ce qui a changé).")] = 5 * MINUTE
    microsoft_every_us: Annotated[int, Knob(
        label="Relire Microsoft toutes les", group="Synchronisation", lo=MINUTE, hi=DAY,
        help="Un compte Outlook.com / Microsoft 365 se relit à ce rythme (par delta).")] = 5 * MINUTE
    caldav_every_us: Annotated[int, Knob(
        label="Relire un serveur CalDAV toutes les", group="Synchronisation", lo=MINUTE, hi=DAY,
        help="Un compte CalDAV se relit à ce rythme (par delta quand le serveur le sait).")] = 10 * MINUTE
    ical_every_us: Annotated[int, Knob(
        label="Relire un abonnement toutes les", group="Synchronisation", lo=10 * MINUTE, hi=7 * DAY,
        help="Une adresse .ics se relit en entier à ce rythme.")] = HOUR
    past_us: Annotated[int, Knob(
        label="Garder les jours passés", group="Synchronisation", lo=7 * DAY, hi=730 * DAY,
        help="La copie d'un agenda branché garde ce qui a eu lieu dans cette période ; plus ancien, il part (on le "
             "redemande au fournisseur).")] = 90 * DAY
    ahead_us: Annotated[int, Knob(
        label="Garder les jours à venir", group="Synchronisation", lo=30 * DAY, hi=3 * 365 * DAY,
        help="La copie d'un agenda branché tient ce qui vient dans cette période ; au-delà, on le demande au "
             "fournisseur.")] = 365 * DAY
    retry_us: Annotated[int, Knob(
        label="Après une panne, réessayer dans", group="Synchronisation", lo=10 * US, hi=HOUR,
        help="Une synchronisation manquée se réessaie après ce délai, doublé à chaque échec de suite.")] = MINUTE
    retry_max_us: Annotated[int, Knob(
        label="Au plus tard, réessayer dans", group="Synchronisation", lo=MINUTE, hi=DAY,
        help="Le délai entre deux essais d'un compte en panne ne dépasse jamais celui-ci.")] = 6 * HOUR
    per_run: Annotated[int, Knob(
        label="Comptes par passage", group="Synchronisation", lo=1, hi=50,
        help="Au plus autant de comptes se synchronisent à chaque passage ; les autres, au suivant.")] = 5
    history_us: Annotated[int, Knob(
        label="Garder l'historique de la synchro", group="Synchronisation", lo=DAY, hi=365 * DAY,
        help="Ce que dit l'onglet Synchronisation de la fiche d'un agenda (la console) : les relectures qui ont changé "
             "quelque chose, les écritures, les pannes et leur reprise ; plus ancien, il part.")] = 30 * DAY
    eve_hour: Annotated[int, Knob(
        label="« La veille au soir », à", group="Rappels", lo=16, hi=23,
        help="L'heure, la veille d'un rendez-vous, à laquelle elle le rappelle quand son agenda dit « la veille au "
             "soir ».")] = 20
    remind_evidence: Annotated[float, Knob(
        label="Envie de rappeler un rendez-vous", group="Rappels", lo=9.0, hi=14.5,
        help="La preuve d'un rappel dû devant l'arbitre : au-dessus du seuil d'une initiative (il part vite), sous la "
             "barre qui la tire du sommeil (endormie, il attend).")] = 12.0
    remind_attempts: Annotated[int, Knob(
        label="Essais d'un rappel", group="Rappels", lo=1, hi=5,
        help="Un rappel qui n'a pas pu se dire (un silence, une panne) se retente au plus autant de fois, et jamais "
             "après le début du rendez-vous.")] = 2
    prepare_evidence: Annotated[float, Knob(
        label="Envie de préparer une réponse d'invitation", group="Invitations", lo=8.0, hi=14.0,
        help="La preuve d'une tâche qui prépare la réponse à une invitation, devant l'arbitre.")] = 11.0
    prepare_per_day: Annotated[int, Knob(
        label="Réponses d'invitation préparées par jour", group="Invitations", lo=0, hi=50,
        help="Au plus autant de tâches par vingt-quatre heures ; 0 : elle n'en prépare plus.")] = 10
    prepare_attempts: Annotated[int, Knob(
        label="Essais d'une réponse d'invitation", group="Invitations", lo=1, hi=5,
        help="Une tâche qui n'a rien proposé se retente au plus autant de fois.")] = 2
    card_within_us: Annotated[int, Knob(
        label="Une carte d'accord du chat vaut", group="Accords", lo=10 * MINUTE, hi=7 * DAY,
        help="La carte de son chat ne vaut que ce temps (jamais au-delà du début du rendez-vous) ; la proposition, "
             "elle, attend dans l'Agenda jusqu'à la décision ou au début du rendez-vous, où elle tombe.")] = 2 * HOUR


@dataclass(frozen=True, slots=True)
class Written:
    """Ce qu'elle a proposé d'écrire dans un agenda (``agenda.write``) et ce que c'est devenu : pour qui (l'adresse de
    la personne en face, à qui le dire), qui en décide (une adresse : une carte dans son chat ; vide : sans accord, ou
    la console), le résumé (un contenu), où il en est ; fait ou raté, l'événement touché et ses mots d'un échec (un
    contenu) ; ``told`` : elle l'a dit."""

    proposal: int
    op: str
    calendar: str
    target: str
    decider: str
    at: int
    summary_ref: str
    status: str = WAITING
    approval: bool = True
    by: str = ""
    uid: str = ""
    occurrence: str = ""
    done_at: int = 0
    why_ref: str = ""
    told: bool = False
    #: la ligne visée (une exception d'une série : la clé de son occurrence) ; le début du rendez-vous, quand elle l'a
    #: proposé (passé, ce qui attend tombe) ; l'invitation dont une tâche a préparé la réponse (sa clé)
    original: str = ""
    starts: int = 0
    invitation: str = ""
    #: la personne l'a ajouté elle-même avec ses changements (« Modifier », depuis son Agenda) : fait, mais pas tel
    #: qu'elle l'avait proposé
    edited: bool = False


@dataclass(frozen=True, slots=True)
class Reminded:
    """Un rappel d'un rendez-vous (``agenda.reminder_due``) : qui prévenir (sa clé de personne), l'occurrence (son
    agenda, la ligne de son événement dans la base, sa clé dans une série, quand elle a lieu), le délai qui l'a fait
    (``ports.agenda.REMINDERS``) et quand il est dû ; où il en est (``agenda.DUE``, ``TOLD``, ``DROPPED`` et pourquoi),
    combien de fois elle a essayé, et, dit, quand et à quelle adresse. Ni titre ni lieu : ils sont dans la base."""

    key: str
    person: str
    calendar: str
    event: int
    occurrence: str
    start: int
    end: int
    all_day: bool
    delay: str
    due_at: int
    status: str = agenda_c.DUE
    attempts: int = 0
    told_at: int = 0
    told_to: str = ""
    why: str = ""
    #: l'épisode qui essaie de le dire (sa corrélation) : s'il n'a pas eu lieu (devancé, préempté), ce n'était pas un
    #: essai
    trying: str = ""


@dataclass(frozen=True, slots=True)
class Invited:
    """Une invitation qui attend sa réponse (``agenda.invitation_noticed``) : son agenda, sa ligne dans la base et ce
    qui la désigne chez tous (UID, l'occurrence d'une exception), à qui est l'agenda, sa prochaine occurrence ; où elle
    en est (``agenda.PENDING``, ``SETTLED`` et pourquoi), les essais de sa tâche, et la réponse que la tâche a proposée
    (``proposal``)."""

    key: str
    calendar: str
    event: int
    uid: str
    original: str
    holder: str
    start: int
    at: int
    status: str = agenda_c.PENDING
    why: str = ""
    attempts: int = 0
    proposal: int = 0


@dataclass(frozen=True, slots=True)
class AgendaState:
    """Son monde est dans sa base ; le journal garde ce qu'elle y a proposé d'écrire et ce que c'est devenu
    (``writes``, par proposition) : « ajouté par Mika », « proposé », « refusé », « raté »."""

    writes: FrozenDict[int, Written] = field(default_factory=FrozenDict)
    #: ses rappels, par clé d'occurrence (lot 3b)
    reminders: FrozenDict[str, Reminded] = field(default_factory=FrozenDict)
    #: les invitations qu'une tâche prépare, par clé (lot 3b)
    invitations: FrozenDict[str, Invited] = field(default_factory=FrozenDict)
    #: « Synchroniser maintenant » (lot 4), par compte (vide : tous) : quand on l'a demandé
    sync_asked: FrozenDict[str, int] = field(default_factory=FrozenDict)


class ReminderDue(Payload):
    """Le rappel d'une occurrence est dû : son agenda le demande à ce délai, et il n'a pas encore commencé. ``key`` :
    l'occurrence telle qu'elle est (son agenda, son événement, sa clé, son début — déplacée, une autre) ; ``person`` :
    la personne à prévenir ; ``about`` : elle (l'oubli l'atteint)."""

    key: str
    person: str
    calendar: str
    event: int
    occurrence: str = ""
    start: int
    end: int
    all_day: bool = False
    delay: str
    about: tuple[str, ...] = ()


class ReminderDropped(Payload):
    """Un rappel dû qui n'a plus lieu d'être, et pourquoi (``MOVED``, ``GONE``, ``OFF``)."""

    key: str
    why: str


class InvitationNoticed(Payload):
    """Une invitation attend sa réponse, dans un agenda où elle peut la préparer au travail : son agenda, sa ligne,
    son UID et son occurrence (une exception), à qui est l'agenda (``holder``), sa prochaine occurrence."""

    key: str
    calendar: str
    event: int
    uid: str
    original: str = ""
    holder: str = ""
    start: int
    about: tuple[str, ...] = ()


class InvitationSettled(Payload):
    """Une invitation n'attend plus : répondue (par la personne, ou par ce qu'elle avait préparé), partie, ou
    commencée (``ANSWERED``, ``LEFT``, ``BEGUN``)."""

    key: str
    why: str


class AgendaWritten(Payload):
    """Ce qu'elle avait proposé d'écrire dans un agenda est fait, ou a raté (après ``effect.executed``) : quoi, où, l'
    événement touché (son UID, l'occurrence), ce qu'elle a fait en mots (``summary``) et, raté, pourquoi (``why``, les
    mots du fournisseur) — des contenus, la personne en face pour sujet."""

    proposal: int
    ok: bool
    op: str
    calendar: str
    summary: Content
    uid: str = ""
    occurrence: str = ""
    why: Content | None = None
    about: tuple[str, ...] = ()
    #: la personne l'a ajouté elle-même, avec ses changements (lot 4 : « Modifier » une proposition)
    edited: bool = False


class SyncAsked(Payload):
    """« Synchroniser maintenant » (lot 4) : ce compte (vide : tous ceux qu'on relit), sans attendre sa cadence ; ``by``
    : qui l'a demandé (son adresse)."""

    account: str = ""
    by: str = ""


def params(p: AgendaParams | None) -> AgendaParams:
    return p if p is not None else AgendaParams()


def params_of(frame: Frame) -> AgendaParams:
    return params(frame.env.params_of(OWNER, frame.root))


def cadence(p: AgendaParams, kind: str) -> int:
    """Le rythme de synchronisation d'un compte de cette sorte (le système ne se synchronise pas : 0)."""
    return {GOOGLE: p.google_every_us, MICROSOFT: p.microsoft_every_us, CALDAV: p.caldav_every_us,
            ICAL: p.ical_every_us}.get(kind, 0)


def owner(p: AgendaParams, account: str) -> str:
    """À qui est ce compte (``vocab/ownership.py`` : vide, à toi ; ``personne:<clé>``)."""
    return owner_of(account, p.owners)


def hers(p: AgendaParams, calendar: str) -> bool:
    """Mika peut-elle s'en servir ? Ni masqué, ni sous un compte décoché."""
    account, _local = split_calendar_key(calendar)
    return calendar not in p.hidden and account not in p.accounts_off


def reminder(p: AgendaParams, calendar: str, kind: str) -> str:
    """« Mika te le rappelle » pour cet agenda : son choix, sinon le défaut de sa sorte."""
    return p.reminders.get(calendar) or default_reminder(kind, system=p.system_reminder,
                                                         provider=p.provider_reminder)


#: v2 : ses écritures (``writes``, lot 3a) ; v3 : ses rappels et ses invitations (lot 3b) ; v4 : « Synchroniser
#: maintenant » et une proposition ajoutée avec les changements de la personne (lot 4) — la tranche se reconstruit
#: depuis la genèse
AGENDA = Faculty(OWNER, state=AgendaState, init=lambda p: AgendaState(), params=AgendaParams, state_version=4)
AGENDA.bundle(BUNDLE, phrase("agenda.bundle"))
WRITTEN = AGENDA.event("written", AgendaWritten, content=("summary", "why"), subjects=("about",))
REMINDER_DUE = AGENDA.event("reminder_due", ReminderDue, subjects=("about",))
REMINDER_DROPPED = AGENDA.event("reminder_dropped", ReminderDropped)
INVITATION_NOTICED = AGENDA.event("invitation_noticed", InvitationNoticed, subjects=("about",))
INVITATION_SETTLED = AGENDA.event("invitation_settled", InvitationSettled)
SYNC_ASKED = AGENDA.event("sync_asked", SyncAsked)


# ── ce qu'elle y a proposé d'écrire, et ce que c'est devenu ──


def _kept(writes: FrozenDict[int, Written]) -> FrozenDict[int, Written]:
    while len(writes) > WRITES_KEPT:
        writes = writes.delete(min(writes))
    return writes


@AGENDA.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    d = e.data
    if d.capability != CAPABILITY:
        return s
    args = rt.proposal_args(d.args_json)
    invitation = str(args.get("invitation") or "")
    w = Written(proposal=e.seq, op=str(args.get("op") or ""), calendar=str(args.get("calendar") or ""),
                target=str(args.get("target") or ""), decider=str(args.get(rt.DECIDER) or ""), at=e.at,
                summary_ref=d.summary.ref or "", status=WAITING if d.approval else APPROVED, approval=d.approval,
                uid=str(args.get("uid") or ""), occurrence=str(args.get("occurrence") or ""),
                original=str(args.get("original") or ""), starts=rt.arg_int(args, "starts"), invitation=invitation)
    s = replace(s, writes=_kept(s.writes.set(e.seq, w)))
    inv = s.invitations.get(invitation) if invitation else None
    if inv is not None and not inv.proposal:  # la réponse que sa tâche a préparée : une invitation, une tâche
        s = replace(s, invitations=s.invitations.set(invitation, replace(inv, proposal=e.seq)))
    return s


@AGENDA.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    d = e.data
    w = s.writes.get(d.proposal)
    if w is None or w.status in FINAL:  # ajoutée par la personne avec ses changements, puis retirée : c'est fait
        return s
    return replace(s, writes=s.writes.set(d.proposal, replace(
        w, status=APPROVED if d.approved else REFUSED, by=d.by, done_at=0 if d.approved else e.at)))


@AGENDA.reducer(rt.EFFECT_EXECUTED)
def _executed(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    d = e.data
    w = s.writes.get(d.proposal)
    if w is None or d.ok or w.status in FINAL:
        return s  # fait : ``agenda.written`` suit, avec l'événement touché
    return replace(s, writes=s.writes.set(d.proposal, replace(w, status=FAILED, done_at=e.at)))


@AGENDA.reducer(WRITTEN)
def _written(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    d = e.data
    w = s.writes.get(d.proposal)
    if w is None:
        return s
    return replace(s, writes=s.writes.set(d.proposal, replace(
        w, status=DONE if d.ok else FAILED, done_at=e.at, uid=d.uid or w.uid, occurrence=d.occurrence or w.occurrence,
        why_ref=(d.why.ref or "") if d.why is not None else "", edited=d.edited)))


@AGENDA.reducer(SYNC_ASKED)
def _sync_asked(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    return replace(s, sync_asked=s.sync_asked.set(e.data.account, e.at))


@AGENDA.reducer(rt.UTTERANCE)
def _uttered(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    """Ce que son prompt ou un outil lui montrait d'une écriture (``agenda:<proposition>``) quand elle a parlé : c'est
    dit. Un rappel que son prompt lui montrait (``agenda:rappel:<clé>``), aussi : il est dit, ici, à cette heure."""
    d = e.data
    if not d.visible:
        return s
    writes, reminders = s.writes, s.reminders
    for p in d.provenance:
        key = agenda_c.reminder_of(p)
        r = reminders.get(key) if key else None
        if r is not None and r.status == agenda_c.DUE:
            reminders = reminders.set(key, replace(r, status=agenda_c.TOLD, told_at=e.at, told_to=d.target or ""))
            continue
        if not p.startswith(PROVENANCE) or not p[len(PROVENANCE):].isdigit():
            continue
        w = writes.get(int(p[len(PROVENANCE):]))
        if w is not None and w.status in FINAL and not w.told:
            writes = writes.set(w.proposal, replace(w, told=True))
    if writes is s.writes and reminders is s.reminders:
        return s
    return replace(s, writes=writes, reminders=reminders)


# ── ses rappels, et les invitations qu'elle prépare (lot 3b) ──


def _pruned(items: FrozenDict[Any, Any], kept: int, order: Any) -> FrozenDict[Any, Any]:
    while len(items) > kept:
        items = items.delete(min(items, key=lambda k: order(items[k])))
    return items


@AGENDA.reducer(REMINDER_DUE)
def _due(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    d = e.data
    if d.key in s.reminders:
        return s
    r = Reminded(key=d.key, person=d.person, calendar=d.calendar, event=d.event, occurrence=d.occurrence,
                 start=d.start, end=d.end, all_day=d.all_day, delay=d.delay, due_at=e.at)
    return replace(s, reminders=_pruned(s.reminders.set(d.key, r), REMINDERS_KEPT, lambda r: (r.start, r.key)))


@AGENDA.reducer(REMINDER_DROPPED)
def _dropped(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    r = s.reminders.get(e.data.key)
    if r is None or r.status != agenda_c.DUE:
        return s
    return replace(s, reminders=s.reminders.set(r.key, replace(r, status=agenda_c.DROPPED, why=e.data.why)))


@AGENDA.reducer(INVITATION_NOTICED)
def _noticed(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    d = e.data
    if d.key in s.invitations:
        return s
    inv = Invited(key=d.key, calendar=d.calendar, event=d.event, uid=d.uid, original=d.original, holder=d.holder,
                  start=d.start, at=e.at)
    return replace(s, invitations=_pruned(s.invitations.set(d.key, inv), INVITATIONS_KEPT, lambda i: (i.at, i.key)))


@AGENDA.reducer(INVITATION_SETTLED)
def _settled(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    inv = s.invitations.get(e.data.key)
    if inv is None or inv.status != agenda_c.PENDING:
        return s
    return replace(s, invitations=s.invitations.set(inv.key, replace(inv, status=agenda_c.SETTLED, why=e.data.why)))


@AGENDA.reducer(rt.EPISODE_STARTED)
def _tried(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    """Un essai de plus : l'initiative qui dit un rappel (son sujet), la tâche qui prépare une invitation (sa cible)."""
    d = e.data
    key = agenda_c.reminder_of(d.subject)
    r = s.reminders.get(key) if key else None
    if r is not None:
        return replace(s, reminders=s.reminders.set(key, replace(r, attempts=r.attempts + 1, trying=e.correlation)))
    found = task_of(d.target) if d.kind == Kind.TASK else None
    inv = s.invitations.get(found[1]) if found is not None and found[0] == OWNER else None
    if inv is not None:
        return replace(s, invitations=s.invitations.set(inv.key, replace(inv, attempts=inv.attempts + 1)))
    return s


@AGENDA.reducer(rt.EPISODE_ENDED)
def _untried(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    """Ce qui n'a pas eu lieu n'est pas un essai : une initiative devancée, préemptée, interrompue (``agency.UNTRIED``)
    ; une tâche qui a cédé la place à ce qu'on attendait (``gave_way``)."""
    d = e.data
    r = next((r for r in s.reminders.values() if r.trying and r.trying == e.correlation), None)
    if r is not None:
        undo = d.outcome in agency_c.UNTRIED and r.attempts > 0
        return replace(s, reminders=s.reminders.set(r.key, replace(
            r, trying="", attempts=r.attempts - 1 if undo else r.attempts)))
    found = task_of(d.target) if d.kind == Kind.TASK else None
    inv = s.invitations.get(found[1]) if found is not None and found[0] == OWNER else None
    if inv is not None and gave_way(d.outcome, d.guard) and inv.attempts > 0:
        return replace(s, invitations=s.invitations.set(inv.key, replace(inv, attempts=inv.attempts - 1)))
    return s


@AGENDA.reducer(SUBJECT_FORGOTTEN)
def _forgotten(s: AgendaState, e: Any, cx: Any) -> AgendaState:
    """Oublier une personne efface ce qu'elle lui avait proposé (leurs contenus, déjà, par leurs sujets), ses rappels
    et les invitations de ses agendas."""
    who = e.data.subject
    writes = s.writes.without(lambda n: s.writes[n].target == who or s.writes[n].decider == who)
    reminders = s.reminders.without(lambda k: s.reminders[k].person == who)
    invitations = s.invitations.without(lambda k: s.invitations[k].holder == PERSON + who)
    if writes is s.writes and reminders is s.reminders and invitations is s.invitations:
        return s
    return replace(s, writes=writes, reminders=reminders, invitations=invitations)


from mika.plugins.agenda import actions as actions  # noqa: E402 — s'enregistrent sur AGENDA
from mika.plugins.agenda import inspect as inspect  # noqa: E402
from mika.plugins.agenda import prompt as prompt  # noqa: E402
from mika.plugins.agenda import remind as remind  # noqa: E402 — s'enregistre sur AGENDA
from mika.plugins.agenda import rights as rights  # noqa: E402
from mika.plugins.agenda import sync as sync  # noqa: E402 — s'enregistre sur AGENDA
from mika.plugins.agenda import tasks as tasks  # noqa: E402 — s'enregistre sur AGENDA
from mika.plugins.agenda import tools as tools  # noqa: E402 — s'enregistrent sur AGENDA
from mika.plugins.agenda import watch as watch  # noqa: E402 — s'enregistre sur AGENDA

__all__ = ["AGENDA", "ANSWERED", "APPROVED", "BEGUN", "BUNDLE", "CAPABILITY", "CREATE", "DELETE", "DONE", "EDIT",
           "ELSEWHERE", "EXPIRED", "FAILED", "FINAL", "GONE", "INVITATION_NOTICED", "INVITATION_SETTLED", "LEFT",
           "MOVED", "OFF", "OPS", "OWNER", "PROVENANCE", "REFUSED", "REMINDER_DROPPED", "REMINDER_DUE", "RESPOND",
           "SYNC_ASKED", "WAITING", "WRITTEN", "AgendaParams", "AgendaState", "AgendaWritten", "Invited", "Reminded",
           "SyncAsked", "Written",
           "cadence", "hers", "owner", "params", "params_of", "reminder"]
