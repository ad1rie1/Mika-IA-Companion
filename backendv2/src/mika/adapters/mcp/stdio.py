"""Un serveur MCP lancé sur cette machine (ADR 0064 §10) : un processus longue durée sous bubblewrap, qui parle
JSON-RPC une ligne par message sur son entrée et sa sortie.

La cage est celle de l'atelier (``adapters/cage.py``) : le système en lecture, un dossier à lui
(``<données>/mcp/<nom>/``, son HOME et son dossier de travail), les dossiers partagés que l'opérateur a déclarés
(en lecture, sauf « :rw »), réseau aucun ou à part (pasta : Internet, jamais cette machine ni le réseau local), un
environnement reconstruit (rien n'est hérité du serveur ; les variables déclarées, les secrètes déchiffrées),
des limites. **Sans bubblewrap, rien ne se lance** ; sans pasta, un serveur qui veut le réseau non plus.

Sa sortie d'erreur est gardée, bornée, secrets masqués : l'opérateur la lit quand le serveur tombe. Une ligne trop
longue, un arrêt, un délai : le processus est tué (son groupe entier) et ce qui attendait reçoit l'erreur — la
session suivante le relance.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import resource
import shutil
import signal
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mika.adapters import cage
from mika.adapters.mcp.client import McpError
from mika.adapters.mcp.config import McpServer, shared_path

#: une ligne au-delà : le serveur est arrêté (une réponse n'a pas à peser plus)
MAX_LINE = 4 * 1024 * 1024
#: ce qu'on garde de sa sortie d'erreur
ERR_LINES, ERR_CHARS = 40, 300
UNSUPPORTED = -32601
NO_BWRAP = "bubblewrap est absent : un serveur sur cette machine ne se lance pas sans sa cage"
NO_NETWORK = ("pas de réseau isolé ici (il faut « pasta », du paquet passt, et « ip ») : un serveur qui veut le "
              "réseau ne part pas sur celui de la machine")


@dataclass(frozen=True, slots=True)
class Limits:
    """Ce qu'un serveur local peut prendre. Il vit longtemps : son temps de calcul est large (un serveur qui l'a
    épuisé est tué, et relancé à la session suivante)."""

    memory_bytes: int = 2 * 1024 ** 3
    cpu_seconds: int = 4 * 3600
    file_bytes: int = 256 * 1024 ** 2
    processes: int = 256
    files: int = 1024


@dataclass(frozen=True, slots=True)
class Sandbox:
    """Les programmes qui font la cage (``None`` : absent)."""

    bwrap: str | None
    pasta: str | None
    ip: str | None
    sh: str | None
    prlimit: str | None

    @staticmethod
    def find() -> Sandbox:
        return Sandbox(shutil.which("bwrap"), shutil.which("pasta"), shutil.which("ip"), shutil.which("sh"),
                       shutil.which("prlimit"))


class Launcher:
    """Construit la commande d'un serveur local : sa cage, son environnement, son dossier."""

    def __init__(self, root: Path, sandbox: Sandbox | None = None, limits: Limits | None = None) -> None:
        self.root = root
        self.sandbox = sandbox or Sandbox.find()
        self.limits = limits or Limits()

    def home(self, name: str) -> Path:
        return self.root / name

    def command(self, name: str, spec: McpServer) -> tuple[list[str], dict[str, str], Path]:
        box = self.sandbox
        if not box.bwrap:
            raise McpError(NO_BWRAP)
        network = "isolated" if spec.network == "isole" else ""
        if network and not (box.pasta and box.ip and box.sh):
            raise McpError(NO_NETWORK)
        home = self.home(name)
        home.mkdir(parents=True, exist_ok=True)
        exe = self._visible(spec.command.strip(), home)
        if exe is None:
            raise McpError(f"« {spec.command.strip()[:80]} » introuvable dans son dossier ({home}) ou dans le système")
        args = [*cage.head(box.bwrap, network), *cage.system(network)]
        if network:
            args += ["--ro-bind", str(cage.resolver(self.root / ".reseau")), "/etc/resolv.conf"]
        for line in spec.shared:
            raw, writable = shared_path(line)
            path = Path(raw)
            if not path.is_absolute() or not path.exists():
                raise McpError(f"dossier partagé introuvable : {raw[:120]}")
            real = str(path.resolve())  # le vrai chemin : un lien ne mène pas ailleurs que ce qui a été déclaré
            args += ["--bind" if writable else "--ro-bind", real, real]
        args += ["--bind", str(home), str(home), "--chdir", str(home), "--"]
        if box.prlimit and Path(box.prlimit).resolve().is_relative_to("/usr"):
            n = self.limits.processes
            args += [box.prlimit, f"--nproc={n}:{n}", "--"]
        inner = [*args, exe, *spec.args]
        argv = cage.isolated(inner, pasta=str(box.pasta), ip=str(box.ip), sh=str(box.sh),
                             addresses=cage.host_addresses(str(box.ip))) if network else inner
        return argv, self.env(home, spec), home

    def env(self, home: Path, spec: McpServer) -> dict[str, str]:
        """Construit, jamais hérité : rien de l'environnement du serveur n'entre."""
        out = {"PATH": _path(home), "HOME": str(home), "TMPDIR": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
               "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "NPM_CONFIG_UPDATE_NOTIFIER": "false",
               "NO_UPDATE_NOTIFIER": "1"}
        for line in spec.env:
            k, _, v = line.partition("=")
            if k.strip():
                out[k.strip()] = v
        out.update(spec.secret_vars())
        return out

    @staticmethod
    def _visible(program: str, home: Path) -> str | None:
        """Le programme, s'il est dans son dossier ou dans le système (ce que la cage montre) ; sinon rien."""
        if not program:
            return None
        found = str(home / program) if "/" in program and not program.startswith("/") else (
            program if program.startswith("/") else shutil.which(program, path=_path(home)))
        if not found or not Path(found).exists():
            return None
        real = Path(found).resolve()
        visible = [home.resolve(), *(Path(d).resolve() for d in cage.SYSTEM_DIRS if Path(d).exists())]
        if not any(real.is_relative_to(v) for v in visible) or not os.access(real, os.X_OK):
            return None
        return found

    def limiter(self) -> Callable[[], None]:
        lim = self.limits

        def apply() -> None:  # dans le processus fils, avant bubblewrap (et pasta)
            resource.setrlimit(resource.RLIMIT_AS, (lim.memory_bytes, lim.memory_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (lim.cpu_seconds, lim.cpu_seconds))
            resource.setrlimit(resource.RLIMIT_FSIZE, (lim.file_bytes, lim.file_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (lim.files, lim.files))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        return apply


def _path(home: Path) -> str:
    return ":".join([str(home / "node_modules" / ".bin"), str(home / ".venv" / "bin"), str(home / ".local" / "bin"),
                     "/usr/local/bin", "/usr/bin", "/bin"])


class StdioTransport:
    """Le transport d'un serveur local : lancé au premier message, arrêté à la fermeture (son groupe entier)."""

    def __init__(self, argv: list[str], env: Mapping[str, str], cwd: Path, *,
                 preexec: Callable[[], None] | None = None, secrets: tuple[str, ...] = (),
                 max_line: int = MAX_LINE) -> None:
        self.argv, self.env, self.cwd = list(argv), dict(env), cwd
        self.preexec = preexec
        self.max_line = max_line
        self.protocol_version: str | None = None
        self.tools_changed = False
        self._secrets = tuple(s for s in secrets if len(s) >= 4)
        self._proc: asyncio.subprocess.Process | None = None
        self._waiting: dict[Any, asyncio.Future[dict[str, Any]]] = {}
        self._tasks: list[asyncio.Task[Any]] = []
        self._err: deque[str] = deque(maxlen=ERR_LINES)
        self._dead: str = ""
        self._lock = asyncio.Lock()

    def stderr_tail(self, n: int = 5) -> tuple[str, ...]:
        return tuple(list(self._err)[-n:])

    async def _ensure(self) -> asyncio.subprocess.Process:
        async with self._lock:
            if self._dead:
                raise McpError(self._dead)
            if self._proc is None:
                try:
                    self._proc = await asyncio.create_subprocess_exec(
                        *self.argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE, env=self.env, cwd=str(self.cwd), start_new_session=True,
                        preexec_fn=self.preexec, limit=self.max_line)
                except OSError as exc:
                    raise McpError(f"il ne se lance pas : {exc.strerror or exc}") from None
                self._tasks = [asyncio.create_task(self._read(), name="mcp-stdout"),
                               asyncio.create_task(self._read_err(), name="mcp-stderr")]
            return self._proc

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        proc = await self._ensure()
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        mid = message.get("id")
        self._waiting[mid] = fut
        try:
            await self._write(proc, message)
            return await fut
        finally:
            self._waiting.pop(mid, None)

    async def notify(self, message: Mapping[str, Any]) -> None:
        await self._write(await self._ensure(), message)

    async def _write(self, proc: asyncio.subprocess.Process, message: Mapping[str, Any]) -> None:
        if proc.stdin is None:
            raise McpError("le serveur n'a pas d'entrée")
        try:
            proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            raise McpError(self._stopped()) from None

    async def _read(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        out = self._proc.stdout
        while True:
            try:
                raw = await out.readline()
            except (ValueError, asyncio.LimitOverrunError):
                self._die("une ligne trop longue : le serveur est arrêté")
                return
            if not raw:
                if len(self._tasks) > 1:  # ce qu'il a dit en tombant : sa sortie d'erreur, lue jusqu'au bout
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(asyncio.shield(self._tasks[1]), 0.5)
                self._die(self._stopped())
                return
            try:
                msg = json.loads(raw)
            except ValueError:
                continue  # un serveur qui écrit autre chose sur sa sortie : ignoré (les journaux vont sur stderr)
            for item in msg if isinstance(msg, list) else [msg]:
                if isinstance(item, dict):
                    self._dispatch(item)

    def _dispatch(self, item: dict[str, Any]) -> None:
        if ("result" in item or "error" in item) and "method" not in item:
            fut = self._waiting.get(item.get("id"))
            if fut is not None and not fut.done():
                fut.set_result(item)
            return
        method = item.get("method")
        if method == "notifications/tools/list_changed":
            self.tools_changed = True
        elif isinstance(method, str) and "id" in item and self._proc is not None:
            # une requête du serveur (« écris pour moi », « demande à la personne ») : refusée
            reply = {"jsonrpc": "2.0", "id": item["id"], "error": {"code": UNSUPPORTED, "message": "non pris en charge"}}
            task = asyncio.get_running_loop().create_task(self._write(self._proc, reply))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def _read_err(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        err = self._proc.stderr
        while True:
            try:
                raw = await err.readline()
            except (ValueError, asyncio.LimitOverrunError):
                continue
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip()
            for secret in self._secrets:
                line = line.replace(secret, "•••")
            if line:
                self._err.append(line[:ERR_CHARS])

    def _stopped(self) -> str:
        tail = " — ".join(self.stderr_tail(2))
        code = self._proc.returncode if self._proc is not None else None
        return "le serveur s'est arrêté" + (f" (code {code})" if code is not None else "") + (f" : {tail}" if tail else "")

    def _die(self, why: str) -> None:
        self._dead = why
        for fut in self._waiting.values():
            if not fut.done():
                fut.set_exception(McpError(why))
        self._kill()

    def _kill(self) -> None:
        proc = self._proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)

    async def aclose(self) -> None:
        proc = self._proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), 2.0)
            except TimeoutError:
                self._kill()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), 2.0)
        for task in self._tasks:
            task.cancel()
        for fut in self._waiting.values():
            if not fut.done():
                fut.set_exception(McpError("session fermée"))
        self._dead = self._dead or "session fermée"
