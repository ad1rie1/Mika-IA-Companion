"""Le direct (ADR 0308) : ce qui change ce que montrent les écrans de tous les jours leur est poussé, sur le ``/ws``
que chacun a déjà ouvert — une trame ``changed`` qui dit quoi a changé, jamais le contenu ; l'écran relit la route
qu'il montre (``docs/protocole-moi.md``, § 2 bis).

- **D'où ça vient.** Du journal (``listen``, abonné à ``Mind.subscribe`` : chaque lot commité, traduit type par type
  en sujets) ; des bases tenues à côté — le courrier relevé, le cache de Teams, l'annuaire (``touch``, leur
  ``on_change`` : appelé une fois l'écriture validée, depuis n'importe quel fil) ; de l'étape d'un épisode, qui ne vit
  qu'en mémoire (``step``, ``EpisodeRunner.on_step``) ; des comptes (``everyone`` : un nom, un téléphone).
- **Regroupé.** La première touche arme un délai (``WINDOW_S``) ; tout ce qui arrive pendant ce délai part ensemble.
  Un sujet qui revient sans cesse (une boîte qu'on range, une étape après l'autre) part au plus ``BURST`` fois d'affilée,
  puis une fois par ``GAP_S`` : ce qui attend n'est jamais perdu, il part dès que son sujet le peut.
- **Seulement ce que chacune peut voir.** À l'envoi, pour chaque personne connectée — et chaque canal de ses clients,
  car ce qu'elle voit d'un projet en dépend —, le service relit ce qu'elle a par les règles mêmes des routes
  (``mail.boxes``, ``teams.accounts``, ``projects.reaches``, ``agenda.seen_calendars``, le téléphone à sa
  personne ; pour un domaine qui a sa fiche, ce que dit sa part du direct : ``LivePart.seen``, ADR 0310) et ne
  garde que ses ressources : une boîte, une conversation, un projet d'une autre n'y paraissent jamais. Ce qu'on ne sait
  pas nommer part sans clé, seulement à qui a quelque chose dans ce domaine. Ce qui change qui voit quoi — les
  propriétaires et les partages d'une boîte, d'un compte Teams, les accès d'un projet, une adresse reliée à une
  personne, un réglage enregistré — part sans clé à toutes : le filtre lit l'état d'après, et celle qui vient de perdre
  l'accès doit le savoir aussi. Une règle qui lève ne prive pas les autres : ce qu'elle gardait ne part pas.
- **Hors de la boucle.** Ces règles lisent l'annuaire et le cache de Teams, que leurs écritures tiennent sous leur
  verrou le temps d'un lot : elles tournent dans un fil, sur l'état lu une fois et sur les comptes que les réglages
  disent (lus une fois par envoi, sur la boucle). Une seule relecture à la fois ; ce qui arrive pendant ce temps part
  avec la suivante.
- **Envoyé en parallèle.** Chaque personne reçoit sa trame sans attendre les autres, en ``SEND_TIMEOUT_S`` au plus ; ce
  qui lui est dit pendant qu'une trame lui part s'y ajoute et part juste après, en une — rien ne s'empile.
- **Rien n'est rattrapé.** Personne de connecté : rien ne se calcule. Le client relit tout à sa reconnexion.
- **Par domaine** (ADR 0310). La forme d'une touche est dans ``touches.py`` ; ce qu'un domaine change et ce que
  chacune en voit, dans la part du direct de sa fiche (``PARTS``). Ce service les réunit sans en nommer aucun ; ce
  qui reste écrit ici (le courrier, Teams, le téléphone, les projets, l'agenda) attend que son domaine ait la sienne.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mika.adapters.web.accounts import Account
from mika.adapters.web.hub import Hub
from mika.app.domains import DOMAINS, part
from mika.app.me import agenda as agenda_me
from mika.app.me import mail as mail_me
from mika.app.me import projects as projects_me
from mika.app.me import teams as teams_me
from mika.app.me.api import Call, me_of
from mika.app.me.common import allows
from mika.app.me.touches import EVERYONE, OWN, PERSON, PREPARE, READ, Touch
from mika.app.settings import (
    AGENDA_GOOGLE_KEY,
    AGENDA_GRANTS_KEY,
    AGENDA_KEY,
    EMAIL_KEY,
    MAIL_GRANTS_KEY,
    MAIL_IMAGES_KEY,
    TEAMS_KEY,
    TEAMS_KEYS_KEY,
)
from mika.contracts import email as email_c
from mika.contracts import identity as identity_c
from mika.contracts import location as location_c
from mika.contracts import phone as phone_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import teams as teams_c
from mika.contracts import trips as trips_c
from mika.faculties.projects import links
from mika.faculties.projects.faculty import ACCESS_SET, AMENDED, ARCHIVED, LINKS_SET, RESTORED
from mika.kernel.builtin import KERNEL, PARAMS_CHANGED
from mika.plugins import agenda as agenda_p
from mika.plugins import email as email_p
from mika.plugins import phone as phone_p
from mika.plugins import teams as teams_p
from mika.plugins import trips as trips_p
from mika.ports.agenda import split_calendar_key
from mika.ports.changes import (
    AGENDA,
    CONTACTS,
    KEYS,
    MAIL,
    MAIL_DRAFTS,
    MAIL_WORK,
    ME,
    OUTBOX,
    PHONE,
    PHONE_POSITION,
    PROJECTS,
    SETTINGS,
    TEAMS,
    TEAMS_DRAFTS,
    TEAMS_REPLIES,
    TEAMS_WORK,
    TOPICS,
    TRIPS,
    Change,
)
from mika.ports.mail import split_ref
from mika.ports.teams import DEFAULT_ACCOUNT, conversation_key, split_conversation_key
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.state import RUNTIME
from mika.vocab.episodes import Kind, project_of, task_of
from mika.vocab.ownership import OWNED

log = logging.getLogger("mika.live")

#: ce qui arrive pendant ce délai après la première touche part en une trame (s)
WINDOW_S = 0.15
#: un même sujet part au plus ``BURST`` fois d'affilée, puis une fois par ``GAP_S`` (s) tant qu'il revient : une boîte
#: qu'on range des heures durant ne fait pas relire chaque écran toutes les 150 ms
GAP_S = 1.0
BURST = 3
#: une trame à une personne part en ce délai au plus (s) : une connexion lente ne retient ni les autres ni la suite
SEND_TIMEOUT_S = 5.0

#: à qui va une touche (avec ``PERSON`` et ``EVERYONE``, ``touches.py``) : ce que dit une boîte, un compte Teams
#: (leurs propriétaires et leurs partages) ; un projet (ce qu'elle en voit) ; un agenda (son compte, ses partages :
#: ``agenda.seen_calendars``). La règle d'un domaine qui a sa fiche est dans sa part du direct (``SEEN``)
BOXES, ACCOUNTS, PROJECT = "boxes", "accounts", "project"
CALENDARS = "calendars"
#: ce que chaque domaine apporte au direct (ADR 0310) : la part de sa fiche, dans l'ordre des fiches
PARTS = tuple(part(d.live, "LIVE") for d in DOMAINS if d.live is not None)
#: sujet d'une base tenue à côté → la traduction de son domaine ; règle d'une touche → ce que la personne en voit
CHANGES = {topic: translate for part in PARTS for topic, translate in part.changes.items()}
SEEN = {rule: seen for part in PARTS for rule, seen in part.seen.items()}

#: ce que change le réglage d'un propriétaire (``kernel.params_changed``) : qui voit quoi, ce qui se règle — à toutes
#: — les contacts compris : qui voit ceux d'une boîte ou d'un compte Teams suit leurs propriétaires et leurs partages
#: (``contacts.reach``)
PARAMS: Mapping[str, tuple[str, ...]] = {
    email_c.OWNER: (SETTINGS, MAIL, MAIL_DRAFTS, ME, CONTACTS),
    teams_c.OWNER: (SETTINGS, TEAMS, TEAMS_REPLIES, ME, CONTACTS),
    "mcp": (SETTINGS,), phone_c.OWNER: (SETTINGS, PHONE), projects_c.OWNER: (PROJECTS, ME),
    trips_c.OWNER: (TRIPS,), location_c.OWNER: (PHONE_POSITION,),
    agenda_p.OWNER: (SETTINGS, AGENDA, ME),
    **{owner: topics for part in PARTS for owner, topics in part.params.items()}}

#: ce qu'un réglage enregistré hors du journal change (``Settings._put``, par sa clé), à toutes, sans clé ; tout autre
#: réglage, Paramètres seulement. Une boîte (ses serveurs, ses dossiers, sa connexion Microsoft), ses images permises ;
#: un compte Teams, la clé de son extension.
SAVED: Mapping[str, tuple[str, ...]] = {
    EMAIL_KEY: (SETTINGS, MAIL, MAIL_DRAFTS, ME, CONTACTS), MAIL_GRANTS_KEY: (SETTINGS, MAIL),
    MAIL_IMAGES_KEY: (SETTINGS, MAIL), TEAMS_KEY: (SETTINGS, TEAMS, TEAMS_REPLIES, ME, CONTACTS),
    TEAMS_KEYS_KEY: (SETTINGS, TEAMS), AGENDA_KEY: (SETTINGS, AGENDA, ME), AGENDA_GRANTS_KEY: (SETTINGS, AGENDA),
    AGENDA_GOOGLE_KEY: (SETTINGS, AGENDA),
    **{key: topics for part in PARTS for key, topics in part.saved.items()}}

#: ce qui, dans un projet, change qui le voit (ses accès, ce qu'il lit des autres, son propriétaire, son sujet ou son
#: niveau, archivé ou rendu) : le filtre lit l'état d'après — celle qui le perd doit le savoir aussi
PROJECT_REACH = frozenset(t.name for t in (ACCESS_SET, LINKS_SET, AMENDED, ARCHIVED, RESTORED))


def _state(frame: Any, owner: str) -> Any:
    """La tranche d'un propriétaire, ou ``None`` s'il n'est pas dans la composition."""
    return frame.root.slices.get(owner)


