"""Une politique : hors de la mémoire, on ne lit ce qu'elle sait que par sa porte (ADR 0078).

Les tables de la mémoire (``memory_items``, ``memory_about``, ``memory_told``…) sont à elle. Les autres facultés,
les plugins, l'application, la console et le simulateur lisent les **vues** que ``contracts.memory`` nomme
(``KNOWLEDGE_VIEW``…) et passent chaque ligne par le verdict commun (``vocab.knowledge`` → ``vocab.lineage.admits``).
Avant, une douzaine de lecteurs refaisaient chacun leur filtre sur la table brute, et plusieurs fuyaient (audit du
2026-10-09). Ce qu'elle a cru et ne croit plus (``FORMER_VIEW``) et le grand livre (``LEDGER_VIEW``, tout, statut
compris) ne sont pas pour les facultés : seule la pensée d'une révision a besoin de l'ancienne croyance.

**Ses tables**, ce sont toutes celles qu'elle déclare : chaque constante ``*_TABLE`` de ``contracts/memory.py`` et de
``faculties/memory/tables.py``, lues dans leur arbre (la garde n'importe pas ce qu'elle interdit), sauf
``memory_chunks``, publique exprès (``contracts.memory.chunks_table`` : la console relit les échanges). Une table
neuve est donc gardée dès qu'elle est déclarée, et une table déclarée sans constante fait échouer la garde. Hors
d'elle, on n'importe pas non plus le module qui les déclare (``tables``) ni celui qui les écrit (``projections``) :
``tb.items()`` n'est ni un nom de table, ni un texte SQL.

Le contrôle porte sur l'arbre du code (``ast``) — les noms et les chaînes, docstrings exceptées —, jamais sur le
texte du fichier : les commentaires nomment justement ce qu'il ne faut pas faire. Chaque contrôle s'éprouve dans les
deux sens, sur un arbre factice (``test_each_check_fails_on_a_fake_offence``).
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "mika"
#: ce qui appartient à la mémoire : ses tables y sont chez elles
OWNERS = (SRC / "faculties" / "memory", SRC / "contracts" / "memory.py")
#: où elle déclare le nom de ses tables
CONTRACT = SRC / "contracts" / "memory.py"
TABLES = SRC / "faculties" / "memory" / "tables.py"
#: publique exprès : les échanges bruts, que la console relit (``contracts.memory.chunks_table``)
PUBLIC_TABLES = frozenset({"CHUNKS_TABLE"})
#: les modules qui déclarent ses tables et qui les écrivent : hors d'elle, on ne les importe pas
WRITERS = ("mika.faculties.memory.tables", "mika.faculties.memory.projections")


def _constants(path: Path) -> dict[str, str]:
    """Les constantes de tête du module qui valent une chaîne (``ITEMS_TABLE = "memory_items"``), lues dans son
    arbre."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out |= {t.id: node.value.value for t in node.targets if isinstance(t, ast.Name)}
    return out


def _her_tables(*paths: Path) -> dict[str, str]:
    """Ses tables privées, constante → nom : chaque ``*_TABLE`` de ces modules, sauf la publique."""
    declared = {k: v for p in paths for k, v in _constants(p).items()}
    return {n: v for n, v in declared.items() if n.endswith("_TABLE") and n not in PUBLIC_TABLES}


def _any_of(words: Iterable[str]) -> re.Pattern[str]:
    """L'un de ces mots entiers, le plus long d'abord (``memory_told_lines`` avant ``memory_told``)."""
    return re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)) + r")\b")


