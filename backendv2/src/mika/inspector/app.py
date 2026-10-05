"""La console : voir ce qu'elle vit, et pourquoi ; décider de ce qui sort.

Rien ici n'est propre à une faculté : chacune déclare ses vues (``@f.inspect``,
rangées par ``section``), ses fiches d'objets, ses actions ; la composition
(``app/console.py``) décide de la carte. Réservé aux opérateurs, formulaires
protégés par jeton, politique de sécurité stricte (ni script ni style en
ligne).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.routing import BaseRoute, Mount
from starlette.staticfiles import StaticFiles

from mika.inspector import catalog
from mika.inspector.catalog import Builtin
from mika.inspector.pages import TABS, reglages
from mika.inspector.pages.routes import Pages
from mika.inspector.pages.settings_form import SettingsForms
from mika.inspector.pages.why import why_page
from mika.inspector.ui import PREFIX, STATIC, UI, InspectorDeps
from mika.kernel.inspect import Param

__all__ = ["ConsolePages", "InspectorDeps", "assemble", "routes"]


class ConsolePages:
    """Les pages de la console sans requête HTTP, pour la console en MCP (``inspector/mcp.py``) : un onglet lu
    avec des paramètres de requête synthétiques, et « pourquoi a-t-elle dit ça ? ». La même ``UI`` que les pages
    (son ``Inspection``, ses noms, son fuseau). Un panneau (un gabarit à formulaires) n'est jamais rendu ici :
    seulement les blocs."""

    def __init__(self, pages: Pages) -> None:
        self.pages = pages
        self.ui = pages.ui

    def tab(self, key: str) -> Builtin | None:
        """Un onglet de la console par sa clé (``systeme.sante``)."""
        return self.ui.builtins.get(key)

    async def read(self, key: str, params: Mapping[str, str]) -> tuple[list[Any], tuple[Param, ...]] | None:
        """Les blocs d'un onglet et ses filtres, comme si on l'ouvrait avec ces paramètres ; ``None`` : aucun
        onglet sous cette clé."""
        item = self.tab(key)
        if item is None:
            return None
        destination, _, slug = key.partition(".")
        scope = {"type": "http", "method": "GET", "path": f"{PREFIX}/{destination}/{slug}", "root_path": "",
                 "query_string": urlencode(dict(params)).encode(), "headers": []}
        got = await self.pages.produce(item, Request(scope))
        return list(got.get("blocks") or []), tuple(got.get("filters") or ())

    def why(self, seq: int) -> dict[str, Any] | None:
        """La page d'une de ses paroles (``pages/why.py``) ; ``None`` si ce numéro n'en est pas une."""
        return why_page(self.ui, seq) if seq > 0 else None


def assemble(deps: InspectorDeps, *, cookie_secure: bool = False) -> tuple[list[BaseRoute], ConsolePages]:
    """Les routes de la console, et ses pages sans requête (ce que sert la console en MCP)."""
    forms = SettingsForms(deps.sections, deps.settings_tabs) if deps.settings_tabs else None
    builtins = {**TABS.items, **(forms.builtins() if forms else {}),
                **reglages.param_builtins(deps.parameters, deps.param_families, deps.faculty_labels)}
    catalog.check(deps.navigation, deps.kernel.registry, builtins)
    ui = UI(deps, builtins, cookie_secure=cookie_secure)
    ui.settings_forms = forms
    pages = Pages(ui)
    return [Mount(PREFIX + "/static", StaticFiles(directory=STATIC), name="console-static"),
            *pages.routes(), *pages.catchall()], ConsolePages(pages)


def routes(deps: InspectorDeps, *, cookie_secure: bool = False) -> list[BaseRoute]:
    return assemble(deps, cookie_secure=cookie_secure)[0]
