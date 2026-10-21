"""Outils, dessinés (ADR 0121, 0122) : « Ce qu'elle peut faire » et « Venus d'ailleurs ».

« Ce qu'elle peut faire » est une grille, que la console porte dans son panneau (son formulaire, ``outils/peut.html``) :
ses blocs ne servent qu'à qui lit sans panneau (la console en MCP) ; la fiche d'un outil, elle, se dessine bloc par
bloc. « Venus d'ailleurs » réunit ce qui ne vient pas d'elle : les services branchés (la vue du plugin MCP, son
onglet) et les outils que ses apps lui donnent (la vue de la Forge, lue ici sans onglet à elle).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import blocks
from mika.inspector import render
from mika.inspector.ui import UI, Drawn, env
from mika.kernel.inspect import Fields, Ref

#: la vue de la Forge que « Venus d'ailleurs » montre sous les services : (propriétaire, nom)
APP_TOOLS = ("forge", "outils_apps")


class Catalogue(Drawn):
    """Outils › Ce qu'elle peut faire : la grille est le panneau de l'onglet ; la fiche d'un outil (``?outil=``),
    ses blocs dessinés."""

    styles = ("handmade/tools.css",)

    def render(self, ui: UI, items: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        if query.get("outil"):
            return blocks.page(ui, items, query, forms=forms)
        return Markup("")


class Elsewhere(Drawn):
    """Outils › Venus d'ailleurs : ce qu'on y fait (brancher un service, leurs réglages) en boutons, les services
    branchés (les blocs de l'onglet), puis les outils de ses apps."""

    styles = ("handmade/tools.css",)

    def render(self, ui: UI, items: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        links, rest = _buttons(items)
        spec = ui.inspection.find(*APP_TOOLS)
        apps = ui.inspection.run(spec, {}, ui.when) if spec is not None else []
        head = Markup(env.get_template("handmade/outils/ailleurs.html").render(links=links)) if links else Markup("")
        return head + (blocks.page(ui, [*rest, *apps], query, forms=forms) or Markup(""))


def _buttons(items: Sequence[Any]) -> tuple[list[tuple[str, str]], list[Any]]:
    """Le premier bloc, s'il n'est fait que de liens (des champs dont chaque valeur mène ailleurs) : (texte,
    adresse) de chacun, et les autres blocs."""
    first = items[0] if items else None
    if isinstance(first, Fields) and first.pairs and all(isinstance(v, Ref) for _k, v in first.pairs):
        links = [(v.text, render.href(v)) for _k, v in first.pairs]
        if all(href for _t, href in links):
            return links, list(items[1:])
    return [], list(items)
