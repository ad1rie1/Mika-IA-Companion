"""Contrat de ``memory`` : ce qu'elle garde de ce qu'elle a vécu.

Trois sortes de choses retenues, chacune un événement dont le ``seq`` est
l'identifiant (stable, référencé par la provenance des énoncés) :

- un **souvenir** (``remembered``) : un épisode vécu, à la première personne ;
- une **croyance** (``believed``) : un fait sur quelqu'un ou sur le monde,
  avec sa confiance, son origine (on me l'a dit, je l'ai vu, j'en déduis) et
  qui l'a dit — la même chose redite par la même personne ne la rend pas
  plus sûre ; dite par une autre, si ;
- une **promesse** (``promise_noticed``) qu'elle a faite à quelqu'un.

Chacune porte sa sensibilité (``vocab.privacy.Sensitivity``) et les messages
d'où elle vient. Les textes sont des ``Content`` : effaçables par l'oubli.
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

SOUVENIR = "souvenir"
BELIEF = "belief"
PROMISE = "promise"
CHUNK = "chunk"


class Remembered(Payload):
    text: Content
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    importance: float = 0.5
    emotion: str | None = None
    sources: tuple[int, ...] = ()
    call_id: str = ""


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


class Reinforced(Payload):
    """Ce qui était déjà retenu revient : il s'estompe moins vite. Une croyance
    corroborée (redite par quelqu'un d'autre) gagne en confiance."""

    item: int
    corroborated: bool = False
    source: str | None = None
    sources: tuple[int, ...] = ()


class PromiseNoticed(Payload):
    text: Content
    to: str
    due: int | None = None
    sensitivity: int = 1
    sources: tuple[int, ...] = ()
    call_id: str = ""


class PromiseResolved(Payload):
    promise: int
    status: str  # HONORED | DROPPED
    by: str = "consolidation"


class Consolidated(Payload):
    """Le point de contrôle : tout ce qui précède ``upto`` a été relu."""

    upto: int
    produced: int = 0
    failed: bool = False
    call_id: str = ""
    model: str = ""


REMEMBERED = event_type("memory.remembered", OWNER, Remembered, public=True, content=("text",), subjects=("about",))
BELIEVED = event_type("memory.believed", OWNER, Believed, public=True, content=("text",), subjects=("about",))
REINFORCED = event_type("memory.reinforced", OWNER, Reinforced, public=True)
PROMISE_NOTICED = event_type("memory.promise_noticed", OWNER, PromiseNoticed, public=True, content=("text",),
                             subjects=("to",))
PROMISE_RESOLVED = event_type("memory.promise_resolved", OWNER, PromiseResolved, public=True)
CONSOLIDATED = event_type("memory.consolidated", OWNER, Consolidated, public=True)
ALL = (REMEMBERED, BELIEVED, REINFORCED, PROMISE_NOTICED, PROMISE_RESOLVED, CONSOLIDATED)


@dataclass(frozen=True, slots=True)
class PendingPromise:
    id: int
    to: str
    due: int | None
    at: int


#: Le dernier message relu par la consolidation.
CHECKPOINT = FactKey("memory.checkpoint", type=int)
#: Les promesses en cours envers une personne.
PROMISES_TO = FactFamily("memory.promises_to", arg=str, type=tuple)

ITEMS_TABLE = "memory_items"
CHUNKS_TABLE = "memory_chunks"
#: À qui elle a répété quoi (``item``, ``handle``, ``at``) : d'après la
#: provenance de ce qu'elle a dit. Ce qu'elle a raconté à Bob, Bob le sait.
TOLD_TABLE = "memory_told"
