"""Ses phrases vivent dans ``persona/voix.yaml`` (ADR 0071) : pas de nouvelle prose écrite en dur.

Une heuristique cherche, dans le code des facultés et des greffons, les chaînes qui ressemblent à de la prose
française (au moins cinq mots, des mots-outils du français). Elle ignore ce qui n'est pas pour elle : les
docstrings, les journaux techniques, les exceptions de programmation, les libellés des réglages (``Knob``), les
raisons d'humeur (des codes gardés au journal), les expressions régulières et les vues de console (``inspect.py``,
``inspect_<sujet>.py``, un paquet ``inspect/``). Tout le greffon Teams est compté depuis le 2026-11-15 : ses consignes
de tâche, la description de son lot et la raison d'une échéance sont dans la voix (audit du 2026-11-05, K8-05) ; ce
que rendent ses outils (``tools.py``) reste à migrer, sous plafond.

Ce qui reste a été trié pendant la migration : des textes de la console de l'opératrice, des valeurs gardées au
journal, des listes de mots, un serveur autonome (``plugins/web/server.py``) qui ne peut pas lire la voix. Le
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
SKIPPED_FILES = re.compile(r"(^|/)((inspect(_\w+)?|actions|params|reglages)\.py$|inspect/)")
NOT_FOR_HER = {"debug", "info", "warning", "error", "exception", "critical", "log", "ValueError", "TypeError",
               "RuntimeError", "KeyError", "AssertionError", "Knob", "Setting", "Action", "Panel", "Row", "Column",
               "Appraisal", "compile"}
WORD = re.compile(r"[A-Za-zÀ-ÿ']+")
FRENCH = re.compile(r"\b(tu|te|ta|ton|tes|elle|la|le|les|de|des|du|un|une|et|est|pas|ne|qui|que|à|ce|sa|son|ses)\b",
                    re.I)

#: ce qui restait le 2026-10-06, trié (console, journal, listes de mots, serveur autonome) — ne peut que baisser,
#: et le test l'exige : un compte sous son plafond fait baisser le plafond (2026-10-26)
CEILING = {
    "faculties/goals/tend.py": 3,  # raisons de clôture, gardées au journal
    "faculties/goals/tools.py": 1,  # aperçu d'une capacité (console)
    "faculties/identity/detection.py": 2,  # listes de mots (détecteur)
    # liste de mots (``FRAMING`` : les tournures d'un récit sans nom, ADR 0092), pas une phrase ; venue de
    # ``vocab/retelling.py`` le 2026-11-13, qu'un seul propriétaire lisait (audit du 2026-11-05, K0-23)
    "faculties/memory/retelling.py": 1,
    # résumés d'effets que l'opératrice approuve ; +9 le 2026-11-05 : l'aperçu d'un envoi au dépôt distant et d'une
    # récupération (``REMOTE`` : où, quel commit, ce qui partira ou arrivera), lu par l'opératrice dans « À valider »
    # avant son accord, pas par elle (audit du 2026-11-05, C1-07) ; −1 le 2026-11-26 : le refus d'un effet pour un
    # projet archivé part avec ``_gone`` (``project_refusal``) dans ``capability_common.py`` (audit d'organisation, C1)
    "faculties/projects/atelier.py": 21,
    # le refus d'un effet pour un projet archivé, lu dans « À valider » (console) ; venu d'``atelier.py`` le
    # 2026-11-26 avec ``_gone`` (audit d'organisation, C1)
    "faculties/projects/capability_common.py": 1,
    # règle de project_steer (console) ; +1 le 2026-10-25 : la description de la capacité projects.steer, piloter sur
    # ton accord (console, ADR 0133) — venues de tools.py avec le pilotage (audit du 2026-11-05, K5-03)
    # la règle de project_milestone (console : la page « Droits » la lit sur l'outil, comme celle de project_steer),
    # ADR 0273
    "faculties/projects/milestones_tools.py": 1,
    "faculties/projects/steer.py": 2,
    "faculties/projects/tend.py": 4,  # raisons de pause (pannes, cadrage sans plan), gardées au journal
    "faculties/projects/tools.py": 2,  # raisons de clôture, gardées au journal
    # les règles de project_items et de project_item (console : la page « Droits » les lit sur l'outil, comme celle
    # de project_steer), ADR 0268 ; venues de ``tracker.py`` le 2026-11-26 avec les outils du registre (audit
    # d'organisation, C3)
    "faculties/projects/tracker_tools.py": 2,
    "plugins/email/tools.py": 2,  # capacité et résumé (console)
    # capacité d'installation (console) ; venue de ``plugins/forge/__init__.py`` le 2026-11-15, avec la version qui
    # attend un accord (audit du 2026-11-05, K8-04)
    "plugins/forge/install.py": 4,
    # les erreurs de validation d'une vue forgée, chemin JSON compris (la note « Vue invalide » de la console,
    # forge_test), pas sa voix ; venues de ``kernel/envelope.py`` le 2026-11-14 (audit du 2026-11-05, K1-01)
    "plugins/forge/envelope.py": 43,
    # mode d'emploi de forge_help (exemples de code) — à migrer ; +2 le 2026-10-12 : le manifeste et le code de
    # l'exemple de veille (ADR 0104), du code qu'un test exécute, pas une phrase qu'elle lit (son texte est dans
    # la voix, forge.guide.veille)
    "plugins/forge/guide.py": 11,
    "plugins/forge/views.py": 6,  # rendus de console, aussi lus par forge_test — à migrer
    "plugins/forge/calls.py": 1,  # capacité forge.call (console, ADR 0133)
    # la règle de draw, ce que le gestionnaire revérifie (console, « vérifié à l'exécution » ; ADR 0148)
    "plugins/imaging/tools.py": 1,
    "plugins/mcp/__init__.py": 1,  # aperçu d'une capacité (console)
    "plugins/mcp/calls.py": 4,  # capacité et résumé (console)
    # ce que ses outils Teams rendent au modèle (refus, résultats) et l'aperçu d'un envoi (console) — à migrer ; les
    # descriptions des trois outils et de leurs arguments sont dans la voix depuis le 2026-11-13 (audit du
    # 2026-11-05, LR2) ; −2 le 2026-11-15 : le sort « brouillon » de teams_draft lit teams.task.fate.brouillon
    # (un f-string compte deux fois : lui et son morceau de texte ; K8-05)
    "plugins/teams/tools.py": 20,
    "plugins/wakeup/prompt.py": 6,  # « pourquoi pas maintenant » (console)
    "plugins/web/server.py": 30,  # serveur autonome dans sa cage : il ne peut pas lire la voix
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
    grew, shrank = [], []
    for root in ROOTS:
        for path in sorted((SRC / root).rglob("*.py")):
            rel = str(path.relative_to(SRC))
            if SKIPPED_FILES.search(rel):
                continue
            found = prose_in(path)
            ceiling = CEILING.get(rel, 0)
            if len(found) > ceiling:
                sample = "; ".join(f"l.{line} « {text[:60]} »" for line, text in found[:3])
                grew.append(f"{rel} : {len(found)} chaînes (plafond {ceiling}) — {sample}")
            elif len(found) < ceiling:
                # le plafond « ne peut que baisser » : quand une phrase migre, on le baisse ici — sinon il resterait
                # une marge où de la prose neuve passerait sans bruit (audit du 2026-10-26)
                shrank.append(f"{rel} : {len(found)} chaînes pour un plafond de {ceiling} — baisse-le")
    assert not grew, ("De la prose écrite en dur : une phrase qu'elle lit va dans persona/voix.yaml (ADR 0071), un "
                      "texte de console dans un fichier de console.\n" + "\n".join(grew))
    assert not shrank, "Des plafonds trop hauts (de la prose a migré) :\n" + "\n".join(shrank)


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


def test_console_views_are_named_inspect() -> None:
    """Les vues de console d'une faculté ou d'un plugin s'appellent ``inspect`` (``inspect.py``, ``inspect_<sujet>.py``,
    un paquet ``inspect/``), jamais ``console`` : un seul nom pour une même notion, celui que ``SKIPPED_FILES``
    reconnaît (audit du 2026-11-05, K11-14)."""
    named = sorted(str(p.relative_to(SRC)) for root in ROOTS for p in (SRC / root).rglob("console*")
                   if "__pycache__" not in p.parts)
    assert not named, "des vues de console sous un autre nom que inspect (ARCHITECTURE.md, « Écrire une faculté ») : " \
                      + ", ".join(named)


#: ce qu'un propriétaire déclare pour la console : vues, fiches et leur recherche, documents, actions, droits,
#: vitaux, courbes
CONSOLE_DECORATORS = frozenset({"inspect", "subject", "search", "download", "action", "rights", "vital", "series"})
CONSOLE_FILES = re.compile(r"(^|/)(inspect(_\w+)?\.py$|inspect/)")


def test_console_declarations_live_in_inspect() -> None:
    """Ce qu'un propriétaire montre à la console se déclare dans ses fichiers ``inspect`` ; ses actions aussi, ou à
    part dans ``actions.py`` — sans exception (ARCHITECTURE.md, « Écrire une faculté », point 3 ; audit du
    2026-11-05, K11-14 : le fil de transcript déclarait encore quatre vues dans son ``__init__.py``, à côté de son
    ``inspect.py`` ; K8-10 : presence, camera, rss et sensors, qui tenaient en un fichier, gardaient la leur dans
    leur ``__init__.py``)."""
    astray = []
    for root in ROOTS:
        for path in sorted((SRC / root).rglob("*.py")):
            rel = str(path.relative_to(SRC))
            if "__pycache__" in path.parts or CONSOLE_FILES.search(rel):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                for deco in getattr(node, "decorator_list", ()):
                    f = deco.func if isinstance(deco, ast.Call) else deco
                    if not (isinstance(f, ast.Attribute) and f.attr in CONSOLE_DECORATORS):
                        continue
                    if f.attr == "action" and path.name == "actions.py":
                        continue
                    astray.append(f"{rel}:{deco.lineno} @{ast.unparse(f)}")
    assert not astray, "de la console déclarée hors de ses fichiers inspect (ARCHITECTURE.md, « Écrire une " \
                       "faculté », point 3) : " + ", ".join(astray)
