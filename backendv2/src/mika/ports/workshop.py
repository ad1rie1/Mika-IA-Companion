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
console : la tête de la branche, ses derniers commits, les issues et pull
requests ouvertes (ADR 0183). Il s'écrit d'une seule façon (ADR 0274) : ouvrir
la pull request d'une branche de travail (``open_pull``), puis la relire
(``pull``). **Elle ne fusionne jamais** : le port de l'atelier n'a pas de quoi le
faire, et celui de l'hôte n'a qu'une porte (``merge_pull``, ADR 0288) — le geste
d'une personne, jamais un outil, une capacité ni un processus.

Le dépôt se lit aussi **à une référence** (ADR 0288 : une branche, un commit),
pour l'écran d'une personne : ses branches (``branches``), un dossier
(``ref_tree``), un fichier (``ref_file``), son histoire (``history``), un commit
(``change``) et ce qui change d'un commit à un autre, fichier par fichier
(``diff_of``). Ces lectures passent par les objets de git, jamais par l'arbre de
travail : un lien symbolique ne s'y suit pas, et rien n'en sort.

Un projet qui passe par des pull requests travaille **sur des branches** (ADR
0274) : l'atelier se place sur la branche d'un travail (``work_on``), créée
depuis sa branche de base (``BASE_BRANCH``) la première fois ; ce qu'une branche
change face à sa base se mesure (``span``). La base ne reçoit que ce qui est
récupéré du distant.

Un projet qui en lit un autre voit une **vue** de son atelier (``View``, ADR
0260) : le dernier commit de sa branche de base, posé à part, jamais son dossier
en cours de travail. Elle se lit sous ``liens/<n>/…`` (``VIEWS_DIR``,
``view_place``, ``viewed``) — le même chemin pour ses outils, son prompt et les
programmes qu'il lance, où elle est montée en lecture seule. Rien ne s'écrit
chez le projet lu pour la poser, et rien ne s'écrit dans une vue.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit


class OutsideWorkshop(ValueError):
    """Le chemin demandé sort de l'atelier, ou touche à ses organes (``.git``)."""


def hidden_path(path: str) -> bool:
    """Ce chemin porte-t-il un segment caché — qui commence par un point (``.env``, ``.github/…``) ? La règle du
    partage d'un fichier de projet, la même pour ce que l'API d'une personne sert du dépôt — son arbre, un fichier,
    un diff (ADR 0292) : un fichier caché n'en sort pas."""
    return any(part.startswith(".") for part in str(path or "").split("/") if part not in ("", ".", ".."))


#: les fichiers de secrets usuels, qui ne s'enregistrent jamais dans le dépôt d'un atelier (ADR 0292) : ``.env`` et
#: ses variantes — sauf les modèles qu'on versionne exprès
SECRET_KEPT = (".env.example", ".env.sample", ".env.template", ".env.dist")


def secret_file(path: str) -> bool:
    """Ce chemin nomme-t-il un fichier de secrets usuel (``.env``, ``.env.local``, ``.env.production``…) ?"""
    name = str(path or "").rsplit("/", 1)[-1].lower()
    return (name == ".env" or name.startswith(".env.")) and name not in SECRET_KEPT


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


#: le statut d'une commande, relu par ``run_status`` : sortie avec un code, délai dépassé, refusée
EXITED, TIMED_OUT, REFUSED = "code", "timeout", "refused"
#: ce que l'atelier dit d'une commande finie (``RunResult.summary``) : « … — code 0 (12 ms) »
_CODE = re.compile(r"— code (-?\d+) \(\d+ ms\)")
#: là où commence ce que la commande a écrit (``describe``)
_WRITTEN = re.compile(r"\n(?:sortie|erreurs) :\n")


def run_status(text: str) -> tuple[str, int | None]:
    """Le statut d'une commande et son code de sortie, relus dans ce que ``RunResult.summary`` et ``describe``
    écrivent juste au-dessus : ``(EXITED, N)`` pour le dernier « — code N (… ms) », sinon ``(TIMED_OUT, None)``
    pour « délai dépassé », sinon ``(REFUSED, None)`` pour un texte qui commence par « refusé » ou « Refusé » (le
    refus de ``summary``, de ``describe``, et ceux qu'une capacité écrit elle-même) ; ``("", None)`` pour un autre
    texte. Seule compte la tête, avant ce que la commande a écrit (« sortie : », « erreurs : ») : une sortie ne
    contrefait pas le code. Une commande peut tenir sur plusieurs lignes. Les textes déjà gardés au journal se
    relisent ainsi : changer ce que ``summary`` écrit, c'est changer ce qu'on lit ici."""
    head = _WRITTEN.split(text, maxsplit=1)[0]
    codes = _CODE.findall(head)
    if codes:
        return EXITED, int(codes[-1])
    if "délai dépassé" in head:
        return TIMED_OUT, None
    if head.startswith(("Refusé", "refusé")):
        return REFUSED, None
    return "", None


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

    #: son identifiant complet (qui l'affiche le raccourcit)
    sha: str
    #: instant (µs depuis l'époque), tel que git l'a daté
    at: int
    title: str
    author: str = ""
    files: int = 0
    insertions: int = 0
    deletions: int = 0
    #: ce que ``history`` et ``change`` disent de plus (ADR 0288) : la branche où il se trouve (celle de la base, ou
    #: la branche de travail qui le porte en plus d'elle ; vide : on ne le dit pas), s'il est signé par l'atelier
    #: lui-même (elle), et ses parents (deux : une fusion)
    branch: str = ""
    local: bool = False
    parents: tuple[str, ...] = ()


