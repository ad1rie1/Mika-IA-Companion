"""Une politique : les facultés et les plugins lisent le journal par le
contexte d'inspection, jamais par le schéma du magasin.

Une vue d'inspection qui relit des événements passe par ``ctx.events`` (les
événements décodés, contenus résolus) et ``ctx.tally`` (un décompte par champ).
Écrire du SQL sur la table du journal couplait chaque faculté au schéma de
l'adaptateur SQLite : un nom de table, des colonnes, un chemin JSON, et des
charges utiles relues à la main plutôt que typées. Lire ses propres
projections par ``query_mind`` reste permis : c'est le journal qui ne l'est pas.

Le contrôle porte sur les chaînes du code (``ast``), jamais sur le texte du
fichier : les commentaires nomment justement ce qu'il ne faut pas faire.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (ROOT / "src" / "mika" / "faculties", ROOT / "src" / "mika" / "plugins")
JOURNAL = "events"
FROM_JOURNAL = re.compile(rf"\bfrom\s+{JOURNAL}\b", re.IGNORECASE)


def _modules() -> list[Path]:
    return sorted(p for package in PACKAGES for p in package.rglob("*.py") if "__pycache__" not in p.parts)


def _strings(path: Path) -> Iterator[tuple[int, str]]:
    """Chaque chaîne du module (y compris les morceaux fixes d'une f-string)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _offences(path: Path) -> list[str]:
    where = path.relative_to(ROOT)
    return [f"{where}:{line} : {value[:80]!r}" for line, value in _strings(path)
            if value == JOURNAL or FROM_JOURNAL.search(value)]


def test_the_policy_sees_every_view_module():
    names = {p.relative_to(ROOT).as_posix() for p in _modules()}
    assert "src/mika/faculties/goals/inspect.py" in names
    assert "src/mika/plugins/forge/__init__.py" in names


def test_no_faculty_or_plugin_reads_the_journal_table():
    offences = [o for path in _modules() for o in _offences(path)]
    assert offences == [], ("lire le journal par ctx.events / ctx.tally, jamais par sa table :\n"
                            + "\n".join(offences))


def test_the_policy_catches_what_it_forbids(tmp_path):
    """Non vide : les deux formes qu'elle interdit sont bien vues."""
    sample = tmp_path / "vue.py"
    sample.write_text('TABLE = "events"\n'
                      'def lire(store, t):\n'
                      '    return store.query_mind(f"SELECT seq FROM {TABLE} WHERE type=?", (t,)), \\\n'
                      '        store.query_mind("select data from events where type=?", (t,))\n'
                      '# un commentaire qui dit FROM events ne compte pas\n',
                      encoding="utf-8")
    lines = sorted(line for line, value in _strings(sample) if value == JOURNAL or FROM_JOURNAL.search(value))
    assert lines == [1, 4]
