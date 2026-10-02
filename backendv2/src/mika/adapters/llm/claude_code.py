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
  continue ; son message ``result`` fait la réponse finale. Si le runtime clôt
  la boucle (les résultats suivis d'un dernier mot à elle : « réponds
  maintenant, sans outil »), ce mot accompagne les résultats rendus — la session
  vivante finit sa réponse, rien n'est refait ;
- annulation (préemption, supplantation, délai) : le groupe de processus est
  arrêté (SIGINT puis SIGKILL) et la session fermée ; une boucle finie sur un
  appel d'outil (un rôle qui le lit comme sortie structurée, un plafond de
  tours) est relâchée par ``release(call_id)`` ; à défaut, la session est
  fauchée après ``idle_s`` — plus long que l'outil le plus lent (un programme de
  l'atelier : 600 s) pour ne jamais faucher une session vivante, plus court que
  le délai d'outil de la CLI (``MCP_TOOL_TIMEOUT``) pour qu'elle ne continue
  jamais seule sur un outil abandonné ;
- **une boucle d'outils ne se reprend pas** : une requête qui porte déjà des
  échanges d'outils sans session vivante (un redémarrage, une bascule de
  fournisseur) est refusée — aplatie en un message, la CLI referait les outils ;
- la lecture de la CLI ne peut pas mourir en silence : une ligne illisible, trop
  longue ou d'une forme inattendue est sautée, et la fin du processus est
  toujours signalée ; l'attente d'un tour est bornée (``turn_timeout_s``) ;
