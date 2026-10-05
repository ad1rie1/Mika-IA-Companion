"""La console en MCP (``/mcp/console``) — lire Mika depuis le Claude Code d'une opératrice.

- les vues déclarées se découvrent (clé, titre, paramètres) et se lisent en
  texte, paramètres compris ; les fiches aussi, par la recherche ;
- rien n'y écrit : tous les outils sont en lecture seule ;
- le point ne sert que la boucle locale, le bon jeton, et n'existe pas tant
  qu'aucun jeton n'est défini.
"""

from __future__ import annotations

import json
from typing import Any

from mika.inspector.mcp import TOOLS, ConsoleHost, console_app
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said


def _kernel_with_someone(tmp_path):
    kernel, clock, _, _ = build(tmp_path, lambda req: LLMResponse("Coucou ! [EMOTION:happy:0.4]"),
                                start=at_paris(2026, 9, 28, 15, 0))
    return kernel, clock


def test_the_console_reads_views_searches_and_fiches(tmp_path):
    kernel, clock = _kernel_with_someone(tmp_path)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "Salut, j'ai adopté un chat roux."))).reply
            await kernel.lanes.join()
            host = ConsoleHost(kernel)
            catalogue = (await host.call("lister_vues", {})).text
            thread = await host.call("vue", {"cle": "transcript/messages", "params": {"q": "chat"}})
            found = (await host.call("chercher", {"texte": "Adrien"})).text
            key = next(line.split("fiche:person/", 1)[1].split(" ")[0] for line in found.splitlines()
                       if "fiche:person/" in line)
            fiche = await host.call("fiche", {"sorte": "person", "cle": key})
            unknown = await host.call("vue", {"cle": "nulle/part"})
            return catalogue, thread, found, fiche, unknown
        finally:
            await kernel.stop()

    catalogue, thread, found, fiche, unknown = run_virtual(clock, main)
    assert "memory/souvenirs" in catalogue and "paramètres : q" in catalogue
    assert "Fiches (outil « fiche ») :" in catalogue and "- person" in catalogue
    assert not thread.is_error and "chat roux" in thread.text
    assert "fiche:person/" in found
    assert not fiche.is_error and fiche.text.startswith("# ") and "Onglets :" in fiche.text
    assert unknown.is_error and "lister_vues" in unknown.text


def test_the_console_endpoint_is_read_only():
    assert all(t.read_only for t in TOOLS)
    assert {t.name for t in TOOLS} == {"lister_vues", "vue", "pourquoi", "chercher", "fiche"}


async def _post(app, *, token: str = "", client: str = "127.0.0.1") -> tuple[int, Any]:
    sent: list[dict[str, Any]] = []
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    scope = {"type": "http", "method": "POST", "path": "/mcp/console", "root_path": "", "client": (client, 5000),
             "headers": [(b"authorization", f"Bearer {token}".encode())] if token else []}
    received = iter([{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        return next(received)

    async def send(msg):
        sent.append(msg)

    await app(scope, receive, send)
    payload = sent[1].get("body", b"") if len(sent) > 1 else b""
    return sent[0]["status"], json.loads(payload) if payload else None


def test_the_console_endpoint_serves_only_this_machine_and_the_operator_token(tmp_path):
    kernel, clock = _kernel_with_someone(tmp_path)
    token = {"value": ""}

    async def main():
        await boot(kernel)
        try:
            app = console_app(kernel, lambda: token["value"])
            closed = await _post(app, token="n'importe")
            token["value"] = "jeton-de-l-operatrice"
            ok = await _post(app, token="jeton-de-l-operatrice")
            far = await _post(app, token="jeton-de-l-operatrice", client="10.0.0.7")
            wrong = await _post(app, token="mauvais")
            return closed, ok, far, wrong
        finally:
            await kernel.stop()

    closed, ok, far, wrong = run_virtual(clock, main)
    assert closed[0] == 404  # pas de jeton défini : le point n'existe pas
    assert ok[0] == 200 and {t["name"] for t in ok[1]["result"]["tools"]} >= {"vue", "fiche"}
    assert far[0] == 403 and wrong[0] == 401
