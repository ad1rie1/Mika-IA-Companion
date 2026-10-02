"""Contrat de ``memory`` : ce qu'elle garde de ce qu'elle a vécu.

Quatre sortes de choses retenues, chacune un événement dont le ``seq`` est
l'identifiant (stable, référencé par la provenance des énoncés) :

- un **souvenir** (``remembered``) : un épisode vécu, à la première personne ;
- une **croyance** (``believed``) : un fait sur quelqu'un, sur le monde ou sur
  elle-même, avec sa confiance, son origine (on me l'a dit, je l'ai vu, j'en
  déduis) et qui l'a dit — la même chose redite par la même personne ne la
  rend pas plus sûre ; dite par une autre, si ;
- une **promesse** (``promise_noticed``) qu'elle a faite à quelqu'un ;
- un **événement de la vie de quelqu'un** (``event_noted``) : ce qui va lui
  arriver (« un entretien chez Ubisoft jeudi »), pour qu'elle y pense au bon
  moment — et lui en demande des nouvelles après.

Chacune porte sa sensibilité (``vocab.privacy.Sensitivity``), les messages
d'où elle vient, **qui le lui a confié** (``told_by`` : les auteurs de ces
messages) et **qui l'a entendu** (``heard_by`` : les personnes de la
conversation, un salon en compte plusieurs). Ce qu'une personne a demandé
explicitement de ne répéter à personne est un **secret** (``secret``) : il ne
ressort que devant celle qui l'a confié. Les textes sont des ``Content`` :
effaçables par l'oubli, qui atteint aussi ce qu'une personne a confié.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "memory"

TOLD = "told"  # quelqu'un le lui a dit
OBSERVED = "observed"  # elle l'a vu, vécu
INFERRED = "inferred"  # elle en déduit

HONORED = "honored"
DROPPED = "dropped"
#: qui règle une promesse restée sans nouvelles bien après son échéance
EXPIRED_BY = "échéance"

SOUVENIR = "souvenir"
BELIEF = "belief"
PROMISE = "promise"
EVENT = "event"
CHUNK = "chunk"


class Remembered(Payload):
    text: Content
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    importance: float = 0.5
    emotion: str | None = None
    sources: tuple[int, ...] = ()
    call_id: str = ""
    #: qui le lui a confié (les auteurs des messages sources) ; vide : elle l'a vécu, observé
    told_by: tuple[str, ...] = ()
    #: qui était là quand ça s'est dit (la personne d'un fil privé, les présents d'un salon)
    heard_by: tuple[str, ...] = ()
    #: « dis-le à personne » : ne ressort que devant qui l'a confié
    secret: bool = False


class Believed(Payload):
    text: Content
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    importance: float = 0.5
    confidence: float = 0.7
    origin: str = TOLD
    source: str | None = None
    replaces: int | None = None
    sources: tuple[int, ...] = ()
    call_id: str = ""
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    #: ce qu'elle a raconté d'elle-même (sa vie de tous les jours) : une note
    #: anodine, de peu d'importance, qui s'efface en quelques jours — assez pour
    #: ne pas se contredire d'un jour à l'autre
    about_self: bool = False


class Reinforced(Payload):
    """Ce qui était déjà retenu revient : il s'estompe moins vite. Une croyance
    corroborée (redite par quelqu'un qui ne l'avait pas encore dite) gagne en
    confiance. Ce qui revient peut être plus sensible qu'avant (la sensibilité
    garde la plus haute), concerner d'autres personnes, avoir d'autres
    confidents ou devenir un secret (les ensembles s'unissent) ; ``replaces``
    remplace une croyance contredite par celle qu'on renforce."""

    item: int
    corroborated: bool = False
    source: str | None = None
    sources: tuple[int, ...] = ()
    sensitivity: int | None = None
    about: tuple[str, ...] = ()
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    replaces: int | None = None


class PromiseNoticed(Payload):
    text: Content
    to: str
    due: int | None = None
    sensitivity: int = 1
    sources: tuple[int, ...] = ()
    call_id: str = ""
    #: l'échéance n'a pas été dite : c'est l'horizon au-delà duquel une
    #: promesse vague s'oublie (une pensée d'abord, puis l'abandon)
    implicit_due: bool = False


class PromiseResolved(Payload):
    promise: int
    status: str  # HONORED | DROPPED
    by: str = "consolidation"


class EventNoted(Payload):
    """Ce qui va arriver dans la vie de quelqu'un (« jeudi, son entretien chez
    Ubisoft ») : ``when`` l'instant (le jour seulement si ``all_day``)."""

    text: Content
    when: int
    about: tuple[str, ...] = ()
    all_day: bool = True
    sensitivity: int = 2
    sources: tuple[int, ...] = ()
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    #: un événement noté plus tôt dont la date a changé
    replaces: int | None = None
    call_id: str = ""


class Consolidated(Payload):
    """Le point de contrôle : tout ce qui précède ``upto`` a été relu."""

    upto: int
    produced: int = 0
    failed: bool = False
    call_id: str = ""
    model: str = ""


class NightSorted(Payload):
    """La nuit, les souvenirs du jour presque identiques à un autre s'y fondent
    (``(gardé, fondu)``) : le gardé prend la plus haute importance et la plus
    haute sensibilité des deux, et les personnes de l'un et de l'autre."""

    night: str
    merges: tuple[tuple[int, int], ...] = ()


#: un élément retenu se soumet à l'oubli de ceux qu'il concerne et de ceux qui l'ont confié
_SUBJECTS = ("about", "told_by")

REMEMBERED = event_type("memory.remembered", OWNER, Remembered, public=True, content=("text",), subjects=_SUBJECTS)
BELIEVED = event_type("memory.believed", OWNER, Believed, public=True, content=("text",), subjects=_SUBJECTS)
REINFORCED = event_type("memory.reinforced", OWNER, Reinforced, public=True)
PROMISE_NOTICED = event_type("memory.promise_noticed", OWNER, PromiseNoticed, public=True, content=("text",),
                             subjects=("to",))
PROMISE_RESOLVED = event_type("memory.promise_resolved", OWNER, PromiseResolved, public=True)
EVENT_NOTED = event_type("memory.event_noted", OWNER, EventNoted, public=True, content=("text",), subjects=_SUBJECTS)
CONSOLIDATED = event_type("memory.consolidated", OWNER, Consolidated, public=True)
NIGHT_SORTED = event_type("memory.night_sorted", OWNER, NightSorted, public=True)
ALL = (REMEMBERED, BELIEVED, REINFORCED, PROMISE_NOTICED, PROMISE_RESOLVED, EVENT_NOTED, CONSOLIDATED, NIGHT_SORTED)


@dataclass(frozen=True, slots=True)
class PendingPromise:
    id: int
    to: str
    due: int | None
    at: int
    implicit_due: bool = False


@dataclass(frozen=True, slots=True)
class LifeEvent:
    """Un moment de la vie de quelqu'un qu'elle a noté. ``text_ref`` : son
    texte (un contenu, effaçable) ; ``followed_at`` : la dernière fois qu'elle
    l'avait sous les yeux en parlant à la personne, une fois le moment passé
    (0 : jamais — elle ne lui en a pas encore reparlé)."""

    id: int
    about: tuple[str, ...]
    when: int
    all_day: bool
    sensitivity: int
    told_by: tuple[str, ...]
    text_ref: str
    secret: bool = False
    followed_at: int = 0


#: Le dernier message relu par la consolidation.
CHECKPOINT = FactKey("memory.checkpoint", type=int)
#: Les promesses en cours envers une personne.
PROMISES_TO = FactFamily("memory.promises_to", arg=str, type=tuple)
#: Les moments de la vie d'une personne qu'elle a notés — à venir, et passés
#: depuis peu (quelques jours) —, triés par date (``LifeEvent``). Forme close :
#: c'est au lecteur de comparer ``when`` à son instant (« c'était hier : et
#: alors, cet entretien ? »). Ce qui la concerne seulement : un moment qu'un
#: tiers a raconté porte ce tiers dans ``told_by``, à respecter avant d'en parler.
LIFE_EVENTS = FactFamily("memory.life_events", arg=str, type=tuple)

ITEMS_TABLE = "memory_items"
CHUNKS_TABLE = "memory_chunks"
#: À qui elle a répété quoi (``item``, ``handle``, ``at``) : d'après la
#: provenance de ce qu'elle a dit. Ce qu'elle a raconté à Bob, Bob le sait.
TOLD_TABLE = "memory_told"
