"""Le port de l'atelier : le dossier d'un projet, et des programmes qu'on y lance.

Un atelier est **capable parce qu'il est séparé** : il ne touche rien du
moteur (ni ses bases, ni ses clés, ni son environnement), donc il peut écrire
de vrais fichiers et lancer de vrais programmes — isolés (bubblewrap), sans
réseau par défaut, bornés dans le temps et en sortie. Pas d'isolation
disponible → pas d'exécution : jamais de repli aux droits du serveur.

Tout chemin est **résolu puis vérifié** : ``../..`` comme le lien symbolique
qui sort du dossier sont refusés. Rien ne lève vers l'appelant pour une
commande qui échoue : c'est une information à rendre au modèle.

Le dépôt git de l'atelier se lit (historique, un commit, l'état) et peut
**pousser** vers un dépôt distant ou en **récupérer** l'histoire : ces deux-là
ont besoin du réseau et d'un jeton, que l'adaptateur tient lui-même (jamais
l'appelant, jamais le modèle).
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


@dataclass(frozen=True, slots=True)
class Commit:
    """Un enregistrement du dépôt de l'atelier."""

    sha: str
    #: instant (µs depuis l'époque), tel que git l'a daté
    at: int
    title: str
    author: str = ""
    files: int = 0
    insertions: int = 0
    deletions: int = 0


class Workshop(Protocol):
    def exists(self, project: int) -> bool: ...

    async def tree(self, project: int, path: str = ".") -> list[str]: ...

    async def read(self, project: int, path: str) -> str: ...

    async def write(self, project: int, path: str, content: str) -> str: ...

    async def write_bytes(self, project: int, path: str, data: bytes) -> str:
        """Un fichier tel quel (un dépôt de l'opérateur : une image, un tableau) ; rend son chemin relatif."""
        ...

    async def read_bytes(self, project: int, path: str, limit: int) -> bytes:
        """Les octets d'un fichier, au plus ``limit`` (un téléchargement depuis la console)."""
        ...

    async def edit(self, project: int, path: str, old: str, new: str) -> str: ...

    async def run(self, project: int, argv: Sequence[str], *, timeout_s: float | None = None,
                  network: bool = False) -> RunResult: ...

    async def commit(self, project: int, message: str, paths: Sequence[str] = ()) -> str:
        """Enregistre l'état s'il a changé (``paths`` : ces chemins seulement) ; rend l'identifiant court, ou
        ``""``."""
        ...

    async def pending(self, project: int) -> list[str]:
        """Ce qui n'est pas encore enregistré : chaque chemin modifié, ajouté, supprimé ou nouveau (non suivi)."""
        ...

    async def diff(self, project: int) -> str:
        """Ce qui a changé depuis le dernier enregistrement (``--stat`` puis le détail)."""
        ...

    async def log(self, project: int, n: int = 10, *, offset: int = 0) -> str:
        """L'historique en lignes « sha titre », du plus récent."""
        ...

    async def commits(self, project: int, n: int = 25, *, offset: int = 0) -> list[Commit]:
        """L'historique détaillé (date, auteur, fichiers, lignes), du plus récent."""
        ...

    async def count(self, project: int) -> int:
        """Combien d'enregistrements (0 : pas encore de dépôt)."""
        ...

    async def show(self, project: int, sha: str) -> str:
        """Un enregistrement : son message et son détail (``--stat`` puis le diff)."""
        ...

    async def head(self, project: int) -> str:
        """Le commit courant (son identifiant complet), ou ``""``."""
        ...

    async def push(self, project: int, url: str, branch: str, sha: str = "") -> RunResult:
        """Pousser ce commit (``sha`` : celui qu'on a approuvé ; vide : le courant) vers un dépôt distant https ;
        le jeton est celui de l'adaptateur, et seulement pour les hôtes qu'il autorise."""
        ...

    async def pull(self, project: int, url: str, branch: str) -> RunResult:
        """Récupérer l'histoire d'un dépôt distant : en ligne droite seulement ; un atelier vierge la prend."""
        ...
