"""Le port des fichiers qu'elle envoie : leurs octets, hors du journal (ADR 0062).

Le journal garde ce qui se raconte et s'oublie (un nom, une taille, une empreinte) ; les octets vivent ici, sous
leur identifiant (32 caractères hexadécimaux). Chacun porte ses **sujets** (la personne à qui il part, celles
qu'il concerne) : oublier une personne efface ses fichiers, comme ses contenus.

- ``put`` est idempotent : réécrire le même identifiant avec les mêmes octets ne change rien (un appel d'outil
  rejoué après une supplantation retombe sur le même fichier) ;
- ``read`` rend au plus ``limit`` octets, ``None`` quand il n'y a rien (retiré, oublié, jamais écrit) ;
- ``delete`` et ``forget`` rendent combien de fichiers ils ont effacés.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Protocol

#: au plus, un fichier envoyé (un texte écrit est bien plus petit : voir la faculté)
MAX_SHARE_BYTES = 10 * 1024 * 1024
#: un identifiant de fichier : 32 caractères hexadécimaux (rien d'autre n'atteint le disque)
FILE_ID = re.compile(r"^[0-9a-f]{32}$")


def valid_id(file: str) -> bool:
    return isinstance(file, str) and FILE_ID.fullmatch(file) is not None


class ShareStore(Protocol):
    async def put(self, file: str, data: bytes, *, subjects: Iterable[str]) -> None: ...

    async def read(self, file: str, limit: int = MAX_SHARE_BYTES) -> bytes | None: ...

    async def delete(self, files: Sequence[str]) -> int: ...

    async def forget(self, subject: str) -> int: ...
