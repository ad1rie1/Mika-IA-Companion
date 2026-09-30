"""Fournisseur Claude Code : la vraie CLI ``claude -p``, avec son propre login.

Mika ne lit, ne stocke ni ne transmet aucun jeton : la CLI s'authentifie comme
elle le fait pour son utilisateur (mode ``abonnement``), ou reçoit une clé API
Console (mode ``cle_api``). ``CLAUDE_CODE_OAUTH_TOKEN`` ne passe jamais :
l'environnement du sous-processus est reconstruit sur liste blanche.

Une requête du runtime devient une session de la CLI, tenue le temps de la
boucle d'outils de l'épisode (même ``call_id`` d'un tour à l'autre) :

- premier tour : la CLI est lancée, isolée (aucun réglage, aucune mémoire,
  aucun connecteur claude.ai, aucun outil natif — l'atelier et la Forge
  exécutent sous bubblewrap, pas la CLI), avec le prompt système du runtime
  et deux serveurs MCP servis par le relais (``mika`` en main, ``mika_plus`` à
  la demande, que la CLI charge par sa recherche d'outils) ;
- quand la CLI appelle un outil, le relais le met en attente : la réponse est
  ``stop="tool_use"`` et c'est **le runtime** qui l'exécute ;
- tour suivant (les résultats dans la requête) : ils sont rendus à la CLI, qui
  continue ; son message ``result`` fait la réponse finale ;
- annulation (préemption, supplantation, délai) : le groupe de processus est
  arrêté (SIGINT puis SIGKILL) et la session fermée ; une session laissée sans
  suite (un rôle qui lit les appels d'outils comme sortie structurée, un
  plafond de tours) est fauchée après ``idle_s`` — plus long que l'outil le plus
  lent (un programme de l'atelier : 600 s), pour ne jamais faucher une session vivante.

La CLI rend aussi l'usage de l'abonnement (``rate_limit_event``) : au-delà de
``quota_ceiling``, les appels de fond sont refusés (``QuotaHeld``) — la
passerelle bascule alors sur le fournisseur de repli, et la conversation, elle,
passe toujours.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mika.adapters.mcp.protocol import Outcome, Tool
from mika.adapters.mcp.relay import Pending, Relay, RelaySession
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolCall, Usage

log = logging.getLogger("mika.llm.claude_code")

AUTHS = ("abonnement", "cle_api")
#: les seules variables du parent qui passent (HOME : la CLI y trouve son login)
INHERITED = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR")
#: jamais transmises, même si le processus de Mika les a
FORBIDDEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
SERVERS = {"mika": "mika", "plus": "mika_plus"}
#: le temps de regrouper des appels d'outils partis ensemble
BATCH_WINDOW_S = 0.15
READ_LIMIT = 16 * 1024 * 1024
STDERR_KEPT = 4000


class ClaudeCodeError(RuntimeError):
    """La CLI a échoué (non connectée, absente, erreur en cours de tour)."""


class QuotaHeld(ClaudeCodeError):
    """Appel de fond refusé : l'abonnement est trop entamé."""


@dataclass(frozen=True, slots=True)
class QuotaReading:
    window: str
    utilization: float
    resets_at: int = 0


@dataclass(slots=True)
class _Run:
    session: RelaySession | None
    proc: asyncio.subprocess.Process | None = None
    workdir: Path | None = None
    events: asyncio.Queue[tuple[str, Any]] = field(default_factory=asyncio.Queue)
    handed: set[str] = field(default_factory=set)
    model: str = ""
    stderr: str = ""
    reaper: asyncio.TimerHandle | None = None
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)

    def on_call(self, p: Pending) -> None:
        self.events.put_nowait(("call", p))


