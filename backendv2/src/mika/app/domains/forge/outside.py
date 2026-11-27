"""Ses apps forgées (ADR 0104, 0219, 0310) : la part de la Forge dans ce qui vient d'ailleurs (``app/me/outside.py``).

Une app a sa famille d'outils (``forge_apps.<app>``) ; l'écran Outils redit, case par case, la ligne de ses accès —
celle de son projet, pour une app d'un projet (``forge_access.resource_allowance``) — et la nomme par son titre.
Réglages › Droits la range sur sa ligne, « App « … » », le détail de ses accès sous celui de son projet
(``project:<n>``), sinon sous le sien (``forge:<app>``), dans le sous-onglet des apps (``tab``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from mika.app.domains.domain import OutsidePart
from mika.contracts import forge as forge_c
from mika.kernel.frame import Audience
from mika.plugins.forge import access as forge_access
from mika.vocab.rights import Allowance


def seen(kernel: Any, frame: Any) -> dict[str, Any]:
    """Ce que la matrice lit une fois de ses apps : chacune, par son nom."""
    return {a.name: a for a in frame.get(forge_c.APPS) or ()}


def tool(apps: Mapping[str, Any], g: Any) -> tuple[str, str]:
    """(l'outil chez elle, sa ressource) d'une ligne d'une app : son nom même."""
    return g.title, g.resource


def allowance(apps: Mapping[str, Any], frame: Any, g: Any, resource: str, tool: str, acts: bool, aud: Audience,
              kind: str, rights: Any, close: Callable[[str], bool] | None) -> Allowance | None:
    """La lecture même de la ligne de son app, ou de son projet (ADR 0219)."""
    return forge_access.resource_allowance(frame, resource, tool, acts, aud, kind)


def name(apps: Mapping[str, Any], resource: str) -> str:
    """Le nom d'une app : son titre quand elle en a un ; une app d'un projet se range sous son projet."""
    kind, _, key = resource.partition(":")
    if kind == "forge":
        app = apps.get(key)
        return f"App « {app.title if app is not None and app.title else key} »"
    return {"project": f"Projet n° {key}"}.get(kind, resource)


def about(apps: Mapping[str, Any], resource: str) -> str:
    """À quoi sert une app, dit à la personne : rien."""
    return ""


def row(frame: Any, name: str) -> tuple[str, str]:
    """Sa ligne dans Réglages › Droits : son titre, et le détail des accès de son projet (une app suit son projet),
    sinon des siens."""
    apps = {a.name: a for a in frame.get(forge_c.APPS)}
    app = apps.get(name)
    detail = f"project:{app.project}" if app is not None and app.project else f"forge:{name}"
    label = (app.title if app is not None and app.title else name)
    return f"App « {label} »", detail


OUTSIDE = OutsidePart("apps", bundle="forge_apps.", title="Apps de la Forge", why="les accès de cette app", seen=seen,
                      tool=tool, allowance=allowance, name=name, about=about, row=row, fiche=("app", "acces"),
                      tab="forge", tab_title="Apps de la Forge",
                      tab_hint="une app suit son projet ; sans projet, ses propres lignes")
