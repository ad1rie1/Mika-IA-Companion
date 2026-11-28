"""Sa mémoire réduit ses événements en un seul endroit (ADR 0315).

La mémoire a son modèle, qui n'est pas celui des projets (ADR 0313) : ses événements sont publics, donc au contrat
(``contracts/memory.py``) ; leurs réducteurs, ses faits et son appréciation sont dans ``faculty.py``, seul ; ses
projections dans ``projections.py`` (``life_archive.py`` pour l'archive de sa vie). Ce qu'un sous-sujet a de propre — ses
règles, son processus, son interprète, sa section — vit dans son module.

Lu par l'AST : un décorateur ``@MEMORY.<sorte>`` ou un appel ``MEMORY.<sorte>(…)`` ; un commentaire ou une docstring
qui en parle ne compte pas. La mémoire se lit aussi sous un autre nom (``M = MEMORY``, ``import … MEMORY as M``,
``faculty.MEMORY``) ; ce qui échappe encore est dit dans ``tests/fixtures/source.py``.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import mika
from tests.fixtures.source import aliases, held

FOLDER = Path(mika.__file__).parent / "faculties" / "memory"

#: chaque sorte de contribution qui n'a qu'une maison, et laquelle
HOMES: dict[str, frozenset[str]] = {
    "reducer": frozenset({"faculty.py"}),
    "fact": frozenset({"faculty.py"}),
    "appraisal": frozenset({"faculty.py"}),
    "projector": frozenset({"projections.py", "life_archive.py"}),
}


def contributions(source: str, owner: str = "MEMORY") -> list[tuple[int, str]]:
    """Chaque contribution qu'un source inscrit auprès de ``owner`` : sa ligne et sa sorte (``reducer``, ``fact``…) —
    le décorateur ``@MEMORY.reducer(…)`` comme l'appel ``MEMORY.projector(…)(…)``, sous chacun de ses noms."""
    tree = ast.parse(source)
    names = aliases(tree, owner)
    return sorted({(node.lineno, node.attr) for node in ast.walk(tree)
                   if isinstance(node, ast.Attribute) and held(node.value, names, owner)})


def misplaced(sources: Mapping[str, str], homes: Mapping[str, frozenset[str]] = HOMES) -> list[str]:
    """Ce qui n'est pas dans sa maison, en phrases (``sources`` : le texte de chaque module, par son nom)."""
    return [f"{name}:{line} inscrit un « {kind} » hors de {' et '.join(sorted(homes[kind]))} : dans la mémoire, "
            "les réducteurs, les faits et l'appréciation sont dans faculty.py, les projections dans projections.py "
            "(ADR 0315 ; ARCHITECTURE.md, la mémoire, « Où va un sous-sujet »)"
            for name, text in sorted(sources.items()) for line, kind in contributions(text)
            if kind in homes and name not in homes[kind]]


def test_memory_reduces_its_events_in_faculty_and_projects_them_in_projections():
    sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(FOLDER.glob("*.py"))}
    found = {kind: {name for name, text in sources.items() if kind in {k for _, k in contributions(text)}}
             for kind in HOMES}
    # la lecture trouve bien ce qu'elle garde : chaque maison sert
    assert found == {kind: set(home) for kind, home in HOMES.items()}, found
    faults = misplaced(sources)
    assert not faults, "\n".join(faults)


def test_the_check_sees_a_reducer_and_a_projector_out_of_their_home():
    """Un réducteur, un fait ou une projection posés dans le module d'un sous-sujet échouent ; ce qui est à lui — son
    processus, sa section — passe, comme une contribution d'un autre propriétaire."""
    toy = {
        "faculty.py": "@MEMORY.reducer(c.KEPT)\ndef _kept(s, e, cx): ...\n\n\n@MEMORY.fact(c.KNOWN)\ndef _known(s): ...\n",
        "projections.py": "MEMORY.projector(c.ITEMS, version=1)(Items)\n",
        "photos.py": ("@MEMORY.process('memory.photos')\nclass Photos: ...\n\n\n@MEMORY.section('photos')\n"
                      "def _photos(s, f): ...\n\n\n@OTHERS.reducer(c.SEEN)\ndef _seen(s, e, cx): ...\n"
                      "# @MEMORY.reducer : un commentaire ne compte pas\n"),
    }
    assert misplaced(toy) == []
    toy["photos.py"] += ("\n\n@MEMORY.reducer(c.SEEN)\ndef _mine(s, e, cx): ...\n\n\n@MEMORY.fact(c.SHOWN)\n"
                         "def _shown(s): ...\n\n\nMEMORY.projector(c.PHOTOS, version=1)(Photos)\n")
    faults = misplaced(toy)
    assert all(fault.startswith("photos.py:") and "ADR 0315" in fault for fault in faults)
    assert [fault.split(" inscrit un ")[1].split(" hors de ")[0] for fault in faults] == [
        "« reducer »", "« fact »", "« projector »"]


def test_the_check_follows_memory_under_another_name():
    """La mémoire rebaptisée — par une affectation, à l'import, ou lue par son module — reste la mémoire."""
    toy = {
        "faculty.py": "@MEMORY.reducer(c.KEPT)\ndef _kept(s, e, cx): ...\n",
        "renamed.py": "M = MEMORY\nN = M\n\n\n@N.reducer(c.SEEN)\ndef _seen(s, e, cx): ...\n",
        "imported.py": ("from mika.faculties.memory.faculty import MEMORY as M\n\n\n@M.fact(c.SHOWN)\n"
                        "def _shown(s): ...\n"),
        "by_module.py": ("from mika.faculties.memory import faculty\n\nfaculty.MEMORY.projector(c.PHOTOS, version=1)"
                         "(Photos)\n"),
        "other.py": "M = OTHERS\n\n\n@M.reducer(c.SEEN)\ndef _seen(s, e, cx): ...\n",
    }
    assert [fault.split(" hors de ")[0] for fault in misplaced(toy)] == [
        "by_module.py:3 inscrit un « projector »", "imported.py:4 inscrit un « fact »",
        "renamed.py:5 inscrit un « reducer »"]
