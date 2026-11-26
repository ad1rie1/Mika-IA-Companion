"""Contrat de ``projects`` : ses projets, des boîtes noires qu'on pilote (ADR 0031).

Un **projet** n'est pas un but : un but est ce qu'elle se propose de faire
ensuite (une intention, une envie qui s'use) ; un projet est un espace de
travail durable — un dossier, son dépôt git, ses décisions techniques, ses
outils, ses exécutions — qu'une propriétaire lui confie ou qu'elle ouvre
d'elle-même.

- Son **mode** : ``persona`` (c'est elle qui y travaille, avec son humeur et
  ses avis ; ce qu'elle y mène à bout la rend fière) ou ``plain`` (un
  traitement impersonnel : sans persona, sans émotion, sans récit).
- Ses **objectifs**, par ligne : un **ponctuel** (``once``) se coche une fois,
  avec une preuve ; un **constant** (``constant``) ne finit jamais, chaque
  passage revient après sa cadence — ou quand ce qu'il déclare arrive (un
  commit d'un projet qu'il lit, un signal d'app, un réveil par API : ADR 0265).
- Une **exécution** (épisode ``WORK`` ou ``JOB``, cible ``project:<id>``) vise
  un objectif et se conclut par un verdict (``report_run``).

Ce que d'autres facultés lisent : ``objective_closed`` (un ponctuel abouti ou
bloqué, avec son mode — l'estime et l'attention ne réagissent qu'au mode
``persona``), ``run_reported`` et les faits ``LIVE`` / ``STATUS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.kernel.forms import Knob
from mika.kernel.guards import workshop
from mika.vocab import access
from mika.vocab.access import (
    ALONE,
    INTERNAL,
    NO,
    POLICIES,
    STEER_EDIT,
    STEER_NO,
    STEER_READ,
    STEERS,
    Policy,
    Rule,
    Steer,
)
from mika.vocab.access import CHANGES as CHANGES
from mika.vocab.access import STEER_ASK as STEER_ASK
from mika.vocab.privacy import Sensitivity

OWNER = "projects"

# modes
PERSONA, PLAIN = "persona", "plain"
MODES = (PERSONA, PLAIN)
# autorités
USER, SELF = "user", "self"
# statuts d'un projet
ACTIVE, PAUSED, ARCHIVED = "active", "paused", "archived"
STATUSES = (ACTIVE, PAUSED, ARCHIVED)
# l'état de son plan (ADR 0145) : sans plan (un projet d'avant, ou de la console), à cadrer (une séance de cadrage est
# due), plan proposé (il attend la réponse de qui l'a demandé), planifié (il suit son plan)
UNPLANNED, TO_FRAME, PROPOSED, PLANNED = "", "to_frame", "proposed", "planned"
# sortes et statuts d'un objectif
ONCE, CONSTANT = "once", "constant"
OBJECTIVE_KINDS = (ONCE, CONSTANT)
OPEN, DONE, BLOCKED, DROPPED = "open", "done", "blocked", "dropped"
OBJECTIVE_STATUSES = (OPEN, DONE, BLOCKED, DROPPED)
# verdicts d'une exécution
CONTINUE, WAIT = "continue", "wait"
VERDICTS = (CONTINUE, DONE, BLOCKED, WAIT)
# priorités (le vocabulaire du panneau du frontend)
LOW, NORMAL, HIGH, URGENT = "low", "normal", "high", "urgent"
PRIORITIES = (LOW, NORMAL, HIGH, URGENT)
# jours de la plage de travail
EVERY_DAY, WEEKDAYS, WEEKEND = "all", "weekdays", "weekend"
DAYS = (EVERY_DAY, WEEKDAYS, WEEKEND)
# statuts d'une décision technique
IN_FORCE, SUPERSEDED, WITHDRAWN = "active", "superseded", "withdrawn"
DECISION_STATUSES = (IN_FORCE, SUPERSEDED, WITHDRAWN)

# ── son registre (ADR 0268) : ses tickets et ses listes de suivi ──
#: la liste que tout projet a d'office
TICKETS = "tickets"
#: les statuts d'une liste de suivi, par défaut (réglables liste par liste) : ouverts, puis clos
#: (« fait » et « écarté » sont ``DONE`` et ``DROPPED``, les mots d'un objectif)
TODO, DOING = "todo", "doing"
ITEM_OPEN, ITEM_CLOSED = (TODO, DOING), (DONE, DROPPED)
#: les étapes d'un ticket, déduites de ses faits (``faculties/projects/tickets.py``, ``stage`` ; ADR 0270) — jamais
#: posées à la main : proposé (il attend que le propriétaire l'accepte), non lu, en analyse (elle l'a pris), en
#: attente de décision (sa question est dans le fil), en attente de validation (son plan est dans le fil), validé en
#: cours (son objectif existe, elle y travaille), traité, écarté. Sur un projet qui passe par des pull requests (ADR
#: 0274), « validé en cours » se dit en deux étapes : validé en attente de PR (elle y travaille, ou sa pull request
#: a été refusée), PR prête en attente de fusion (la main est au propriétaire)
STAGE_PROPOSED, STAGE_UNREAD, STAGE_TREATED, STAGE_DISMISSED = "proposed", "unread", "treated", "dismissed"
STAGE_ANALYSIS, STAGE_DECISION, STAGE_VALIDATION, STAGE_WORKING = "analysis", "decision", "validation", "working"
STAGE_PR_PENDING, STAGE_PR_READY = "pr_pending", "pr_ready"
STAGES_OPEN = (STAGE_PROPOSED, STAGE_UNREAD, STAGE_ANALYSIS, STAGE_DECISION, STAGE_VALIDATION, STAGE_WORKING,
               STAGE_PR_PENDING, STAGE_PR_READY)
STAGES_CLOSED = (STAGE_TREATED, STAGE_DISMISSED)
#: le flux d'un projet (ADR 0274) : son travail va droit sur sa branche (``direct``, comme toujours sans dépôt
#: distant), ou chaque travail a sa branche et finit en pull request (``pr`` : le défaut dès que l'hôte de son dépôt
#: distant sait en ouvrir une)
FLOW_DIRECT, FLOW_PR = "direct", "pr"
FLOWS = (FLOW_DIRECT, FLOW_PR)
#: ce qu'un ticket dit de la pull request de son objectif (``Item.pull``, ADR 0274) : rien (son projet n'en passe
#: pas par là), attendue (elle y travaille, ou elle a été refusée), prête (ouverte chez l'hôte, elle attend sa
#: fusion), fusionnée (le ticket se ferme avec elle)
PULL_NONE, PULL_AWAITED, PULL_READY, PULL_MERGED = "", "awaited", "ready", "merged"
PULLS = (PULL_NONE, PULL_AWAITED, PULL_READY, PULL_MERGED)
#: une note du fil d'un ticket qui a une sorte (ADR 0270) : sa question, son plan ; ``""`` : une note
NOTE_QUESTION, NOTE_PLAN = "question", "plan"
#: la validation du plan d'un ticket, réglée par projet (ADR 0270) : toujours, ou seulement pour ce qui n'est pas
#: petit
REVIEW_ALWAYS, REVIEW_LARGE = "always", "large"
REVIEWS = (REVIEW_ALWAYS, REVIEW_LARGE)
#: les jalons d'un objectif ponctuel (ADR 0273) : cinq vivants au plus ; comment un jalon se vérifie — une commande
#: que l'outil lance dans l'atelier, un point d'arrêt que le propriétaire tranche, un élément du registre dans un
#: statut donné, ou ce qu'elle en dit ; son statut — ouvert (``OPEN``), atteint, retiré (``DROPPED``)
MILESTONES_MAX = 5
CHECK_COMMAND, CHECK_OWNER, CHECK_ITEM, CHECK_PROSE = "command", "owner", "item", "prose"
CHECKS = (CHECK_PROSE, CHECK_COMMAND, CHECK_OWNER, CHECK_ITEM)
REACHED = "reached"
#: les sortes d'un ticket : un défaut, une tâche, une idée, une question
BUG, TASK, IDEA, QUESTION = "bug", "task", "idea", "question"
TICKET_KINDS = (BUG, TASK, IDEA, QUESTION)
#: qui agit sur un élément : elle, le propriétaire du projet, une personne (nommée à côté)
ACTOR_SELF, ACTOR_OWNER, ACTOR_PERSON = "self", "owner", "person"
ACTORS = (ACTOR_SELF, ACTOR_OWNER, ACTOR_PERSON)
#: qui a écrit (ouvert, changé, noté) : elle, une personne en conversation, l'opérateur dans la console — ou un autre
#: projet (``project:<n>``, ``item_author``)
BY_SELF, BY_PERSON, BY_OPERATOR, BY_PROJECT = "self", "person", "operator", "project"
#: …ou quelqu'un chez l'hôte du dépôt distant (ADR 0275) : une issue ouverte là-bas, un commentaire, une fermeture —
#: un inconnu, dont le nom de compte n'est jamais ici (il est dans le contenu de ce qu'il a écrit)
BY_HOST = "host"
#: le reflet des tickets d'un projet en issues chez l'hôte de son dépôt distant (ADR 0275), réglé par projet :
#: jamais ; sur accord (le défaut) — une publication se demande et attend l'accord, une fermeture aussi ; toujours
#: (la synchronisation) — chaque ticket ouvert par une personne se publie de lui-même. Quel que soit le réglage, ce
#: qui porte plus que le projet, un ticket qu'elle a ouvert elle-même et un ticket qui nomme une personne du projet
#: ne partent jamais sans accord (``faculties/projects/issues.py``, ``reasons``, ``publishing`` ; ADR 0278)
ISSUES_NEVER, ISSUES_ASK, ISSUES_ALWAYS = "never", "ask", "always"
ISSUES = (ISSUES_NEVER, ISSUES_ASK, ISSUES_ALWAYS)
#: la relecture indépendante d'un travail conclu (ADR 0276), réglée par projet : jamais ; avant de sortir (le défaut)
#: — avant qu'une pull request ou un envoi au dépôt distant soit proposé ; à chaque « fait » — aussi quand un
#: objectif ponctuel aboutit sur un projet dont rien ne sort (``faculties/projects/review.py``)
REREAD_NEVER, REREAD_OUT, REREAD_EACH = "never", "out", "each"
REREADS = (REREAD_NEVER, REREAD_OUT, REREAD_EACH)
#: les tables de sa projection : une ligne par élément, une ligne par note de son fil
REGISTRY_TABLE, REGISTRY_NOTES_TABLE = "project_items", "project_item_notes"


def item_author(project: int) -> str:
    """« Qui l'a écrit », quand c'est un autre projet (``project:<n>``)."""
    return f"{BY_PROJECT}:{project}"


def asking_project(author: str) -> int:
    """Le projet qui a écrit (``project:<n>`` : une demande d'un projet à un autre, ADR 0271) ; 0 : ce n'est pas un
    projet."""
    sort, _, number = (author or "").partition(":")
    return int(number) if sort == BY_PROJECT and number.isdecimal() else 0


def from_outside(author: str) -> bool:
    """Écrit par un autre que ceux du projet : l'hôte du dépôt, ou un projet qui lui adresse une demande."""
    return author == BY_HOST or bool(asking_project(author))


# raisons de preuve (arbitrage)
#: une exécution (épisode WORK ou JOB, cible ``project:<id>``)
RUN = "run"
#: raconter un objectif mené à bout (INITIATIVE ; en mode impersonnel, un compte rendu factuel)
SHARE = "project_share"
#: « j'ai besoin de toi pour… » : un objectif confié bloque ou attend quelque chose de qui l'a confié
NEED = "project_need"
#: « voilà comment je vois ça » : son plan, dit à qui a demandé le projet (ses questions, ou ce qu'elle va faire)
PLAN = "project_plan"
#: décalage : trop d'exécutions dans l'heure, tous projets confondus
RUN_CAP = "run_cap"


# ── qui peut quoi sur un projet et ses apps (ADR 0133, 0134) ──
#: piloter un projet : en lecture seule (elle en dit le détail — son dernier compte rendu, ce qui vient — sans rien y
#: changer) ; ses demandes (une consigne, un objectif, une pause, « vas-y maintenant ») sur l'accord du propriétaire, ou
#: appliquées aussitôt (modification) ; ou aucun pilotage — jamais son cadre (titre, outils, accord), qui reste dans la
#: console (``vocab.access.STEERS``)


class ProjectAccess(Rule):
    """Une ligne d'accès à un projet (ADR 0133, 0134), dans le cadre commun (``vocab.access.Rule`` : qui, par où,
    quand) : le voir (en entendre parler), le piloter (``STEERS``), ses fichiers (en recevoir), sa documentation (la
    lire : l'espace à part de son dépôt, ADR 0289 — fermée tant qu'on ne la coche pas), ce qu'elle fait d'un
    outil de ses apps qui lit et d'un outil qui agit (``POLICIES``), et à quels outils de ses apps ces deux colonnes
    s'appliquent (``<app>_<outil>`` ; vide : tous). Voir, piloter et fichiers valent quelle que soit la sélection
    d'outils."""

    see: Annotated[bool, Knob(label="Le voir", advanced=False)] = False
    steer: Annotated[Steer, Knob(label="Piloter projet", choices=STEERS, advanced=False)] = STEER_NO
    files: Annotated[bool, Knob(label="Ses fichiers", advanced=False)] = False
    docs: Annotated[bool, Knob(label="Sa documentation", advanced=False)] = False
    read: Annotated[Policy, Knob(label="Apps : un outil qui lit", choices=POLICIES, advanced=False)] = NO
    act: Annotated[Policy, Knob(label="Apps : un outil qui agit", choices=POLICIES, advanced=False)] = NO
    tools: Annotated[tuple[str, ...], Knob(label="Ses outils", advanced=False)] = ()

    def concerns(self, tool: str) -> bool:
        return not self.tools or tool in self.tools


#: la ligne par défaut fermée : personne d'autre ne le voit, ne le pilote ni ne se sert de ses apps
CLOSED = ProjectAccess()
#: un projet dont on n'a pas réglé les accès : toi, tout ; elle seule, tout ; les autres l'entendent selon ce que
#: permet sa confidentialité, en lecture seule, sans fichier ni ses apps
UNSET = (ProjectAccess(who=(access.OWNER,), see=True, steer=STEER_EDIT, files=True, docs=True, read=ALONE,
                       act=ALONE),
         ProjectAccess(who=(access.SELF,), canal=(INTERNAL,), see=True, steer=STEER_EDIT, files=True, docs=True,
                       read=ALONE, act=ALONE))
UNSET_DEFAULT = ProjectAccess(see=True, steer=STEER_READ)


class ProjectCreated(Payload):
    title: Content
    description: Content | None = None
    authority: str
    mode: str = PERSONA
    #: la personne pour qui (qui l'a confié, ou de qui il parle)
    owner: str | None = None
    #: où lui en parler
    address: str | None = None
    about: tuple[str, ...] = ()
    #: ses lots d'outils (l'atelier et ``projects`` en plus, toujours)
    bundles: tuple[str, ...] = ()
    #: ``manual``, ``interval:2h``, ``cron:0 9 * * MON-FRI``
    schedule: str = ""
    #: la plage de travail : ``all`` | ``weekdays`` | ``weekend``, et ses heures (minutes depuis minuit, locales)
    days: str = EVERY_DAY
    start_min: int = 0
    end_min: int = 24 * 60
    #: au plus tant d'exécutions par jour (0 : la valeur par défaut)
    runs_per_day: int = 0
    approval: bool = True
    priority: str = NORMAL
    #: le dépôt distant (https) et sa branche ; vide : aucun
    remote: str = ""
    branch: str = "main"
    #: pousser après chaque exécution qui a commité
    auto_push: bool = False
    #: son flux (ADR 0274) : ``direct``, ou ``pr`` — décidé à sa naissance par qui le crée, selon l'hôte de son
    #: dépôt distant
    flow: str = FLOW_DIRECT
    #: quand une exécution indépendante relit son travail conclu (ADR 0276 ; ``REREADS``)
    reread: str = REREAD_OUT
    #: d'où il vient : ``operator``, ``tool``, ``goal:12``, ``conversation``
    source: str = ""
    sensitivity: int = 1
    #: les mots de qui l'a demandé, tels quels (ses messages depuis sa dernière réponse), et qui (ADR 0145)
    request: Content | None = None
    asked_by: str | None = None
    #: il naît à cadrer : une séance écrit son plan avant toute exécution sur un objectif (ADR 0145)
    framing: bool = False


class ObjectiveClosed(Payload):
    """Un objectif ponctuel abouti (avec preuve) ou bloqué — ce qu'on en ressent dépend du mode."""

    project: int
    objective: int
    #: ``done`` | ``blocked``
    status: str
    mode: str = PERSONA
    authority: str = ""
    #: recopiés : ce qu'il en reste se dit sans relire le projet
    title: Content
    result: Content | None = None
    notable: float = 0.0
    owner: str | None = None
    about: tuple[str, ...] = ()
    #: les personnes des projets qu'il lit, ou a lus (ADR 0262) : pour l'oubli seulement — ce texte peut reprendre ce
    #: qu'il en a lu. Jamais « de qui ça parle » : qui lit cet événement ne les prend pas pour des personnes concernées
    read_about: tuple[str, ...] = ()
    sensitivity: int = 1


class RunReported(Payload):
    project: int
    objective: int = 0
    verdict: str
    summary: Content
    notable: float = 0.5
    mode: str = PERSONA
    #: « fait » avec une preuve (un outil qui a produit quelque chose pendant ce projet)
    proven: bool = False
    #: ce qu'elle a réellement fait pendant cette exécution (outils réussis qui changent quelque chose)
    tools: tuple[str, ...] = ()
    #: ce qui prouve que cette exécution a produit : ``commit`` (un commit non vide), ``outil`` (un brouillon,
    #: une app), ``""`` (rien) ; ``None`` : un ancien journal (chaque outil réussi comptait)
    proof: str | None = None
    #: « j'ai besoin de toi pour… » : ce qu'il lui faudrait de qui lui a confié le projet (rien : elle avance seule)
    need: Content | None = None
    #: le commit laissé dans l'atelier (vide : rien de changé)
    commit: str = ""
    #: la branche de travail où cette exécution a eu lieu (ADR 0274 ; vide : un projet au flux direct)
    branch: str = ""
    wait_s: int = 0
    owner: str | None = None
    about: tuple[str, ...] = ()
    #: les personnes des projets qu'il lit, ou a lus (ADR 0262) : pour l'oubli seulement, jamais « de qui ça parle »
    read_about: tuple[str, ...] = ()


PROJECT_CREATED = event_type("projects.created", OWNER, ProjectCreated, public=True,
                             content=("title", "description", "request"), subjects=("owner", "about", "asked_by"))
OBJECTIVE_CLOSED = event_type("projects.objective_closed", OWNER, ObjectiveClosed, public=True,
                              content=("title", "result"), subjects=("owner", "about", "read_about"))
RUN_REPORTED = event_type("projects.run_reported", OWNER, RunReported, public=True, content=("summary", "need"),
                          subjects=("owner", "about", "read_about"))
ALL = (PROJECT_CREATED, OBJECTIVE_CLOSED, RUN_REPORTED)


@dataclass(frozen=True, slots=True)
class ProjectView:
    id: int
    title_ref: str
    authority: str
    mode: str
    status: str
    owner: str | None
    #: de qui il parle, lui : ce qui décide de qui l'entend (jamais les personnes des projets qu'il lit)
    about: tuple[str, ...]
    sensitivity: int
    created_at: int
    priority: str = NORMAL
    schedule: str = ""
    #: ses objectifs : ponctuels ouverts, ponctuels faits, ponctuels bloqués, constants
    open_once: int = 0
    done_once: int = 0
    blocked_once: int = 0
    constants: int = 0
    blocked: int = 0
    runs: int = 0
    last_run_at: int = 0
    last_summary_ref: str = ""
    #: la sensibilité de ce qu'elle y écrit (comptes rendus, carnet, fichiers de l'atelier) : au moins
    #: « personnel » — ce qu'il faut pour qu'on puisse l'entendre, le lire ou le recevoir
    written: int = int(Sensitivity.PERSONAL)
    #: ses dernières consignes (références, la plus récente en dernier) : ce que qui suit le projet a demandé — ce
    #: qui en dépend (le tri de la file d'une de ses apps) les suit aussi
    instructions: tuple[str, ...] = ()
    #: ses lignes d'accès, dans leur ordre, et sa ligne par défaut (ADR 0133 ; jamais réglées : ``UNSET``) — ses apps
    #: les suivent
    access: tuple[ProjectAccess, ...] = UNSET
    default_access: ProjectAccess = UNSET_DEFAULT
    #: l'état de son plan (ADR 0145 : ``UNPLANNED``, ``TO_FRAME``, ``PROPOSED``, ``PLANNED``)
    plan_state: str = UNPLANNED
    #: les personnes des projets qu'il lit, ou a lus (ADR 0262) : les sujets de plus de ce qui sort de lui (un fichier
    #: partagé), pour l'oubli seulement — rien de ce qui décide de qui entend ne les lit
    read_about: tuple[str, ...] = ()


#: Les projets vivants (actifs ou en pause, pas archivés), du plus ancien au plus récent.
LIVE = FactKey("projects.live", type=tuple, time_varying=True)
#: Le statut d'un projet (``""`` : inconnu).
STATUS = FactFamily("projects.status", arg=int, type=str)


def run_lease(project: int) -> str:
    """La ressource que tient une exécution de ce projet (son atelier) : une seule à la fois, d'où qu'elle vienne
    (son agenda, un réveil par API — ADR 0068)."""
    return workshop(f"projet-{project}")

#: Quelque chose est-il en route hors de la machine pour ce projet (une commande, un envoi ou une récupération du
#: dépôt) ? Rien d'autre ne part dans son atelier pendant ce temps — une exécution venue d'un réveil par API non plus
#: (ADR 0068).
OUTGOING = FactFamily("projects.outgoing", arg=int, type=bool, time_varying=True)
#: Le statut d'un objectif, par ``(projet, objectif)`` (``""`` : inconnu) — une clôture n'en vaut que pour
#: un objectif encore ouvert.
OBJECTIVE_STATUS = FactFamily("projects.objective_status", arg=tuple, type=str)
#: Une fusion demandée est-elle en route pour la pull request d'un objectif, par ``(projet, objectif)`` (ADR 0292) ?
#: Une seule demande à la fois : celle qui arrive pendant qu'une autre attend l'hôte ne s'écrit pas.
MERGING = FactFamily("projects.merging", arg=tuple, type=bool)
#: Ce que vise un réveil par API dans un projet, par ``(projet, nom du réveil)`` (ADR 0265) : le sujet de l'objectif
#: constant ouvert qui déclare ce réveil (``wake:<nom>``), ``""`` s'il n'y en a pas. L'exécution que le réveil lance
#: le porte dans son sujet (``contracts.wakeup.subject``) : elle vise cet objectif.
WAKE_AIM = FactFamily("projects.wake_aim", arg=tuple, type=str)
