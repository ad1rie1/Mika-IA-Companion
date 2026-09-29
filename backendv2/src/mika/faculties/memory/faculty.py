"""La faculté ``memory`` : sa tranche, ses paramètres, ses réducteurs, ses faits.

La tranche ne garde que des résumés (point de contrôle, messages pas encore
relus, promesses en cours) ; les éléments retenus vivent dans la projection
T0 ``memory_items`` et leurs vecteurs dans l'index (un cache).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as attention_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict

PENDING_CAP = 500


class MemoryParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # consolidation : une fenêtre mûre (assez de messages) ou calme (plus rien depuis un moment)
    min_messages: int = 6
    quiet_us: int = 5 * MINUTE
    max_window: int = 80
    retry_us: int = 10 * MINUTE
    max_attempts: int = 3
    dedup_similarity: float = 0.92
    # rappel
    recall_k: int = 40
    recall_floor: float = 0.25
    max_souvenirs: int = 5
    max_beliefs: int = 8
    max_chunks: int = 3
    # oubli : l'importance s'estompe à la lecture, jamais par balayage
    dormant: float = 0.03
    base_half_life_days: float = 3.0
    importance_half_life_days: float = 27.0
    belief_half_life_days: float = 180.0
    min_belief_confidence: float = 0.3
    person_boost: float = 1.25
    repetition_us: int = 30 * MINUTE
    repetition_penalty: float = 0.6
    # la nuit
    night_after_sleep_us: int = 3 * HOUR
    night_merge_similarity: float = 0.9
    night_max_merges: int = 20


@dataclass(frozen=True, slots=True)
class Reflection:
    """Une pensée restée forte, digérée cette nuit : un souvenir à écrire."""

    thought: int
    text_ref: str
    about: tuple[str, ...]
    sensitivity: int
    emotion: str


@dataclass(frozen=True, slots=True)
class MemoryState:
    checkpoint: int = 0
    #: messages de personnes pas encore relus (``seq``), les plus récents
    pending: tuple[int, ...] = field(default_factory=tuple)
    last_message_at: int = 0
    items: int = 0
    chunks: int = 0
    promises: FrozenDict[int, c.PendingPromise] = field(default_factory=FrozenDict)
    reflections: tuple[Reflection, ...] = ()
    sorted_night: str = ""
    #: la dernière relecture journalisée (``seq``, instant), et les fenêtres
    #: abandonnées après trop d'échecs (combien, la dernière) : pour l'inspecteur
    consolidated_seq: int = 0
    consolidated_at: int = 0
    given_up: int = 0
    given_up_seq: int = 0


MEMORY = Faculty("memory", state=MemoryState, init=lambda p: MemoryState(), params=MemoryParams, state_version=2)
MEMORY.declare(*c.ALL)


def params(p: MemoryParams | None) -> MemoryParams:
    return p if p is not None else MemoryParams()


@MEMORY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, pending=(*s.pending, e.seq)[-PENDING_CAP:], last_message_at=e.at)


@MEMORY.reducer(rt.UTTERANCE)
def _uttered(s: MemoryState, e, cx) -> MemoryState:
    if not e.data.visible:
        return s
    return replace(s, last_message_at=e.at, chunks=s.chunks + (1 if e.data.target and e.data.reply_to else 0))


@MEMORY.reducer(c.CONSOLIDATED)
def _consolidated(s: MemoryState, e, cx) -> MemoryState:
    upto = max(s.checkpoint, e.data.upto)
    s = replace(s, checkpoint=upto, pending=tuple(q for q in s.pending if q > upto), consolidated_seq=e.seq,
                consolidated_at=e.at)
    return replace(s, given_up=s.given_up + 1, given_up_seq=e.seq) if e.data.failed else s


@MEMORY.reducer(c.REMEMBERED, c.BELIEVED)
def _retained(s: MemoryState, e, cx) -> MemoryState:
    reflections = tuple(r for r in s.reflections if e.data.call_id != f"réflexion:{r.thought}")
    return replace(s, items=s.items + 1, reflections=reflections)


@MEMORY.reducer(attention_c.DIGESTED)
def _digested(s: MemoryState, e, cx) -> MemoryState:
    """Ce qui est resté fort toute la journée, repensé la nuit, devient un souvenir."""
    new = tuple(Reflection(i.thought, i.text_ref, tuple(i.about), i.sensitivity, i.emotion)
                for i in e.data.items if i.reflective and i.text_ref)
    return replace(s, reflections=(*s.reflections, *new)[-20:]) if new else s


@MEMORY.reducer(c.NIGHT_SORTED)
def _sorted(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, sorted_night=e.data.night)


@MEMORY.reducer(c.PROMISE_NOTICED)
def _promised(s: MemoryState, e, cx) -> MemoryState:
    promise = c.PendingPromise(e.seq, e.data.to, e.data.due, e.at)
    return replace(s, items=s.items + 1, promises=s.promises.set(e.seq, promise))


@MEMORY.reducer(c.PROMISE_RESOLVED)
def _resolved(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, promises=s.promises.delete(e.data.promise))


@MEMORY.fact(c.CHECKPOINT)
def _checkpoint(s: MemoryState, cx) -> int:
    return s.checkpoint


@MEMORY.fact(c.PROMISES_TO)
def _promises_to(s: MemoryState, cx, person: str) -> tuple[c.PendingPromise, ...]:
    return tuple(p for p in s.promises.values() if p.to == person)
