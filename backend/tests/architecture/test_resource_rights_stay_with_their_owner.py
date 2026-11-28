"""Les droits d'une ressource sont à son propriétaire (ADR 0316).

Le moteur des droits est commun : ``vocab.access`` porte le cadre d'une ligne (qui, par où, quand), le tableau et
``decide`` ; ``vocab.rights``, les deux portes et le plafond. Ce qui n'est qu'à une sorte de ressource est chez son
propriétaire : son type de ligne au contrat (``contracts/agenda.py::AgendaRule``), son calcul dans son plugin ou sa
faculté (``plugins/agenda/rights.py::agenda_allowance``), ses tableaux réglés dans les réglages de son domaine
(``SettingsPart.access_tables``), que la porte des réglages réunit sous ``Rights.tables``. Cette garde le lit par
l'AST — jamais un commentaire :

- **``Rights`` n'a aucun champ au nom d'un domaine** : ses champs (ce que ``vocab/rights.py`` déclare dans la classe,
  une annotation par champ) sont nommés ici un à un (``FIELDS``) ; un champ de plus fait échouer la garde, et son
  message dit où va le tableau d'une sorte neuve.
- **``vocab/access.py`` ne déclare aucune ligne de ressource d'un seul domaine** : une classe du module qui dérive de
  ``Rule`` (de proche en proche, dans le module) est lue, hors de ``vocab/``, par les modules d'au moins deux domaines
  — ou d'aucun : le cœur, le runtime, l'inspecteur, le cadre, qui la lisent sans nommer de propriétaire. Lire, c'est
  l'importer par son nom (``from mika.vocab.access import X``) ou la lire par son module (``access.X``). Un domaine,
  c'est son dossier d'``app`` (``app/domains/<nom>/``) et ses paquets du dessous (``PACKAGES`` de
  ``test_frame_names_no_domain``) ; ce qui y loge sans être à lui (``SHARED``) ne compte pas. Lue par un seul domaine
  — même si le cadre la lit aussi, pour la ranger, comme l'agenda le faisait avant —, elle va au contrat de ce
  domaine.

Ce qu'elle ne voit pas : un type de ligne déclaré ailleurs dans ``vocab`` (``vocab/canals.py`` : les canaux, qui sont
au cadre) ; un calcul d'une seule sorte ajouté à ``vocab/rights.py`` — une fonction n'a pas de forme qui la
distingue, et ``project_allowance`` y reste parce que deux propriétaires le lisent (les projets, les fichiers
envoyés) ; un tableau que le cadre rangerait sous une clé à lui. Ce sont les phrases de l'ADR 0316 et d'« Écrire un
domaine » qui le disent.

Le contrôle est une fonction des sources (``extra_fields``, ``single_owner_lines``) : les derniers tests l'essaient
sur un petit arbre factice, dans les deux sens.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Iterator, Mapping
from pathlib import Path

import mika
from tests.architecture.test_frame_names_no_domain import PACKAGES, SHARED

SRC = Path(mika.__file__).parent
#: les champs de ``Rights`` : ce que partagent toutes les sortes, rien qui soit à un domaine
FIELDS = ("canals", "families", "in_hand", "tables")
#: le module des lignes communes, et la classe du cadre de toute ligne
ACCESS, FRAME = "mika.vocab.access", "Rule"


def extra_fields(src: Path | None = None) -> list[str]:
    """Les champs de ``Rights`` (``vocab/rights.py``) que ``FIELDS`` ne nomme pas, et ceux qu'il nomme et qui manquent
    (préfixés « − »)."""
    tree = ast.parse(((src or SRC) / "vocab" / "rights.py").read_text(encoding="utf-8"))
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Rights")
    fields = [n.target.id for n in klass.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
    return [f for f in fields if f not in FIELDS] + [f"−{f}" for f in FIELDS if f not in fields]


def lines_declared(src: Path | None = None) -> list[str]:
    """Les classes de ``vocab/access.py`` qui dérivent de ``Rule``, de proche en proche dans le module."""
    tree = ast.parse(((src or SRC) / "vocab" / "access.py").read_text(encoding="utf-8"))
    rules = {FRAME}
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id in rules for b in node.bases):
            rules.add(node.name)
            out.append(node.name)
    return out


def _module_of(path: Path, src: Path) -> str:
    parts = list(path.relative_to(src.parent).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _source(reader: str, package: bool, node: ast.ImportFrom) -> str:
    """Le module que nomme un ``from … import`` — un import relatif résolu depuis celui qui le lit."""
    if not node.level:
        return node.module or ""
    base = reader.split(".") if package else reader.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _dotted(node: ast.AST) -> str:
    """``a.b.c`` pour une suite d'attributs posée sur un nom ; vide sinon."""
    chain: list[str] = []
    while isinstance(node, ast.Attribute):
        chain.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(chain)]) if isinstance(node, ast.Name) else ""


