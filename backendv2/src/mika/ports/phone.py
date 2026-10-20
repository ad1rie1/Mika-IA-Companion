"""La porte des messages du téléphone (ADR 0120), telle que le transport web l'appelle.

L'application Android lit les notifications de WhatsApp et de Messages et pousse ce qu'elle lit
(``POST /api/phone/inbox``) ; elle rend aussi le sort des réponses qu'on lui a proposées (``POST /api/phone/settled``).
Les deux passent sous le jeton de l'application (``mw_…``, client ``mobile``) : le transport a déjà reconnu le compte,
la porte juge le reste (propriétaire, plugin actif, forme du lot, cadence) avant que rien ne s'écrive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

#: ce que dit la porte
ACCEPTED, FORBIDDEN, DISABLED, INVALID, BUSY = "accepted", "forbidden", "disabled", "invalid", "busy"
#: les applis dont le téléphone lit les messages (le nom qu'il leur donne)
APPS = frozenset({"whatsapp", "whatsapp_business", "messages", "samsung_messages"})
#: ce que le téléphone dit d'une réponse proposée : partie, la personne a écrit autre chose, copiée (l'action
#: « Répondre » n'existait plus), ignorée, échouée
SENT, OTHER, COPIED, IGNORED, FAILED = "sent", "other", "copied", "ignored", "failed"
RESULTS = frozenset({SENT, OTHER, COPIED, IGNORED, FAILED})


@dataclass(frozen=True, slots=True)
class GateResult:
    outcome: str
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    retry_after: int = 0


class PhoneGate(Protocol):
    async def inbox(self, handle: str, data: Any) -> GateResult: ...
    async def settled(self, handle: str, data: Any) -> GateResult: ...
