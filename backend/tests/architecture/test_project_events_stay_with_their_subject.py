"""Un sous-sujet des projets garde ses événements dans son module (ADR 0313).

``faculties/projects/faculty.py`` ne déclare que les événements du projet lui-même et de ses objectifs
(``ITSELF``). Un sous-sujet déclare les siens dans son module, comme le registre (``tracker.py``) et la documentation
(``docs.py``) ; ceux qui étaient nés dans ``faculty.py`` avant la règle en sont tous sortis — les jalons, les
décisions techniques, les pull requests et leur CI, la fusion, les issues, la relecture (``milestones.py``,
``decisions.py``, ``pulls.py``, ``merge.py``, ``issues.py``, ``review.py``). La liste d'ici ne s'allonge donc que d'un
événement du projet lui-même, et il n'y a plus de place où ranger un sous-sujet.

Les réducteurs et la projection d'un sous-sujet vont avec ses événements : ``faculty.py`` ne réduit que ce qu'il
déclare lui-même et ce qu'il lit d'un contrat (``c.…``, ``rt.…``) — jamais l'événement d'un module voisin, jamais par
forme (``shapes=``, qui prendrait ceux de tous) —, et n'inscrit aucune projection.

Lu par l'AST : un commentaire ou une docstring qui nomme un événement ne compte pas. Les projets se lisent aussi sous
un autre nom (``P = PROJECTS``) ; ce qui échappe encore est dit dans ``tests/fixtures/source.py``. Un événement public
d'un sous-sujet, déclaré au contrat, échapperait aussi : le contrat des projets n'en porte aucun.
"""

from __future__ import annotations

import ast
from pathlib import Path

import mika
from tests.fixtures.source import aliases, held

FOLDER = Path(mika.__file__).parent / "faculties" / "projects"

#: le projet lui-même et ses objectifs : ce que ``Project`` et ``Objective`` sont
ITSELF = frozenset({
    "objective_added", "objective_changed", "reframed", "paused", "resumed", "archived", "restored", "nudged", "noted",
    "amended", "plan_proposed", "plan_answered", "deposited", "remote_requested", "network_queued", "answered",
    "access_set", "links_set", "stirred", "steer_asked",
})


def calls(tree: ast.AST, kind: str, owner: str = "PROJECTS") -> list[ast.Call]:
    """Chaque appel ``PROJECTS.<kind>(…)`` d'un source, sous chacun des noms que le module donne aux projets."""
    names = aliases(tree, owner)
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == kind
            and held(node.func.value, names, owner)]


def declared_in(source: str, where: str = "faculty.py") -> set[str]:
    """Les événements qu'un source déclare : le premier argument de chaque ``PROJECTS.event(...)``."""
    found: set[str] = set()
    for node in calls(ast.parse(source), "event"):
        assert node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str), (
            f"{where}:{node.lineno} : le nom d'un événement s'écrit en clair, pour que cette garde le lise")
        found.add(node.args[0].value)
    return found


def declared(module: str) -> set[str]:
    """Les événements qu'un module des projets déclare."""
    return declared_in((FOLDER / module).read_text(encoding="utf-8"), module)


