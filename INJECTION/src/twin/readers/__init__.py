"""Les lecteurs : un par format, découverts ici.

Un lecteur dit s'il reconnaît un fichier (``detect`` : 0 = non, jusqu'à 100 = sûr) et le
lit en enregistrements normalisés (``read``). Le plus confiant gagne ; un fichier que
personne ne reconnaît est listé comme « inconnu », pour la commande
``/jumeau-nouveau-format`` qui fait écrire un lecteur à Claude Code.

Ajouter un format : un module ici qui expose ``READER``, puis l'inscrire dans ``ALL``.
"""

from __future__ import annotations

import codecs
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from twin.records import Item


@dataclass
class ReadContext:
    tz: ZoneInfo
    root: Path  # le dossier brut/ : les dates des dossiers se lisent sous lui
    country_code: str = "+33"  # pour normaliser les numéros nationaux (06… → +336…)
    warnings: list[str] = field(default_factory=list)
    warn_cb: Callable[[str], None] | None = None

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        if self.warn_cb:
            self.warn_cb(msg)


class Reader(Protocol):
    name: str
    label: str
    version: int

    def detect(self, path: Path) -> int: ...

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]: ...


def all_readers() -> list[Reader]:
    from twin.readers import mail, meta, msn, notes, sms, whatsapp  # noqa: PLC0415 — registre paresseux

    return [whatsapp.READER, meta.READER, msn.READER, sms.READER, mail.READER, notes.READER]


def pick(path: Path, readers: list[Reader]) -> tuple[Reader | None, int]:
    best: Reader | None = None
    score = 0
    for r in readers:
        s = r.detect(path)
        if s > score:
            best, score = r, s
    return best, score


def head(path: Path, size: int = 8192) -> str:
    """Le début d'un fichier en texte, quel que soit l'encodage (pour ``detect``)."""
    try:
        with path.open("rb") as f:
            raw = f.read(size)
    except OSError:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if len(raw) >= 16 and raw[1::2].count(0) > len(raw) // 4:  # UTF-16 sans BOM : un octet nul sur deux
        return raw.decode("utf-16-le", errors="replace")
    try:
        # incrémental : un caractère coupé par la limite de lecture n'est pas une erreur d'encodage
        return codecs.getincrementaldecoder("utf-8-sig")().decode(raw, final=False)
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def read_text(path: Path) -> str:
    """Tout le fichier en texte : UTF-8 (avec ou sans BOM), UTF-16, sinon cp1252/latin-1."""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("latin-1")
