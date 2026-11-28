"""Facultés jouets pour éprouver le noyau (jamais utilisées en production)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic import BaseModel, ConfigDict

from mika.kernel.events import Content, Payload
from mika.kernel.facts import FactFamily, FactKey
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict

# ── counter : une tranche simple, un contenu, un fait ─────────────────────


class CounterParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    step: int = 1


@dataclass(frozen=True, slots=True)
class CounterState:
    n: int = 0
    notes: int = 0


class Bumped(Payload):
    by: int = 1
    note: Content | None = None
    who: str = ""


COUNTER = Faculty("counter", state=CounterState, init=lambda p: CounterState(), params=CounterParams)
BUMPED = COUNTER.event("bumped", Bumped, public=True, content=("note",), subjects=("who",))
VALUE = FactKey("counter.value", type=int)


@COUNTER.reducer(BUMPED)
def _bump(s: CounterState, e, cx) -> CounterState:
    assert e.data.note is None or e.data.note.text is None, "un réducteur ne voit jamais de texte"
    return replace(s, n=s.n + e.data.by * cx.params.step, notes=s.notes + (e.data.note is not None))


@COUNTER.fact(VALUE)
def _value(s: CounterState, cx) -> int:
    return s.n


# ── echo : lit le fait d'un autre propriétaire dans son réducteur ──────────


@dataclass(frozen=True, slots=True)
class EchoState:
    seen: tuple[int, ...] = ()


ECHO = Faculty("echo", state=EchoState, init=lambda p: EchoState())


@ECHO.reducer(BUMPED, reads=[VALUE])
def _echo(s: EchoState, e, cx) -> EchoState:
    # Double tampon : on lit la valeur d'AVANT l'événement.
    return replace(s, seen=s.seen + (cx.facts.get(VALUE),))


# ── people : une famille de faits paramétrée ──────────────────────────────


@dataclass(frozen=True, slots=True)
class PeopleState:
    last_inbound: FrozenDict[str, int] = FrozenDict()


class Said(Payload):
    who: str


PEOPLE = Faculty("people", state=PeopleState, init=lambda p: PeopleState())
SAID = PEOPLE.event("said", Said, public=True)
LAST_INBOUND = FactFamily("people.last_inbound", arg=str, type=int)


@PEOPLE.reducer(SAID)
def _said(s: PeopleState, e, cx) -> PeopleState:
    return replace(s, last_inbound=s.last_inbound.set(e.data.who, e.at))


@PEOPLE.fact(LAST_INBOUND)
def _last_inbound(s: PeopleState, cx, who: str) -> int:
    return s.last_inbound.get(who, 0)
