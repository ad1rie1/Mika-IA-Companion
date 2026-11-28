"""Les outils dynamiques du registre (ADR 0064) : une faculté déclare une famille de lots, le noyau y range ce que
sa source rend — jamais par-dessus un outil du code, jamais hors de sa famille, d'un bloc."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from mika.kernel.faculty import Faculty, ToolSpec
from mika.kernel.registry import CompositionError, Registry
from mika.runtime.state import RUNTIME


@dataclass(frozen=True)
class Nothing:
    pass


class NoArgs(BaseModel):
    pass


async def _noop(args, ctx):
    return "ok"


def _faculty(name: str = "ext", family: str = "ext") -> Faculty:
    f = Faculty(name, state=Nothing, init=lambda p: Nothing())
    f.tool("ext_static", description="un outil du code", args=NoArgs, bundle="ext_code", episodes=["REPLY"])(_noop)

    @f.tool_source(family)
    def source(ports):
        return [], {}

    return f


def _spec(name: str, bundle: str = "ext.meteo", owner: str = "ext") -> ToolSpec:
    return ToolSpec(owner, name, "la météo", NoArgs, _noop, bundle, frozenset({"REPLY"}))


def test_a_source_fills_its_family_and_reads_like_any_tool():
    registry = Registry([RUNTIME, _faculty()])
    before = registry.tools
    problems = registry.set_dynamic("ext", [_spec("meteo_prevision")], {"ext.meteo": "la météo d'une ville"})
    assert problems == []
    assert "meteo_prevision" in registry.tools and registry.is_dynamic("meteo_prevision")
    assert not registry.is_dynamic("ext_static") and "ext_static" in registry.tools
    assert registry.bundles["ext.meteo"] == "la météo d'une ville"
    assert registry.dynamic_owner("meteo_prevision") == "ext"
    # un lecteur garde le dictionnaire qu'il a : le remplacement est d'un bloc
    assert "meteo_prevision" not in before


def test_what_does_not_fit_is_set_aside_and_said():
    registry = Registry([RUNTIME, _faculty()])
    problems = registry.set_dynamic("ext", [
        _spec("ext_static"),                       # un outil du code n'est jamais remplacé
        _spec("hors_famille", bundle="memory"),    # hors de sa famille
        _spec("mal nommé"),                        # un nom qu'aucun fournisseur n'accepte
        _spec("x" * 65),
        _spec("vole", owner="memory"),             # au nom d'une autre faculté
        _spec("bon"),
        _spec("bon"),                              # deux fois
    ], {"ext.meteo": "ok", "memory": "volé"})
    assert set(registry.tools) - set(Registry([RUNTIME, _faculty()]).tools) == {"bon"}
    assert registry.tools["ext_static"].description == "un outil du code"
    assert "memory" not in registry.bundles or registry.bundles.get("memory") != "volé"
    assert len(problems) == 7, problems


def test_a_new_set_replaces_the_old_one_and_an_empty_one_clears_it():
    registry = Registry([RUNTIME, _faculty()])
    registry.set_dynamic("ext", [_spec("a"), _spec("b")], {"ext.meteo": "x"})
    registry.set_dynamic("ext", [_spec("b")], {})
    assert "a" not in registry.tools and "b" in registry.tools and "ext.meteo" not in registry.bundles
    registry.set_dynamic("ext", [], {})
    assert not any(registry.is_dynamic(n) for n in registry.tools)


def test_a_faculty_without_a_family_cannot_add_tools():
    registry = Registry([RUNTIME, _faculty()])
    assert registry.set_dynamic("runtime", [_spec("a", owner="runtime")], {}) != []
    assert "a" not in registry.tools


def test_a_family_cannot_shadow_a_bundle_of_the_code():
    f = _faculty(family="ext_code")
    with pytest.raises(CompositionError, match="un lot du code porte déjà ce nom"):
        Registry([RUNTIME, f])