#: la branche de base d'un atelier : celle où il naît, celle que lit la vue qu'un autre projet en a (ADR 0260), et
#: celle d'où part chaque branche de travail (ADR 0274). Elle suit la branche du dépôt distant, quel que soit son nom
#: là-bas, et n'avance que par une récupération
BASE_BRANCH = "main"


#: un nom de branche git que l'atelier et l'hôte du dépôt acceptent
BRANCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")


def check_remote(url: str) -> str:
    """Une adresse de dépôt distant acceptable, ou ``ValueError`` : https, sans identifiants (le jeton est un réglage,
    jamais dans l'adresse), sans « ? » ni « # ». Vide : aucun distant, rendu tel quel — qui en exige un le dit
    lui-même. La seule règle : la faculté la passe à ce qu'on règle, l'atelier à ce qu'il joint."""
    raw = url.strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname or any(ch.isspace() for ch in raw):
        raise ValueError("une adresse https, comme https://github.com/compte/depot.git")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("pas d'identifiants dans l'adresse : le jeton se règle dans Connexions › Dépôts Git")
    if parts.query or parts.fragment or "?" in raw or "#" in raw:
        raise ValueError("une adresse de dépôt, sans « ? » ni « # » (rien de secret ne va dans l'adresse)")
    return raw


def check_branch(branch: str) -> str:
    """Un nom de branche acceptable, ou ``ValueError`` ; vide : la branche de base."""
    raw = (branch or "").strip() or BASE_BRANCH
    if not BRANCH_NAME.match(raw) or ".." in raw or raw.endswith((".lock", "/")):
        raise ValueError(f"nom de branche refusé : {raw[:40]}")
    return raw


@dataclass(frozen=True, slots=True)
class Placed:
    """Où l'atelier se trouve après s'être placé sur une branche de travail (``Workshop.work_on``, ADR 0274)."""

    #: la branche où il est maintenant ; vide : il n'a pas pu s'y placer, et ``why`` dit pourquoi
    branch: str = ""
    #: elle vient d'être créée depuis la base
    created: bool = False
    #: le commit de la base à cet instant (son identifiant complet), et combien d'enregistrements la branche a de plus
    base: str = ""
    ahead: int = 0
    #: un travail resté non enregistré sur une autre branche de travail y a été rangé : ce commit, sur cette branche
    stowed: str = ""
    stowed_on: str = ""
    why: str = ""


@dataclass(frozen=True, slots=True)
class Joined:
    """Ce qu'a donné la base ramenée dans une branche de travail (``Workshop.take_base``, ADR 0280)."""

    #: la branche de travail où la base est entrée ; vide : rien n'a bougé, et ``why`` dit pourquoi
    branch: str = ""
    #: le commit de la base qu'elle a pris (son identifiant complet)
    base: str = ""
    #: la branche avait déjà toute la base : rien n'a bougé
    already: bool = False
    #: les fichiers où la base et la branche se contredisent : leurs marques de conflit sont dans les fichiers, à
    #: résoudre avant d'enregistrer
    conflicts: tuple[str, ...] = ()
    #: ce qui n'était pas enregistré a d'abord été rangé par ce commit, sur la branche
    stowed: str = ""
    why: str = ""


@dataclass(frozen=True, slots=True)
class Span:
    """Ce qu'une branche de travail change face à sa base (``Workshop.span``) : le vrai diff, pas une somme par
    exécution — les fichiers touchés, les lignes ajoutées et retirées, ses enregistrements que la base n'a pas."""

    files: tuple[str, ...] = ()
    insertions: int = 0
    deletions: int = 0
    commits: tuple[Commit, ...] = ()
    #: le commit au bout de la branche (complet), et celui d'où elle s'écarte de la base
    head: str = ""
    base: str = ""


# ── Le dépôt lu à une référence (ADR 0288) ──

#: une entrée d'un dossier (``TreeEntry.kind``) : un dossier, un fichier, un lien symbolique (jamais suivi), un
#: sous-module (jamais ouvert)
ENTRY_DIR, ENTRY_FILE, ENTRY_LINK, ENTRY_MODULE = "dir", "file", "link", "module"
#: ce qu'un fichier est devenu d'un commit à un autre (``FileDiff.status``)
FILE_ADDED, FILE_MODIFIED, FILE_DELETED = "added", "modified", "deleted"
#: une ligne d'un diff (``DiffLine.kind``) : inchangée, ajoutée, retirée
LINE_SAME, LINE_ADDED, LINE_REMOVED = " ", "+", "-"
#: les entrées d'un dossier qu'une lecture rend, au plus ; une ligne de diff, au plus (caractères)
TREE_MAX, DIFF_LINE_MAX = 1000, 500


