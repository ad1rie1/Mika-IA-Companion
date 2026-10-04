"""Les paramètres des facultés : défaut ← tempérament ← réglages ← surcharges.

Chaque valeur dit d'où elle vient ; une surcharge refusée est écartée sans
emporter les autres ; les propriétaires (un réglage) survivent à toute
reconfiguration ; chaque curseur dit ce qu'il pilote.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.app import composition
from mika.faculties.body import BODY
from mika.faculties.needs import NEEDS
from mika.kernel import forms
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.runtime import params
from mika.runtime.params import DEFAULT, OVERRIDE, SETTING, TEMPERAMENT, Parameters
from mika.sim.clock import run_virtual
from mika.vocab.temperament import Temperament
from tests.fixtures.harness import build


class Inner(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tau_h: Annotated[float, Knob(lo=0.5, hi=48)] = 6.0


class ToyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    gain: Annotated[float, Knob(lo=0.0, hi=1.0)] = 0.5
    steps: Annotated[int, Knob(lo=1, hi=10)] = Field(default=3, ge=1)
    owners: tuple[str, ...] = ()
    inner: Inner = Inner()


def derive(t: Temperament, overrides: Any = None) -> ToyParams:
    return ToyParams(gain=round(0.2 + 0.6 * t.reactivity, 3))


@dataclass(frozen=True, slots=True)
class Toy:
    n: int = 0


TOY = Faculty("toy", state=Toy, init=lambda p: Toy(), params=ToyParams, derive=derive)


def test_each_value_says_where_it_comes_from():
    p = params.planned(TOY, Temperament(reactivity=1.0), {"inner.tau_h": 12.0}, {"owners": ("ext_1",)})
    assert p is not None
    assert p.value.gain == 0.8 and p.value.inner.tau_h == 12.0 and p.value.owners == ("ext_1",)
    assert p.sources["gain"] == TEMPERAMENT
    assert p.sources["inner.tau_h"] == OVERRIDE
    assert p.sources["owners"] == SETTING
    assert p.sources["steps"] == DEFAULT
    assert p.natural.inner.tau_h == 6.0  # la valeur « naturelle » ignore les surcharges


def test_a_refused_override_is_set_aside_alone():
    p = params.planned(TOY, Temperament(), {"steps": 0, "inner.tau_h": 3.0, "nope": 1})
    assert p is not None
    assert set(p.refused) == {"steps", "nope"}
    assert p.value.steps == 3 and p.value.inner.tau_h == 3.0  # la bonne surcharge reste
    assert p.sources["steps"] == DEFAULT


def test_overriding_a_derived_field_no_longer_raises():
    """``body.derive`` passait la surcharge en argument nommé à côté du champ
    dérivé : « got multiple values for shift_minutes »."""
    p = params.planned(BODY, Temperament(chronotype=1.0), {"shift_minutes": -30})
    assert p is not None and not p.refused
    assert p.value.shift_minutes == -30 and p.sources["shift_minutes"] == OVERRIDE
    assert p.natural.shift_minutes == 120


def test_each_slider_says_what_it_drives():
    moved = params.influence(NEEDS, Temperament())
    assert "tau_social_h" in {path for path, _, _ in moved["sociability"]}
    assert "chronotype" not in moved
    body = params.influence(BODY, Temperament())
    assert [(path, lo, hi) for path, lo, hi in body["chronotype"]] == [("shift_minutes", -120, 120)]
    everywhere = params.influences([BODY, NEEDS, TOY], Temperament())
    assert ("toy", "gain", 0.2, 0.8) in everywhere["reactivity"]
    assert set(everywhere) == set(params.SLIDERS)


def _kernel(tmp_path):
    kernel, clock, _ = build(tmp_path, [TOY])
    return kernel, clock


def test_console_changes_are_bounded_reverted_and_kept_apart_from_settings(tmp_path):
    kernel, clock = _kernel(tmp_path)
    stored: dict[str, dict[str, Any]] = {}
    owners = {"toy": {"owners": ("ext_7",)}}
    temperament = Temperament(reactivity=0.5)

    async def save(value: dict[str, dict[str, Any]]) -> None:
        stored.clear()
        stored.update(value)

    async def apply() -> list[str]:
        planned = params.plan([TOY], temperament, stored, owners)
        for owner, value in params.to_journal(kernel, planned, stored, owners):
            await kernel.set_params(owner, value)
        return []

    ps = Parameters(kernel, temperament=lambda: temperament, overrides=lambda: stored, save_overrides=save,
                    inputs=lambda: owners, apply=apply)
    rendered = [f.path for f in ps.fields("toy") if f.kind not in ("group",)]

    async def main():
        await kernel.start()
        await apply()
        out = {}
        form = {forms.RENDERED: rendered, "gain": ["0,9"], "steps": ["3"], "inner.tau_h": ["6 h"]}
        out["set"] = await ps.change("toy", form)
        out["after_set"] = dict(stored)
        out["journaled"] = ps.journaled("toy")
        # hors bornes de la console : refusé, rien ne change
        out["bad"] = await ps.change("toy", {**form, "gain": ["2"]})
        out["after_bad"] = dict(stored)
        # revenir à la valeur naturelle retire la surcharge
        out["back"] = await ps.change("toy", {**form, "gain": ["0,5"]})
        out["after_back"] = dict(stored)
        out["final"] = ps.journaled("toy")
        await kernel.stop()
        return out

    out = run_virtual(clock, main)
    assert out["set"] == (True, {})
    assert out["after_set"] == {"toy": {"gain": 0.9}}  # seul ce qui diffère de la valeur naturelle
    assert out["journaled"].gain == 0.9 and out["journaled"].owners == ("ext_7",)
    assert out["bad"][0] is False and "gain" in out["bad"][1]
    assert out["after_bad"] == {"toy": {"gain": 0.9}}
    assert out["back"] == (True, {}) and out["after_back"] == {}
    assert out["final"].gain == 0.5 and out["final"].owners == ("ext_7",)  # le réglage survit


def test_configure_keeps_owners_through_a_reconfiguration(tmp_path):
    kernel, clock, _ = build(tmp_path, composition.faculties())
    doc = composition.load(composition.PERSONA)

    async def main():
        await kernel.start()
        await composition.configure(kernel, doc, {}, {"identity": {"owners": ("ext_42",)}})
        first = kernel.mind.root.slices["kernel"].params["identity"].data
        await composition.configure(kernel, doc, {"body": {"shift_minutes": 15}},
                                    {"identity": {"owners": ("ext_42",)}})
        second = kernel.mind.root.slices["kernel"].params["identity"].data
        body = kernel.mind.root.slices["kernel"].params["body"].data
        await kernel.stop()
        return first, second, body

    first, second, body = run_virtual(clock, main)
    assert "ext_42" in first and first == second
    assert '"shift_minutes":15' in body.replace(" ", "")


def test_untouched_faculties_get_no_event(tmp_path):
    """Première mise en route : une faculté sans ``derive``, ni surcharge ni réglage,
    garde son défaut sans un événement de plus."""
    kernel, clock, _ = build(tmp_path, composition.faculties())
    doc = composition.load(composition.PERSONA)

    async def main():
        await kernel.start()
        await composition.configure(kernel, doc)
        stored = set(kernel.mind.root.slices["kernel"].params)
        await kernel.stop()
        return stored

    stored = run_virtual(clock, main)
    derived = {f.name for f in composition.faculties() if f.derive is not None}
    assert derived <= stored
    assert "identity" not in stored


