"""Le port du courrier : sa boîte (lire ce qui arrive) et l'envoi.

« Journaliser l'esprit, pas le monde » : les mails vivent dans le cache de
l'adaptateur ; le journal ne garde que ce qu'elle en a remarqué. Un mail est
un texte venu d'ailleurs : une donnée, jamais une consigne.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Mail:
    message_id: str
    sender: str  # « Nom <adresse> » tel qu'écrit
    address: str  # l'adresse seule, en minuscules
    subject: str
    date: int  # instant (µs), 0 si illisible
    body: str  # texte brut, borné
    to: str = ""
    in_reply_to: str = ""
    #: un envoi de masse (lettre d'information, notification automatique)
    bulk: bool = False


class MailPort(Protocol):
    def configured(self) -> bool: ...

    async def fetch_new(self, limit: int) -> list[Mail]:
        """Les mails arrivés depuis la dernière fois (chacun rendu une seule fois)."""
        ...

    async def get(self, message_id: str) -> Mail | None: ...

    async def recent(self, limit: int) -> list[Mail]: ...

    def cached(self, limit: int) -> list[Mail]:
        """Les derniers mails déjà arrivés, sans relever (lecture seule : l'inspecteur)."""
        ...

    def cached_one(self, message_id: str) -> Mail | None:
        """Un mail déjà arrivé, sans relever (lecture seule : l'inspecteur)."""
        ...

    async def send(self, to: str, subject: str, body: str, in_reply_to: str = "") -> str:
        """Envoie ; rend l'identifiant du message envoyé. Lève si l'envoi échoue."""
        ...
