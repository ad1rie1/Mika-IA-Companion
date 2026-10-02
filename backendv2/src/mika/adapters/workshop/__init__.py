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
- **L'arbre** d'un atelier se lit depuis git (suivis, et nouveaux non ignorés :
  ni ``.venv`` ni ``node_modules``), en largeur d'abord, chaque entrée par
  ``lstat`` (un lien cassé est une entrée, pas une panne), hors de la boucle.

Les commandes tournent dans un fil (``run_in_executor``) : l'attente du
processus ne bloque pas la boucle ; en simulation, l'exécuteur est en ligne.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
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

from mika.ports.workshop import Commit, OutsideWorkshop, RunResult, WorkshopFull

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
#: un parcours d'arbre sans git s'arrête après tant d'entrées vues
WALK_MAX = 20_000
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
_SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
_SYSTEM_FILES = ("/etc/passwd", "/etc/group", "/etc/nsswitch.conf", "/etc/ld.so.cache", "/etc/localtime")
_NETWORK_FILES = ("/etc/hosts", "/etc/ssl", "/etc/pki", "/etc/ca-certificates")
#: le réseau à part : une adresse, une passerelle et un résolveur qui n'existent nulle part (TEST-NET-1, RFC 5737)
NET_ADDRESS, NET_GATEWAY, NET_DNS = "192.0.2.2", "192.0.2.1", "192.0.2.3"
#: ce que le réseau à part ne joint jamais : le réseau local, l'opérateur, les métadonnées d'un nuage, le réservé
#: (la boucle locale de la cage est la sienne : rien de l'hôte n'y est relayé)
UNREACHABLE = ("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
               "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4",
               "240.0.0.0/4")
_GIT = ("-c", "user.name=Mika", "-c", "user.email=mika@atelier.local", "-c", "commit.gpgsign=false",
        "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main")
#: un identifiant de commit (abrégé ou complet), une branche
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
#: ce que git dit d'un enregistrement (``--shortstat``)
_STAT = re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")
REMOTE_TIMEOUT_S = 180.0
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