_DECLARED = {**_constants(CONTRACT), **_constants(TABLES)}
#: ses tables privées, par leur constante (au contrat ou dans ``tables.py``) : toutes celles qu'elle déclare, sauf la
#: publique — comme noms (``c.LIFE_TABLE``) et comme texte SQL (``"… FROM memory_life"``)
HER_TABLES = _her_tables(CONTRACT, TABLES)
TABLE_NAMES = frozenset(HER_TABLES)
TABLE_TEXT = _any_of(HER_TABLES.values())
#: ce que les facultés et les plugins ne lisent pas (sauf la raison nommée) : par leur nom, leur texte en clair
#: (``"… FROM memory_ledger"``), ou les colonnes déclarées pour les lire par des requêtes (``FORMER``, ``LEDGER``,
#: ADR 0101)
BEHIND = frozenset({"LEDGER_VIEW", "FORMER_VIEW", "FORMER", "LEDGER"})
BEHIND_TEXT = _any_of(_DECLARED[n] for n in ("LEDGER_VIEW", "FORMER_VIEW"))
ALLOWED_BEHIND = {
    # la pensée d'une croyance révisée cite l'ancienne et la nouvelle (sous la filiation des deux)
    (SRC / "faculties" / "attention" / "watch.py", "FORMER"),
}


