"""Contrat du fournisseur Claude Code : la CLI est le cerveau, le runtime reste les mains.

Une fausse CLI (``tests/fixtures/fake_claude.py``, un vrai sous-processus qui
parle stream-json et appelle le relais MCP en HTTP) remplace ``claude -p`` :

- un outil appelé par la CLI est exécuté **par la boucle du runtime** (même
  validation, même plafond, même trace) et son résultat — ou son erreur —
  revient à la CLI ;
- en conversation, ce qui est en main va au serveur ``mika``, le reste au
  serveur ``mika_plus`` (à la demande) ;
- l'isolation se vérifie sur ce que la CLI reçoit vraiment : aucun jeton OAuth,
  aucune clé en mode abonnement, aucun réglage chargé, aucun outil natif ;
- une annulation tue la CLI ; une session abandonnée est fauchée ; une CLI non
  connectée échoue et la passerelle bascule sur le repli ; un abonnement trop
  entamé retient les appels de fond, jamais la conversation ;
- le relais ne sert que la machine locale, le bon jeton, une session ouverte.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Mount

from mika.adapters.llm.claude_code import ClaudeCodeBackend, ClaudeCodeError, QuotaHeld
from mika.adapters.llm.gateway import Gateway
from mika.adapters.mcp.protocol import Tool
from mika.adapters.mcp.relay import PREFIX, Relay
from mika.kernel.clock import ManualClock
from mika.kernel.faculty import ToolSpec
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolDecl
from mika.runtime.tools import ToolResult, declare, run_tool_loop

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_claude.py"


@pytest.fixture
def cli(tmp_path: Path) -> str:
    """La fausse CLI, exécutable, lancée par l'interpréteur des tests (un enrobage
    ``sh`` : un chemin avec des espaces ne tient pas dans un shebang)."""
    path = tmp_path / "claude"
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@contextlib.asynccontextmanager
async def serving(relay: Relay):
    """Le relais monté comme dans le serveur, à l'écoute sur un port libre."""
    server = uvicorn.Server(uvicorn.Config(Starlette(routes=[Mount(PREFIX, app=relay.app)]), host="127.0.0.1",
                                           port=0, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def backend(relay: Relay, base: str, cli: str, tmp_path: Path, **kw: Any) -> ClaudeCodeBackend:
    return ClaudeCodeBackend("", relay=relay, relay_base=lambda: base, claude_bin=cli, work_dir=tmp_path / "cc",
                             **kw)


def scenario(**steps: Any) -> str:
    return "Tu es Mika.\nSCENARIO: " + json.dumps(steps)


class AddArgs(BaseModel):
    what: str


def notes(seen: list[str], *, fail: bool = False) -> ToolSpec:
    async def note_add(args: AddArgs, ctx: Any) -> ToolResult:
        seen.append(args.what)
        if fail:
            raise RuntimeError("base verrouillée")
        return ToolResult(content=f"noté {args.what}")

    return ToolSpec(owner="notes", name="note_add", description="Ajoute une note.", args=AddArgs,
                    handler=note_add, bundle="notes", episodes=frozenset({"REPLY"}), max_calls_per_episode=2)


async def loop_through(be: ClaudeCodeBackend, spec: ToolSpec, system: str):
    gateway = Gateway({"cc": be}, {"reply": "cc"}, clock=ManualClock(0))
    req = LLMRequest(role="reply", call_id="ep-1#0", system_stable=system,
                     messages=(Message("user", "Adrien: note pain et lait"),), tools=declare([spec]))
    loop = await run_tool_loop(gateway, req, {spec.name: spec},
                               lambda s, call_id: SimpleNamespace(call_id=call_id), max_turns=6)
    return loop, gateway


# ── La boucle reste celle du runtime ──────────────────────────────────────


async def test_the_cli_calls_a_tool_and_the_runtime_executes_it(tmp_path, cli):
    relay, seen = Relay(), []
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path)
        steps = [[["mika", "note_add", {"what": "pain"}], ["mika", "note_add", {"what": "lait"}]]]
        loop, gateway = await loop_through(be, notes(seen), scenario(calls=steps, say="Noté : {results}"))
    assert sorted(seen) == ["lait", "pain"]  # exécutés par le gestionnaire, pas par la CLI
    assert sorted(loop.calls) == [("note_add", True), ("note_add", True)]
    assert "note_add=noté pain" in loop.text and "note_add=noté lait" in loop.text
    assert loop.stop == "end" and loop.last.model == "fake-cc"
    assert loop.last.usage.cache_read == 100
    assert [t.outcome for t in gateway.traces] == ["ok", "ok"]  # un tour d'outils, puis la réponse
    assert len(relay) == 0 and be.status()["sessions"] == 0


async def test_the_runtime_caps_and_errors_reach_the_cli(tmp_path, cli):
    relay, seen = Relay(), []
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path)
        steps = [[["mika", "note_add", {"what": "un"}]], [["mika", "note_add", {"what": "deux"}]],
                 [["mika", "note_add", {"what": "trois"}]], [["mika", "note_add", {"oops": 1}]]]
        loop, _ = await loop_through(be, notes(seen, fail=True), scenario(calls=steps, say="{results}"))
    assert seen == ["un", "deux"]  # plafond de 2 par épisode : le troisième n'atteint pas le gestionnaire
    assert loop.text.count("ERREUR:") == 4
    assert "plafond" in loop.text and "base verrouillée" in loop.text
    assert [r.executed for r in loop.records] == [True, True, False, False]


