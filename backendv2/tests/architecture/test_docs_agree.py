"""La documentation dit ce que fait le code.

La doc du moteur dérivait plus vite qu'on ne la relisait : des trames que le serveur n'émet pas, un fichier disparu,
une sous-commande renommée, un ADR cité qui n'existe pas. Ce test confronte ce qui se vérifie mécaniquement ; le
reste relève de la règle « la doc suit le code, dans le même lot » (``CLAUDE.md``).

- les numéros d'ADR cités par le code et la doc ont leur entrée dans ``docs/decisions.md``, numérotée sans trou ni
  double, et chaque entrée est sur sa carte ;
- les trames du chat que le serveur émet et lit (lues dans le code par ``ast``) sont celles que décrit
  ``docs/protocole-chat.md`` ;
- les sous-commandes de la CLI (lues dans l'analyseur lui-même) sont celles de la table d'``ARCHITECTURE.md`` ;
- un chemin de fichier cité entre accents graves existe.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import pytest

from mika.app import cli

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
PACKAGE = ROOT / "src" / "mika"
DECISIONS = ROOT / "docs" / "decisions.md"
CHAT = ROOT / "docs" / "protocole-chat.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
#: la doc qui décrit le présent ; ``decisions.md`` raconte aussi ce qui a été retiré, il n'est pas lu pour ses chemins
DOCS = (ARCHITECTURE, ROOT / "README.md", ROOT / "deploy" / "README.md", CHAT, ROOT / "docs" / "protocole-monde.md",
        ROOT / "docs" / "console-carte.md", REPO / "CLAUDE.md", REPO / "frontend" / "Web" / "README.md")
#: d'où se lit un chemin écrit court (« `handmade/now.py` », « `ui/bubbles.ts` »)
BASES = (ROOT, PACKAGE, PACKAGE / "app", PACKAGE / "inspector", PACKAGE / "inspector" / "templates",
         PACKAGE / "inspector" / "static", ROOT / "tests", REPO, REPO / "frontend" / "Web", REPO / "frontend" / "Web" / "src",
         REPO / "frontend" / "Unity")
#: une trame que le serveur lit et ignore toujours : l'identité vient de la session ou du jeton
IGNORED = frozenset({"identify"})

ENTRY = re.compile(r"^### (\d{4}) — ", re.M)
CITED = re.compile(r"\bADR (\d{4})\b")
#: un chemin : des mots, des points, des tirets et des « / », qui finit par une extension connue ou par « / »
PATH = re.compile(r"`([\w.][\w./-]*/[\w./-]*?(?:\.(?:py|md|json|ya?ml|html|cjs|js|ts|sh|toml|service|timer)|/))"
                  r"(?:::[^`]*)?`")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    """Le texte d'une section : de la ligne qui commence par ``start`` à celle qui commence par ``end``."""
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = next(i for i, line in enumerate(lines) if i > first and line.startswith(end))
    return "\n".join(lines[first:last])


def _entries() -> list[str]:
    return ENTRY.findall(_text(DECISIONS))


# ── les décisions ──

def test_the_decisions_are_numbered_without_gap_or_double():
    numbers = _entries()
    assert len(numbers) == len(set(numbers)), sorted(n for n in set(numbers) if numbers.count(n) > 1)
    assert sorted(numbers) == [f"{i:04d}" for i in range(1, int(max(numbers)) + 1)]


def test_every_decision_is_on_the_map_once():
    on_map = re.findall(r"\b\d{4}\b", _between(_text(DECISIONS), "## La carte", "## Le noyau"))
    assert sorted(on_map) == sorted(_entries())


def test_every_cited_adr_has_its_entry():
    known = set(_entries())
    sources = [*sorted(PACKAGE.rglob("*.py")), ROOT / "persona" / "voix.yaml", *DOCS]
    missing = {f"{n} ({path.relative_to(REPO)})" for path in sources for n in CITED.findall(_text(path))
               if n not in known}
    # « Révise 0034 », « Révisée par 0081 » : les renvois entre entrées
    for line in _text(DECISIONS).splitlines():
        if line.startswith("*") and ("Révis" in line or "Remplacée" in line):
            missing |= {f"{n} (decisions.md)" for n in re.findall(r"\b\d{4}\b", line) if n not in known}
    assert not missing, sorted(missing)


