"""Un seul Mika par dossier de données.

Deux processus qui écrivent le même journal se disputent les numéros de séquence :
le second échoue en boucle (``UNIQUE constraint failed: events.seq``) et plus rien
de ce qu'on lui demande — une opération de la console, un pas de travail — ne
s'écrit. C'est arrivé : plusieurs ``mika serve`` lancés sur ``data/v2``.

Le verrou (``flock`` exclusif sur ``<dossier>/mika.lock``, qui porte le pid de son
détenteur) est pris par le serveur et par les commandes qui écrivent le journal ;
un second processus est refusé en le disant. Dans un même processus il est
réentrant (les tests bâtissent plusieurs serveurs, ``replay --verify`` ouvre deux
fois le dossier) ; le système le libère de lui-même quand le processus meurt.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

LOCK_NAME = "mika.lock"

#: les verrous tenus par ce processus : chemin → [descripteur, nombre de détenteurs]
_HELD: dict[Path, list[int]] = {}


class DataDirBusy(RuntimeError):
    """Un autre processus tient déjà ce dossier de données."""


def _lock_path(data: Path) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    return (data / LOCK_NAME).resolve()


def hold(data: Path) -> None:
    """Prend le dossier (ou compte un détenteur de plus, dans ce processus) ; lève
    ``DataDirBusy`` si un autre processus le tient."""
    path = _lock_path(data)
    held = _HELD.get(path)
    if held is not None:
        held[1] += 1
        return
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        other = os.read(fd, 32).decode(errors="replace").strip() or "inconnu"
        os.close(fd)
        raise DataDirBusy(f"un autre Mika tourne déjà sur ce dossier ({data}) : pid {other}. Arrête-le d'abord, "
                          "ou lance celui-ci sur un autre dossier (--data).") from None
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    _HELD[path] = [fd, 1]


def release(data: Path) -> None:
    """Rend le dossier (le dernier détenteur de ce processus le libère)."""
    path = _lock_path(data)
    held = _HELD.get(path)
    if held is None:
        return
    held[1] -= 1
    if held[1] > 0:
        return
    del _HELD[path]
    fcntl.flock(held[0], fcntl.LOCK_UN)
    os.close(held[0])
