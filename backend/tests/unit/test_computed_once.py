"""Ce que le noyau ne calcule qu'une fois, parce que chaque démarrage, chaque épisode ou chaque fait le redemandait à
l'identique (K3-01, la voie rapide) : par classe ou par type, le schéma JSON des arguments d'un outil, l'adaptateur
d'une tranche, la façon dont un modèle de paramètres se déplie, ce que pilote chaque curseur ; par vue des faits, les
paramètres d'un fournisseur et le fuseau.

Chaque mémoire rend ce que le calcul frais rendrait, pour chaque entrée ; une entrée qui change (une autre classe, un
autre type, un autre tempérament, une autre dérivation, une autre racine) change le résultat ; et ce qu'elle rend,
l'appelant peut le modifier sans toucher au suivant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from mika.app.composition import faculties
from mika.faculties.memory.extraction import Extraction
from mika.faculties.memory.reread import Relecture
from mika.faculties.self.interests import Reflet
from mika.faculties.social.profile import XProfile
from mika.kernel import forms
from mika.kernel.facts import FactContext, FactKey, FactSpec, FactView
from mika.kernel.faculty import Faculty, schema_of
from mika.kernel.forms import Knob
from mika.kernel.registry import Registry
from mika.kernel.state import FrozenDict, Root
from mika.runtime import params
from mika.vocab.temperament import Temperament

# ── le schéma des arguments d'un outil ─────────────────────────────────────


def test_a_tool_schema_is_the_one_pydantic_computes_for_its_class():
    models = {t.args for f in faculties() for t in f.tools} | {Extraction, Relecture, Reflet, XProfile}
    assert len(models) > 20
    for model in models:
        assert schema_of(model) == model.model_json_schema(), model.__qualname__


def test_two_classes_never_share_a_schema_even_under_the_same_name():
    class Args(BaseModel):
        city: str

    first = schema_of(Args)

    class Args(BaseModel):  # type: ignore[no-redef]  # le même nom, un champ de plus
        city: str
        days: int = 1

    second = schema_of(Args)
    assert set(first["properties"]) == {"city"}
    assert set(second["properties"]) == {"city", "days"}


def test_a_schema_changed_by_its_caller_leaves_the_next_one_intact():
    class Args(BaseModel):
        city: str

    got = schema_of(Args)
    got["properties"]["city"]["type"] = "integer"
    got["required"].append("days")
    assert schema_of(Args) == Args.model_json_schema()


# ── l'adaptateur d'une tranche ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Pebble:
    n: int = 1


@dataclass(frozen=True, slots=True)
class Leaf:
    name: str = "chêne"
    tags: tuple[str, ...] = ("vert",)


PEBBLE = Faculty("pebble", state=Pebble, init=lambda p: Pebble())
LEAF = Faculty("leaf", state=Leaf, init=lambda p: Leaf())


def test_each_slice_is_read_back_by_the_adapter_of_its_own_type():
    first, second = Registry([PEBBLE, LEAF]), Registry([PEBBLE, LEAF])
    # un par type, pas un par registre : chaque démarrage compose un registre neuf
    assert first.slice_adapter("pebble") is second.slice_adapter("pebble")
    assert first.slice_adapter("pebble") is not first.slice_adapter("leaf")
    root = first.initial_root()
    for owner in ("pebble", "leaf"):
        adapter = second.slice_adapter(owner)
        assert adapter.validate_python(adapter.dump_python(root.slices[owner], mode="json")) == root.slices[owner]


# ── le dépliage d'un modèle de paramètres ──────────────────────────────────


class Inner(BaseModel):
    model_config = ConfigDict(frozen=True)
    x: int = 1


class Folded(BaseModel):
    inner: Inner = Inner()


class Kept(BaseModel):
    inner: Annotated[Inner, Knob(widget="yaml")] = Inner()


class Maybe(BaseModel):
    inner: Inner | None = Inner()


def test_flatten_unfolds_what_each_class_declares():
    """Trois classes au même champ ``inner`` : seule celle qui le déclare dépliable le déplie."""
    assert forms.flatten(Folded()) == {"inner.x": 1}
    assert forms.flatten(Kept()) == {"inner": {"x": 1}}
    assert forms.flatten(Maybe()) == {"inner": {"x": 1}}
    assert forms.flatten(Maybe(inner=None)) == {"inner": None}


def _flatten_fresh(value: BaseModel) -> dict[str, Any]:
    """``flatten`` tel qu'il était : chaque champ relu à chaque appel."""
    out: dict[str, Any] = {}
    for name, info in type(value).model_fields.items():
        current = getattr(value, name)
        annotation, extra, nullable = forms._unwrap(info.annotation)
        knob = forms._knob_of(forms._expand((*info.metadata, *extra)))
        if isinstance(current, BaseModel) and forms._groups(annotation, knob, nullable):
            out.update({f"{name}.{path}": sub for path, sub in _flatten_fresh(current).items()})
        else:
            out[name] = forms._plain(current)
    return out


