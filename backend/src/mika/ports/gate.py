"""Ce qu'une porte à clé rend au transport web (Teams, le téléphone, les réveils) : ses issues, son résultat, et ce
qu'on montre d'une clé.

Chaque port garde sa porte (``TeamsGate``, ``PhoneGate``, ``WakeGate``) et ce qui n'est qu'à lui ; une issue veut dire
la même chose partout, et le transport n'a qu'une table pour la dire en HTTP. La machinerie qu'elles partagent est dans
``adapters/web/gate.py``, avec ce qui reste propre à chacune.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: admis
ACCEPTED = "accepted"
#: admis, mais il n'y a rien à faire (le « ping » d'un service qui vérifie son webhook) : rien n'est journalisé
IGNORED = "ignored"
#: clé absente ou fausse, ou nom inconnu : la même réponse dans tous ces cas (rien ne dit qu'un nom existe)
UNKNOWN = "unknown"
#: reconnu, mais ce n'est pas à lui (les messages du téléphone sont à sa propriétaire)
FORBIDDEN = "forbidden"
#: coupé dans ses réglages
DISABLED = "disabled"
#: une requête illisible (forme, tailles, texte vide ou trop long)
INVALID = "invalid"
#: trop de requêtes, ou pas prête : réessayer dans ``retry_after`` secondes
BUSY = "busy"
#: ce qu'elle vise n'existe pas (un élément de la file)
MISSING = "missing"
#: la requête ne va pas avec l'état de ce qu'elle vise (« posé » pour un message déjà parti)
CONFLICT = "conflict"
#: elle ne peut rien en faire maintenant (le projet d'un réveil n'est pas actif)
REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class GateResult:
    """Ce que la porte a décidé : ``outcome``, un message pour l'appelant, ce que rend un appel admis (``data``, tel
    quel dans la réponse), et dans combien de secondes réessayer (``BUSY``)."""

    outcome: str
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    retry_after: int = 0


@dataclass(frozen=True, slots=True)
class KeyState:
    """Ce qu'on montre d'une clé : jamais le secret, de quoi la reconnaître."""

    hint: str
    created_at: int
    by: str = ""
    #: elle peut vérifier une signature (une copie chiffrée est gardée, pour un réveil signé)
    signs: bool = False
