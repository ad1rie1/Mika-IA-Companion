"""L'hôte de la Forge : les apps qu'elle écrit, exécutées hors de son processus.

**Le bac à sable, c'est le système** (bubblewrap) : chaque app tourne dans
son propre processus, sans réseau, sans les bases ni les clés de Mika (rien
n'est monté hormis ``/usr`` en lecture, son dossier en lecture, un ``/tmp``
éphémère), dans un environnement reconstruit, mémoire, CPU, fichiers et
descripteurs bornés. Un appel qui dépasse son délai **tue** le processus (le
bac à sable v1 ne pouvait pas interrompre un appel C : une expression
régulière pathologique tenait un fil pendant des secondes). Sans
bubblewrap, rien ne tourne.

La relecture à l'écriture (syntaxe, imports inutiles dans un bac à sable,
fonctions attendues, taille) est une politesse, pas la défense.

Le processus d'une app reste chaud entre deux appels ; une nouvelle version
le remplace ; il est relancé s'il meurt.

**Seules les fonctions déclarées s'appellent** : les fixes (``tick``,
``context``, ``view``, ``action``, ``on_event``) quand elles existent, et
celles que le manifeste déclare (``view_<vue>``, ``action_<vue>_<action>``,
``tool_<nom>``). Une vue rendue pour la console est gardée un instant
(``cache_s``) ; tout autre appel à l'app l'oublie.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import resource
import select
import shutil
import signal
import socket
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from mika.adapters.forge.manifest import HANDLERS, coherence, lint, read_manifest, signatures
from mika.ports.forge import AppInfo, AppTool, CallResult, ForgeRefused, config_form, ui_dump, view_specs

__all__ = ["ForgeHost", "Limits", "lint", "read_manifest", "real_http_get"]

WORKER = Path(__file__).with_name("worker.py")
NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
MAX_LINE = 1_000_000
MAX_RESULT = 64_000
MAX_LOGS = 500
KV_MAX_KEYS = 1000
KV_MAX_VALUE = 16_000
HTTP_MAX = 1_000_000
#: les vues rendues gardées un instant (même app, version, fonction, paramètres, réglages)
CACHE_MAX = 64
_SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")


@dataclass(frozen=True, slots=True)
class Limits:
    memory_bytes: int = 512 * 1024 * 1024
    cpu_seconds: int = 120  # filet : la durée de vie d'un processus chaud
    file_bytes: int = 10 * 1024 * 1024
    files: int = 64
    load_timeout_s: float = 5.0


def surface(manifest: Mapping[str, Any], functions: Mapping[str, int] | set[str], title: str
            ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """(vues déclarées dont les fonctions existent, outils, fonctions appelables).
    Une ancienne ``view(api)`` sans vues déclarées devient la vue « principale »."""
    views = []
    for v in manifest.get("views", []):
        if v["function"] not in functions:
            continue
        views.append({**v, "actions": [a for a in v["actions"] if a["function"] in functions]})
    if not views and "view" in functions:
        views = [{"key": "principale", "label": title or "Vue principale", "description": "", "order": 100,
                  "params": [], "actions": [], "function": "view"}]
    tools = [t["name"] for t in manifest.get("tools", []) if f"tool_{t['name']}" in functions]
    callable_ = {h for h in HANDLERS if h in functions} | {v["function"] for v in views} \
        | {a["function"] for v in views for a in v["actions"]} | {f"tool_{t}" for t in tools}
    return views, tools, sorted(callable_)


@dataclass(slots=True)
class _Worker:
    proc: subprocess.Popen[bytes]
    version: int
    buffer: bytes = b""


@dataclass(slots=True)
class _Call:
    logs: list[str] = field(default_factory=list)
    signals: list[tuple[str, float, str]] = field(default_factory=list)
    emits: list[tuple[str, str]] = field(default_factory=list)


def _is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast \
                or ip.is_unspecified:
            return False
    return bool(infos)


def real_http_get(url: str) -> str:
    with httpx.Client(follow_redirects=False, timeout=10.0,
                      headers={"User-Agent": "Mika-Forge/2"}) as client, client.stream("GET", url) as resp:
        chunks, size = [], 0
        for chunk in resp.iter_bytes():
            size += len(chunk)
            if size > HTTP_MAX:
                break
            chunks.append(chunk)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return b"".join(chunks).decode("utf-8", "replace")


class ForgeHost:
    def __init__(self, root: Path, *, limits: Limits = Limits(), bwrap: str | None = None,
                 http_get: Callable[[str], str] = real_http_get, public: Callable[[str], bool] = _is_public,
                 config: Callable[[str], Mapping[str, Any]] | None = None,
                 which: Callable[[str], str | None] = shutil.which) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits
        self.bwrap = bwrap if bwrap is not None else which("bwrap")
        self.python = which("python3") or "/usr/bin/python3"
        self._http_get = http_get
        self._public = public
        self._config = config
        self._workers: dict[str, _Worker] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._db = sqlite3.connect(str(self.root / "forge.db"), check_same_thread=False)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS kv(app TEXT, key TEXT, value TEXT, PRIMARY KEY(app, key));"
            "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, app TEXT, at REAL, line TEXT);")
        self._dblock = threading.Lock()
        #: ``info`` relu seulement quand ses fichiers changent (la console le demande à chaque page)
        self._infos: dict[str, tuple[tuple[Any, ...], AppInfo | None]] = {}
        #: les vues rendues : clé → (instant, résultat)
        self._cache: dict[tuple[Any, ...], tuple[float, CallResult]] = {}
        self._cachelock = threading.Lock()

    # ── les apps ──
    def _dir(self, app: str) -> Path:
        if not NAME.match(app):
            raise ForgeRefused("un nom d'app : des minuscules, chiffres et _, commençant par une lettre (2 à 31)")
        return self.root / app

    def _version(self, app: str) -> int:
        try:
            return int(json.loads((self._dir(app) / "version.json").read_text())["version"])
        except (OSError, ValueError, KeyError):
            return 0

    def apps(self) -> list[AppInfo]:
        out = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and NAME.match(d.name) and (d / "main.py").exists():
                info = self.info(d.name)
                if info is not None:
                    out.append(info)
        return out

    def _stamp(self, d: Path) -> tuple[Any, ...]:
        out: list[Any] = []
        for name in ("manifest.yaml", "main.py", "version.json"):
            try:
                st = (d / name).stat()
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def info(self, app: str) -> AppInfo | None:
        try:
            d = self._dir(app)
        except ForgeRefused:
            return None
        stamp = self._stamp(d)
        cached = self._infos.get(app)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        info = self._read_info(app, d) if stamp[1] is not None else None
        self._infos[app] = (stamp, info)
        return info

    def _read_info(self, app: str, d: Path) -> AppInfo | None:
        try:
            text = (d / "manifest.yaml").read_text(encoding="utf-8") if (d / "manifest.yaml").exists() else ""
            code = (d / "main.py").read_text(encoding="utf-8")
        except OSError:
            return None
        manifest, problems = read_manifest(text)
        _, functions = signatures(code)
        title = manifest.get("title") or app
        views, tools, callable_ = surface(manifest, functions, title)
        config = manifest.get("config_fields", [])
        return AppInfo(
            name=app, title=title, description=manifest.get("description", ""),
            version=self._version(app), schedule=manifest.get("schedule", "manual"),
            context=bool(manifest.get("context")) and "context" in functions,
            tools=tuple(AppTool(t["name"], t["description"]) for t in manifest.get("tools", [])
                        if t["name"] in tools),
            handlers=tuple(sorted(functions)), error="; ".join(problems),
            events=tuple(manifest.get("events", [])) if "on_event" in functions else (),
            config=tuple(manifest.get("config", {}).items()),
            views=view_specs(views), config_fields=config_form(config),
            ui=ui_dump(views, config, tools, callable_), callable=tuple(callable_))

    def source(self, app: str) -> tuple[str, str] | None:
        d = self._dir(app)
        if not (d / "main.py").exists():
            return None
        manifest = (d / "manifest.yaml").read_text(encoding="utf-8") if (d / "manifest.yaml").exists() else ""
        return manifest, (d / "main.py").read_text(encoding="utf-8")

    async def write(self, app: str, manifest: str, code: str) -> tuple[int, list[str]]:
        d = self._dir(app)
        data, problems = read_manifest(manifest)
        code_problems, functions = signatures(code)
        problems += code_problems
        if not code_problems:
            problems += coherence(data, functions)
        if problems:
            raise ForgeRefused(" ; ".join(problems))
        version = self._version(app) + 1
        if (d / "main.py").exists():
            archive = d / "_versions" / str(version - 1)
            archive.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.yaml", "main.py"):
                if (d / name).exists():
                    shutil.copy2(d / name, archive / name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.yaml").write_text(manifest, encoding="utf-8")
        (d / "main.py").write_text(code, encoding="utf-8")
        (d / "version.json").write_text(json.dumps({"version": version}))
        self._stop(app)  # la version suivante repart d'un processus neuf
        self._forget(app)
        return version, []

    async def rollback(self, app: str) -> int:
        d = self._dir(app)
        versions = sorted((int(p.name) for p in (d / "_versions").glob("*") if p.name.isdigit()), reverse=True)
        if not versions:
            raise ForgeRefused("aucune version précédente")
        previous = d / "_versions" / str(versions[0])
        manifest = (previous / "manifest.yaml").read_text(encoding="utf-8")
        code = (previous / "main.py").read_text(encoding="utf-8")
        version, _ = await self.write(app, manifest, code)
        return version

    async def erase(self, app: str) -> str:
        d = self._dir(app)
        if not d.exists():
            raise ForgeRefused("cette app n'existe pas")
        self._stop(app)
        trash = self.root / "_corbeille"
        trash.mkdir(exist_ok=True)
        target = trash / f"{app}-{self._version(app)}-{int(time.time())}"
        shutil.move(str(d), str(target))
        self._forget(app)
        return str(target)

    async def reset_storage(self, app: str) -> int:
        self._dir(app)
        with self._dblock:
            n = self._db.execute("DELETE FROM kv WHERE app=?", (app,)).rowcount
            self._db.commit()
        self._drop_cache(app)
        return n

    async def reload(self, app: str) -> None:
        """Arrête son processus chaud (après l'appel en cours) : l'appel suivant
        repart du disque, et rien de ce qui était gardé ne resservira."""
        self._dir(app)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._reload_sync, app)

    def _reload_sync(self, app: str) -> None:
        with self._lock(app):
            self._stop(app)
        self._forget(app)

    def _forget(self, app: str) -> None:
        self._infos.pop(app, None)
        self._drop_cache(app)

    def _drop_cache(self, app: str) -> None:
        with self._cachelock:
            for key in [k for k in self._cache if k[0] == app]:
                del self._cache[key]

    def logs(self, app: str, n: int = 20) -> list[str]:
        with self._dblock:
            rows = self._db.execute("SELECT line FROM logs WHERE app=? ORDER BY id DESC LIMIT ?", (app, n)).fetchall()
        return [r[0] for r in reversed(rows)]

    # ── l'exécution ──
    async def call(self, app: str, method: str, args: dict[str, Any] | None = None, *,
                   timeout_s: float = 5.0, max_result: int = MAX_RESULT, cache_s: float = 0.0) -> CallResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._call_sync, app, method, dict(args or {}), timeout_s,
                                          max_result, cache_s)

    def _lock(self, app: str) -> threading.Lock:
        return self._locks.setdefault(app, threading.Lock())

    def _limits(self) -> None:  # dans le processus fils, avant bubblewrap
        lim = self.limits
        resource.setrlimit(resource.RLIMIT_AS, (lim.memory_bytes, lim.memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (lim.cpu_seconds, lim.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (lim.file_bytes, lim.file_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (lim.files, lim.files))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def _command(self, app: str) -> list[str]:
        assert self.bwrap
        args = [self.bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL"]
        for d in _SYSTEM_DIRS:
            p = Path(d)
            if p.is_symlink():
                args += ["--symlink", os.readlink(p), d]
            elif p.is_dir():
                args += ["--ro-bind", d, d]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--ro-bind", str(self._dir(app).resolve()), "/app",
                 "--ro-bind", str(WORKER.resolve()), "/runner/worker.py", "--chdir", "/tmp"]
        return [*args, "--", self.python, "-I", "-S", "/runner/worker.py"]

    def _start(self, app: str, version: int) -> _Worker | str:
        env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
               "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.Popen(self._command(app), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=env, start_new_session=True,
                                preexec_fn=self._limits)  # noqa: PLW1509 — les limites du processus fils
        worker = _Worker(proc, version)
        hello = self._read(worker, time.monotonic() + self.limits.load_timeout_s)
        if not isinstance(hello, dict) or not hello.get("loaded"):
            self._kill(worker)
            reason = hello.get("error") if isinstance(hello, dict) else hello
            return f"l'app ne se charge pas : {reason or 'délai dépassé au chargement'}"
        return worker

    def _kill(self, w: _Worker) -> None:
        try:
            os.killpg(w.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            w.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (w.proc.stdin, w.proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def _stop(self, app: str) -> None:
        w = self._workers.pop(app, None)
        if w is not None:
            self._kill(w)

    def shutdown(self) -> None:
        for app in list(self._workers):
            self._stop(app)

    def _read(self, w: _Worker, deadline: float) -> dict[str, Any] | str | None:
        """Une ligne JSON avant l'échéance ; ``None`` au délai, un texte si le processus meurt."""
        assert w.proc.stdout is not None
        fd = w.proc.stdout.fileno()
        while b"\n" not in w.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(fd, 65536)
            if not chunk:
                return "le processus de l'app est mort (mémoire, CPU, ou sortie)"
            w.buffer += chunk
            if len(w.buffer) > MAX_LINE:
                return "réponse trop longue"
        line, w.buffer = w.buffer.split(b"\n", 1)
        try:
            msg = json.loads(line)
        except ValueError:
            return "réponse illisible"
        return msg if isinstance(msg, dict) else "réponse illisible"

    def _send(self, w: _Worker, obj: Any) -> bool:
        try:
            assert w.proc.stdin is not None
            w.proc.stdin.write((json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode())
            w.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def _call_sync(self, app: str, method: str, args: dict[str, Any], timeout_s: float,
                   max_result: int = MAX_RESULT, cache_s: float = 0.0) -> CallResult:
        started = time.monotonic()
        call = _Call()

        def done(ok: bool, value: Any = None, error: str = "", killed: bool = False) -> CallResult:
            return CallResult(ok, value, error[:1000], killed, int((time.monotonic() - started) * 1000),
                              tuple(call.logs[-50:]), tuple(call.signals), tuple(call.emits))

        if not self.bwrap:
            return done(False, error="bubblewrap est absent : aucune app ne tourne sans isolation")
        info = self.info(app)
        if info is None:
            return done(False, error="cette app n'existe pas")
        if info.error:
            return done(False, error=f"manifeste : {info.error}")
        if method not in info.callable:
            known = ", ".join(info.callable) or "aucune"
            return done(False, error=f"« {method[:60]} » n'est pas une fonction déclarée de cette app "
                                     f"(appelables : {known})")
        key = self._cache_key(app, info, method, args) if cache_s > 0 else None
        if key is not None:
            with self._cachelock:
                hit = self._cache.get(key)
            if hit is not None and time.monotonic() - hit[0] <= cache_s:
                return hit[1]
        if not method.startswith("view"):
            self._drop_cache(app)  # ce qu'elle fait peut changer ce qu'elle montre
        result = self._run(app, info, method, args, timeout_s, max_result, call, done)
        if key is not None and result.ok:
            with self._cachelock:
                if len(self._cache) >= CACHE_MAX:
                    del self._cache[min(self._cache, key=lambda k: self._cache[k][0])]
                self._cache[key] = (time.monotonic(), result)
        return result

    def _cache_key(self, app: str, info: AppInfo, method: str, args: Mapping[str, Any]) -> tuple[Any, ...] | None:
        try:
            config = json.dumps(dict(self._config(app) if self._config else {}), sort_keys=True, default=str)
            return (app, info.version, method, json.dumps(args, sort_keys=True, default=str), config)
        except (TypeError, ValueError):
            return None

    def _run(self, app: str, info: AppInfo, method: str, args: dict[str, Any], timeout_s: float, max_result: int,
             call: _Call, done: Callable[..., CallResult]) -> CallResult:
        with self._lock(app):
            w = self._workers.get(app)
            if w is None or w.version != info.version or w.proc.poll() is not None:
                if w is not None:
                    self._stop(app)
                got = self._start(app, info.version)
                if isinstance(got, str):
                    self._log(app, got)
                    return done(False, error=got, killed=True)
                w = self._workers[app] = got
            deadline = time.monotonic() + timeout_s
            if not self._send(w, {"call": method, "args": args}):
                self._stop(app)
                return done(False, error="le processus de l'app ne répond plus", killed=True)
            while True:
                msg = self._read(w, deadline)
                if msg is None or isinstance(msg, str):
                    self._stop(app)
                    reason = msg or f"délai de {timeout_s:g} s dépassé : tuée"
                    self._log(app, f"{method} : {reason}")
                    return done(False, error=reason, killed=True)
                if "host" in msg:
                    reply = self._serve(app, info, str(msg.get("host")), msg.get("params") or {}, call)
                    if not self._send(w, reply):
                        self._stop(app)
                        return done(False, error="le processus de l'app ne répond plus", killed=True)
                    continue
                if "error" in msg:
                    self._log(app, f"{method} : {msg['error']}")
                    return done(False, error=str(msg["error"]))
                value = msg.get("result")
                size = len(json.dumps(value, ensure_ascii=False, default=str))
                if size > max_result:
                    self._log(app, f"{method} : résultat trop gros ({size // 1000} Ko)")
                    return done(False, error=f"résultat trop gros ({size // 1000} Ko ; au plus "
                                             f"{max_result // 1000} Ko)")
                return done(True, value)

    # ── les services de l'hôte ──
    def _log(self, app: str, line: str) -> None:
        with self._dblock:
            self._db.execute("INSERT INTO logs(app, at, line) VALUES(?,?,?)", (app, time.time(), line[:1000]))
            self._db.execute("DELETE FROM logs WHERE app=? AND id NOT IN (SELECT id FROM logs WHERE app=? "
                             "ORDER BY id DESC LIMIT ?)", (app, app, MAX_LOGS))
            self._db.commit()

    def _serve(self, app: str, info: AppInfo, name: str, p: Mapping[str, Any], call: _Call) -> dict[str, Any]:
        try:
            return {"result": self._service(app, name, p, call)}
        except (ValueError, RuntimeError, OSError, httpx.HTTPError) as exc:
            return {"error": str(exc)[:300]}

    def _service(self, app: str, name: str, p: Mapping[str, Any], call: _Call) -> Any:
        if name == "log":
            line = str(p.get("message") or "")[:1000]
            call.logs.append(line)
            self._log(app, line)
            return None
        if name == "kv_get":
            with self._dblock:
                row = self._db.execute("SELECT value FROM kv WHERE app=? AND key=?", (app, str(p.get("key")))).fetchone()
            return json.loads(row[0]) if row else p.get("default")
        if name == "kv_set":
            key, raw = str(p.get("key"))[:200], json.dumps(p.get("value"), ensure_ascii=False)
            if len(raw) > KV_MAX_VALUE:
                raise ValueError(f"valeur trop grosse (> {KV_MAX_VALUE // 1000} Ko)")
            with self._dblock:
                count = self._db.execute("SELECT COUNT(*) FROM kv WHERE app=?", (app,)).fetchone()[0]
                exists = self._db.execute("SELECT 1 FROM kv WHERE app=? AND key=?", (app, key)).fetchone()
                if count >= KV_MAX_KEYS and not exists:
                    raise ValueError(f"trop de clés (> {KV_MAX_KEYS})")
                self._db.execute("INSERT INTO kv VALUES(?,?,?) ON CONFLICT(app, key) DO UPDATE SET value=excluded.value",
                                 (app, key, raw))
                self._db.commit()
            return True
        if name == "kv_delete":
            with self._dblock:
                self._db.execute("DELETE FROM kv WHERE app=? AND key=?", (app, str(p.get("key"))))
                self._db.commit()
            return True
        if name == "kv_keys":
            with self._dblock:
                rows = self._db.execute("SELECT key FROM kv WHERE app=? AND key LIKE ? ORDER BY key LIMIT 1000",
                                        (app, f"{p.get('prefix') or ''}%")).fetchall()
            return [r[0] for r in rows]
        if name == "config":
            info = self.info(app)
            defaults = {**dict(info.config), **{f.path: f.default for f in info.config_fields
                                                if f.default is not None}} if info is not None else {}
            values = {**defaults, **dict((self._config(app) if self._config else {}) or {})}
            return values.get(str(p.get("key")), p.get("default"))
        if name == "emit":
            if len(call.emits) >= 5:
                raise ValueError("trop d'émissions pour un appel (5)")
            data = json.dumps(p.get("data"), ensure_ascii=False, default=str)
            if len(data) > 4000:
                raise ValueError("données trop grosses (4 Ko)")
            call.emits.append((re.sub(r"[^a-z0-9_]", "_", str(p.get("type") or "event").lower())[:40], data))
            return True
        if name == "signal":
            if len(call.signals) >= 3:
                raise ValueError("trop de signaux pour un appel (3)")
            call.signals.append((str(p.get("summary") or "")[:300], max(0.0, min(1.0, float(p.get("pertinence") or 0))),
                                 str(p.get("emotion") or "")[:20]))
            return True
        if name == "http_get":
            return self._http(app, str(p.get("url") or ""))
        raise ValueError(f"service inconnu : {name}")

    def _http(self, app: str, url: str) -> str:
        parts = urlsplit(url)
        manifest, _ = read_manifest(self.source(app)[0] if self.source(app) else "")
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not host:
            raise ValueError("une adresse http(s) complète")
        if host not in manifest.get("allowed_domains", []):
            raise ValueError(f"« {host} » n'est pas dans allowed_domains")
        if not self._public(host):
            raise ValueError(f"« {host} » est une adresse privée : refusée")
        return self._http_get(url)[:HTTP_MAX]