def test_flatten_gives_what_reading_each_field_again_gives_on_her_parameters():
    seen = 0
    for fac in faculties():
        if fac.params is None:
            continue
        for value in (fac.default_params(), fac.derive(Temperament(), None) if fac.derive else None):
            if value is not None:
                assert forms.flatten(value) == _flatten_fresh(value), fac.name
                seen += 1
    assert seen > 30


# ── ce que pilote chaque curseur ───────────────────────────────────────────


class Gains(BaseModel):
    model_config = ConfigDict(frozen=True)
    gain: float = 0.5


def _both(t: Temperament, overrides: Any = None) -> Gains:
    return Gains(gain=round(0.2 + 0.6 * t.reactivity * t.resilience, 3))


def _alone(t: Temperament, overrides: Any = None) -> Gains:
    return Gains(gain=round(0.1 + 0.8 * t.reactivity, 3))


BOTH = Faculty("both", state=Pebble, init=lambda p: Pebble(), params=Gains, derive=_both)
ALONE = Faculty("alone", state=Pebble, init=lambda p: Pebble(), params=Gains, derive=_alone)


def _influence_fresh(fac: Faculty[Any, Any], t: Temperament) -> dict[str, tuple[tuple[str, Any, Any], ...]]:
    """``influence`` tel qu'il était : chaque curseur poussé à ses deux bouts à chaque appel."""
    out = {}
    assert fac.derive is not None
    for slider in params.SLIDERS:
        lo = forms.flatten(fac.derive(t.model_copy(update={slider: 0.0}), None))
        hi = forms.flatten(fac.derive(t.model_copy(update={slider: 1.0}), None))
        moved = tuple((path, lo[path], hi[path]) for path in lo if lo[path] != hi.get(path))
        if moved:
            out[slider] = moved
    return out


def test_what_a_slider_drives_is_measured_again_when_another_slider_moves():
    calm, quick = Temperament(resilience=0.5), Temperament(resilience=1.0)
    assert params.influence(BOTH, calm)["reactivity"] == (("gain", 0.2, 0.5),)
    assert params.influence(BOTH, quick)["reactivity"] == (("gain", 0.2, 0.8),)
    assert params.influence(BOTH, calm) == _influence_fresh(BOTH, calm)


def test_what_a_slider_drives_depends_on_the_faculty_that_derives():
    t = Temperament()
    assert params.influence(BOTH, t) != params.influence(ALONE, t)
    assert params.influence(ALONE, t) == {"reactivity": (("gain", 0.1, 0.9),)}


def test_a_measure_changed_by_its_caller_leaves_the_next_one_intact():
    t = Temperament()
    got = params.influence(BOTH, t)
    got.clear()
    assert params.influence(BOTH, t) == _influence_fresh(BOTH, t)


def test_on_her_faculties_what_each_slider_drives_is_what_pushing_it_gives():
    for t in (Temperament(), Temperament(reactivity=0.9, optimism=0.2, notes={"optimism": "le verre à moitié plein"})):
        for fac in faculties():
            if fac.derive is not None:
                assert params.influence(fac, t) == _influence_fresh(fac, t), fac.name


# ── les paramètres d'un fournisseur de faits, dans une vue ─────────────────

SOWN = FactKey("garden.sown")
GROWN = FactKey("garden.grown")


def _sown(state: Any, ctx: FactContext) -> tuple[Any, str]:
    return ctx.params, ctx.tz.key


def _grown(state: Any, ctx: FactContext) -> tuple[Any, Any, str]:
    return ctx.params, ctx.facts.get(SOWN), ctx.tz.key


class Garden:
    """Un registre jouet : les paramètres du jardin sont ceux que porte la racine, et chaque lecture est comptée."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.specs = {SOWN.name: FactSpec("garden", SOWN, _sown, frozenset()),
                      GROWN.name: FactSpec("garden", GROWN, _grown, frozenset({SOWN.name}))}

    def fact_spec(self, name: str) -> FactSpec:
        return self.specs[name]

    def params_of(self, owner: str, root: Root) -> Any:
        self.asked.append(owner)
        return root.slices[owner]

    def tz_of(self, root: Root) -> ZoneInfo:
        self.asked.append("fuseau")
        return ZoneInfo(root.slices["tz"])


def _root(params: str, tz: str) -> Root:
    return Root(slices=FrozenDict({"garden": params, "tz": tz}))


def test_a_view_reads_the_parameters_of_a_provider_once_and_each_root_its_own():
    env = Garden()
    spring = FactView(_root("tomates", "Europe/Paris"), 0, env)
    assert spring.get(GROWN) == ("tomates", ("tomates", "Europe/Paris"), "Europe/Paris")
    assert env.asked == ["garden", "fuseau"]  # deux faits calculés, une lecture de chaque
    autumn = FactView(_root("courges", "America/Montreal"), 0, env)
    assert autumn.get(GROWN) == ("courges", ("courges", "America/Montreal"), "America/Montreal")
    assert spring.restricted(None).get(SOWN) == ("tomates", "Europe/Paris")
