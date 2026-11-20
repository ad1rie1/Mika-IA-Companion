"""Le fichier ``.env`` du dossier courant (ADR 0250), lu au démarrage de la commande ``mika`` : des variables
d'environnement posées à côté du code en local (une clé d'API : ``MIKA_GOOGLE_PLACES_API_KEY=…``), sans les taper à
chaque lancement.

**Les règles** : une affectation ``NOM=valeur`` par ligne (``export NOM=valeur`` aussi) ; une ligne vide, ou qui
commence par ``#``, ne compte pas, ni ce qui suit `` #`` après une valeur sans guillemets ; une valeur entre
guillemets (simples ou doubles) les perd ; une ligne illisible est laissée. **Rien n'est écrasé** : une variable déjà
posée (en service, ``/etc/mika/mika.env`` par l'unité systemd) garde sa valeur, même vide. Aucune valeur n'est écrite
nulle part, ni au journal.

``MIKA_ENV_FILE`` nomme un autre fichier ; vide, aucun n'est lu — c'est ce que posent les tests (``tests/conftest.py``),
qui ne lisent jamais le ``.env`` de qui les lance."""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

#: un autre fichier que ``.env`` du dossier courant ; vide : aucun
FILE_VAR = "MIKA_ENV_FILE"
DEFAULT = ".env"
#: au-delà, le fichier n'est pas lu (ce n'est pas un fichier de variables)
SIZE_MAX = 256 * 1024
_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def parse(text: str) -> dict[str, str]:
    """Les affectations d'un fichier de variables, dans l'ordre (la dernière d'un nom l'emporte)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        found = _LINE.match(line)
        if found is None:
            continue
        name, value = found.group(1), found.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[name] = value
    return out


def load(environ: MutableMapping[str, str] | None = None, *, cwd: Path | None = None) -> list[str]:
    """Le ``.env`` du dossier courant (ou ``MIKA_ENV_FILE``) dans l'environnement, sans rien écraser ; absent ou
    illisible : rien. Rend les noms posés (jamais leurs valeurs)."""
    env = os.environ if environ is None else environ
    if FILE_VAR in env:
        named = env[FILE_VAR].strip()
        if not named:
            return []
        path = Path(named)
    else:
        path = (cwd or Path.cwd()) / DEFAULT
    try:
        if not path.is_file() or path.stat().st_size > SIZE_MAX:
            return []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    posed = []
    for name, value in parse(text).items():
        if name in env:
            continue
        env[name] = value
        posed.append(name)
    return posed
