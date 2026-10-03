"""Le port d'entrée : ce que les adaptateurs (web, Telegram…) peuvent
demander au cœur. Ils ne voient jamais le Mind ni les facultés : ils
soumettent des stimulus, lisent des vues, et reçoivent les livraisons.

Rangé dans ``contracts`` : c'est le contrat public du cœur envers les
adaptateurs, et il parle la langue des contrats (perceptions, présence).
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from mika.contracts import world as w
from mika.contracts.presence import Connected
from mika.contracts.runtime import PerceptionReceived
from mika.kernel.events import Event
from mika.kernel.frame import Frame


@dataclass(frozen=True, slots=True)
class Admission:
    """Ce qu'est devenu un message soumis."""

    status: str  # "accepted" | "overloaded"
    seq: int | None = None
    duplicate: bool = False
    reply: Awaitable[Any] | None = None
    #: elle dort : la réponse attend son réveil (l'écran ne montre pas « Mika écrit… » pendant ce temps)
    held: bool = False


@dataclass(frozen=True, slots=True)
class HistoryRow:
    """Un message du fil tel que la personne le relit : ``text`` est ce qu'elle a tapé et ``attachments`` (JSON)
    ses pièces jointes, par leur nom et leur sorte — ce qu'elle en a perçu reste dans le fil de son prompt. Un
    message d'un journal plus ancien, sans séparation connue, garde son texte perçu et aucune pièce jointe."""

    id: int
    at: int
    role: str
    text: str
    source: str
    emotion: str | None
    emotion_intensity: float | None
    attachments: str


class MindPort(Protocol):
    async def perceive(self, p: PerceptionReceived, *, dedupe_key: str | None = None) -> Admission: ...

    async def connected(self, c: Connected) -> None: ...

    async def disconnected(self, handle: str, connection: str) -> None: ...

    def frame(self) -> Frame: ...

    def recent(self, handle: str, limit: int) -> list[HistoryRow]: ...

    def after(self, handle: str, after_id: int, limit: int) -> tuple[list[HistoryRow], bool]: ...

    def life(self) -> str:
        """L'empreinte de sa vie : la même tant que c'est le même journal depuis sa genèse (une sauvegarde
        restaurée comprise), une autre pour un autre dossier de données. Opaque ; vide si inconnue. Un écran
        qui garde le fil d'une autre vie le vide avant de fusionner."""
        ...

    def ready(self) -> bool: ...

    def health(self) -> dict[str, Any]:
        """``{"status", "ready", "checks": {nom: état}}`` : des noms et des états,
        jamais un contenu (la route est publique)."""
        ...

    def person_panel(self, handle: str) -> dict[str, Any] | None:
        """Ce que le panneau montre de la personne (identité ; profil et
        promesses seulement si sa fiche est ouverte ; projets et actions en
        attente seulement pour une propriétaire)."""
        ...

    async def sense(self, device: str, text: str, *, pertinence: float = 0.5, emotion: str = "",
                    sensitivity: int = 1) -> int | None:
        """Un appareil lui signale quelque chose ; rend le ``seq`` (``None`` : refusé)."""
        ...

    async def resolve_effect(self, proposal: int, approved: bool, *, by: str, note: str = "",
                             seen: str = "") -> str:
        """Approuver ou refuser un effet externe proposé : ``"approved"``,
        ``"rejected"``, ``"unknown"`` (rien en attente sous ce numéro)."""
        ...

    # ── le monde (ADR 0050, 0051) ──
    def world_view(self) -> tuple[w.WorldDef, w.WorldState]:
        """La définition en vigueur et l'état vécu, lus sur la même racine (``WorldState.seq`` : le dernier
        événement qui a changé le monde)."""
        ...

    async def world_command(self, command: w.Command, *, actor: str, handle: str | None, operator: bool,
                            session: str | None = None) -> w.CommandResult:
        """Ce que le noyau fait d'une commande d'un client du monde, pour l'acteur qu'il incarne : validée par la
        faculté ``world``, journalisée si elle est acceptée. ``session`` : la connexion qui l'envoie (sa clé de
        dédoublonnage au journal, ``<session>:<cmd>``)."""
        ...

    def world_events(self, after: int, *, limit: int) -> list[Event[Any]] | None:
        """Ce qui a changé ce que montrent les écrans du monde après ``after``, jusqu'à la tête publiée : les
        événements que le monde réduit (les siens et ceux d'autres facultés, comme l'endormissement) et ceux
        qu'il diffuse sans les réduire (gestes, présences) — jamais ce qu'elle remarque ni la prose. ``None`` :
        plus de ``limit`` (le client recevra un instantané)."""
        ...
