"""Contrat de ``goals`` : ce qu'elle a entrepris.

Un **but** a une sorte, une **autorité** et, souvent, une personne :

- un **rappel** (``reminder``) : quelqu'un lui a demandé de lui rappeler
  quelque chose à une heure dite. Autorité de la personne ; il se dit à
  l'heure — l'ordinaire attend son réveil, l'urgent la réveille.
- une **exploration** (``exploration``) : c'est elle, parce qu'une pensée
  insiste ou qu'une curiosité la tient. Une envie qui s'use (demi-vie).
- un **projet** (``project``) : un travail confié par son propriétaire, avec
  un atelier (un dossier à lui, des programmes qu'on y lance). Le cadre
  confié ne se modifie pas par elle.

Elle avance par **pas** (épisodes ``STEP``, silencieux) ; chaque pas se
conclut par un verdict (``report_step``) : continuer, fini, bloquée,
attendre. « Fini » n'est cru qu'avec une **preuve** — un outil qui a
réellement produit quelque chose pendant ce but. Un but se clôt abouti,
bloqué, abandonné (l'envie s'est usée), en échec (un rappel qui n'a pas pu
être dit) ou annulé.

Un opérateur peut **suspendre** un but vivant (``paused``) : il ne fait plus
de pas, son rappel ne se dit pas, son envie ne s'use pas, jusqu'à ce qu'il
le reprenne. Il peut aussi en changer le cadre (un projet confié), le rouvrir,
le faire avancer tout de suite, lui donner une **priorité** et tenir avec elle
son **plan de travail** (des tâches : à faire, en cours, faites, bloquées).
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "goals"

# sortes et autorités
REMINDER, EXPLORATION, PROJECT = "reminder", "exploration", "project"
# d'où vient une exploration
FROM_EXCHANGE, FROM_REVISION, FROM_SIGNAL, FROM_INTEREST = "exchange", "revision", "signal", "interest"
#: un sujet de conversation qui l'a intéressée (ce dont une amie lui a parlé, ce qu'on lui a fait découvrir) :
#: une rêverie ancrée dans ce qu'on lui a dit, avant ses centres d'intérêt de toujours (ADR 0053)
FROM_TALK = "talk"
#: ce qui fait une rêverie quand elle n'a nulle part où chercher du neuf : un centre d'intérêt, un sujet de
#: conversation
MUSING_ORIGINS = frozenset({FROM_INTEREST, FROM_TALK})
KINDS = (REMINDER, EXPLORATION, PROJECT)
USER, SELF = "user", "self"

# verdicts d'un pas
CONTINUE, DONE, BLOCKED, WAIT = "continue", "done", "blocked", "wait"
VERDICTS = (CONTINUE, DONE, BLOCKED, WAIT)

# statuts : vivants, puis clos
ACTIVE, WAITING, PAUSED = "active", "waiting", "paused"
LIVE_STATUSES = (ACTIVE, WAITING, PAUSED)
ACHIEVED, STUCK, ABANDONED, FAILED, CANCELLED = "done", "blocked", "abandoned", "failed", "cancelled"
#: la raison d'une rêverie écrite (une curiosité sans endroit où chercher du neuf : elle a laissé son esprit
#: vagabonder, et l'a écrit) : close « abouti », mais **rien n'est arrivé** — ni une nouvelle à raconter, ni une
#: matière d'initiative, ni un exploit qui relève l'estime ; son journal la dit une fois, comme une rêverie
MUSED = "rêverie"
#: la raison d'une rêverie qui ne donne rien : elle se dissipe (abandonnée, sans rien ressentir ni rien retenir
#: dans son journal) — rêvasser ne se rate pas, ça ne « bloque » jamais
DISSIPATED = "rêverie dissipée"
#: les raisons de clôture d'une rêverie, quelle qu'en soit l'issue : ce qui les lit n'a pas à recopier une chaîne
MUSINGS = frozenset({MUSED, DISSIPATED})
#: la raison d'une réflexion (repenser à ce qu'on lui a confié, à ce qu'elle croyait) qui n'a rien donné en sa
#: séance : elle en reste là — comme une rêverie qui se dissipe, ce n'est ni un échec ni un renoncement (ni « je
#: bloque », ni frustration, ni mélancolie) ; la pensée d'où elle venait, elle, reste (ADR 0053)
LET_GO = "réflexion sans suite"
#: les fins qui ne se ressentent pas et ne se racontent pas : une rêverie dissipée, une réflexion sans suite
QUIET_ENDS = frozenset({DISSIPATED, LET_GO})
CLOSED_STATUSES = (ACHIEVED, STUCK, ABANDONED, FAILED, CANCELLED)

# priorités (le vocabulaire du panneau du frontend) : elles déplacent la preuve d'un pas
LOW, NORMAL, HIGH, URGENT = "low", "normal", "high", "urgent"
PRIORITIES = (LOW, NORMAL, HIGH, URGENT)

# le plan de travail d'un but : ses tâches
TODO, DOING, TASK_DONE, TASK_BLOCKED = "todo", "doing", "done", "blocked"
TASK_STATUSES = (TODO, DOING, TASK_DONE, TASK_BLOCKED)

# raisons de preuve (arbitrage)
#: avancer d'un pas (épisode STEP, cible ``goal:<id>``)
WORK = "work"
#: dire un rappel à l'heure dite (INITIATIVE vers la personne)
REMIND = "remind"
#: raconter ce qu'elle a mené à bout (INITIATIVE vers qui elle fait confiance)
SHARE = "share"
#: décalage : trop de pas dans l'heure
STEP_CAP = "step_cap"


class GoalOpened(Payload):
    kind: str
    authority: str
    title: Content
    details: Content | None = None
    #: la personne concernée au premier chef (qui a demandé le rappel, confié
    #: le projet, ou de qui parle la pensée d'où il vient)
    owner: str | None = None
    #: où lui parler (l'adresse d'où venait la demande)
    address: str | None = None
    about: tuple[str, ...] = ()
    due: int | None = None
    urgent: bool = False
    #: ses outils, gelés à l'ouverture (un pas ne perd pas ses mains en route)
    bundles: tuple[str, ...] = ()
    max_steps: int = 0
    #: projets : la règle d'agenda (``manual``, ``interval:2h``, ``cron:0 9 * * MON-FRI``)
    schedule: str = ""
    #: projets : ce qui sort de la machine attend un accord
    approval: bool = True
    #: d'où il vient : ``thought:12``, ``interest:<n>``, ``tool``, ``operator``
    source: str = ""
    sensitivity: int = 1
    #: explorations : l'envie de départ (0–1), qui s'use
    desire: float = 0.0
    #: ``low`` | ``normal`` | ``high`` | ``urgent``
    priority: str = NORMAL
    #: explorations : ce qui l'a fait naître — ``exchange`` (ce qu'on lui a confié), ``revision`` (une croyance
    #: revue), ``signal`` (un titre, un mail…), ``interest`` (un de ses centres d'intérêt), ``talk`` (un sujet de
    #: conversation qui l'a intéressée) ; vide : un ancien journal
    origin: str = ""
    #: …et quand (la pensée d'où il vient est née à cet instant ; 0 : inconnu)
    origin_at: int = 0
    #: une rêverie (un de ses centres d'intérêt, sans endroit où chercher du neuf) : elle s'y laisse aller, rien de
    #: neuf n'arrivera — ce n'est pas « se lancer » dans quelque chose (``False`` dans un journal plus ancien)
    musing: bool = False


class StepReported(Payload):
    goal: int
    kind: str = ""
    verdict: str
    summary: Content
    #: ce qu'elle en pense (0–1) : un résultat ordinaire se garde pour soi
    notable: float = 0.5
    wait_s: int = 0
    #: une attente nominative : la personne dont elle attend la réponse (elle
    #: reprend dès que cette personne écrit, ou à l'échéance)
    wait_for: str | None = None
    #: « fini » avec une preuve (un outil qui a produit quelque chose dans ce but)
    proven: bool = False
    #: ce qu'elle a réellement fait pendant ce pas (outils réussis)
    tools: tuple[str, ...] = ()
    #: recopiés du but : le résumé peut citer ces personnes (l'oubli l'atteint)
    owner: str | None = None
    about: tuple[str, ...] = ()


class GoalClosed(Payload):
    goal: int
    status: str
    kind: str = ""
    authority: str = ""
    #: recopié : ce qu'il en reste se dit sans relire l'ouverture
    title: Content
    result: Content | None = None
    notable: float = 0.0
    reason: str = ""
    source: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    sensitivity: int = 1


GOAL_OPENED = event_type("goals.opened", OWNER, GoalOpened, public=True, content=("title", "details"),
                         subjects=("owner", "about"))
STEP_REPORTED = event_type("goals.step_reported", OWNER, StepReported, public=True, content=("summary",),
                           subjects=("owner", "about"))
GOAL_CLOSED = event_type("goals.closed", OWNER, GoalClosed, public=True, content=("title", "result"),
                         subjects=("owner", "about"))
ALL = (GOAL_OPENED, STEP_REPORTED, GOAL_CLOSED)


@dataclass(frozen=True, slots=True)
class GoalView:
    id: int
    kind: str
    authority: str
    status: str
    title_ref: str
    owner: str | None
    about: tuple[str, ...]
    sensitivity: int
    opened_at: int
    steps: int
    max_steps: int
    due: int | None = None
    waiting_until: int = 0
    last_summary_ref: str = ""
    schedule: str = ""
    next_step_at: int | None = None
    priority: str = NORMAL
    #: son plan de travail (des tâches ; zéro : elle avance sans plan écrit)
    tasks_total: int = 0
    tasks_done: int = 0
    tasks_blocked: int = 0
    #: une rêverie en cours : ce n'est pas « ce sur quoi elle est » (rien de neuf ne se raconte)
    musing: bool = False


#: Les buts vivants (actifs ou en attente), du plus ancien au plus récent.
LIVE = FactKey("goals.live", type=tuple, time_varying=True)
#: Le statut d'un but (``""`` : inconnu).
STATUS = FactFamily("goals.status", arg=int, type=str)
