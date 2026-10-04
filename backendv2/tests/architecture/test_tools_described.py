"""Chaque outil dit à quoi il sert et à qui il est offert (ADR 0064) : « Ses outils » le lit dans le registre.

Un lot sans phrase se lirait dans son catalogue comme une liste de noms ; une condition d'offre (``when=``) sans
docstring se lirait sur sa fiche « sa condition n'est pas remplie », sans dire laquelle."""

from __future__ import annotations

import inspect

from mika.app.composition import arbitration, faculties
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME


def _registry() -> Registry:
    return Registry([RUNTIME, *faculties()], arbitration=arbitration())


def test_every_bundle_of_the_code_says_what_it_allows():
    registry = _registry()
    missing = sorted({s.bundle for s in registry.tools.values() if not registry.bundles.get(s.bundle, "").strip()})
    assert missing == [], f"lots sans description : {missing}"


def test_every_offer_condition_says_itself():
    registry = _registry()
    silent = sorted(s.name for s in registry.tools.values()
                    if s.when is not None and not (inspect.getdoc(s.when) or "").strip())
    assert silent == [], f"conditions d'offre sans docstring : {silent}"


def test_every_tool_says_what_it_does():
    registry = _registry()
    assert sorted(s.name for s in registry.tools.values() if len(s.description.strip()) < 8) == []
