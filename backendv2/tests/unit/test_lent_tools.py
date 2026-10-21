"""Ce qu'elle expose en MCP, réglé dans la console (ADR 0122) — par leurs intentions.

- la console en MCP ne sert que ce qu'une opératrice lui fait servir : ce qui est fermé n'est ni listé ni lu ;
- un point de prêt ne sert que les outils qu'il prête, parmi ce que la porte offre en conversation à l'opératrice
  qui l'a déclaré ; l'agent agit avec ses droits à elle ;
- en lecture seule, rien ne s'écrit dans sa vie : l'outil qui voudrait écrire est refusé ; un point qui peut écrire
  écrit, sous sa propre corrélation ;
- la porte : cette machine seulement, le bon jeton (seule son empreinte est gardée), un plafond par minute ; un
  point inconnu ou sans jeton n'existe pas.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mika.app import lending as lending_mod
from mika.app.lending import Lending
from mika.contracts import goals as goals_c
from mika.inspector.mcp import ConsoleHost
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import at_paris, boot, build, connect

TOKEN = "mlp_jeton-de-test"


def _kernel(tmp_path):
    return build(tmp_path, lambda req: LLMResponse("Coucou ! [EMOTION:happy:0.4]"), start=at_paris(2026, 9, 28, 15, 0))


async def _rpc(app, method: str, params: dict | None = None, *, token: str = TOKEN, point: str = "agent",
               client: str = "127.0.0.1") -> tuple[int, Any]:
    sent: list[dict[str, Any]] = []
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    scope = {"type": "http", "method": "POST", "path": f"/mcp/pret/{point}", "root_path": "/mcp/pret",
             "client": (client, 5000), "headers": [(b"authorization", f"Bearer {token}".encode())]}
    received = iter([{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        return next(received)

    async def send(msg):
        sent.append(msg)

    await app(scope, receive, send)
    payload = sent[1].get("body", b"") if len(sent) > 1 else b""
    return sent[0]["status"], json.loads(payload) if payload else None


def test_the_console_serves_only_what_she_is_told_to(tmp_path):
    kernel, clock, _, _ = _kernel(tmp_path)

    async def main():
        await boot(kernel)
        try:
            host = ConsoleHost(kernel, served=lambda: ["systeme.sante"])
            tools = {t.name for t in host.tools()}
            catalogue = (await host.call("lister_vues", {})).text
            view = await host.call("vue", {"cle": "memory/souvenirs"})
            search = await host.call("chercher", {"texte": "Adrien"})
            everything = {t.name for t in ConsoleHost(kernel, served=lambda: None).tools()}
            return tools, catalogue, view, search, everything
        finally:
            await kernel.stop()

    tools, catalogue, view, search, everything = run_virtual(clock, main)
    assert tools == {"lister_vues", "vue"} and everything >= {"chercher", "fiche", "pourquoi"}
    assert "memory/souvenirs" not in catalogue and "Fiches" not in catalogue
    assert view.is_error and search.is_error  # fermé : ni lu, ni cherché


def test_a_point_lends_only_its_tools_read_only_or_writing(tmp_path):
    kernel, clock, _, _ = _kernel(tmp_path)
    entries = {"agent": {"digest": hashlib.sha256(TOKEN.encode()).hexdigest(), "by": "user_1",
                         "tools": ["memory_search", "goal_remind", "report_step"], "writes": False}}
    lending = Lending(kernel, lambda: entries)
    app = lending.app()
    remind = {"name": "goal_remind", "arguments": {"when": "2026-09-29T10:00", "what": "appeler le dentiste"}}

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            listed = await _rpc(app, "tools/list")
            found = await _rpc(app, "tools/call", {"name": "memory_search", "arguments": {"query": "chat"}})
            other = await _rpc(app, "tools/call", {"name": "draw", "arguments": {}})
            reading = await _rpc(app, "tools/call", remind)
            entries["agent"]["writes"] = True
            writing = await _rpc(app, "tools/call", remind)
            opened = kernel.mind.store.latest([goals_c.GOAL_OPENED.name], 5)
            return listed, found, other, reading, writing, opened
        finally:
            await kernel.stop()

    listed, found, other, reading, writing, opened = run_virtual(clock, main)
    names = {t["name"] for t in listed[1]["result"]["tools"]}
    assert names == {"memory_search", "goal_remind"}  # pas ce qui clôt une boucle, rien au-delà de ce qu'il prête
    assert all(t.get("annotations", {}).get("readOnlyHint") for t in listed[1]["result"]["tools"])
    assert not found[1]["result"]["isError"]
    assert other[1]["result"]["isError"] and "plus prêté" in other[1]["result"]["content"][0]["text"]
    assert reading[1]["result"]["isError"]
    assert reading[1]["result"]["content"][0]["text"] == phrase("runtime.tools.refused.read_only")
    assert not writing[1]["result"]["isError"]
    assert len(opened) == 1 and opened[0].correlation.startswith("pret:agent:")  # sa propre séance, au journal
    # ses derniers appels, le plus récent d'abord (un outil qu'il ne prête pas n'est pas un appel)
    assert [(c.tool, c.ok) for c in lending.recent("agent")] == [("goal_remind", True), ("goal_remind", False),
                                                                ("memory_search", True)]


def test_the_door_of_a_point(tmp_path, monkeypatch):
    kernel, clock, _, _ = _kernel(tmp_path)
    entries = {"agent": {"digest": hashlib.sha256(TOKEN.encode()).hexdigest(), "by": "user_1",
                         "tools": ["memory_search"], "writes": False},
               "neuf": {"digest": "", "by": "user_1", "tools": ["memory_search"], "writes": False}}
    app = Lending(kernel, lambda: entries).app()
    monkeypatch.setattr(lending_mod, "PER_MINUTE", 3)

    async def main():
        await boot(kernel)
        try:
            far = await _rpc(app, "tools/list", client="10.0.0.7")
            wrong = await _rpc(app, "tools/list", token="mlp_mauvais")
            unknown = await _rpc(app, "tools/list", point="ailleurs")
            tokenless = await _rpc(app, "tools/list", point="neuf")
            ok = [await _rpc(app, "tools/list") for _ in range(3)]
            flooded = await _rpc(app, "tools/list")
            return far, wrong, unknown, tokenless, ok, flooded
        finally:
            await kernel.stop()

    far, wrong, unknown, tokenless, ok, flooded = run_virtual(clock, main)
    assert far[0] == 403 and wrong[0] == 401 and unknown[0] == 404 and tokenless[0] == 404
    assert all(status == 200 for status, _ in ok) and flooded[0] == 429
