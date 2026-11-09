"""Outils : ses onglets, chacun dans sa forme (ADR 0121, 0122, 0177).

- Ce qu'elle peut faire : la page des tableaux de droits de ses familles, que la console porte dans son panneau
  (``droits/familles.html``, ``inspector/pages/families.py``, ADR 0134) ; ses blocs ne servent qu'à qui lit sans panneau
  (la console en MCP). La fiche d'un outil (``?outil=``), elle, se dessine bloc par bloc.
- Venus d'ailleurs : ce qui ne vient pas d'elle — les services branchés (la vue du plugin MCP, son onglet), une carte
  par service, et les outils que ses apps lui donnent (la vue de la Forge, lue ici sans onglet à elle), une carte par
  app. Ce qu'on y fait (brancher un service), en bouton de la barre de titre ; leurs réglages sont derrière la roue de
  Ses outils (ADR 0206). Lus dans leurs tableaux déclarés ; un tableau qu'il ne reconnaît pas reste tel quel.
- Prêter à un agent : la page est son panneau, déjà dessiné (``handmade/outils/expose.html`` : la console en lecture,
  ses points de prêt, le relais du moteur Claude Code) ; la vue n'a pas de blocs. L'onglet garde ce panneau, charge sa
  feuille (``handmade/tools.css``) et pose sa marque, rien de plus.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import blocks, plain
from mika.app.handmade.tabs import Got, Tab, raw_rows, raw_table
from mika.inspector import render
from mika.inspector.ui import env
from mika.kernel.inspect import Badge, Fields, Nav, Note, Ref, Table, When

STYLES = ("handmade/tools.css",)
#: la vue de la Forge que « Venus d'ailleurs » montre sous les services : (propriétaire, nom)
APP_TOOLS = ("forge", "outils_apps")
#: la vue des services branchés (où « Brancher » revient)
SERVICES = ("mcp", "serveurs")
#: les tableaux de la page, par leur titre : les services branchés, les outils de ses apps
SERVED_TABLE, GIVEN_TABLE = "Les services branchés", "Les outils de ses apps"
#: les colonnes qu'elle lit : les outils servis d'un service, l'état d'une app
SERVED, GIVEN = "outils servis / proposés", "quand il sert"
#: le choix de qui sont les services montrés (``plugins/mcp/console.py``)
OWNERS = "À qui"


# ── Ce qu'elle peut faire ─────────────────────────────────────────────────


def catalogue(got: Got) -> Markup | None:
    """Outils › Ce qu'elle peut faire : les tableaux de droits de ses familles sont le panneau de l'onglet
    (``inspector/pages/families.py``, ADR 0134) ; la fiche d'un outil (``?outil=``), ses blocs dessinés."""
    if got.query.get("outil"):
        return blocks.page(got.ui, got.raw, got.query, forms=got.forms)
    return Markup("")


# ── Venus d'ailleurs ──────────────────────────────────────────────────────


def elsewhere(got: Got) -> Any:
    """Outils › Venus d'ailleurs : ce qu'on y fait (brancher un service) en bouton de la barre de titre — leurs
    réglages sont derrière la roue de Ses outils (ADR 0206) —, une carte par service branché (l'onglet du plugin MCP),
    une carte par app et les outils qu'elle lui donne (la vue de la Forge). Lus dans leurs tableaux ; un tableau qu'il ne
    reconnaît pas reste tel quel."""
    ui, query, forms = got.ui, got.query, got.forms
    shown = ui.env(ui.when)
    plug = next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == "mcp.brancher"), None)
    if query.get("brancher") and plug is not None:
        # brancher un service : à quoi il sert, comment le joindre (ADR 0128, 0131) — fermé tant qu'aucune ligne
        # d'accès ne l'ouvre
        return Markup(env.get_template("handmade/outils/brancher.html").render(
            form=plug, back=render.href(Ref.view(*SERVICES, ""), shown), values={"ou": "local"}))
    links, rest = _buttons(got.raw, shown)
    spec = ui.inspection.find(*APP_TOOLS)
    rest += ui.inspection.run(spec, {}, ui.when) if spec is not None else []
    services = raw_table(rest, SERVED_TABLE)
    apps = raw_table(rest, GIVEN_TABLE)
    # « À qui » (ADR 0192) : un bouton à choix en tête des services, quand plusieurs personnes en ont branché
    owners = next((b for b in rest if isinstance(b, Nav) and b.title == OWNERS), None)
    others = [b for b in rest if b is not services and b is not apps and b is not owners]
    html = Markup(env.get_template("handmade/outils/ailleurs.html").render(
        owners=[{"text": i.text, "href": render.href(i.href, shown), "on": i.active} for i in owners.items]
        if owners is not None else [],
        services=_services(services, shown) if services is not None else None,
        apps=_apps(apps, shown) if apps is not None else None,
        services_empty=services.empty if services is not None else "", apps_empty=apps.empty if apps is not None else ""))
    # brancher un service : l'action de la page, dans sa barre de titre (ADR 0176) ; la roue la ferme
    return html + (blocks.page(ui, others, query, forms=forms) or Markup("")), [], blocks.head(links)


