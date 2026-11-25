"""La déclaration des données du paquet ne ment pas sur la console : chaque gabarit et chaque fichier statique de
l'inspecteur (``templates/handmade/…``, ``static/handmade/…`` compris) est couvert par les motifs de
``[tool.setuptools.package-data]``. Les anciens motifs (``templates/*.html``, ``static/*.css``…) ne descendaient pas
dans les sous-dossiers : une installation non éditable aurait perdu les pages dessinées (audit du 2026-11-05, K0-24).

Seule l'installation éditable est prise en charge (la persona est lue à côté de ``src/``, ``app/paths.py``) ; ce test
ne dit que ceci : ce que la déclaration annonce pour la console, elle le couvre.

Les gabarits et les fichiers statiques d'un domaine vivent dans son dossier de console
(``app/domains/<nom>/console/templates/``, ``…/static/``, ADR 0310), sous les noms et aux adresses qu'ils auraient
dans l'inspecteur : ils sont déclarés de même (``mika.app``), et **un même nom n'existe que dans un dossier** — la
console les cherche dans l'ordre, le premier trouvé gagnerait sans bruit."""

from __future__ import annotations

import glob
import tomllib
from pathlib import Path

from mika import app, inspector

ROOT = Path(__file__).resolve().parents[2]
INSPECTOR = Path(inspector.__file__).resolve().parent
APP = Path(app.__file__).resolve().parent
#: les dossiers de console des domaines
CONSOLES = sorted(p for p in (APP / "domains").glob("*/console") if p.is_dir())


def _declared(package: str = "mika.inspector", root: Path = INSPECTOR) -> set[Path]:
    """Ce que les motifs d'un paquet prennent, lus comme setuptools les lit (``glob`` récursif)."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"][package]
    return {Path(found).resolve() for pattern in patterns
            for found in glob.glob(str(root / pattern), recursive=True) if Path(found).is_file()}


def _files(root: Path) -> set[Path]:
    return {p.resolve() for folder in ("templates", "static") for p in (root / folder).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


def test_every_console_file_is_declared():
    files = _files(INSPECTOR)
    assert files, "ni gabarit ni fichier statique : le chemin de l'inspecteur a changé"
    missing = sorted(str(p.relative_to(INSPECTOR)) for p in files - _declared())
    assert not missing, f"des fichiers de la console hors de [tool.setuptools.package-data] : {missing[:5]}"


def test_every_console_file_of_a_domain_is_declared():
    files = {p for console in CONSOLES for p in _files(console)}
    assert files, "aucun gabarit de domaine : le chemin des dossiers de console a changé"
    missing = sorted(str(p.relative_to(APP)) for p in files - _declared("mika.app", APP))
    assert not missing, f"des fichiers de console d'un domaine hors de [tool.setuptools.package-data] : {missing[:5]}"


def test_no_console_file_exists_twice():
    """La console cherche un gabarit ou une feuille dans son dossier, puis dans celui de chaque domaine : deux fichiers
    du même nom, et le second ne servirait jamais — sans erreur."""
    seen: dict[tuple[str, str], Path] = {}
    twice = []
    for root in (INSPECTOR, *CONSOLES):
        for folder in ("templates", "static"):
            for path in sorted((root / folder).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    name = (folder, path.relative_to(root / folder).as_posix())
                    if name in seen:
                        twice.append(f"{name[1]} : {seen[name].relative_to(ROOT)} et {path.relative_to(ROOT)}")
                    seen.setdefault(name, path)
    assert not twice, twice


def test_a_console_folder_serves_its_templates_and_its_sheets_under_their_names(tmp_path):
    """Un dossier de console inscrit : ses gabarits se chargent par leur nom, ses fichiers statiques se servent à leur
    adresse — à côté de ceux de l'inspecteur, qui passent d'abord."""
    from jinja2 import FileSystemLoader
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from starlette.testclient import TestClient

    from mika.inspector import ui
    from mika.inspector.app import ConsoleStatic

    (tmp_path / "templates" / "handmade" / "essai").mkdir(parents=True)
    (tmp_path / "templates" / "handmade" / "essai" / "page.html").write_text("<p>{{ PREFIX }}</p>", encoding="utf-8")
    (tmp_path / "static" / "handmade").mkdir(parents=True)
    (tmp_path / "static" / "handmade" / "essai.css").write_text(".essai{}", encoding="utf-8")
    before, loader = list(ui.FOLDERS), ui.env.loader
    try:
        ui.console_folder(tmp_path)
        ui.console_folder(tmp_path)  # deux fois : inscrit une fois
        assert ui.FOLDERS.count(tmp_path) == 1
        assert ui.env.get_template("handmade/essai/page.html").render() == f"<p>{ui.PREFIX}</p>"
        assert ui.env.get_template("base.html") is not None  # ceux de l'inspecteur restent
        client = TestClient(Starlette(routes=[Mount("/static", ConsoleStatic(ui.static_roots()))]))
        assert client.get("/static/handmade/essai.css").text == ".essai{}"
        assert client.get("/static/console.css").status_code == 200
        assert client.get("/static/handmade/absent.css").status_code == 404
    finally:
        ui.FOLDERS[:] = before
        ui.env.loader = loader if isinstance(loader, FileSystemLoader) else ui.env.loader
