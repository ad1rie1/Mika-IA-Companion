"""Un serveur MCP lancé sur cette machine (ADR 0064 §10), dans la vraie cage bubblewrap.

Un faux serveur Python dit ce qu'il voit de dedans : son environnement (reconstruit — rien du serveur n'entre ;
ses variables, ses secrets), son dossier (le seul où il écrit), un dossier partagé (en lecture ; « :rw » pour
écrire), ce qu'il ne voit pas (le reste de la machine), le réseau (coupé). Il tombe : sa sortie d'erreur est
gardée, son secret masqué, la session suivante le relance. Sans bubblewrap, rien ne se lance."""

from __future__ import annotations

import os
import shutil
import socket
import textwrap

import pytest

from mika.adapters.mcp.config import McpConfig, McpServer, StoredReview
from mika.adapters.mcp.hub import McpHub
from mika.adapters.mcp.stdio import NO_BWRAP, Sandbox

pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")

SECRET = "secret-local-canari-91"
SERVER = textwrap.dedent('''
    import json, os, socket, sys

    TOOLS = [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}}}
             for n, d in (("voir", "ce que je vois"), ("lire", "lire un chemin"), ("ecrire", "écrire un chemin"),
                          ("reseau", "joindre une adresse"), ("tomber", "tomber"))]

    def answer(mid, result):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\\n")
        sys.stdout.flush()

    def text(mid, value, error=False):
        answer(mid, {"content": [{"type": "text", "text": value}], "isError": error})

    for line in sys.stdin:
        msg = json.loads(line)
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue
        if method == "initialize":
            answer(mid, {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                         "serverInfo": {"name": "local", "version": "0.1"}})
        elif method == "tools/list":
            answer(mid, {"tools": TOOLS})
        elif method == "tools/call":
            name, x = msg["params"]["name"], msg["params"]["arguments"].get("x", "")
            if name == "voir":
                text(mid, json.dumps({"home": os.environ.get("HOME"), "cwd": os.getcwd(),
                                      "secret": os.environ.get("API_KEY"), "mine": os.environ.get("MINE"),
                                      "leak": os.environ.get("MIKA_TEST_CANARY")}, ensure_ascii=False))
            elif name == "lire":
                try:
                    text(mid, open(x).read())
                except OSError as exc:
                    text(mid, type(exc).__name__, True)
            elif name == "ecrire":
                try:
                    open(x, "w").write("écrit")
                    text(mid, "ok")
                except OSError as exc:
                    text(mid, type(exc).__name__, True)
            elif name == "reseau":
                host, port = x.rsplit(":", 1)
                try:
                    socket.create_connection((host, int(port)), timeout=2).close()
                    text(mid, "joint")
                except OSError as exc:
                    text(mid, type(exc).__name__, True)
            elif name == "tomber":
                sys.stderr.write("je tombe avec API_KEY=" + os.environ.get("API_KEY", "") + "\\n")
                sys.stderr.flush()
                sys.exit(3)
''')


class Store:
    def __init__(self, **servers: McpServer) -> None:
        self.config = McpConfig(servers=servers)
        self.reviews: dict[str, dict[str, StoredReview]] = {}

    async def save(self, reviews):
        self.reviews = reviews


def _local(tmp_path, **kw) -> tuple[McpHub, Store]:
    root = tmp_path / "mcp"
    (root / "ici").mkdir(parents=True)
    (root / "ici" / "server.py").write_text(SERVER, encoding="utf-8")
    spec = McpServer(**{"purpose": "un outil sur cette machine", "transport": "local", "command": "python3",
                        "args": ("-I", "server.py"), "env": ("MINE=à moi",), "secret_env": f"API_KEY={SECRET}",
                        "breaker": 5, **kw})
    store = Store(ici=spec)
    return McpHub(lambda: store.config, lambda: store.reviews, store.save, local_root=root), store


