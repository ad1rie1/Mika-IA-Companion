"""Les réveils par API (ADR 0068) : ce que la faculté « wakeup » et le transport web voient des réveils déclarés.

Un réveil est déclaré par l'opérateur (Réglages › Plugins › Réveils par API) ; sa clé est générée ici, montrée
une seule fois, et seule son empreinte est gardée. Deux faces :

- *le guichet* (``WakeDesk``, le port ``wakeup``) : la console lit les réveils et l'état de leur clé, en génère une
  neuve ou la retire ;
- *la porte* (``WakeGate``) : le transport web lui passe un appel (``WakeRequest`` : le nom, la clé ou la signature,
  le corps tel qu'il est arrivé et lu, l'évènement annoncé, la clé d'idempotence) et rend à l'appelant ce qu'elle a
  décidé (``WakeResult``) — elle vérifie la clé, l'état du réveil et ses plafonds avant de journaliser quoi que ce
  soit (ADR 0068, 0117).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

#: le préfixe d'une clé de réveil (une clé se reconnaît, et ne se confond pas avec un jeton de compte, ``mw_``)
KEY_PREFIX = "mwk_"
#: les issues d'un appel
ACCEPTED = "accepted"
#: réveil inconnu ou mauvaise clé : la même réponse dans les deux cas (rien ne dit qu'un nom existe)
UNKNOWN = "unknown"
#: le réveil est désactivé
DISABLED = "disabled"
#: le texte est vide ou trop long
INVALID = "invalid"
#: trop d'appels (par heure, ou en attente)
BUSY = "busy"
#: le réveil ne peut rien en faire maintenant (son projet n'est pas actif)
REFUSED = "refused"
#: admis, mais il n'y a rien à faire (le « ping » d'un service qui vérifie son webhook) : rien n'est journalisé
IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class KeyState:
    """Ce qu'on montre d'une clé : jamais le secret, de quoi la reconnaître."""

    hint: str
    created_at: int
    by: str = ""
    #: elle peut vérifier une signature (une copie chiffrée est gardée, pour un réveil signé)
    signs: bool = False


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Un réveil tel que l'opérateur l'a déclaré, et l'état de sa clé."""

    name: str
    label: str
    enabled: bool
    project: int
    plain: bool
    bundles: tuple[str, ...]
    instructions: str
    rouse: bool
    notify: str
    per_hour: int
    max_pending: int
    lifetime_us: int
    max_chars: int
    key: KeyState | None = None
    #: l'appelant signe le corps avec la clé (``X-Hub-Signature-256``) au lieu de la présenter
    signed: bool = False
    #: les champs gardés d'un corps qui n'a pas de ``text`` (des chemins : ``issue.title``, ``commits.*.message``)
    fields: tuple[str, ...] = ()


class WakeDesk(Protocol):
    """Le guichet des réveils (le port ``wakeup``)."""

    def endpoints(self) -> Sequence[Endpoint]: ...

    def endpoint(self, name: str) -> Endpoint | None: ...

    async def new_key(self, name: str, by: str) -> str:
        """Une clé neuve pour ce réveil (l'ancienne ne vaut plus) ; ``ValueError`` si le réveil n'existe pas."""
        ...

    async def revoke_key(self, name: str, by: str) -> bool:
        """Retirer la clé de ce réveil (plus aucun appel ne passe) ; ``False`` s'il n'en avait pas."""
        ...


@dataclass(frozen=True, slots=True)
class WakeResult:
    """Ce que la porte a décidé d'un appel : ``outcome`` (``ACCEPTED``…), un message pour l'appelant, le ``seq`` de
    l'appel journalisé, et dans combien de secondes réessayer (``BUSY``)."""

    outcome: str
    message: str = ""
    call: int | None = None
    retry_after: int = 0


@dataclass(frozen=True, slots=True)
class WakeRequest:
    """Un appel tel que le transport l'a reçu, rien n'étant encore décidé."""

    #: le nom du réveil (la fin de l'URL)
    name: str
    #: la clé présentée (``Authorization: Bearer``, ou l'en-tête d'un service qui la recopie) ; vide : aucune
    key: str = ""
    #: le corps tel qu'il est arrivé : ce que vérifie une signature
    body: bytes = b""
    #: le corps lu (du JSON) ; ``None`` : illisible ou absent
    data: Any = None
    #: la signature du corps (HMAC-SHA256 en hexadécimal, ``sha256=`` devant ou non) ; vide : aucune
    signature: str = ""
    #: l'évènement que le service annonce (``push``, ``issues``, ``ping``…) ; vide : aucun
    event: str = ""
    idempotency: str = ""


#: la porte : ``WakeRequest -> WakeResult``
WakeGate = Callable[[WakeRequest], Awaitable[WakeResult]]
