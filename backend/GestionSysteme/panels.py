"""Espaces de modules — le contrat par lequel un greffon expose une interface.

**Ce qui change par rapport à l'ancien système.**

Avant, un module déclarait des ``ModuleView`` dont le ``data_handler``
renvoyait du JSON, rendu dans le navigateur par un script générique qui
l'injectait via ``innerHTML``. Deux conséquences :

1. Un module qui faisait transiter un corps d'e-mail, un article RSS ou une
   page aspirée par une clé ``html`` obtenait du XSS stocké sur l'interface
   d'administration — celle qui édite les clés d'API. Il a fallu écrire
   ``dashboard/sanitize.py`` pour retirer ``html``/``js``/``template`` de
   *toutes* les charges utiles, avec ``allow_raw_html`` comme dérogation.
2. Chaque module obtenait des **pages éparpillées** dans le menu global, sans
   endroit où voir sa configuration, son état et ses données ensemble.

Ici :

- Un gestionnaire renvoie des **blocs typés** (``Table``, ``Fields``,
  ``Stats``, ``Note``) composés de **cellules typées**. Un module déclare une
  *intention* (« ceci est un badge d'alerte », « ceci est une jauge »), jamais
  du balisage. Le rendu est fait par les gabarits de GestionSystème, avec
  l'échappement automatique de Django. Il n'y a plus rien à assainir : la
  classe de vulnérabilité a disparu au lieu d'être filtrée.
- L'échappatoire légitime reste ``Template`` : le module fournit son propre
  gabarit Django. C'est du code qu'il possède, pas une donnée qu'il relaie, et
  il passe quand même par le moteur de gabarits.
- Chaque module reçoit un **espace** : ses panneaux, sa configuration et son
  état au même endroit, sous ``/gestion/modules/<nom>/``.

La compatibilité est assurée : un module qui déclare encore ``get_views()``
est adapté automatiquement (voir ``_adapt_legacy_view``). Rien à réécrire pour
qu'un greffon existant continue d'apparaître.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  Cellules — l'unité de rendu
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Cell:
    """Une cellule de tableau, décrite par son intention.

    ``kind`` choisit le rendu ; le gabarit ne lit jamais autre chose. Un
    ``kind`` inconnu retombe sur ``text``, donc un module qui invente une
    valeur obtient du texte échappé, pas une page cassée.
    """
    text: str = ""
    kind: str = "text"        # text | mono | num | badge | emotion | link | meter | bool | muted
    href: str = ""
    tone: str = ""            # "" | ok | warn | danger | info
    title: str = ""           # infobulle (valeur exacte, date absolue…)
    ratio: float | None = None
    emotion: str = ""
    clamp: bool = False       # borne un texte long à 3 lignes

    @property
    def render_kind(self) -> str:
        return self.kind if self.kind in _CELL_KINDS else "text"


_CELL_KINDS = frozenset({
    "text", "mono", "num", "badge", "emotion", "link", "meter", "bool", "muted",
})


def text(value: Any, *, title: str = "", clamp: bool = False) -> Cell:
    return Cell(text=_str(value), title=title, clamp=clamp)


def muted(value: Any) -> Cell:
    return Cell(text=_str(value), kind="muted")


def mono(value: Any, *, title: str = "") -> Cell:
    return Cell(text=_str(value), kind="mono", title=title)


def num(value: Any, *, title: str = "") -> Cell:
    return Cell(text=_str(value), kind="num", title=title)


def badge(value: Any, *, tone: str = "") -> Cell:
    return Cell(text=_str(value), kind="badge", tone=_tone(tone))


def link(value: Any, href: str, *, title: str = "") -> Cell:
    return Cell(text=_str(value), kind="link", href=href, title=title)


def emotion(name: str, *, weight: float | None = None) -> Cell:
    return Cell(text=_str(name), kind="emotion", emotion=_str(name), ratio=weight)


def meter(ratio: float | None, *, label: str = "", tone: str = "") -> Cell:
    return Cell(
        text=label, kind="meter", ratio=_ratio(ratio), tone=_tone(tone),
    )


def boolean(value: Any, *, yes: str = "oui", no: str = "non") -> Cell:
    return Cell(text=yes if value else no, kind="bool",
                tone="ok" if value else "")


def _str(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "oui" if value else "non"
    return str(value)


def _tone(value: str) -> str:
    return value if value in ("ok", "warn", "danger", "info") else ""


def _ratio(value) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════
#  Blocs
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Column:
    label: str
    align: str = ""      # "" | num | fit
    hint: str = ""


@dataclass(frozen=True)
class Row:
    cells: tuple[Cell, ...]
    href: str = ""       # rend la ligne cliquable vers une fiche
    tone: str = ""


@dataclass
class Table:
    """Un tableau. ``page`` porte la pagination si le module en fournit une."""
    columns: Sequence[Column]
    rows: Sequence[Row]
    page: Any = None                 # tables.PageResult | None
    empty: str = "Rien à afficher."
    caption: str = ""
    block = "table"


@dataclass(frozen=True)
class Field:
    label: str
    value: str = ""
    kind: str = "text"
    tone: str = ""
    href: str = ""

    @property
    def render_kind(self) -> str:
        return self.kind if self.kind in _CELL_KINDS else "text"


@dataclass
class Fields:
    """Liste clé/valeur — fiche de détail, résumé d'état."""
    items: Sequence[Field]
    title: str = ""
    block = "fields"