@dataclass(frozen=True, slots=True)
class Branch:
    """Une branche du dépôt de l'atelier (``Workshop.branches``) : le commit à son bout, et son écart avec la base —
    ses enregistrements que la base n'a pas (``ahead``), ceux de la base qu'elle n'a pas (``behind``)."""

    name: str
    head: Commit
    ahead: int = 0
    behind: int = 0
    #: c'est la branche de base ; c'est celle où l'atelier se trouve
    base: bool = False
    current: bool = False


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """Une entrée d'un dossier à une référence (``Workshop.ref_tree``) : son chemin depuis la racine du dépôt, sa
    sorte (``ENTRY_*``) et, pour un fichier, sa taille (octets)."""

    path: str
    kind: str = ENTRY_FILE
    size: int = 0


@dataclass(frozen=True, slots=True)
class Blob:
    """Un fichier à une référence (``Workshop.ref_file``). Son texte n'est rendu que s'il en est un et qu'il tient
    sous la borne : un fichier binaire (``binary``), trop gros (``too_big``), un lien symbolique ou un sous-module
    (``kind``) se disent, sans contenu."""

    path: str
    #: le commit où il a été lu (son identifiant complet)
    sha: str = ""
    kind: str = ENTRY_FILE
    size: int = 0
    binary: bool = False
    too_big: bool = False
    text: str = ""


@dataclass(frozen=True, slots=True)
class History:
    """Une page de l'histoire d'une référence (``Workshop.history``), du plus récent, et combien elle en compte."""

    commits: tuple[Commit, ...] = ()
    total: int = 0


@dataclass(frozen=True, slots=True)
class Change:
    """Un commit lu de près (``Workshop.change``) : lui (ses parents compris) et son message entier, borné."""

    commit: Commit
    body: str = ""


@dataclass(frozen=True, slots=True)
class DiffLine:
    """Une ligne d'un diff : sa sorte (``LINE_*``), son numéro avant et après (0 : elle n'y est pas), son texte
    (coupé à ``DIFF_LINE_MAX``)."""

    kind: str
    old: int = 0
    new: int = 0
    text: str = ""


@dataclass(frozen=True, slots=True)
class Hunk:
    """Un passage d'un diff : son en-tête (« @@ -1,9 +1,22 @@ … ») et ses lignes."""

    header: str
    lines: tuple[DiffLine, ...] = ()


@dataclass(frozen=True, slots=True)
class FileDiff:
    """Ce qu'un fichier change d'un commit à un autre (``Workshop.diff_of``) : son chemin, ce qu'il est devenu
    (``FILE_*``), ses lignes ajoutées et retirées (0 pour un binaire), et ses passages. ``cut`` : ses passages ne
    sont pas tous là — la borne du diff était atteinte ; il se relit seul (``path``)."""

    path: str
    status: str = FILE_MODIFIED
    insertions: int = 0
    deletions: int = 0
    binary: bool = False
    cut: bool = False
    hunks: tuple[Hunk, ...] = ()


#: le dossier, dans l'atelier d'un projet lecteur, où se lisent les vues des ateliers qu'il lit (ADR 0260) :
#: ``liens/<n>/…``, ``n`` étant le numéro du projet lu
VIEWS_DIR = "liens"
#: pourquoi un projet lu n'a pas de vue (``View.why`` ; les clés de ``projects.links.view.none`` dans sa voix : NE PAS
#: RENOMMER) : sa branche de base n'a aucun commit ; son dernier commit dépasse la place d'une vue ; son dépôt ne se
#: lit pas pour l'instant
NO_COMMIT, TOO_BIG, UNREADABLE = "no_commit", "too_big", "unreadable"


def view_place(target: int, rel: str = "") -> str:
    """Où se lit la vue du projet ``target``, ou un de ses fichiers : ``liens/<n>`` puis ``rel`` — le chemin que
    disent ses outils et son prompt, et que voient les programmes qu'elle lance."""
    rest = rel.strip().strip("/")
    return f"{VIEWS_DIR}/{int(target)}" + (f"/{rest}" if rest and rest != "." else "")


def viewed(path: str) -> tuple[int, str] | None:
    """Ce chemin vise-t-il la vue d'un projet lu ? Son numéro et le reste du chemin (``"."`` : la racine de la vue) ;
    ``None`` : un chemin de l'atelier lui-même. Le chemin est d'abord réduit (``a/../liens/3/x`` vise la vue) ; seul
    un numéro écrit comme on le dit (``3``, pas ``03``) en désigne une."""
    raw = str(path or "").strip()
    if not raw or raw.startswith("/"):
        return None
    parts = [x for x in posixpath.normpath(raw).split("/") if x and x != "."]
    # ``isdecimal``, pas ``isdigit`` : « ² » est un chiffre pour ``isdigit``, et ``int("²")`` lève
    if len(parts) < 2 or parts[0] != VIEWS_DIR or not parts[1].isdecimal() or str(int(parts[1])) != parts[1]:
        return None
    return int(parts[1]), "/".join(parts[2:]) or "."


#: une ligne d'arbre d'une vue, au plus (caractères)
VIEW_ENTRY_MAX = 200


