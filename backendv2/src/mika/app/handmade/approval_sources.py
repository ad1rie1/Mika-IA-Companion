"""Ce qu'une demande à autoriser concerne, et d'où elle vient (ADR 0177) : le seul lecteur du contexte d'une demande
(``EffectProposed.context``), côté composition — l'inspecteur ne nomme aucun plugin ni aucune faculté.

- ``about(ui, contexte)`` : ce qu'elle concerne, dit simplement — une personne (son nom), un projet (« projet n° 61 »),
  un service (« service « agenda » »), une app forgée, un canal (« Teams », « courrier », « téléphone » : jamais une
  personne) — et la fiche où ça mène, s'il y en a une. La file, sa demande ouverte et l'historique le disent ainsi
  (``Waiting.about``, par ``InspectorDeps.queue``).
- ``sources(ui, capacité, contexte, arguments)`` : sa source en liens, du plus proche au plus large — la boîte et le
  brouillon d'un mail, la conversation et la réponse préparée d'une réponse Teams, puis ce que dit son contexte (le
  service, l'app, le projet, la fiche de la personne et leur conversation) ; ``InspectorDeps.approval_sources``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from mika.app.handmade import person_href
from mika.app.handmade.mail_fiches import DRAFT
from mika.app.handmade.servers import KIND as SERVER
from mika.app.handmade.teams_fiches import CONVERSATION, REPLY
from mika.contracts import email as email_c
from mika.contracts import phone as phone_c
from mika.contracts import teams as teams_c
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import PREFIX, UI
from mika.ports.teams import DEFAULT_ACCOUNT as DEFAULT_TEAMS_ACCOUNT
from mika.ports.teams import conversation_key
from mika.vocab.episodes import project_of
from mika.vocab.words import elided

#: la fiche d'une app forgée
APP = "app"
#: les sortes de ce qu'une demande concerne
PERSON, PROJECT, SERVICE, FORGED, CHANNEL = "personne", "projet", "service", "app", "canal"
#: le préfixe du contexte d'un appel à un service MCP, d'une app forgée (``mcp:agenda``, ``forge:meteo``)
PREFIXES = {"mcp": SERVICE, "forge": FORGED}
#: les canaux qui posent leur nom en contexte (``teams``, ``email``, ``phone``) : jamais une personne
CHANNELS = {teams_c.OWNER: "Teams", email_c.OWNER: "courrier", phone_c.OWNER: "téléphone"}


@dataclass(frozen=True, slots=True)
class Concern:
    """Ce qu'une demande concerne, lu dans son contexte : sa sorte, ce qu'on en dit (« projet n° 61 »), son nom seul
    (« 61 », « agenda », « Adrien »), sa fiche (vide : aucune), et la personne derrière (une personne seulement)."""

    kind: str
    text: str
    name: str = ""
    href: str = ""
    person: str = ""


def concern(ui: UI, context: str) -> Concern | None:
    """Ce qu'une demande concerne (``None`` : son contexte est vide)."""
    if not context:
        return None
    head, _, rest = context.partition(":")
    kind = PREFIXES.get(head) if rest else None
    if kind == SERVICE:
        return Concern(SERVICE, f"service « {rest} »", rest, fiche_url(SERVER, rest))
    if kind == FORGED:
        return Concern(FORGED, f"app « {rest} »", rest, fiche_url(APP, rest))
    if (project := project_of(context)) is not None:
        return Concern(PROJECT, f"projet n° {project}", str(project), fiche_url("project", str(project)))
    if context in CHANNELS:
        return Concern(CHANNEL, CHANNELS[context])
    name = ui.names.name_of(context) or ui.names.who(context).removeprefix("le ")
    person = ui.names.person_of(context)
    href = person_href(person)
    return Concern(PERSON, name, name, href, person) if href else Concern("", name, name)


def about(ui: UI, context: str) -> tuple[str, str | None]:
    """Ce qu'une demande concerne, dit simplement, et la fiche où ça mène (``None`` : aucune)."""
    got = concern(ui, context)
    return ("", None) if got is None else (got.text, got.href or None)


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
            key = conversation_key(_arg(args, "account") or DEFAULT_TEAMS_ACCOUNT, conversation)
            out.append(("La conversation Teams", fiche_url(CONVERSATION, key)))
    got = concern(ui, context)
    if got is None or not got.href:  # un canal n'a pas de fiche : ses liens sont ceux de sa capacité
        return out
    if got.kind == SERVICE:
        out.append((f"Le service « {got.name} »", got.href))
    elif got.kind == FORGED:
        out.append((f"L'app « {got.name} »", got.href))
    elif got.kind == PROJECT:
        out.append((f"Le projet n° {got.name}", got.href))
    elif got.kind == PERSON:
        out.append((f"La fiche {elided(got.name, 'de')}", got.href))
        out.append(("Leur conversation", fiche_url("person", got.person, "echanges")))
    return out