def foreign(source: str) -> list[str]:
    """Ce que ``faculty.py`` réduit ou projette et qui n'est pas au projet lui-même, en phrases : un réducteur dont
    l'événement n'est ni déclaré ici ni lu d'un contrat — donc celui d'un module voisin —, un réducteur par forme, une
    projection."""
    tree = ast.parse(source)
    events = {id(node) for node in calls(tree, "event")}
    own = {target.id for node in tree.body if isinstance(node, ast.Assign | ast.AnnAssign) and id(node.value) in events
           for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
           if isinstance(target, ast.Name)}
    public: set[str] = set()  # un contrat sous son nom local, ou un nom qu'on en importe
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level and (node.module or "").split(".")[:2] == [
                "mika", "contracts"]:
            public |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            public |= {a.asname for a in node.names if a.asname and a.name.startswith("mika.contracts.")}
    rule = "un sous-sujet des projets garde ses événements, leurs réducteurs et sa projection dans son module (ADR 0313)"
    out = []
    for node in calls(tree, "reducer"):
        if any(keyword.arg == "shapes" for keyword in node.keywords):
            out.append(f"faculty.py:{node.lineno} réduit par forme (shapes=), donc aussi les événements des "
                       f"sous-sujets : {rule}")
        for arg in node.args:
            root = arg
            while isinstance(root, ast.Attribute):
                root = root.value
            name = root.id if isinstance(root, ast.Name) else ""
            if name not in public and not (isinstance(arg, ast.Name) and name in own):
                out.append(f"faculty.py:{node.lineno} réduit {ast.unparse(arg)}, qu'il ne déclare pas et qui ne vient "
                           f"pas d'un contrat : {rule}")
    out += [f"faculty.py:{node.lineno} inscrit une projection : {rule}" for node in calls(tree, "projector")]
    return out


def test_faculty_declares_no_event_of_a_new_subject():
    new = sorted(declared("faculty.py") - ITSELF)
    assert not new, (
        f"faculty.py déclare {new} : un sous-sujet des projets garde ses événements, leurs réducteurs et sa "
        "projection dans son module (ADR 0313), comme tracker.py et docs.py. Seul un événement du projet lui-même ou "
        "d'un objectif s'ajoute à ITSELF.")


def test_the_list_shrinks_when_a_subject_leaves_faculty():
    gone = sorted(ITSELF - declared("faculty.py"))
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


def test_faculty_reduces_and_projects_nothing_of_a_subject():
    source = (FOLDER / "faculty.py").read_text(encoding="utf-8")
    assert len(calls(ast.parse(source), "reducer")) > 30  # la lecture trouve bien ses réducteurs
    faults = foreign(source)
    assert not faults, "\n".join(faults)


def test_the_check_sees_a_subject_reduced_or_projected_in_faculty():
    """Le projet lui-même et les événements d'un contrat passent ; l'événement d'un voisin, importé par son nom ou lu
    par son module, la réduction par forme et une projection échouent — et les projets rebaptisés restent les projets."""
    toy = ("from mika.contracts import projects as c\nfrom mika.contracts import runtime as rt\n"
           "from mika.contracts.forge import RAISED\n\nPAUSED = PROJECTS.event('paused', StateChanged)\n\n\n"
           "@PROJECTS.reducer(PAUSED)\ndef _paused(s, e, cx): ...\n\n\n"
           "@PROJECTS.reducer(c.PROJECT_CREATED, rt.UTTERANCE, RAISED, reads=[x.PERSON])\ndef _made(s, e, cx): ...\n"
           "# @PROJECTS.reducer(PULL_SEEN) : un commentaire ne compte pas\n")
    assert foreign(toy) == []
    assert declared_in(toy) == {"paused"}
    toy += ("from mika.faculties.projects import pulls\nfrom mika.faculties.projects.pulls import PULL_SEEN\n"
            "P = PROJECTS\n\n\n@P.reducer(PULL_SEEN)\ndef _seen(s, e, cx): ...\n\n\n"
            "@PROJECTS.reducer(pulls.CHECKS_SEEN)\ndef _checks(s, e, cx): ...\n\n\n"
            "@PROJECTS.reducer(shapes=[PullSeen])\ndef _any(s, e, cx): ...\n\n\n"
            "P.projector('projects_reviews', version=1)(Reviews)\nMILESTONE_X = P.event('milestone_x', Milestone)\n")
    assert [fault.split(" : ")[0].split(" ", 1)[1] for fault in foreign(toy)] == [
        "réduit PULL_SEEN, qu'il ne déclare pas et qui ne vient pas d'un contrat",
        "réduit pulls.CHECKS_SEEN, qu'il ne déclare pas et qui ne vient pas d'un contrat",
        "réduit par forme (shapes=), donc aussi les événements des sous-sujets",
        "inscrit une projection"]
    assert declared_in(toy) == {"paused", "milestone_x"}
