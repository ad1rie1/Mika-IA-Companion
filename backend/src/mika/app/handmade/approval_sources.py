"""Ce qu'une demande à autoriser concerne, et d'où elle vient (ADR 0177) : le seul lecteur du contexte d'une demande
(``EffectProposed.context``), côté composition — l'inspecteur ne nomme aucun plugin ni aucune faculté. Ce module non
plus (ADR 0310) : ce qu'un contexte dit d'un domaine et la source de ses capacités sont dans sa part de la file
(``QueuePart`` : ``contexts``, ``channels``, ``sources``), qu'il lit au moment de répondre.

- ``about(ui, contexte)`` : ce qu'elle concerne, dit simplement — une personne (son nom), un projet (« projet n° 61 »),
  un service (« service « agenda » »), une app forgée, un canal (« Teams », « courrier », « téléphone » : jamais une
  personne) — et la fiche où ça mène, s'il y en a une. La file, sa demande ouverte et l'historique le disent ainsi
  (``Waiting.about``, par ``InspectorDeps.queue``).
- ``sources(ui, capacité, contexte, arguments)`` : sa source en liens, du plus proche au plus large — la boîte et le
  brouillon d'un mail, la conversation et la réponse préparée d'une réponse Teams, l'agenda et sa semaine d'une
  écriture d'agenda (ADR 0309), puis ce que dit son contexte (le
  service, l'app, le projet, la fiche de la personne et leur conversation) ; ``InspectorDeps.approval_sources``.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mika.app.domains import DOMAINS, QueuePart, part
from mika.app.handmade import person_href
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI
from mika.vocab.words import elided

#: les sortes de ce qu'une demande concerne que le cadre dit lui-même : une personne, un canal (celles d'un domaine —
#: un service, une app, un projet — sont dites par sa part de la file)
PERSON, CHANNEL = "personne", "canal"


@functools.cache
def queues() -> tuple[QueuePart, ...]:
    """La part de chaque domaine dans la file, dans l'ordre des fiches. Lue à la demande, une fois : la part d'un
    domaine importe ce module (``Concern``, ``arg``), qui ne peut donc pas importer la sienne en naissant."""
    consoles = (part(d.console, "CONSOLE") for d in DOMAINS if d.console is not None)
    return tuple(console.queue for console in consoles if console.queue is not None)


@dataclass(frozen=True, slots=True)
class Concern:
    """Ce qu'une demande concerne, lu dans son contexte : sa sorte, ce qu'on en dit (« projet n° 61 »), son nom seul
    (« 61 », « agenda », « Adrien »), sa fiche (vide : aucune), la personne derrière (une personne seulement), et le
    texte du lien vers sa fiche parmi les sources de la demande (« Le projet n° 61 » : ce que dit son domaine)."""

    kind: str
    text: str
    name: str = ""
    href: str = ""
    person: str = ""
    link: str = ""


def concern(ui: UI, context: str) -> Concern | None:
    """Ce qu'une demande concerne (``None`` : son contexte est vide)."""
    if not context:
        return None
    head, _, rest = context.partition(":")
    for queue in queues():  # le préfixe d'un domaine (``mcp:agenda``, ``forge:meteo``, ``project:61``)
        read = queue.contexts.get(head) if rest else None
        got: Concern | None = read(ui, rest) if read is not None else None
        if got is not None:
            return got
    for queue in queues():  # un canal qui pose son nom (``teams``, ``email``, ``phone``) : jamais une personne
        if context in queue.channels:
            return Concern(CHANNEL, queue.channels[context])
    name = ui.names.name_of(context) or ui.names.who(context).removeprefix("le ")
    person = ui.names.person_of(context)
    href = person_href(person)
    return Concern(PERSON, name, name, href, person) if href else Concern("", name, name)


def about(ui: UI, context: str) -> tuple[str, str | None]:
    """Ce qu'une demande concerne, dit simplement, et la fiche où ça mène (``None`` : aucune)."""
    got = concern(ui, context)
    return ("", None) if got is None else (got.text, got.href or None)


def arg(args: Mapping[str, Any], name: str) -> str:
    """Un argument d'une demande, en texte (vide : absent, ou ni un texte ni un nombre)."""
    value = args.get(name)
    return str(value) if isinstance(value, str | int) and str(value) else ""


def sources(ui: UI, capability: str, context: str, args: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Les liens vers la source d'une demande (texte, adresse), du plus proche au plus large : ceux de sa capacité, que
    dit son domaine, puis ce que dit son contexte."""
    out: list[tuple[str, str]] = []
    for queue in queues():
        if capability in queue.sources:
            out += queue.sources[capability](ui, args)
            break
    got = concern(ui, context)
    if got is None or not got.href:  # un canal n'a pas de fiche : ses liens sont ceux de sa capacité
        return out
    if got.kind == PERSON:
        out.append((f"La fiche {elided(got.name, 'de')}", got.href))
        out.append(("Leur conversation", subject_url("person", got.person, "echanges")))
    elif got.link:  # la fiche de ce que dit un domaine : son service, son app, son projet
        out.append((got.link, got.href))
    return out