def view_entry(line: str, limit: int = VIEW_ENTRY_MAX) -> str:
    """Une ligne d'arbre d'une vue, telle qu'on la montre (ADR 0262) : le nom d'un fichier d'un autre projet entre
    dans le prompt du lecteur et dans ce que rendent ses outils — c'est une donnée, et un dépôt récupéré d'ailleurs
    peut en porter de piégés. Tout caractère qui ne s'imprime pas (un saut de ligne, un retour chariot, un contrôle,
    un séparateur de ligne Unicode) devient « ? » : un nom de fichier ne fait jamais une ligne de plus. Au-delà de
    ``limit``, la ligne est coupée par le milieu : son début (où elle est) et sa fin (son nom, sa taille) restent."""
    plain = "".join(ch if ch.isprintable() else "?" for ch in str(line))
    if len(plain) <= limit:
        return plain
    head = (limit - 1) // 2
    return plain[:head] + "…" + plain[len(plain) - (limit - 1 - head):]


@dataclass(frozen=True, slots=True)
class View:
    """La vue qu'un projet a de l'atelier d'un projet qu'il lit (ADR 0260) : le dernier commit de sa branche de
    base, posé à part et en lecture seule."""

    #: le projet lu
    project: int
    #: le commit vu (son identifiant complet) ; vide : pas de vue, et ``why`` dit pourquoi
    sha: str = ""
    #: l'instant de ce commit (µs depuis l'époque), tel que git l'a daté
    at: int = 0
    #: ``NO_COMMIT``, ``TOO_BIG`` ou ``UNREADABLE`` quand il n'y a pas de vue
    why: str = ""


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
                  network: bool = False, views: Sequence[int] = ()) -> RunResult:
        """Lance un programme dans l'atelier. ``views`` : les projets lus dont la vue est montée, en lecture seule,
        sous ``liens/<n>/`` (ADR 0260) — jamais pour une commande réseau."""
        ...

    async def commit(self, project: int, message: str, paths: Sequence[str] = ()) -> str:
        """Enregistre l'état s'il a changé (``paths`` : ces chemins seulement) ; rend l'identifiant complet du
        commit, ou ``""``. Partout où ce port rend un commit qui se compare (``commit``, ``head``, ``commits``,
        ``span``, ``sent``), c'est son identifiant complet : l'abrégé n'est qu'un affichage (``log``)."""
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

    async def base(self, project: int) -> str:
        """Le commit au bout de la branche de base de l'atelier (son identifiant complet), ou ``""`` : ce qu'un
        projet lecteur en voit (ADR 0260, 0280), où que l'atelier se trouve."""
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
        """Récupérer l'histoire d'un dépôt distant dans la branche de base : en ligne droite seulement ; un atelier
        vierge la prend. Un atelier placé sur une branche de travail n'est pas touché : seule sa base avance (ADR
        0274)."""
        ...

    async def work_on(self, project: int, branch: str, *, stow: str = "") -> Placed:
        """Placer l'atelier sur une branche de travail (ADR 0274) : créée depuis la base si elle n'existe pas,
        retrouvée sinon. Ce qui n'était pas enregistré sur une autre branche de travail y est d'abord rangé par un
        commit (``stow`` : son message) ; resté sur la base, il suit sur la branche. Jamais la base elle-même. Déjà
        sur la branche : rien ne bouge."""
        ...

    async def take_base(self, project: int, branch: str, *, stow: str = "") -> Joined:
        """Ramener la base dans la branche de travail où l'atelier se trouve (ADR 0280) : ce que la base a reçu
        depuis que la branche en est partie y entre, sans enregistrer — l'enregistrement de l'exécution le fera. Ce
        qui n'était pas enregistré est d'abord rangé par un commit (``stow`` : son message). Là où la base et la
        branche se contredisent, les marques de conflit restent dans les fichiers, nommés dans ``conflicts``. La
        base elle-même n'est jamais écrite, et rien ne part chez l'hôte. Une entrée déjà en cours est redite telle
        qu'elle est. Jamais la base, jamais une autre branche que celle où l'atelier se trouve."""
        ...

    async def unresolved(self, project: int) -> list[str]:
        """Les fichiers qui portent encore des marques de conflit, tant que la base ramenée dans la branche n'est
        pas enregistrée (ADR 0280) ; vide : rien n'est en cours, ou tout est résolu."""
        ...

    async def span(self, project: int, branch: str) -> Span | None:
        """Ce que cette branche change face à la base (``None`` : pas de dépôt, ou une branche inconnue)."""
        ...

    async def patch(self, project: int, since: str, head: str, limit: int = 60_000) -> str | None:
        """Le texte de ce qui change d'un commit à un autre (ADR 0276 : ce qu'une relecture lit) — le résumé par
        fichier, puis le diff, coupé à ``limit`` caractères. ``since`` vide : depuis le début du dépôt. ``None`` :
        pas de dépôt, ou un commit inconnu."""
        ...

    async def branches(self, project: int) -> list[Branch]:
        """Les branches du dépôt (ADR 0288), la base d'abord, puis par nom : pour chacune le commit à son bout et son
        écart avec la base. Vide : pas de dépôt."""
        ...

    async def ref_tree(self, project: int, ref: str, path: str = ".") -> list[TreeEntry] | None:
        """Un dossier du dépôt à une référence — une branche, ou un commit — (ADR 0288) : ses entrées directes, les
        dossiers d'abord, ``TREE_MAX`` au plus. Lu dans les objets de git, pas dans l'arbre de travail. ``None`` :
        pas de dépôt, ou une référence inconnue. Lève ``OutsideWorkshop`` pour un chemin absolu ou qui remonte
        (``..``), ``FileNotFoundError`` si ce n'est pas un dossier de ce commit."""
        ...

    async def ref_file(self, project: int, ref: str, path: str, limit: int = 400_000) -> Blob | None:
        """Un fichier du dépôt à une référence (ADR 0288) : son texte s'il en est un et qu'il pèse au plus ``limit``
        octets ; sinon ce qu'il est (binaire, trop gros, un lien symbolique — jamais suivi —, un sous-module), sans
        contenu. ``None`` : pas de dépôt, ou une référence inconnue. Lève ``OutsideWorkshop`` et
        ``FileNotFoundError`` comme ``ref_tree``."""
        ...

    async def history(self, project: int, ref: str = "", *, path: str = "", n: int = 25,
                      offset: int = 0) -> History | None:
        """L'histoire d'une référence (ADR 0288), du plus récent : ses commits, chacun avec la branche qui le porte
        (``Commit.branch``), s'il est d'elle (``local``) et ses parents ; et leur nombre. ``ref`` vide : toutes les
        branches. ``path`` : seulement ceux qui ont touché ce chemin. ``None`` : pas de dépôt, ou une référence
        inconnue. Lève ``OutsideWorkshop`` pour un chemin qui sort."""
        ...

    async def change(self, project: int, sha: str) -> Change | None:
        """Un commit (ADR 0288) : lui, ses parents, son message entier (borné). ``None`` : pas de dépôt, ou un
        commit inconnu."""
        ...

    async def diff_of(self, project: int, since: str, head: str, *, path: str = "",
                      lines: int = 3000) -> tuple[FileDiff, ...] | None:
        """Ce qui change de ``since`` à ``head``, fichier par fichier (ADR 0288) : ses comptes, ses passages et leurs
        lignes numérotées — ``lines`` lignes au plus en tout ; au-delà, les fichiers restants gardent leurs comptes
        et disent ``cut``. ``since`` vide : depuis le début du dépôt. ``path`` : ce fichier seulement. Ni pilote de
        diff externe, ni conversion de texte, ni renommage deviné. ``None`` : pas de dépôt, ou un commit inconnu."""
        ...

    async def sent(self, project: int, url: str, branch: str) -> str:
        """Le dernier commit que ce dépôt distant possède sur cette branche, tel que l'atelier le sait (ADR 0277) :
        son dernier envoi réussi, ou sa dernière récupération — son identifiant complet. ``""`` : il n'en sait rien
        (jamais envoyé ni récupéré à cette adresse)."""
        ...

    async def checkout(self, project: int, sha: str) -> str:
        """Poser une copie jetable du commit ``sha`` de cet atelier, dans un dossier à part (ADR 0277 : ce qu'une
        relecture lit, et où elle lance ses commandes). L'atelier n'est ni déplacé ni écrit. Une seule copie à la
        fois par projet : poser un autre commit remplace celle d'avant ; déjà posée, elle sert telle quelle. Rend
        pourquoi elle n'est pas posée (``NO_COMMIT``, ``TOO_BIG``, ``UNREADABLE``) — vide : elle l'est."""
        ...

    async def copy_tree(self, project: int, sha: str, path: str = ".") -> list[str]:
        """Les fichiers de la copie posée de ce commit (ou d'un de ses dossiers), comme ``tree``. Lève
        ``OutsideWorkshop`` pour un chemin qui en sort, ``FileNotFoundError`` si elle n'est pas posée."""
        ...

    async def copy_read(self, project: int, sha: str, path: str) -> str:
        """Un fichier de la copie posée de ce commit, comme ``read``."""
        ...

    async def copy_run(self, project: int, sha: str, argv: Sequence[str], *, timeout_s: float | None = None,
                       views: Sequence[int] = ()) -> RunResult:
        """Lance un programme dans la copie posée de ce commit, sans réseau : ce qu'il écrit reste dans la copie,
        rien dans l'atelier. ``views`` : comme ``run``."""
        ...

    async def discard(self, project: int) -> None:
        """Efface la copie de commit de ce projet, s'il en a une."""
        ...

    async def view(self, reader: int, target: int, *, fresh: bool = False) -> View:
        """La vue qu'a le projet ``reader`` de l'atelier du projet ``target`` (ADR 0260) : le dernier commit de sa
        branche de base, dans un dossier à part — rien ne s'écrit chez ``target``. ``fresh`` (au départ d'une
        exécution) : la tête est relue, et la vue reposée si elle a bougé ; sinon la vue déjà posée sert telle
        quelle, et n'est posée que si elle manque. Sans vue, ``View.why`` dit pourquoi."""
        ...

    async def view_tree(self, reader: int, target: int, path: str = ".") -> list[str]:
        """Les fichiers de la vue posée (ou d'un de ses dossiers), comme ``tree``, chacun sous son chemin
        ``liens/<n>/…`` ; ``path`` est relatif à la vue. Lève ``OutsideWorkshop`` pour un chemin qui en sort,
        ``FileNotFoundError`` si aucune vue n'est posée."""
        ...

    async def view_read(self, reader: int, target: int, path: str) -> str:
        """Un fichier de la vue posée, comme ``read`` ; ``path`` est relatif à la vue."""
        ...

    async def drop_views(self, reader: int, keep: Sequence[int] = ()) -> None:
        """Supprime les vues du projet ``reader``, sauf celles des projets ``keep`` : un droit retiré, un lien
        retiré ou suspendu, un projet archivé ne laissent rien derrière eux."""
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


