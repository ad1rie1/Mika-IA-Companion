"""Le serveur au bord du monde : ce que les journaux ne disent jamais, un
déploiement derrière un mandataire (déclaré, ou trahi par ses en-têtes), les
points MCP qu'un mandataire ne rend pas joignables, les dossiers de la CLI hors
des sauvegardes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mika.adapters.mcp.protocol import Tool
from mika.adapters.mcp.relay import PREFIX, Relay
from mika.adapters.web import app as web_app
from mika.adapters.web.app import DEV_ORIGINS
from mika.app import backup
from mika.app.server import RedactingFilter, redact, web_config
from tests.protocol.test_web import world  # noqa: F401 — fixture

TOKEN = "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


def test_logs_never_show_a_secret():
    assert "abc123secret" not in redact("GET https://flux.example/rss?user=moi&token=abc123secret&x=1")
    assert "user=moi" in redact("GET https://flux.example/rss?user=moi&token=abc123secret")
    assert "s3cr3t-jeton-long" not in redact("Authorization: Bearer s3cr3t-jeton-long")


def test_logs_mask_her_own_tokens_basic_auth_gitlab_and_mysql_secrets():
    for secret in ("mw_" + "A" * 43, "mtk_" + "b" * 43, "mwk_" + "c" * 43, "mlp_" + "d" * 43):
        shown = redact(f"jeton {secret} refusé sur /ws")
        prefix = secret[:secret.index("_") + 1]
        assert secret not in shown and f" {prefix}… " in shown  # son préfixe dit lequel, le reste part
    assert "dXNlcjpwYXNzd29yZA==" not in redact("Authorization: Basic dXNlcjpwYXNzd29yZA==")
    assert "glpat-abcdefghij12" not in redact("X-Gitlab-Token: glpat-abcdefghij12")
    assert "abcdefgh1234" not in redact(repr({"x-gitlab-token": "abcdefgh1234"}))
    assert "s3cret!" not in redact("env MYSQL_PWD=s3cret! mariadb-dump mika_mind")
    assert redact("mw_court et mwk_x restent lisibles") == "mw_court et mwk_x restent lisibles"


def test_an_undeclared_proxy_is_said_once(world, caplog, monkeypatch):  # noqa: F811
    """Sans ``--behind-proxy``, la première requête qui porte un en-tête de mandataire est dite au journal — une
    seule fois par processus : derrière un mandataire non déclaré, l'étranglement par adresse verrait tout le monde
    en 127.0.0.1 et les cookies partiraient sans ``Secure``."""
    client, _, _ = world
    monkeypatch.setattr(web_app, "_PROXY_SAID", set())
    with caplog.at_level(logging.WARNING, logger="mika.web"):
        client.get("/auth/whoami")  # sans en-tête : rien à dire
        assert not [r for r in caplog.records if "mandataire" in r.getMessage()]
        client.get("/auth/whoami", headers={"X-Forwarded-For": "203.0.113.9"})
        client.get("/auth/whoami", headers={"X-Real-IP": "203.0.113.9", "Via": "1.1 nginx"})
    said = [r.getMessage() for r in caplog.records if "mandataire non déclaré" in r.getMessage()]
    assert len(said) == 1 and "--behind-proxy" in said[0] and "x-forwarded-for" in said[0]


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
    # le cache du modèle de plongements (HF_HOME de l'unité) se retélécharge : jamais dans une archive (ADR 0109)
    model = data / "cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-Embedding-0.6B"
    model.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"\0" * 64)
    members = [p.as_posix() for p in backup._members(data)]
    assert "forge/app.py" in members and not [m for m in members if m.startswith(("claude-code", "cache"))]
