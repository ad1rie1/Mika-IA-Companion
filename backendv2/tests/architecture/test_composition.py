"""Preuve M0 — le démarrage refuse une composition incohérente, et les couches
sont vérifiées (un import interdit fait échouer import-linter)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from mika.kernel.events import Payload
from mika.kernel.facts import FactKey
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.registry import ArbitrationPolicy, CompositionError, Registry

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class S:
    n: int = 0


class P(Payload):
    x: int = 0


def fac(name: str) -> Faculty:
    return Faculty(name, state=S, init=lambda p: S())


def problems(*faculties: Faculty, arbitration: ArbitrationPolicy | None = None) -> list[str]:
    with pytest.raises(CompositionError) as info:
        Registry(list(faculties), arbitration=arbitration)
    return info.value.problems


def test_duplicate_fact_provider():
    a, b = fac("a"), fac("b")
    k = FactKey("a.k")
    a.fact(k)(lambda s, cx: 1)
    b.fact(k)(lambda s, cx: 2)
    assert any("fourni deux fois" in p for p in problems(a, b))


def test_unknown_fact_reference():
    a = fac("a")
    e = a.event("e", P)
    a.reducer(e, reads=["inconnu.fait"])(lambda s, ev, cx: s)
    assert any("fait inconnu" in p for p in problems(a))


def test_private_event_reduced_by_other_owner():
    a, b = fac("a"), fac("b")
    private = a.event("secret", P)  # privé par défaut
    b.reducer(private)(lambda s, ev, cx: s)
    assert any("privé" in p for p in problems(a, b))


def test_fact_cycle():
    a = fac("a")
    k1, k2 = FactKey("a.un"), FactKey("a.deux")
    a.fact(k1, reads=[k2])(lambda s, cx: 1)
    a.fact(k2, reads=[k1])(lambda s, cx: 2)
    assert any("cycle de faits" in p for p in problems(a))


def test_section_cycle_and_unknown_anchor():
    a = fac("a")
    a.section("x", zone=Zone.VOLATILE, episodes=["REPLY"], after=["y"])(lambda s, f, e: None)
    a.section("y", zone=Zone.VOLATILE, episodes=["REPLY"], after=["x"])(lambda s, f, e: None)
    a.section("z", zone=Zone.VOLATILE, episodes=["REPLY"], before=["fantome"])(lambda s, f, e: None)
    ps = problems(a)
    assert any("cycle dans l'ordre des sections" in p for p in ps)
    assert any("ancre inconnue" in p for p in ps)


def test_unreachable_threshold():
    a = fac("a")
    a.propose(kinds=["INITIATIVE"], reasons={"manque": (0.0, 1.0)})(lambda s, f: [])
    ps = problems(a, arbitration=ArbitrationPolicy(thresholds={"INITIATIVE": 3.0}))
    assert any("inatteignable" in p for p in ps)


def test_namespace_violation():
    a = fac("a")
    a.event("autre.chose", P)
    assert any("espace de noms" in p for p in problems(a))


def test_valid_composition_boots():
    a, b = fac("a"), fac("b")
    k = FactKey("a.k")
    e = a.event("e", P, public=True)
    a.fact(k)(lambda s, cx: s.n)
    b.reducer(e, reads=[k])(lambda s, ev, cx: s)
    Registry([a, b])


def _lint(src_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports"), "--config", str(ROOT / "pyproject.toml")],
        cwd=src_root, capture_output=True, text=True, env={"PYTHONPATH": str(src_root), "PATH": "/usr/bin:/bin"},
    )


def test_layers_hold_on_the_real_code():
    out = _lint(ROOT / "src")
    assert out.returncode == 0, out.stdout + out.stderr


def test_a_forbidden_import_breaks_the_layers(tmp_path):
    copy = tmp_path / "src"
    shutil.copytree(ROOT / "src" / "mika", copy / "mika", ignore=shutil.ignore_patterns("__pycache__"))
    target = copy / "mika" / "faculties" / "body" / "__init__.py"
    target.write_text("import mika.adapters.store_sqlite  # interdit\n")
    out = _lint(copy)
    assert out.returncode != 0
    assert "BROKEN" in out.stdout or "broken" in out.stdout.lower()