# ── Ce que la CLI reçoit ──────────────────────────────────────────────────


def _report(text: str) -> dict[str, Any]:
    return json.loads(text.split("REPORT ", 1)[1])


async def test_the_cli_is_isolated_and_never_receives_a_token(tmp_path, cli, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-jamais")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-du-parent")
    monkeypatch.setenv("MIKA_SECRET_KEY", "secret-de-mika")
    relay = Relay()
    tools = (ToolDecl("memory_search", "Chercher.", {"type": "object"}),
             ToolDecl("email_list", "Les mails.", {"type": "object"}, deferred=True))
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path)
        req = LLMRequest(role="reply", call_id="ep-2#0", system_stable=scenario(report=True),
                         messages=(Message("user", "Adrien: salut"), Message("assistant", "Coucou !"),
                                   Message("user", "--- ETAT INTERNE ---\nx\n--- FIN ETAT INTERNE ---\n\nAdrien: ça va ?")),
                         tools=tools)
        report = _report((await be.complete(req)).text)
        keyed = backend(relay, base, cli, tmp_path, auth="cle_api", api_key="sk-ant-api-de-la-console")
        keyed_report = _report((await keyed.complete(req)).text)
    env, argv = report["env"], report["argv"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env and "MIKA_SECRET_KEY" not in env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in keyed_report["env"]
    assert keyed_report["api_key"] == "sk-ant-api-de-la-console"  # la clé déclarée, jamais celle du parent
    assert {"CLAUDE_CODE_DISABLE_AUTO_MEMORY", "ENABLE_CLAUDEAI_MCP_SERVERS", "HOME"} <= set(env)
    assert "--bare" not in argv and "--strict-mcp-config" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--tools") + 1] == "ToolSearch"  # aucun outil natif, sauf la recherche d'outils
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert report["listed"] == {"mika": ["memory_search"], "mika_plus": ["email_list"]}
    assert "Adrien: salut\ntoi : Coucou !" in report["user"] and report["user"].endswith("Adrien: ça va ?")


async def test_without_deferred_tools_no_tool_at_all_is_native(tmp_path, cli):
    relay = Relay()
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path)
        req = LLMRequest(role="journal", call_id="j-1#0", system_stable=scenario(report=True),
                         messages=(Message("user", "Écris ton journal."),))
        report = _report((await be.complete(req)).text)
    assert report["argv"][report["argv"].index("--tools") + 1] == ""
    assert "--mcp-config" not in report["argv"] and report["listed"] == {}


# ── Arrêts ────────────────────────────────────────────────────────────────


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}").exists() and "zombie" not in Path(f"/proc/{pid}/status").read_text().lower()


async def test_a_cancelled_call_kills_the_cli(tmp_path, cli):
    relay = Relay()
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path)
        req = LLMRequest(role="reply", call_id="ep-3#0", system_stable=scenario(sleep=60),
                         messages=(Message("user", "x"),), tools=(ToolDecl("t", "t", {"type": "object"}),))
        task = asyncio.create_task(be.complete(req))
        while not be._runs.get("ep-3#0") or be._runs["ep-3#0"].proc is None:
            await asyncio.sleep(0.02)
        pid = be._runs["ep-3#0"].proc.pid
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not _alive(pid) and len(relay) == 0 and not be._runs


async def test_an_abandoned_session_is_reaped(tmp_path, cli):
    relay = Relay()
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path, idle_s=0.3)
        req = LLMRequest(role="extract", call_id="x-1#0", system_stable=scenario(calls=[[["mika", "t", {}]]]),
                         messages=(Message("user", "x"),), tools=(ToolDecl("t", "t", {"type": "object"}),))
        resp = await be.complete(req)  # un rôle qui lit les appels d'outils comme sortie : il ne rappelle pas
        assert resp.stop == "tool_use" and [c.name for c in resp.tool_calls] == ["t"]
        pid = be._runs["x-1#0"].proc.pid
        for _ in range(100):
            if not be._runs:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
    assert not be._runs and len(relay) == 0 and not _alive(pid)


# ── Échecs, repli, quota ──────────────────────────────────────────────────


class Spare:
    name = "spare"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return LLMResponse("réponse de repli", model="spare-1")


