"""Ce que le modèle lit de la personne (ADR 0093), joué par un test : c'est le modèle qui juge, jamais le code de
Mika — un test qui veut qu'elle sente quelque chose le fait déclarer par la réponse, avec sa balise ``[EN_FACE: …]``.
"""

from __future__ import annotations

from collections.abc import Mapping

from mika.kernel.prompt import CONTEXT_FOOTER


def said_in(req) -> str:
    """Le dernier message de la personne, tel que la réponse le reçoit (après l'état interne)."""
    content = req.messages[-1].content if req.messages else ""
    return content.split(CONTEXT_FOOTER)[-1].strip()


class Reads:
    """Ce que le modèle lit de chaque message, par son texte (``{"je suis triste": "sad 0.7"}``) ; un message que la
    table ne connaît pas se lit « rien »."""

    def __init__(self, table: Mapping[str, str] | None = None, default: str = "rien"):
        self.table = dict(table or {})
        self.default = default

    def of(self, message: str) -> str:
        for text, reading in self.table.items():
            if message.strip().endswith(text.strip()):
                return reading
        return self.default

    def tag(self, req) -> str:
        return f" [EN_FACE: {self.of(said_in(req))}]"
