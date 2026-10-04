"""Les outils venus d'ailleurs (ADR 0064) : ce que la faculté « mcp » voit des serveurs MCP branchés.

Un serveur est déclaré par l'opérateur (à quoi il sert pour elle, comment le joindre, pour qui, quand) ; ses outils
ne lui sont offerts que tels qu'ils ont été **approuvés** — l'empreinte d'un outil (nom, description, schéma,
annotations) qui change le suspend jusqu'à une nouvelle approbation. Le port rend cet instantané approuvé
(``offered``), l'état de chaque serveur, et exécute un appel ; il ne décide jamais à qui un outil est offert (c'est
la porte d'offre du pipeline, avec ce que la faculté déclare).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

#: la nature d'un outil : lire, ou changer quelque chose ailleurs
NATURES = (("lecture", "lecture — elle lit, rien ne change ailleurs"),
           ("action", "action — ça change quelque chose ailleurs"))
#: qui doit accepter un appel avant qu'il parte
APPROVALS = (("aucun", "aucun — l'appel part dans la boucle, elle lit la réponse"),
             ("conversation", "dans la conversation — la personne accepte une carte dans le chat"),
             ("operateur", "de l'opérateur — dans Approbations"))
#: à qui un serveur peut servir (jamais dans un salon : une règle, pas un réglage)
AUDIENCES = (("proprietaire", "sa propriétaire seulement"),
             ("comptes", "aussi une personne authentifiée, en tête-à-tête"))
#: les familles d'épisodes où un serveur peut servir
EPISODES = (("conversation", "quand elle répond"), ("initiative", "quand elle prend la parole"),
            ("travail", "quand elle travaille (si le but ou le projet a pris ce lot)"))

#: l'état d'un serveur, du plus calme au plus grave
STATES = {
    "inactif": "inactif (décoché)",
    "incomplet": "incomplet (il manque un réglage)",
    "jamais": "pas encore joint",
    "connecte": "connecté",
    "erreur": "en erreur (il réessaie au prochain appel)",
    "panne": "en panne (trop d'échecs d'affilée : à relancer)",
}


@dataclass(frozen=True, slots=True)
class LiveTool:
    """Un outil tel que le serveur le décrit **maintenant** (une donnée venue d'ailleurs, bornée)."""

    remote: str
    title: str
    description: str
    schema: Mapping[str, Any]
    annotations: Mapping[str, Any]
    fingerprint: str

    @property
    def read_only_hint(self) -> bool:
        return bool(self.annotations.get("readOnlyHint"))


@dataclass(frozen=True, slots=True)
class ToolReview:
    """Ce que l'opérateur a approuvé d'un outil : l'instantané servi (empreinte, schéma, description du
    serveur), et ce qu'il en a décidé."""

    remote: str
    fingerprint: str
    enabled: bool = False
    nature: str = "lecture"
    approval: str = "conversation"
    #: la description qu'elle lit (vide : celle du serveur, désamorcée)
    description: str = ""
    server_description: str = ""
    title: str = ""
    schema: Mapping[str, Any] = field(default_factory=dict)
    by: str = ""
    at: int = 0


@dataclass(frozen=True, slots=True)
class OfferedTool:
    """Un outil prêt à lui être offert : approuvé, actif, son serveur joint, son empreinte inchangée."""

    server: str
    remote: str
    #: son nom chez elle (``mcp_<serveur>_<outil>``, ce qu'acceptent les fournisseurs)
    name: str
    description: str
    schema: Mapping[str, Any]
    nature: str
    approval: str
    audience: str
    episodes: frozenset[str]
    in_hand: bool
    max_calls: int
    max_result_chars: int
    #: à quoi sert son serveur, pour elle (la ligne de son catalogue) et quand s'en servir
    purpose: str
    when_to_use: str
    local: bool
    #: l'empreinte approuvée (un appel proposé l'épingle : s'il change avant l'accord, l'accord est refusé)
    fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ServerStatus:
    name: str
    kind: str
    enabled: bool
    ready: bool
    state: str
    detail: str = ""
    #: ce que l'opérateur a déclaré (sans secret) : à quoi il sert pour elle, quand, où le joindre, pour qui
    purpose: str = ""
    when_to_use: str = ""
    address: str = ""
    audience: str = "proprietaire"
    episodes: tuple[str, ...] = ()
    in_hand: bool = False
    server_name: str = ""
    server_version: str = ""
    protocol: str = ""
    #: ce que le serveur dit de lui-même (une donnée venue d'ailleurs : montrée à l'opérateur, jamais à elle)
    instructions: str = ""
    live: tuple[LiveTool, ...] = ()
    reviews: Mapping[str, ToolReview] = field(default_factory=dict)
    last_ok_at: int = 0
    last_error_at: int = 0
    calls: int = 0
    failures: int = 0
    consecutive: int = 0
    #: la fin de la sortie d'erreur d'un serveur lancé ici, quand il est tombé (secrets masqués)
    log: tuple[str, ...] = ()

    @property
    def new(self) -> tuple[str, ...]:
        """Les outils que le serveur propose et que l'opérateur n'a jamais regardés."""
        return tuple(t.remote for t in self.live if t.remote not in self.reviews)

    @property
    def changed(self) -> tuple[str, ...]:
        """Les outils approuvés dont le serveur a changé la description, le schéma ou les annotations : suspendus."""
        return tuple(t.remote for t in self.live if t.remote in self.reviews
                     and self.reviews[t.remote].enabled and self.reviews[t.remote].fingerprint != t.fingerprint)

    @property
    def missing(self) -> tuple[str, ...]:
        """Les outils approuvés que le serveur ne propose plus."""
        live = {t.remote for t in self.live}
        return tuple(r for r, v in self.reviews.items() if v.enabled and r not in live) if self.live else ()


@dataclass(frozen=True, slots=True)
class CallResult:
    """Ce qu'un appel a rendu. ``reached`` : le serveur a répondu (même par une erreur) — faux pour une panne de
    transport (injoignable, délai, refusé), ce qui compte pour son disjoncteur."""

    ok: bool
    text: str
    reached: bool = True


class ExternalTools(Protocol):
    def offered(self) -> Sequence[OfferedTool]: ...

    def statuses(self) -> Sequence[ServerStatus]: ...

    def status(self, server: str) -> ServerStatus | None: ...

    async def call(self, server: str, remote: str, args: Mapping[str, Any], *,
                   timeout_s: float | None = None) -> CallResult: ...

    async def test(self, server: str) -> tuple[bool, str]: ...

    async def refresh(self, server: str | None = None) -> None: ...

    async def review(self, server: str, remote: str, *, enabled: bool, nature: str, approval: str,
                     description: str, by: str) -> ToolReview: ...

    def on_change(self, fn: Callable[[], Awaitable[Any] | Any]) -> None: ...

    def failing(self) -> list[str]: ...

    def keep(self, request: str, text: str) -> None:
        """Garder en mémoire, le temps qu'elle soit journalisée comme un contenu, la réponse d'un appel exécuté
        après accord (le résultat d'un effet, lui, n'est pas effaçable)."""
        ...

    def take(self, request: str) -> str | None: ...
