"""L'onglet Fichiers de la fiche d'une personne, dessiné (ADR 0179) : ce qu'on lui a envoyé et ce qu'elle a envoyé,
en deux sous-onglets — les pièces reçues (sa place, puis chaque pièce et ce qu'elle y a lu), les fichiers envoyés.

Deux facultés : ``shares`` (son onglet ``fichiers``) et ``attachments`` (son onglet ``pieces``), que la console
exécute ensemble (``PersonOverview.joined``) et passe en deux sections, la première d'abord. Cette page n'en change
que la forme ; une forme qu'elle ne reconnaît pas rend la main aux blocs des facultés.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade.lists import Roles, listing
from mika.app.handmade.tabs import anchored
from mika.inspector import render
from mika.inspector.ui import UI, env
from mika.kernel.inspect import Fields, Note, Section, Table

#: les sections, dans l'ordre où la console les passe (l'onglet qui porte l'autre d'abord) : leur onglet (l'ancre
#: de leur sous-onglet), leur nom dans la colonne, la forme de leurs listes
PANES = (("fichiers", "Envoyés", Roles(title="nom", badges=("état",), time="quand", tiles=True)),
         ("pieces", "Reçus", Roles(title="nom", badges=("sorte", "état"), body=("ce qu'elle y a lu",), time="reçue",
                                   tiles=True)))
#: le sous-onglet ouvert d'abord : ce qu'on lui a envoyé
FIRST = "pieces"


def files(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    if len(blocks) != len(PANES) or not all(isinstance(b, Section) for b in blocks):
        return None  # pas les deux sections attendues (une faculté absente) : les blocs de la console
    shown, name, counter = ui.env(), ui.names.name_of(key), [0]
    panes = []
    for (anchor, label, roles), section in zip(PANES, blocks, strict=True):
        lists = []
        for t in (b for b in section.items if isinstance(b, Table)):
            # une page plus loin rouvre son sous-onglet
            lists.append({**anchored(listing(t, shown, query, name, roles, counter), anchor), "kind": anchor})
        panes.append({"id": anchor, "label": label, "count": sum(s["count"] or 0 for s in lists),
                      "facts": [render.block(b, shown, query) for b in section.items if isinstance(b, Fields)],
                      "lists": lists,
                      "notes": [{"text": b.text, "title": b.title, "tone": b.tone} for b in section.items
                                if isinstance(b, Note)]})
    panes.sort(key=lambda p: p["id"] != FIRST)
    return Markup(env.get_template("handmade/person/tabs/fichiers.html").render(panes=panes))
