"""La console en MCP (``/mcp/console``) — lire Mika depuis le Claude Code d'une opératrice.

- les vues déclarées se découvrent (clé, titre, paramètres) et se lisent en
  texte, paramètres compris ; les fiches aussi, par la recherche ;
- rien n'y écrit : tous les outils sont en lecture seule ;
- le point ne sert que la boucle locale, le bon jeton (il n'en connaît que
  l'empreinte, comparée à celle du jeton présenté), et n'existe pas tant
  qu'aucun jeton n'est défini ; ouvert au réseau (ADR 0126), il sert aussi une
  autre machine, mandataire compris, toujours avec le jeton.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from mika.app.handmade.waiting import QUEUE as WAITING
from mika.inspector.mcp import DEFAULT_SERVED, PARTS, QUEUE, TOOLS, ConsoleHost, console_app
from mika.ports.llm import LLMResponse
from mika.runtime.inspection import Inspection
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest() if token else ""


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


def test_the_views_the_queue_reads_are_listed_and_read_too(tmp_path):
    """Les identités à confirmer, les noms à relier, les rapprochements de l'annuaire : hors de la navigation (la file
    « À valider » les lit), mais listés et lus ici comme les autres (ADR 0304)."""
    kernel, clock = _kernel_with_someone(tmp_path)

    async def main():
        await boot(kernel)
        try:
            host = ConsoleHost(kernel)
            return (await host.call("lister_vues", {})).text, await host.call("vue", {"cle": "contacts/rapprochements"})
        finally:
            await kernel.stop()

    catalogue, matches = run_virtual(clock, main)
    lines = {line.split(" — ", 1)[0]: line for line in catalogue.splitlines() if line.startswith("- ")}
    for key in ("identity/noms", "identity/revendications", "contacts/rapprochements"):
        assert "(hors de la navigation)" in lines[f"- {key}"]
    assert "(hors de la navigation)" not in lines["- memory/souvenirs"]
    assert not matches.is_error and matches.text.startswith("# Rapprochements de l'annuaire")


def test_what_waits_for_your_decision_is_served_by_its_own_part(tmp_path):
    """Les vues que lit la file « À valider » (la composition les déclare) se servent par leur part, « a_valider », que
    la page Prêter à un agent coche ou non ; les autres vues, par la leur (ADR 0304)."""
    kernel, clock = _kernel_with_someone(tmp_path)
    chosen: list[str] = ["vues"]
    pages = SimpleNamespace(ui=SimpleNamespace(inspection=Inspection(kernel, sampler=kernel.series.read),
                                               deps=SimpleNamespace(queue=WAITING)), tab=lambda key: None)

    async def main():
        await boot(kernel)
        try:
            host = ConsoleHost(kernel, pages, lambda: chosen)
            out = [(await host.call("lister_vues", {})).text, await host.call("vue", {"cle": "identity/noms"}),
                   await host.call("vue", {"cle": "transcript/messages"})]
            chosen[:] = ["a_valider"]
            out += [(await host.call("lister_vues", {})).text, await host.call("vue", {"cle": "identity/noms"})]
            return out
        finally:
            await kernel.stop()

    views_only, names_refused, messages, queue_only, names = run_virtual(clock, main)
    assert "identity/noms" not in views_only and "- memory/souvenirs" in views_only
    assert names_refused.is_error and not messages.is_error
    assert "- identity/noms — Noms à relier [identites] (la file « À valider »)" in queue_only
    assert "- contacts/rapprochements" in queue_only and "- memory/souvenirs" not in queue_only
    assert not names.is_error and names.text.startswith("# Noms à relier")
    assert QUEUE in PARTS and QUEUE in DEFAULT_SERVED


def test_the_console_endpoint_is_read_only():
    assert all(t.read_only for t in TOOLS)
    assert {t.name for t in TOOLS} == {"lister_vues", "vue", "pourquoi", "chercher", "fiche"}


async def _post(app, *, token: str = "", client: str = "127.0.0.1", proxied: bool = False) -> tuple[int, Any]:
    sent: list[dict[str, Any]] = []
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    if proxied:  # relayée par un mandataire local : elle arrive de 127.0.0.1, ses en-têtes la trahissent
        headers.append((b"x-forwarded-for", b"192.168.1.22"))
    scope = {"type": "http", "method": "POST", "path": "/mcp/console", "root_path": "", "client": (client, 5000),
             "headers": headers}
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
            app = console_app(kernel, lambda: _digest(token["value"]))  # le point ne reçoit que l'empreinte
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


def test_the_console_opened_to_the_network_still_wants_its_token(tmp_path):
    kernel, clock = _kernel_with_someone(tmp_path)
    network = {"open": False}

    async def main():
        await boot(kernel)
        try:
            app = console_app(kernel, lambda: _digest("jeton-de-l-operatrice"), network=lambda: network["open"])
            relayed = await _post(app, token="jeton-de-l-operatrice", proxied=True)
            network["open"] = True
            far = await _post(app, token="jeton-de-l-operatrice", client="192.168.1.22")
            through = await _post(app, token="jeton-de-l-operatrice", proxied=True)
            wrong = await _post(app, token="mauvais", client="192.168.1.22")
            return relayed, far, through, wrong
        finally:
            await kernel.stop()

    relayed, far, through, wrong = run_virtual(clock, main)
    assert relayed[0] == 403  # fermée au réseau : relayée par le mandataire, elle ne passe pas
    assert far[0] == 200 and through[0] == 200
    assert wrong[0] == 401
