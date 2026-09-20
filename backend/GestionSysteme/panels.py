"""Composants de gestion partagés par le cœur, les plugins et la Forge.

Les plugins produisent ces objets typés. Les apps forgées produisent le
contrat JSON v2, décodé par panel_payload. Django assure le rendu échappé.
"""
from __future__ import annotations

import inspect
import logging
import math
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
    clamp: bool = False       # aperçu dépliable, texte intégral toujours disponible

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
    """Pastille d'émotion. Le texte est traduit, la couleur reste sur le nom.

    Les deux champs divergent volontairement : ``emotion`` compose une variable
    CSS et doit donc rester le nom canonique anglais, ``text`` est ce que lit
    l'opérateur. Traduire ici couvre d'un coup tous les panneaux de modules,
    qui n'ont jamais à connaître le vocabulaire d'affichage.
    """
    from GestionSysteme.formatting import emotion_fr

    return Cell(
        text=emotion_fr(_str(name)), kind="emotion",
        emotion=_str(name), ratio=weight,
    )


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
        value = float(value)
        return max(0.0, min(1.0, value)) if math.isfinite(value) else None
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
    detail: Any = None   # blocs consultables sans perdre la liste


@dataclass
class Table:
    """Un tableau. ``page`` porte la pagination si le module en fournit une.

    ``filters`` accepte un ``tables.FilterSet`` : le module décrit les filtres
    qu'il veut, la coquille les rend et les relit depuis l'URL. Ils vivent sur
    le tableau plutôt que dans un bloc séparé parce qu'un filtre détaché de la
    liste qu'il filtre n'a pas de sens — et parce que la barre doit se placer
    dans l'en-tête de la carte, pas au-dessus d'elle.
    """
    columns: Sequence[Column]
    rows: Sequence[Row]
    page: Any = None                 # tables.PageResult | None
    filters: Any = None              # tables.FilterSet | None
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
    ratio: float | None = None
    title: str = ""
    emotion: str = ""

    @property
    def cell(self) -> Cell:
        return Cell(text=_str(self.value), kind=self.kind, tone=_tone(self.tone),
                    href=self.href, ratio=_ratio(self.ratio), title=self.title,
                    emotion=(self.emotion or self.value) if self.kind == "emotion" else "")

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
    href: str = ""


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


@dataclass
class Grid:
    """Composition adaptative, de une à trois colonnes."""
    items: Sequence[Any]
    columns: int = 2
    block = "grid"


@dataclass
class Section:
    title: str
    items: Sequence[Any]
    description: str = ""
    block = "section"


@dataclass
class Disclosure:
    title: str
    items: Sequence[Any]
    open: bool = False
    block = "disclosure"


@dataclass
class Code:
    text: str
    title: str = ""
    block = "code"


@dataclass(frozen=True)
class TimelineEntry:
    title: str
    text: str = ""
    meta: str = ""
    tone: str = ""
    href: str = ""


@dataclass
class Timeline:
    items: Sequence[TimelineEntry]
    title: str = ""
    empty: str = "Aucun événement."
    block = "timeline"


@dataclass
class ActionForm:
    """Instance d'une action déclarée, éventuellement liée à une ligne.

    Les valeurs initiales ne changent jamais la définition ni le destinataire
    de l'action. La validation est faite à nouveau au POST.
    """
    action: str
    initial: dict = field(default_factory=dict)
    title: str = ""
    block = "form"


BLOCK_TYPES = (Table, Fields, Stats, Note, Prose, Template, Blocks,
               Grid, Section, Disclosure, Code, Timeline, ActionForm)


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
    fields: tuple = ()             # panel_forms.Input ; request.panel_data après validation
    description: str = ""


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
    """Panneaux déclarés par un module Python.

    Un module qui n'expose rien mais possède une configuration reçoit tout de
    même son espace : la page de réglages est construite par GestionSystème,
    pas par le module.
    """
    from modules.manager import module_manager

    module = module_manager.get_registered(module_name)
    if module is None:
        return []

    return _native_panels(module)


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


def blocks_from_payload(payload: dict, *, request=None):
    from GestionSysteme.panel_payload import decode
    return decode(payload, request=request)


# ══════════════════════════════════════════════════════════════════════
#  Exécution
# ══════════════════════════════════════════════════════════════════════

def _call(handler: Callable, *args):
    """Appelle un gestionnaire synchrone ou asynchrone indifféremment.

    Le contrat accepte les deux pour convenir aux lectures en base comme aux
    appels de services asynchrones.
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
        return blocks_from_payload(result, request=request)
    return Prose(text=str(result))


def run_action(request, module_name: str, panel: ModulePanel, action_key: str) -> Note:
    action = next((a for a in panel.actions if a.key == action_key), None)
    if action is None:
        return Note("Action inconnue.", tone="danger")
    from GestionSysteme.panel_forms import build_form, InvalidAction
    form = build_form(action, data=request.POST)
    if not form.is_valid():
        raise InvalidAction(action_key, form)
    request.panel_data = form.cleaned_data
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


def walk_blocks(block) -> Iterable[Any]:
    """Parcourt la composition sans l'aplatir pour le rendu."""
    yield block
    if isinstance(block, (Blocks, Grid, Section, Disclosure)):
        for child in block.items:
            yield from walk_blocks(child)
    elif isinstance(block, Table):
        for row in block.rows:
            if row.detail is not None:
                yield from walk_blocks(row.detail)


def header_actions(panel, block):
    inline = {b.action for b in walk_blocks(block) if isinstance(b, ActionForm)}
    return [a for a in panel.actions if a.key not in inline]