@dataclass(frozen=True)
class Stat:
    label: str
    value: str
    sub: str = ""
    tone: str = ""


@dataclass
class Stats:
    items: Sequence[Stat]
    title: str = ""
    block = "stats"


@dataclass
class Note:
    """Message encadré — explication, avertissement, erreur."""
    text: str
    tone: str = "info"    # info | ok | warn | danger
    title: str = ""
    block = "note"


@dataclass
class Prose:
    """Bloc de texte long (narratif, journal, corps de message)."""
    text: str
    title: str = ""
    block = "prose"


@dataclass
class Template:
    """Gabarit Django fourni par le module.

    Résolu depuis ``modules/plugins/<nom>/templates/``. C'est l'échappatoire
    assumée : le module écrit son propre balisage, mais via le moteur de
    gabarits — donc échappé par défaut, et versionné avec son code plutôt
    qu'assemblé à l'exécution à partir de données.
    """
    name: str
    context: dict = field(default_factory=dict)
    block = "template"


@dataclass
class Blocks:
    """Composition — plusieurs blocs dans un même panneau."""
    items: Sequence[Any]
    block = "blocks"


BLOCK_TYPES = (Table, Fields, Stats, Note, Prose, Template, Blocks)


# ══════════════════════════════════════════════════════════════════════
#  Panneaux et actions
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PanelAction:
    """Bouton d'action dans un panneau.

    Toujours servi en POST derrière un formulaire protégé par CSRF — pas de
    lien GET destructeur, qu'un préchargement de navigateur suffirait à
    déclencher.
    """
    key: str
    label: str
    handler: Callable                 # (request) -> str | Note | None
    confirm: str = ""
    danger: bool = False


@dataclass(frozen=True)
class ModulePanel:
    """Une page dans l'espace d'un module.

    ``handler`` reçoit la ``request`` et renvoie un bloc (ou ``Blocks``).
    Synchrone ou asynchrone, au choix du module.
    """
    key: str
    label: str
    icon: str = "▦"
    order: int = 100
    handler: Callable | None = None
    description: str = ""
    actions: tuple[PanelAction, ...] = ()


@dataclass(frozen=True)
class ModuleSpaceInfo:
    """Ce que la coquille doit savoir d'un espace pour l'afficher au menu."""
    name: str
    label: str
    icon: str
    running: bool
    enabled: bool
    panel_count: int
    has_config: bool


