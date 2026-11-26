"""L'atelier réel : un dossier par projet, des programmes isolés par bubblewrap.

- **Confinement des chemins**, un seul contrôle appliqué partout : résoudre,
  puis vérifier l'appartenance (``..`` comme le lien symbolique sortant).
  ``.git`` et la maison de l'atelier ne s'écrivent jamais depuis les outils.
- **Exécution** : bubblewrap (espaces de noms, ``/usr`` en lecture seule, un
  ``/tmp`` éphémère, le dossier seul inscriptible, un environnement
  reconstruit — rien de celui du serveur, donc aucune de ses clés). Comme la
  Forge, le programme est **borné** (``setrlimit`` : mémoire, temps de calcul,
  taille d'un fichier, descripteurs ; ``prlimit`` dans la cage : nombre de
  processus) ; sa sortie passe par un **tube plafonné** (au-delà, il est tué) ;
  un délai, un dépassement ou une **annulation** tuent tout son groupe. Un
  atelier qui dépasse sa taille refuse d'écrire et de lancer autre chose que du
  ménage (``rm``). Sans bubblewrap : refus, jamais de repli.
- **Le réseau** n'est jamais celui de l'hôte pour ce que le modèle lance : une
  commande approuvée tourne dans un espace de noms réseau **à part** (``pasta``,
  paquet ``passt``), Internet seulement — la machine hôte (sa boucle locale, ses
  propres adresses), le réseau local et les adresses réservées (métadonnées
  d'un nuage comprises) sont injoignables (routes ``unreachable`` posées avant
  d'entrer dans la cage, que le programme, sans aucune capacité, ne peut pas
  retirer), IPv6 coupé, aucun port relayé. Sans ``pasta`` (ou sans ``ip``), une
  commande réseau du modèle est **refusée**. Les git de l'atelier lui-même
  (pousser, récupérer : un programme fixe, vers l'adresse qu'un opérateur a
  réglée, un dépôt du réseau local compris) gardent le réseau de l'hôte.
- **Git par projet** : un commit d'amorce, puis un commit par exécution qui a
  changé quelque chose (jamais de commit vide). Le ``.git`` est **en lecture
  seule** pour ce que le modèle lance (seul l'atelier y écrit), et les git de
  l'atelier ne lisent aucune configuration globale ni système (``HOME`` dans le
  ``/tmp`` éphémère) : ni le modèle ni un dépôt récupéré ne peuvent régler le git
  qui porte le jeton.
- **Pousser** et **récupérer** parlent à un dépôt distant https : le jeton vient
  d'un réglage (``credentials``), seulement pour les hôtes qu'il autorise, passe
  par l'environnement de git seulement (un en-tête ``Authorization`` limité à
  l'adresse du dépôt), sans assistant d'identification, sans redirection, en https
  seulement, et n'apparaît jamais dans ce qui est rendu (sorties nettoyées avant
  d'être coupées, en clair comme en base64). Un envoi pousse un commit **épinglé**
  (ce qui a été approuvé), pas ce que ``HEAD`` est devenu entre-temps ; une
  récupération ne fait qu'avancer en ligne droite et n'écrase jamais un fichier.
- **Une branche par travail** (ADR 0274) : ``work_on`` place l'atelier sur une
  branche de travail, créée depuis la base (``BASE_BRANCH``) ou retrouvée ; ce
  qui n'était pas enregistré sur une autre branche de travail y est rangé par un
  commit avant de changer, ce qui l'était sur la base suit. ``span`` mesure ce
  qu'une branche change face à la base. Une récupération n'avance que la base :
  sur une branche de travail, ni l'arbre ni la branche ne bougent (un ``fetch``,
  puis la seule référence de la base, en ligne droite). Une base qui n'a que
  son amorce prend l'histoire du distant, et les branches de travail déjà
  parties de l'amorce y sont rejouées (``_adopt``, ADR 0277). Rien ici ne
  fusionne une branche de travail dans la base.
- **L'arbre** d'un atelier se lit depuis git (suivis, et nouveaux non ignorés :
  ni ``.venv`` ni ``node_modules``), en largeur d'abord, chaque entrée par
  ``lstat`` (un lien cassé est une entrée, pas une panne), hors de la boucle.
- **La vue de l'atelier d'un projet lu** (ADR 0260) : le dernier commit de sa
  branche de base (``BASE_BRANCH``, pas la branche où il se trouve), posé dans
  un dossier à part (``.vues/projet-<lecteur>/projet-<lu>/<commit>/``, hors de
  l'atelier du lecteur : ni son arbre, ni son git, ni sa taille ne la comptent).
  Un git en cage lit le dépôt du projet lu, monté **en lecture seule**, et
  n'écrit que là où la vue se pose : rien ne s'écrit chez le projet lu, quoi que
  git veuille. Elle a son propre plafond (``Limits.view_bytes``), mesuré deux
  fois : dans le commit avant de rien poser, puis sur l'arbre réellement posé
  avant de le mettre en place — les attributs du dépôt lu (``ident``,
  ``working-tree-encoding``, ``eol``) grossissent ce que git écrit (ADR 0262).
  Une pose qui n'aboutit pas (annulée par une échéance, ou qui lève) ne laisse
  pas valoir ce qu'on avait mémorisé : l'appel suivant repose à la tête
  courante. Ce que le modèle lance la voit en lecture seule sous
  ``liens/<n>/``, montée sur un dossier vide posé dans l'atelier du lecteur ;
  jamais une commande réseau. Ses chemins sont résolus puis vérifiés comme ceux
  de l'atelier, et là où une vue est posée, rien ne s'écrit. Les lignes de son
  arbre sont des données d'un autre projet : sans caractère de contrôle, et
  coupées (``view_entry``).
- **La copie d'un commit, pour une relecture** (ADR 0277) : le commit épinglé
  d'un atelier, posé comme une vue dans un dossier à part
  (``.relectures/projet-<n>/<commit>/``), une seule à la fois par projet. La
  relecture y lit ses fichiers et y lance ses commandes : dans la cage, la
  copie est montée **à la place de l'atelier** (au même chemin : ses
  environnements, ``.venv`` et ``node_modules``, y sont montés en lecture
  seule), sans son ``.git``, sans réseau. Ce qu'une commande y écrit reste
  dans la copie, effacée ensuite (``discard``) : l'atelier n'est ni déplacé ni
  écrit.
- **Ce que le dépôt distant possède** (``sent``, ADR 0277) : après un envoi
  réussi ou une récupération, une référence à part
  (``refs/atelier/sent/<empreinte de l'adresse et de la branche>``) garde le
  commit que le distant a — d'où part le diff d'une relecture en flux direct.

Les commandes tournent dans un fil (``run_in_executor``) : l'attente du
processus ne bloque pas la boucle ; en simulation, l'exécuteur est en ligne.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import itertools
import os
import re
import resource
import select
import shutil
import signal
import stat
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from mika.adapters import cage
from mika.contracts.self_ import DEFAULT_NAME
from mika.kernel.inspect import size_fr
from mika.kernel.text import fold
from mika.ports.workshop import (
    BASE_BRANCH,
    BRANCH_NAME,
    DIFF_LINE_MAX,
    ENTRY_DIR,
    ENTRY_FILE,
    ENTRY_LINK,
    ENTRY_MODULE,
    FILE_ADDED,
    FILE_DELETED,
    FILE_MODIFIED,
    LINE_ADDED,
    LINE_REMOVED,
    LINE_SAME,
    NO_COMMIT,
    SECRET_KEPT,
    TOO_BIG,
    TREE_MAX,
    UNREADABLE,
    VIEWS_DIR,
    Blob,
    Branch,
    Change,
    Commit,
    DiffLine,
    FileDiff,
    History,
    Hunk,
    Joined,
    OutsideWorkshop,
    Placed,
    RunResult,
    Span,
    TreeEntry,
    View,
    WorkshopFull,
    check_branch,
    check_remote,
    secret_file,
    view_entry,
    view_place,
)

#: ce qu'on peut lancer sans réseau. Ce n'est **pas** une barrière (``sh`` et ``python`` font tout) : c'est la
#: palette des outils qu'on sait présents ; la barrière, c'est la cage (bubblewrap, limites, réseau coupé)
ALLOWED = ("python", "python3", "pytest", "node", "npm", "npx", "git", "ls", "cat", "head", "tail", "wc", "grep",
           "find", "mkdir", "cp", "mv", "rm", "sh", "bash", "echo", "diff", "sort", "make", "pip", "pip3", "uv")
#: ce qu'une commande **approuvée** avec le réseau peut lancer en plus : télécharger
NETWORK_ALLOWED = (*ALLOWED, "curl", "wget")
#: ce qu'on peut encore lancer quand l'atelier est plein : faire de la place
CLEANING = ("rm",)
HOME_DIRNAME = ".atelier-home"
ORGANS = (".git", HOME_DIRNAME)
#: des dossiers qu'un arbre sans git ne parcourt pas (des milliers de fichiers qui ne disent rien du travail)
NOISE = (".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
#: ce que le dépôt de l'atelier ignore : son ``.gitignore`` d'amorce, et son exclusion locale qui survit à un ``reset``
IGNORED = f"{HOME_DIRNAME}/\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n"
#: les fichiers de secrets usuels (ADR 0292) : jamais dans le dépôt — l'atelier enregistre tout ce qu'il trouve
#: (``git add -A``), et une exécution qui crée un ``.env`` le commitait. Dans l'exclusion locale seulement : elle
#: n'est pas versionnée, un dépôt récupéré ne la retire pas, et le ``.gitignore`` du dépôt reste celui du projet
SECRETS_IGNORED = ".env\n.env.*\n" + "".join(f"!{name}\n" for name in SECRET_KEPT)
#: un parcours d'arbre sans git s'arrête après tant d'entrées vues
WALK_MAX = 20_000
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
# la cage est commune (``adapters/cage.py``) : l'atelier et les serveurs MCP lancés ici voient le même système
_SYSTEM_DIRS = cage.SYSTEM_DIRS
NET_ADDRESS, NET_GATEWAY, NET_DNS = cage.NET_ADDRESS, cage.NET_GATEWAY, cage.NET_DNS
UNREACHABLE = cage.UNREACHABLE
# la branche de base d'un atelier (``BASE_BRANCH``, dans le port) : celle où il naît, celle que lit la vue qu'un autre
# projet en a (ADR 0260), celle d'où part chaque branche de travail (ADR 0274)
_GIT = ("-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", f"init.defaultBranch={BASE_BRANCH}")
#: où se posent les vues des ateliers lus, à côté des ateliers : ``.vues/projet-<lecteur>/projet-<lu>/<commit>/``
VIEWS_DIRNAME = ".vues"
#: le délai du git qui pose une vue (il recopie un commit entier)
VIEW_TIMEOUT_S = 120.0
#: où se posent les copies d'un commit qu'une relecture lit (ADR 0277) : ``.relectures/projet-<n>/<commit>/``
REVIEWS_DIRNAME = ".relectures"
#: les environnements d'un atelier, hors de son dépôt, qu'une copie voit en lecture seule
ENVIRONMENTS = (".venv", "node_modules")
#: ce qui ne peut pas entrer dans un nom d'auteur git (une fin de ligne, un chevron d'adresse, un contrôle)
_AUTHOR_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>]")


def author_identity(name: str) -> tuple[str, ...]:
    """Qui signe les enregistrements de l'atelier : son nom (celui de sa persona, que l'application fournit) et une
    adresse locale qui en dérive (« Léa Martin » → ``lea.martin@atelier.local``) — jamais une vraie boîte."""
    shown = " ".join(_AUTHOR_UNSAFE.sub(" ", name).split())[:80] or DEFAULT_NAME
    local = re.sub(r"[^a-z0-9]+", ".", fold(shown)).strip(".") or "atelier"
    return ("-c", f"user.name={shown}", "-c", f"user.email={local}@atelier.local")
#: un identifiant de commit (abrégé ou complet), un identifiant complet (le nom du dossier d'une vue), une branche
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
#: une marque de conflit laissée dans un fichier par la base ramenée dans une branche (ADR 0280) ; et ce qu'on lit,
#: au plus, d'un fichier pour la chercher (octets)
_CONFLICT_MARK = re.compile(rb"^(?:<<<<<<<|>>>>>>>) ", re.MULTILINE)
_MARKS_READ = 4 << 20
#: l'arbre vide de git (le diff « depuis le début du dépôt »), et ce qui dit qu'un diff trop long a été coupé
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_PATCH_CUT = "\n[… le diff est plus long : la suite se lit fichier par fichier …]"
#: ce que git dit d'un enregistrement (``--shortstat``)
_STAT = re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")
REMOTE_TIMEOUT_S = 180.0
#: le dépôt lu à une référence (ADR 0288) : l'en-tête d'un passage de diff ; les branches qu'on rend, au plus ; le
#: message d'un commit, au plus (caractères) ; ce qu'on regarde d'un fichier pour le dire binaire (un octet nul,
#: comme git)
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
BRANCHES_MAX = 100
BODY_MAX_CHARS = 4000
_BINARY_PEEK = 8000
#: l'environnement de tout git de l'atelier : aucune configuration globale ni système, une maison éphémère
_GIT_ENV = {"HOME": "/tmp", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
#: ce qu'un git qui parle au dépôt distant s'interdit : un assistant d'identification (il hériterait du jeton),
#: une redirection (l'en-tête suivrait), un autre protocole que https, un certificat non vérifié
_REMOTE_GIT = ("-c", "credential.helper=", "-c", "http.followRedirects=false", "-c", "protocol.allow=never",
               "-c", "protocol.https.allow=always", "-c", "http.sslVerify=true", "-c", "submodule.recurse=false")
#: les clés de configuration locale qu'un dépôt d'atelier peut avoir (au-delà : refus de parler au distant)
_LOCAL_KEYS = ("core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates",
               "core.symlinks", "core.ignorecase", "core.precomposeunicode")
#: les hôtes à qui le jeton peut être montré, quand le réglage n'en dit rien
DEFAULT_HOSTS = ("github.com",)
SHOW_MAX_CHARS = 200_000
#: les identifiants d'un dépôt distant : ``{"token": …, "user": …}`` (vide : aucun)
Credentials = Callable[[], Mapping[str, str]]
NO_ISOLATED_NETWORK = ("pas de réseau isolé ici (il faut « pasta », du paquet passt, et « ip ») : une commande qui "
                       "a besoin du réseau ne part pas sur celui de la machine")


@dataclass(frozen=True, slots=True)
class Limits:
    """Ce qu'un programme de l'atelier peut prendre (comme les apps de la Forge, plus large : on y compile, on y
    installe). La mémoire est un espace d'adressage : ``node`` en réserve beaucoup, 1 Gio ne lui suffit pas."""

    memory_bytes: int = 2 * 1024 ** 3
    cpu_seconds: int = 900
    file_bytes: int = 256 * 1024 ** 2
    processes: int = 512
    files: int = 1024
    #: par flux (sortie, erreurs) : au-delà, le programme est tué
    output_bytes: int = 8 * 1024 ** 2
    #: au-delà, l'atelier refuse d'écrire et de lancer autre chose que du ménage
    workshop_bytes: int = 2 * 1024 ** 3
    #: la place d'une vue (ADR 0260), à part de celle de l'atelier qui la lit : au-delà, le commit n'est pas posé
    view_bytes: int = 512 * 1024 ** 2


