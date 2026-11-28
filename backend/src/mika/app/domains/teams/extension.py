"""L'extension de Teams à télécharger (ADR 0069, 0246) : le dossier ``frontend/ExtensionChromeTeams`` du dépôt où tourne le
serveur, mis en zip à la demande, pour qui est connecté. Elle suit donc le code déployé : rien à déposer à la main, et
la version qu'on charge est celle que le serveur attend.

Le zip crée un dossier ``mika-teams/``, celui qu'on charge dans le navigateur (« Charger l'extension non
empaquetée »). Il emporte les fichiers de l'extension tels qu'ils sont, sans ses tests, ce qui ne sert qu'à les lancer
ni sa doc ; jamais un fichier caché ni un lien (rien hors du dossier). Au-delà de ses bornes, ce n'est plus l'extension
(un dossier égaré dedans) : rien ne part.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import zipfile
from pathlib import Path

from starlette.responses import Response

from mika.app.me.api import Call, Denied

#: le dossier de l'extension, dans le dépôt à côté du serveur (``backend/src/mika/app/domains/teams`` → la racine du
#: dépôt)
EXTENSION_DIR = Path(__file__).resolve().parents[6] / "frontend" / "ExtensionChromeTeams"
#: ce qui reste au dépôt, à la racine de l'extension : ses tests, ce qui les lance, sa doc
LEFT_OUT = frozenset({"tests", "node_modules", "package.json", "package-lock.json", "README.md"})
#: le dossier que le zip crée en se décompressant
FOLDER = "mika-teams"
MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 400
VERSION = re.compile(r"\d{1,9}(\.\d{1,9}){0,3}")


def version_of(folder: Path | None) -> str | None:
    """La version de l'extension posée là (son ``manifest.json``) ; ``None`` : pas d'extension lisible."""
    if folder is None:
        return None
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version if isinstance(version, str) and VERSION.fullmatch(version) else None


def packed(folder: Path) -> bytes | None:
    """L'extension en zip, sous ``mika-teams/`` ; ``None`` : illisible, ou au-delà de ses bornes."""
    buffer = io.BytesIO()
    files = size = 0
    try:
        # un fichier daté d'avant 1980 (une copie qui a perdu ses dates) y est ramené, plutôt que de tout refuser
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as out:
            for root, dirs, names in os.walk(folder):  # ne suit pas les liens vers un dossier
                here = Path(root)
                top = here == folder
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (top and d in LEFT_OUT)
                                 and not (here / d).is_symlink())
                for name in sorted(names):
                    path = here / name
                    if name.startswith(".") or (top and name in LEFT_OUT) or path.is_symlink() or not path.is_file():
                        continue
                    files += 1
                    size += path.stat().st_size
                    if files > MAX_FILES or size > MAX_BYTES:
                        return None
                    out.write(path, f"{FOLDER}/{path.relative_to(folder).as_posix()}")
    except OSError:
        return None
    return buffer.getvalue()


async def download(call: Call) -> Response:
    """``GET /api/moi/teams/extension`` : l'extension en zip, à qui est connecté (sa session, ou un jeton de son
    compte) — jamais par un lien public. Pas à côté de ce serveur, ou illisible : 404."""
    folder = call.api.extension
    version = version_of(folder)
    if folder is None or version is None:
        raise Denied(404, "L'extension n'est pas à côté de ce serveur : demande-la à ton opérateur.")
    data = await asyncio.to_thread(packed, folder)  # quelques centaines de Kio lus et compressés, hors de la boucle
    if data is None:
        raise Denied(404, "L'extension posée à côté de ce serveur est illisible : préviens ton opérateur.")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{FOLDER}-{version}.zip"',
                             "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
