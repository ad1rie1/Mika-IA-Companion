"""« Ses outils » (ADR 0064) : la console lit ce que le moteur exécute.

Chaque outil du registre a sa ligne et sa fiche ; la matrice « qui reçoit quoi » est calculée par la porte d'offre
du pipeline — le récit « pourquoi pas » dit la même chose qu'elle, situation par situation ; un outil défini dans le
code ne se règle pas ici (aucun formulaire de plus qu'une page sans action) ; « Ce qu'elle lit » est le texte que
son prompt porte vraiment."""

from __future__ import annotations

import re
from types import SimpleNamespace

from mika.inspector.mcp import TOOLS as CONSOLE_TOOLS
from mika.inspector.pages import tools as page
from mika.runtime.tools import ACTING
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_inspector_pages import every_page, html_of
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

BASE = "/inspecteur/outils"


def _forms(text: str) -> int:
    return len(re.findall(r"<form\b", text))


def test_every_tool_is_listed_with_its_fiche_and_none_can_be_set_here(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    registry = live.kernel.registry
    listed = every_page(client, f"{BASE}/tous")
    missing = [n for n in registry.tools if n not in listed]
    assert missing == [], missing
    plain = _forms(client.get(f"{BASE}/qui").text)  # une page sans action : ses seuls formulaires sont ceux du cadre
    for name, spec in registry.tools.items():
        r = client.get(f"{BASE}/tous", params={"outil": name})
        text = html_of(r)
        assert r.status_code == 200 and name in text and "non — défini dans le code" in text, name
        assert registry.bundles[spec.bundle] in text, name
        assert _forms(r.text) == plain, f"{name} : un outil du code ne se règle pas ici"
        ConsoleHTML(r.text).check()
    assert "Aucun outil ne s'appelle" in html_of(client.get(f"{BASE}/tous", params={"outil": "rien_du_tout"}))


def test_the_matrix_and_its_reasons_say_what_the_pipeline_offers(world):  # noqa: F811
    client, live, _ = world
    kernel = live.kernel
    ui = SimpleNamespace(kernel=kernel)
    offers = {}
    for s in page.situations(ui):
        policy = kernel.runner.policies[s.kind]
        offered = page.offered_in(ui, s)
        # la console et le pipeline passent par la même porte
        assert offered == kernel.runner._tools(policy, s.kind, s.audience), s.key
        for name, spec in kernel.registry.tools.items():
            assert (page.why_not(spec, policy, s) == "") == (name in offered), (s.key, name)
        offers[s.key] = offered
    # cibles d'intention : sa boîte, pour sa propriétaire en privé seulement ; ses dessins, pour qui a un compte
    assert "email_read" in offers["proprietaire"]
    assert "email_read" not in offers["compte"] and "email_read" not in offers["salon"]
    assert "draw" in offers["compte"] and "draw" not in offers["inconnue"] and "draw" not in offers["salon"]
    assert not any(spec.owner_only for spec in offers["salon"].values())
    # et la page le rend : le lot du courrier, en tête-à-tête avec sa propriétaire
    bootstrap(client)
    text = html_of(client.get(f"{BASE}/qui"))
    assert "email" in text and ("●" in text or "○" in text)


def test_what_she_reads_is_her_prompt(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    spoken = html_of(client.get(f"{BASE}/texte", params={"situation": "proprietaire"}))
    assert ACTING[:40] in spoken and "En main" in spoken
    # un pas de travail : personne ne lit sa parole, la règle de ses mains n'y est pas
    silent = html_of(client.get(f"{BASE}/texte", params={"situation": "pas"}))
    assert ACTING[:40] not in silent


def test_what_mika_serves_is_said(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    text = html_of(client.get(f"{BASE}/expose"))
    assert all(t.name in text for t in CONSOLE_TOOLS)
    assert "mika mcp token" in text and "/mcp/relais" in text
