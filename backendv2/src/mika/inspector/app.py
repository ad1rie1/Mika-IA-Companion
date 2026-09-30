"""La console : voir ce qu'elle vit, et pourquoi ; décider de ce qui sort.

Rien ici n'est propre à une faculté : chacune déclare ses vues (``@f.inspect``,
rangées par ``section``), ses fiches d'objets, ses actions ; la composition
(``app/console.py``) décide de la carte. Réservé aux opérateurs, formulaires
protégés par jeton, politique de sécurité stricte (ni script ni style en
ligne).
"""

from __future__ import annotations

from starlette.routing import BaseRoute, Mount
from starlette.staticfiles import StaticFiles

from mika.inspector import catalog
from mika.inspector.pages import TABS, reglages
from mika.inspector.pages.routes import Pages
from mika.inspector.pages.settings_form import SettingsForms
from mika.inspector.ui import PREFIX, STATIC, UI, InspectorDeps

__all__ = ["InspectorDeps", "routes"]


def routes(deps: InspectorDeps, *, cookie_secure: bool = False) -> list[BaseRoute]:
    forms = SettingsForms(deps.sections, deps.settings_tabs) if deps.settings_tabs else None
    builtins = {**TABS.items, **(forms.builtins() if forms else {}),
                **reglages.param_builtins(deps.parameters, deps.param_families, deps.faculty_labels)}
    catalog.check(deps.navigation, deps.kernel.registry, builtins)
    ui = UI(deps, builtins, cookie_secure=cookie_secure)
    ui.settings_forms = forms
    pages = Pages(ui)
    return [Mount(PREFIX + "/static", StaticFiles(directory=STATIC), name="console-static"),
            *pages.routes(), *pages.catchall()]
