"""Les outils venus d'ailleurs (ADR 0064) : ce que la faculté « mcp » voit des serveurs MCP branchés.

Un serveur est déclaré par l'opérateur (à quoi il sert pour elle, comment le joindre) ; qui peut quoi se dit par ses
lignes d'accès, lues de haut en bas comme les règles d'un pare-feu, et la ligne par défaut (ADR 0131) ; ses outils
ne lui sont offerts que tels qu'ils ont été **approuvés** — l'empreinte d'un outil (nom, description, schéma,
annotations) qui change le suspend jusqu'à une nouvelle approbation. Le port rend cet instantané approuvé
(``offered``), l'état de chaque serveur, et exécute un appel ; il ne décide jamais à qui un outil est offert (c'est
la porte d'offre du pipeline, avec ce que la faculté déclare).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

# qui une ligne d'accès désigne, quand elle vaut, ce qu'elle laisse faire d'un outil : ceux de ``vocab.access``,
# partagés avec les projets et leurs apps (ADR 0131, 0133)
from mika.vocab.access import CLOSE as CLOSE
from mika.vocab.access import EVERYONE as EVERYONE
from mika.vocab.access import MOMENTS as MOMENTS
from mika.vocab.access import OWNER as OWNER
from mika.vocab.access import PERSON as PERSON
from mika.vocab.access import POLICIES as POLICIES
from mika.vocab.access import WHO_ACCOUNTS as WHO_ACCOUNTS
from mika.vocab.access import WHO_OWNER as WHO_OWNER
from mika.vocab.access import WHO_PERSON as WHO_PERSON
from mika.vocab.access import WORK as WORK

#: la nature d'un outil : lire, ou changer quelque chose ailleurs
NATURES = (("lecture", "lecture — elle lit, rien ne change ailleurs"),
           ("action", "action — ça change quelque chose ailleurs"))
#: ce qu'elle garde de ce qu'un serveur lui rend (ADR 0128), du plus ouvert au plus serré
KEEPS = (("public", "ce qu'elle sait — peut devenir un savoir, et se raconter"),
         ("perso", "un souvenir — comme ce qu'on lui raconte"),
         ("prive", "une confidence — elle en reparle avec la personne, jamais à quelqu'un d'autre"),
         ("rien", "rien — elle s'en sert sur le moment, puis l'oublie"))
#: les familles d'épisodes où un serveur peut servir
EPISODES = MOMENTS


@dataclass(frozen=True, slots=True)
class Access:
    """Une ligne d'accès aux outils d'un serveur (ADR 0131, 0133) : ses sources (``vocab.access`` ; vide : la ligne
    par défaut), quand, ce qu'elle fait d'un outil qui lit et d'un outil qui agit, ce qu'elle garde de ce qu'ils
    rendent, et à quels outils elle s'applique (vide : tous). Les lignes se lisent de haut en bas : pour un outil, la
    première qui le concerne décide ; aucune, c'est la ligne par défaut."""

    who: tuple[str, ...]
    #: ses moments (``MOMENTS``) ; vide : toujours
    when: tuple[str, ...] = ()
    read: str = "non"
    act: str = "non"
    keep: str = "rien"
    tools: tuple[str, ...] = ()

    def concerns(self, remote: str) -> bool:
        return not self.tools or remote in self.tools

    def level(self, nature: str) -> str:
        """Ce qu'elle fait d'un outil de cette nature (``lecture`` ou ``action``)."""
        return self.read if nature == "lecture" else self.act


#: la ligne par défaut d'un service qu'on branche : fermé, comme un pare-feu
CLOSED = Access(who=(), read="non", act="non", keep="rien")


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
    #: la description qu'elle lit (vide : celle du serveur, désamorcée)
    description: str = ""
    server_description: str = ""
    title: str = ""
    schema: Mapping[str, Any] = field(default_factory=dict)
    by: str = ""
    at: int = 0
    #: son nom chez elle (``mcp_<serveur>_<outil>``), celui de ses appels dans les traces
    name: str = ""


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
    #: les familles d'épisodes où une de ses lignes (ou la ligne par défaut) le laisse servir (``EPISODES``)
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
    #: les lignes d'accès de son serveur qui le concernent, dans leur ordre, puis la ligne par défaut (ADR 0131)
    access: tuple[Access, ...] = ()
    default: Access = CLOSED


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
    #: ses lignes d'accès, dans leur ordre, et sa ligne par défaut (ADR 0131)
    access: tuple[Access, ...] = ()
    default: Access = CLOSED
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

    async def review(self, server: str, remote: str, *, enabled: bool, nature: str, description: str,
                     by: str) -> ToolReview: ...

    async def settle(self, server: str, changes: Mapping[str, Any]) -> None: ...

    async def plug(self, server: str, changes: Mapping[str, Any]) -> None: ...

    async def decide(self, server: str, choices: Mapping[str, str], *, by: str) -> dict[str, str]:
        """Les outils nouveaux ou changés, d'un coup (ADR 0129) : ``non`` (coupé), ``lecture`` ou ``action`` (servi,
        tel qu'il est maintenant). Rend ce qui a été appliqué."""
        ...

    def on_change(self, fn: Callable[[], Awaitable[Any] | Any]) -> None: ...

    def failing(self) -> list[str]: ...

    def keep(self, request: str, text: str) -> None:
        """Garder en mémoire, le temps qu'elle soit journalisée comme un contenu, la réponse d'un appel exécuté
        après accord (le résultat d'un effet, lui, n'est pas effaçable)."""
        ...

    def take(self, request: str) -> str | None: ...
