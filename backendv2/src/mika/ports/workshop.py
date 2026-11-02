"""Le port de l'atelier : le dossier d'un projet, et des programmes qu'on y lance.

Un atelier est **capable parce qu'il est séparé** : il ne touche rien du
moteur (ni ses bases, ni ses clés, ni son environnement), donc il peut écrire
de vrais fichiers et lancer de vrais programmes — isolés (bubblewrap), sans
réseau par défaut, bornés dans le temps et en sortie. Pas d'isolation
disponible → pas d'exécution : jamais de repli aux droits du serveur.

Tout chemin est **résolu puis vérifié** : ``../..`` comme le lien symbolique
qui sort du dossier sont refusés. Rien ne lève vers l'appelant pour une
commande qui échoue : c'est une information à rendre au modèle.

Un programme est **borné en ressources** (mémoire, temps de calcul, taille d'un
fichier, processus, descripteurs) et sa sortie passe par un tube plafonné : au
dépassement, il est tué. Un atelier trop gros refuse d'écrire ou de lancer
quoi que ce soit d'autre que du ménage. Le réseau, quand une commande approuvée
en a besoin, est **à part** : Internet seulement, jamais la machine hôte ni le
réseau local.

Le dépôt git de l'atelier se lit (historique, un commit, l'état) et peut
**pousser** vers un dépôt distant ou en **récupérer** l'histoire : ces deux-là
ont besoin du réseau et d'un jeton, que l'adaptateur tient lui-même (jamais
l'appelant, jamais le modèle).

L'**hôte** d'un dépôt distant (GitHub, ``RepoHost``) se lit à part, pour la
console seulement : la tête de la branche, ses derniers commits, les issues et
pull requests ouvertes (ADR 0183). Il ne lui écrit rien.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


class OutsideWorkshop(ValueError):
    """Le chemin demandé sort de l'atelier, ou touche à ses organes (``.git``)."""


class WorkshopFull(ValueError):
    """L'atelier dépasse sa taille : il faut faire de la place avant d'écrire."""


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
    parts = [r.summary(), *r.notes]
    if r.stdout.strip():
        parts.append("sortie :\n" + r.stdout[-limit:])
    if r.stderr.strip():
        parts.append("erreurs :\n" + r.stderr[-limit:])
    return "\n".join(parts)


def argv_lines(argv: Sequence[str]) -> str:
    """Une commande montrée à qui l'approuve : **entière et exacte**, un argument par ligne. Un argument qui
    contient un espace, une fin de ligne ou un caractère de contrôle est montré tel que Python l'écrit (entre
    guillemets, échappé) : rien ne s'y cache, rien n'est coupé."""
    out = []
    for i, a in enumerate(str(x) for x in argv):
        plain = a and a.isprintable() and not any(ch.isspace() for ch in a)
        out.append(f"{i:>2}. {a if plain else repr(a)}")
    return "\n".join(out) or "(commande vide)"


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

    async def branch(self, project: int) -> str:
        """La branche courante de l'atelier (``main`` d'ordinaire), ou ``""``."""
        ...

    async def compare(self, project: int, sha: str) -> tuple[int, int] | None:
        """L'atelier face à un commit (la tête du distant) : (ses enregistrements que ce commit n'a pas, ceux de ce
        commit qu'il n'a pas) ; ``None`` s'il ne connaît pas ce commit."""
        ...

    async def push(self, project: int, url: str, branch: str, sha: str = "") -> RunResult:
        """Pousser ce commit (``sha`` : celui qu'on a approuvé ; vide : le courant) vers un dépôt distant https ;
        le jeton est celui de l'adaptateur, et seulement pour les hôtes qu'il autorise."""
        ...

    async def pull(self, project: int, url: str, branch: str) -> RunResult:
        """Récupérer l'histoire d'un dépôt distant : en ligne droite seulement ; un atelier vierge la prend."""
        ...


# ── L'hôte du dépôt distant (ADR 0183) ──


@dataclass(frozen=True, slots=True)
class Ticket:
    """Une issue ou une pull request ouverte chez l'hôte du dépôt distant."""

    number: int
    title: str
    #: sa page chez l'hôte (composée par l'adaptateur, jamais reprise de la réponse)
    url: str
    author: str = ""
    #: sa dernière mise à jour (µs)
    at: int = 0
    labels: tuple[str, ...] = ()
    comments: int = 0
    #: une pull request : sa branche, celle où elle veut entrer, et si c'est un brouillon
    head: str = ""
    base: str = ""
    draft: bool = False


@dataclass(frozen=True, slots=True)
class Hosted:
    """Ce que l'hôte dit d'un dépôt, lu à un instant (``read_at``, µs). ``error`` non vide : il n'a pas répondu, ou
    il refuse — le reste est vide. ``head`` vide sans erreur : la branche n'existe pas encore chez lui."""

    #: « compte/depot », et sa page
    name: str
    url: str
    branch: str
    host: str = "GitHub"
    about: str = ""
    private: bool = False
    #: le commit au bout de la branche (son identifiant complet), et ses derniers commits, du plus récent
    head: str = ""
    commits: tuple[Commit, ...] = ()
    issues: tuple[Ticket, ...] = ()
    pulls: tuple[Ticket, ...] = ()
    #: combien sont ouvertes (au moins : ``more_*`` vrai, l'hôte en a plus que la page lue)
    open_issues: int = 0
    open_pulls: int = 0
    more_issues: bool = False
    more_pulls: bool = False
    read_at: int = 0
    error: str = ""


class RepoHost(Protocol):
    """L'hôte des dépôts distants (GitHub), en lecture seule et pour la console : la branche, ses derniers commits, les
    issues et pull requests ouvertes. Une lecture se garde un moment ; ``fresh`` la refait, ``since`` (µs) aussi
    quand elle est plus ancienne (un envoi, une récupération depuis). Pousser et récupérer restent à l'atelier."""

    def handles(self, url: str) -> bool:
        """Cet hôte sait lire ce dépôt (``https://github.com/compte/depot``)."""
        ...

    async def read(self, url: str, branch: str, *, fresh: bool = False, since: int = 0) -> Hosted: ...

    async def compare(self, url: str, base: str, head: str) -> tuple[int, int] | None:
        """``base`` (un commit de l'atelier) face à ``head`` (la tête du distant) : (les commits de ``base`` que
        ``head`` n'a pas, ceux de ``head`` que ``base`` n'a pas) ; ``None`` si l'hôte ne connaît pas ``base``."""
        ...