# ══════════════════════════════════════════════════════════════════════
#  Découverte
# ══════════════════════════════════════════════════════════════════════

# Modules d'infrastructure : ils n'existent que pour exposer des outils MCP
# au-dessus de sous-systèmes que le cycle de vie ASGI possède déjà. Leur
# donner un espace afficherait des coquilles vides dans le menu.
def _is_system(info: dict) -> bool:
    return bool(info.get("system"))


def _module_infos() -> list[dict]:
    from modules.manager import module_manager
    return [i for i in module_manager.list_all() if not _is_system(i)]


def config_section_key(module_name: str) -> str:
    return f"module_{module_name}"


def has_config_section(module_name: str) -> bool:
    """Le module déclare-t-il des réglages ?

    Interrogé sur le **registre**, pas sur l'instance : le point d'une
    section de configuration est justement de pouvoir régler un module qui
    ne démarre pas encore.
    """
    from configs.registry import registry
    prefix = f"{module_name}."
    section = config_section_key(module_name)
    for item in registry.all_items():
        if item.section == section or item.key.startswith(prefix):
            return True
    return False


def collect_spaces() -> list[ModuleSpaceInfo]:
    """Tous les modules ayant droit à un espace, triés par nom."""
    out: list[ModuleSpaceInfo] = []
    for info in _module_infos():
        name = info["name"]
        try:
            panels = panels_for(name)
        except Exception:
            logger.exception("panneaux illisibles pour le module %s", name)
            panels = []
        has_cfg = has_config_section(name)
        # Un module sans panneau ni configuration n'a rien à montrer : on ne
        # crée pas une page vide juste parce qu'il est enregistré.
        if not panels and not has_cfg:
            continue
        out.append(ModuleSpaceInfo(
            name=name,
            label=label_for(name),
            icon=_icon_for(panels),
            running=bool(info.get("running")),
            enabled=bool(info.get("enabled")),
            panel_count=len(panels),
            has_config=has_cfg,
        ))
    out.sort(key=lambda s: s.label.lower())
    return out


def label_for(module_name: str) -> str:
    from configs.registry import registry
    for section in registry.sections():
        if section.key == config_section_key(module_name):
            # « Module · Email » → « Email »
            return section.label.split("·")[-1].strip() or module_name
    return module_name.replace("_", " ").capitalize()


def _icon_for(panels: Sequence[ModulePanel]) -> str:
    return panels[0].icon if panels else "▦"


def panels_for(module_name: str) -> list[ModulePanel]:
    """Panneaux d'un module — natifs si déclarés, adaptés sinon.

    Un module qui n'expose rien mais possède une configuration reçoit tout de
    même son espace : la page de réglages est construite par GestionSystème,
    pas par le module.
    """
    from modules.manager import module_manager

    module = module_manager.get_registered(module_name)
    if module is None:
        return []

    native = _native_panels(module)
    if native:
        return native
    return _legacy_panels(module)


def _native_panels(module) -> list[ModulePanel]:
    getter = getattr(module, "get_panels", None)
    if not callable(getter):
        return []
    try:
        panels = list(getter() or [])
    except Exception:
        logger.exception("get_panels() a échoué pour %s", module.name)
        return []
    panels = [p for p in panels if isinstance(p, ModulePanel)]
    panels.sort(key=lambda p: (p.order, p.label))
    return panels


def _legacy_panels(module) -> list[ModulePanel]:
    """Adapte les ``ModuleView`` historiques.

    Le module continue de renvoyer ``{columns, rows, total, page, limit}`` ;
    on le convertit en cellules typées. Les clés ``html`` / ``js`` /
    ``template`` d'une charge utile ne sont pas « nettoyées » : elles ne sont
    simplement jamais lues, puisque le rendu ne connaît que des cellules.
    """
    getter = getattr(module, "get_views", None)
    if not callable(getter):
        return []
    try:
        views = list(getter() or [])
    except Exception:
        logger.exception("get_views() a échoué pour %s", module.name)
        return []

    panels = [_adapt_legacy_view(module, v) for v in views]
    panels = [p for p in panels if p is not None]
    panels.sort(key=lambda p: (p.order, p.label))
    return panels


