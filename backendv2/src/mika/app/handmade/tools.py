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

from mika.app.handmade import blocks, columns, reader
from mika.inspector import render
from mika.inspector.ui import UI, Drawn, env
from mika.kernel.inspect import Badge, Fields, Note, Ref, Row, Table, Text, When

#: la vue de la Forge que « Venus d'ailleurs » montre sous les services : (propriétaire, nom)
APP_TOOLS = ("forge", "outils_apps")


class Catalogue(Drawn):
    """Outils › Ce qu'elle peut faire : les tableaux de droits de ses familles sont le panneau de l'onglet
    (``inspector/pages/families.py``, ADR 0134) ; la fiche d'un outil (``?outil=``), ses blocs dessinés."""

    styles = ("handmade/tools.css",)

    def render(self, ui: UI, items: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        if query.get("outil"):
            return blocks.page(ui, items, query, forms=forms)
        return Markup("")


class Elsewhere(Drawn):
    """Outils › Venus d'ailleurs : ce qu'on y fait (brancher un service, leurs réglages) en boutons, une carte par
    service branché (l'onglet du plugin MCP), une carte par app et les outils qu'elle lui donne (la vue de la Forge).
    Lus dans leurs tableaux, par le nom de leurs colonnes ; un tableau qu'il ne reconnaît pas reste tel quel."""

    styles = ("handmade/tools.css",)

    def render(self, ui: UI, items: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        plug = next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == "mcp.brancher"), None)
        if query.get("brancher") and plug is not None:
            # brancher un service : à quoi il sert, comment le joindre (ADR 0128, 0131) — fermé tant qu'aucune ligne
            # d'accès ne l'ouvre
            return Markup(env.get_template("handmade/outils/brancher.html").render(
                form=plug, back=LIST, values={"ou": "local"}))
        links, rest = _buttons(items)
        spec = ui.inspection.find(*APP_TOOLS)
        rest += ui.inspection.run(spec, {}, ui.when) if spec is not None else []
        shown = render.Env(when=ui.when, now=ui.now())
        services = _table(rest, SERVED)
        apps = _table(rest, GIVEN)
        others = [b for b in rest if b is not services and b is not apps]
        html = Markup(env.get_template("handmade/outils/ailleurs.html").render(
            links=links, services=_services(services, shown) if services is not None else None,
            apps=_apps(apps) if apps is not None else None,
            services_empty=services.empty if services is not None else "", apps_empty=apps.empty if apps is not None else ""))
        return html + (blocks.page(ui, others, query, forms=forms) or Markup(""))


#: la page des services branchés (où « Brancher » revient)
LIST = "/inspecteur/outils/serveurs"
#: les colonnes qui font reconnaître les tableaux de la page : les services branchés, les outils de ses apps
SERVED, GIVEN = "outils servis / proposés", "quand il sert"


def _buttons(items: Sequence[Any]) -> tuple[list[tuple[str, str]], list[Any]]:
    """Le premier bloc, s'il n'est fait que de liens (des champs dont chaque valeur mène ailleurs) : (texte,
    adresse) de chacun, et les autres blocs."""
    first = items[0] if items else None
    if isinstance(first, Fields) and first.pairs and all(isinstance(v, Ref) for _k, v in first.pairs):
        links = [(v.text, render.href(v)) for _k, v in first.pairs]
        if all(href for _t, href in links):
            return links, list(items[1:])
    return [], list(items)


def _table(items: Sequence[Any], column: str) -> Table | None:
    return next((b for b in items if isinstance(b, Table) and column in columns(b)), None)


def _text(value: Any) -> str:
    if isinstance(value, Text | Badge | Ref):
        return value.text
    return "" if value in (None, "—") else str(value)


def _services(table: Table, shown: render.Env) -> list[dict[str, Any]]:
    """Une carte par service : son nom, son état, à quoi il lui sert, ses outils servis, ce qui attend ton
    regard, et sa fiche."""
    cell = reader(table)
    out = []
    for raw in table.rows:
        row = raw if isinstance(raw, Row) else Row(tuple(raw))
        state, served, review = cell(row, "état"), _text(cell(row, SERVED)), _text(cell(row, "à revoir"))
        given, _, offered = served.partition("/")
        joined = cell(row, "joint")
        notes = [d.text for d in row.detail if isinstance(d, Note)]
        out.append({
            "name": _text(cell(row, "service")), "href": render.href(row.href) if row.href else "",
            "state": _text(state), "tone": state.tone if isinstance(state, Badge) else "",
            "purpose": _text(cell(row, "à quoi il lui sert")), "where": _text(cell(row, "où")),
            "served": given.strip(), "offered": offered.strip(), "review": int(review) if review.isdigit() else 0,
            "joined": render.cell(joined, shown)["text"] if isinstance(joined, When) else _text(joined),
            "notes": notes, "who": _text(cell(row, "avec qui")), "access": _text(cell(row, "accès")),
        })
    return out


def _apps(table: Table) -> list[dict[str, Any]]:
    """Une carte par app : son titre, quand elle sert, et chacun des outils qu'elle lui donne."""
    cell = reader(table)
    apps: dict[str, dict[str, Any]] = {}
    for raw in table.rows:
        row = raw if isinstance(raw, Row) else Row(tuple(raw))
        name, state = cell(row, "app"), cell(row, GIVEN)
        app = apps.setdefault(_text(name), {
            "title": _text(name), "href": render.href(name) if isinstance(name, Ref) else "",
            "state": _text(state), "tone": state.tone if isinstance(state, Badge) else "", "tools": []})
        app["tools"].append({"name": _text(cell(row, "outil")), "what": _text(cell(row, "ce qu'il fait")),
                             "args": _text(cell(row, "arguments"))})
    return list(apps.values())
