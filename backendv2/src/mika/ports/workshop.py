"""Le port de l'atelier : le dossier d'un but, et des programmes qu'on y lance.

Un atelier est **capable parce qu'il est séparé** : il ne touche rien du
moteur (ni ses bases, ni ses clés, ni son environnement), donc il peut écrire
de vrais fichiers et lancer de vrais programmes — isolés (bubblewrap), sans
réseau par défaut, bornés dans le temps et en sortie. Pas d'isolation
disponible → pas d'exécution : jamais de repli aux droits du serveur.

Tout chemin est **résolu puis vérifié** : ``../..`` comme le lien symbolique
qui sort du dossier sont refusés. Rien ne lève vers l'appelant pour une
commande qui échoue : c'est une information à rendre au modèle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


class OutsideWorkshop(ValueError):
    """Le chemin demandé sort de l'atelier, ou touche à ses organes (``.git``)."""


@dataclass(frozen=True, slots=True)
class RunResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    truncated: bool = False
    refused: str = ""  # non vide : la commande n'a jamais été lancée
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.refused and not self.timed_out and self.returncode == 0

    def summary(self) -> str:
        if self.refused:
            return f"refusé : {self.refused}"
        if self.timed_out:
            return f"{' '.join(self.argv)} — délai dépassé ({self.duration_ms} ms)"
        return f"{' '.join(self.argv)} — code {self.returncode} ({self.duration_ms} ms)"


def describe(r: RunResult, limit: int = 6000) -> str:
    """Ce qu'une commande a donné, racontable au modèle."""
    if r.refused:
        return f"Refusé : {r.refused}"
    parts = [r.summary()]
    if r.stdout.strip():
        parts.append("sortie :\n" + r.stdout[-limit:])
    if r.stderr.strip():
        parts.append("erreurs :\n" + r.stderr[-limit:])
    return "\n".join(parts)


class Workshop(Protocol):
    def exists(self, goal: int) -> bool: ...

    async def tree(self, goal: int, path: str = ".") -> list[str]: ...

    async def read(self, goal: int, path: str) -> str: ...

    async def write(self, goal: int, path: str, content: str) -> str: ...

    async def edit(self, goal: int, path: str, old: str, new: str) -> str: ...

    async def run(self, goal: int, argv: Sequence[str], *, timeout_s: float | None = None,
                  network: bool = False) -> RunResult: ...

    async def commit(self, goal: int, message: str) -> str:
        """Enregistre l'état s'il a changé ; rend l'identifiant court, ou ``""``."""
        ...

    async def diff(self, goal: int) -> str: ...

    async def log(self, goal: int, n: int = 10) -> str: ...