#: l'état d'une pull request, tel que l'hôte le dit (``Pull.state``) : ouverte, fusionnée, fermée sans fusion ; et ce
#: que ses relecteurs y demandent (``Pull.review``) : des changements, ou rien
PULL_OPEN, PULL_MERGED, PULL_CLOSED = "open", "merged", "closed"
PULL_STATES = (PULL_OPEN, PULL_MERGED, PULL_CLOSED)
REVIEW_CHANGES = "changes"
#: ce qu'on garde, au plus, de ce que l'hôte dit d'une pull request (caractères) ; et de son texte, pour qui la lit
PULL_SAID_MAX = 1200
PULL_BODY_MAX = 8000


@dataclass(frozen=True, slots=True)
class Pull:
    """Une pull request telle que l'hôte la dit, lue à un instant (ADR 0274). ``error`` non vide : il n'a pas
    répondu, ou il refuse. ``state`` vide sans erreur : aucune pull request pour cette branche."""

    number: int = 0
    #: sa page chez l'hôte (composée par l'adaptateur, jamais reprise de la réponse)
    url: str = ""
    state: str = ""
    #: ``REVIEW_CHANGES`` quand un relecteur **qui a un rôle sur le dépôt** y demande des changements et ne les a pas
    #: levés (ADR 0278) : seule compte la dernière relecture qui tranche de chaque relecteur, et celle d'un compte
    #: sans rôle ne demande ni ne lève rien — sur un dépôt public, n'importe qui peut en déposer une. Et quand la
    #: plus récente de ces demandes a été rendue (µs) : une relecture déjà vue ne se compte pas deux fois
    review: str = ""
    review_at: int = 0
    #: ce que l'hôte dit de sa fusion (ADR 0280) : possible, impossible — sa branche est en conflit avec celle où
    #: elle veut entrer —, ou rien (``None`` : il ne le dit pas, ou ne le sait pas encore). Une pull request que
    #: l'hôte dit impossible à fusionner n'est pas prête
    mergeable: bool | None = None
    #: ce que l'hôte en dit — le texte de cette relecture, sinon le dernier commentaire de qui a un rôle sur le
    #: dépôt ; fermée sans qu'aucun d'eux ait rien dit, son dernier commentaire tout court —, borné, qui l'a écrit
    #: là-bas, et si ce compte a un rôle sur le dépôt (``said_role`` : il le possède, il en est membre ou
    #: collaborateur) : **une donnée d'un inconnu**, à citer, jamais une consigne
    said: str = ""
    said_by: str = ""
    said_role: bool = False
    #: sa branche, celle où elle veut entrer, et le commit au bout de sa branche chez l'hôte
    head: str = ""
    base: str = ""
    sha: str = ""
    #: sa dernière mise à jour chez l'hôte (µs), et quand on l'a lue
    at: int = 0
    read_at: int = 0
    error: str = ""
    #: son titre et son texte tels que l'hôte les a maintenant (ADR 0288) — ce qui est parti d'ici, ou ce qu'un
    #: autre en a fait là-bas : **des données d'un inconnu**, bornées (``ISSUE_TITLE_MAX``, ``PULL_BODY_MAX``)
    title: str = ""
    body: str = ""