def _remote(url: str) -> str:
    """L'adresse d'un dépôt distant à joindre : acceptable (``ports.workshop.check_remote``), et dite."""
    raw = check_remote(url or "")
    if not raw:
        raise ValueError("une adresse https (https://github.com/compte/depot.git)")
    return raw


def _search_path(root: Path) -> str:
    return f"{root}/.venv/bin:{root}/node_modules/.bin:{SYSTEM_PATH}"


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return text[:half] + f"\n\n[… {len(text) - limit} caractères coupés …]\n\n" + text[-half:], True


def _killpg(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _entry(rel: str, st: os.stat_result) -> str:
    """Une ligne de l'arbre : un lien (même cassé) se dit lien, sans être suivi."""
    return f"{rel} (lien)" if stat.S_ISLNK(st.st_mode) else f"{rel} ({st.st_size} o)"


class _Job:
    """Un programme en cours, que l'appelant peut tuer : une exécution annulée tue ce qu'elle a lancé."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.proc: subprocess.Popen[bytes] | None = None
        self.cancelled = False

    def attach(self, proc: subprocess.Popen[bytes]) -> bool:
        with self._lock:
            self.proc = proc
            return not self.cancelled

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            proc = self.proc
        if proc is not None:
            _killpg(proc)


class BwrapWorkshop:
    def __init__(self, root: Path, *, allowed: Sequence[str] = ALLOWED, timeout_s: float = 120.0,
                 max_output_chars: int = 20_000, max_file_bytes: int = 400_000, max_tree: int = 400,
                 bwrap: str | None = None, which: Callable[[str], str | None] = shutil.which,
                 credentials: Credentials | None = None, limits: Limits = Limits(),
                 pasta: str | None = None, ip: str | None = None, author: Callable[[], str] | None = None) -> None:
        # absolu : bubblewrap reçoit ses chemins et les lit depuis un autre dossier (un ``--data`` relatif cassait
        # la cage, sonde du 2026-10-13)
        self.root = Path(root).resolve()
        self.credentials = credentials
        #: qui signe ses enregistrements : son nom, celui de sa persona (relu à chaque fois : elle peut en changer)
        self.author = author or (lambda: DEFAULT_NAME)
        self.allowed = frozenset(allowed)
        self.network_allowed = self.allowed | (frozenset(NETWORK_ALLOWED) - frozenset(ALLOWED))
        self.timeout_s = timeout_s
        self.max_output = max_output_chars
        self.max_file = max_file_bytes
        self.max_tree = max_tree
        self.limits = limits
        self.bwrap = bwrap if bwrap is not None else which("bwrap")
        self.pasta = pasta if pasta is not None else which("pasta")
        self.ip = ip if ip is not None else which("ip")
        self.sh = which("sh") or "/bin/sh"
        self.prlimit = which("prlimit")
        #: la dernière taille mesurée de chaque atelier (octets)
        self._sizes: dict[int, int] = {}
        #: les vues telles qu'on les a posées, par (lecteur, lu) ; une pose à la fois par lecteur
        self._views: dict[tuple[int, int], View] = {}
        self._view_locks: dict[int, asyncio.Lock] = {}
        self._poses = itertools.count(1)
        #: une pose à la fois par projet pour la copie qu'une relecture lit (ADR 0277)
        self._copy_locks: dict[int, asyncio.Lock] = {}

    # ── le dossier ──
    def folder(self, project: int) -> Path:
        return self.root / f"projet-{int(project)}"

    def exists(self, project: int) -> bool:
        return self.folder(project).is_dir()

    def _has_git(self, project: int) -> bool:
        """L'atelier a-t-il un dépôt ? Un ``.git`` dossier ou fichier (un gitfile) compte ; ``_listed``, qui laisse
        git lister les fichiers, demande un dossier."""
        return (self.folder(project) / ".git").exists()

    def _open(self, project: int) -> Path:
        cage.private_root(self.root)  # ``ateliers/`` : des dépôts, des données personnelles, à elle seule
        d = self.folder(project)
        (d / HOME_DIRNAME).mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _confined(base: Path, rel: str, where: str = "l'atelier") -> Path:
        """Le seul contrôle des chemins : résoudre ``rel`` dans ``base`` (déjà résolu), puis vérifier qu'il y est
        resté — ``..``, un chemin absolu et le lien symbolique qui sort lèvent ``OutsideWorkshop``."""
        raw = str(rel or "").strip()
        if raw and Path(raw).is_absolute():
            raise OutsideWorkshop(f"chemin absolu refusé : {raw} — écris un chemin relatif au dossier")
        target = base / raw if raw and raw not in (".", "./") else base
        try:
            resolved = target.resolve()
        except (OSError, RuntimeError) as exc:  # une boucle de liens
            raise OutsideWorkshop(f"chemin illisible : {raw} ({exc})") from exc
        if resolved != base and not resolved.is_relative_to(base):
            raise OutsideWorkshop(f"hors de {where} : {raw}")
        return resolved

    def path(self, project: int, rel: str, *, write: bool = False) -> Path:
        """Résout ``rel`` dans l'atelier, ou lève ``OutsideWorkshop`` (une lecture ne crée rien)."""
        base = (self._open(project) if write else self.folder(project)).resolve()
        resolved = self._confined(base, rel)
        if write:
            parts = resolved.relative_to(base).parts if resolved != base else ()
            if not parts:
                raise OutsideWorkshop("écris un fichier, pas le dossier lui-même")
            if parts[0] in ORGANS:
                raise OutsideWorkshop(f"« {parts[0]}/ » appartient à l'atelier lui-même : il ne s'écrit pas")
            if len(parts) > 1 and parts[0] == VIEWS_DIR and parts[1].isdecimal() \
                    and str(int(parts[1])) == parts[1] and self._view_home(project, int(parts[1])).exists():
                # là où la vue d'un projet lu est montée, rien ne s'écrit : le fichier serait caché sous elle
                raise OutsideWorkshop(f"« {VIEWS_DIR}/{parts[1]}/ » est la vue d'un projet lu : elle ne s'écrit pas")
        return resolved

    def _rel(self, project: int, p: Path) -> str:
        return str(p.relative_to(self.folder(project).resolve()))

    def full(self, project: int) -> str:
        """Pourquoi l'atelier n'accepte plus rien (vide : il accepte)."""
        size = self._sizes.get(project, 0)
        if size <= self.limits.workshop_bytes:
            return ""
        return (f"l'atelier pèse {size_fr(size)} (au plus {size_fr(self.limits.workshop_bytes)}) : fais de la place "
                "(rm …) avant d'écrire ou de lancer autre chose")

    def _grew(self, project: int, n: int) -> None:
        if project in self._sizes:
            self._sizes[project] += n

    async def _room(self, project: int) -> None:
        """Lève ``WorkshopFull`` si l'atelier dépasse sa taille. Sa taille se mesure une première fois (hors de la
        boucle) au premier besoin : un atelier rempli fichier par fichier, sans jamais rien lancer, est borné lui
        aussi ; ensuite, chaque écriture l'ajoute, et chaque exécution la remesure."""
        if project not in self._sizes and self.exists(project):
            loop = asyncio.get_running_loop()
            self._sizes[project] = await loop.run_in_executor(None, self._measure, self.folder(project))
        if why := self.full(project):
            raise WorkshopFull(why)

    async def tree(self, project: int, path: str = ".") -> list[str]:
        """Les fichiers de l'atelier (ou d'un de ses dossiers), en largeur d'abord : ce que git suit et ce qui est
        nouveau sans être ignoré (ni ``.venv`` ni ``node_modules``), sinon un parcours borné. Chaque entrée est lue
        par ``lstat`` : un lien cassé reste une entrée. Rien de tout ça ne tourne sur la boucle."""
        start = self.path(project, path or ".")
        try:
            st = os.lstat(start)
        except OSError:
            return []
        if not stat.S_ISDIR(st.st_mode):
            return [_entry(self._rel(project, start), st)]
        listed = await self._listed(project)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._tree_sync, project, start, listed)

    async def _listed(self, project: int) -> list[str] | None:
        """Ce que git voit (suivis, et nouveaux non ignorés), ou ``None`` (pas de dépôt, ou git ne répond pas)."""
        if not (self.folder(project) / ".git").is_dir():
            return None
        # une liste lue par le code : coupée au milieu, elle tairait des dossiers entiers ; trop longue, le parcours
        # borné prend le relais
        r = await self._git(project, "-c", "core.quotepath=off", "ls-files", "-z", "--cached", "--others",
                            "--exclude-standard", clip=False)
        if not r.ok or r.truncated:
            return None
        return [p for p in r.stdout.split("\x00") if p]

    def _tree_sync(self, project: int, start: Path, listed: list[str] | None) -> list[str]:
        base = self.folder(project).resolve()
        prefix = "" if start == base else self._rel(project, start) + "/"
        rows: list[tuple[int, str, os.stat_result]] = []
        if listed is not None:
            for rel in dict.fromkeys(listed):
                if (prefix and not rel.startswith(prefix)) or rel.split("/", 1)[0] in ORGANS:
                    continue
                try:
                    rows.append((rel.count("/"), rel, os.lstat(base / rel)))
                except OSError:  # supprimé depuis (encore dans l'index)
                    continue
        else:
            rows = self._walk(base, start)
        return self._listing(rows)

    def _listing(self, rows: list[tuple[int, str, os.stat_result]], prefix: str = "") -> list[str]:
        """Les lignes d'un arbre, les plus proches de la racine d'abord, coupées à ``max_tree`` ; ``prefix`` : ce
        sous quoi ces chemins se disent (``liens/<n>/`` pour une vue — ses lignes, venues d'un autre projet, sont
        alors repliées et coupées : ``view_entry``)."""
        rows.sort(key=lambda r: (r[0], r[1]))
        shown = view_entry if prefix else str
        out = [shown(_entry(prefix + rel, st)) for _, rel, st in rows[: self.max_tree]]
        if len(rows) > self.max_tree:
            out.append(f"[… liste coupée à {self.max_tree} entrées sur {len(rows)} …]")
        return out

    def _walk(self, base: Path, start: Path) -> list[tuple[int, str, os.stat_result]]:
        """Un parcours en largeur de ``start``, borné, qui ne descend ni dans les organes ni dans le bruit ; les
        chemins sont relatifs à ``base`` (l'atelier, ou une vue)."""
        rows: list[tuple[int, str, os.stat_result]] = []
        queue: deque[Path] = deque([start])
        seen = 0
        while queue and seen < WALK_MAX:
            d = queue.popleft()
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                seen += 1
                rel = str(Path(e.path).relative_to(base))
                if rel.split("/", 1)[0] in ORGANS:
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if e.name not in NOISE:
                        queue.append(Path(e.path))
                    continue
                rows.append((rel.count("/"), rel, st))
        return rows

    async def read(self, project: int, path: str) -> str:
        target = self.path(project, path)
        if not target.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier (un dossier se liste avec ws_list)")
        return self._text(target)

    def _text(self, target: Path) -> str:
        """Le texte d'un fichier, borné (``max_file``) : ce qui dépasse est coupé, et dit."""
        with target.open("rb") as f:
            raw = f.read(self.max_file + 1)
        text = raw[: self.max_file].decode("utf-8", errors="replace")
        return text + ("\n\n[… fichier tronqué …]" if len(raw) > self.max_file else "")

    async def write(self, project: int, path: str, content: str) -> str:
        target = self.path(project, path, write=True)
        await self._room(project)
        await self._init(project)  # l'amorce d'abord : le premier travail sera son propre commit
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        self._grew(project, len(str(content).encode()))
        return self._rel(project, target)

    async def write_bytes(self, project: int, path: str, data: bytes) -> str:
        target = self.path(project, path, write=True)
        await self._room(project)
        await self._init(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(data))
        self._grew(project, len(data))
        return self._rel(project, target)

    async def read_bytes(self, project: int, path: str, limit: int) -> bytes:
        target = self.path(project, path)
        if not target.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier")
        with target.open("rb") as f:
            return f.read(max(0, limit))

    async def edit(self, project: int, path: str, old: str, new: str) -> str:
        """Remplacement exact et unique : une édition « à peu près » donne un
        fichier plausible et faux."""
        target = self.path(project, path, write=True)
        if not target.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier")
        await self._room(project)
        await self._init(project)
        # En octets, décodés strictement : un octet non UTF-8 deviendrait « � » sur le disque, et le mode
        # texte changerait les fins de ligne de tout le fichier. Hors du fragment, rien ne bouge.
        try:
            text = target.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"{path} n'est pas un texte UTF-8 — ws_edit l'abîmerait, il reste tel quel") from None
        n = text.count(old)
        if n == 0:
            raise ValueError(f"fragment introuvable dans {path} — relis le fichier avant de l'éditer")
        if n > 1:
            raise ValueError(f"fragment présent {n} fois dans {path} — donne un extrait plus large")
        target.write_bytes(text.replace(old, new, 1).encode("utf-8"))
        self._grew(project, len(new.encode()) - len(old.encode()))
        return self._rel(project, target)

    # ── l'exécution ──
    def _visible(self, program: str, root: Path) -> str | None:
        found = shutil.which(program, path=_search_path(root)) if "/" not in program else str(root / program)
        if not found:
            return None
        real = Path(found).resolve()
        visible = [root, *(Path(d).resolve() for d in _SYSTEM_DIRS if Path(d).exists())]
        if not any(real.is_relative_to(v) for v in visible):
            return None
        return found if real.is_file() and os.access(real, os.X_OK) else None

    def _resolver(self) -> Path:
        """Le résolveur que voit le réseau à part (celui que relaie pasta), jamais celui de l'hôte."""
        return cage.resolver(self.root / ".reseau")

    def _sandbox(self, root: Path, argv: list[str], network: str, protect_git: bool = False,
                 read_only: Sequence[tuple[Path, Path]] = (), source: Path | None = None) -> list[str]:
        """La cage bubblewrap. ``network`` : ``""`` (aucun), ``"isolated"`` (le réseau à part de pasta, posé
        autour), ``"host"`` (celui de l'hôte : les git de l'atelier seulement, faute de pasta). ``read_only`` : des
        dossiers de plus, chacun (ce qu'il est hors de la cage, où il se lit dedans), que le programme lit sans
        pouvoir y écrire — la vue d'un projet lu sous ``liens/<n>/``, le dépôt d'un projet lu pour le git qui la
        pose (ADR 0260). ``source`` : le dossier monté à la place de ``root`` (la copie d'un commit qu'une
        relecture lit, ADR 0277) — ``root`` lui-même n'est alors pas dans la cage."""
        assert self.bwrap is not None
        args = [*cage.head(self.bwrap, network), *cage.system(network)]
        if network == "isolated":
            args += ["--ro-bind", str(self._resolver()), "/etc/resolv.conf"]
        elif network == "host" and Path("/etc/resolv.conf").exists():
            args += ["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf"]
        args += ["--bind", str(source or root), str(root)]
        if protect_git and (root / ".git").is_dir():  # le dépôt est à l'atelier : ce que lance le modèle le lit seulement
            args += ["--ro-bind", str(root / ".git"), str(root / ".git")]
        for source, at in read_only:  # après l'atelier : une vue se monte dedans, par-dessus son dossier vide
            args += cage.read_only(source, at)
        args += ["--chdir", str(root), "--"]
        if self.prlimit and Path(self.prlimit).resolve().is_relative_to("/usr"):
            n = self.limits.processes  # compté dans l'espace de la cage, pas parmi les fils de l'hôte
            args += [self.prlimit, f"--nproc={n}:{n}", "--"]
        return [*args, *argv]

    def _isolated(self, inner: list[str]) -> list[str]:
        """``inner`` (la cage) dans un réseau à part : pasta, IPv4 seulement, aucun port relayé, une passerelle qui
        n'est pas l'hôte, et des routes « unreachable » vers tout ce qui n'est pas Internet (et vers les adresses de
        la machine) — posées avant d'entrer dans la cage, qui n'a ensuite plus aucune capacité pour les retirer."""
        assert self.pasta and self.ip
        return cage.isolated(inner, pasta=self.pasta, ip=self.ip, sh=self.sh, addresses=self._host_addresses())

    def _host_addresses(self) -> list[ipaddress.IPv4Address]:
        """Les adresses IPv4 de la machine elle-même (``cage.host_addresses``)."""
        return cage.host_addresses(str(self.ip))

    def _env(self, root: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Construit, jamais hérité : aucune variable du serveur n'entre (seulement ``extra``, que
        l'atelier pose lui-même pour ses propres commandes git)."""
        home = root / HOME_DIRNAME
        return {"PATH": _search_path(root), "HOME": str(home), "TMPDIR": "/tmp", "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                "MIKA_ATELIER": "1", **dict(extra or {})}

    def _limit(self) -> None:  # dans le processus fils, avant bubblewrap (et pasta)
        lim = self.limits
        resource.setrlimit(resource.RLIMIT_AS, (lim.memory_bytes, lim.memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (lim.cpu_seconds, lim.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (lim.file_bytes, lim.file_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (lim.files, lim.files))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    async def run(self, project: int, argv: Sequence[str], *, timeout_s: float | None = None,
                  network: bool = False, views: Sequence[int] = (), check_allowed: bool = True,
                  extra_env: Mapping[str, str] | None = None, secrets: Sequence[str] = (),
                  clip: bool = True) -> RunResult:
        """``views`` : les projets lus dont la vue se monte, en lecture seule, sous ``liens/<n>/`` (ADR 0260) —
        seulement pour ce que le modèle lance sans réseau : ni une commande réseau, ni les git de l'atelier."""
        args = [str(a) for a in argv]
        if not args:
            return RunResult((), None, refused="commande vide")
        program = Path(args[0]).name
        allowed = self.network_allowed if network else self.allowed
        if check_allowed and program not in allowed:
            more = " (télécharger passe par une commande réseau, ws_network)" \
                if not network and program in self.network_allowed else ""
            return RunResult(tuple(args), None, refused=f"« {program} » n'est pas autorisé ici{more}. Autorisés : "
                                                        f"{', '.join(sorted(allowed))}.")
        if not self.bwrap:
            return RunResult(tuple(args), None, refused="bubblewrap est absent : aucune exécution sans isolation")
        mode = ""
        if network and not check_allowed:
            mode = "host"  # les git de l'atelier lui-même, vers l'adresse qu'un opérateur a réglée (un dépôt local compris)
        elif network:
            if not (self.pasta and self.ip):  # ce que le modèle lance ne sort jamais par le réseau de l'hôte
                return RunResult(tuple(args), None, refused=NO_ISOLATED_NETWORK)
            mode = "isolated"
        if check_allowed:
            full = self.full(project)
            if full and program not in CLEANING:
                return RunResult(tuple(args), None, refused=full)
            await self._init(project)
        root = self._open(project).resolve()
        exe = self._visible(args[0], root)
        if exe is None:
            return RunResult(tuple(args), None, refused=f"« {args[0]} » est absent de l'environnement isolé "
                                                        "(installe-le dans l'atelier : .venv/bin, node_modules/.bin)")
        mounted, unmounted = await self._mounts(project, root, views) if check_allowed and not network else ([], ())
        cmd = self._sandbox(root, [exe, *args[1:]], mode, protect_git=check_allowed, read_only=mounted)
        if mode == "isolated":
            cmd = self._isolated(cmd)
        limit = timeout_s or self.timeout_s
        loop = asyncio.get_running_loop()
        job = _Job()
        try:
            result = await loop.run_in_executor(None, self._run_sync, tuple(args), cmd, root, limit, extra_env,
                                                tuple(x for x in secrets if x), job, clip)
        except asyncio.CancelledError:
            job.cancel()  # l'exécution est annulée : ce qu'elle a lancé ne lui survit pas
            raise
        if check_allowed:
            self._sizes[project] = await loop.run_in_executor(None, self._measure, root)
            if self.full(project):
                result = replace(result, notes=(*result.notes, f"Attention : {self.full(project)}."))
        if unmounted:
            result = replace(result, notes=(*result.notes, *unmounted))
        return result

    def _measure(self, root: Path, limit: int | None = None) -> int:
        """La place qu'occupe un dossier (sans suivre les liens) — l'atelier, ou une vue qu'on vient de poser
        (``limit`` : son plafond) —, en s'arrêtant dès qu'elle dépasse franchement la limite."""
        total, stop = 0, (self.limits.workshop_bytes if limit is None else limit) * 2
        stack = [root]
        while stack and total <= stop:
            d = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    stack.append(Path(e.path))
                else:
                    total += st.st_size
        return total

    def _run_sync(self, argv: tuple[str, ...], cmd: list[str], root: Path, limit: float,
                  extra_env: Mapping[str, str] | None = None, secrets: tuple[str, ...] = (),
                  job: _Job | None = None, clip: bool = True) -> RunResult:
        """``clip=False`` pour une sortie que le code lit lui-même (une liste de chemins) : elle n'est pas coupée au
        milieu, seulement bornée par le plafond d'octets d'un flux (``truncated`` le dit)."""
        job = job or _Job()
        cap = self.max_output * 4 if clip else self.limits.output_bytes
        start = time.perf_counter()
        try:
            proc = subprocess.Popen(cmd, cwd=str(root), env=self._env(root, extra_env), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                                    preexec_fn=self._limit)  # noqa: PLW1509 — les limites du processus fils
        except OSError as exc:
            return RunResult(argv, None, refused=f"lancement impossible : {exc}")
        if not job.attach(proc):
            _killpg(proc)  # annulée avant même de partir
        timed_out, overflow, raw = self._collect(proc, limit, job, cap + 1)
        if timed_out or overflow or job.cancelled:
            _killpg(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _killpg(proc)
            proc.wait()
        duration = int((time.perf_counter() - start) * 1000)
        texts = []
        cut = overflow
        for buf in raw:
            text = bytes(buf[:cap]).decode("utf-8", errors="replace")
            for secret in secrets:  # avant de couper : un secret à cheval sur la coupure reste reconnu
                text = text.replace(secret, "***")
            text, clipped = _clip(text, self.max_output) if clip else (text, False)
            texts.append(text)
            cut |= clipped or len(buf) > cap
        notes: tuple[str, ...] = ()
        if overflow:
            notes = (f"Programme arrêté : sa sortie dépassait {size_fr(self.limits.output_bytes)}.",)
        elif job.cancelled:
            notes = ("Programme arrêté : l'exécution qui l'avait lancé a été interrompue.",)
        return RunResult(argv, proc.returncode, texts[0], texts[1], duration, timed_out, cut, notes=notes)

    def _collect(self, proc: subprocess.Popen[bytes], limit: float, job: _Job, keep: int
                 ) -> tuple[bool, bool, tuple[bytearray, bytearray]]:
        """Lit la sortie et les erreurs par leurs tubes jusqu'à la fin du programme, son délai, une annulation ou
        un flux qui dépasse sa limite (on garde le début : ce qu'on rend est de toute façon coupé). Rend (délai,
        débordement, ce qui a été lu)."""
        assert proc.stdout is not None and proc.stderr is not None
        out, err = bytearray(), bytearray()
        streams = {proc.stdout.fileno(): out, proc.stderr.fileno(): err}
        sizes = dict.fromkeys(streams, 0)
        deadline = time.monotonic() + limit
        open_ = set(streams)
        timed_out = overflow = False
        try:
            while open_ and not job.cancelled and not overflow:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                ready, _, _ = select.select(list(open_), [], [], min(remaining, 0.25))
                for fd in ready:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        open_.discard(fd)
                        continue
                    sizes[fd] += len(chunk)
                    buf = streams[fd]
                    if len(buf) < keep:
                        buf += chunk[: keep - len(buf)]
                    overflow = overflow or sizes[fd] > self.limits.output_bytes
        finally:
            for f in (proc.stdout, proc.stderr):
                try:
                    f.close()
                except OSError:
                    pass
        return timed_out, overflow, (out, err)

    # ── git ──
    async def _git(self, project: int, *args: str, network: bool = False, timeout_s: float = 30,
                   extra_env: Mapping[str, str] | None = None, secrets: Sequence[str] = (),
                   clip: bool = True) -> RunResult:
        return await self.run(project, ["git", *author_identity(self.author()), *_GIT, *args], timeout_s=timeout_s,
                              check_allowed=False, network=network,
                              extra_env={**_GIT_ENV, **dict(extra_env or {})}, secrets=secrets, clip=clip)

    async def _init(self, project: int) -> bool:
        root = self._open(project)
        if (root / ".git").exists():
            return True
        r = await self._git(project, "init", "-q")
        if not r.ok:
            return False
        self._exclude(root)
        (root / ".gitignore").write_text(IGNORED, encoding="utf-8")
        await self._git(project, "add", "-A")
        await self._git(project, "commit", "-q", "-m", "atelier ouvert")
        return True

    @staticmethod
    def _exclude(root: Path) -> None:
        """La maison de l'atelier, ses environnements (``.venv``, ``node_modules``) et ses caches n'entrent jamais
        dans le dépôt, même si un dépôt récupéré retire ou change le ``.gitignore`` de l'amorce (l'exclusion
        locale n'est pas versionnée)."""
        info = root / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        wanted = IGNORED + SECRETS_IGNORED
        target = info / "exclude"
        if not target.is_file() or target.read_text(encoding="utf-8", errors="replace") != wanted:
            target.write_text(wanted, encoding="utf-8")

    async def commit(self, project: int, message: str, paths: Sequence[str] = ()) -> str:
        if not self.exists(project) or not await self._init(project):
            return ""
        # un atelier d'avant reçoit l'exclusion des fichiers de secrets ; un chemin nommé qui en est un ne
        # s'enregistre pas (``git add`` le refuserait, et rien d'autre ne partirait avec lui)
        self._exclude(self._open(project))
        named = [p for p in paths if p]
        only = [f":(literal){p}" for p in named if not secret_file(p)]
        if named and not only:
            return ""
        scope = ("--", *only) if only else ()
        state = await self._git(project, "status", "--porcelain", *scope)
        if not state.ok or not state.stdout.strip():
            return ""
        await self._git(project, "add", "-A", *scope)
        title = re.sub(r"\s+", " ", (message or "travail")).strip()[:72] or "travail"
        done = await self._git(project, "commit", "-q", "-m", title, *scope)
        if not done.ok:
            return ""
        # son identifiant complet, comme ``head`` et ``span`` : ce qui se compare à un commit épinglé (un verdict de
        # relecture, un envoi) n'a qu'une forme — l'abrégé n'est qu'un affichage (ADR 0277)
        return await self.head(project)

    async def diff(self, project: int) -> str:
        """Ce qui a changé depuis le dernier enregistrement : le diff des fichiers suivis, puis les fichiers nouveaux
        (que ``git diff`` ne montre pas)."""
        if not self._has_git(project):
            return ""
        r = await self._git(project, "diff", "HEAD", "--stat", "-p")
        new = [p[3:] for p in await self._status(project) if p.startswith("??")]
        text = r.stdout if r.ok else ""
        if new:
            text += ("\n" if text else "") + "Fichiers nouveaux, pas encore enregistrés :\n" + \
                "\n".join(f"+ {n}" for n in new[:200])
        return text

    async def _status(self, project: int) -> list[str]:
        # ``core.quotepath=off`` : un chemin qui a un accent se lit tel quel, pas en octal entre guillemets — sinon
        # un fichier protégé au nom accentué ne correspondrait jamais à son motif (ADR 0272)
        r = await self._git(project, "-c", "core.quotepath=off", "status", "--porcelain", "--untracked-files=all",
                            clip=False)
        return [line for line in r.stdout.splitlines() if line.strip()] if r.ok else []

    async def pending(self, project: int) -> list[str]:
        if not self._has_git(project):
            return []
        return [line[3:] for line in await self._status(project)]

    async def log(self, project: int, n: int = 10, *, offset: int = 0) -> str:
        if not self._has_git(project):
            return ""
        r = await self._git(project, "log", f"-{max(1, n)}", f"--skip={max(0, offset)}", "--format=%h %s")
        return r.stdout if r.ok else ""

    async def commits(self, project: int, n: int = 25, *, offset: int = 0) -> list[Commit]:
        return await self._history(project, n, offset)

    async def _history(self, project: int, n: int, offset: int = 0, *revs: str) -> list[Commit]:
        """L'historique détaillé de la branche courante, ou de ``revs`` (une étendue : ``base..branche``)."""
        if not self._has_git(project):
            return []
        # une entrée commence par un NUL (qu'un message de commit ne peut pas contenir) ; le titre vient en
        # dernier : un séparateur glissé dans un message ne fabrique ni une fausse ligne ni un faux auteur
        r = await self._git(project, "log", f"-{max(1, n)}", f"--skip={max(0, offset)}", "--shortstat",
                            "--format=%x00%H%x1f%ct%x1f%an%x1f%s", *revs)
        if not r.ok:
            return []
        out = []
        for record in r.stdout.split("\x00"):
            head, _, rest = record.strip("\n").partition("\n")
            fields = head.split("\x1f", 3)
            if len(fields) != 4 or not _SHA.match(fields[0]) or not fields[1].isdigit():
                continue
            sha, stamp, author, title = fields
            stat = _STAT.search(rest)
            files, plus, minus = (int(x) if x else 0 for x in stat.groups()) if stat else (0, 0, 0)
            out.append(Commit(sha, int(stamp) * 1_000_000 if stamp.isdigit() else 0, title, author, files, plus,
                              minus))
        return out

    async def count(self, project: int) -> int:
        if not self._has_git(project):
            return 0
        r = await self._git(project, "rev-list", "--count", "HEAD")
        return int(r.stdout.strip()) if r.ok and r.stdout.strip().isdigit() else 0

    async def head(self, project: int) -> str:
        """Le commit courant (complet), ou ``""``."""
        if not self._has_git(project):
            return ""
        r = await self._git(project, "rev-parse", "--verify", "-q", "HEAD^{commit}")
        sha = r.stdout.strip()
        return sha if r.ok and _SHA.match(sha) else ""

    async def branch(self, project: int) -> str:
        """La branche courante, ou ``""`` (pas de dépôt, ou une tête détachée)."""
        if not self._has_git(project):
            return ""
        r = await self._git(project, "symbolic-ref", "--short", "-q", "HEAD")
        name = r.stdout.strip()
        return name if r.ok and BRANCH_NAME.match(name) else ""

    # ── les branches de travail (ADR 0274) ──
    async def base(self, project: int) -> str:
        return await self._ref(project, f"refs/heads/{BASE_BRANCH}") if self._has_git(project) else ""

    async def _ref(self, project: int, name: str) -> str:
        """Le commit d'une référence (son identifiant complet), ou ``""``."""
        r = await self._git(project, "rev-parse", "--verify", "-q", f"{name}^{{commit}}")
        sha = r.stdout.strip()
        return sha if r.ok and _FULL_SHA.match(sha) else ""

    async def _ahead(self, project: int, branch: str) -> int:
        r = await self._git(project, "rev-list", "--count", f"refs/heads/{BASE_BRANCH}..refs/heads/{branch}")
        return int(r.stdout.strip()) if r.ok and r.stdout.strip().isdigit() else 0

    async def work_on(self, project: int, branch: str, *, stow: str = "") -> Placed:
        try:
            branch = check_branch(branch)
        except ValueError as exc:
            return Placed(why=str(exc))
        if branch == BASE_BRANCH:
            return Placed(why="la branche de base ne reçoit pas de travail")
        if not self.exists(project) or not await self._init(project):
            return Placed(why="le dépôt de l'atelier ne s'ouvre pas")
        base = await self._ref(project, f"refs/heads/{BASE_BRANCH}")
        if not base:
            return Placed(why=f"l'atelier n'a pas de branche « {BASE_BRANCH} »")
        current = await self.branch(project)
        if current == branch:
            return Placed(branch, base=base, ahead=await self._ahead(project, branch))
        stowed = ""
        if current and current != BASE_BRANCH:
            # un travail interrompu reste sur sa branche : rangé par un commit avant de changer. Sur la base (ou une
            # tête détachée), rien ne s'y enregistre jamais : ce qui n'est pas enregistré suit sur la branche
            stowed = await self.commit(project, stow or "travail interrompu")
            if not stowed and await self.pending(project):
                return Placed(why=f"le travail resté sur « {current} » ne s'enregistre pas : l'atelier y reste")
        created = not await self._ref(project, f"refs/heads/{branch}")
        moved = await self._git(project, "checkout", "-q", "-b", branch, f"refs/heads/{BASE_BRANCH}") if created \
            else await self._git(project, "checkout", "-q", branch)
        if not moved.ok:
            said = " ".join((moved.stderr or moved.refused or "").split())[:200]
            return Placed(why=f"l'atelier ne passe pas sur « {branch} » : {said or 'git refuse'}", stowed=stowed,
                          stowed_on=current if stowed else "")
        return Placed(branch, created, base, await self._ahead(project, branch), stowed, current if stowed else "")

    # ── la base ramenée dans une branche de travail (ADR 0280) ──
    def _joining(self, project: int) -> bool:
        """La base ramenée dans la branche attend-elle encore son enregistrement ?"""
        return (self.folder(project) / ".git" / "MERGE_HEAD").is_file()

    async def _unmerged(self, project: int) -> list[str]:
        """Les fichiers que git dit en conflit, tant que rien n'est enregistré."""
        r = await self._git(project, "-c", "core.quotepath=off", "diff", "--name-only", "--diff-filter=U", clip=False)
        return [line for line in r.stdout.splitlines() if line.strip()] if r.ok else []

    async def unresolved(self, project: int) -> list[str]:
        if not self._has_git(project) or not self._joining(project):
            return []
        base, left = self.folder(project).resolve(), []
        for rel in await self._unmerged(project):
            try:
                target = self._confined(base, rel)
                with target.open("rb") as f:
                    marked = bool(_CONFLICT_MARK.search(f.read(_MARKS_READ)))
            except (OSError, OutsideWorkshop):
                continue  # supprimé, ou illisible : ce n'est plus une marque à résoudre
            if marked:
                left.append(rel)
        return left

    async def take_base(self, project: int, branch: str, *, stow: str = "") -> Joined:
        try:
            branch = check_branch(branch)
        except ValueError as exc:
            return Joined(why=str(exc))
        if branch == BASE_BRANCH:
            return Joined(why="la branche de base ne reçoit pas de travail")
        if not self.exists(project) or not self._has_git(project):
            return Joined(why="le dépôt de l'atelier ne s'ouvre pas")
        if await self.branch(project) != branch:
            return Joined(why=f"l'atelier n'est pas sur « {branch} »")
        base = await self._ref(project, f"refs/heads/{BASE_BRANCH}")
        if not base:
            return Joined(why=f"l'atelier n'a pas de branche « {BASE_BRANCH} »")
        if self._joining(project):
            # déjà en cours : redite telle qu'elle est — ce qu'il reste à résoudre avant d'enregistrer
            return Joined(branch, await self._ref(project, "MERGE_HEAD") or base,
                          conflicts=tuple(await self.unresolved(project)))
        if (await self._git(project, "merge-base", "--is-ancestor", base, "HEAD")).ok:
            return Joined(branch, base, already=True)
        # ce qui n'est pas enregistré est d'abord rangé : ce que la base apporte ne s'y mêle pas, et rien ne se perd
        stowed = await self.commit(project, stow or "travail interrompu")
        if not stowed and await self.pending(project):
            return Joined(why="ce qui n'est pas enregistré ne s'enregistre pas : rien n'a bougé")
        if (await self._git(project, "merge-base", "--is-ancestor", "HEAD", base)).ok:
            # la branche n'a rien à elle : elle rejoint la base, en ligne droite — rien à enregistrer
            moved = await self._git(project, "merge", "--ff-only", f"refs/heads/{BASE_BRANCH}")
            said = " ".join((moved.stderr or moved.refused or "").split())[:200]
            return Joined(branch, base, stowed=stowed) if moved.ok else \
                Joined(why=f"« {branch} » ne rejoint pas la base : {said or 'git refuse'}", stowed=stowed)
        # sur la branche de travail seulement, et sans enregistrer : l'enregistrement de l'exécution le fera, une
        # fois les conflits résolus. La base n'est pas écrite, rien ne part
        merged = await self._git(project, "merge", "--no-ff", "--no-commit", f"refs/heads/{BASE_BRANCH}")
        conflicts = await self._unmerged(project)
        if not merged.ok and not conflicts:
            await self._git(project, "merge", "--abort")
            said = " ".join((merged.stderr or merged.refused or "").split())[:200]
            return Joined(why=f"la base n'entre pas dans « {branch} » : {said or 'git refuse'}", stowed=stowed)
        return Joined(branch, base, conflicts=tuple(conflicts), stowed=stowed)

    async def span(self, project: int, branch: str) -> Span | None:
        if not self._has_git(project) or not BRANCH_NAME.match(branch or ""):
            return None
        head = await self._ref(project, f"refs/heads/{branch}")
        base = await self._ref(project, f"refs/heads/{BASE_BRANCH}")
        if not head or not base:
            return None
        fork = (await self._git(project, "merge-base", base, head)).stdout.strip()
        if not _FULL_SHA.match(fork):
            return None  # deux histoires sans rien de commun : rien à mesurer
        # ``core.quotepath=off`` : un chemin accentué se lit tel quel (ADR 0272) ; sans renommages : deux chemins
        r = await self._git(project, "-c", "core.quotepath=off", "diff", "--numstat", "--no-renames", fork, head,
                            clip=False)
        if not r.ok:
            return None
        files, plus, minus = [], 0, 0
        for row in r.stdout.splitlines():
            added, _, rest = row.partition("\t")
            removed, _, name = rest.partition("\t")
            if not name:
                continue
            files.append(name)
            plus += int(added) if added.isdigit() else 0  # « - » : un fichier binaire, compté sans lignes
            minus += int(removed) if removed.isdigit() else 0
        # avec qui les a signés et leurs parents (ADR 0288 : l'écran d'une personne dit si un commit est d'elle)
        commits = await self._lineage(project, [f"{fork}..{head}"], 200)
        return Span(tuple(files), plus, minus, tuple(commits), head, fork)

    async def patch(self, project: int, since: str, head: str, limit: int = 60_000) -> str | None:
        """Le texte de ce qui change de ``since`` à ``head`` : le résumé par fichier, puis le diff, coupé à
        ``limit`` caractères (``since`` vide : depuis l'arbre vide). Ni pilote de diff externe ni conversion de
        texte : ce qui est lu est ce qui est enregistré."""
        if not self._has_git(project) or not _SHA.match(head or "") or (since and not _SHA.match(since)):
            return None
        r = await self._git(project, "-c", "core.quotepath=off", "diff", "--no-ext-diff", "--no-textconv", "--stat",
                            "-p", "--no-renames", since or _EMPTY_TREE, head, clip=False)
        if not r.ok:
            return None
        return r.stdout if len(r.stdout) <= limit else r.stdout[:limit] + _PATCH_CUT

    async def compare(self, project: int, sha: str) -> tuple[int, int] | None:
        """(les enregistrements de l'atelier que ``sha`` n'a pas, ceux de ``sha`` qu'il n'a pas) ; ``None`` si
        l'atelier ne connaît pas ce commit (le distant a bougé sans lui)."""
        if not _SHA.match(sha or "") or not self._has_git(project):
            return None
        if not (await self._git(project, "cat-file", "-e", f"{sha}^{{commit}}")).ok:
            return None
        r = await self._git(project, "rev-list", "--left-right", "--count", f"HEAD...{sha}")
        counts = r.stdout.split()
        if not r.ok or len(counts) != 2 or not all(n.isdigit() for n in counts):
            return None
        return int(counts[0]), int(counts[1])

    async def show(self, project: int, sha: str) -> str:
        if not _SHA.match(sha or "") or not self._has_git(project):
            return ""
        r = await self._git(project, "show", "--stat", "-p", "--format=%H%n%an, %cd%n%n%B", "--date=iso", sha)
        if not r.ok:
            return ""
        text = r.stdout
        return text if len(text) <= SHOW_MAX_CHARS else text[:SHOW_MAX_CHARS] + "\n[… coupé …]"

    # ── le dépôt lu à une référence (ADR 0288) ──
    @staticmethod
    def _inside(path: str) -> str:
        """Un chemin du dépôt, relatif à sa racine (``""`` : la racine) — ou ``OutsideWorkshop`` : un chemin absolu,
        qui remonte (``..``), ou qui porte un octet nul ne nomme rien du dépôt. Les objets de git ne suivent aucun
        lien : ce contrôle suffit, rien ne se résout sur le disque."""
        raw = str(path or "").strip()
        if raw.startswith("/") or "\x00" in raw:
            raise OutsideWorkshop(f"chemin absolu refusé : {raw[:80]} — écris un chemin relatif au dépôt")
        parts = [x for x in raw.split("/") if x and x != "."]
        if ".." in parts or (parts and parts[0] in ORGANS):
            raise OutsideWorkshop(f"hors du dépôt : {raw[:80]}")
        return "/".join(parts)

    async def _resolved(self, project: int, ref: str) -> str:
        """Le commit que nomme une référence — une branche du dépôt, sinon un identifiant de commit — (complet), ou
        ``""``. Rien d'autre ne se nomme : ni une expression de révision, ni une option."""
        raw = str(ref or "").strip()
        if not self._has_git(project) or ".." in raw:
            return ""
        if BRANCH_NAME.match(raw) and (sha := await self._ref(project, f"refs/heads/{raw}")):
            return sha
        return await self._ref(project, raw) if _SHA.match(raw) else ""

    async def _labels(self, project: int) -> dict[str, str]:
        """La branche de travail qui porte chaque commit que la base n'a pas (les autres sont sur la base)."""
        r = await self._git(project, "log", "--branches", "--not", f"refs/heads/{BASE_BRANCH}", "--source",
                            "--format=%H %S", "-n", "5000", clip=False)
        out: dict[str, str] = {}
        for row in r.stdout.splitlines() if r.ok else ():
            sha, _, source = row.partition(" ")
            name = source.removeprefix("refs/heads/")  # git la dit courte ou entière, selon sa version
            if _FULL_SHA.match(sha) and BRANCH_NAME.match(name):
                out[sha] = name
        return out

    async def _lineage(self, project: int, revs: Sequence[str], n: int, offset: int = 0,
                       path: str = "") -> list[Commit]:
        """Des commits avec leurs comptes, leurs parents et qui les a signés — ``_history``, en plus dit."""
        scope = ("--", f":(literal){path}") if path else ()
        # un enfant avant ses parents, même quand deux commits portent la même seconde
        r = await self._git(project, "log", f"-{max(1, n)}", f"--skip={max(0, offset)}", "--topo-order",
                            "--shortstat", "--format=%x00%H%x1f%ct%x1f%P%x1f%ae%x1f%ce%x1f%an%x1f%s", *revs, *scope,
                            clip=False)
        if not r.ok:
            return []
        mine = author_identity(self.author())[-1].partition("user.email=")[2]
        out = []
        for record in r.stdout.split("\x00"):
            head, _, rest = record.strip("\n").partition("\n")
            fields = head.split("\x1f", 6)
            if len(fields) != 7 or not _FULL_SHA.match(fields[0]) or not fields[1].isdigit():
                continue
            sha, stamp, parents, mail, committer, author, title = fields
            stat = _STAT.search(rest)
            files, plus, minus = (int(x) if x else 0 for x in stat.groups()) if stat else (0, 0, 0)
            out.append(Commit(sha, int(stamp) * 1_000_000, title, author, files, plus, minus,
                              # d'elle : signé **et** posé par l'adresse de l'atelier, entière (ADR 0292) — une
                              # adresse qui finit seulement comme elle est celle d'un commit venu d'ailleurs
                              local=mail == mine and committer == mine,
                              parents=tuple(x for x in parents.split() if _FULL_SHA.match(x))))
        return out

    async def branches(self, project: int) -> list[Branch]:
        if not self._has_git(project):
            return []
        r = await self._git(project, "for-each-ref", "--format=%(refname:short)", f"--count={BRANCHES_MAX}",
                            "refs/heads", clip=False)
        names = [x for x in r.stdout.splitlines() if BRANCH_NAME.match(x)] if r.ok else []
        current = await self.branch(project)
        out = []
        for name in sorted(names, key=lambda x: (x != BASE_BRANCH, x)):
            head = await self._lineage(project, [f"refs/heads/{name}"], 1)
            if not head:
                continue
            ahead = behind = 0
            if name != BASE_BRANCH and BASE_BRANCH in names:
                gap = await self._git(project, "rev-list", "--left-right", "--count",
                                      f"refs/heads/{BASE_BRANCH}...refs/heads/{name}")
                counts = gap.stdout.split()
                if gap.ok and len(counts) == 2 and all(x.isdigit() for x in counts):
                    behind, ahead = int(counts[0]), int(counts[1])
            out.append(Branch(name, replace(head[0], branch=name), ahead, behind, name == BASE_BRANCH,
                              name == current))
        return out

    async def ref_tree(self, project: int, ref: str, path: str = ".") -> list[TreeEntry] | None:
        rel = self._inside(path)
        sha = await self._resolved(project, ref)
        if not sha:
            return None
        r = await self._git(project, "ls-tree", "-z", "-l", f"{sha}:{rel}", clip=False)
        if not r.ok:
            raise FileNotFoundError(f"{rel or '.'} n'est pas un dossier de ce commit")
        rows = []
        for record in r.stdout.split("\x00"):
            meta, tab, name = record.partition("\t")
            parts = meta.split()
            if not tab or len(parts) != 4 or not name:
                continue
            mode, kind, _, size = parts
            sort = ENTRY_DIR if kind == "tree" else ENTRY_MODULE if kind == "commit" else \
                ENTRY_LINK if mode == "120000" else ENTRY_FILE
            rows.append(TreeEntry(f"{rel}/{name}" if rel else name, sort, int(size) if size.isdigit() else 0))
        rows.sort(key=lambda e: (e.kind != ENTRY_DIR, e.path))
        return rows[:TREE_MAX]

    async def ref_file(self, project: int, ref: str, path: str, limit: int = 400_000) -> Blob | None:
        rel = self._inside(path)
        sha = await self._resolved(project, ref)
        if not sha:
            return None
        if not rel:
            raise FileNotFoundError("un fichier se nomme par son chemin")
        # son entrée dans le dossier qui le porte : sa sorte et sa taille, sans lire son contenu
        folder, _, name = rel.rpartition("/")
        r = await self._git(project, "ls-tree", "-z", "-l", f"{sha}:{folder}", clip=False)
        found = None
        for record in r.stdout.split("\x00") if r.ok else ():
            meta, tab, said = record.partition("\t")
            parts = meta.split()
            if tab and said == name and len(parts) == 4:
                found = parts
                break
        if found is None or found[1] == "tree":
            raise FileNotFoundError(f"{rel} n'est pas un fichier de ce commit")
        mode, kind, blob, size = found
        if not _FULL_SHA.match(blob):
            raise FileNotFoundError(f"{rel} ne se lit pas dans ce commit")
        if kind == "commit" or mode == "120000":  # un sous-module ne s'ouvre pas, un lien ne se suit pas
            return Blob(rel, sha, ENTRY_MODULE if kind == "commit" else ENTRY_LINK)
        weight = int(size) if size.isdigit() else 0
        if weight > max(0, limit):
            return Blob(rel, sha, size=weight, too_big=True)
        got = await self._git(project, "cat-file", "blob", blob, clip=False)
        if not got.ok or got.truncated:
            return Blob(rel, sha, size=weight, too_big=True)
        if "\x00" in got.stdout[:_BINARY_PEEK]:
            return Blob(rel, sha, size=weight, binary=True)
        return Blob(rel, sha, size=weight, text=got.stdout)

    async def history(self, project: int, ref: str = "", *, path: str = "", n: int = 25,
                      offset: int = 0) -> History | None:
        rel = self._inside(path)
        if not self._has_git(project):
            return None
        if ref:
            sha = await self._resolved(project, ref)
            if not sha:
                return None
            revs = [sha]
        else:
            revs = ["--branches"]
        scope = ("--", f":(literal){rel}") if rel else ()
        counted = await self._git(project, "rev-list", "--count", *revs, *scope)
        total = int(counted.stdout.strip()) if counted.ok and counted.stdout.strip().isdigit() else 0
        labels = await self._labels(project)
        found = await self._lineage(project, revs, n, offset, rel)
        return History(tuple(replace(k, branch=labels.get(k.sha, BASE_BRANCH)) for k in found), total)

    async def change(self, project: int, sha: str) -> Change | None:
        if not self._has_git(project) or not _SHA.match(sha or ""):
            return None
        full = await self._ref(project, sha)
        found = await self._lineage(project, [full], 1) if full else []
        if not found:
            return None
        body = await self._git(project, "show", "-s", "--format=%b", full, clip=False)
        labels = await self._labels(project)
        return Change(replace(found[0], branch=labels.get(full, BASE_BRANCH)),
                      body.stdout.strip()[:BODY_MAX_CHARS] if body.ok else "")

    async def diff_of(self, project: int, since: str, head: str, *, path: str = "",
                      lines: int = 3000) -> tuple[FileDiff, ...] | None:
        rel = self._inside(path)
        if not self._has_git(project) or not _SHA.match(head or "") or (since and not _SHA.match(since)):
            return None
        scope = ("--", f":(literal){rel}") if rel else ()
        base = since or _EMPTY_TREE
        # ce que chaque fichier est devenu et ses comptes, lus par le code : jamais coupés au milieu
        listed = await self._git(project, "diff", "--raw", "--numstat", "-z", "--no-renames", "--no-abbrev", base,
                                 head, *scope, clip=False)
        if not listed.ok:
            return None
        tokens = listed.stdout.split("\x00")
        status: dict[str, str] = {}
        counts: list[tuple[str, int, int, bool]] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.startswith(":") and i + 1 < len(tokens):
                letter = token.split()[-1][:1]
                status[tokens[i + 1]] = FILE_ADDED if letter == "A" else FILE_DELETED if letter == "D" else \
                    FILE_MODIFIED
                i += 2
                continue
            added, _, rest = token.partition("\t")
            removed, tab, name = rest.partition("\t")
            if tab and name:
                counts.append((name, int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0,
                               added == "-"))
            i += 1
        patch = await self._git(project, "-c", "core.quotepath=off", "diff", "--no-ext-diff", "--no-textconv",
                                "--no-color", "--no-renames", "-p", base, head, *scope, clip=False)
        blocks = self._blocks(patch.stdout) if patch.ok and not patch.truncated else []
        out, left = [], max(0, lines)
        for at, (name, plus, minus, binary) in enumerate(counts):
            block = blocks[at] if at < len(blocks) else None
            hunks: tuple[Hunk, ...] = ()
            cut = block is None and not binary
            if block is not None and not binary:
                size = sum(len(h.lines) for h in block)
                if size <= left:
                    hunks, left = tuple(block), left - size
                else:  # la borne est atteinte : ce fichier-ci garde ce qui tient, les suivants leurs seuls comptes
                    kept = []
                    for h in block:
                        if left <= 0:
                            break
                        kept.append(Hunk(h.header, h.lines[:left]))
                        left -= len(kept[-1].lines)
                    hunks, cut, left = tuple(kept), True, 0
            out.append(FileDiff(name, status.get(name, FILE_MODIFIED), plus, minus, binary, cut, hunks))
        return tuple(out)

    @staticmethod
    def _blocks(patch: str) -> list[list[Hunk]]:
        """Les passages de chaque fichier d'un diff, dans l'ordre où git les écrit (celui de ses comptes), chaque
        ligne avec son numéro avant et après."""
        files: list[list[tuple[str, list[DiffLine]]]] = []
        rows: list[DiffLine] | None = None
        old = new = 0
        for row in patch.split("\n"):
            if row.startswith("diff --git "):  # une ligne d'un passage commence par « », « + » ou « - », jamais ainsi
                files.append([])
                rows = None
                continue
            if not files:
                continue
            found = _HUNK.match(row)
            if found is not None:
                old, new = int(found.group(1)), int(found.group(2))
                rows = []
                files[-1].append((row[:DIFF_LINE_MAX], rows))
                continue
            if rows is None or not row or row[0] not in (LINE_SAME, LINE_ADDED, LINE_REMOVED):
                continue  # l'en-tête du fichier, « \ No newline at end of file »
            kind, text = row[0], row[1:DIFF_LINE_MAX + 1]
            if kind == LINE_SAME:
                rows.append(DiffLine(kind, old, new, text))
                old, new = old + 1, new + 1
            elif kind == LINE_ADDED:
                rows.append(DiffLine(kind, 0, new, text))
                new += 1
            else:
                rows.append(DiffLine(kind, old, 0, text))
                old += 1
        return [[Hunk(header, tuple(lines)) for header, lines in hunks] for hunks in files]

    # ── le dépôt distant ──
    def _auth(self, url: str) -> tuple[dict[str, str], tuple[str, ...], str]:
        """L'environnement d'authentification de git pour ce dépôt, les secrets à effacer des sorties, et ce
        qui empêche de montrer le jeton (vide : rien)."""
        creds = dict(self.credentials() if self.credentials is not None else {})
        token = (creds.get("token") or "").strip()
        env = {"GIT_ASKPASS": "/bin/false"}
        if not token:
            return env, (), "aucun jeton : règle-le dans Connexions › Dépôts Git"
        hosts = creds.get("hosts") or DEFAULT_HOSTS
        allowed = {h.strip().lower() for h in (hosts.split(",") if isinstance(hosts, str) else hosts) if h.strip()}
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host not in allowed:
            return env, (), (f"le jeton n'est pas autorisé pour « {host} » (hôtes autorisés : "
                             f"{', '.join(sorted(allowed)) or 'aucun'} — Connexions › Dépôts Git)")
        basic = base64.b64encode(f"{creds.get('user') or 'x-access-token'}:{token}".encode()).decode()
        # l'en-tête ne vaut que pour l'adresse de ce dépôt (le chemin compris, et le port s'il y en a un)
        scope = f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.{scope}.extraheader",
                    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"})
        return env, (token, basic), ""

    async def _clean_config(self, project: int) -> str:
        """Ce qui, dans la configuration locale du dépôt, n'a rien à y faire (vide : rien) — on ne parle pas au
        distant avec une configuration qu'on n'a pas posée."""
        r = await self._git(project, "config", "--local", "--name-only", "--list")
        if not r.ok:
            return "configuration locale illisible"
        odd = sorted({k for k in r.stdout.split() if k and k.lower() not in _LOCAL_KEYS})
        return f"configuration locale inattendue : {', '.join(odd[:5])}" if odd else ""

    async def push(self, project: int, url: str, branch: str, sha: str = "") -> RunResult:
        try:
            url, branch = _remote(url), check_branch(branch)
        except ValueError as exc:
            return RunResult(("git", "push"), None, refused=str(exc))
        env, secrets, why = self._auth(url)
        if why:
            return RunResult(("git", "push"), None, refused=f"pas d'envoi : {why}")
        if not await self._init(project):
            return RunResult(("git", "push"), None, refused="le dépôt de l'atelier ne s'ouvre pas")
        odd = await self._clean_config(project)
        if odd:
            return RunResult(("git", "push"), None, refused=f"pas d'envoi : {odd}")
        sha = sha or await self.head(project)
        if not _SHA.match(sha or "") or not (await self._git(project, "cat-file", "-e", f"{sha}^{{commit}}")).ok:
            return RunResult(("git", "push"), None, refused=f"le commit à envoyer est introuvable : {sha[:40]}")
        r = await self._git(project, *_REMOTE_GIT, "push", "--no-recurse-submodules", url,
                            f"{sha}:refs/heads/{branch}", network=True, timeout_s=REMOTE_TIMEOUT_S, extra_env=env,
                            secrets=secrets)
        if r.ok:
            await self._remember_sent(project, url, branch, sha)
        return replace(r, argv=("git", "push", url, f"{sha[:12]} → {branch}"))

    # ── ce que le dépôt distant possède (ADR 0277) ──
    @staticmethod
    def _sent_ref(url: str, branch: str) -> str:
        """La référence qui garde le commit que ce dépôt distant a sur cette branche : à part des branches, et
        propre à l'adresse — un distant réglé autrement ne passe pas pour avoir ce que l'ancien avait."""
        return "refs/atelier/sent/" + hashlib.sha256(f"{url}\n{branch}".encode()).hexdigest()[:20]

    async def _remember_sent(self, project: int, url: str, branch: str, commit: str) -> None:
        full = await self._ref(project, commit)
        if full:
            await self._git(project, "update-ref", self._sent_ref(url, branch), full)

    async def sent(self, project: int, url: str, branch: str) -> str:
        if not self._has_git(project):
            return ""
        try:
            url, branch = _remote(url), check_branch(branch)
        except ValueError:
            return ""
        return await self._ref(project, self._sent_ref(url, branch))

    async def pull(self, project: int, url: str, branch: str) -> RunResult:
        try:
            url, branch = _remote(url), check_branch(branch)
        except ValueError as exc:
            return RunResult(("git", "pull"), None, refused=str(exc))
        env, secrets, _ = self._auth(url)  # sans jeton (ou pour un autre hôte) : un dépôt public se récupère quand même
        if not await self._init(project):
            return RunResult(("git", "pull"), None, refused="le dépôt de l'atelier ne s'ouvre pas")
        odd = await self._clean_config(project)
        if odd:
            return RunResult(("git", "pull"), None, refused=f"pas de récupération : {odd}")
        fetched = await self._git(project, *_REMOTE_GIT, "fetch", "--no-tags", "--no-recurse-submodules", url, branch,
                                  network=True, timeout_s=REMOTE_TIMEOUT_S, extra_env=env, secrets=secrets)
        if not fetched.ok:
            return replace(fetched, argv=("git", "fetch", url, branch))
        # ce qu'on vient de lire est ce que le distant possède, que la suite l'intègre ou non (ADR 0277)
        await self._remember_sent(project, url, branch, "FETCH_HEAD")
        # les organes sont à la racine : le premier niveau suffit, et sa liste reste courte (une liste récursive
        # était coupée au milieu sur un gros dépôt)
        listed = await self._git(project, "ls-tree", "--name-only", "FETCH_HEAD", clip=False)
        organs = [n for n in listed.stdout.splitlines() if n in ORGANS]
        if not listed.ok or organs:
            return RunResult(("git", "pull", url, branch), None,
                             refused=f"le dépôt distant contient « {organs[0] if organs else '?'} », qui appartient à "
                                     "l'atelier lui-même : rien n'est récupéré")
        state = await self._git(project, "status", "--porcelain")
        if not state.ok:
            return RunResult(("git", "pull", url, branch), None, refused="l'état de l'atelier est illisible")
        current = await self.branch(project)
        if current and current != BASE_BRANCH:
            # l'atelier est sur une branche de travail (ADR 0274) : seule la référence de la base avance, en ligne
            # droite — ni l'arbre ni la branche en cours ne bougent
            return await self._advance_base(project, url, branch)
        if await self.count(project) <= 1 and not state.stdout.strip():
            # un atelier vierge (l'amorce seule) prend l'histoire du dépôt distant, sans écraser aucun fichier
            r = await self._git(project, "reset", "-q", "--keep", "FETCH_HEAD")
        else:
            r = await self._git(project, "merge", "--ff-only", "FETCH_HEAD")
        self._exclude(self.folder(project))
        return replace(r, argv=("git", "pull", url, branch))

    async def _advance_base(self, project: int, url: str, branch: str) -> RunResult:
        """Avancer la branche de base jusqu'à ce qu'on vient de récupérer (``FETCH_HEAD``), sans y être : sa seule
        référence bouge, et seulement en ligne droite."""
        argv = ("git", "pull", url, branch)
        got = await self._ref(project, "FETCH_HEAD")
        base = await self._ref(project, f"refs/heads/{BASE_BRANCH}")
        if not got:
            return RunResult(argv, None, refused="ce qui a été récupéré ne se lit pas")
        if base == got:
            return RunResult(argv, 0, stdout=f"« {BASE_BRANCH} » est déjà à jour.\n")
        if base and not (await self._git(project, "merge-base", "--is-ancestor", base, got)).ok:
            # une base qui n'a encore rien à elle (l'amorce seule) prend l'histoire du dépôt distant, comme un
            # atelier vierge resté sur sa base (ADR 0277) : la première exécution a pu partir avant toute
            # récupération, et sans cela la base ne rejoignait jamais le distant
            why = await self._adopt(project, base, got) if await self._bare_base(project, base) else \
                (f"« {BASE_BRANCH} » et le dépôt distant ont divergé : rien n'est récupéré (la base n'avance qu'en "
                 "ligne droite)")
            self._exclude(self.folder(project))
            return RunResult(argv, None, refused=why) if why else \
                RunResult(argv, 0, stdout=f"« {BASE_BRANCH} » prend l'histoire du dépôt distant ({got[:12]}).\n")
        r = await self._git(project, "update-ref", f"refs/heads/{BASE_BRANCH}", got, *([base] if base else []))
        self._exclude(self.folder(project))
        return replace(r, argv=argv, stdout=f"« {BASE_BRANCH} » avance jusqu'à {got[:12]}.\n" if r.ok else r.stdout)

    async def _bare_base(self, project: int, base: str) -> bool:
        """La base n'a-t-elle encore rien à elle : un seul commit, celui de l'amorce ?"""
        r = await self._git(project, "rev-list", "--count", base)
        return r.ok and r.stdout.strip() == "1"

    async def _adopt(self, project: int, old: str, new: str) -> str:
        """La base, encore à son amorce (``old``), prend l'histoire du dépôt distant (``new``) ; rend pourquoi elle
        ne l'a pas fait (vide : c'est fait). Les branches de travail parties de l'amorce suivent : leurs
        enregistrements sont rejoués un à un sur la nouvelle base — sans toucher à l'arbre (``merge-tree`` puis
        ``commit-tree``) —, et rien ne bouge si l'un d'eux ne se rejoue pas. La branche où l'atelier se trouve
        avance sans écraser un fichier non enregistré. Aucune fusion : chaque enregistrement garde un seul parent."""
        listed = await self._git(project, "for-each-ref", "--format=%(refname:short)", "refs/heads/", clip=False)
        if not listed.ok:
            return "les branches de l'atelier ne se lisent pas : rien n'est récupéré"
        moves: list[tuple[str, str, str]] = []
        for name in listed.stdout.split():
            tip = await self._ref(project, f"refs/heads/{name}") if name != BASE_BRANCH and BRANCH_NAME.match(name) else ""
            if not tip or not (await self._git(project, "merge-base", "--is-ancestor", old, tip)).ok:
                continue
            chain = await self._git(project, "rev-list", "--reverse", "--first-parent", f"{old}..{tip}", clip=False)
            if not chain.ok:
                return f"le travail de « {name} » ne se lit pas : rien n'est récupéré"
            at = new
            for commit in chain.stdout.split():
                merged = await self._git(project, "merge-tree", "--write-tree", f"--merge-base={commit}^", at, commit)
                tree = merged.stdout.split("\n", 1)[0].strip()
                said = await self._git(project, "log", "-1", "--format=%B", commit)
                made = await self._git(project, "commit-tree", tree, "-p", at, "-m", said.stdout.strip() or "travail") \
                    if merged.ok and _FULL_SHA.match(tree) else None
                if made is None or not made.ok or not _FULL_SHA.match(made.stdout.strip()):
                    return (f"le travail déjà enregistré sur « {name} » ne se rejoue pas sur l'histoire du dépôt "
                            "distant (les mêmes fichiers des deux côtés) : rien n'est récupéré")
                at = made.stdout.strip()
            moves.append((name, tip, at))
        current = await self.branch(project)
        here = next((m for m in moves if m[0] == current), None)
        if here is not None:
            # la seule étape qui peut se refuser (un fichier non enregistré que le distant porte aussi) : d'abord
            kept = await self._git(project, "reset", "-q", "--keep", here[2])
            if not kept.ok:
                return (f"un fichier non enregistré de « {current} » existe aussi dans le dépôt distant : rien "
                        "n'est récupéré")
        for name, tip, at in moves:
            if name != current:
                await self._git(project, "update-ref", f"refs/heads/{name}", at, tip)
        moved = await self._git(project, "update-ref", f"refs/heads/{BASE_BRANCH}", new, old)
        return "" if moved.ok else f"« {BASE_BRANCH} » n'a pas pu prendre l'histoire du dépôt distant"

    # ── les vues des ateliers lus (ADR 0260) ──
    def _views_of(self, reader: int) -> Path:
        return self.root / VIEWS_DIRNAME / f"projet-{int(reader)}"

    def _view_home(self, reader: int, target: int) -> Path:
        """Là où se pose la vue qu'a ``reader`` de l'atelier de ``target`` : un dossier au nom du commit vu, un seul
        à la fois."""
        return self._views_of(reader) / f"projet-{int(target)}"

    def _view_lock(self, reader: int) -> asyncio.Lock:
        return self._view_locks.setdefault(int(reader), asyncio.Lock())

    async def view(self, reader: int, target: int, *, fresh: bool = False) -> View:
        key = (int(reader), int(target))
        if fresh:
            # Ce qu'on avait mémorisé ne vaut plus dès qu'on demande une pose fraîche (ADR 0262) — avant même
            # d'attendre son tour : si l'échéance de l'enrichisseur coupe la pose lente d'une autre vue du même
            # lecteur, celle-ci, qui attendait, ne garde pas non plus son commit d'avant.
            self._views.pop(key, None)
        async with self._view_lock(reader):
            known = self._views.get(key)
            if known is not None and (not known.sha or (self._view_home(*key) / known.sha).is_dir()):
                # telle qu'elle a été posée au départ de l'exécution (ou à l'instant, par un appel simultané) : elle
                # ne bouge pas en route
                return known
            # Une pose annulée (l'échéance de l'enrichisseur) ou qui lève ne laisse ni le commit d'avant ni un « pas
            # de commit » d'avant répondre à sa place : rien n'est mémorisé, et l'appel suivant repose à la tête
            # courante. Une pose qui rend sa réponse — une vue, ou pourquoi il n'y en a pas — la mémorise : c'est
            # celle de cette tête-ci.
            self._views.pop(key, None)
            self._views[key] = view = await self._pose(*key)
            return view

    async def _pose(self, reader: int, target: int) -> View:
        """Pose la vue, ou dit pourquoi il n'y en a pas. La tête de la branche de base se relit dans le dépôt du
        projet lu (pas ``HEAD`` : pas la branche où son atelier se trouve) ; un commit déjà posé sert tel quel, un
        autre le remplace, et ce qui n'est plus la vue est effacé."""
        home = self._view_home(reader, target)
        repo = self.folder(target) / ".git"
        loop = asyncio.get_running_loop()
        if reader == target or not repo.is_dir():
            await loop.run_in_executor(None, self._unpose, reader, target)
            return View(target, why=NO_COMMIT)
        if not self.bwrap:  # git ne lit le dépôt d'un autre projet que dans la cage : jamais de repli
            return View(target, why=UNREADABLE)
        cage.private_root(self.root)
        home.mkdir(parents=True, exist_ok=True)
        tip = await self._view_git(repo, home, "for-each-ref", "--count=1",
                                   "--format=%(objectname)%1f%(committerdate:unix)", f"refs/heads/{BASE_BRANCH}")
        if not tip.ok:
            return View(target, why=UNREADABLE)
        sha, _, stamp = tip.stdout.strip().partition("\x1f")
        if not _FULL_SHA.match(sha):  # la branche de base n'a encore aucun commit
            await loop.run_in_executor(None, self._unpose, reader, target)
            return View(target, why=NO_COMMIT)
        at = int(stamp) * 1_000_000 if stamp.isdigit() else 0
        if not (home / sha).is_dir():
            why = await self._checkout(repo, home, sha)
            if why == TOO_BIG:  # la vue d'avant ne dit plus où en est le projet : elle part aussi
                await loop.run_in_executor(None, self._unpose, reader, target)
            if why:
                return View(target, at=at, why=why)
        await loop.run_in_executor(None, self._sweep, home, sha)
        return View(target, sha, at)

    async def _checkout(self, repo: Path, home: Path, sha: str) -> str:
        """Recopie le commit ``sha`` du dépôt ``repo`` dans ``home/<sha>`` ; rend pourquoi il ne l'a pas fait (vide :
        c'est fait). La place se mesure dans le commit avant de rien poser, puis sur l'arbre réellement posé avant
        de le mettre en place : ``checkout-index`` applique les attributs du dépôt lu (``ident``,
        ``working-tree-encoding``, ``eol``), qui peuvent multiplier ce que pèsent ses blobs (ADR 0262). L'index est
        un fichier à part, dans le dossier de la pose : celui du projet lu n'est ni lu ni écrit."""
        listed = await self._view_git(repo, home, "ls-tree", "-r", "-l", "-z", sha, clip=False)
        if listed.truncated:  # trop de fichiers pour seulement les compter
            return TOO_BIG
        if not listed.ok:
            return UNREADABLE
        size = 0
        for record in listed.stdout.split("\x00"):
            fields = record.partition("\t")[0].split()  # « mode type objet taille », puis le chemin
            if len(fields) == 4 and fields[3].isdigit():
                size += int(fields[3])
        if size > self.limits.view_bytes:
            return TOO_BIG
        loop = asyncio.get_running_loop()
        stage = home / f".pose-{next(self._poses)}"
        tree = stage / "arbre"
        tree.mkdir(parents=True)
        index = {"GIT_INDEX_FILE": str(stage / "index")}
        try:
            done = await self._view_git(repo, home, "read-tree", sha, extra_env=index)
            if done.ok:
                done = await self._view_git(repo, home, f"--work-tree={tree}", "checkout-index", "--all", "--force",
                                            f"--prefix={tree}/", extra_env=index, timeout_s=VIEW_TIMEOUT_S)
            if not done.ok:
                return UNREADABLE
            posed = await loop.run_in_executor(None, self._measure, tree, self.limits.view_bytes)
            if posed > self.limits.view_bytes:  # plus gros posé que dans le commit : il n'est pas mis en place
                return TOO_BIG
            os.rename(tree, home / sha)
            return ""
        except OSError:
            return UNREADABLE
        finally:
            await loop.run_in_executor(None, shutil.rmtree, stage, True)

    async def _view_git(self, repo: Path, where: Path, *args: str, timeout_s: float = 30.0,
                        extra_env: Mapping[str, str] | None = None, clip: bool = True) -> RunResult:
        """Un git qui **lit** le dépôt d'un projet lu, pour poser la vue qu'un autre projet en a : dans une cage sans
        réseau où ce dépôt est monté en lecture seule — rien ne s'y écrit, quoi que git veuille — et où seul
        ``where`` (là où la vue se pose) s'écrit."""
        assert self.bwrap
        argv = ("git", *args)
        exe = shutil.which("git", path=SYSTEM_PATH)
        if exe is None:
            return RunResult(argv, None, refused="git est absent de l'environnement isolé")
        cmd = self._sandbox(where, [exe, *_GIT, f"--git-dir={repo}", *args], "", read_only=((repo, repo),))
        loop = asyncio.get_running_loop()
        job = _Job()
        try:
            return await loop.run_in_executor(None, self._run_sync, argv, cmd, where, timeout_s,
                                              {**_GIT_ENV, **dict(extra_env or {})}, (), job, clip)
        except asyncio.CancelledError:
            job.cancel()  # la pose est annulée (l'échéance d'un enrichisseur) : son git ne lui survit pas
            raise

    @staticmethod
    def _sweep(home: Path, keep: str) -> None:
        """Efface, là où une vue se pose, tout ce qui n'est pas le commit vu : la vue d'avant, une pose inachevée."""
        try:
            names = [e.name for e in os.scandir(home)]
        except OSError:
            return
        for name in names:
            if name != keep:
                shutil.rmtree(home / name, ignore_errors=True)

    def _unpose(self, reader: int, target: int) -> None:
        """Efface la vue qu'a ``reader`` de ``target``, et le dossier vide où elle se montait dans son atelier —
        jamais à travers un lien symbolique : un ``liens`` dont un programme du lecteur a fait un lien vers
        l'atelier d'un autre projet y ferait supprimer un dossier vide (comme ``_mount_point``, qui n'y monte rien)."""
        shutil.rmtree(self._view_home(reader, target), ignore_errors=True)
        at = self.folder(reader) / VIEWS_DIR / str(int(target))
        if at.parent.is_symlink() or at.is_symlink():
            return
        for folder in (at, at.parent):  # seulement s'ils sont vides : ce que le projet y a mis lui-même reste
            try:
                os.rmdir(folder)
            except OSError:
                break

    async def _mounts(self, reader: int, root: Path,
                      targets: Sequence[int]) -> tuple[list[tuple[Path, Path]], tuple[str, ...]]:
        """Les vues à monter pour un programme du projet ``reader`` — chacune (la vue posée, là où elle se lit dans
        son atelier) — et ce qu'il faut dire de celles qui ne l'ont pas été."""
        mounted: list[tuple[Path, Path]] = []
        notes: list[str] = []
        for target in dict.fromkeys(int(t) for t in targets):
            view = await self.view(reader, target)
            if not view.sha:
                continue
            at = self._mount_point(root, target)
            if at is None:
                notes.append(f"La vue {view_place(target)}/ n'est pas montée pour ce programme : « {VIEWS_DIR} » ou "
                             f"« {view_place(target)} » n'est pas un dossier de cet atelier.")
                continue
            mounted.append((self._view_home(reader, target) / view.sha, at))
        return mounted, tuple(notes)

    @staticmethod
    def _mount_point(root: Path, target: int) -> Path | None:
        """Le dossier vide, dans l'atelier du lecteur, sur lequel la vue se monte : bubblewrap ne monte que sur un
        dossier, et le poser ici décide où. Un fichier ou un lien symbolique à cette place ne reçoit rien."""
        at = root / VIEWS_DIR / str(int(target))
        for folder in (at.parent, at):
            try:
                folder.mkdir(exist_ok=True)
            except OSError:
                return None
            if folder.is_symlink():
                return None
        return at

    def _view_root(self, reader: int, target: int) -> Path:
        """La racine de la vue posée, résolue ; ``FileNotFoundError`` si aucune ne l'est."""
        view = self._views.get((int(reader), int(target)))
        root = self._view_home(reader, target) / view.sha if view is not None and view.sha else None
        if root is None or not root.is_dir():
            raise FileNotFoundError(f"aucune vue de l'atelier du projet n° {int(target)} n'est posée")
        return root.resolve()

    async def view_tree(self, reader: int, target: int, path: str = ".") -> list[str]:
        base = self._view_root(reader, target)
        start = self._confined(base, path or ".", "la vue")
        prefix = view_place(target) + "/"
        try:
            st = os.lstat(start)
        except OSError:
            return []
        if not stat.S_ISDIR(st.st_mode):
            return [view_entry(_entry(prefix + str(start.relative_to(base)), st))]
        loop = asyncio.get_running_loop()
        return self._listing(await loop.run_in_executor(None, self._walk, base, start), prefix)

    async def view_read(self, reader: int, target: int, path: str) -> str:
        found = self._confined(self._view_root(reader, target), path, "la vue")
        if not found.is_file():
            raise FileNotFoundError(f"{view_place(target, path)} n'existe pas dans la vue du projet n° {int(target)} "
                                    "(un dossier se liste avec ws_list)")
        return self._text(found)

    async def drop_views(self, reader: int, keep: Sequence[int] = ()) -> None:
        kept = frozenset(int(t) for t in keep)
        async with self._view_lock(reader):
            for key in [k for k in self._views if k[0] == int(reader) and k[1] not in kept]:
                del self._views[key]
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._drop_sync, int(reader), kept)

    def _drop_sync(self, reader: int, kept: frozenset[int]) -> None:
        home = self._views_of(reader)
        try:
            names = [e.name for e in os.scandir(home)]
        except OSError:
            return  # ce projet n'a aucune vue
        for name in names:
            number = name.removeprefix("projet-")
            if number.isdecimal() and int(number) not in kept:
                self._unpose(reader, int(number))
            elif not number.isdecimal():
                shutil.rmtree(home / name, ignore_errors=True)
        try:
            os.rmdir(home)
        except OSError:
            pass

    # ── la copie d'un commit, pour une relecture (ADR 0277) ──
    def _copy_home(self, project: int) -> Path:
        return self.root / REVIEWS_DIRNAME / f"projet-{int(project)}"

    def _copy_root(self, project: int, sha: str) -> Path:
        """La copie posée de ce commit, résolue ; ``FileNotFoundError`` si elle ne l'est pas. Un identifiant abrégé
        (un journal d'avant l'ADR 0277) désigne la copie posée dont le nom commence par lui."""
        home, root = self._copy_home(project), None
        if _FULL_SHA.match(sha or ""):
            root = home / sha
        elif _SHA.match(sha or "") and home.is_dir():
            found = [d for d in home.iterdir() if d.name.startswith(sha) and _FULL_SHA.match(d.name)]
            root = found[0] if len(found) == 1 else None
        if root is None or not root.is_dir():
            raise FileNotFoundError(f"aucune copie du commit {str(sha)[:12] or '?'} n'est posée")
        return root.resolve()

    async def checkout(self, project: int, sha: str) -> str:
        if not _SHA.match(sha or "") or not (self.folder(project) / ".git").is_dir():
            return NO_COMMIT
        if not self.bwrap:  # git ne recopie un commit que dans la cage : jamais de repli
            return UNREADABLE
        full = sha if _FULL_SHA.match(sha) else await self._ref(project, sha)
        if not full:
            return NO_COMMIT
        home = self._copy_home(project)
        async with self._copy_locks.setdefault(int(project), asyncio.Lock()):
            cage.private_root(self.root)
            home.mkdir(parents=True, exist_ok=True)
            if not (home / full).is_dir():
                why = await self._checkout(self.folder(project) / ".git", home, full)
                if why:
                    return why
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sweep, home, full)  # une seule copie à la fois : celle-ci
        return ""

    async def copy_tree(self, project: int, sha: str, path: str = ".") -> list[str]:
        base = self._copy_root(project, sha)
        start = self._confined(base, path or ".", "la copie relue")
        try:
            st = os.lstat(start)
        except OSError:
            return []
        if not stat.S_ISDIR(st.st_mode):
            return [_entry(str(start.relative_to(base)), st)]
        loop = asyncio.get_running_loop()
        return self._listing(await loop.run_in_executor(None, self._walk, base, start))

    async def copy_read(self, project: int, sha: str, path: str) -> str:
        found = self._confined(self._copy_root(project, sha), path, "la copie relue")
        if not found.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans le commit relu (un dossier se liste)")
        return self._text(found)

    async def copy_run(self, project: int, sha: str, argv: Sequence[str], *, timeout_s: float | None = None,
                       views: Sequence[int] = ()) -> RunResult:
        args = [str(a) for a in argv]
        if not args:
            return RunResult((), None, refused="commande vide")
        program = Path(args[0]).name
        if program not in self.allowed:
            return RunResult(tuple(args), None, refused=f"« {program} » n'est pas autorisé ici. Autorisés : "
                                                        f"{', '.join(sorted(self.allowed))}.")
        if not self.bwrap:
            return RunResult(tuple(args), None, refused="bubblewrap est absent : aucune exécution sans isolation")
        try:
            copy = self._copy_root(project, sha)
        except FileNotFoundError as exc:
            return RunResult(tuple(args), None, refused=str(exc))
        loop = asyncio.get_running_loop()
        if await loop.run_in_executor(None, self._measure, copy) > self.limits.workshop_bytes \
                and program not in CLEANING:
            return RunResult(tuple(args), None, refused="la copie relue est pleine : plus rien ne s'y lance")
        # dans la cage, la copie est montée à la place de l'atelier, au même chemin : ses environnements (montés
        # en lecture seule) gardent leurs chemins absolus, et rien de l'atelier lui-même ne s'y écrit
        root = self.folder(project).resolve()
        if "/" in args[0]:  # un programme du dépôt : celui du commit relu
            try:
                inside = self._confined(copy, args[0], "la copie relue")
            except OutsideWorkshop as exc:
                return RunResult(tuple(args), None, refused=str(exc))
            exe = str(root / inside.relative_to(copy)) if inside.is_file() and os.access(inside, os.X_OK) else None
        else:
            exe = self._visible(args[0], root)
        if exe is None:
            return RunResult(tuple(args), None, refused=f"« {args[0]} » est absent de l'environnement isolé")
        (copy / HOME_DIRNAME).mkdir(exist_ok=True)
        mounted: list[tuple[Path, Path]] = []
        for name in ENVIRONMENTS:
            real, at = root / name, copy / name
            if not real.is_dir() or real.is_symlink() or at.is_symlink() or (at.exists() and not at.is_dir()):
                continue
            if at.is_dir() and any(at.iterdir()):
                continue  # le commit porte le sien : c'est lui qu'elle relit
            at.mkdir(exist_ok=True)
            mounted.append((real, root / name))
        seen, notes = await self._mounts(project, copy, views)
        mounted += [(source, root / at.relative_to(copy)) for source, at in seen]
        cmd = self._sandbox(root, [exe, *args[1:]], "", read_only=mounted, source=copy)
        job = _Job()
        try:
            # l'environnement se construit sur le chemin de l'atelier : c'est là que la cage montre la copie
            result = await loop.run_in_executor(None, self._run_sync, tuple(args), cmd, root,
                                                timeout_s or self.timeout_s, None, (), job, True)
        except asyncio.CancelledError:
            job.cancel()
            raise
        return replace(result, notes=(*result.notes, *notes)) if notes else result

    async def discard(self, project: int) -> None:
        async with self._copy_locks.setdefault(int(project), asyncio.Lock()):
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, shutil.rmtree, self._copy_home(project), True)


__all__ = ["BwrapWorkshop"]