def _adapt_legacy_view(module, view) -> ModulePanel | None:
    key = getattr(view, "key", "")
    if not key:
        return None

    data_handler = getattr(view, "data_handler", None)

    def handler(request, _handler=data_handler, _view=view):
        if _handler is None:
            return Note("Cette vue ne fournit aucune donnée.", tone="warn")
        payload = _call(_handler, request)
        if not isinstance(payload, dict):
            return Note("Réponse inattendue de la vue du module.", tone="warn")
        return _blocks_from_legacy_payload(payload)

    actions = tuple(
        PanelAction(
            key=a.key,
            label=a.label,
            handler=_legacy_action(a),
            confirm=getattr(a, "confirm", "") or "",
        )
        for a in (getattr(view, "actions", None) or [])
        if getattr(a, "key", "")
    )

    return ModulePanel(
        key=key,
        label=getattr(view, "label", key),
        icon=getattr(view, "icon", "▦") or "▦",
        order=getattr(view, "order", 100),
        handler=handler,
        actions=actions,
    )


def _legacy_action(action):
    def run(request, _a=action):
        result = _call(_a.handler, request)
        if isinstance(result, dict):
            if result.get("error"):
                return Note(str(result["error"]), tone="danger")
            message = result.get("message") or result.get("detail")
            if message:
                return Note(str(message), tone="ok")
        return Note(f"Action « {_a.label} » exécutée.", tone="ok")
    return run


def _blocks_from_legacy_payload(payload: dict):
    """Convertit ``{columns, rows, …}`` (ou ``{tabs: [...]}``) en blocs."""
    if payload.get("tabs"):
        items = []
        for tab in payload["tabs"]:
            if not isinstance(tab, dict):
                continue
            title = str(tab.get("label") or tab.get("key") or "")
            if tab.get("columns") is not None:
                table = _table_from_legacy(tab)
                table.caption = title
                items.append(table)
            else:
                items.append(Fields(
                    title=title,
                    items=[
                        Field(label=str(k), value=_str(v))
                        for k, v in tab.items()
                        if k not in ("key", "label", "columns", "rows", "html", "js", "template")
                    ],
                ))
        return Blocks(items=items)

    if payload.get("columns") is not None:
        return _table_from_legacy(payload)

    return Fields(items=[
        Field(label=str(k), value=_str(v))
        for k, v in payload.items()
        if k not in ("html", "js", "template")
    ])


def _table_from_legacy(payload: dict) -> Table:
    raw_columns = payload.get("columns") or []
    columns: list[Column] = []
    keys: list[str] = []
    for c in raw_columns:
        if isinstance(c, dict):
            keys.append(str(c.get("key", "")))
            columns.append(Column(label=str(c.get("label") or c.get("key") or "")))
        else:
            keys.append(str(c))
            columns.append(Column(label=str(c)))

    rows: list[Row] = []
    for raw in payload.get("rows") or []:
        if isinstance(raw, dict):
            cells = tuple(text(raw.get(k), clamp=True) for k in keys)
        elif isinstance(raw, (list, tuple)):
            cells = tuple(text(v, clamp=True) for v in raw)
        else:
            cells = (text(raw),)
        rows.append(Row(cells=cells))

    return Table(columns=columns, rows=rows, page=_legacy_page(payload, len(rows)))


