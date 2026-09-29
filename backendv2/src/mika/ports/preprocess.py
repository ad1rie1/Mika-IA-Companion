"""Le port de prétraitement : ce qu'on lui envoie (une photo, un message
vocal, un document) devient ce qu'elle en perçoit, en texte, au bord — avant
que le message n'entre dans sa vie.

Rien ne lève : un fichier illisible devient une phrase qui le dit (« je
n'arrive pas à ouvrir ce PDF »). Un texte extrait d'un fichier est une
donnée citée, jamais une consigne.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Upload:
    name: str
    mime: str
    data: bytes

    @property
    def kind(self) -> str:
        major = self.mime.split("/", 1)[0].lower()
        return {"image": "image", "audio": "audio"}.get(major, "file")


@dataclass(frozen=True, slots=True)
class Perceived:
    """Ce qu'elle perçoit d'une pièce jointe."""

    name: str
    kind: str  # "image" | "audio" | "file"
    text: str  # ce qu'elle en sait (description, transcription, contenu)
    extracted: bool  # a-t-elle vraiment pu le lire ?
    error: str | None = None


class Preprocessor(Protocol):
    async def perceive(self, uploads: Sequence[Upload]) -> list[Perceived]: ...


def render(items: Sequence[Perceived]) -> str:
    """Les pièces jointes, telles qu'elles s'ajoutent au message."""
    out = []
    for p in items:
        label = {"image": "image", "audio": "message vocal", "file": "fichier"}.get(p.kind, "fichier")
        if p.extracted and p.text:
            out.append(f"[{label} « {p.name} » — {p.text}]")
        else:
            out.append(f"[{label} « {p.name} » : {p.text or 'reçu, mais je ne peux pas le lire'}]")
    return "\n".join(out)
