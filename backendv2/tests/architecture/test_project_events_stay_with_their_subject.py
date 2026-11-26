"""Un sous-sujet des projets garde ses événements dans son module (ADR 0313).

``faculties/projects/faculty.py`` déclare les événements du projet lui-même et de ses objectifs, et ceux des
sous-sujets nés avant la règle (``BORN_BEFORE`` : tous en sont sortis). Un sous-sujet neuf déclare les siens dans son
module, comme le registre (``tracker.py``) et la documentation (``docs.py``) : la liste d'ici ne s'allonge pas, et
raccourcit quand un sous-sujet d'avant sort de ``faculty.py``.

Lu par l'AST : un commentaire ou une docstring qui nomme un événement ne compte pas.
"""

from __future__ import annotations

import ast
from pathlib import Path

import mika

FOLDER = Path(mika.__file__).parent / "faculties" / "projects"

#: le projet lui-même et ses objectifs : ce que ``Project`` et ``Objective`` sont
ITSELF = frozenset({
    "objective_added", "objective_changed", "reframed", "paused", "resumed", "archived", "restored", "nudged", "noted",
    "amended", "plan_proposed", "plan_answered", "deposited", "remote_requested", "network_queued", "answered",
    "access_set", "links_set", "stirred", "steer_asked",
})

#: les sous-sujets nés avant la règle, encore dans ``faculty.py`` : chacun en sort quand on y touche, et sa ligne
#: s'efface alors d'ici. Tous l'ont fait : les jalons, les décisions techniques, les pull requests et leur CI, la
#: fusion, les issues et la relecture (``milestones.py``, ``decisions.py``, ``pulls.py``, ``merge.py``,
#: ``issues.py``, ``review.py``)
BORN_BEFORE: dict[str, frozenset[str]] = {}


def declared(module: str) -> set[str]:
    """Les événements qu'un module des projets déclare : le premier argument de chaque ``PROJECTS.event(...)``."""
    tree = ast.parse((FOLDER / module).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "event"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "PROJECTS"):
            assert node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str), (
                f"{module}:{node.lineno} : le nom d'un événement s'écrit en clair, pour que cette garde le lise")
            found.add(node.args[0].value)
    return found


def test_faculty_declares_no_event_of_a_new_subject():
    known = ITSELF.union(*BORN_BEFORE.values())
    new = sorted(declared("faculty.py") - known)
    assert not new, (
        f"faculty.py déclare {new} : un sous-sujet des projets garde ses événements, leurs réducteurs et sa "
        "projection dans son module (ADR 0313), comme tracker.py et docs.py. Seul un événement du projet lui-même ou "
        "d'un objectif s'ajoute à ITSELF.")


def test_the_list_shrinks_when_a_subject_leaves_faculty():
    gone = sorted(ITSELF.union(*BORN_BEFORE.values()) - declared("faculty.py"))
    assert not gone, f"{gone} n'est plus déclaré dans faculty.py : l'ôter de cette garde (ADR 0313)."


def test_a_subject_out_of_faculty_declares_its_own_events():
    """Ce qui fait foi pour la règle : le registre et la documentation déclarent les leurs chez eux, comme chaque
    sous-sujet sorti de ``faculty.py``."""
    assert declared("tracker.py") >= {"list_set", "item_added", "item_changed", "item_noted"}
    assert declared("docs.py") >= {"doc_written", "doc_moved", "doc_removed"}
    assert declared("milestones.py") >= {"milestone_added", "milestone_changed"}
    assert declared("decisions.py") >= {"decided", "decision_changed", "decision_revised"}
    assert declared("pulls.py") >= {"pull_seen", "checks_seen", "base_seen"}
    assert declared("merge.py") >= {"merge_asked", "merge_answered", "pull_write_asked", "pull_write_answered"}
    assert declared("issues.py") >= {"issue_asked"}
    assert declared("review.py") >= {"review_asked", "reviewed"}
