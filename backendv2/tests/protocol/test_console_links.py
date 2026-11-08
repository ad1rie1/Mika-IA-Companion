"""Les adresses de la console mènent quelque part (K11-01, audit du 2026-11-05) : la fiche d'un compte Teams envoyait
vers « /inspecteur/envoi », une page fondue dans les canaux depuis l'ADR 0134 — « Page inconnue », 404. Chaque lien
d'une fiche se suit, et chaque adresse de la console écrite en toutes lettres dans le code répond autre chose que 404."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from mika.runtime import operations
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_teams import plugged
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

SRC = Path(operations.__file__).resolve().parents[1]
#: une adresse de la console écrite en entier (sans paramètre ni morceau calculé)
ADDRESS = re.compile(r"/inspecteur(/[a-z0-9_-]+)+")


def _content_links(page: str) -> set[str]:
    """Les liens de la console dans le contenu de la page (le menu, commun à toutes, est à part)."""
    main = page[page.index("<main"):]
    return {href for href in re.findall(r'href="(/inspecteur/[^"#]*)"', main)}


def test_every_link_of_a_teams_account_fiche_leads_somewhere(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    links = _content_links(drawn(client, "/inspecteur/teams/extension?compte=principal"))
    # comment partent ses réponses : le tableau de canal de ce compte (« teams:<clé> »), comme pour une boîte
    assert "/inspecteur/reglages/canaux?canal=teams%3Aprincipal" in links
    dead = sorted(href for href in links if client.get(href, follow_redirects=False).status_code == 404)
    assert not dead, dead


def _written_addresses() -> dict[str, str]:
    """Les adresses de la console écrites en toutes lettres dans le code (hors des f-strings), et où."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parts = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in parts
                    and ADDRESS.fullmatch(node.value)):
                found.setdefault(node.value, f"{path.relative_to(SRC)}:{node.lineno}")
    return found


def test_every_written_console_address_leads_somewhere(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    written = _written_addresses()
    assert len(written) > 20  # la recherche trouve bien les adresses du code
    dead = sorted(f"{address} ({where})" for address, where in written.items()
                  if client.get(address, follow_redirects=False).status_code == 404)
    assert not dead, dead