async def test_a_local_server_lives_in_its_cage(tmp_path, monkeypatch):
    monkeypatch.setenv("MIKA_TEST_CANARY", "fuite")
    outside = tmp_path / "ailleurs.txt"
    outside.write_text("à ne pas lire", encoding="utf-8")
    shared = tmp_path / "partage"
    shared.mkdir()
    (shared / "note.txt").write_text("une note partagée", encoding="utf-8")
    writable = tmp_path / "ecrivable"
    writable.mkdir()
    hub, _ = _local(tmp_path, shared=(str(shared), f"{writable}:rw"))
    ok, message = await hub.test("ici")
    assert ok and "local 0.1" in message and "5 outil(s)" in message, message
    seen = await hub.call("ici", "voir", {})
    home = str(tmp_path / "mcp" / "ici")
    assert seen.ok and f'"home": "{home}"' in seen.text and f'"cwd": "{home}"' in seen.text
    assert SECRET in seen.text and "à moi" in seen.text and '"leak": null' in seen.text
    assert (await hub.call("ici", "lire", {"x": str(shared / "note.txt")})).text == "une note partagée"
    assert not (await hub.call("ici", "lire", {"x": str(outside)})).ok  # le reste de la machine n'existe pas
    assert not (await hub.call("ici", "ecrire", {"x": str(shared / "x.txt")})).ok  # partagé en lecture
    assert (await hub.call("ici", "ecrire", {"x": str(writable / "x.txt")})).ok
    assert (await hub.call("ici", "ecrire", {"x": f"{home}/x.txt"})).ok and (tmp_path / "mcp/ici/x.txt").exists()
    await hub.aclose()


async def test_without_network_nothing_reaches_the_machine(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    hub, _ = _local(tmp_path)
    try:
        await hub.test("ici")
        got = await hub.call("ici", "reseau", {"x": f"127.0.0.1:{port}"})
        assert not got.ok and got.reached  # le serveur a répondu : il n'a pas pu joindre l'hôte
    finally:
        listener.close()
        await hub.aclose()


async def test_a_server_that_falls_is_said_masked_and_restarted(tmp_path):
    hub, _ = _local(tmp_path)
    await hub.test("ici")
    fell = await hub.call("ici", "tomber", {})
    assert not fell.ok and not fell.reached and "s'est arrêté" in fell.text
    status = hub.status("ici")
    assert status.state == "erreur" and any("je tombe" in line for line in status.log)
    assert all(SECRET not in line for line in status.log) and SECRET not in fell.text
    again = await hub.call("ici", "voir", {})  # la session suivante le relance
    assert again.ok and hub.status("ici").consecutive == 0
    await hub.aclose()


async def test_without_bubblewrap_nothing_starts(tmp_path):
    root = tmp_path / "mcp"
    store = Store(ici=McpServer(purpose="un outil sur cette machine", transport="local", command="python3"))
    hub = McpHub(lambda: store.config, lambda: store.reviews, store.save, local_root=root,
                 sandbox=Sandbox(None, None, None, None, None))
    ok, message = await hub.test("ici")
    assert not ok and NO_BWRAP in message
    await hub.aclose()


async def test_a_program_outside_its_folder_and_the_system_is_refused(tmp_path):
    elsewhere = tmp_path / "bin"
    elsewhere.mkdir()
    tool = elsewhere / "outil"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(tool, 0o755)
    hub, store = _local(tmp_path)
    store.config = McpConfig(servers={"ici": store.config.servers["ici"].model_copy(update={"command": str(tool)})})
    ok, message = await hub.test("ici")
    assert not ok and "introuvable" in message
    await hub.aclose()


@pytest.mark.skipif(shutil.which("pasta") is None or shutil.which("ip") is None, reason="pasta absent")
async def test_an_isolated_network_never_reaches_this_machine(tmp_path):
    listener = socket.socket()
    listener.bind(("0.0.0.0", 0))
    listener.listen()
    port = listener.getsockname()[1]
    hub, _ = _local(tmp_path, network="isole")
    try:
        ok, message = await hub.test("ici")
        assert ok, message
        for host in ("127.0.0.1", "192.0.2.1"):  # sa propre boucle locale ; la passerelle qui n'est pas l'hôte
            got = await hub.call("ici", "reseau", {"x": f"{host}:{port}"})
            assert not got.ok and got.reached, (host, got.text)
    finally:
        listener.close()
        await hub.aclose()
