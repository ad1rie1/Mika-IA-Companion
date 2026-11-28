"""L'onglet Fichiers de la fiche d'une personne, dessiné (ADR 0179) : ce qu'on lui a envoyé et ce qu'elle a envoyé,
en deux sous-onglets — les pièces reçues (sa place, puis chaque pièce et ce qu'elle y a lu), les fichiers envoyés.

Deux facultés : ``shares`` (son onglet ``fichiers``) et ``attachments`` (son onglet ``pieces``), que la console
exécute ensemble (``PersonOverview.joined``) et passe en deux sections, la première d'abord. Cette page n'en change
que la forme ; une forme qu'elle ne reconnaît pas rend la main aux blocs des facultés. Chaque fichier encore là porte
« Retirer » (ADR 0205) : l'action de sa faculté (``shares.retirer``, ``attachments.retirer``), le fichier pour objet,
confirmée — ses octets s'effacent, sa ligne reste et le dit (« retiré par un opérateur »).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade.lists import Roles, forms_for, listing, row_keys
from mika.app.handmade.tabs import anchored
from mika.faculties.attachments import inspect as received
from mika.faculties.shares import inspect as sent
from mika.inspector import render
from mika.inspector.ui import UI, env
from mika.kernel.inspect import Fields, Note, Ref, Section, Table

#: les sections, dans l'ordre où la console les passe (l'onglet qui porte l'autre d'abord) : leur onglet (l'ancre
#: de leur sous-onglet), leur nom dans la colonne, la forme de leurs listes
PANES = (("fichiers", "Envoyés", Roles(title="nom", badges=("état",), time="quand", tiles=True)),
         ("pieces", "Reçus", Roles(title="nom", badges=("sorte", "état"), body=("ce qu'elle y a lu",), time="reçue",
                                   tiles=True)))
#: le sous-onglet ouvert d'abord : ce qu'on lui a envoyé
FIRST = "pieces"
#: « Retirer » sur chaque fichier d'un sous-onglet : la sorte de sa fiche, l'action, la question qui la confirme
REMOVALS = {"fichiers": (sent.KIND, sent.REMOVE, sent.removal_question),
            "pieces": (received.KIND, received.REMOVE, received.removal_question)}


def _names(table: Table, kind: str) -> dict[str, str]:
    """Le nom de chaque fichier de la liste (la cellule qui mène à sa fiche), par sa clé."""
    out: dict[str, str] = {}
    for r in table.rows:
        for cell in getattr(r, "cells", ()):
            if isinstance(cell, Ref) and cell.text and cell.key.startswith(f"{kind}/"):
                out.setdefault(cell.key.split("/", 1)[1], cell.text)
    return out


def _removals(ui: UI, anchor: str, table: Table, shaped: dict[str, Any], query: Mapping[str, str],
              forms: Any) -> None:
    """« Retirer » sur la ligne de chaque fichier encore là (``acts`` : le pied de son entrée), confirmé par son nom."""
    kind, action, question = REMOVALS[anchor]
    keys = row_keys(table, kind)
    names = _names(table, kind)
    prepared = forms_for(ui, forms, action, keys, query, title="Retirer", button="Retirer")
    for line, key in zip(shaped["rows"], keys, strict=False):
        if key in prepared:
            line["acts"] = [{**prepared[key], "confirm": question(names.get(key, ""))}]


def files(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
          forms: Mapping[str, Any] | None = None) -> Markup | None:
    if len(blocks) != len(PANES) or not all(isinstance(b, Section) for b in blocks):
        return None  # pas les deux sections attendues (une faculté absente) : les blocs de la console
    shown, name, counter = ui.env(), ui.names.name_of(key), [0]
    panes = []
    for (anchor, label, roles), section in zip(PANES, blocks, strict=True):
        lists = []
        for t in (b for b in section.items if isinstance(b, Table)):
            # une page plus loin rouvre son sous-onglet
            shaped = {**anchored(listing(t, shown, query, name, roles, counter), anchor), "kind": anchor}
            _removals(ui, anchor, t, shaped, query, forms)
            lists.append(shaped)
        panes.append({"id": anchor, "label": label, "count": sum(s["count"] or 0 for s in lists),
                      "facts": [render.block(b, shown, query) for b in section.items if isinstance(b, Fields)],
                      "lists": lists,
                      "notes": [{"text": b.text, "title": b.title, "tone": b.tone} for b in section.items
                                if isinstance(b, Note)]})
    panes.sort(key=lambda p: p["id"] != FIRST)
    return Markup(env.get_template("handmade/person/tabs/fichiers.html").render(panes=panes))
