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
  passage revient après sa cadence.
- Une **exécution** (épisode ``WORK`` ou ``JOB``, cible ``project:<id>``) vise
  un objectif et se conclut par un verdict (``report_run``).

Ce que d'autres facultés lisent : ``objective_closed`` (un ponctuel abouti ou
bloqué, avec son mode — l'estime et l'attention ne réagissent qu'au mode
``persona``), ``run_reported`` et les faits ``LIVE`` / ``STATUS``.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
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

# raisons de preuve (arbitrage)
#: une exécution (épisode WORK ou JOB, cible ``project:<id>``)
RUN = "run"
#: raconter un objectif mené à bout (INITIATIVE ; en mode impersonnel, un compte rendu factuel)
SHARE = "project_share"
#: « j'ai besoin de toi pour… » : un objectif confié bloque ou attend quelque chose de qui l'a confié
NEED = "project_need"
#: décalage : trop d'exécutions dans l'heure, tous projets confondus
RUN_CAP = "run_cap"


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
    #: d'où il vient : ``operator``, ``tool``, ``goal:12``, ``conversation``
    source: str = ""
    sensitivity: int = 1


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
    wait_s: int = 0
    owner: str | None = None
    about: tuple[str, ...] = ()


PROJECT_CREATED = event_type("projects.created", OWNER, ProjectCreated, public=True,
                             content=("title", "description"), subjects=("owner", "about"))
OBJECTIVE_CLOSED = event_type("projects.objective_closed", OWNER, ObjectiveClosed, public=True,
                              content=("title", "result"), subjects=("owner", "about"))
RUN_REPORTED = event_type("projects.run_reported", OWNER, RunReported, public=True, content=("summary", "need"),
                          subjects=("owner", "about"))
ALL = (PROJECT_CREATED, OBJECTIVE_CLOSED, RUN_REPORTED)


@dataclass(frozen=True, slots=True)
class ProjectView:
    id: int
    title_ref: str
    authority: str
    mode: str
    status: str
    owner: str | None
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


#: Les projets vivants (actifs ou en pause, pas archivés), du plus ancien au plus récent.
LIVE = FactKey("projects.live", type=tuple, time_varying=True)
#: Le statut d'un projet (``""`` : inconnu).
STATUS = FactFamily("projects.status", arg=int, type=str)
#: Le statut d'un objectif, par ``(projet, objectif)`` (``""`` : inconnu) — une clôture n'en vaut que pour
#: un objectif encore ouvert.
OBJECTIVE_STATUS = FactFamily("projects.objective_status", arg=tuple, type=str)