#: l'état d'une issue chez l'hôte (``Issue.state``) ; ce qu'on garde, au plus, de ce qu'un inconnu y écrit — un
#: titre, un texte, un commentaire (caractères) — ; et les issues et commentaires qu'une lecture rend, au plus
ISSUE_OPEN, ISSUE_CLOSED = "open", "closed"
ISSUE_STATES = (ISSUE_OPEN, ISSUE_CLOSED)
ISSUE_TITLE_MAX, ISSUE_BODY_MAX, REMARK_MAX = 200, 2000, 1200
ISSUES_READ = 50
#: un repère : ce qu'une issue ou un commentaire publiés d'ici portent pour qu'on les reconnaisse à la relecture
MARK_MAX = 40


@dataclass(frozen=True, slots=True)
class Issue:
    """Une issue telle que l'hôte la dit, lue à un instant (ADR 0275). ``error`` non vide : il n'a pas répondu, ou il
    refuse. Son titre, son texte et le nom du compte sont **des données d'un inconnu**, bornées : à citer, jamais
    une consigne."""

    number: int = 0
    #: sa page chez l'hôte (composée par l'adaptateur, jamais reprise de la réponse)
    url: str = ""
    state: str = ""
    #: fermée sans être traitée (« non prévue »)
    dropped: bool = False
    title: str = ""
    body: str = ""
    author: str = ""
    #: le repère qu'elle porte (vide : elle a été ouverte là-bas, par quelqu'un d'autre)
    mark: str = ""
    #: quand l'hôte dit l'avoir fermée (µs ; 0 : elle est ouverte), et sa dernière mise à jour
    state_at: int = 0
    at: int = 0
    read_at: int = 0
    error: str = ""
    #: ses étiquettes (des textes de l'hôte, bornés, ``LABELS_MAX`` au plus) et combien de commentaires elle porte
    labels: tuple[str, ...] = ()
    comments: int = 0