async def test_a_cli_that_is_not_logged_in_fails_and_the_gateway_falls_back(tmp_path, cli):
    relay = Relay()
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path)
        req = LLMRequest(role="reply", call_id="ep-4#0", system_stable=scenario(fail="Not logged in · Please run /login"),
                         messages=(Message("user", "x"),))
        with pytest.raises(ClaudeCodeError, match="Not logged in"):
            await be.complete(req)
        gateway = Gateway({"cc": be, "spare": Spare()}, {"reply": "cc"}, clock=ManualClock(0),
                          backend_fallbacks={"cc": "spare"})
        resp = await gateway.call(req)
    assert resp.text == "réponse de repli"
    assert [(t.backend, t.outcome) for t in gateway.traces] == [("cc", "error:ClaudeCodeError"), ("spare", "ok")]


async def test_a_worn_subscription_holds_background_calls_but_never_the_conversation(tmp_path, cli):
    relay = Relay()
    async with serving(relay) as base:
        be = backend(relay, base, cli, tmp_path, quota_ceiling=0.8)
        worn = LLMRequest(role="reply", call_id="ep-5#0", system_stable=scenario(quota=0.93),
                          messages=(Message("user", "x"),), priority=0)
        await be.complete(worn)
        assert be.status()["quota"] == {"five_hour": 0.93}
        background = LLMRequest(role="journal", call_id="j-2#0", system_stable=scenario(),
                                messages=(Message("user", "x"),), priority=2, lane="background")
        with pytest.raises(QuotaHeld):
            await be.complete(background)
        talk = LLMRequest(role="reply", call_id="ep-6#0", system_stable=scenario(say="je suis là"),
                          messages=(Message("user", "x"),), priority=0)
        assert (await be.complete(talk)).text == "je suis là"


# ── Le relais ─────────────────────────────────────────────────────────────


async def _post(relay: Relay, path: str, *, token: str = "", client: str = "127.0.0.1") -> int:
    sent: list[dict[str, Any]] = []
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    scope = {"type": "http", "method": "POST", "path": path, "root_path": "", "client": (client, 5000),
             "headers": [(b"authorization", f"Bearer {token}".encode())] if token else []}
    received = iter([{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        return next(received)

    async def send(msg):
        sent.append(msg)

    await relay.app(scope, receive, send)
    return sent[0]["status"]


async def test_the_relay_serves_only_this_machine_the_right_token_and_an_open_session():
    relay = Relay()
    session = relay.open([Tool("t", "t", {"type": "object"})], [], lambda p: None)
    path = f"{PREFIX}/{session.id}/mika"
    assert await _post(relay, path, token=session.token) == 200
    assert await _post(relay, path, token=session.token, client="192.168.1.20") == 403
    assert await _post(relay, path, token="mauvais") == 401
    assert await _post(relay, path) == 401
    assert await _post(relay, f"{PREFIX}/inconnue/mika", token=session.token) == 404
    assert await _post(relay, f"{PREFIX}/{session.id}/ailleurs", token=session.token) == 404
    relay.close(session)
    assert await _post(relay, path, token=session.token) == 404


# ── La configuration ──────────────────────────────────────────────────────


def test_a_claude_code_backend_is_declared_with_its_fallback_and_costs_nothing_on_the_subscription():
    from mika.adapters.llm.config import BackendSpec, LLMConfig, build_gateway
    from mika.adapters.llm.pricing import price_usd
    from mika.ports.llm import Usage

    cfg = LLMConfig(backends={"cc": BackendSpec(kind="claude_code", model="sonnet", fallback="api"),
                              "api": BackendSpec(kind="claude", model="claude-sonnet-5-5", api_key="k")},
                    routes={"reply": "cc"})
    assert cfg.problems() == []
    gateway = build_gateway(cfg, ManualClock(0), relay=Relay(), relay_base=lambda: "http://127.0.0.1:1")
    assert gateway.backend_fallbacks == {"cc": "api"}
    assert type(gateway.backends["cc"]).__name__ == "ClaudeCodeBackend"
    kind, ttl = gateway.pricing["cc"]
    assert price_usd("claude-sonnet-5-5", Usage(1_000_000, 1_000_000), provider=kind, cache_ttl=ttl) == 0.0
    keyed = LLMConfig(backends={"cc": BackendSpec(kind="claude_code", model="sonnet", auth="cle_api", api_key="k")})
    kind, ttl = build_gateway(keyed, ManualClock(0), relay=Relay()).pricing["cc"]
    assert price_usd("claude-sonnet-5-5", Usage(1_000_000, 0), provider=kind, cache_ttl=ttl) > 0
    broken = LLMConfig(backends={"cc": BackendSpec(kind="claude_code", model="", auth="cle_api", fallback="nulle")})
    assert len(broken.problems()) == 2
