"""La carte de la console : groupes, destinations, onglets.

La composition (``app/console.py``) déclare la navigation ; les facultés
déclarent leurs vues avec une ``section`` (la clé d'une destination) ; la
console fournit ses propres onglets (``builtin``). ``check`` vérifie au
démarrage que tout se tient : aucune vue vers une section inconnue, aucun
onglet en double, aucune destination vide.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mika.kernel.registry import CompositionError


@dataclass(frozen=True, slots=True)
class Destination:
    key: str
    label: str
    icon: str = ""
    description: str = ""
    #: les onglets fournis par la console, dans l'ordre (``"decisions.maintenant"``)
    builtin: tuple[str, ...] = ()
    #: ``tabs`` (un onglet à la fois) | ``stack`` (tout l'un sous l'autre : l'accueil)
    layout: str = "tabs"


@dataclass(frozen=True, slots=True)
class NavGroup:
    label: str
    items: tuple[Destination, ...]


@dataclass(frozen=True, slots=True)
class Builtin:
    """Un onglet fourni par la console : ``fn(ui, request) -> blocs`` (ou une réponse)."""

    key: str
    title: str
    fn: Callable[..., Awaitable[Any]]
    #: ce qui demande une action : ``fn(ui) -> int``
    badge: Callable[..., int] | None = None
    #: un lien vers une page à part (réglages en cours de refonte) plutôt qu'un contenu
    href: str = ""

    @property
    def slug(self) -> str:
        return self.key.split(".", 1)[1] if "." in self.key else self.key


@dataclass(frozen=True, slots=True)
class Command:
    """Un bouton d'une section de réglages (« un jeton neuf ») : ``run(opérateur) ->
    (ton, message)`` ; le message peut montrer une valeur une seule fois."""

    key: str
    title: str
    run: Callable[[str], Awaitable[tuple[str, str]]]
    confirm: str = ""
    danger: bool = False


@dataclass(frozen=True, slots=True)
class SettingsSection:
    """Une section de réglages d'exploitation, décrite par un modèle pydantic
    (``kernel/forms.py`` en tire le formulaire : groupes, bloc « avancé » replié,
    secrets jamais réaffichés, enregistrements, correspondances).

    ``load()`` rend la valeur actuelle ; ``save(valeur, opérateur)`` l'enregistre et
    rend les problèmes (rien n'est gardé s'il y en a) ; ``loaders`` chargent des
    choix à la demande (``fn(valeurs) -> [(valeur, libellé)]``, qui lève
    ``ValueError`` avec un message) ; ``commands`` sont des boutons ;
    ``facts()`` et ``blocks()`` ajoutent ce qu'il faut savoir (l'état du robot, ce
    que pilote chaque curseur). Plusieurs sections peuvent partager un onglet."""

    key: str
    label: str
    tab: str
    model: type[Any] | None = None
    load: Callable[[], Any] = lambda: None
    save: Callable[[Any, str], Awaitable[list[str]]] | None = None
    description: str = ""
    order: int = 100
    loaders: Mapping[str, Callable[[Mapping[str, Any]], Awaitable[list[tuple[str, str]]]]] = \
        field(default_factory=dict)
    commands: tuple[Command, ...] = ()
    facts: Callable[[], Sequence[tuple[str, str]]] | None = None
    blocks: Callable[[], Sequence[Any]] | None = None
    #: les chemins que ce formulaire ne montre pas (une autre section les règle)
    exclude: tuple[str, ...] = ()
    #: propose aussi d'importer / exporter le tout en YAML (sans secret)
    yaml: bool = False


@dataclass(frozen=True, slots=True)
class SettingsTab:
    key: str
    title: str


@dataclass(frozen=True, slots=True)
class Panel:
    """Un onglet qui a besoin de son propre gabarit (des formulaires sur mesure),
    inclus dans la page commune avec ce contexte."""

    template: str
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Builtins:
    items: dict[str, Builtin] = field(default_factory=dict)

    def tab(self, key: str, *, title: str, badge: Callable[..., int] | None = None, href: str = ""):
        def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            if key in self.items:
                raise ValueError(f"onglet de la console déclaré deux fois : {key}")
            self.items[key] = Builtin(key, title, fn, badge, href)
            return fn

        return deco


def destinations(nav: Sequence[NavGroup]) -> dict[str, Destination]:
    return {d.key: d for g in nav for d in g.items}


def check(nav: Sequence[NavGroup], registry: Any, builtins: Mapping[str, Builtin]) -> None:
    """Refuse une carte incohérente (``CompositionError``, comme le registre)."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for g in nav:
        for d in g.items:
            if d.key in seen:
                problems.append(f"destination déclarée deux fois : {d.key}")
            seen[d.key] = d.label
    for d in destinations(nav).values():
        slugs: set[str] = set()
        for key in d.builtin:
            b = builtins.get(key)
            if b is None:
                problems.append(f"destination {d.key} : onglet de console inconnu {key}")
                continue
            if b.slug in slugs:
                problems.append(f"destination {d.key} : onglet en double {b.slug}")
            slugs.add(b.slug)
        views = [v for v in registry.inspectors if v.section == d.key]
        for v in views:
            if v.name in slugs:
                problems.append(f"destination {d.key} : onglet en double {v.name}")
            slugs.add(v.name)
        if not slugs:
            problems.append(f"destination {d.key} : aucun onglet")
    for v in registry.inspectors:
        if v.section and v.section not in seen:
            problems.append(f"vue {v.owner}/{v.name} : destination inconnue {v.section}")
    for a in registry.actions.values():
        if a.section and a.section not in seen:
            problems.append(f"action {a.key} : destination inconnue {a.section}")
    if problems:
        raise CompositionError(problems)
