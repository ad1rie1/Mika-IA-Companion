"""Un onglet d'une faculté, dessiné bloc par bloc (ADR 0121) : le rendu de tout onglet dessiné qui n'a pas de forme
à lui — le détail d'une personne (Synthèse, Lien, Affect…), une page de la console — dans le vocabulaire des pages
dessinées.

Chaque bloc que la faculté déclare garde son contenu et prend une forme : des chiffres en tuiles, des faits en
grille, une liste en cartes, une chronologie en fil, une note, un texte, une courbe, un repli, un espace de travail
(sa navigation à côté). Un formulaire se dessine à sa place avec ce que la console a préparé (``Forms`` : son jeton,
ses champs).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade.lists import shaped
from mika.inspector import render
from mika.inspector.ui import UI, env


def shape(d: dict[str, Any], name: str = "") -> dict[str, Any]:
    """Un bloc rendu par la console, ses listes prêtes pour une carte (et celles qu'il contient)."""
    if d.get("t") == "table":
        return shaped(d, name)
    if d.get("t") in ("disclosure", "grid", "section", "toolbar"):
        return {**d, "items": [shape(x, name) for x in d.get("items", [])]}
    if d.get("t") == "workspace":
        return {**d, "sidebar": [shape(x, name) for x in d.get("sidebar", [])],
                "items": [shape(x, name) for x in d.get("items", [])]}
    return d


def tab(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
        forms: Mapping[str, Any] | None = None) -> Markup | None:
    """Un onglet de la fiche d'un objet (``key``) : son nom se tait dans ses listes."""
    return page(ui, blocks, query, ui.names.name_of(key) if key else "", forms=forms)


def page(ui: UI, blocks: Sequence[Any], query: Mapping[str, str], name: str = "", tables: str = "cards",
         forms: Mapping[str, Any] | None = None) -> Markup | None:
    """Des blocs dessinés ; ``None`` : rien à dessiner. ``forms`` : les formulaires que la console a préparés pour
    leurs actions (par emplacement, avec leur jeton) ; sans eux, une action dit qu'elle n'est pas déclarée ici.
    ``tables`` : une liste en cartes (``cards``), ou en tableau sobre (``table`` : des données d'exploitation, plus
    lisibles en colonnes)."""
    if not blocks:
        return None
    # numérotées comme la console les numérote sur toute la page : leur ancre, leur pagination, « vue_… »
    drawn = [shape(d, name) for d in render.blocks(blocks, ui.env(), query)]
    return Markup(env.get_template("handmade/shared/blocks.html").render(blocks=drawn, tables=tables,
                                                                        forms=forms or {}))
