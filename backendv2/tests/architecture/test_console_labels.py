"""Tout ce que la composition déclare, la console le nomme (ADR 0042).

Une section, une raison, un veto, un processus ou un événement qu'une faculté ajoute
sans le nommer dans ``app/console.py`` se lit sous une forme générique (« Liens ·
reciprocity », « step_origin » dans « Pourquoi a-t-elle dit ça ? ») : la promesse
de l'ADR 0042 ne tenait que par vigilance. Ce garde confronte le registre de la
composition réelle aux tables ; il échoue dès qu'une clé manque, ou qu'un libellé
nomme ce qui n'existe plus.

Les vetos ne sont pas déclarés au registre (une modulation les rend à la volée) :
ils sont lus dans le code, par l'AST, là où une modulation les pose — directement
(``Modulation(veto=c.GRUDGE)``) ou par une fonction du même module qui rend le veto
(``veto = harassing(…)`` : ce que ``harassing`` peut rendre).

Le murmure (``expression.why()``, ``expression.murmur.why`` dans sa voix) dit en clair ce qui la pousse à écrire : chaque
raison d'une initiative y a sa phrase, sauf celles qui ne sont pas un motif.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from mika.app import console
from mika.app.composition import arbitration, faculties
from mika.contracts import agency as agency_c
from mika.contracts import social as social_c
from mika.faculties.expression import why
from mika.inspector.names import EVENTS as CONSOLE_EVENTS
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME
from mika.vocab.episodes import Kind

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"
#: ce qui pose des vetos : les facultés et les plugins (le noyau n'en pose pas)
VETO_ROOTS = (SRC / "faculties", SRC / "plugins")
#: des raisons d'initiative qui ne sont pas un motif à murmurer : pas de murmure avant une salutation (et
#: « quelqu'un de présent » l'accompagne), et se raviser est une retenue
NOT_A_MOTIVE = frozenset({social_c.GREETING, social_c.PRESENT_PERSON, agency_c.SECOND_THOUGHTS})


def _registry() -> Registry:
    return Registry([RUNTIME, *faculties()], arbitration=arbitration())


def _declared() -> dict[str, set[str]]:
    reg = _registry()
    out: dict[str, set[str]] = {"faculties": set(), "sections": set(), "reasons": set(), "processes": set(),
                                "events": set(), "initiative_reasons": set()}
    for f in reg.faculties.values():
        out["faculties"].add(f.name)
        out["sections"] |= {s.key for s in f.sections}
        for p in f.proposers:
            out["reasons"] |= set(p.reasons)
            if Kind.INITIATIVE in p.kinds:
                out["initiative_reasons"] |= set(p.reasons)
        out["processes"] |= {p.name for p in f.processes}
        out["events"] |= {e.name for e in f.events.values()}
    return out


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Les modules importés par alias (``from mika.contracts import agency as c`` → ``c`` : le module)."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mika."):
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _value(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
        got = getattr(importlib.import_module(aliases[node.value.id]), node.attr, None)
        return got if isinstance(got, str) else None
    return None


def _vetoes() -> dict[str, str]:
    """Chaque veto que le code peut poser, et où (pour le message d'échec)."""
    found: dict[str, str] = {}
    for root in VETO_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            aliases = _aliases(tree)
            functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            for fn in functions.values():
                for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                    for kw in call.keywords:
                        if kw.arg != "veto":
                            continue
                        candidates: list[ast.AST] = [kw.value]
                        if isinstance(kw.value, ast.Name):  # ``veto = harassing(…)`` : ce que la fonction rend
                            for assign in (n for n in ast.walk(fn) if isinstance(n, ast.Assign)):
                                if any(isinstance(t, ast.Name) and t.id == kw.value.id for t in assign.targets) \
                                        and isinstance(assign.value, ast.Call) \
                                        and isinstance(assign.value.func, ast.Name) \
                                        and assign.value.func.id in functions:
                                    callee = functions[assign.value.func.id]
                                    candidates += [r.value for r in ast.walk(callee)
                                                   if isinstance(r, ast.Return) and r.value is not None]
                        for c in candidates:
                            v = _value(c, aliases)
                            if v is not None:
                                found.setdefault(v, f"{path.relative_to(SRC)}:{getattr(c, 'lineno', 0)}")
    return found


def test_every_section_reason_process_event_and_faculty_is_named():
    d = _declared()
    named_events = set(console.EVENT_LABELS) | set(CONSOLE_EVENTS)
    missing = {
        "sections": sorted(d["sections"] - set(console.SECTION_LABELS)),
        "raisons": sorted(d["reasons"] - set(console.REASON_LABELS)),
        "processus": sorted(d["processes"] - set(console.PROCESS_LABELS)),
        "événements": sorted(d["events"] - named_events),
        "facultés": sorted(d["faculties"] - set(console.FACULTY_LABELS)),
    }
    assert not any(missing.values()), f"à nommer dans app/console.py : {missing}"
    # la vague en cours en a ajouté : nommés eux aussi
    assert {"habits"} <= set(console.SECTION_LABELS) and {"follow_up"} <= set(console.REASON_LABELS)


def test_no_label_names_something_that_no_longer_exists():
    """Un libellé orphelin cache une clé renommée (la nouvelle, elle, se lit sous sa forme générique)."""
    d = _declared()
    stale = {
        "sections": sorted(set(console.SECTION_LABELS) - d["sections"]),
        "raisons": sorted(set(console.REASON_LABELS) - d["reasons"]),
        "processus": sorted(set(console.PROCESS_LABELS) - d["processes"]),
        "événements": sorted(set(console.EVENT_LABELS) - d["events"]),
    }
    assert not any(stale.values()), f"libellés sans objet dans app/console.py : {stale}"


def test_every_veto_the_code_can_set_is_named():
    vetoes = _vetoes()
    assert {social_c.GRUDGE, agency_c.UNANSWERED, agency_c.AWAITING_REPLY} <= set(vetoes)  # le garde voit loin
    missing = {v: where for v, where in vetoes.items() if v not in console.VETO_LABELS}
    assert not missing, f"vetos à nommer dans app/console.py (VETO_LABELS) : {missing}"


def test_the_murmur_says_why_for_every_motive_of_an_initiative():
    """« lui dire un mot » : le murmure d'une initiative dont le motif n'avait pas de phrase (« j'ai besoin de toi »
    pour un projet)."""
    motives = _declared()["initiative_reasons"] - NOT_A_MOTIVE
    assert motives, "aucune raison d'initiative lue"
    said = set(why())
    assert not sorted(motives - said), f"raisons sans phrase dans expression.murmur.why : {sorted(motives - said)}"
