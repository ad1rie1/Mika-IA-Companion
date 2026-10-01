"""L'atelier réel : un dossier par projet, des programmes isolés par bubblewrap.

- **Confinement des chemins**, un seul contrôle appliqué partout : résoudre,
  puis vérifier l'appartenance (``..`` comme le lien symbolique sortant).
  ``.git`` et la maison de l'atelier ne s'écrivent jamais depuis les outils.
- **Exécution** : bubblewrap (espaces de noms, ``/usr`` en lecture seule, un
  ``/tmp`` éphémère, le dossier seul inscriptible, un environnement
  reconstruit — rien de celui du serveur, donc aucune de ses clés), réseau
  coupé sauf demande approuvée. Délai tenu en **tuant le groupe** de
  processus ; sorties bornées. Sans bubblewrap : refus, jamais de repli.
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

Les commandes tournent dans un fil (``run_in_executor``) : l'attente du
processus ne bloque pas la boucle ; en simulation, l'exécuteur est en ligne.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from mika.ports.workshop import Commit, OutsideWorkshop, RunResult

ALLOWED = ("python", "python3", "pytest", "node", "npm", "npx", "git", "ls", "cat", "head", "tail", "wc", "grep",
           "find", "mkdir", "cp", "mv", "sh", "bash", "echo", "diff", "sort")
HOME_DIRNAME = ".atelier-home"
ORGANS = (".git", HOME_DIRNAME)
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
_SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
_SYSTEM_FILES = ("/etc/passwd", "/etc/group", "/etc/nsswitch.conf", "/etc/ld.so.cache", "/etc/localtime")
_NETWORK_FILES = ("/etc/resolv.conf", "/etc/hosts", "/etc/ssl", "/etc/pki", "/etc/ca-certificates")
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


class BwrapWorkshop:
    def __init__(self, root: Path, *, allowed: Sequence[str] = ALLOWED, timeout_s: float = 120.0,
                 max_output_chars: int = 20_000, max_file_bytes: int = 400_000, max_tree: int = 400,
                 bwrap: str | None = None, which: Callable[[str], str | None] = shutil.which,
                 credentials: Credentials | None = None) -> None:
        self.root = Path(root)
        self.credentials = credentials
        self.allowed = frozenset(allowed)
        self.timeout_s = timeout_s
        self.max_output = max_output_chars
        self.max_file = max_file_bytes
        self.max_tree = max_tree
        self.bwrap = bwrap if bwrap is not None else which("bwrap")

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
        except OSError as exc:
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

    async def tree(self, goal: int, path: str = ".") -> list[str]:
        start = self.path(goal, path)
        if not start.exists():
            return []
        if start.is_file():
            return [self._rel(goal, start)]
        out: list[str] = []
        for p in sorted(start.rglob("*")):
            rel = self._rel(goal, p.resolve()) if p.resolve().is_relative_to(self.folder(goal).resolve()) else None
            if rel is None or p.is_dir() or any(part in ORGANS for part in Path(rel).parts):
                continue
            out.append(f"{rel} ({p.stat().st_size} o)")
            if len(out) >= self.max_tree:
                out.append(f"[… liste coupée à {self.max_tree} entrées …]")
                break
        return out

    async def read(self, goal: int, path: str) -> str:
        target = self.path(goal, path)
        if not target.is_file():
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier")
        raw = target.read_bytes()[: self.max_file + 1]
        text = raw[: self.max_file].decode("utf-8", errors="replace")
        return text + ("\n\n[… fichier tronqué …]" if len(raw) > self.max_file else "")

    async def write(self, goal: int, path: str, content: str) -> str:
        target = self.path(goal, path, write=True)
        await self._init(goal)  # l'amorce d'abord : le premier travail sera son propre commit
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        return self._rel(goal, target)

    async def write_bytes(self, goal: int, path: str, data: bytes) -> str:
        target = self.path(goal, path, write=True)
        await self._init(goal)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(data))
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
        await self._init(goal)
        text = target.read_text(encoding="utf-8", errors="replace")
        n = text.count(old)
        if n == 0:
            raise ValueError(f"fragment introuvable dans {path} — relis le fichier avant de l'éditer")
        if n > 1:
            raise ValueError(f"fragment présent {n} fois dans {path} — donne un extrait plus large")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
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

    def _command(self, root: Path, argv: list[str], network: bool, protect_git: bool = False) -> list[str]:
        assert self.bwrap is not None
        args = [self.bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL"]
        if network:
            args.append("--share-net")
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
        args += ["--bind", str(root), str(root)]
        if protect_git and (root / ".git").is_dir():  # le dépôt est à l'atelier : ce que lance le modèle le lit seulement
            args += ["--ro-bind", str(root / ".git"), str(root / ".git")]
        args += ["--chdir", str(root)]
        return [*args, "--", *argv]

    def _env(self, root: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Construit, jamais hérité : aucune variable du serveur n'entre (seulement ``extra``, que
        l'atelier pose lui-même pour ses propres commandes git)."""
        home = root / HOME_DIRNAME
        return {"PATH": _search_path(root), "HOME": str(home), "TMPDIR": "/tmp", "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                "MIKA_ATELIER": "1", **dict(extra or {})}

    async def run(self, goal: int, argv: Sequence[str], *, timeout_s: float | None = None,
                  network: bool = False, check_allowed: bool = True,
                  extra_env: Mapping[str, str] | None = None, secrets: Sequence[str] = ()) -> RunResult:
        args = [str(a) for a in argv]
        if not args:
            return RunResult((), None, refused="commande vide")
        program = Path(args[0]).name
        if check_allowed and program not in self.allowed:
            return RunResult(tuple(args), None, refused=f"« {program} » n'est pas autorisé ici. Autorisés : "
                                                        f"{', '.join(sorted(self.allowed))}.")
        if not self.bwrap:
            return RunResult(tuple(args), None, refused="bubblewrap est absent : aucune exécution sans isolation")
        if check_allowed:
            await self._init(goal)
        root = self._open(goal).resolve()
        exe = self._visible(args[0], root)
        if exe is None:
            return RunResult(tuple(args), None, refused=f"« {args[0]} » est absent de l'environnement isolé "
                                                        "(installe-le dans l'atelier : .venv/bin, node_modules/.bin)")
        cmd = self._command(root, [exe, *args[1:]], network, protect_git=check_allowed)
        limit = timeout_s or self.timeout_s
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run_sync, tuple(args), cmd, root, limit, extra_env,
                                          tuple(x for x in secrets if x))

    def _run_sync(self, argv: tuple[str, ...], cmd: list[str], root: Path, limit: float,
                  extra_env: Mapping[str, str] | None = None, secrets: tuple[str, ...] = ()) -> RunResult:
        start = time.perf_counter()
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                proc = subprocess.Popen(cmd, cwd=str(root), env=self._env(root, extra_env), stdin=subprocess.DEVNULL,
                                        stdout=out, stderr=err, start_new_session=True)
            except OSError as exc:
                return RunResult(argv, None, refused=f"lancement impossible : {exc}")
            timed_out = False
            try:
                proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            duration = int((time.perf_counter() - start) * 1000)
            texts = []
            cut = False
            for f in (out, err):
                f.seek(0)
                raw = f.read(self.max_output * 4 + 1)
                text = raw[: self.max_output * 4].decode("utf-8", errors="replace")
                for secret in secrets:  # avant de couper : un secret à cheval sur la coupure reste reconnu
                    text = text.replace(secret, "***")
                text, clipped = _clip(text, self.max_output)
                texts.append(text)
                cut |= clipped or len(raw) > self.max_output * 4
        return RunResult(argv, proc.returncode, texts[0], texts[1], duration, timed_out, cut)

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
