"""D'où elle tient une croyance, en mots : une seule table (``faculties/memory/inspect.py``), qui nomme chaque origine
que la mémoire donne à ses éléments (audit du 2026-11-05, K11-02).

Avant : la table de la faculté oubliait « lu » (``READ``, ADR 0085) ; la console affichait la clé brute, « read
(le-monde) », et l'onglet dessiné, qui retrouve la sorte par les mots, la perdait. La fiche d'une personne avait sa
propre table, complète, sous d'autres mots.
"""

from __future__ import annotations

import ast
from pathlib import Path

from mika.app.handmade.tabs.memory import _origin
from mika.contracts import memory as memory_c
from mika.faculties.memory.inspect import ORIGIN_FR, ORIGIN_SHORT
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import Table
from mika.ports.llm import LLMResponse
from mika.runtime import inspection
from mika.runtime.inspection import Inspection
from mika.sim.clock import run_virtual
from tests.fixtures.mika import boot, build

FACULTY = Path(__file__).resolve().parents[2] / "src" / "mika" / "faculties" / "memory"


def _aliases(tree: ast.Module) -> set[str]:
    """Les noms sous lesquels un module importe le contrat de la mémoire (``from mika.contracts import memory as c``)."""
    return {a.asname or a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            and node.module == "mika.contracts" for a in node.names if a.name == "memory"}


def _value(node: ast.AST | None, aliases: set[str]) -> str:
    """Une origine écrite dans le code : une constante du contrat (``c.READ``) ou sa valeur (``"inferred"``)."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
        return str(getattr(memory_c, node.attr, ""))
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def origins_given() -> set[str]:
    """Les origines que la faculté donne à ses éléments, lues dans son code : chaque origine passée en ``origin=``,
    comparée à un ``.origin``, ou que devient le mot du modèle (``extraction.ORIGIN`` : « déduit » → ``inferred``)."""
    found: set[str] = set()
    for path in FACULTY.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "origin":
                found.add(_value(node.value, aliases))
            elif isinstance(node, ast.Compare) and any(isinstance(x, ast.Attribute) and x.attr == "origin"
                                                       for x in (node.left, *node.comparators)):
                found |= {_value(x, aliases) for x in (node.left, *node.comparators)}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) \
                    and any(isinstance(t, ast.Name) and t.id == "ORIGIN" for t in node.targets):
                found |= {_value(v, aliases) for v in node.value.values}
    return found - {""}


def test_every_origin_a_belief_can_have_has_its_words_in_one_table():
    given = origins_given()
    # la lecture n'est pas vide : les quatre origines d'une croyance, et le mensonge, que la faculté donne
    assert {memory_c.TOLD, memory_c.OBSERVED, memory_c.INFERRED, memory_c.READ, memory_c.LIED} <= given
    beliefs = given - {memory_c.LIED}  # un souvenir né d'un mensonge n'est pas une croyance : il a sa mention
    for origin in beliefs:
        assert ORIGIN_FR.get(origin) and ORIGIN_FR[origin] != origin, origin
        assert ORIGIN_SHORT.get(origin) and ORIGIN_SHORT[origin] != origin, origin
    assert set(ORIGIN_FR) == set(ORIGIN_SHORT) == beliefs  # une table, sa forme courte : les mêmes clés


def test_the_drawn_tab_finds_the_kind_of_every_origin_from_its_words():
    assert _origin("elle l'a lu (Le Monde)") == {"kind": memory_c.READ, "text": "elle l'a lu", "who": "Le Monde"}
    for origin, words in ORIGIN_FR.items():
        assert _origin(f"{words} (Adrien)") == {"kind": origin, "text": words, "who": "Adrien"}
        assert _origin(words) == {"kind": origin, "text": words, "who": ""}


def test_a_belief_she_read_says_so_in_the_console(tmp_path):
    """La colonne « origine » de Mémoire › Croyances : « elle l'a lu (sa source) », jamais la clé brute."""
    kernel, clock, _llm, _out = build(tmp_path, lambda req: LLMResponse("{}"))

    async def main():
        await boot(kernel)
        try:
            await kernel.mind.append([memory_c.BELIEVED.draft(
                text=Content.of("Le musée rouvre samedi."), origin=memory_c.READ, source="le-monde",
                confidence=0.6)], emitter="memory", correlation="lu", origin=Origin.GENESIS)
            spec = inspection.find(kernel, "memory", "croyances")
            return Inspection(kernel).run(spec, {}, str)
        finally:
            await kernel.stop()

    blocks = run_virtual(clock, main)
    table = next(b for b in blocks if isinstance(b, Table) and b.title.startswith("Ses croyances"))
    column = [c if isinstance(c, str) else c.label for c in table.columns].index("origine")
    said = [row.cells[column] for row in table.rows]
    assert said == ["elle l'a lu (le-monde)"]
