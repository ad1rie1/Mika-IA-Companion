"""L'atelier réel : un dossier par but, des programmes isolés par bubblewrap.

- **Confinement des chemins**, un seul contrôle appliqué partout : résoudre,
  puis vérifier l'appartenance (``..`` comme le lien symbolique sortant).
  ``.git`` et la maison de l'atelier ne s'écrivent jamais depuis les outils.
- **Exécution** : bubblewrap (espaces de noms, ``/usr`` en lecture seule, un
  ``/tmp`` éphémère, le dossier seul inscriptible, un environnement
  reconstruit — rien de celui du serveur, donc aucune de ses clés), réseau
  coupé sauf demande approuvée. Délai tenu en **tuant le groupe** de
  processus ; sorties bornées. Sans bubblewrap : refus, jamais de repli.
- **Git par but** : un commit d'amorce, puis un commit par pas qui a changé
  quelque chose (jamais de commit vide).

Les commandes tournent dans un fil (``run_in_executor``) : l'attente du
processus ne bloque pas la boucle ; en simulation, l'exécuteur est en ligne.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from mika.ports.workshop import OutsideWorkshop, RunResult

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


def _search_path(root: Path) -> str:
    return f"{root}/.venv/bin:{root}/node_modules/.bin:{SYSTEM_PATH}"


def _clip(data: bytes, limit: int) -> tuple[str, bool]:
    text = data.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return text[:half] + f"\n\n[… {len(text) - limit} caractères coupés …]\n\n" + text[-half:], True


class BwrapWorkshop:
    def __init__(self, root: Path, *, allowed: Sequence[str] = ALLOWED, timeout_s: float = 120.0,
                 max_output_chars: int = 20_000, max_file_bytes: int = 400_000, max_tree: int = 400,
                 bwrap: str | None = None, which: Callable[[str], str | None] = shutil.which) -> None:
        self.root = Path(root)
        self.allowed = frozenset(allowed)
        self.timeout_s = timeout_s
        self.max_output = max_output_chars
        self.max_file = max_file_bytes
        self.max_tree = max_tree
        self.bwrap = bwrap if bwrap is not None else which("bwrap")

    # ── le dossier ──
    def folder(self, goal: int) -> Path:
        return self.root / f"but-{int(goal)}"

    def exists(self, goal: int) -> bool:
        return self.folder(goal).is_dir()

    def _open(self, goal: int) -> Path:
        d = self.folder(goal)
        (d / HOME_DIRNAME).mkdir(parents=True, exist_ok=True)
        return d

    def path(self, goal: int, rel: str, *, write: bool = False) -> Path:
        """Résout ``rel`` dans l'atelier, ou lève ``OutsideWorkshop``."""
        base = self._open(goal).resolve()
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

    def _command(self, root: Path, argv: list[str], network: bool) -> list[str]:
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
        args += ["--bind", str(root), str(root), "--chdir", str(root)]
        return [*args, "--", *argv]

    def _env(self, root: Path) -> dict[str, str]:
        """Construit, jamais hérité : aucune variable du serveur n'entre."""
        home = root / HOME_DIRNAME
        return {"PATH": _search_path(root), "HOME": str(home), "TMPDIR": "/tmp", "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                "MIKA_ATELIER": "1"}

    async def run(self, goal: int, argv: Sequence[str], *, timeout_s: float | None = None,
                  network: bool = False, check_allowed: bool = True) -> RunResult:
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
        cmd = self._command(root, [exe, *args[1:]], network)
        limit = timeout_s or self.timeout_s
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run_sync, tuple(args), cmd, root, limit)

    def _run_sync(self, argv: tuple[str, ...], cmd: list[str], root: Path, limit: float) -> RunResult:
        start = time.perf_counter()
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                proc = subprocess.Popen(cmd, cwd=str(root), env=self._env(root), stdin=subprocess.DEVNULL,
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
                text, clipped = _clip(raw[: self.max_output * 4], self.max_output)
                texts.append(text)
                cut |= clipped or len(raw) > self.max_output * 4
        return RunResult(argv, proc.returncode, texts[0], texts[1], duration, timed_out, cut)

    # ── git ──
    async def _git(self, goal: int, *args: str) -> RunResult:
        return await self.run(goal, ["git", *_GIT, *args], timeout_s=30, check_allowed=False)

    async def _init(self, goal: int) -> bool:
        root = self._open(goal)
        if (root / ".git").exists():
            return True
        r = await self._git(goal, "init", "-q")
        if not r.ok:
            return False
        (root / ".gitignore").write_text(f"{HOME_DIRNAME}/\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n",
                                         encoding="utf-8")
        await self._git(goal, "add", "-A")
        await self._git(goal, "commit", "-q", "-m", "atelier ouvert")
        return True

    async def commit(self, goal: int, message: str) -> str:
        if not self.exists(goal) or not await self._init(goal):
            return ""
        state = await self._git(goal, "status", "--porcelain")
        if not state.ok or not state.stdout.strip():
            return ""
        await self._git(goal, "add", "-A")
        title = re.sub(r"\s+", " ", (message or "travail")).strip()[:72] or "travail"
        done = await self._git(goal, "commit", "-q", "-m", title)
        if not done.ok:
            return ""
        sha = await self._git(goal, "rev-parse", "--short", "HEAD")
        return sha.stdout.strip() if sha.ok else ""

    async def diff(self, goal: int) -> str:
        if not (self.folder(goal) / ".git").exists():
            return ""
        r = await self._git(goal, "diff", "--stat", "-p")
        return r.stdout if r.ok else ""

    async def log(self, goal: int, n: int = 10, *, offset: int = 0) -> str:
        if not (self.folder(goal) / ".git").exists():
            return ""
        r = await self._git(goal, "log", f"-{max(1, n)}", f"--skip={max(0, offset)}", "--format=%h %s")
        return r.stdout if r.ok else ""


__all__ = ["BwrapWorkshop"]
