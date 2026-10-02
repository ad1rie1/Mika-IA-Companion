"""Le serveur au bord du monde : ce que les journaux ne disent jamais, un robot
Telegram qui ne démarre pas du premier coup, un déploiement derrière un
mandataire, les points MCP qu'un mandataire ne rend pas joignables, les dossiers
de la CLI hors des sauvegardes."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mika.adapters.mcp.protocol import Tool
from mika.adapters.mcp.relay import PREFIX, Relay
from mika.adapters.web.app import DEV_ORIGINS
from mika.app import backup
from mika.app.server import Live, RedactingFilter, redact, web_config

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


def test_logs_never_show_a_secret():
    line = f"HTTP Request: POST https://api.telegram.org/bot{TOKEN}/getUpdates \"HTTP/1.1 200 OK\""
    assert TOKEN not in redact(line) and "bot<jeton>/getUpdates" in redact(line)
    assert "abc123secret" not in redact("GET https://flux.example/rss?user=moi&token=abc123secret&x=1")
    assert "user=moi" in redact("GET https://flux.example/rss?user=moi&token=abc123secret")
    assert "s3cr3t-jeton-long" not in redact("Authorization: Bearer s3cr3t-jeton-long")


def test_the_filter_masks_records_from_any_library(caplog):
    record = logging.LogRecord("httpx", logging.WARNING, __file__, 1, "HTTP Request: %s %s", ("POST",
                               f"https://api.telegram.org/bot{TOKEN}/sendMessage"), None)
    assert RedactingFilter().filter(record)
    assert TOKEN not in record.getMessage()


class FakePoller:
    """Le robot : échoue ``fail`` fois au démarrage (réseau coupé), puis démarre."""

    def __init__(self, fail: int, error: type[Exception] = OSError) -> None:
        self.fail = fail
        self.error = error
        self.starts = 0
        self.stopped = 0
        self.channel = object()

    def __call__(self, token: str, make_channel: Any) -> FakePoller:
        return self

    async def start(self) -> None:
        self.starts += 1
        if self.starts <= self.fail:
            raise self.error("réseau injoignable")

    async def stop(self) -> None:
        self.stopped += 1


class _Settings:
    def __init__(self, **tg: Any) -> None:
        self.tg = {"token": "t", "allowed_chats": [], "owners": [], "open": False, **tg}

    def telegram(self) -> dict[str, Any]:
        return self.tg


class _Router:
    telegram: Any = None


class _Live(Live):
    """Le robot seul, sans noyau."""

    async def reconfigure(self) -> list[str]:
        return []

    def persona(self) -> Any:
        return type("P", (), {"name": "Mika"})()


def live_with(poller: FakePoller, **tg: Any) -> Live:
    live = _Live.__new__(_Live)
    live.settings = _Settings(**tg)  # type: ignore[assignment]
    live.router = _Router()  # type: ignore[assignment]
    live.telegram = None
    live.make_poller = poller
    live.telegram_status, live.telegram_attempts, live.telegram_error = "off", 0, ""
    live._telegram_task = None
    live.port = None  # type: ignore[assignment]
    live.preprocess = None
    return live


async def test_a_robot_that_fails_to_start_is_retried_with_growing_delays(monkeypatch):
    from mika.app import server

    monkeypatch.setattr(server, "TELEGRAM_RETRY_MIN_S", 0.01)
    poller = FakePoller(fail=2)
    live = live_with(poller, owners=[42])
    await live.start_telegram()
    assert live.channel_health() == {"telegram": "degraded"}  # pas encore là : /health le dit
    for _ in range(100):
        if live.telegram_status == "running":
            break
        await asyncio.sleep(0.01)
    assert live.telegram_status == "running" and poller.starts == 3 and live.telegram is poller
    assert live.router.telegram is poller.channel and live.channel_health() == {"telegram": "ok"}
    await live.stop_telegram()
    assert live.channel_health() == {}


async def test_a_refused_token_is_not_retried_and_a_closed_robot_does_not_start(monkeypatch):
    class InvalidToken(Exception):
        pass

    poller = FakePoller(fail=99, error=InvalidToken)
    live = live_with(poller, owners=[42])
    await live.start_telegram()
    await asyncio.sleep(0.05)
    assert live.telegram_status == "invalid" and poller.starts == 1
    assert live.channel_health() == {"telegram": "ko"}
    closed = live_with(FakePoller(fail=0))  # ni liste, ni propriétaire, ni ouverture
    await closed.start_telegram()
    assert closed.telegram_status == "closed" and closed.make_poller.starts == 0  # type: ignore[attr-defined]


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