class ClaudeCodeBackend:
    def __init__(
        self,
        model: str = "",
        *,
        relay: Relay,
        relay_base: Any,
        name: str = "claude_code",
        auth: str = "abonnement",
        api_key: str = "",
        claude_bin: str = "",
        config_dir: str = "",
        work_dir: str | Path | None = None,
        idle_s: float = 900.0,
        quota_ceiling: float = 0.8,
        tool_timeout_s: float = 900.0,
    ) -> None:
        if auth not in AUTHS:
            raise ValueError(f"mode d'authentification inconnu : {auth!r} (attendu : {' ou '.join(AUTHS)})")
        self.name = name
        self.model = model
        self.auth = auth
        self._api_key = api_key
        self.claude_bin = claude_bin
        self.config_dir = config_dir
        self.relay = relay
        #: l'URL de base du serveur qui monte le relais (connue quand il écoute)
        self._relay_base = relay_base
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "mika-claude-code"
        self.idle_s = idle_s
        self.quota_ceiling = quota_ceiling
        self.tool_timeout_s = tool_timeout_s
        self.quota: dict[str, QuotaReading] = {}
        self._runs: dict[str, _Run] = {}

    # ── Ce que la CLI reçoit ─────────────────────────────────────────────

    def binary(self) -> str:
        found = self.claude_bin or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
        return found

    def argv(self, req: LLMRequest, workdir: Path, *, mcp: bool, deferred: bool) -> list[str]:
        args = [self.binary(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--system-prompt-file", str(workdir / "system.txt"),
                "--setting-sources", "", "--strict-mcp-config",
                "--tools", "ToolSearch" if deferred else "",
                "--permission-mode", "dontAsk", "--no-session-persistence"]
        if mcp:
            args += ["--mcp-config", str(workdir / "mcp.json"),
                     "--allowedTools", ",".join(f"mcp__{s}__*" for s in SERVERS.values())]
        if self.model:
            args += ["--model", self.model]
        return args

    def env(self, req: LLMRequest) -> dict[str, str]:
        out = {k: os.environ[k] for k in INHERITED if os.environ.get(k)}
        out.update({
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            "MCP_TOOL_TIMEOUT": str(int(self.tool_timeout_s * 1000)),
        })
        if self.config_dir:
            out["CLAUDE_CONFIG_DIR"] = self.config_dir
        if self.auth == "cle_api" and self._api_key:
            out["ANTHROPIC_API_KEY"] = self._api_key
        for key in FORBIDDEN:
            out.pop(key, None)
        return out

    @staticmethod
    def user_message(req: LLMRequest) -> dict[str, Any]:
        """Le fil en un message : l'historique, puis le dernier tour tel quel
        (il porte déjà l'état interne)."""
        turns = [m for m in req.messages if m.role in ("user", "assistant") and m.content.strip()]
        last = turns[-1] if turns and turns[-1].role == "user" else None
        history = turns[:-1] if last is not None else turns
        lines = [f"toi : {m.content.strip()}" if m.role == "assistant" else m.content.strip() for m in history]
        text = last.content if last is not None else ""
        if lines:
            text = "--- LE FIL JUSQU'ICI (tes répliques marquées « toi ») ---\n" + "\n".join(lines) + \
                   "\n--- FIN DU FIL ---\n\n" + text
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": i.mime, "data": i.data}}
            for i in (last.images if last is not None else ())]
        content.append({"type": "text", "text": text or "(silence)"})
        return {"type": "user", "message": {"role": "user", "content": content}}

    def mcp_config(self, session: RelaySession, base: str) -> dict[str, Any]:
        servers: dict[str, Any] = {}
        for part, server in SERVERS.items():
            if not session.parts[part].tools():
                continue
            conf: dict[str, Any] = {"type": "http", "url": Relay.url(base, session, part),
                                    "headers": {"Authorization": f"Bearer {session.token}"}}
            if part == "mika":
                conf["alwaysLoad"] = True
            servers[server] = conf
        return {"mcpServers": servers}

    # ── Appel ────────────────────────────────────────────────────────────

    async def complete(self, req: LLMRequest) -> LLMResponse:
        run = self._runs.get(req.call_id)
        try:
            if run is not None and self._answers(run, req):
                self._feed(run, req)
            else:
                if run is not None:
                    await self._stop(req.call_id)
                run = await self._start(req)
            return await self._next(req.call_id, run)
        except BaseException:
            await self._stop(req.call_id)
            raise

    def _answers(self, run: _Run, req: LLMRequest) -> bool:
        results = _trailing_results(req.messages)
        return bool(run.handed) and bool(results) and {m.tool_call_id for m in results} >= run.handed

    def _feed(self, run: _Run, req: LLMRequest) -> None:
        if run.reaper is not None:
            run.reaper.cancel()
            run.reaper = None
        assert run.session is not None
        for m in _trailing_results(req.messages):
            if m.tool_call_id in run.handed:
                run.session.resolve(m.tool_call_id or "", Outcome(m.content, bool(m.is_error)))
        run.handed.clear()

    async def _start(self, req: LLMRequest) -> _Run:
        self._hold_for_quota(req)
        binary = self.binary()
        if not Path(binary).is_file() and shutil.which(binary) is None:
            raise ClaudeCodeError(f"CLI Claude Code introuvable : {binary}")
        core = [_tool(t) for t in req.tools if not t.deferred]
        extra = [_tool(t) for t in req.tools if t.deferred]
        run = _Run(session=None)
        base = self._relay_base() if callable(self._relay_base) else self._relay_base
        if (core or extra) and not base:
            raise ClaudeCodeError("le relais MCP n'est pas joignable (serveur pas encore à l'écoute)")
        if core or extra:
            run.session = self.relay.open(core, extra, run.on_call)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        run.workdir = Path(tempfile.mkdtemp(prefix="appel-", dir=self.work_dir))
        _write_private(run.workdir / "system.txt", "\n\n".join(p for p in (req.system_stable, req.system_volatile)
                                                                  if p.strip()))
        if run.session is not None:
            _write_private(run.workdir / "mcp.json", json.dumps(self.mcp_config(run.session, str(base))))
        (run.workdir / "cwd").mkdir()
        self._runs[req.call_id] = run
        run.proc = await asyncio.create_subprocess_exec(
            *self.argv(req, run.workdir, mcp=run.session is not None, deferred=bool(extra)),
            cwd=run.workdir / "cwd", env=self.env(req), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
            limit=READ_LIMIT)
        assert run.proc.stdin is not None
        run.proc.stdin.write((json.dumps(self.user_message(req), ensure_ascii=False) + "\n").encode())
        await run.proc.stdin.drain()
        run.proc.stdin.close()
        run.tasks = [asyncio.create_task(self._read(run)), asyncio.create_task(self._drain_stderr(run))]
        return run

    async def _next(self, call_id: str, run: _Run) -> LLMResponse:
        texts: list[str] = []
        while True:
            kind, value = await run.events.get()
            if kind == "text":
                texts.append(value)
            elif kind == "call":
                batch = [value]
                await asyncio.sleep(BATCH_WINDOW_S)
                while not run.events.empty():
                    k, v = run.events.get_nowait()
                    if k == "call":
                        batch.append(v)
                    elif k == "text":
                        texts.append(v)
                    else:  # la CLI s'est arrêtée pendant qu'on regroupait : c'est l'issue
                        return self._ended(call_id, run, k, v)
                run.handed.update(p.id for p in batch)
                self._arm_reaper(call_id, run)
                return LLMResponse("".join(texts), tuple(ToolCall(p.id, p.name, p.args) for p in batch),
                                   stop="tool_use", model=run.model or self.model)
            else:
                return self._ended(call_id, run, kind, value)

    def _ended(self, call_id: str, run: _Run, kind: str, value: Any) -> LLMResponse:
        self._schedule_stop(call_id)
        if kind == "exit":
            raise ClaudeCodeError(f"la CLI s'est arrêtée sans réponse (code {value}) : {run.stderr[-300:]}".strip())
        d: Mapping[str, Any] = value
        if d.get("is_error") or d.get("subtype") != "success":
            detail = d.get("result") or ", ".join(map(str, d.get("errors") or ())) or d.get("subtype")
            raise ClaudeCodeError(f"la CLI a échoué : {detail}")
        stop = {"max_tokens": "max_tokens", "refusal": "refusal"}.get(str(d.get("stop_reason") or ""), "end")
        models = list((d.get("modelUsage") or {}).keys())
        model = run.model or (models[0] if models else self.model)
        return LLMResponse(str(d.get("result") or ""), stop=stop, usage=_usage(d.get("usage")), model=model)

    # ── Lecture de la CLI ────────────────────────────────────────────────

    async def _read(self, run: _Run) -> None:
        assert run.proc is not None and run.proc.stdout is not None
        result_seen = False
        while True:
            line = await run.proc.stdout.readline()
            if not line:
                break
            try:
                d = json.loads(line)
            except ValueError:
                continue
            kind = d.get("type")
            if kind == "assistant":
                message = d.get("message") or {}
                run.model = message.get("model") or run.model
                for block in message.get("content") or ():
                    if block.get("type") == "text" and block.get("text"):
                        run.events.put_nowait(("text", block["text"]))
            elif kind == "rate_limit_event":
                self._note_quota(d.get("rate_limit_info") or {})
            elif kind == "result":
                result_seen = True
                run.events.put_nowait(("result", d))
        code = await run.proc.wait()
        if not result_seen:
            run.events.put_nowait(("exit", code))

    async def _drain_stderr(self, run: _Run) -> None:
        assert run.proc is not None and run.proc.stderr is not None
        while chunk := await run.proc.stderr.read(4096):
            run.stderr = (run.stderr + chunk.decode(errors="replace"))[-STDERR_KEPT:]

    # ── Quota de l'abonnement ────────────────────────────────────────────

    def _note_quota(self, info: Mapping[str, Any]) -> None:
        for window, w in (info.get("unifiedWindows") or {}).items():
            if isinstance(w, Mapping) and isinstance(w.get("utilization"), (int, float)):
                self.quota[str(window)] = QuotaReading(str(window), float(w["utilization"]),
                                                       int(w.get("resetsAt") or 0))

    def _hold_for_quota(self, req: LLMRequest) -> None:
        if self.auth != "abonnement" or self.quota_ceiling <= 0 or req.priority == 0:
            return
        worst = max(self.quota.values(), key=lambda q: q.utilization, default=None)
        if worst is not None and worst.utilization >= self.quota_ceiling:
            raise QuotaHeld(f"abonnement entamé à {worst.utilization:.0%} ({worst.window}) : "
                            f"appel de fond laissé au repli")

    def status(self) -> dict[str, Any]:
        return {"sessions": len(self._runs),
                "quota": {k: round(q.utilization, 3) for k, q in sorted(self.quota.items())}}

    # ── Arrêt ────────────────────────────────────────────────────────────

    def _arm_reaper(self, call_id: str, run: _Run) -> None:
        if run.reaper is not None:
            run.reaper.cancel()
        run.reaper = asyncio.get_running_loop().call_later(self.idle_s, self._schedule_stop, call_id)

    def _schedule_stop(self, call_id: str) -> None:
        task = asyncio.get_running_loop().create_task(self._stop(call_id))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())

    async def _stop(self, call_id: str) -> None:
        run = self._runs.pop(call_id, None)
        if run is None:
            return
        if run.reaper is not None:
            run.reaper.cancel()
        if run.session is not None:
            self.relay.close(run.session)
        proc = run.proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGINT)
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), 3.0)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        for task in run.tasks:
            task.cancel()
        if run.workdir is not None:
            shutil.rmtree(run.workdir, ignore_errors=True)

    async def aclose(self) -> None:
        for call_id in list(self._runs):
            await self._stop(call_id)


def _tool(t: Any) -> Tool:
    return Tool(t.name, t.description, t.schema)


def _trailing_results(messages: Sequence[Message]) -> list[Message]:
    out: list[Message] = []
    for m in reversed(messages):
        if m.role != "tool":
            break
        out.append(m)
    return out[::-1]


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def _usage(u: Any) -> Usage:
    u = u if isinstance(u, Mapping) else {}

    def n(key: str) -> int:
        value = u.get(key, 0)
        return value if isinstance(value, int) else 0

    return Usage(input_tokens=n("input_tokens"), output_tokens=n("output_tokens"),
                 cache_read=n("cache_read_input_tokens"), cache_write=n("cache_creation_input_tokens"))
