"""Ses phrases vivent dans ``persona/voix.yaml`` (ADR 0071) : pas de nouvelle prose écrite en dur.

Une heuristique cherche, dans le code des facultés et des greffons, les chaînes qui ressemblent à de la prose
française (au moins cinq mots, des mots-outils du français). Elle ignore ce qui n'est pas pour elle : les
docstrings, les journaux techniques, les exceptions de programmation, les libellés des réglages (``Knob``), les
raisons d'humeur (des codes gardés au journal), les expressions régulières, les fichiers de console et le greffon
Teams (une autre session y travaille).

Ce qui reste a été trié pendant la migration : des textes de la console de l'opératrice, des valeurs gardées au
journal, des listes de mots, un serveur autonome (``plugins/web/serveur.py``) qui ne peut pas lire la voix. Le
plafond ci-dessous en fixe le nombre **par fichier** : il ne peut que baisser. Une phrase nouvelle qu'elle lit va
dans ``voix.yaml`` ; un texte de console va dans un fichier de console — ou, s'il faut vraiment, on relève le plafond
ici en disant pourquoi.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"
ROOTS = ("faculties", "plugins")
SKIPPED_FILES = re.compile(r"(^|/)((inspect|actions|console[^/]*|params|knobs|reglages)\.py$|console/|teams/)")
NOT_FOR_HER = {"debug", "info", "warning", "error", "exception", "critical", "log", "ValueError", "TypeError",
               "RuntimeError", "KeyError", "AssertionError", "Knob", "Setting", "Action", "Panel", "Row", "Column",
               "Appraisal", "compile"}
WORD = re.compile(r"[A-Za-zÀ-ÿ']+")
FRENCH = re.compile(r"\b(tu|te|ta|ton|tes|elle|la|le|les|de|des|du|un|une|et|est|pas|ne|qui|que|à|ce|sa|son|ses)\b",
                    re.I)

#: ce qui restait le 2026-10-06, trié (console, journal, listes de mots, serveur autonome) — ne peut que baisser
CEILING = {
    "faculties/goals/tend.py": 3,  # raisons de clôture, gardées au journal
    "faculties/goals/tools.py": 1,  # aperçu d'une capacité (console)
    "faculties/goals/work.py": 6,  # « pourquoi pas maintenant » (console)
    "faculties/identity/detection.py": 2,  # listes de mots (détecteur)
    "faculties/presence/__init__.py": 2,  # panneau de console
    "faculties/projects/atelier.py": 13,  # résumés d'effets que l'opératrice approuve
    "faculties/projects/tend.py": 2,  # raison de pause, gardée au journal
    "faculties/projects/tools.py": 2,  # raisons de clôture, gardées au journal
    "faculties/projects/work.py": 8,  # « pourquoi pas maintenant » (console)
    "faculties/transcript/__init__.py": 10,  # inspection du fil (console)
    "faculties/world/commands.py": 13,  # refus adressés aux clients du monde, pas à elle
    "plugins/camera/__init__.py": 10,  # panneaux de console
    "plugins/email/tools.py": 2,  # capacité et résumé (console)
    "plugins/forge/__init__.py": 5,  # capacité d'installation (console)
    "plugins/forge/guide.py": 9,  # mode d'emploi de forge_help (exemples de code) — à migrer
    "plugins/forge/views.py": 6,  # rendus de console, aussi lus par forge_test — à migrer
    "plugins/mcp/__init__.py": 2,  # aperçu d'une capacité (console)
    "plugins/mcp/calls.py": 5,  # capacité et résumé (console)
    "plugins/rss/__init__.py": 16,  # panneaux de console
    "plugins/sensors/__init__.py": 6,  # panneaux de console
    "plugins/wakeup/prompt.py": 6,  # « pourquoi pas maintenant » (console)
    "plugins/web/__init__.py": 1,  # aperçu d'une capacité (console)
    "plugins/web/serveur.py": 30,  # serveur autonome dans sa cage : il ne peut pas lire la voix
}


def _skipped_nodes(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name in NOT_FOR_HER:
                out |= {id(sub) for sub in ast.walk(node)}
    return out


def _prose(text: str) -> bool:
    if "(?" in text or "\\b" in text or text.startswith("|"):
        return False  # une expression régulière : un détecteur, pas une phrase
    return len(text) >= 25 and len(WORD.findall(text)) >= 5 and len(FRENCH.findall(text)) >= 2


def prose_in(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _skipped_nodes(tree)
    found = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _prose(node.value):
            found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if _prose(text):
                found.append((node.lineno, text))
    return found


def test_no_new_prose_outside_her_voice() -> None:
    grew = []
    for root in ROOTS:
        for path in sorted((SRC / root).rglob("*.py")):
            rel = str(path.relative_to(SRC))
            if SKIPPED_FILES.search(rel):
                continue
            found = prose_in(path)
            if len(found) > CEILING.get(rel, 0):
                sample = "; ".join(f"l.{line} « {text[:60]} »" for line, text in found[:3])
                grew.append(f"{rel} : {len(found)} chaînes (plafond {CEILING.get(rel, 0)}) — {sample}")
    assert not grew, ("De la prose écrite en dur : une phrase qu'elle lit va dans persona/voix.yaml (ADR 0071), un "
                      "texte de console dans un fichier de console.\n" + "\n".join(grew))


def test_the_ceiling_names_real_files() -> None:
    missing = [rel for rel in CEILING if not (SRC / rel).is_file()]
    assert not missing, f"plafonds pour des fichiers disparus : {missing}"


def test_the_detector_sees_a_sentence() -> None:
    """L'heuristique n'est pas vide : une consigne écrite en dur est vue, un détecteur ne l'est pas."""
    code = 'def f():\n    """Doc."""\n    return "Tu écris ton journal intime, à la première personne, ce soir."\n'
    tree = ast.parse(code)
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in _skipped_nodes(tree) and _prose(n.value)]
    assert not _prose(r"(?:tu es|t es) (?:vraiment|trop) (?:nulle|bete)")


def test_her_voice_is_one_file() -> None:
    """Les fragments de la migration sont fusionnés : un seul fichier, aucun dossier ``voix.d``."""
    persona = SRC.parents[1] / "persona"
    assert (persona / "voix.yaml").is_file()
    assert not (persona / "voix.d").exists(), "persona/voix.d : fusionner ses fragments dans voix.yaml (ADR 0071)"