def check_remote(url: str) -> str:
    """Une adresse de dépôt distant acceptable (https, sans identifiants dedans), ou ``ValueError``."""
    raw = (url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("une adresse https (https://github.com/compte/depot.git)")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("pas d'identifiants dans l'adresse : le jeton se règle dans Configuration › Canaux › "
                         "Dépôts git")
    if any(ch.isspace() for ch in raw) or raw.startswith("-"):
        raise ValueError("adresse illisible")
    return raw


def check_branch(branch: str) -> str:
    raw = (branch or "").strip() or "main"
    if not _BRANCH.match(raw) or ".." in raw or raw.endswith((".lock", "/")):
        raise ValueError(f"nom de branche refusé : {raw[:40]}")
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


def _size(n: int) -> str:
    return f"{n / 1024 ** 2:.0f} Mo" if n < 1024 ** 3 else f"{n / 1024 ** 3:.1f} Go"


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
                 pasta: str | None = None, ip: str | None = None) -> None:
        self.root = Path(root)
        self.credentials = credentials
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

    # ── le dossier ──
    def folder(self, goal: int) -> Path:
        return self.root / f"projet-{int(goal)}"

    def exists(self, goal: int) -> bool:
        return self.folder(goal).is_dir()

    def _open(self, goal: int) -> Path:
        d = self.folder(goal)
        (d / HOME_DIRNAME).mkdir(parents=True, exist_ok=True)
        return d

    def path(self, goal: int, rel: str, *, write: bool = False) -> Path:
        """Résout ``rel`` dans l'atelier, ou lève ``OutsideWorkshop`` (une lecture ne crée rien)."""
        base = (self._open(goal) if write else self.folder(goal)).resolve()
        raw = str(rel or "").strip()
        if raw and Path(raw).is_absolute():
            raise OutsideWorkshop(f"chemin absolu refusé : {raw} — écris un chemin relatif au dossier")
        target = base / raw if raw and raw not in (".", "./") else base
        try:
            resolved = target.resolve()
        except (OSError, RuntimeError) as exc:  # une boucle de liens
            raise OutsideWorkshop(f"chemin illisible : {raw} ({exc})") from exc
        if resolved != base and not resolved.is_relative_to(base):
            raise OutsideWorkshop(f"hors de l'atelier : {raw}")
        if write:
            parts = resolved.relative_to(base).parts if resolved != base else ()
            if not parts:
                raise OutsideWorkshop("écris un fichier, pas le dossier lui-même")
            if parts[0] in ORGANS:
                raise OutsideWorkshop(f"« {parts[0]}/ » appartient à l'atelier lui-même : il ne s'écrit pas")
        return resolved

    def _rel(self, goal: int, p: Path) -> str:
        return str(p.relative_to(self.folder(goal).resolve()))

    def full(self, goal: int) -> str:
        """Pourquoi l'atelier n'accepte plus rien (vide : il accepte)."""
        size = self._sizes.get(goal, 0)
        if size <= self.limits.workshop_bytes:
            return ""
        return (f"l'atelier pèse {_size(size)} (au plus {_size(self.limits.workshop_bytes)}) : fais de la place "
                "(rm …) avant d'écrire ou de lancer autre chose")

    def _grew(self, goal: int, n: int) -> None:
        if goal in self._sizes:
            self._sizes[goal] += n

    async def _room(self, goal: int) -> None:
        """Lève ``WorkshopFull`` si l'atelier dépasse sa taille. Sa taille se mesure une première fois (hors de la
        boucle) au premier besoin : un atelier rempli fichier par fichier, sans jamais rien lancer, est borné lui
        aussi ; ensuite, chaque écriture l'ajoute, et chaque exécution la remesure."""
        if goal not in self._sizes and self.exists(goal):
            loop = asyncio.get_running_loop()
            self._sizes[goal] = await loop.run_in_executor(None, self._measure, self.folder(goal))
        if why := self.full(goal):
            raise WorkshopFull(why)

    async def tree(self, goal: int, path: str = ".") -> list[str]:
        """Les fichiers de l'atelier (ou d'un de ses dossiers), en largeur d'abord : ce que git suit et ce qui est
        nouveau sans être ignoré (ni ``.venv`` ni ``node_modules``), sinon un parcours borné. Chaque entrée est lue
        par ``lstat`` : un lien cassé reste une entrée. Rien de tout ça ne tourne sur la boucle."""
        start = self.path(goal, path or ".")
        try:
            st = os.lstat(start)
        except OSError:
            return []
        if not stat.S_ISDIR(st.st_mode):
            return [_entry(self._rel(goal, start), st)]
        listed = await self._listed(goal)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._tree_sync, goal, start, listed)

    async def _listed(self, goal: int) -> list[str] | None:
        """Ce que git voit (suivis, et nouveaux non ignorés), ou ``None`` (pas de dépôt, ou git ne répond pas)."""
        if not (self.folder(goal) / ".git").is_dir():
            return None
        r = await self._git(goal, "-c", "core.quotepath=off", "ls-files", "-z", "--cached", "--others",
                            "--exclude-standard")
        if not r.ok:
            return None
        return [p for p in r.stdout.split("\x00") if p]

    def _tree_sync(self, goal: int, start: Path, listed: list[str] | None) -> list[str]:
        base = self.folder(goal).resolve()
        prefix = "" if start == base else self._rel(goal, start) + "/"
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
            rows = self._walk(goal, start)
        rows.sort(key=lambda r: (r[0], r[1]))
        out = [_entry(rel, st) for _, rel, st in rows[: self.max_tree]]
        if len(rows) > self.max_tree:
            out.append(f"[… liste coupée à {self.max_tree} entrées sur {len(rows)} …]")
        return out

    def _walk(self, goal: int, start: Path) -> list[tuple[int, str, os.stat_result]]:
        """Un parcours en largeur, borné, qui ne descend ni dans les organes ni dans le bruit."""
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
                rel = self._rel(goal, Path(e.path))
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

    async def read(self, goal: int, path: str) -> str:
        target = self.path(goal, path)
        if not target.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier (un dossier se liste avec ws_list)")
        raw = target.read_bytes()[: self.max_file + 1]
        text = raw[: self.max_file].decode("utf-8", errors="replace")
        return text + ("\n\n[… fichier tronqué …]" if len(raw) > self.max_file else "")

    async def write(self, goal: int, path: str, content: str) -> str:
        target = self.path(goal, path, write=True)
        await self._room(goal)
        await self._init(goal)  # l'amorce d'abord : le premier travail sera son propre commit
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        self._grew(goal, len(str(content).encode()))
        return self._rel(goal, target)

    async def write_bytes(self, goal: int, path: str, data: bytes) -> str:
        target = self.path(goal, path, write=True)
        await self._room(goal)
        await self._init(goal)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(data))
        self._grew(goal, len(data))
        return self._rel(goal, target)

    async def read_bytes(self, goal: int, path: str, limit: int) -> bytes:
        target = self.path(goal, path)
        if not target.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier")
        with target.open("rb") as f:
            return f.read(max(0, limit))

    async def edit(self, goal: int, path: str, old: str, new: str) -> str:
        """Remplacement exact et unique : une édition « à peu près » donne un
        fichier plausible et faux."""
        target = self.path(goal, path, write=True)
        if not target.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier")
        await self._room(goal)
        await self._init(goal)
        text = target.read_text(encoding="utf-8", errors="replace")
        n = text.count(old)
        if n == 0:
            raise ValueError(f"fragment introuvable dans {path} — relis le fichier avant de l'éditer")
        if n > 1:
            raise ValueError(f"fragment présent {n} fois dans {path} — donne un extrait plus large")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        self._grew(goal, len(new.encode()) - len(old.encode()))
        return self._rel(goal, target)

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
        d = self.root / ".reseau"
        d.mkdir(parents=True, exist_ok=True)
        conf = d / "resolv.conf"
        wanted = f"nameserver {NET_DNS}\noptions timeout:3 attempts:2\n"
        if not conf.exists() or conf.read_text(encoding="utf-8") != wanted:
            conf.write_text(wanted, encoding="utf-8")
        return conf

    def _sandbox(self, root: Path, argv: list[str], network: str, protect_git: bool = False) -> list[str]:
        """La cage bubblewrap. ``network`` : ``""`` (aucun), ``"isolated"`` (le réseau à part de pasta, posé
        autour), ``"host"`` (celui de l'hôte : les git de l'atelier seulement, faute de pasta)."""
        assert self.bwrap is not None
        args = [self.bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL"]
        if network:
            args.append("--share-net")
        if network == "isolated":  # dans l'espace de pasta, on est « root » : la cage reprend son utilisateur
            args += ["--uid", str(os.getuid()), "--gid", str(os.getgid())]
        for d in _SYSTEM_DIRS:
            p = Path(d)
            if p.is_symlink():
                args += ["--symlink", os.readlink(p), d]
            elif p.is_dir():
                args += ["--ro-bind", d, d]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        for f in _SYSTEM_FILES + (_NETWORK_FILES if network else ()):
            if Path(f).exists():
                args += ["--ro-bind", f, f]
        if network == "isolated":
            args += ["--ro-bind", str(self._resolver()), "/etc/resolv.conf"]
        elif network == "host" and Path("/etc/resolv.conf").exists():
            args += ["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf"]
        args += ["--bind", str(root), str(root)]
        if protect_git and (root / ".git").is_dir():  # le dépôt est à l'atelier : ce que lance le modèle le lit seulement
            args += ["--ro-bind", str(root / ".git"), str(root / ".git")]
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
        routes = list(UNREACHABLE)
        nets = [ipaddress.ip_network(r) for r in UNREACHABLE]
        for addr in self._host_addresses():
            if not any(addr in n for n in nets):
                routes.append(f"{addr}/32")
        script = "; ".join(f"{self.ip} route add unreachable {r} || exit 97" for r in dict.fromkeys(routes))
        return [self.pasta, "--config-net", "--quiet", "-4", "-a", NET_ADDRESS, "-n", "24", "-g", NET_GATEWAY,
                "--no-map-gw", "--dns-forward", NET_DNS, "-t", "none", "-u", "none", "-T", "none", "-U", "none",
                "--", self.sh, "-c", script + '; exec "$0" "$@"', *inner]

    def _host_addresses(self) -> list[ipaddress.IPv4Address]:
        """Les adresses IPv4 de la machine elle-même (l'adresse publique d'un serveur joindrait ses propres
        services) ; au mieux : sans réponse, la liste est vide."""
        try:
            r = subprocess.run([str(self.ip), "-o", "-4", "addr", "show"], capture_output=True, text=True,
                               timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return []
        out = []
        for m in re.finditer(r"\binet (\d+\.\d+\.\d+\.\d+)", r.stdout):
            try:
                out.append(ipaddress.IPv4Address(m.group(1)))
            except ValueError:
                continue
        return out

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

    async def run(self, goal: int, argv: Sequence[str], *, timeout_s: float | None = None,
                  network: bool = False, check_allowed: bool = True,
                  extra_env: Mapping[str, str] | None = None, secrets: Sequence[str] = ()) -> RunResult:
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
            full = self.full(goal)
            if full and program not in CLEANING:
                return RunResult(tuple(args), None, refused=full)
            await self._init(goal)
        root = self._open(goal).resolve()
        exe = self._visible(args[0], root)
        if exe is None:
            return RunResult(tuple(args), None, refused=f"« {args[0]} » est absent de l'environnement isolé "
                                                        "(installe-le dans l'atelier : .venv/bin, node_modules/.bin)")
        cmd = self._sandbox(root, [exe, *args[1:]], mode, protect_git=check_allowed)
        if mode == "isolated":
            cmd = self._isolated(cmd)
        limit = timeout_s or self.timeout_s
        loop = asyncio.get_running_loop()
        job = _Job()
        try:
            result = await loop.run_in_executor(None, self._run_sync, tuple(args), cmd, root, limit, extra_env,
                                                tuple(x for x in secrets if x), job)
        except asyncio.CancelledError:
            job.cancel()  # l'exécution est annulée : ce qu'elle a lancé ne lui survit pas
            raise
        if check_allowed:
            self._sizes[goal] = await loop.run_in_executor(None, self._measure, root)
            if self.full(goal):
                result = replace(result, notes=(*result.notes, f"Attention : {self.full(goal)}."))
        return result

    def _measure(self, root: Path) -> int:
        """La place qu'occupe l'atelier (sans suivre les liens), en s'arrêtant dès qu'elle dépasse franchement la
        limite."""
        total, stop = 0, self.limits.workshop_bytes * 2
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
                  job: _Job | None = None) -> RunResult:
        job = job or _Job()
        start = time.perf_counter()
        try:
            proc = subprocess.Popen(cmd, cwd=str(root), env=self._env(root, extra_env), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                                    preexec_fn=self._limit)  # noqa: PLW1509 — les limites du processus fils
        except OSError as exc:
            return RunResult(argv, None, refused=f"lancement impossible : {exc}")
        if not job.attach(proc):
            _killpg(proc)  # annulée avant même de partir
        timed_out, overflow, raw = self._collect(proc, limit, job)
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
            text = bytes(buf[: self.max_output * 4]).decode("utf-8", errors="replace")
            for secret in secrets:  # avant de couper : un secret à cheval sur la coupure reste reconnu
                text = text.replace(secret, "***")
            text, clipped = _clip(text, self.max_output)
            texts.append(text)
            cut |= clipped or len(buf) > self.max_output * 4
        notes: tuple[str, ...] = ()
        if overflow:
            notes = (f"Programme arrêté : sa sortie dépassait {_size(self.limits.output_bytes)}.",)
        elif job.cancelled:
            notes = ("Programme arrêté : l'exécution qui l'avait lancé a été interrompue.",)
        return RunResult(argv, proc.returncode, texts[0], texts[1], duration, timed_out, cut, notes=notes)

    def _collect(self, proc: subprocess.Popen[bytes], limit: float, job: _Job
                 ) -> tuple[bool, bool, tuple[bytearray, bytearray]]:
        """Lit la sortie et les erreurs par leurs tubes jusqu'à la fin du programme, son délai, une annulation ou
        un flux qui dépasse sa limite (on garde le début : ce qu'on rend est de toute façon coupé). Rend (délai,
        débordement, ce qui a été lu)."""
        assert proc.stdout is not None and proc.stderr is not None
        out, err = bytearray(), bytearray()
        streams = {proc.stdout.fileno(): out, proc.stderr.fileno(): err}
        sizes = dict.fromkeys(streams, 0)
        keep = self.max_output * 4 + 1
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
    async def _git(self, goal: int, *args: str, network: bool = False, timeout_s: float = 30,
                   extra_env: Mapping[str, str] | None = None, secrets: Sequence[str] = ()) -> RunResult:
        return await self.run(goal, ["git", *_GIT, *args], timeout_s=timeout_s, check_allowed=False,
                              network=network, extra_env={**_GIT_ENV, **dict(extra_env or {})}, secrets=secrets)

    async def _init(self, goal: int) -> bool:
        root = self._open(goal)
        if (root / ".git").exists():
            return True
        r = await self._git(goal, "init", "-q")
        if not r.ok:
            return False
        self._exclude(root)
        (root / ".gitignore").write_text(f"{HOME_DIRNAME}/\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n",
                                         encoding="utf-8")
        await self._git(goal, "add", "-A")
        await self._git(goal, "commit", "-q", "-m", "atelier ouvert")
        return True

    @staticmethod
    def _exclude(root: Path) -> None:
        """La maison de l'atelier n'entre jamais dans le dépôt, même si un dépôt récupéré change le
        ``.gitignore`` (l'exclusion locale n'est pas versionnée)."""
        info = root / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "exclude").write_text(f"{HOME_DIRNAME}/\n", encoding="utf-8")

    async def commit(self, goal: int, message: str, paths: Sequence[str] = ()) -> str:
        if not self.exists(goal) or not await self._init(goal):
            return ""
        only = [f":(literal){p}" for p in paths if p]
        scope = ("--", *only) if only else ()
        state = await self._git(goal, "status", "--porcelain", *scope)
        if not state.ok or not state.stdout.strip():
            return ""
        await self._git(goal, "add", "-A", *scope)
        title = re.sub(r"\s+", " ", (message or "travail")).strip()[:72] or "travail"
        done = await self._git(goal, "commit", "-q", "-m", title, *scope)
        if not done.ok:
            return ""
        sha = await self._git(goal, "rev-parse", "--short", "HEAD")
        return sha.stdout.strip() if sha.ok else ""

    async def diff(self, goal: int) -> str:
        """Ce qui a changé depuis le dernier enregistrement : le diff des fichiers suivis, puis les fichiers nouveaux
        (que ``git diff`` ne montre pas)."""
        if not (self.folder(goal) / ".git").exists():
            return ""
        r = await self._git(goal, "diff", "HEAD", "--stat", "-p")
        new = [p[3:] for p in await self._status(goal) if p.startswith("??")]
        text = r.stdout if r.ok else ""
        if new:
            text += ("\n" if text else "") + "Fichiers nouveaux, pas encore enregistrés :\n" + \
                "\n".join(f"+ {n}" for n in new[:200])
        return text

    async def _status(self, goal: int) -> list[str]:
        r = await self._git(goal, "status", "--porcelain", "--untracked-files=all")
        return [line for line in r.stdout.splitlines() if line.strip()] if r.ok else []

    async def pending(self, goal: int) -> list[str]:
        if not (self.folder(goal) / ".git").exists():
            return []
        return [line[3:] for line in await self._status(goal)]

    async def log(self, goal: int, n: int = 10, *, offset: int = 0) -> str:
        if not (self.folder(goal) / ".git").exists():
            return ""
        r = await self._git(goal, "log", f"-{max(1, n)}", f"--skip={max(0, offset)}", "--format=%h %s")
        return r.stdout if r.ok else ""

    async def commits(self, goal: int, n: int = 25, *, offset: int = 0) -> list[Commit]:
        if not (self.folder(goal) / ".git").exists():
            return []
        # une entrée commence par un NUL (qu'un message de commit ne peut pas contenir) ; le titre vient en
        # dernier : un séparateur glissé dans un message ne fabrique ni une fausse ligne ni un faux auteur
        r = await self._git(goal, "log", f"-{max(1, n)}", f"--skip={max(0, offset)}", "--shortstat",
                            "--format=%x00%h%x1f%ct%x1f%an%x1f%s")
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

    async def count(self, goal: int) -> int:
        if not (self.folder(goal) / ".git").exists():
            return 0
        r = await self._git(goal, "rev-list", "--count", "HEAD")
        return int(r.stdout.strip()) if r.ok and r.stdout.strip().isdigit() else 0

    async def head(self, goal: int) -> str:
        """Le commit courant (complet), ou ``""``."""
        if not (self.folder(goal) / ".git").exists():
            return ""
        r = await self._git(goal, "rev-parse", "--verify", "-q", "HEAD^{commit}")
        sha = r.stdout.strip()
        return sha if r.ok and _SHA.match(sha) else ""

    async def show(self, goal: int, sha: str) -> str:
        if not _SHA.match(sha or "") or not (self.folder(goal) / ".git").exists():
            return ""
        r = await self._git(goal, "show", "--stat", "-p", "--format=%H%n%an, %cd%n%n%B", "--date=iso", sha)
        if not r.ok:
            return ""
        text = r.stdout
        return text if len(text) <= SHOW_MAX_CHARS else text[:SHOW_MAX_CHARS] + "\n[… coupé …]"

    # ── le dépôt distant ──
    def _auth(self, url: str) -> tuple[dict[str, str], tuple[str, ...], str]:
        """L'environnement d'authentification de git pour ce dépôt, les secrets à effacer des sorties, et ce
        qui empêche de montrer le jeton (vide : rien)."""
        creds = dict(self.credentials() if self.credentials is not None else {})
        token = (creds.get("token") or "").strip()
        env = {"GIT_ASKPASS": "/bin/false"}
        if not token:
            return env, (), "aucun jeton : règle-le dans Configuration › Canaux › Dépôts git"
        hosts = creds.get("hosts") or DEFAULT_HOSTS
        allowed = {h.strip().lower() for h in (hosts.split(",") if isinstance(hosts, str) else hosts) if h.strip()}
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host not in allowed:
            return env, (), (f"le jeton n'est pas autorisé pour « {host} » (hôtes autorisés : "
                             f"{', '.join(sorted(allowed)) or 'aucun'} — Configuration › Canaux › Dépôts git)")
        basic = base64.b64encode(f"{creds.get('user') or 'x-access-token'}:{token}".encode()).decode()
        # l'en-tête ne vaut que pour l'adresse de ce dépôt (le chemin compris, et le port s'il y en a un)
        scope = f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.{scope}.extraheader",
                    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"})
        return env, (token, basic), ""

    async def _clean_config(self, goal: int) -> str:
        """Ce qui, dans la configuration locale du dépôt, n'a rien à y faire (vide : rien) — on ne parle pas au
        distant avec une configuration qu'on n'a pas posée."""
        r = await self._git(goal, "config", "--local", "--name-only", "--list")
        if not r.ok:
            return "configuration locale illisible"
        odd = sorted({k for k in r.stdout.split() if k and k.lower() not in _LOCAL_KEYS})
        return f"configuration locale inattendue : {', '.join(odd[:5])}" if odd else ""

    async def push(self, goal: int, url: str, branch: str, sha: str = "") -> RunResult:
        try:
            url, branch = check_remote(url), check_branch(branch)
        except ValueError as exc:
            return RunResult(("git", "push"), None, refused=str(exc))
        env, secrets, why = self._auth(url)
        if why:
            return RunResult(("git", "push"), None, refused=f"pas d'envoi : {why}")
        if not await self._init(goal):
            return RunResult(("git", "push"), None, refused="le dépôt de l'atelier ne s'ouvre pas")
        odd = await self._clean_config(goal)
        if odd:
            return RunResult(("git", "push"), None, refused=f"pas d'envoi : {odd}")
        sha = sha or await self.head(goal)
        if not _SHA.match(sha or "") or not (await self._git(goal, "cat-file", "-e", f"{sha}^{{commit}}")).ok:
            return RunResult(("git", "push"), None, refused=f"le commit à envoyer est introuvable : {sha[:40]}")
        r = await self._git(goal, *_REMOTE_GIT, "push", "--no-recurse-submodules", url,
                            f"{sha}:refs/heads/{branch}", network=True, timeout_s=REMOTE_TIMEOUT_S, extra_env=env,
                            secrets=secrets)
        return replace(r, argv=("git", "push", url, f"{sha[:12]} → {branch}"))

    async def pull(self, goal: int, url: str, branch: str) -> RunResult:
        try:
            url, branch = check_remote(url), check_branch(branch)
        except ValueError as exc:
            return RunResult(("git", "pull"), None, refused=str(exc))
        env, secrets, _ = self._auth(url)  # sans jeton (ou pour un autre hôte) : un dépôt public se récupère quand même
        if not await self._init(goal):
            return RunResult(("git", "pull"), None, refused="le dépôt de l'atelier ne s'ouvre pas")
        odd = await self._clean_config(goal)
        if odd:
            return RunResult(("git", "pull"), None, refused=f"pas de récupération : {odd}")
        fetched = await self._git(goal, *_REMOTE_GIT, "fetch", "--no-tags", "--no-recurse-submodules", url, branch,
                                  network=True, timeout_s=REMOTE_TIMEOUT_S, extra_env=env, secrets=secrets)
        if not fetched.ok:
            return replace(fetched, argv=("git", "fetch", url, branch))
        listed = await self._git(goal, "ls-tree", "-r", "--name-only", "FETCH_HEAD")
        organs = [n for n in listed.stdout.splitlines() if n.split("/", 1)[0] in ORGANS]
        if not listed.ok or organs:
            return RunResult(("git", "pull", url, branch), None,
                             refused=f"le dépôt distant contient « {organs[0] if organs else '?'} », qui appartient à "
                                     "l'atelier lui-même : rien n'est récupéré")
        state = await self._git(goal, "status", "--porcelain")
        if not state.ok:
            return RunResult(("git", "pull", url, branch), None, refused="l'état de l'atelier est illisible")
        if await self.count(goal) <= 1 and not state.stdout.strip():
            # un atelier vierge (l'amorce seule) prend l'histoire du dépôt distant, sans écraser aucun fichier
            r = await self._git(goal, "reset", "-q", "--keep", "FETCH_HEAD")
        else:
            r = await self._git(goal, "merge", "--ff-only", "FETCH_HEAD")
        self._exclude(self.folder(goal))
        return replace(r, argv=("git", "pull", url, branch))


__all__ = ["BwrapWorkshop"]