@dataclass
class _LegacyPage:
    """Pagination reconstituée depuis ``{total, page, limit}``.

    L'ancien contrat compte les pages à partir de **zéro** ; l'interface
    compte à partir de un. La conversion est faite ici, à l'unique endroit
    qui connaît les deux conventions.
    """
    total: int
    number: int
    per_page: int
    num_pages: int
    param: str = "page"
    zero_based: bool = True

    @property
    def has_prev(self) -> bool: return self.number > 1

    @property
    def has_next(self) -> bool: return self.number < self.num_pages

    @property
    def prev_number(self) -> int: return max(1, self.number - 1)

    @property
    def next_number(self) -> int: return min(self.num_pages, self.number + 1)

    @property
    def start_index(self) -> int:
        return 0 if not self.total else (self.number - 1) * self.per_page + 1

    @property
    def end_index(self) -> int:
        return min(self.total, self.number * self.per_page)

    @property
    def page_links(self):
        from GestionSysteme.tables import _elided_range
        return _elided_range(self.number, self.num_pages)


def _legacy_page(payload: dict, fallback_rows: int) -> _LegacyPage | None:
    if "total" not in payload:
        return None
    try:
        total = int(payload.get("total") or 0)
        per_page = int(payload.get("limit") or fallback_rows or 25) or 25
        zero_based_page = int(payload.get("page") or 0)
    except (TypeError, ValueError):
        return None
    num_pages = max(1, -(-total // per_page))
    return _LegacyPage(
        total=total,
        number=min(num_pages, zero_based_page + 1),
        per_page=per_page,
        num_pages=num_pages,
    )


# ══════════════════════════════════════════════════════════════════════
#  Exécution
# ══════════════════════════════════════════════════════════════════════

def _call(handler: Callable, *args):
    """Appelle un gestionnaire synchrone ou asynchrone indifféremment.

    Les modules historiques déclarent des coroutines ; le nouveau contrat
    accepte les deux, parce qu'un panneau qui lit trois lignes en base n'a
    aucune raison d'être asynchrone.
    """
    if inspect.iscoroutinefunction(handler):
        return async_to_sync(handler)(*args)
    result = handler(*args)
    if inspect.isawaitable(result):
        return async_to_sync(_await)(result)
    return result


async def _await(awaitable):
    return await awaitable


def run_panel(request, module_name: str, panel: ModulePanel):
    """Exécute un panneau et renvoie un bloc affichable.

    Une exception devient un bloc d'erreur : l'espace du module doit rester
    navigable quand l'un de ses panneaux casse — c'est précisément là qu'on
    vient chercher pourquoi.
    """
    if panel.handler is None:
        return Note("Ce panneau ne produit aucun contenu.", tone="warn")
    try:
        result = _call(panel.handler, request)
    except Exception as exc:
        logger.exception("panneau %s/%s en échec", module_name, panel.key)
        return Note(f"Le panneau a échoué : {exc}", tone="danger",
                    title="Erreur du module")
    if result is None:
        return Note("Aucune donnée.", tone="info")
    if isinstance(result, BLOCK_TYPES):
        return result
    if isinstance(result, dict):
        return _blocks_from_legacy_payload(result)
    return Prose(text=str(result))


def run_action(request, module_name: str, panel: ModulePanel, action_key: str) -> Note:
    action = next((a for a in panel.actions if a.key == action_key), None)
    if action is None:
        return Note("Action inconnue.", tone="danger")
    try:
        result = _call(action.handler, request)
    except Exception as exc:
        logger.exception("action %s/%s/%s en échec", module_name, panel.key, action_key)
        return Note(f"L'action a échoué : {exc}", tone="danger")
    if isinstance(result, Note):
        return result
    if isinstance(result, str):
        return Note(result, tone="ok")
    return Note(f"Action « {action.label} » exécutée.", tone="ok")


def find_panel(module_name: str, panel_key: str) -> ModulePanel | None:
    for panel in panels_for(module_name):
        if panel.key == panel_key:
            return panel
    return None


def iter_blocks(block) -> Iterable[Any]:
    """Aplati un ``Blocks`` pour l'itération du gabarit."""
    if isinstance(block, Blocks):
        for item in block.items:
            yield from iter_blocks(item)
    elif block is not None:
        yield block
