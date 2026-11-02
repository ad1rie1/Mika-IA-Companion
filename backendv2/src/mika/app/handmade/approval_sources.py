"""D'où vient une demande à autoriser (ADR 0177), en liens vers sa source : la boîte et le brouillon d'un mail, la
conversation et la réponse préparée d'une réponse Teams, le service d'un appel MCP, l'app forgée, le projet, la
personne et sa conversation. La composition les fournit à la console (``InspectorDeps.approval_sources``) : l'inspecteur
ne nomme aucun plugin ni aucune faculté.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from mika.app.handmade import person_href
from mika.app.handmade.mail_fiches import DRAFT
from mika.app.handmade.servers import KIND as SERVER
from mika.app.handmade.teams_fiches import CONVERSATION, REPLY
from mika.contracts import email as email_c
from mika.contracts import teams as teams_c
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import PREFIX, UI
from mika.vocab.episodes import project_of
from mika.vocab.people import is_identifiable

#: la fiche d'une app forgée
APP = "app"


def _arg(args: Mapping[str, Any], name: str) -> str:
    value = args.get(name)
    return str(value) if isinstance(value, str | int) and str(value) else ""


def sources(ui: UI, capability: str, context: str, args: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Les liens vers la source d'une demande (texte, adresse), du plus proche au plus large."""
    out: list[tuple[str, str]] = []
    if capability == email_c.SEND:
        if draft := _arg(args, "draft"):
            out.append(("Le brouillon", fiche_url(DRAFT, draft)))
        if account := _arg(args, "account"):
            out.append((f"La boîte « {account} »", f"{PREFIX}/courrier/reception?" + urlencode({"compte": account})))
    elif capability == teams_c.SEND:
        if draft := _arg(args, "draft"):
            out.append(("La réponse préparée", fiche_url(REPLY, draft)))
        if conversation := _arg(args, "conversation"):
            out.append(("La conversation Teams", fiche_url(CONVERSATION, conversation)))
    head, _, rest = context.partition(":")
    if head == "mcp" and rest:
        out.append((f"Le service « {rest} »", fiche_url(SERVER, rest)))
    elif head == "forge" and rest:
        out.append((f"L'app « {rest} »", fiche_url(APP, rest)))
    elif (project := project_of(context)) is not None:
        out.append((f"Le projet n° {project}", fiche_url("project", str(project))))
    elif context and is_identifiable(person := ui.names.person_of(context)):
        name = ui.names.name_of(context) or ui.names.who(context)
        out.append((f"La fiche de {name}", person_href(person)))
        out.append(("Leur conversation", fiche_url("person", person, "echanges")))
    return out
