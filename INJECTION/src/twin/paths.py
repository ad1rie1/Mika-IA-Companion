"""Où vit le jumeau : le dossier INJECTION/ (``JUMEAU_RACINE`` pour en désigner un autre)."""

from __future__ import annotations

import os
from pathlib import Path


def default_root() -> Path:
    env = os.environ.get("JUMEAU_RACINE")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "twin").is_dir():
            return parent
    return Path.cwd()