# ── les trames du chat ──

def _emitted() -> set[str]:
    """Les trames que le serveur du chat construit : chaque dict littéral qui porte un ``"type"``."""
    out: set[str] = set()
    for path in sorted((PACKAGE / "adapters" / "web").glob("*.py")):
        for node in ast.walk(ast.parse(_text(path))):
            if isinstance(node, ast.Dict):
                out |= {v.value for k, v in zip(node.keys, node.values, strict=True)
                        if isinstance(k, ast.Constant) and k.value == "type"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)}
    return out


def _read() -> set[str]:
    """Les trames que le serveur lit : les ``kind == "…"`` de ``_Session.dispatch``."""
    tree = ast.parse(_text(PACKAGE / "adapters" / "web" / "app.py"))
    dispatch = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "dispatch")
    return {c.comparators[0].value for c in ast.walk(dispatch)
            if isinstance(c, ast.Compare) and isinstance(c.left, ast.Name) and c.left.id == "kind"
            and isinstance(c.comparators[0], ast.Constant)}


def test_the_chat_frames_are_those_the_protocol_describes():
    doc = _text(CHAT)
    sent = set(re.findall(r"^\| `(\w+)` \|", _between(doc, "## 3.", "## 4."), re.M))
    served = set(re.findall(r"\*\*`(\w+)`\*\*", _between(doc, "## 4.", "## 5.")))
    assert sent == _read() - IGNORED, "protocole-chat.md § 3 contre ce que lit adapters/web/app.py"
    assert served == _emitted(), "protocole-chat.md § 4 contre ce qu'émet adapters/web/"


# ── la ligne de commande ──

class _Built(Exception):
    """L'analyseur est construit : on l'arrête avant qu'il lise quoi que ce soit."""


def _parser(monkeypatch: pytest.MonkeyPatch) -> argparse.ArgumentParser:
    caught: list[argparse.ArgumentParser] = []

    def grab(self: argparse.ArgumentParser, *_args: object, **_kwargs: object) -> None:
        caught.append(self)
        raise _Built

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", grab)
    with pytest.raises(_Built):
        cli.main([])
    return caught[0]


def _choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser | None]:
    """Ses sous-commandes : des sous-analyseurs, ou un premier argument à choix (``mika sim selftest|run|sonde``)."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    first = next((a for a in parser._actions if not a.option_strings and a.choices), None)
    return dict.fromkeys(first.choices) if first is not None else {}


def _documented() -> dict[str, set[str] | None]:
    """La table « Toutes les sous-commandes » : chaque commande, et ses sous-commandes quand la table les énumère."""
    table = _between(_text(ARCHITECTURE), "Toutes les sous-commandes", "Codes de sortie")
    out: dict[str, set[str] | None] = {}
    for row in (line for line in table.splitlines() if line.startswith("| `")):
        for token in re.findall(r"`([^`]+)`", row.split(" | ")[0]):
            words = token.replace("\\|", "|").split()
            if words[0].startswith("-"):
                continue  # une option (« --client screen|mobile »), pas une commande
            subs = words[1] if len(words) > 1 and not words[1].startswith(("-", "<", "[")) else None
            out[words[0]] = set(subs.split("|")) if subs else None
    return out


def test_the_cli_table_names_every_command_and_only_those(monkeypatch):
    real = _choices(_parser(monkeypatch))
    documented = _documented()
    assert set(documented) == set(real), "ARCHITECTURE.md › Commandes contre app/cli.py"
    for command, subs in documented.items():
        if subs is None:
            continue
        parser = real[command]
        actual = set(_choices(parser)) if parser is not None else set()
        if len(subs) > 1:
            assert subs == actual, f"mika {command}"
        else:
            assert subs <= actual, f"mika {command}"


# ── les chemins ──

def test_every_cited_path_exists():
    missing = []
    for doc in DOCS:
        for cited in PATH.findall(_text(doc)):
            if not any((base / cited).exists() for base in (doc.parent, *BASES)):
                missing.append(f"{doc.relative_to(REPO)} : {cited}")
    assert not missing, missing