def _both(*values: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


# ── du journal ────────────────────────────────────────────────────────────


def _email(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    d, name = e.data, e.type.name
    if name == email_p.POLL_ASKED.name:
        return []
    ref = str(getattr(d, "mail", "") or "")
    box = str(getattr(d, "account", "") or "") or split_ref(ref)[0]
    out = [Touch(MAIL, BOXES, keys=_both(box))]
    if name == email_c.DRAFT_ASKED.name and ref:  # elle s'y met (``work`` : « waiting »)
        out.append(Touch(MAIL_WORK, BOXES, PREPARE, keys=(ref,)))
    if name == email_c.SENT.name and getattr(d, "draft", ""):  # un de ses brouillons est parti
        out += [Touch(MAIL_DRAFTS, BOXES, PREPARE, keys=_both(box)), Touch(ME, BOXES, OWN, owners=_both(box))]
    return out


def _teams_key(frame: Any, kernel: Any, ref: str) -> str:
    """La conversation d'un message (``compte~id``) : ce qu'elle en a remarqué ou ce qu'on lui a demandé, sinon le
    cache."""
    s = _state(frame, teams_p.TEAMS.name)
    seen = s.messages.get(ref) if s is not None else None
    if seen is not None:
        return conversation_key(seen.account, seen.conversation)
    asked = s.asked.get(ref) if s is not None else None
    if asked is not None:
        return conversation_key(asked.account, asked.conversation)
    port = kernel.ports.get("teams")
    found = port.message(ref) if port is not None and ref else None
    return conversation_key(found.account, found.conversation) if found is not None else ""


def _teams(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    d, name = e.data, e.type.name
    account = str(getattr(d, "account", "") or DEFAULT_ACCOUNT)
    conversation = str(getattr(d, "conversation", "") or "")
    if name == teams_p.SETTLED.name:  # une de ses réponses (une réponse de la personne : le cache le dit)
        s = _state(frame, teams_p.TEAMS.name)
        seen = teams_p.latest(s, d.draft) if s is not None else None
        if seen is None:
            return []
        account, conversation = seen.account, seen.conversation
    yours = (account,)
    if name in (teams_p.RECEIVED.name, teams_p.IMAGES.name, teams_p.IMAGE_SEEN.name):
        # ce qui est arrivé, le cache le nomme ; une réponse à laquelle la personne a répondu autrement ne part plus
        return [Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=yours), Touch(ME, ACCOUNTS, OWN, owners=yours)] \
            if getattr(d, "replied", ()) else []
    keys = (conversation_key(account, conversation),) if conversation else ()
    out = [Touch(TEAMS, ACCOUNTS, keys=keys, owners=yours)]
    if name == teams_c.DRAFT_ASKED.name:
        out.append(Touch(TEAMS_WORK, ACCOUNTS, PREPARE, keys=keys, owners=yours))
    if name in (teams_c.SENT.name, teams_p.SETTLED.name):
        out += [Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=yours), Touch(ME, ACCOUNTS, OWN, owners=yours)]
    return out


def _phone(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Ses messages, ses réponses offertes : à elle seule — son adresse ou sa personne, la règle de ``phone.api._mine``."""
    d, name = e.data, e.type.name
    s = _state(frame, phone_p.PHONE.name)
    if name == phone_c.RECEIVED.name:
        m = s.messages.get(e.seq) if s is not None else None
        if m is None:
            return [Touch(PHONE, PERSON, owners=_both(d.handle))]
        return [Touch(PHONE, PERSON, keys=(f"{m.source}|{m.thread}",), owners=_both(m.handle, m.person))]
    offer = (s.offers.get(e.seq if name == phone_c.DRAFTED.name else d.draft) if s is not None else None)
    if offer is None:
        return []
    return _offered(offer)


def _offered(o: Any) -> list[Touch]:
    who = _both(o.handle, o.person)
    return [Touch(PHONE, PERSON, keys=(f"{o.source}|{o.thread}",), owners=who), Touch(ME, PERSON, owners=who)]


def _location(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    return [Touch(PHONE_POSITION, PERSON, owners=_both(e.data.handle, e.data.person))]


def _trips(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Un voyage est à sa personne, telle que l'identité la relie maintenant ; un regard, aussi à l'adresse qui l'a
    demandé (la règle de ``maps``)."""
    d = e.data
    return [Touch(TRIPS, PERSON, owners=_both(trips_p.owner_key(frame.get, d.person), getattr(d, "handle", "")))]


def _projects(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    if e.type.name in PROJECT_REACH:  # qui le voit a peut-être changé : à toutes, sans clé
        return [Touch(PROJECTS, EVERYONE), Touch(ME, EVERYONE)]
    pid = e.seq if e.type.name == projects_c.PROJECT_CREATED.name else getattr(e.data, "project", None)
    return _project(pid)


def _project(pid: Any) -> list[Touch]:
    keys = (str(pid),) if isinstance(pid, int) and pid > 0 else ()
    return [Touch(PROJECTS, PROJECT, keys=keys), Touch(ME, PROJECT, owners=keys)]


def _work(kind: str, target: str | None, frame: Any, kernel: Any, *, projects: bool = True) -> list[Touch]:
    """Où elle en est d'une réponse (ADR 0306) : sa tâche sur un mail, sur un message de Teams ; et, au départ et à la
    fin d'une exécution, son projet."""
    found = task_of(target) if kind == Kind.TASK else None
    if found is not None and found[0] == email_c.OWNER:
        return [Touch(MAIL_WORK, BOXES, PREPARE, keys=(found[1],))]
    if found is not None and found[0] == teams_c.OWNER:
        key = _teams_key(frame, kernel, found[1])
        return [Touch(TEAMS_WORK, ACCOUNTS, PREPARE, keys=(key,))] if key else []
    pid = project_of(target) if projects else None
    return [Touch(PROJECTS, PROJECT, keys=(str(pid),))] if pid else []


def _effect(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Un brouillon proposé, décidé, parti : celui d'une boîte, d'un compte Teams, du téléphone — ce que leur tranche
    en garde, par sa proposition ; un accord d'un projet, par son contexte."""
    d = e.data
    proposal = e.seq if e.type is rt.EFFECT_PROPOSED else d.proposal
    mail = _state(frame, email_p.EMAIL.name)
    seen = mail.drafts.get(proposal) if mail is not None else None
    if seen is not None:
        box = _both(seen.account)
        out = [Touch(MAIL_DRAFTS, BOXES, PREPARE, keys=box), Touch(MAIL, BOXES, keys=box),
               Touch(ME, BOXES, OWN, owners=box)]
        return out + ([Touch(MAIL_WORK, BOXES, PREPARE, keys=(seen.mail,))] if seen.mail else [])
    teams = _state(frame, teams_p.TEAMS.name)
    reply = teams.drafts.get(proposal) if teams is not None else None
    if reply is not None:
        yours = (reply.account,)
        keys = (conversation_key(reply.account, reply.conversation),) if reply.conversation else ()
        return [Touch(TEAMS, ACCOUNTS, keys=keys, owners=yours), Touch(TEAMS_WORK, ACCOUNTS, PREPARE, keys=keys),
                Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=yours), Touch(ME, ACCOUNTS, OWN, owners=yours)]
    phone = _state(frame, phone_p.PHONE.name)
    offer = next((o for o in phone.offers.values() if o.proposal == proposal), None) if phone is not None else None
    if offer is not None:
        return _offered(offer)
    agenda = _state(frame, agenda_p.OWNER)
    written = agenda.writes.get(proposal) if agenda is not None else None
    if written is not None:  # ce qu'elle propose d'écrire dans un agenda : proposé, décidé, fait
        return _calendar(written.calendar)
    pid = project_of(getattr(d, "context", "") or "")
    return _project(pid) if pid else []


def _calendar(calendar: str) -> list[Touch]:
    """Un agenda a changé : à qui le voit (son compte, ses partages), et ses pastilles (ce qui attend sa décision)."""
    if not calendar:
        return []
    account = split_calendar_key(calendar)[0]
    return [Touch(AGENDA, CALENDARS, keys=(calendar,)), Touch(ME, CALENDARS, owners=_both(account))]


def _agenda(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Ce qu'elle a écrit, et les invitations dont elle prépare la réponse : leur agenda."""
    d, name = e.data, e.type.name
    if name in (agenda_p.WRITTEN.name, agenda_p.INVITATION_NOTICED.name):
        return _calendar(str(d.calendar))
    if name == agenda_p.INVITATION_SETTLED.name:
        s = _state(frame, agenda_p.OWNER)
        inv = s.invitations.get(d.key) if s is not None else None
        return _calendar(inv.calendar) if inv is not None else []
    return []


def _runtime(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    if e.type in (rt.EFFECT_PROPOSED, rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED):
        return _effect(e, frame, kernel)
    if e.type in (rt.EPISODE_STARTED, rt.EPISODE_ENDED):
        return _work(e.data.kind, e.data.target, frame, kernel)
    return []


def _kernel(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    if e.type is not PARAMS_CHANGED:
        return []
    return [Touch(topic, EVERYONE) for topic in PARAMS.get(e.data.owner, ())]


def _identity(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Une adresse reliée à une personne (ou déliée) : à qui elle est (``me.person``) change ce qui est à elle dans
    chaque domaine — les boîtes et les comptes « personne:… », son téléphone, sa position, ses voyages, ses contacts,
    ses projets. Rare : tous les domaines, à toutes, sans clé."""
    return [Touch(topic, EVERYONE) for topic in TOPICS] if e.type is identity_c.LINKED else []


#: chaque propriétaire d'événements dont le journal change ce que montrent les écrans, et sa traduction
BY_OWNER = {email_c.OWNER: _email, teams_c.OWNER: _teams, phone_c.OWNER: _phone, location_c.OWNER: _location,
            trips_c.OWNER: _trips, projects_c.OWNER: _projects, rt.OWNER: _runtime, KERNEL.name: _kernel,
            identity_c.OWNER: _identity, agenda_p.OWNER: _agenda,
            **{owner: translate for part in PARTS for owner, translate in part.events.items()}}


def touches_of(events: Iterable[Any], frame: Any, kernel: Any) -> list[Touch]:
    """Ce qu'un lot commité change, traduit événement par événement (``frame`` : l'état juste après) ; un événement
    qui ne se traduit pas (une panne de sa traduction) ne prive pas les autres."""
    out: list[Touch] = []
    for e in events:
        translate = BY_OWNER.get(e.type.owner)
        if translate is None:
            continue
        got = call(translate, e, frame, kernel, label=f"le direct ({e.type.name})")
        if not isinstance(got, Failed):
            out += got
    return out


# ── des bases tenues à côté ───────────────────────────────────────────────


def touches_from(change: Change) -> list[Touch]:
    """Ce qu'une écriture d'une base tenue à côté change : ses boîtes, ses comptes et ses conversations, ses sources."""
    if change.topic in (MAIL, MAIL_DRAFTS):
        return [Touch(change.topic, BOXES, PREPARE if change.topic == MAIL_DRAFTS else READ, keys=change.accounts)]
    if change.topic == TEAMS:
        return [Touch(TEAMS, ACCOUNTS, keys=change.keys, owners=change.accounts)]
    if change.topic in (TEAMS_DRAFTS, OUTBOX):  # un brouillon, ce que la boîte d'envoi en fait : son fil, ses réponses
        return [Touch(TEAMS, ACCOUNTS, keys=change.keys, owners=change.accounts),
                Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=change.accounts)]
    if change.topic == AGENDA:  # un agenda relu, écrit, réglé ; un compte synchronisé (sa dernière synchro, son erreur)
        return [Touch(AGENDA, CALENDARS, keys=change.keys, owners=change.accounts),
                Touch(ME, CALENDARS, owners=change.accounts)]
    translate = CHANGES.get(change.topic)  # la base d'un domaine qui a sa fiche
    return list(translate(change)) if translate is not None else []




# ── ce que chacune voit ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Listed:
    """Les comptes d'un port (des boîtes, des comptes Teams) tels que ses réglages les disent, lus une fois sur la
    boucle : ce que les règles des routes en lisent (``held_by``, ``contacts.reach``), sans base ni verrou."""

    found: tuple[Any, ...]

    def accounts(self) -> list[Any]:
        return list(self.found)


class Seen(Call):
    """Ce qu'une route de son espace lirait, sans requête, sur un état lu une fois (``frame``) et sur les comptes que
    les réglages disent (``ports`` : ``Listed``, lus sur la boucle) — ce que le direct relit dans un fil : rien n'y
    touche la base de son journal, que seule la boucle lit."""

    __slots__ = ("_frame", "_ports")

    def __init__(self, me: Any, kernel: Any, api: Any, frame: Any, ports: Mapping[str, Any]) -> None:
        super().__init__(None, me, kernel, {}, api)  # type: ignore[arg-type]
        self._frame = frame
        self._ports = dict(ports)

    @property
    def frame(self) -> Any:
        return self._frame

    def port(self, name: str) -> Any:
        return self._ports[name] if name in self._ports else super().port(name)


@dataclass(slots=True)
class Reader:
    """Ce qu'une personne voit, par ce canal, lu par les règles des routes — chaque domaine une fois, à la demande. Une
    règle qui lève ne voit rien (rien de ce qu'elle gardait ne part) et ne prive pas les autres."""

    call: Call
    channel: str
    _seen: dict[str, Any] = field(default_factory=dict)

    def _once(self, name: str, read: Any, empty: Any) -> Any:
        if name not in self._seen:
            got = call(read, label=f"le direct ({name})")
            self._seen[name] = empty if isinstance(got, Failed) else got
        return self._seen[name]

    def levels(self, rule: str) -> dict[str, str]:
        """Ses boîtes, ou ses comptes Teams : la clé et son niveau (les siens, ceux qu'on lui partage)."""
        held = mail_me.boxes if rule == BOXES else teams_me.accounts
        return self._once(rule, lambda: {key: level for key, (_, level) in held(self.call).items()}, {})

    def projects(self) -> frozenset[str]:
        """Ses projets, ceux qu'elle voit par ce canal (``projects.reaches``)."""

        def read() -> frozenset[str]:
            frame = self.call.frame
            sc = projects_me.Scene(self.call, frame, frame.state(projects_c.OWNER), links.world_of(frame),
                                   projects_me.audience_at(frame, self.call.me, self.channel), self.call.me.person)
            return frozenset(str(pid) for pid in projects_me.reaches(sc))

        return self._once(PROJECT, read, frozenset())

    def calendars(self) -> tuple[frozenset[str], frozenset[str]]:
        """Les agendas qu'on lui partage, et ses comptes d'agenda (``agenda.seen_calendars``)."""
        return self._once(CALENDARS, lambda: agenda_me.seen_calendars(self.call), (frozenset(), frozenset()))

    def _agenda(self, t: Touch) -> tuple[bool, tuple[str, ...]]:
        """Un agenda est à elle par son compte, ou par un partage encore ouvert ; un compte, s'il est à elle ou si un
        de ses agendas lui est partagé. Sans clé ni compte : tout le domaine (elle a toujours son agenda)."""
        shared, accounts = self.calendars()
        if t.keys:
            kept = tuple(k for k in t.keys if k in shared or split_calendar_key(k)[0] in accounts)
            return bool(kept), kept
        if not t.owners:
            return True, ()
        reach = accounts | {split_calendar_key(c)[0] for c in shared}
        return bool(reach & set(t.owners)), ()

    def judge(self, t: Touch) -> tuple[bool, tuple[str, ...]]:
        """Cette touche la concerne-t-elle, et ce qu'elle peut en voir nommé."""
        me = self.call.me
        if t.rule == EVERYONE:
            return True, ()
        if t.rule == CALENDARS:
            return self._agenda(t)
        if t.rule == PERSON:
            mine = me.handle in t.owners or me.person in t.owners
            return mine, t.keys if mine else ()
        if t.rule in SEEN:  # la règle d'un domaine : ce que sa part du direct dit qu'elle voit
            seen = self._once(t.rule, lambda: frozenset(SEEN[t.rule](self.call)), frozenset())
        elif t.rule == PROJECT:
            seen = self.projects()
        else:
            seen = frozenset(a for a, level in self.levels(t.rule).items()
                             if t.need == READ or (level == OWNED if t.need == OWN else allows(level, t.need)))
        if t.keys:
            kept = tuple(k for k in t.keys if _owner_of(t, k) in seen)
            return bool(kept), kept
        return (bool(seen & set(t.owners)) if t.owners else bool(seen)), ()

    def changes(self, touches: Sequence[Touch]) -> list[dict[str, Any]]:
        """La trame de cette personne : un sujet par élément, dans l'ordre du contrat ; un sujet sans clé dit tout son
        domaine et l'emporte sur ce qu'on y nommait."""
        found: dict[str, set[Any] | None] = {}
        for t in sorted(touches, key=lambda t: t.weak):  # une touche faible après les autres : elle ne les efface pas
            got = call(self.judge, t, label="le direct (une règle)")
            if isinstance(got, Failed):
                continue
            mine, keys = got
            if mine and not (t.weak and t.topic in found):
                _add_keys(found, t.topic, keys)
        return _ordered(found)


def _add_keys(found: dict[str, set[Any] | None], topic: str, keys: Iterable[Any]) -> None:
    """Ce sujet, avec ces clés (aucune : tout le domaine, qui l'emporte)."""
    keys = tuple(keys)
    if not keys or topic not in KEYS:
        found[topic] = None
    elif (known := found.get(topic, set())) is not None:
        found[topic] = known | set(keys)


def _ordered(found: Mapping[str, set[Any] | None]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for topic in TOPICS:
        if topic not in found:
            continue
        keys = found[topic]
        item: dict[str, Any] = {"topic": topic}
        if keys:
            item[KEYS[topic]] = sorted(int(k) for k in keys) if topic == PROJECTS else sorted(keys)
        out.append(item)
    return out


def merged(*frames: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Plusieurs trames d'une même personne en une : les clés d'un sujet s'ajoutent, un sujet sans clé l'emporte."""
    found: dict[str, set[Any] | None] = {}
    for frame in frames:
        for item in frame:
            topic = str(item["topic"])
            name = KEYS.get(topic)
            _add_keys(found, topic, item.get(name) or () if name else ())
    return _ordered(found)


def _owner_of(t: Touch, key: str) -> str:
    """Le compte d'une clé : la boîte d'une référence, le compte d'une conversation ; un projet est sa clé."""
    if t.rule == BOXES:
        return split_ref(key)[0] if t.topic == MAIL_WORK else key
    if t.rule == ACCOUNTS:
        return split_conversation_key(key)[0]
    return key


# ── le service ────────────────────────────────────────────────────────────

#: à qui va une trame : une personne (son adresse) et le canal de ses clients
Recipient = tuple[str, str]


class LiveChanges:
    """Ce qui change, regroupé puis poussé à chaque personne connectée, filtré par ses droits (ADR 0308). ``api`` :
    l'API par personne (ce que ses routes lisent) ; ``window_s`` : le regroupement ; ``gap_s`` et ``burst`` : le rythme
    d'un même sujet (``gap_s`` nul : aucun) ; ``send_timeout_s`` : l'attente d'un envoi.

    Ce qui arrive (``_add``, de n'importe quel fil) attend le délai du regroupement, puis passe par le rythme de son
    sujet (``_admit``, sur la boucle : ce qui doit attendre son tour est gardé, ``_held``) ; ce qui peut partir est
    relu par une seule tâche à la fois (``_drain`` : les règles dans un fil), puis confié à chaque personne
    (``_deliver`` : une trame en vol par personne et par canal, ce qui suit s'y ajoute)."""

    def __init__(self, kernel: Any, hub: Hub, api: Any = None, *, window_s: float = WINDOW_S, gap_s: float = GAP_S,
                 burst: int = BURST, send_timeout_s: float = SEND_TIMEOUT_S) -> None:
        self.kernel = kernel
        self.hub = hub
        self.api = api
        self.window_s = window_s
        self.gap_s = gap_s
        self.burst = max(1, burst)
        self.send_timeout_s = send_timeout_s
        self._lock = threading.Lock()
        self._pending: list[Touch] = []
        self._armed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        # le reste ne se touche que sur la boucle
        self._held: list[Touch] = []
        self._held_timer: asyncio.TimerHandle | None = None
        #: par sujet : ce qu'il lui reste d'envois d'affilée, et quand on l'a compté (horloge de la boucle)
        self._budget: dict[str, tuple[float, float]] = {}
        self._ready: list[Touch] = []
        self._sender: asyncio.Task[None] | None = None
        #: par personne et canal dont une trame est en vol : ce qui partira juste après, en une
        self._waiting: dict[Recipient, list[dict[str, Any]]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    def start(self) -> None:
        """Sur la boucle du serveur : avant, rien ne part (la relecture de sa vie ne prévient personne)."""
        self._loop = asyncio.get_running_loop()

    async def stop(self) -> None:
        self._loop = None
        with self._lock:
            self._pending, self._armed = [], False
        if self._held_timer is not None:
            self._held_timer.cancel()
            self._held_timer = None
        self._held, self._ready = [], []
        for task in [*self._tasks, *([self._sender] if self._sender is not None else [])]:
            task.cancel()
        self._waiting.clear()

    # ── ce qui le prévient ──
    def listen(self, events: Sequence[Any], root: Any) -> None:
        """Un lot commité (``Mind.subscribe``, sur la boucle) : traduit, s'il y a quelqu'un à prévenir."""
        if self._loop is None or not self.hub.signed_in():
            return
        found = call(touches_of, events, self.kernel.mind.frame(), self.kernel, label="le direct (journal)")
        if not isinstance(found, Failed):
            self._add(found)

    def touch(self, change: Change) -> None:
        """Une écriture validée d'une base tenue à côté (``on_change``), depuis n'importe quel fil."""
        self._add(touches_from(change))

    def step(self, episode: str) -> None:
        """L'étape d'un épisode a changé (``EpisodeRunner.on_step``) : sa tâche sur un mail ou un message de Teams."""
        if self._loop is None or not self.hub.signed_in():
            return
        frame = self.kernel.mind.frame()
        opened = frame.state(RUNTIME.name).open.get(episode)
        if opened is not None:
            self._add(_work(opened.kind, opened.target, frame, self.kernel, projects=False))

    def everyone(self, *topics: str) -> None:
        """Ce qui change pour qui que ce soit sans rien nommer (un compte, ses téléphones) : à toutes, sans clé."""
        self._add([Touch(topic, EVERYONE) for topic in topics])

    def saved(self, key: str) -> None:
        """Un réglage enregistré hors du journal (``Settings.on_saved``, par sa clé) : ce qu'il change, à toutes."""
        self.everyone(*SAVED.get(key, (SETTINGS,)))

    def presence(self, account: str) -> None:
        """La présence de l'extension de ce compte Teams se voit autrement (``TeamsDesk.on_presence``) : ses comptes se
        relisent, chez qui le lit — une touche faible, que ce qu'un lot du même instant nomme suffit à dire."""
        self._add([Touch(TEAMS, ACCOUNTS, owners=(account,), weak=True)])

    def agenda_signed(self, account: str) -> None:
        """La connexion Google ou Microsoft d'un compte d'agenda a changé (``on_state`` : connecté, refusé, échu, le
        code d'appareil entré) : à qui le lit."""
        self._add([Touch(AGENDA, CALENDARS, owners=(account,))])

    def signed(self, box: str) -> None:
        """L'attente d'un code Microsoft a fini pour cette boîte (``MicrosoftSignIn.on_state`` : connectée, refusée,
        échue) : à qui la lit, et ses réglages à qui en est propriétaire."""
        self._add([Touch(MAIL, BOXES, keys=(box,)), Touch(SETTINGS, BOXES, OWN, owners=(box,))])

    # ── le regroupement ──
    def _add(self, touches: Sequence[Touch]) -> None:
        loop = self._loop
        if not touches or loop is None:
            return
        with self._lock:
            self._pending.extend(touches)
            if self._armed:
                return
            self._armed = True
        try:
            loop.call_soon_threadsafe(self._arm)
        except RuntimeError:  # la boucle s'est arrêtée : plus personne à prévenir
            with self._lock:
                self._pending, self._armed = [], False

    def _arm(self) -> None:
        if self._loop is not None:
            self._loop.call_later(self.window_s, self._fire)

    def _fire(self) -> None:
        with self._lock:
            touches, self._pending, self._armed = self._pending, [], False
        if touches:
            self._admit(touches)

    # ── le rythme d'un sujet ──
    def _spend(self, topic: str, now: float) -> bool:
        """Ce sujet peut-il partir maintenant ? Il a ``burst`` envois d'affilée, qui reviennent un par ``gap_s``."""
        if self.gap_s <= 0:
            return True
        left, at = self._budget.get(topic, (float(self.burst), now))
        left = min(float(self.burst), left + (now - at) / self.gap_s)
        ok = left >= 1 - 1e-9
        self._budget[topic] = (left - 1 if ok else left, now)
        return ok

    def _admit(self, touches: Sequence[Touch]) -> None:
        """(Sur la boucle.) Ce qui attendait son tour et ce qui arrive : ce dont le sujet peut partir part (toutes
        ses touches ensemble) ; le reste attend le premier tour qui revient."""
        loop = self._loop
        if loop is None:
            return
        pool = list(dict.fromkeys([*self._held, *touches]))
        self._held = []
        if self._held_timer is not None:
            self._held_timer.cancel()
            self._held_timer = None
        now = loop.time()
        go: list[Touch] = []
        spent: set[str] = set()
        refused: set[str] = set()
        for t in pool:
            if t.topic not in spent and t.topic not in refused:
                (spent if self._spend(t.topic, now) else refused).add(t.topic)
            (go if t.topic in spent else self._held).append(t)
        if self._held:
            due = min(at + max(0.0, 1 - left) * self.gap_s
                      for left, at in (self._budget[topic] for topic in refused))
            self._held_timer = loop.call_at(due, self._unhold)
        if go:
            self._ready.extend(go)
            if self._sender is None or self._sender.done():
                self._sender = loop.create_task(self._drain())

    def _unhold(self) -> None:
        self._held_timer = None
        self._admit([])

    # ── l'envoi ──
    async def _drain(self) -> None:
        """Une relecture à la fois : ce qui est prêt pendant qu'elle tourne part avec la suivante."""
        while self._ready:
            batch, self._ready = self._ready, []
            await acall(self._dispatch, batch, label="le direct (envoi)")

    async def send(self, touches: Sequence[Touch]) -> int:
        """Ces touches, à chaque personne connectée (par canal), ce qu'elle en voit ; rend combien de trames sont
        parties (ce qui s'ajoute à une trame déjà en vol part avec elle, sans être compté ici)."""
        tasks = await self._dispatch(touches)
        return sum(await asyncio.gather(*tasks)) if tasks else 0

    async def _dispatch(self, touches: Sequence[Touch]) -> list[asyncio.Task[int]]:
        said = await self._judged(touches)
        return [task for task in (self._deliver(key, changes) for key, changes in said.items()) if task is not None]

    def _listed(self) -> dict[str, Listed]:
        """(Sur la boucle.) Les boîtes et les comptes Teams que disent les réglages, lus une fois pour cet envoi : leur
        lecture passe par la base du journal, que seule la boucle lit. Illisibles : aucun (rien ne part qui les nomme)."""
        out: dict[str, Listed] = {}
        for name, read in (("mail", lambda port: port.accounts()),
                           ("teams", lambda port: port.accounts(extension=False))):
            port = self.kernel.ports.get(name)
            if port is not None:
                got = call(functools.partial(read, port), label=f"le direct (les comptes de {name})")
                out[name] = Listed(() if isinstance(got, Failed) else tuple(got))
        return out

    async def _judged(self, touches: Sequence[Touch]) -> dict[Recipient, list[dict[str, Any]]]:
        """Ce que chaque personne connectée en voit, par canal : les règles des routes, dans un fil."""
        groups: dict[Recipient, Any] = {}
        for conn in self.hub.signed_in():
            groups.setdefault((conn.handle, conn.channel), conn)
        if not groups:
            return {}
        frame = self.kernel.mind.frame()
        ports = self._listed()
        readers = {key: Reader(Seen(me_of(frame, Account(int(conn.account), "", conn.display_name, conn.operator,
                                                         True)), self.kernel, self.api, frame, ports), key[1])
                   for key, conn in groups.items()}

        def judge() -> dict[Recipient, list[dict[str, Any]]]:
            out: dict[Recipient, list[dict[str, Any]]] = {}
            for key, reader in readers.items():
                got = call(reader.changes, touches, label=f"le direct ({key[0]})")
                if not isinstance(got, Failed) and got:
                    out[key] = got
            return out

        return await asyncio.to_thread(judge)

    def _deliver(self, key: Recipient, said: list[dict[str, Any]]) -> asyncio.Task[int] | None:
        """Sa trame part, sans attendre les autres ; si une trame lui part déjà, celle-ci s'y ajoute et part juste
        après (rien rend ``None``)."""
        if key in self._waiting:
            self._waiting[key] = merged(self._waiting[key], said)
            return None
        self._waiting[key] = []
        task = asyncio.get_running_loop().create_task(self._push(key, said))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _push(self, key: Recipient, said: list[dict[str, Any]]) -> int:
        sent = 0
        try:
            while said:
                got = await acall(self._one, key, said, label=f"le direct ({key[0]})")
                sent += got if isinstance(got, int) else 0
                said, self._waiting[key] = self._waiting.get(key, []), []
        finally:
            self._waiting.pop(key, None)
        return sent

    async def _one(self, key: Recipient, said: list[dict[str, Any]]) -> int:
        try:
            return await asyncio.wait_for(self.hub.push_changed(key[0], key[1], said), self.send_timeout_s)
        except TimeoutError:  # une connexion qui ne prend plus rien : elle relira tout à sa reconnexion
            log.info("le direct : une trame pour %s n'est pas partie en %g s", key[0], self.send_timeout_s)
            return 0