- la sortie est bornée (``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` d'après ``max_tokens``) ;
- les dossiers d'appel (prompt système, configuration MCP et son jeton de
  session) vivent sous ``XDG_RUNTIME_DIR`` (mémoire, propre à l'utilisateur,
  jamais sauvegardé), en ``0700`` ; ceux d'un processus mort sont purgés.

La CLI rend aussi l'usage de l'abonnement (``rate_limit_event``) : au-delà de
``quota_ceiling``, les appels de fond sont refusés (``QuotaHeld``) — la
passerelle bascule alors sur le fournisseur de repli, et la conversation, elle,
passe toujours. Une lecture dont la fenêtre est déjà réinitialisée
(``resetsAt`` passé) ne compte plus.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import shutil
import signal
import tempfile
import time
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
#: le plafond de sortie donné à la CLI ne descend pas sous ceci (un modèle qui réfléchit
#: dépenserait un petit budget avant le premier mot)
MIN_OUTPUT_TOKENS = 1024
#: un dossier d'appel sans processus connu, plus vieux que ça, est une épave (secondes)
STALE_CALL_S = 3600.0
#: le préfixe des dossiers d'appel
CALL_PREFIX = "appel-"


def runtime_dir(scope: str | os.PathLike[str] = "") -> Path:
    """Où rangent les dossiers d'appel : sous ``XDG_RUNTIME_DIR`` (en mémoire, propre à
    l'utilisateur, hors de tout dossier sauvegardé), à défaut le dossier temporaire
    suffixé de l'uid ; un sous-dossier par ``scope`` (le dossier de données), pour que
    deux Mika ne purgent pas les appels l'une de l'autre."""
    base = os.environ.get("XDG_RUNTIME_DIR") or ""
    root = Path(base) / "mika" if base and Path(base).is_dir() else \
        Path(tempfile.gettempdir()) / f"mika-{os.getuid()}"
    tag = hashlib.sha256(str(Path(scope).resolve()).encode()).hexdigest()[:12] if str(scope) else "defaut"
    return root / "claude-code" / tag


def foreign_owner(path: Path) -> Path | None:
    """Le premier dossier du chemin (lui ou un parent existant) qui n'est ni à nous ni à root :
    un ``/tmp/mika-<uid>`` créé d'avance par un autre compte recevrait sinon nos prompts privés
    et nos jetons de session (il peut renommer ce qu'on crée chez lui). ``None`` : sûr."""
    uid = os.getuid()
    for p in (path, *path.parents):
        try:
            owner = os.lstat(p).st_uid
        except OSError:
            continue  # pas encore créé : on le créera, à nous
        if owner not in (uid, 0):
            return p
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def purge_stale(work_dir: Path, *, now: float | None = None) -> int:
    """Efface les dossiers d'appel laissés par un processus mort (``appel-<pid>-…``) ou,
    sans pid lisible, plus vieux que ``STALE_CALL_S`` ; rend le nombre effacé."""
    if not work_dir.is_dir():
        return 0
    now = time.time() if now is None else now
    gone = 0
    for d in work_dir.glob(f"{CALL_PREFIX}*"):
        pid_text = d.name[len(CALL_PREFIX):].split("-", 1)[0]
        try:
            dead = int(pid_text) != os.getpid() and not _pid_alive(int(pid_text))
        except ValueError:
            try:
                dead = now - d.stat().st_mtime > STALE_CALL_S
            except OSError:
                continue
        if dead:
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
    return gone


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
    #: les serveurs MCP donnés à la CLI (``mcp.json``) : chacun doit être connecté
    servers: tuple[str, ...] = ()

    def on_call(self, p: Pending) -> None:
        self.events.put_nowait(("call", p))


class ClaudeCodeBackend:
    #: une boucle d'outils commencée ailleurs ne se reprend pas ici (voir l'en-tête) :
    #: la passerelle ne bascule jamais vers ce fournisseur en cours de boucle
    resumes_tool_loops = False

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
        idle_s: float = 660.0,
        quota_ceiling: float = 0.8,
        tool_timeout_s: float = 900.0,
        turn_timeout_s: float = 900.0,
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
        self.work_dir = Path(work_dir) if work_dir else runtime_dir()
        # fauchée avant que la CLI ne renonce d'elle-même à un outil (elle continuerait seule)
        self.idle_s = min(idle_s, max(1.0, tool_timeout_s - 60.0))
        self.quota_ceiling = quota_ceiling
        self.tool_timeout_s = tool_timeout_s
        #: l'attente d'un tour de la CLI (entre deux appels d'outils, ou jusqu'à sa réponse)
        self.turn_timeout_s = turn_timeout_s
        self.quota: dict[str, QuotaReading] = {}
        self._runs: dict[str, _Run] = {}
        self._purged = False

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
            # la sortie suit le budget de la requête (la CLI l'ignorait : un murmure pouvait faire une page)
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max(MIN_OUTPUT_TOKENS, int(req.max_tokens))),
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
        results = _results_of(req.messages)
        return bool(run.handed) and bool(results) and {m.tool_call_id for m in results} >= run.handed

    def _feed(self, run: _Run, req: LLMRequest) -> None:
        if run.reaper is not None:
            run.reaper.cancel()
            run.reaper = None
        assert run.session is not None
        mine = [m for m in _results_of(req.messages) if m.tool_call_id in run.handed]
        closing = _closing_word(req.messages)
        for i, m in enumerate(mine):
            # le dernier mot du runtime (clore la boucle) arrive avec le dernier résultat : la CLI ne
            # reçoit plus rien d'autre de nous, c'est la seule voie pour qu'elle le lise
            content = f"{m.content}\n\n{closing}" if closing and i == len(mine) - 1 else m.content
            run.session.resolve(m.tool_call_id or "", Outcome(content, bool(m.is_error)))
        run.handed.clear()

    async def _start(self, req: LLMRequest) -> _Run:
        if any(m.role == "tool" or m.tool_calls for m in req.messages):
            # aplatie en un message, la boucle perdrait ses échanges d'outils : la CLI les referait
            raise ClaudeCodeError("une boucle d'outils commencée ailleurs (ou avant un redémarrage) ne se reprend "
                                  "pas dans une nouvelle session de la CLI")
        self._hold_for_quota(req)
        binary = self.binary()
        if not Path(binary).is_file() and shutil.which(binary) is None:
            raise ClaudeCodeError(f"CLI Claude Code introuvable : {binary}")
        core = [_tool(t) for t in req.tools if not t.deferred]
        extra = [_tool(t) for t in req.tools if t.deferred]
        base = self._relay_base() if callable(self._relay_base) else self._relay_base
        if (core or extra) and not base:
            raise ClaudeCodeError("le relais MCP n'est pas joignable (serveur pas encore à l'écoute)")
        self._prepare_work_dir()
        run = _Run(session=None)
        # enregistrée tout de suite : une erreur plus loin (disque plein…) l'arrête entière, session comprise
        self._runs[req.call_id] = run
        if core or extra:
            run.session = self.relay.open(core, extra, run.on_call)
        run.workdir = Path(tempfile.mkdtemp(prefix=f"{CALL_PREFIX}{os.getpid()}-", dir=self.work_dir))
        _write_private(run.workdir / "system.txt", "\n\n".join(p for p in (req.system_stable, req.system_volatile)
                                                                  if p.strip()))
        if run.session is not None:
            config = self.mcp_config(run.session, str(base))
            run.servers = tuple(config["mcpServers"])
            _write_private(run.workdir / "mcp.json", json.dumps(config))
        (run.workdir / "cwd").mkdir()
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

    def _prepare_work_dir(self) -> None:
        """Le dossier des appels, privé (``0700``) ; à sa première utilisation, les épaves
        laissées par un processus mort (prompts privés, jetons de session) sont effacées.
        Un dossier tenu par un autre compte est refusé : on n'y écrit rien."""
        squatted = foreign_owner(self.work_dir)
        if squatted is not None:
            raise ClaudeCodeError(f"le dossier des appels passe par {squatted}, qui appartient à un autre compte : "
                                  "rien n'y est écrit (définis XDG_RUNTIME_DIR)")
        self.work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            self.work_dir.chmod(0o700)
        if not self._purged:
            self._purged = True
            gone = purge_stale(self.work_dir)
            if gone:
                log.info("Claude Code : %d dossier(s) d'appel abandonné(s) effacé(s)", gone)

    async def _next(self, call_id: str, run: _Run) -> LLMResponse:
        texts: list[str] = []
        while True:
            try:
                kind, value = await asyncio.wait_for(run.events.get(), self.turn_timeout_s)
            except TimeoutError:
                self._schedule_stop(call_id)
                raise ClaudeCodeError(f"la CLI n'a rien dit en {self.turn_timeout_s:.0f} s") from None
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
        if kind == "mcp":
            raise ClaudeCodeError(f"la CLI n'a pas pu joindre les outils de Mika ({value}) : elle aurait répondu "
                                  "sans ses mains")
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
        """Lit la CLI jusqu'au bout. Ne meurt jamais en silence : une ligne qu'on ne
        comprend pas est sautée, et la fin est **toujours** signalée (``exit``) quand
        aucun résultat n'est venu — sinon l'appel attendait sans fin."""
        assert run.proc is not None and run.proc.stdout is not None
        result_seen = False
        code: int | None = None
        try:
            while True:
                try:
                    line = await run.proc.stdout.readline()
                except ValueError:  # ligne au-delà de READ_LIMIT : le tampon est vidé, la suite se relit
                    log.warning("Claude Code : une ligne trop longue a été sautée")
                    continue
                if not line:
                    break
                try:
                    if self._line(run, line):
                        result_seen = True
                except Exception as exc:  # une forme inattendue ne tue pas la lecture
                    log.warning("Claude Code : ligne illisible sautée (%r)", exc)
            code = await run.proc.wait()
        finally:
            if not result_seen:
                run.events.put_nowait(("exit", code))

    def _line(self, run: _Run, line: bytes) -> bool:
        """Une ligne de la CLI ; ``True`` si c'est son résultat."""
        try:
            d = json.loads(line)
        except ValueError:
            return False
        if not isinstance(d, dict):
            return False
        kind = d.get("type")
        if kind == "system" and d.get("subtype") == "init":
            broken = _unreachable(d, run.servers)
            if broken:
                # la vraie CLI continue sans un serveur MCP qui a échoué : le modèle
                # n'aurait alors aucun outil et raconterait ses appels au lieu de les faire
                run.events.put_nowait(("mcp", broken))
        elif kind == "assistant":
            message = d.get("message")
            message = message if isinstance(message, Mapping) else {}
            run.model = str(message.get("model") or run.model)
            for block in message.get("content") or ():
                if isinstance(block, Mapping) and block.get("type") == "text" and block.get("text"):
                    run.events.put_nowait(("text", str(block["text"])))
        elif kind == "rate_limit_event":
            info = d.get("rate_limit_info")
            self._note_quota(info if isinstance(info, Mapping) else {})
        elif kind == "result":
            run.events.put_nowait(("result", d))
            return True
        return False

    async def _drain_stderr(self, run: _Run) -> None:
        assert run.proc is not None and run.proc.stderr is not None
        while chunk := await run.proc.stderr.read(4096):
            run.stderr = (run.stderr + chunk.decode(errors="replace"))[-STDERR_KEPT:]

    # ── Quota de l'abonnement ────────────────────────────────────────────

    def _note_quota(self, info: Mapping[str, Any]) -> None:
        """Les fenêtres d'usage de l'abonnement : un objet par fenêtre, ou une liste
        (une forme qui changerait ne doit jamais casser la lecture)."""
        windows = info.get("unifiedWindows")
        if isinstance(windows, Mapping):
            items = [(str(k), w) for k, w in windows.items()]
        elif isinstance(windows, list):
            items = [(str(w.get("window") or w.get("name") or i) if isinstance(w, Mapping) else str(i), w)
                     for i, w in enumerate(windows)]
        else:
            return
        for window, w in items:
            if not isinstance(w, Mapping) or not isinstance(w.get("utilization"), (int, float)):
                continue
            resets = w.get("resetsAt")
            self.quota[window] = QuotaReading(window, float(w["utilization"]),
                                              int(resets) if isinstance(resets, (int, float)) else 0)

    def _live_quota(self, now: float | None = None) -> list[QuotaReading]:
        """Les lectures encore valables : une fenêtre réinitialisée (``resetsAt`` passé) ne compte plus."""
        now = time.time() if now is None else now
        for key in [k for k, q in self.quota.items() if q.resets_at and q.resets_at <= now]:
            del self.quota[key]
        return list(self.quota.values())

    def _hold_for_quota(self, req: LLMRequest) -> None:
        if self.auth != "abonnement" or self.quota_ceiling <= 0 or req.priority == 0:
            return
        worst = max(self._live_quota(), key=lambda q: q.utilization, default=None)
        if worst is not None and worst.utilization >= self.quota_ceiling:
            raise QuotaHeld(f"abonnement entamé à {worst.utilization:.0%} ({worst.window}) : "
                            f"appel de fond laissé au repli")

    def status(self) -> dict[str, Any]:
        return {"sessions": len(self._runs),
                "quota": {q.window: round(q.utilization, 3) for q in sorted(self._live_quota(), key=lambda q: q.window)}}

    def release(self, call_id: str) -> None:
        """La boucle ``call_id`` est finie (la passerelle relaie la fin dite par le runtime) :
        la session, si elle attend encore un résultat d'outil, est arrêtée tout de suite."""
        if call_id in self._runs:
            self._schedule_stop(call_id)

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


def _closing_word(messages: Sequence[Message]) -> str:
    """Le dernier mot du runtime après les résultats d'outils (« réponds maintenant ») : vide sinon."""
    if len(messages) >= 2 and messages[-1].role == "user" and messages[-2].role == "tool":
        return str(messages[-1].content or "")
    return ""


def _results_of(messages: Sequence[Message]) -> list[Message]:
    """Les résultats d'outils qui terminent la requête — suivis, au plus, d'un dernier mot du runtime."""
    return _trailing_results(messages[:-1] if _closing_word(messages) else messages)


#: ce qu'un serveur MCP peut encore devenir (la CLI peut annoncer l'état avant la fin de la poignée de main)
REACHABLE = frozenset({"connected", "pending"})


def _unreachable(init: Mapping[str, Any], servers: Sequence[str]) -> str:
    """Les serveurs donnés à la CLI qu'elle n'a pas pu joindre, en mots (vide : tous
    joints). Sans liste d'états dans ``init`` (une CLI qui ne la donne pas), rien à dire."""
    listed = init.get("mcp_servers")
    if not servers or not isinstance(listed, list):
        return ""
    states = {str(s.get("name")): str(s.get("status") or "") for s in listed if isinstance(s, Mapping)}
    broken = [f"{name} : {states.get(name) or 'absent'}" for name in servers if states.get(name) not in REACHABLE]
    return ", ".join(broken)


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
