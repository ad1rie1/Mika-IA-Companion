"""Le premier compte (audit du 2026-10-26) : sur la machine du serveur, il se crée comme avant ; depuis une autre
machine, la page demande le code de premier démarrage écrit au journal — le premier arrivé sur le réseau ne devient
pas opérateur. Sans code configuré (les tests, un montage sans ``serve``), rien ne change."""

from __future__ import annotations

from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.server import build
from mika.kernel.registry import ArbitrationPolicy

ORIGIN = "http://localhost:3000"
CODE = "abc-def-ghi"


def _client(tmp_path, code: str, host: str) -> TestClient:
    app, _live = build(tmp_path / "data", web=WebConfig(bootstrap_code=code), gateway=LiveGateway(),
                       embedder=HashEmbedder(), arbitration=ArbitrationPolicy(), reply_wait=None)
    client = TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}, client=(host, 40000))
    client.__enter__()
    return client


def _bootstrap(client: TestClient, **extra):
    who = client.get("/auth/whoami").json()
    headers = {"X-CSRFToken": client.cookies.get("csrftoken")}
    return who, client.post("/auth/bootstrap", json={"username": "adrien", "password": "un-long-mot-de-passe", **extra},
                            headers=headers)


def test_from_another_machine_the_first_account_needs_the_code(tmp_path):
    client = _client(tmp_path, CODE, "192.168.1.42")
    try:
        who, refused = _bootstrap(client)
        assert who["needs_bootstrap"] and who["bootstrap_code_required"]
        assert refused.status_code == 403 and "code" in refused.json()["error"]
        _, wrong = _bootstrap(client, code="pas-le-bon")
        assert wrong.status_code == 403
        _, ok = _bootstrap(client, code=CODE)
        assert ok.status_code == 200 and ok.json()["operator"]
        assert client.get("/auth/whoami").json()["bootstrap_code_required"] is False
    finally:
        client.__exit__(None, None, None)


def test_on_the_server_machine_no_code_is_asked(tmp_path):
    client = _client(tmp_path, CODE, "127.0.0.1")
    try:
        who, ok = _bootstrap(client)
        assert who["needs_bootstrap"] and not who["bootstrap_code_required"]
        assert ok.status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_without_a_configured_code_nothing_changes(tmp_path):
    client = _client(tmp_path, "", "10.0.0.9")
    try:
        who, ok = _bootstrap(client)
        assert who["needs_bootstrap"] and not who["bootstrap_code_required"]
        assert ok.status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_the_console_asks_the_code_from_another_machine_only(tmp_path):
    far = _client(tmp_path, CODE, "192.168.1.42")
    try:
        page = far.get("/inspecteur/connexion")
        assert page.status_code == 200 and 'name="code"' in page.text
        token = far.cookies.get("csrftoken") or ""
        refused = far.post("/inspecteur/connexion", data={"csrf": token, "username": "adrien",
                                                           "password": "un-long-mot-de-passe",
                                                           "password2": "un-long-mot-de-passe", "code": "non"})
        assert refused.status_code == 400 and "code de premier démarrage" in refused.text
    finally:
        far.__exit__(None, None, None)
    near = _client(tmp_path / "ici", CODE, "127.0.0.1")
    try:
        assert 'name="code"' not in near.get("/inspecteur/connexion").text
    finally:
        near.__exit__(None, None, None)
