"""La déclaration des données du paquet ne ment pas sur la console : chaque gabarit et chaque fichier statique de
l'inspecteur (``templates/handmade/…``, ``static/handmade/…`` compris) est couvert par les motifs de
``[tool.setuptools.package-data]``. Les anciens motifs (``templates/*.html``, ``static/*.css``…) ne descendaient pas
dans les sous-dossiers : une installation non éditable aurait perdu les pages dessinées (audit du 2026-11-05, K0-24).

Seule l'installation éditable est prise en charge (la persona est lue à côté de ``src/``, ``app/paths.py``) ; ce test
ne dit que ceci : ce que la déclaration annonce pour la console, elle le couvre."""

from __future__ import annotations

import glob
import tomllib
from pathlib import Path

from mika import inspector

ROOT = Path(__file__).resolve().parents[2]
INSPECTOR = Path(inspector.__file__).resolve().parent


def _declared() -> set[Path]:
    """Ce que les motifs de ``mika.inspector`` prennent, lus comme setuptools les lit (``glob`` récursif)."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["mika.inspector"]
    return {Path(found).resolve() for pattern in patterns
            for found in glob.glob(str(INSPECTOR / pattern), recursive=True) if Path(found).is_file()}


def test_every_console_file_is_declared():
    files = {p.resolve() for folder in ("templates", "static") for p in (INSPECTOR / folder).rglob("*")
             if p.is_file() and "__pycache__" not in p.parts}
    assert files, "ni gabarit ni fichier statique : le chemin de l'inspecteur a changé"
    missing = sorted(str(p.relative_to(INSPECTOR)) for p in files - _declared())
    assert not missing, f"des fichiers de la console hors de [tool.setuptools.package-data] : {missing[:5]}"
