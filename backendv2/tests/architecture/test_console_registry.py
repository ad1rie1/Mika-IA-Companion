"""La console lit le registre : il refuse au démarrage ce qu'elle ne saurait
pas montrer ou exécuter proprement — un type d'objet déclaré deux fois, un
onglet vers un type inconnu, une action qui émettrait l'événement d'un autre,
un badge sans place. Chaque règle a son contre-exemple accepté."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.kernel.inspect import Head, Param
from mika.kernel.operate import Done
from mika.kernel.registry import CompositionError, Registry


@dataclass(frozen=True, slots=True)
class S:
    n: int = 0


class P(Payload):
    x: int = 0


class Args(BaseModel):
    note: str = ""


def fac(name: str) -> Faculty:
    return Faculty(name, state=S, init=lambda p: S())


def problems(*faculties: Faculty) -> list[str]:
    with pytest.raises(CompositionError) as info:
        Registry(list(faculties))
    return info.value.problems


def people() -> Faculty:
    f = fac("people")

    @f.subject("person", label="Personne", plural="Personnes")
    def _head(s, frame, ctx, key):
        return Head(key, key)

    return f


def test_a_well_formed_console_composition_is_accepted():
    a, b = people(), fac("notes")
    NOTED = b.event("noted", P)

    @b.inspect("carnet", title="Carnet", subject="person", params=[Param("q", "recherche")])
    def _tab(s, frame, ctx):
        return []

    @b.inspect("liste", title="Liste", section="vie", badge=lambda s, frame: 1)
    def _list(s, frame, ctx):
        return []

    @b.action("noter", title="Noter", args=Args, emits=[NOTED], subject="person")
    def _act(s, frame, args, ctx):
        return Done(drafts=(NOTED.draft(x=1),))

    @b.series("n", label="Compte")
    def _n(s, frame):
        return float(s.n)

    reg = Registry([a, b])
    assert reg.subjects["person"].owner == "people"
    assert reg.actions["notes.noter"].emits == frozenset({"notes.noted"})
    assert "notes.n" in reg.series
    tab = next(v for v in reg.inspectors if v.name == "carnet")
    assert tab.params == (("q", "recherche"),) and tab.typed[0].kind == "search"


def test_a_subject_kind_has_one_owner():
    other = fac("other")

    @other.subject("person", label="Personne", plural="Personnes")
    def _head(s, frame, ctx, key):
        return None

    assert any("type d'objet déclaré deux fois : person" in p for p in problems(people(), other))


def test_a_tab_or_an_action_needs_a_known_subject_kind():
    f = fac("notes")
    NOTED = f.event("noted", P)

    @f.inspect("carnet", subject="personne")
    def _tab(s, frame, ctx):
        return []

    @f.action("noter", title="Noter", args=Args, emits=[NOTED], subject="personne")
    def _act(s, frame, args, ctx):
        return Done()

    found = problems(f)
    assert any("vue notes/carnet : type d'objet inconnu personne" in p for p in found)
    assert any("action notes.noter : type d'objet inconnu personne" in p for p in found)


def test_an_action_only_emits_its_own_events():
    a = people()
    TOUCHED = a.event("touched", P)
    thief = fac("thief")

    @thief.action("toucher", title="Toucher", args=Args, emits=[TOUCHED])
    def _act(s, frame, args, ctx):
        return Done()

    assert any("émet people.touched, qui appartient à people" in p for p in problems(a, thief))


def test_two_tabs_of_the_same_name_on_one_subject_are_refused():
    a, b, c = people(), fac("b"), fac("c")
    for f in (b, c):
        f.inspect("synthese", subject="person")(lambda s, frame, ctx: [])
    assert any("onglet déclaré deux fois sur la fiche person : synthese" in p for p in problems(a, b, c))


def test_a_badge_needs_a_place():
    f = fac("notes")
    f.inspect("orpheline", badge=lambda s, frame: 1)(lambda s, frame, ctx: [])
    assert any("un badge sans place" in p for p in problems(f))
