"""Ses outils venus d'ailleurs sur la fiche d'une personne (ADR 0192, 0310) : les services qu'elle a branchés depuis
son espace, en sous-onglet de Comptes (``PersonPart.owned`` ; l'onglet est dessiné par la fiche,
``app/handmade/person/``, et son gabarit, ``handmade/person/tabs/comptes.html``, reste dans l'inspecteur).
"""

from __future__ import annotations

from typing import Any

from mika.adapters.mcp.config import TRANSPORTS
from mika.app.domains.domain import PersonPart
from mika.app.domains.tools.settings import ToolsSettings
from mika.app.domains.tools.sharing import service_shares
from mika.app.handmade import Look, excerpt
from mika.app.handmade.person.common import Who, share_person
from mika.inspector.pages.subjects import subject_url
from mika.vocab.access import PERSON


def services(look: Look, who: Who) -> list[dict[str, Any]]:
    """Les services MCP qu'elle a branchés depuis son espace (ADR 0192 : ``McpServer.owner``), lus dans les réglages :
    chacun, à quoi il sert, s'il est actif, avec qui elle le partage."""
    settings = look.ui.deps.settings
    if settings is None:
        return []
    mine = PERSON + who.person
    return [{"name": name, "href": subject_url("serveur", name), "purpose": excerpt(spec.purpose, 200),
             "on": spec.enabled, "where": dict(TRANSPORTS).get(spec.transport, spec.transport),
             "shared": [share_person(look, p, level) for p, level in sorted(service_shares(spec).items())]}
            for name, spec in sorted(settings.of(ToolsSettings).mcp().servers.items()) if spec.owner == mine]


PERSON_PART = PersonPart(owned=("services", "Services", services))
