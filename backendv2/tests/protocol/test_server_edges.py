"""Le serveur au bord du monde : ce que les journaux ne disent jamais, un
déploiement derrière un mandataire, les points MCP qu'un mandataire ne rend pas
joignables, les dossiers de la CLI hors des sauvegardes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mika.adapters.mcp.protocol import Tool
from mika.adapters.mcp.relay import PREFIX, Relay
from mika.adapters.web.app import DEV_ORIGINS
from mika.app import backup
from mika.app.server import RedactingFilter, redact, web_config

TOKEN = "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


def test_logs_never_show_a_secret():
    assert "abc123secret" not in redact("GET https://flux.example/rss?user=moi&token=abc123secret&x=1")
    assert "user=moi" in redact("GET https://flux.example/rss?user=moi&token=abc123secret")
    assert "s3cr3t-jeton-long" not in redact("Authorization: Bearer s3cr3t-jeton-long")


def test_the_filter_masks_records_from_any_library(caplog):
    record = logging.LogRecord("httpx", logging.WARNING, __file__, 1, "HTTP Request: %s %s", ("GET",
                               f"https://flux.example/rss?access_token={TOKEN}"), None)
    assert RedactingFilter().filter(record)
    assert TOKEN not in record.getMessage()


def test_a_deployment_behind_a_proxy_declares_its_origin_and_secure_cookies():
    dev = web_config()
    assert tuple(dev.origins) == DEV_ORIGINS and not dev.cookie_secure and not dev.behind_proxy
    prod = web_config(origins=["https://mika.example/", "https://mika.example"], behind_proxy=True)
    assert tuple(prod.origins) == ("https://mika.example",) and prod.cookie_secure and prod.behind_proxy


async def _status(relay: Relay, path: str, token: str, headers: list[tuple[bytes, bytes]]) -> int:
    sent: list[dict[str, Any]] = []
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    scope = {"type": "http", "method": "POST", "path": path, "root_path": "", "client": ("127.0.0.1", 5000),
             "headers": [(b"authorization", f"Bearer {token}".encode()), *headers]}
    received = iter([{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        return next(received)

    async def send(msg):
        sent.append(msg)

    await relay.app(scope, receive, send)
    return sent[0]["status"]


async def test_mcp_refuses_a_request_relayed_by_a_local_proxy():
    relay = Relay()
    session = relay.open([Tool("t", "t", {"type": "object"})], [], lambda p: None)
    path = f"{PREFIX}/{session.id}/mika"
    assert await _status(relay, path, session.token, []) == 200  # la CLI, en local
    for header in (b"x-forwarded-for", b"forwarded", b"x-real-ip"):  # Internet, relayé par nginx en local
        assert await _status(relay, path, session.token, [(header, b"203.0.113.9")]) == 403


def test_cli_call_folders_are_never_archived(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "mind.db").write_bytes(b"")
    leak = data / "claude-code" / "appel-1-x"
    leak.mkdir(parents=True)
    (leak / "mcp.json").write_text("{\"Authorization\": \"Bearer jeton\"}")
    (data / "forge").mkdir()
    (data / "forge" / "app.py").write_text("x")
    members = [p.as_posix() for p in backup._members(data)]
    assert "forge/app.py" in members and not [m for m in members if m.startswith("claude-code")]