def read_names(path: Path, src: Path) -> Iterator[str]:
    """Les noms de ``vocab.access`` que ce fichier lit : importés par leur nom, ou lus par le module
    (``from mika.vocab import access`` puis ``access.X`` ; ``import mika.vocab.access as a`` puis ``a.X`` ;
    ``import mika.vocab.access`` puis ``mika.vocab.access.X``). Un source qui n'écrit nulle part « access » ne peut
    pas le lire : il n'est pas relu."""
    reader = _module_of(path, src)
    text = path.read_text(encoding="utf-8")
    if "access" not in text:
        return
    tree = ast.parse(text)
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = _source(reader, path.name == "__init__.py", node)
            for a in node.names:
                if source == ACCESS:
                    yield a.name
                elif f"{source}.{a.name}" == ACCESS:
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            aliases |= {a.asname or a.name for a in node.names if a.name == ACCESS}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _dotted(node.value) in aliases:
            yield node.attr


def owner_of(module: str, packages: Mapping[str, tuple[str, ...]]) -> str | None:
    """Le domaine d'un module de ``mika`` : son dossier d'``app``, ou un de ses paquets du dessous ; ``None`` pour le
    cœur, le runtime, l'inspecteur, le cadre — et ce qui loge chez un domaine sans être à lui (``SHARED``)."""
    parts = module.split(".")[1:]
    if parts[:2] == ["app", "domains"] and len(parts) > 2 and parts[2] not in ("domain",):
        return parts[2]
    dotted = ".".join(parts)
    if any(dotted == s or dotted.startswith(s + ".") for s in SHARED):
        return None
    return next((d for d, pkgs in packages.items() if any(dotted == p or dotted.startswith(p + ".") for p in pkgs)),
                None)


def readers(src: Path | None = None) -> dict[str, set[str]]:
    """Chaque ligne de ``vocab/access.py``, et les modules qui la lisent hors de ``vocab/``."""
    root = src or SRC
    declared = lines_declared(root)
    out: dict[str, set[str]] = {name: set() for name in declared}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or path.relative_to(root).parts[0] == "vocab":
            continue
        for name in set(read_names(path, root)) & set(declared):
            out[name].add(_module_of(path, root))
    return out


def owners(modules: set[str], packages: Mapping[str, tuple[str, ...]] | None = None) -> dict[str | None, list[str]]:
    """Les modules lecteurs, rangés par domaine (``None`` : le cœur, le runtime, l'inspecteur, le cadre)."""
    out: dict[str | None, list[str]] = {}
    for module in sorted(modules):
        out.setdefault(owner_of(module, PACKAGES if packages is None else packages), []).append(module)
    return out


def single_owner_lines(src: Path | None = None, read: Mapping[str, set[str]] | None = None
                       ) -> dict[str, dict[str, list[str]]]:
    """Ce que la garde reproche : chaque ligne de ``vocab/access.py`` que les modules d'un seul domaine lisent (hors de
    ``vocab/``), avec ce domaine et ses modules lecteurs — le cœur et le cadre ne comptent pas. ``read`` : ce que
    ``readers`` a déjà lu."""
    out: dict[str, dict[str, list[str]]] = {}
    for name, modules in (readers(src) if read is None else read).items():
        domains = {d: m for d, m in owners(modules).items() if d is not None}
        if len(domains) == 1:
            out[name] = domains
    return out


@functools.cache
def _real() -> dict[str, set[str]]:
    """Ce que lit l'arbre réel, une fois pour les tests qui le regardent."""
    return readers()


def test_rights_has_no_field_named_after_a_domain():
    found = extra_fields()
    assert not found, (
        f"Rights (vocab/rights.py) ne porte que ce que toutes les sortes partagent ({', '.join(FIELDS)}) ; voici ce "
        f"qui diffère : {', '.join(found)}. Le tableau réglé d'une sorte neuve de ressource se range dans les réglages "
        "de son domaine, sous sa clé (sa SettingsPart, qui le rend par access_tables), et se lit par "
        "Rights.sort(<sa sorte>) — jamais par un champ de plus ici (ADR 0316). Un champ que toutes les sortes "
        "partagent se nomme dans FIELDS, avec sa raison.")