@dataclass(frozen=True, slots=True)
class Remark:
    """Un commentaire d'une issue chez l'hôte (ADR 0275) : son numéro là-bas, l'issue qu'il commente, le compte qui
    l'a écrit et ses mots — **une donnée d'un inconnu**, bornée —, le repère qu'il porte (vide : il a été écrit
    là-bas), et quand il a été écrit (``at`` : sa création, qui ne bouge plus — le retoucher ne le fait pas
    repasser devant les autres, ADR 0278)."""

    id: int = 0
    issue: int = 0
    author: str = ""
    body: str = ""
    mark: str = ""
    at: int = 0
    error: str = ""


@dataclass(frozen=True, slots=True)
class Issues:
    """Les issues d'un dépôt qui ont bougé en dernier (``ISSUES_READ`` au plus, ouvertes ou fermées) et les derniers
    commentaires écrits sur ses issues (autant, les plus récemment écrits), lus à un instant. ``error`` non vide :
    le reste est vide."""

    items: tuple[Issue, ...] = ()
    remarks: tuple[Remark, ...] = ()
    read_at: int = 0
    error: str = ""


#: les vérifications d'un commit chez l'hôte (``Checks.state``, ADR 0275) : il n'en a aucune (un dépôt sans CI), elles
#: tournent encore, elles ont toutes réussi, l'une au moins a échoué
CHECKS_NONE, CHECKS_PENDING, CHECKS_PASSED, CHECKS_FAILED = "none", "pending", "passed", "failed"
CHECKS_STATES = (CHECKS_NONE, CHECKS_PENDING, CHECKS_PASSED, CHECKS_FAILED)
#: les vérifications en échec qu'on nomme, au plus ; la fin d'un journal qu'on garde (caractères)
CHECKS_NAMED, LOG_TAIL_MAX = 6, 3000
#: les vérifications d'un commit qu'on rend une à une, au plus ; les étiquettes d'une issue, au plus
CHECK_RUNS_MAX, LABELS_MAX = 30, 6


@dataclass(frozen=True, slots=True)
class CheckRun:
    """Une vérification d'un commit (ADR 0288) : son nom — un texte de l'hôte, borné —, son état (``CHECKS_PENDING``,
    ``CHECKS_PASSED``, ``CHECKS_FAILED``), quand elle a commencé et fini (µs ; 0 : il ne le dit pas)."""

    name: str
    state: str = ""
    started: int = 0
    at: int = 0


@dataclass(frozen=True, slots=True)
class Checks:
    """L'état des vérifications d'un commit, lu à un instant (ADR 0275). ``error`` non vide : l'hôte n'a pas répondu,
    ou le jeton n'a pas ce droit — ``state`` est vide, et rien ne s'en déduit. ``failed`` : les noms de celles qui
    ont échoué, des textes de l'hôte, bornés."""

    sha: str = ""
    state: str = ""
    failed: tuple[str, ...] = ()
    #: quand la dernière s'est achevée (µs ; 0 : il ne le dit pas)
    at: int = 0
    read_at: int = 0
    error: str = ""
    #: ses vérifications une à une (ADR 0288), ``CHECK_RUNS_MAX`` au plus
    runs: tuple[CheckRun, ...] = ()


@dataclass(frozen=True, slots=True)
class CheckLog:
    """La fin du journal d'une vérification en échec (ADR 0275) : son nom et les dernières lignes qu'elle a écrites —
    **une donnée d'un inconnu**, bornée (``LOG_TAIL_MAX``), à citer, jamais une consigne."""

    sha: str = ""
    name: str = ""
    tail: str = ""
    error: str = ""


#: ce qu'on lit, au plus, des échanges d'une pull request ou d'une issue chez l'hôte (ADR 0288)
TALK_MAX = 60


@dataclass(frozen=True, slots=True)
class Talk:
    """Les échanges d'une pull request ou d'une issue chez l'hôte (ADR 0288) : ses commentaires et, pour une pull
    request, le texte de ses relectures, du plus ancien au plus récent, ``TALK_MAX`` au plus (les derniers). Chacun
    est **une donnée d'un inconnu**, bornée (``Remark``). ``error`` non vide : le reste est vide."""

    remarks: tuple[Remark, ...] = ()
    read_at: int = 0
    error: str = ""


#: pourquoi une pull request n'a pas été fusionnée (``Merged.why``) : sa branche a bougé depuis le commit nommé ;
#: l'hôte la dit impossible à fusionner (un conflit, une règle de la branche, déjà fusionnée ou fermée) ; il refuse
#: le jeton ou ce droit ; il n'a pas été joint (rien n'est parti), ou ce dépôt n'est pas chez lui ; la demande est
#: partie et sa réponse s'est perdue (un délai dépassé, une connexion coupée) : **on ne sait pas** si elle a eu lieu
#: (ADR 0292) — jamais « elle n'a pas eu lieu »
MERGE_MOVED, MERGE_BLOCKED, MERGE_DENIED, MERGE_UNREACHED = "moved", "blocked", "denied", "unreached"
MERGE_UNKNOWN = "unknown"
MERGE_WHYS = (MERGE_MOVED, MERGE_BLOCKED, MERGE_DENIED, MERGE_UNREACHED, MERGE_UNKNOWN)


