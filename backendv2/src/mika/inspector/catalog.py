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
    #: ``tabs`` (des onglets) | ``menu`` (un sous-menu rangé par rubrique, à gauche) |
    #: ``stack`` (tout l'un sous l'autre : l'accueil)
    layout: str = "tabs"
    #: prend aussi tous les onglets de la console dont la clé commence par « <clé>. »
    #: (rangés par ``Builtin.order``) : des pages connues seulement au démarrage
    dynamic: bool = False
    #: l'ordre des onglets (leurs noms courts) ; les autres suivent dans l'ordre déclaré
    order: tuple[str, ...] = ()
    #: les types d'objets dont la fiche « habite » ici (le menu s'y allume, le fil d'Ariane y mène)
    subjects: tuple[str, ...] = ()


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
    #: un lien vers une page à part plutôt qu'un contenu
    href: str = ""
    #: la rubrique du sous-menu (destinations ``menu``)
    group: str = ""
    order: int = 100
    #: ce que montre la page, sous son titre
    description: str = ""

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
class SettingsPage:
    """Une sous-page de la configuration : un seul sujet, jamais toute une section.

    ``fields`` : les chemins montrés (vide : toute la section) ; une liste
    d'enregistrements (``records``) parmi eux s'affiche en table, chaque entrée sur
    sa propre page. ``commands``, ``blocks`` et ``yaml`` disent si la page porte les
    boutons, les blocs d'explication et l'import YAML de sa section."""

    key: str
    title: str
    fields: tuple[str, ...] = ()
    description: str = ""
    order: int = 100
    commands: bool = False
    blocks: bool = False
    yaml: bool = False
    facts: bool = True
    #: la page n'a pas de formulaire (seulement l'import YAML, des commandes, des blocs)
    form: bool = True
    #: des blocs propres à cette page (un historique, une table de résolution)
    extra: Callable[[], Sequence[Any]] | None = None


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
    #: ses sous-pages (vide : une seule page, la section entière)
    pages: tuple[SettingsPage, ...] = ()
    #: des choix connus au rendu pour un champ texte (chemin → ``fn() -> [(valeur, libellé)]``) :
    #: il devient un sélecteur (les fuseaux horaires)
    choices: Mapping[str, Callable[[], Sequence[tuple[str, str]]]] = field(default_factory=dict)


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

    def tab(self, key: str, *, title: str, badge: Callable[..., int] | None = None, href: str = "",
            group: str = "", order: int = 100, description: str = ""):
        def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            if key in self.items:
                raise ValueError(f"onglet de la console déclaré deux fois : {key}")
            self.items[key] = Builtin(key, title, fn, badge, href, group, order, description)
            return fn

        return deco


def builtin_keys(d: Destination, builtins: Mapping[str, Builtin]) -> list[str]:
    """Les onglets de console d'une destination : ceux qu'elle nomme, puis (``dynamic``)
    tous ceux de son préfixe, rangés par ``order``."""
    keys = list(d.builtin)
    if d.dynamic:
        prefix = d.key + "."
        extra = [b for k, b in builtins.items() if k.startswith(prefix) and k not in keys]
        keys += [b.key for b in sorted(extra, key=lambda b: b.order)]
    return keys


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
        for key in builtin_keys(d, builtins):
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
        for name in d.order:
            if name not in slugs:
                problems.append(f"destination {d.key} : ordre vers un onglet inconnu {name}")
    for v in registry.inspectors:
        if v.section and v.section not in seen:
            problems.append(f"vue {v.owner}/{v.name} : destination inconnue {v.section}")
    for a in registry.actions.values():
        if a.section and a.section not in seen:
            problems.append(f"action {a.key} : destination inconnue {a.section}")
    if problems:
        raise CompositionError(problems)
