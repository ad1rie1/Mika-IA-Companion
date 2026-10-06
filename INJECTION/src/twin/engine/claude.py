"""Un appel à Claude Code : la CLI ``claude -p``, son propre login, isolée, sortie structurée.

Mêmes règles que le moteur de Mika (``backendv2/src/mika/adapters/llm/claude_code.py``,
ADR 0026) :

- **aucun jeton** ne passe par ici. L'environnement est reconstruit sur une liste
  blanche, et ``CLAUDE_CODE_OAUTH_TOKEN`` / ``ANTHROPIC_AUTH_TOKEN`` sont retirés même si
  le parent les a ;
- **isolée** : ni réglages, ni CLAUDE.md, ni connecteurs claude.ai, ni outil natif, ni
  session gardée, dans un dossier de travail vide. Seul un serveur MCP explicitement donné
  (le « jumeau », en lecture) peut lui ouvrir des outils ;
- la **sortie structurée** passe par ``--json-schema`` ; à défaut, on prend le premier
  objet JSON du texte. Le schéma Pydantic de l'appelant valide dans les deux cas ;
- l'**usage de l'abonnement** (``rate_limit_event``) est relevé à chaque appel. Le
  pilote des lots s'en sert pour faire une pause avant le plafond.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: les seules variables du parent qui passent (HOME : la CLI y trouve son login)
INHERITED = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR")
#: jamais transmises, même si le parent les a
FORBIDDEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
READ_LIMIT = 32 * 1024 * 1024
STDERR_KEPT = 4000


class ClaudeError(RuntimeError):
    """La CLI n'a pas rendu de réponse utilisable (non connectée, plantée, refus, délai)."""


@dataclass(frozen=True, slots=True)
class QuotaReading:
    window: str
    utilization: float
    resets_at: int = 0  # secondes epoch


@dataclass
class CallSpec:
    prompt: str
    system: str
    schema: Mapping[str, Any] | None = None
    model: str = "sonnet"
    #: un serveur MCP à ouvrir (fichier de configuration) et les outils permis (« mcp__jumeau__* »)
    mcp_config: Path | None = None
    allowed_tools: tuple[str, ...] = ()
    max_output_tokens: int = 32_000
    timeout_s: float = 900.0


@dataclass
class CallResult:
    text: str
    data: dict[str, Any] | None
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    duration_s: float = 0.0
    quota: list[QuotaReading] = field(default_factory=list)


def claude_binary() -> str:
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


def build_env(spec: CallSpec) -> dict[str, str]:
    env = {k: os.environ[k] for k in INHERITED if os.environ.get(k)}
    env.update({
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(spec.max_output_tokens),
        "MCP_TOOL_TIMEOUT": "120000",
    })
    for key in FORBIDDEN:
        env.pop(key, None)
    return env


def build_argv(spec: CallSpec, workdir: Path, binary: str | None = None) -> list[str]:
    args = [binary or claude_binary(), "-p", "--output-format", "stream-json", "--verbose",
            "--system-prompt-file", str(workdir / "system.txt"),
            "--setting-sources", "", "--strict-mcp-config", "--tools", "",
            "--permission-mode", "dontAsk", "--no-session-persistence", "--model", spec.model]
    if spec.schema is not None:
        args += ["--json-schema", json.dumps(spec.schema, ensure_ascii=False)]
    if spec.mcp_config is not None:
        args += ["--mcp-config", str(spec.mcp_config)]
        if spec.allowed_tools:
            args += ["--allowedTools", ",".join(spec.allowed_tools)]
    return args


_OBJECT = re.compile(r"\{.*\}", re.S)


def first_json_object(text: str) -> dict[str, Any] | None:
    """Le premier objet JSON d'un texte (dans un bloc ```json``` ou nu)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    for candidate in ([fenced.group(1)] if fenced else []) + ([m.group(0)] if (m := _OBJECT.search(text)) else []):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_quota(info: Mapping[str, Any]) -> list[QuotaReading]:
    """Les fenêtres d'usage de l'abonnement (un objet par fenêtre, ou une liste)."""
    windows = info.get("unifiedWindows")
    if isinstance(windows, Mapping):
        items = [(str(k), w) for k, w in windows.items()]
    elif isinstance(windows, list):
        items = [(str(w.get("window") or w.get("name") or i) if isinstance(w, Mapping) else str(i), w)
                 for i, w in enumerate(windows)]
    else:
        return []
    out = []
    for window, w in items:
        if isinstance(w, Mapping) and isinstance(w.get("utilization"), int | float):
            resets = w.get("resetsAt")
            out.append(QuotaReading(window, float(w["utilization"]), int(resets) if isinstance(resets, int | float) else 0))
    return out


async def call(spec: CallSpec, *, binary: str | None = None) -> CallResult:
    """Un appel complet. Lève ``ClaudeError`` si rien d'utilisable n'est revenu."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="jumeau-appel-") as tmp:
        workdir = Path(tmp)
        (workdir / "system.txt").write_text(spec.system, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            *build_argv(spec, workdir, binary), cwd=workdir, env=build_env(spec),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=READ_LIMIT, start_new_session=True)
        try:
            out, err = await asyncio.wait_for(_communicate(proc, spec.prompt), timeout=spec.timeout_s)
        except (TimeoutError, asyncio.CancelledError):
            _kill(proc)
            await proc.wait()
            raise
        result, texts, model, quota = _read_stream(out)
    elapsed = time.monotonic() - started
    if result is None:
        raise ClaudeError(f"la CLI s'est arrêtée sans résultat (code {proc.returncode}) : "
                          f"{err.decode(errors='replace')[-STDERR_KEPT:].strip()}")
    if result.get("is_error") or result.get("subtype") != "success":
        detail = result.get("result") or ", ".join(map(str, result.get("errors") or ())) or result.get("subtype")
        raise ClaudeError(f"la CLI a échoué : {detail}")
    text = str(result.get("result") or "".join(texts))
    data = result.get("structured_output")
    if not isinstance(data, dict):
        data = first_json_object(text)
    return CallResult(text=text, data=data, model=model, usage=dict(result.get("usage") or {}),
                      cost_usd=float(result.get("total_cost_usd") or 0.0), duration_s=elapsed, quota=quota)


async def _communicate(proc: asyncio.subprocess.Process, prompt: str) -> tuple[bytes, bytes]:
    return await proc.communicate(prompt.encode("utf-8"))


def _kill(proc: asyncio.subprocess.Process) -> None:
    """Arrête tout le groupe de processus (la CLI et ce qu'elle a lancé)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_stream(out: bytes) -> tuple[dict[str, Any] | None, list[str], str, list[QuotaReading]]:
    result: dict[str, Any] | None = None
    texts: list[str] = []
    model = ""
    quota: list[QuotaReading] = []
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        kind = d.get("type")
        if kind == "assistant":
            message = d.get("message") if isinstance(d.get("message"), Mapping) else {}
            model = str(message.get("model") or model)
            for block in message.get("content") or ():
                if isinstance(block, Mapping) and block.get("type") == "text" and block.get("text"):
                    texts.append(str(block["text"]))
        elif kind == "rate_limit_event" and isinstance(d.get("rate_limit_info"), Mapping):
            quota = parse_quota(d["rate_limit_info"]) or quota
        elif kind == "result":
            result = d
    return result, texts, model, quota