def _buttons(items: Sequence[Any], shown: render.Env) -> tuple[list[tuple[str, str]], list[Any]]:
    """Le premier bloc, s'il n'est fait que de liens (des champs dont chaque valeur mène ailleurs) : (texte,
    adresse) de chacun, et les autres blocs."""
    first = items[0] if items else None
    if isinstance(first, Fields) and first.pairs and all(isinstance(v, Ref) for _k, v in first.pairs):
        links = [(v.text, render.href(v, shown)) for _k, v in first.pairs]
        if all(href for _t, href in links):
            return links, list(items[1:])
    return [], list(items)


def _services(table: Table, shown: render.Env) -> list[dict[str, Any]]:
    """Une carte par service : son nom, son état, à quoi il lui sert, ses outils servis, ce qui attend ton
    regard, et sa fiche."""
    out = []
    for row, cell in raw_rows(table):
        state, served, review = cell.get("état"), plain(cell.get(SERVED)), plain(cell.get("à revoir"))
        given, _, offered = served.partition("/")
        joined = cell.get("joint")
        notes = [d.text for d in row.detail if isinstance(d, Note)]
        owner = cell.get("à qui")
        out.append({
            "name": plain(cell.get("service")), "href": render.href(row.href, shown) if row.href else "",
            "owner": plain(owner), "owner_href": render.href(owner, shown) if isinstance(owner, Ref) else "",
            "state": plain(state), "tone": state.tone if isinstance(state, Badge) else "",
            "purpose": plain(cell.get("à quoi il lui sert")), "where": plain(cell.get("où")),
            "served": given.strip(), "offered": offered.strip(), "review": int(review) if review.isdigit() else 0,
            "joined": render.cell(joined, shown)["text"] if isinstance(joined, When) else plain(joined),
            "notes": notes, "who": plain(cell.get("avec qui")), "access": plain(cell.get("accès")),
        })
    return out


def _apps(table: Table, shown: render.Env) -> list[dict[str, Any]]:
    """Une carte par app : son titre, quand elle sert, et chacun des outils qu'elle lui donne."""
    apps: dict[str, dict[str, Any]] = {}
    for _row, cell in raw_rows(table):
        name, state = cell.get("app"), cell.get(GIVEN)
        app = apps.setdefault(plain(name), {
            "title": plain(name), "href": render.href(name, shown) if isinstance(name, Ref) else "",
            "state": plain(state), "tone": state.tone if isinstance(state, Badge) else "", "tools": []})
        app["tools"].append({"name": plain(cell.get("outil")), "what": plain(cell.get("ce qu'il fait")),
                             "args": plain(cell.get("arguments"))})
    return list(apps.values())


# ── Prêter à un agent ─────────────────────────────────────────────────────


def expose(got: Got) -> Markup:
    """Prêter à un agent : le panneau dit tout ; la marque de l'onglet, vide."""
    return got.draw("handmade/outils/preter.html")


TABS: dict[str, Any] = {
    "outils/tous": Tab(catalogue, *STYLES),
    "outils/serveurs": Tab(elsewhere, *STYLES),
    "outils/expose": Tab(expose, *STYLES),
}