def test_vocab_access_declares_no_line_of_a_single_domain():
    found = single_owner_lines(read=_real())
    said = [f"{name} : lue par le seul domaine « {domain} » ({', '.join(modules)})"
            for name, domains in sorted(found.items()) for domain, modules in domains.items()]
    assert not found, (
        "Une ligne de ressource que lit un seul domaine va au contrat de ce domaine, son calcul dans son plugin ou sa "
        "faculté, ses tableaux réglés dans ses réglages (ADR 0316) — pas dans vocab/access.py, même si le cadre la "
        "lit pour la ranger :\n" + "\n".join(said))


def test_the_guard_reads_the_real_lines():
    """La garde lit bien de vraies lignes : celles des outils (un service, une app, une de ses familles), que lisent
    au moins le domaine de ses outils venus d'ailleurs et celui de la Forge, et le cadre."""
    assert "ToolRule" in lines_declared()
    assert {"tools", "forge", None} <= set(owners(_real()["ToolRule"]))


def _tree(tmp_path: Path, files: Mapping[str, str]) -> Path:
    src = tmp_path / "mika"
    for rel, text in {"__init__.py": "", "vocab/__init__.py": "", **files}.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="utf-8")
    return src


FAKE_PACKAGES = {"coffre": ("plugins.coffre", "contracts.coffre"), "forge": ("plugins.forge",),
                 "tools": ("adapters.mcp",)}
FAKE_ACCESS = ("class Rule:\n    pass\n\nclass ToolRule(Rule):\n    pass\n\nclass VaultRule(Rule):\n    pass\n\n"
               "class Narrower(VaultRule):\n    pass\n\nclass Other:\n    pass\n")


def test_the_guard_fails_on_a_line_of_one_domain_and_passes_a_shared_one(tmp_path: Path, monkeypatch):
    """Une ligne lue par un seul domaine est vue — par son nom, par son module, même quand le cadre la lit aussi —, et
    pas une ligne que deux domaines lisent, ni ce qui n'est pas une ligne."""
    monkeypatch.setattr(f"{__name__}.PACKAGES", FAKE_PACKAGES)
    src = _tree(tmp_path, {
        "vocab/access.py": FAKE_ACCESS,
        "vocab/rights.py": "from mika.vocab.access import VaultRule\n",  # vocab ne compte pas
        "plugins/coffre/rights.py": "from mika.vocab.access import VaultRule, Narrower, Other\n",
        "plugins/coffre/plain.py": "import mika.vocab.access\nw = mika.vocab.access.Narrower\n",
        "app/domains/coffre/settings.py": "from mika.vocab import access\nx = access.VaultRule\n",
        "app/settings.py": "import mika.vocab.access as a\ny = a.VaultRule\n",  # le cadre, qui la range
        "plugins/forge/access.py": "from mika.vocab.access import ToolRule\n",
        "adapters/mcp/config.py": "from mika.vocab import access as acc\nz = acc.ToolRule\n",
    })
    assert lines_declared(src) == ["ToolRule", "VaultRule", "Narrower"]
    assert single_owner_lines(src) == {
        "VaultRule": {"coffre": ["mika.app.domains.coffre.settings", "mika.plugins.coffre.rights"]},
        "Narrower": {"coffre": ["mika.plugins.coffre.plain", "mika.plugins.coffre.rights"]}}
    # sa ligne passe au contrat de son domaine, et ce qui la lit l'y prend : plus rien à reprocher
    (src / "vocab" / "access.py").write_text("class Rule:\n    pass\n\nclass ToolRule(Rule):\n    pass\n",
                                             encoding="utf-8")
    assert single_owner_lines(src) == {}
    # lue par deux domaines, une ligne de vocab passe
    (src / "vocab" / "access.py").write_text(FAKE_ACCESS, encoding="utf-8")
    (src / "plugins" / "forge" / "vault.py").write_text("from mika.vocab.access import VaultRule, Narrower\n",
                                                        encoding="utf-8")
    assert single_owner_lines(src) == {}


def test_the_guard_fails_on_a_field_named_after_a_domain(tmp_path: Path):
    """Un champ de plus dans ``Rights`` est vu, un champ qui manque aussi ; les méthodes ne sont pas des champs."""
    rights = ("class Rights:\n    canals: int = 0\n    families: dict = {}\n    in_hand: dict = {}\n"
              "    tables: dict = {}\nEXTRA\n    def sort(self, name):\n        return {}\n")
    src = _tree(tmp_path, {"vocab/rights.py": rights.replace("EXTRA", "    vaults: dict = {}")})
    assert extra_fields(src) == ["vaults"]
    (src / "vocab" / "rights.py").write_text(rights.replace("EXTRA", "").replace("    in_hand: dict = {}\n", ""),
                                             encoding="utf-8")
    assert extra_fields(src) == ["−in_hand"]
    (src / "vocab" / "rights.py").write_text(rights.replace("EXTRA", ""), encoding="utf-8")
    assert extra_fields(src) == []
