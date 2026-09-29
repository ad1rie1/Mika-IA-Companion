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
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "goals"

# sortes et autorités
REMINDER, EXPLORATION, PROJECT = "reminder", "exploration", "project"
KINDS = (REMINDER, EXPLORATION, PROJECT)
USER, SELF = "user", "self"

# verdicts d'un pas
CONTINUE, DONE, BLOCKED, WAIT = "continue", "done", "blocked", "wait"
VERDICTS = (CONTINUE, DONE, BLOCKED, WAIT)

# statuts : vivants, puis clos
ACTIVE, WAITING = "active", "waiting"
ACHIEVED, STUCK, ABANDONED, FAILED, CANCELLED = "done", "blocked", "abandoned", "failed", "cancelled"
CLOSED_STATUSES = (ACHIEVED, STUCK, ABANDONED, FAILED, CANCELLED)

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
    #: où lui parler (la poignée d'où venait la demande)
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


class StepReported(Payload):
    goal: int
    kind: str = ""
    verdict: str
    summary: Content
    #: ce qu'elle en pense (0–1) : un résultat ordinaire se garde pour soi
    notable: float = 0.5
    wait_s: int = 0
    #: « fini » avec une preuve (un outil qui a produit quelque chose dans ce but)
    proven: bool = False
    #: ce qu'elle a réellement fait pendant ce pas (outils réussis)
    tools: tuple[str, ...] = ()


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
STEP_REPORTED = event_type("goals.step_reported", OWNER, StepReported, public=True, content=("summary",))
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


#: Les buts vivants (actifs ou en attente), du plus ancien au plus récent.
LIVE = FactKey("goals.live", type=tuple, time_varying=True)
#: Le statut d'un but (``""`` : inconnu).
STATUS = FactFamily("goals.status", arg=int, type=str)