def _modules(*roots: Path) -> list[Path]:
    return sorted(p for r in roots for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def _owned(path: Path) -> bool:
    return any(path == o or o in path.parents for o in OWNERS)


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _uses(path: Path) -> Iterator[tuple[int, str]]:
    """Chaque nom d'attribut et chaque chaîne du module (morceaux fixes des f-strings compris, docstrings non)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docs = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _writer(name: str) -> bool:
    return any(name == w or name.startswith(f"{w}.") for w in WRITERS)


def _imports_her_writers(path: Path) -> Iterator[tuple[int, str]]:
    """Chaque endroit du module qui atteint ``tables`` ou ``projections`` : un import (``from mika.faculties.memory
    import tables``…), un attribut d'un module importé (``memory.tables.items()``), ou son nom en clair
    (``importlib.import_module("mika.faculties.memory.tables")``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    alias: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                alias[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                if _writer(a.name):
                    yield node.lineno, a.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                full = f"{node.module}.{a.name}"
                alias[a.asname or a.name] = full
                if _writer(full) or _writer(node.module):
                    yield node.lineno, full

    def resolved(expr: ast.AST) -> str:
        head, _, rest = (_dotted(expr) or "").partition(".")
        full = alias.get(head, head)
        return f"{full}.{rest}" if rest else full

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # seulement là où l'on entre dans le module (``memory.tables``), pas chacun de ses noms ensuite
            if _writer(resolved(node)) and not _writer(resolved(node.value)):
                yield node.lineno, resolved(node)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _writer(node.value):
            yield node.lineno, node.value


_SYSTEM_TAB = SRC / "app" / "handmade" / "tabs" / "system.py"
#: nomme cinq de ses tables pour les étiqueter dans la console (« Ses souvenirs et ses croyances », « Ses lectures »…),
#: sans en lire une ligne : ces noms seulement, le reste du module (il lit le journal en SQL) reste sous le contrôle
LABELS_ONLY = frozenset({(_SYSTEM_TAB, "memory_items"), (_SYSTEM_TAB, "memory_told"), (_SYSTEM_TAB, "memory_life"),
                         (_SYSTEM_TAB, "memory_readings"), (_SYSTEM_TAB, "memory_extraction_queue")})


def _reads_her_tables(path: Path, used: str) -> bool:
    return bool(used in TABLE_NAMES or TABLE_TEXT.search(used)) and (path, used) not in LABELS_ONLY


def _reads_behind(path: Path, used: str) -> bool:
    return bool(used in BEHIND or BEHIND_TEXT.search(used)) and (path, used) not in ALLOWED_BEHIND


def test_every_table_she_declares_is_named():
    """La garde connaît ses tables par leurs constantes : chaque table que la mémoire déclare (un ``projection_table``)
    l'est dans ``tables.py`` ou au contrat, prend son nom d'une constante ``*_TABLE``, et chaque constante nomme une
    table déclarée. Une table déclarée ailleurs, ou nommée en clair, passerait sous la garde ; une constante de trop la
    ferait mentir."""
    elsewhere = [f"{p.relative_to(ROOT)}:{n.lineno}" for p in _modules(OWNERS[0]) if p not in (CONTRACT, TABLES)
                 for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"), filename=str(p)))
                 if isinstance(n, ast.Call) and (_dotted(n.func) or "").rpartition(".")[2] == "projection_table"]
    assert elsewhere == [], ("une table de la mémoire se déclare dans faculties/memory/tables.py (au contrat si elle "
                             "est publique), sous une constante ``*_TABLE`` que cette garde lit :\n"
                             + "\n".join(elsewhere))
    constants = set(_her_tables(CONTRACT, TABLES)) | PUBLIC_TABLES
    declared, unnamed = [], []
    for path in (CONTRACT, TABLES):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and _dotted(n.func) == "projection_table"]
            if not calls:
                continue
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            used = sorted(names & constants)
            if len(used) != 1:
                unnamed.append(f"{path.relative_to(ROOT)}:{fn.lineno} {fn.name} ({', '.join(used) or 'aucune'})")
            declared += used
    assert unnamed == [], ("chaque table de la mémoire prend son nom d'une seule constante ``*_TABLE`` (au contrat ou "
                           "dans tables.py), que cette garde lit : déclare-la, et nomme la table par elle :\n"
                           + "\n".join(unnamed))
    assert sorted(declared) == sorted(constants), (
        "une constante ``*_TABLE`` de la mémoire ne nomme aucune table déclarée, ou deux tables la partagent : "
        f"{sorted(constants ^ set(declared))}")


def test_no_one_reads_her_tables_behind_her_back():
    offences = []
    for path in _modules(SRC):
        if _owned(path):
            continue
        for line, used in _uses(path):
            if _reads_her_tables(path, used):
                offences.append(f"{path.relative_to(ROOT)}:{line} lit {used!r}")
    assert offences == [], ("hors de la mémoire, on lit ses vues (contracts.memory : KNOWLEDGE, select_known, "
                            "concerning…), jamais ses tables ; un libellé de la console qui nomme une table sans la "
                            "lire s'excuse nommément dans LABELS_ONLY :\n" + "\n".join(offences))


def test_her_writers_stay_hers():
    """Hors de la mémoire, aucun module n'importe ``tables.py`` ni ``projections.py`` : ``tb.items()`` lirait la
    table brute sans en dire le nom. ``lint-imports`` l'interdit déjà aux facultés et aux plugins ; ceci le dit aussi
    d'``app``, de la console et du simulateur."""
    offences = []
    for path in _modules(SRC):
        if _owned(path):
            continue
        offences += [f"{path.relative_to(ROOT)}:{line} atteint {name}" for line, name in _imports_her_writers(path)]
    assert offences == [], ("hors de la mémoire, on lit sa porte (les vues de contracts.memory), jamais ses tables "
                            "par le module qui les déclare ou les écrit : ce qu'il faut d'une ligne s'ajoute à une vue "
                            "de la porte, ou passe par un module public de la faculté (recall, inspect…) :\n"
                            + "\n".join(offences))


def test_a_label_is_excused_not_its_whole_module():
    """L'exception porte sur une étiquette de ce module, jamais sur le module : une vraie lecture y serait vue."""
    assert not _reads_her_tables(_SYSTEM_TAB, "memory_items")
    assert not _reads_her_tables(_SYSTEM_TAB, "memory_life")
    assert _reads_her_tables(_SYSTEM_TAB, "memory_about")
    assert _reads_her_tables(_SYSTEM_TAB, "ITEMS_TABLE")
    assert _reads_her_tables(_SYSTEM_TAB, "SELECT text FROM memory_items")
    assert _reads_her_tables(_SYSTEM_TAB, "SELECT payload FROM memory_life")
    assert _reads_her_tables(SRC / "app" / "handmade" / "home.py", "memory_items")
    used = {name for _, name in _uses(_SYSTEM_TAB)}
    assert {name for _, name in LABELS_ONLY} <= used  # une étiquette retirée : son exception part avec elle


def test_faculties_and_plugins_read_what_she_still_holds():
    offences = []
    for path in _modules(SRC / "faculties", SRC / "plugins"):
        if _owned(path):
            continue
        for line, used in _uses(path):
            if _reads_behind(path, used):
                offences.append(f"{path.relative_to(ROOT)}:{line} lit {used!r}")
    assert offences == [], ("une faculté lit ce qu'elle tient pour sien (KNOWLEDGE_VIEW, select_known) ; le grand "
                            "livre et ce qu'elle ne croit plus sont à la console et à la seule raison nommée dans "
                            "ALLOWED_BEHIND :\n" + "\n".join(offences))


def test_the_check_sees_a_raw_read():
    """Le contrôle n'est pas vide : une lecture brute, sous forme de constante ou de texte SQL, est vue."""
    probe = ast.parse('rows = q(f"SELECT text FROM {memory_c.ITEMS_TABLE}")\nq("SELECT 1 FROM memory_about")')
    attrs = {n.attr for n in ast.walk(probe) if isinstance(n, ast.Attribute)}
    texts = [n.value for n in ast.walk(probe) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert attrs & TABLE_NAMES and any(TABLE_TEXT.search(t) for t in texts)
    assert not TABLE_TEXT.search("SELECT item FROM memory_knowledge_about")  # la vue, elle, est permise
    assert not TABLE_TEXT.search("SELECT id FROM memory_chunks")  # publique exprès


#: une lecture brute de chacune des tables que la garde ne voyait pas avant le 2026-11-26 (audit de la mémoire, M3),
#: par son texte et par sa constante ; puis les autres constantes qui lui manquaient
_FORGOTTEN = (("memory_life", "LIFE_TABLE"), ("memory_feelings", "FEELINGS_TABLE"),
              ("memory_readings", "READINGS_TABLE"), ("memory_extraction_queue", "DEFERRED_TABLE"))
_UNNAMED = ("REFS_TABLE", "TESTIMONIES_TABLE", "CONTESTS_TABLE", "CHANGES_TABLE")


def test_each_check_fails_on_a_fake_offence(tmp_path, monkeypatch):
    """Chaque contrôle s'éprouve dans les deux sens, sur un arbre factice : un module propre passe ; une lecture
    brute — d'une table par son texte ou sa constante, de ``tables.py`` ou ``projections.py`` importé depuis ``app``,
    du grand livre en clair depuis une faculté — le fait échouer, et le message la nomme ; la même chose dans la
    mémoire même passe."""
    fake = tmp_path / "src" / "mika"
    here = sys.modules[__name__]
    monkeypatch.setattr(here, "ROOT", tmp_path)
    monkeypatch.setattr(here, "SRC", fake)
    monkeypatch.setattr(here, "OWNERS", (fake / "faculties" / "memory", fake / "contracts" / "memory.py"))
    app, faculty = fake / "app" / "probe.py", fake / "faculties" / "probe" / "x.py"
    owned, plugin = fake / "faculties" / "memory" / "x.py", fake / "plugins" / "probe" / "x.py"
    for p in (app, faculty, owned, plugin):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")

    def passes(text: str, where: Path = app) -> None:
        where.write_text(text, encoding="utf-8")
        test_no_one_reads_her_tables_behind_her_back()
        test_her_writers_stay_hers()
        test_faculties_and_plugins_read_what_she_still_holds()
        where.write_text("", encoding="utf-8")

    def fails(check, text: str, said: str, where: Path = app) -> None:
        where.write_text(text, encoding="utf-8")
        with pytest.raises(AssertionError, match=re.escape(said)):
            check()
        where.write_text("", encoding="utf-8")

    # ce qui est permis : sa porte, un module public de la faculté, et tout, chez elle
    passes("from mika.contracts import memory as memory_c\n"
           "from mika.faculties.memory import recall\n"
           'rows = q(f"SELECT item FROM {memory_c.KNOWLEDGE_ABOUT_VIEW}")\nq("SELECT id FROM memory_chunks")\n')
    passes("from mika.faculties.memory import tables as tb\nfrom mika.faculties.memory.projections import Items\n"
           'q("SELECT payload FROM memory_life")\nq(f"SELECT * FROM {LEDGER_VIEW}")\n', owned)
    passes("from mika.contracts import memory as memory_c\nrows = q(memory_c.select_known())\n", faculty)

    for text, constant in _FORGOTTEN:
        fails(test_no_one_reads_her_tables_behind_her_back, f'q("SELECT * FROM {text} WHERE id = 1")', text)
        fails(test_no_one_reads_her_tables_behind_her_back, f'q(f"SELECT * FROM {{memory_c.{constant}}}")', constant)
    for constant in _UNNAMED:
        fails(test_no_one_reads_her_tables_behind_her_back, f"t = {constant}", constant)
    for text in ("from mika.faculties.memory import tables as tb\nrows = tb.items()",
                 "from mika.faculties.memory.tables import items",
                 "import mika.faculties.memory.tables",
                 "from mika.faculties.memory.projections import ITEM_COLUMNS",
                 "from mika.faculties import memory\nrows = memory.tables.items()",
                 'import importlib\ntb = importlib.import_module("mika.faculties.memory.tables")'):
        fails(test_her_writers_stay_hers, text, "mika.faculties.memory.", app)
    for text, said in (('q("SELECT * FROM memory_ledger")', "memory_ledger"),
                       ('q("SELECT * FROM memory_former WHERE id = 1")', "memory_former"),
                       ("rows = q(memory_c.select_known(memory_c.LEDGER))", "'LEDGER'")):
        fails(test_faculties_and_plugins_read_what_she_still_holds, text, said, faculty)

    # ses tables, telles qu'elle les déclare : chacune par sa constante, chaque constante pour une table
    contract, tables = fake / "contracts" / "memory.py", fake / "faculties" / "memory" / "tables.py"
    contract.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(here, "CONTRACT", contract)
    monkeypatch.setattr(here, "TABLES", tables)
    contract.write_text('CHUNKS_TABLE = "memory_chunks"\n\n\ndef chunks_table(sfx=""):\n'
                        '    return projection_table(f"{CHUNKS_TABLE}{sfx}")\n', encoding="utf-8")
    named = ('from mika.contracts import memory as c\nA_TABLE = "memory_a"\n\n\ndef a(sfx=""):\n'
             '    return projection_table(f"{A_TABLE}{sfx}")\n\n\ndef b(sfx=""):\n'
             '    name = f"{c.B_TABLE}{sfx}"\n    return projection_table(name)\n')
    contract.write_text(contract.read_text(encoding="utf-8") + 'B_TABLE = "memory_b"\n', encoding="utf-8")
    tables.write_text(named, encoding="utf-8")
    test_every_table_she_declares_is_named()
    tables.write_text(named + '\n\ndef inline(sfx=""):\n    return projection_table(f"memory_c{sfx}")\n',
                      encoding="utf-8")
    with pytest.raises(AssertionError, match=re.escape("inline (aucune)")):
        test_every_table_she_declares_is_named()
    tables.write_text(named + 'C_TABLE = "memory_c"\n', encoding="utf-8")
    with pytest.raises(AssertionError, match=re.escape("['C_TABLE']")):
        test_every_table_she_declares_is_named()
    tables.write_text(named, encoding="utf-8")
    owned.write_text('from mika.ports import sql\nPHOTOS = sql.projection_table("memory_photos")\n', encoding="utf-8")
    with pytest.raises(AssertionError, match=re.escape("faculties/memory/x.py:2")):
        test_every_table_she_declares_is_named()
