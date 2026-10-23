"""Les outils venus d'ailleurs (ADR 0064) : ce que la faculté « mcp » voit des serveurs MCP branchés.

Un serveur est déclaré par l'opérateur (à quoi il sert pour elle, comment le joindre, avec qui, quand, ce qu'elle
fait seule et ce qu'elle en garde : ADR 0128) ; ses outils
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
#: ce qu'elle fait seule d'un serveur (ADR 0128) : s'en servir sans demander ; lire seule et demander pour agir ;
#: demander à chaque appel (une carte à la personne en face) ; ou à sa propriétaire, à chaque appel
AUTONOMIES = (("seule", "seule — elle s'en sert sans demander"),
              ("lit", "lit seule, demande pour agir — lire ne change rien ; créer, envoyer, supprimer : un accord"),
              ("carte", "demande à chaque appel — une carte à la personne en face"),
              ("toi", "te demande à chaque appel — même quand c'est quelqu'un d'autre, ou qu'elle travaille seule"))
#: ce qu'un outil fait seul : comme son service, ou son accord à lui
TOOL_AUTONOMIES = (("service", "comme le service"), ("seule", "seule"), ("carte", "demande à chaque appel"),
                   ("toi", "te demande à chaque appel"))
#: une règle d'outil dans une situation ou pour une personne : comme le service (ou sa situation), un accord, ou non
RULE_LEVELS = (("seule", "oui, seule"), ("carte", "oui, sur accord de la personne"), ("toi", "oui, avec ton accord"),
               ("non", "non"))
#: les situations où un outil a une règle à lui (ADR 0128)
TOOL_SITUATIONS = (("proprietaire", "toi"), ("compte", "une personne qui a un compte"),
                   ("travail", "quand elle travaille seule"))
#: ce qu'elle garde de ce qu'un serveur lui rend (ADR 0128), du plus ouvert au plus serré
KEEPS = (("public", "ce qu'elle sait — peut devenir un savoir, et se raconter"),
         ("perso", "un souvenir — comme ce qu'on lui raconte"),
         ("prive", "une confidence — elle en reparle avec la personne, jamais à quelqu'un d'autre"),
         ("rien", "rien — elle s'en sert sur le moment, puis l'oublie"))
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
    #: son accord à lui (``TOOL_AUTONOMIES``) : ``service`` suit son serveur
    autonomy: str = "service"
    #: ses règles par situation et par personne nommée (``RULE_LEVELS`` ; absente : comme le service, ou sa situation)
    situations: Mapping[str, str] = field(default_factory=dict)
    people: Mapping[str, str] = field(default_factory=dict)
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
    #: son accord quand aucune règle de situation ni de personne ne le change : ``seule``, ``carte`` ou ``toi``
    autonomy: str
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
    #: un outil de lecture d'un serveur dont ce qu'elle lit est public (``keep``) : ce qu'elle y lit en travaillant se
    #: garde comme une lecture (ADR 0085)
    reads_world: bool = False
    #: avec qui (ADR 0128) : sa propriétaire, toute personne qui a un compte, des personnes nommées (leurs clés)
    with_owner: bool = True
    with_accounts: bool = False
    with_people: tuple[str, ...] = ()
    #: ses règles par situation et par personne, triées (``RULE_LEVELS``)
    situations: tuple[tuple[str, str], ...] = ()
    people: tuple[tuple[str, str], ...] = ()
    #: ce qu'elle garde de ce qu'il rend (``KEEPS``)
    keep: str = "perso"


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
    with_owner: bool = True
    with_accounts: bool = False
    with_people: tuple[str, ...] = ()
    autonomy: str = "carte"
    keep: str = "prive"
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

    async def review(self, server: str, remote: str, *, enabled: bool, nature: str, autonomy: str,
                     description: str, by: str) -> ToolReview: ...

    async def rule(self, server: str, remote: str, *, situations: Mapping[str, str], people: Mapping[str, str],
                   by: str) -> ToolReview: ...

    async def settle(self, server: str, changes: Mapping[str, Any]) -> None: ...

    async def plug(self, server: str, changes: Mapping[str, Any]) -> None: ...

    async def serve_new(self, server: str, *, by: str) -> list[str]: ...

    def on_change(self, fn: Callable[[], Awaitable[Any] | Any]) -> None: ...

    def failing(self) -> list[str]: ...

    def keep(self, request: str, text: str) -> None:
        """Garder en mémoire, le temps qu'elle soit journalisée comme un contenu, la réponse d'un appel exécuté
        après accord (le résultat d'un effet, lui, n'est pas effaçable)."""
        ...

    def take(self, request: str) -> str | None: ...
