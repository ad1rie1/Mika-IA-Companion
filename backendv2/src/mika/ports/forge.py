"""Le port de la Forge : les petites apps qu'elle écrit elle-même, exécutées
**hors de son processus**.

Une app est un dossier (``manifest.yaml`` + ``main.py``) ; elle tourne dans
un processus isolé (bubblewrap : sans réseau, sans les bases, sans
l'environnement du serveur, mémoire et temps bornés — un délai dépassé tue le
processus). Elle ne parle au monde que par l'hôte : un stockage clé/valeur à
elle, sa configuration, un journal, ``http_get`` vers les seuls domaines
qu'elle déclare, et des **signaux** (ce qu'elle veut porter à l'attention de
Mika) que le plugin journalise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ForgeRefused(ValueError):
    """Une écriture refusée (manifeste invalide, code qui ne passe pas la relecture)."""


@dataclass(frozen=True, slots=True)
class AppTool:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AppInfo:
    name: str
    title: str
    description: str = ""
    version: int = 0
    schedule: str = ""
    context: bool = False
    tools: tuple[AppTool, ...] = ()
    handlers: tuple[str, ...] = ()
    #: un manifeste illisible (l'app existe mais ne peut pas tourner)
    error: str = ""
    #: les événements qu'elle veut recevoir (``on_event``)
    events: tuple[str, ...] = ()
    #: les réglages que déclare son manifeste, avec leur valeur par défaut
    config: tuple[tuple[str, str | int | float | bool], ...] = ()


@dataclass(frozen=True, slots=True)
class CallResult:
    ok: bool
    value: Any = None
    error: str = ""
    killed: bool = False  # tuée à son délai, ou morte (mémoire, CPU)
    duration_ms: int = 0
    logs: tuple[str, ...] = ()
    #: ce que l'app a voulu signaler : (résumé, pertinence, émotion)
    signals: tuple[tuple[str, float, str], ...] = ()
    #: ce qu'elle a émis : (type, données JSON)
    emits: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class ForgePort(Protocol):
    def apps(self) -> list[AppInfo]: ...

    def info(self, app: str) -> AppInfo | None: ...

    def source(self, app: str) -> tuple[str, str] | None:
        """(manifeste, code), ou ``None``."""
        ...

    async def write(self, app: str, manifest: str, code: str) -> tuple[int, list[str]]:
        """Écrit (en archivant la version précédente) ; rend (version, remarques).
        Lève ``ForgeRefused`` sans rien changer si c'est refusé."""
        ...

    async def rollback(self, app: str) -> int: ...

    async def erase(self, app: str) -> str: ...

    async def reset_storage(self, app: str) -> int: ...

    async def call(self, app: str, method: str, args: dict[str, Any] | None = None, *,
                   timeout_s: float = 5.0) -> CallResult: ...

    def logs(self, app: str, n: int = 20) -> list[str]: ...