@dataclass(frozen=True, slots=True)
class Merged:
    """Ce qu'a donné la fusion d'une pull request chez l'hôte (ADR 0288). ``merged`` : elle est fusionnée, et
    ``sha`` est le commit que l'hôte a posé sur la base. Sinon ``why`` (``MERGE_*``) dit pourquoi, et ``error`` le
    dit en mots — composés par l'adaptateur, jamais repris de la réponse."""

    number: int = 0
    merged: bool = False
    sha: str = ""
    why: str = ""
    error: str = ""


class RepoHost(Protocol):
    """L'hôte des dépôts distants (GitHub) : pour la console, la branche, ses derniers commits, les issues et pull
    requests ouvertes — une lecture se garde un moment ; ``fresh`` la refait, ``since`` (µs) aussi quand elle est
    plus ancienne (un envoi, une récupération depuis). Et, pour un projet qui passe par des pull requests (ADR 0274),
    ouvrir celle d'une branche et la relire. Pour le reflet des tickets (ADR 0275), lire les issues et leurs
    commentaires, en ouvrir une, la fermer ou la rouvrir, y publier un commentaire ; et dire les vérifications d'un
    commit. Pousser et récupérer restent à l'atelier. **Fusionner** (``merge_pull``, ADR 0288) est le geste d'une
    personne — le propriétaire du projet, ou qui s'occupe d'elle : aucun outil, aucune capacité, aucun processus
    n'appelle cette méthode."""

    def handles(self, url: str) -> bool:
        """Cet hôte sait lire ce dépôt (``https://github.com/compte/depot``)."""
        ...

    async def read(self, url: str, branch: str, *, fresh: bool = False, since: int = 0) -> Hosted: ...

    async def compare(self, url: str, base: str, head: str) -> tuple[int, int] | None:
        """``base`` (un commit de l'atelier) face à ``head`` (la tête du distant) : (les commits de ``base`` que
        ``head`` n'a pas, ceux de ``head`` que ``base`` n'a pas) ; ``None`` si l'hôte ne connaît pas ``base``."""
        ...

    def writes(self, url: str) -> bool:
        """Cet hôte sait ouvrir une pull request sur ce dépôt (ADR 0274) : un projet qui s'y pousse passe par elles,
        par défaut."""
        ...

    async def open_pull(self, url: str, *, head: str, base: str, title: str, body: str) -> Pull:
        """Ouvrir la pull request de la branche ``head`` vers ``base`` — une seule : s'il y en a déjà une ouverte
        pour cette branche, c'est elle qui est rendue, sans rien écrire."""
        ...

    async def pull(self, url: str, head: str) -> Pull:
        """La pull request de la branche ``head`` — l'ouverte s'il y en a une, sinon la dernière —, relue chez
        l'hôte : son état, ce que ses relecteurs qui ont un rôle sur le dépôt y demandent, ce qu'il en dit."""
        ...

    async def issues(self, url: str) -> Issues:
        """Les issues du dépôt qui ont bougé en dernier, ouvertes ou fermées, et les derniers commentaires faits sur
        ses issues (ADR 0275)."""
        ...

    async def open_issue(self, url: str, *, title: str, body: str, mark: str) -> Issue:
        """Ouvrir une issue qui porte ce repère — une seule : s'il y en a déjà une qui le porte, c'est elle qui est
        rendue, sans rien écrire."""
        ...

    async def set_issue(self, url: str, number: int, *, closed: bool, dropped: bool = False) -> Issue:
        """Fermer une issue (``dropped`` : sans la dire traitée) ou la rouvrir. Rien d'autre d'elle ne change."""
        ...

    async def remark(self, url: str, number: int, *, body: str, mark: str) -> Remark:
        """Publier un commentaire sur une issue, avec ce repère — un seul : déjà publié, il est rendu tel quel."""
        ...

    async def checks(self, url: str, sha: str) -> Checks:
        """L'état des vérifications de ce commit (``CHECKS_NONE`` : l'hôte n'en a aucune)."""
        ...

    async def check_log(self, url: str, sha: str) -> CheckLog:
        """La fin du journal de la première vérification en échec de ce commit."""
        ...

    async def talk(self, url: str, number: int, *, pull: bool = False) -> Talk:
        """Les échanges d'une issue — ou d'une pull request (``pull`` : avec le texte de ses relectures) — chez
        l'hôte (ADR 0288), pour qui la regarde : rien n'en va au journal."""
        ...

    async def merge_pull(self, url: str, number: int, *, sha: str) -> Merged:
        """Fusionner la pull request ``number`` dans sa base (ADR 0288), **seulement si le commit au bout de sa
        branche est ``sha``** — celui que la personne a vu : si la branche a bougé, l'hôte refuse (``MERGE_MOVED``).
        Le geste d'une personne : rien d'autre que l'effet de ce geste n'appelle cette méthode."""
        ...

    async def edit_pull(self, url: str, number: int, *, title: str | None = None, body: str | None = None) -> Pull:
        """Changer le titre et le texte de la pull request ``number`` (ADR 0290 ; ``None`` : inchangé). Rien d'autre
        d'elle ne change : ni son état, ni sa base. Le geste d'une personne, comme la fusion : seul l'effet de ce
        geste appelle cette méthode."""
        ...
