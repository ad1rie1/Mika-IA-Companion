"""Preuve M0 — le démarrage refuse une composition incohérente, et les couches
sont vérifiées (un import interdit fait échouer import-linter) ; les sections
des plugins restent en zone volatile (ADR 0022)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from mika.app.composition import READING, faculties
from mika.kernel.events import Payload
from mika.kernel.facts import FactKey
from mika.kernel.faculty import Faculty, SectionSpec, Zone
from mika.kernel.registry import ArbitrationPolicy, CompositionError, Registry
from mika.runtime.state import RUNTIME

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class S:
    n: int = 0


class P(Payload):
    x: int = 0


def fac(name: str) -> Faculty:
    return Faculty(name, state=S, init=lambda p: S())


def problems(*faculties: Faculty, arbitration: ArbitrationPolicy | None = None,
             reading: Sequence[str] | None = None) -> list[str]:
    with pytest.raises(CompositionError) as info:
        Registry(list(faculties), arbitration=arbitration, reading=reading)
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


def test_the_reading_order_names_every_section_once():
    """L'ordre de lecture (ADR 0151) nomme chaque section une fois : une section oubliée, une clé inconnue, une clé
    redite sont des erreurs de composition — jamais un ordre que personne n'a choisi."""
    a = fac("a")
    for key in ("x", "y", "z"):
        a.section(key, zone=Zone.VOLATILE, episodes=["REPLY"])(lambda s, f, e: None)
    ps = problems(a, reading=("x", "y", "y", "fantome"))
    assert any("« z » n'y figure pas" in p for p in ps)
    assert any("section inconnue « fantome »" in p for p in ps)
    assert any("« y » y figure deux fois" in p for p in ps)
    assert [s.key for s in Registry([a], reading=("z", "x", "y")).sections] == ["z", "x", "y"]
    assert [s.key for s in Registry([a]).sections] == ["x", "y", "z"]  # sans ordre : celui de la déclaration


def test_her_composition_declares_the_reading_order_of_her_prompt():
    """Toutes ses sections sont dans ``READING`` : le registre de sa composition se construit sans problème, et le
    prompt suit cet ordre (la personne en face juste avant sa parole, sa réponse en dernier)."""
    keys = [s.key for s in Registry([RUNTIME, *faculties()], reading=READING).sections]
    assert keys == list(READING)
    assert keys[-1] == "answer" and keys.index("who") < keys.index("their_state") < keys.index("habits")


def _plugin_sections(facs: Sequence[Faculty]) -> list[SectionSpec]:
    """Les sections dont la fonction vit sous ``mika.plugins`` : celles d'un plugin. Rien d'autre ne les distingue
    de celles d'une faculté, que ``faculties()`` rend dans la même liste."""
    return [s for f in facs for s in f.sections if (getattr(s.fn, "__module__", None) or "").startswith("mika.plugins.")]


def _plugin_sections_outside_volatile(facs: Sequence[Faculty]) -> list[str]:
    """Les sections d'un plugin hors de la zone volatile, nommées ``plugin.clé (zone)``."""
    return [f"{s.owner}.{s.key} ({s.zone})" for s in _plugin_sections(facs) if s.zone is not Zone.VOLATILE]


def test_every_plugin_section_is_in_the_volatile_zone():
    """La confiance restreinte des plugins (ARCHITECTURE.md, « Les plugins ») : toute section d'un plugin est en zone
    volatile, jamais dans le préfixe stable du prompt — ce qui vient d'ailleurs est cité : une section non fiable,
    coupée en premier (ADR 0022). Sur la composition réelle ; au moins vingt sections de plugin vues, pour que la
    garde ne passe pas à vide."""
    facs = faculties()
    assert len(_plugin_sections(facs)) >= 20
    assert _plugin_sections_outside_volatile(facs) == []


def test_a_plugin_section_in_the_stable_zone_is_caught():
    """La garde attrape un plugin qui écrirait en zone stable, et elle seule : la même zone reste permise à une
    faculté, et une section de plugin en zone volatile passe."""
    def stable_plugin(s, f, e):
        return None

    def volatile_plugin(s, f, e):
        return None

    def stable_faculty(s, f, e):
        return None

    stable_plugin.__module__ = volatile_plugin.__module__ = "mika.plugins.jouet"
    stable_faculty.__module__ = "mika.faculties.jouet"
    a = fac("jouet")
    a.section("dedans", zone=Zone.STABLE, episodes=["REPLY"])(stable_plugin)
    a.section("dehors", zone=Zone.VOLATILE, episodes=["REPLY"])(volatile_plugin)
    a.section("sienne", zone=Zone.STABLE, episodes=["REPLY"])(stable_faculty)
    assert len(_plugin_sections([a])) == 2
    assert _plugin_sections_outside_volatile([a]) == ["jouet.dedans (stable)"]


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
    target.write_text("import mika.adapters.store_sql  # interdit\n")
    out = _lint(copy)
    assert out.returncode != 0
    assert "BROKEN" in out.stdout or "broken" in out.stdout.lower()
