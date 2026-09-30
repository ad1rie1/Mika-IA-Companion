"""Les vues d'inspection : ce qu'une faculté montre d'elle à un opérateur.

Une faculté déclare ``@f.inspect("nom", title=…, section=…, subject=…)`` une
fonction ``(tranche, frame, ctx) -> Sequence[Block]`` ; la console les rend
toutes de la même façon, les range là où la composition l'a décidé (une
destination, ou un onglet de la fiche d'un objet), sans connaître aucune
faculté. Le même vocabulaire sert aux apps forgées, par une enveloppe JSON
(``kernel/envelope.py``).

Lecture seule : une vue lit le frame, les projections et les caches des
ports, jamais n'écrit. Tout y est montré (la console est réservée aux
opérateurs) ; un contenu oublié s'affiche comme tel.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

#: les tons d'une cellule, d'une ligne, d'une note
TONES = ("", "info", "ok", "warn", "danger", "muted")
_LEGACY_TONES = {"ko": "danger", "mut": "muted"}


def tone(value: str) -> str:
    """Un ton connu, ou rien (« ko » et « mut » restent compris)."""
    value = _LEGACY_TONES.get(value, value)
    return value if value in TONES else ""


# ── Liens ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Ref:
    """Un lien vers une autre page de la console.

    ``kind`` : ``"episode"`` (clé = corrélation), ``"event"`` (clé = seq),
    ``"view"`` (clé = ``"<propriétaire>/<nom>"``), ``"subject"`` (clé =
    ``"<sorte>/<clé>"``, la fiche d'un objet), ``"url"`` (http(s) seulement,
    revérifié au rendu)."""

    kind: str
    key: str
    text: str
    params: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def subject(kind: str, key: str, text: str, tab: str = "") -> Ref:
        return Ref("subject", f"{kind}/{key}", text, (("onglet", tab),) if tab else ())

    @staticmethod
    def view(owner: str, name: str, text: str, **params: str) -> Ref:
        return Ref("view", f"{owner}/{name}", text, tuple((k, str(v)) for k, v in params.items()))

    @staticmethod
    def url(href: str, text: str) -> Ref:
        return Ref("url", href, text)


# ── Cellules ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Text:
    """Un texte typé : ``kind`` ``text`` | ``mono`` | ``num`` | ``muted`` ;
    ``clamp`` > 0 : replié au-delà de tant de caractères (« lire la suite »)."""

    text: str
    kind: str = "text"
    tone: str = ""
    hint: str = ""
    clamp: int = 0


@dataclass(frozen=True, slots=True)
class Badge:
    text: str
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Meter:
    """Une jauge : ``ratio`` dans [0, 1] (hors bornes : ramené ; non fini : « — »)."""

    ratio: float
    text: str = ""
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Swatch:
    """Une pastille de couleur tirée d'une palette nommée (``"emotion"`` : la
    couleur de l'une des 29 émotions, ``key`` = son nom canonique)."""

    text: str
    palette: str
    key: str
    weight: float | None = None


@dataclass(frozen=True, slots=True)
class When:
    """Un instant : « il y a 3 min », la date exacte au survol."""

    at: int
    relative: bool = True


Cell = str | int | float | bool | Ref | Text | Badge | Meter | Swatch | When | None


# ── Blocs ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Column:
    label: str
    #: ``""`` | ``"num"`` (aligné à droite) | ``"fit"`` (aussi étroit que possible)
    align: str = ""
    hint: str = ""


@dataclass(frozen=True, slots=True)
class Row:
    """Une ligne riche : un lien, un ton, et un détail dépliable (d'autres blocs,
    y compris un formulaire d'action)."""

    cells: tuple[Cell, ...]
    href: Ref | None = None
    tone: str = ""
    detail: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class Pager:
    """Une pagination : par numéro (``total`` connu) ou par curseur (``older`` :
    la requête de la page suivante, p. ex. ``(("avant", "1234"),)``)."""

    param: str = "page"
    number: int = 1
    size: int = 50
    total: int | None = None
    older: tuple[tuple[str, str], ...] = ()

    @property
    def pages(self) -> int:
        return max(1, math.ceil((self.total or 0) / self.size)) if self.total is not None else 1

    @property
    def offset(self) -> int:
        return (self.number - 1) * self.size


@dataclass(frozen=True, slots=True)
class Table:
    columns: tuple[str | Column, ...]
    rows: tuple[tuple[Cell, ...] | Row, ...]
    title: str = ""
    empty: str = "rien pour l'instant"
    pager: Pager | None = None
    #: les paramètres de la vue montrés comme filtres au-dessus du tableau
    filters: tuple[str, ...] = ()
    caption: str = ""


@dataclass(frozen=True, slots=True)
class Fields:
    pairs: tuple[tuple[str, Cell], ...]
    title: str = ""
    #: une aide par libellé (au survol)
    hints: tuple[tuple[str, str], ...] = ()
    columns: int = 1


@dataclass(frozen=True, slots=True)
class Note:
    text: str
    tone: str = ""
    title: str = ""


@dataclass(frozen=True, slots=True)
class Prose:
    """Un texte long (un récit, un journal, un prompt), rendu tel quel."""

    text: str
    title: str = ""
    clamp: int = 0


@dataclass(frozen=True, slots=True)
class Code:
    text: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class Series:
    """Une série de points (instant, valeur) ; ``slot`` : sa couleur (1 à 4)."""

    label: str
    points: tuple[tuple[int, float], ...]
    slot: int = 0


@dataclass(frozen=True, slots=True)
class Chart:
    """Une courbe, des barres ou une petite tendance, sur **une** échelle (la
    valence −1…1 ne se mêle jamais à des 0…1)."""

    series: tuple[Series, ...]
    #: ``line`` | ``bars`` | ``spark``
    kind: str = "line"
    title: str = ""
    #: ``""`` | ``"%"`` | ``"$"``
    unit: str = ""
    y: tuple[float, float] | None = None
    zero: float | None = None
    since: int | None = None
    until: int | None = None
    empty: str = "pas encore de mesure"
    #: un tableau des valeurs, repliable (lisible sans la couleur)
    table: bool = True


@dataclass(frozen=True, slots=True)
class Stat:
    label: str
    value: Cell
    sub: str = ""
    tone: str = ""
    href: Ref | None = None
    trend: Chart | None = None


@dataclass(frozen=True, slots=True)
class Stats:
    items: tuple[Stat, ...]
    title: str = ""


@dataclass(frozen=True, slots=True)
class Entry:
    at: int
    title: str
    text: str = ""
    tone: str = ""
    href: Ref | None = None
    meta: str = ""


@dataclass(frozen=True, slots=True)
class Timeline:
    entries: tuple[Entry, ...]
    title: str = ""
    empty: str = "rien pour l'instant"


@dataclass(frozen=True, slots=True)
class Grid:
    items: tuple[Any, ...]
    #: 1 à 3
    columns: int = 2


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    items: tuple[Any, ...]
    description: str = ""


@dataclass(frozen=True, slots=True)
class Disclosure:
    title: str
    items: tuple[Any, ...]
    open: bool = False


@dataclass(frozen=True, slots=True)
class ActionSlot:
    """Le formulaire d'une action déclarée (``"<propriétaire>.<nom>"``), en place ;
    ``initial`` pré-remplit ses champs."""

    action: str
    initial: tuple[tuple[str, str], ...] = ()
    title: str = ""
    compact: bool = False


@dataclass(frozen=True, slots=True)
class NavItem:
    """Un lien d'une rangée de navigation : son texte, où il mène, un compte
    facultatif (« 3 » non lus) et s'il désigne la page où l'on est."""

    text: str
    href: Ref
    count: int | str | None = None
    active: bool = False
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Nav:
    """Une rangée de liens en puces (les boîtes d'un courrier, ses dossiers) :
    une navigation dans la vue, qui se replie sur plusieurs lignes."""

    items: tuple[NavItem, ...]
    title: str = ""


Block = (Table | Fields | Note | Prose | Code | Stats | Timeline | Chart | Grid | Section | Disclosure
         | ActionSlot | Nav)
BLOCKS: tuple[type, ...] = (Table, Fields, Note, Prose, Code, Stats, Timeline, Chart, Grid, Section, Disclosure,
                            ActionSlot, Nav)


# ── Paramètres typés d'une vue ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Param:
    """Un filtre d'une vue. ``kind`` : ``search`` | ``select`` | ``int`` |
    ``bool`` | ``hidden`` ; pour ``select``, une valeur ou son libellé tapés à
    la main sont compris."""

    name: str
    label: str
    kind: str = "search"
    choices: tuple[tuple[str, str], ...] = ()
    default: str = ""
    placeholder: str = ""
    lo: int | None = None
    hi: int | None = None


#: réservés à la console (pagination, onglet, retour des actions)
RESERVED = frozenset({"page", "taille", "onglet", "fait", "avant", "q_global"})


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def read_params(specs: Sequence[Param], raw: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Les valeurs validées des filtres, et ce qu'il faut en dire (une valeur
    inconnue retombe sur le défaut, et le dit)."""
    values: dict[str, Any] = {}
    notes: list[str] = []
    for p in specs:
        given = str(raw.get(p.name, "") or "").strip()[:200]
        if p.kind == "int":
            try:
                n = int(given) if given else (int(p.default) if p.default else None)
            except ValueError:
                notes.append(f"Filtre « {p.label} » : « {given} » n'est pas un nombre.")
                n = int(p.default) if p.default else None
            if n is not None and ((p.lo is not None and n < p.lo) or (p.hi is not None and n > p.hi)):
                notes.append(f"Filtre « {p.label} » : {n} est hors bornes.")
                n = int(p.default) if p.default else None
            values[p.name] = n
        elif p.kind == "bool":
            values[p.name] = given.lower() in ("1", "oui", "on", "true") if given else p.default in ("1", "oui")
        elif p.kind == "select":
            if not given:
                values[p.name] = p.default
                continue
            folded = _fold(given)
            match = next((v for v, label in p.choices if v == given or _fold(label) == folded or _fold(v) == folded),
                         None)
            if match is None:
                known = ", ".join(label for _, label in p.choices)
                notes.append(f"Filtre « {p.label} » : « {given} » inconnu (au choix : {known}).")
                match = p.default
            values[p.name] = match
        else:
            values[p.name] = given or p.default
    return values, notes


def paginate(items: Sequence[Any], pager: Pager) -> tuple[Sequence[Any], Pager]:
    """Découpe une liste déjà en mémoire ; le numéro est ramené dans les bornes."""
    total = len(items)
    pages = max(1, math.ceil(total / pager.size))
    number = min(max(1, pager.number), pages)
    p = replace(pager, number=number, total=total)
    return items[p.offset:p.offset + p.size], p


# ── Fiches d'objets, vitaux ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Head:
    """L'en-tête de la fiche d'un objet. ``key`` est la clé canonique (une
    poignée rend la clé de sa personne : la console y redirige)."""

    key: str
    title: str
    subtitle: str = ""
    badges: tuple[Badge, ...] = ()
    facts: tuple[tuple[str, Cell], ...] = ()
    #: d'autres clés du même objet (ses poignées) : recherche, oubli
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Found:
    """Un résultat de recherche d'objets."""

    key: str
    title: str
    subtitle: str = ""


@dataclass(frozen=True, slots=True)
class Vital:
    """Une valeur de la barre de vitaux."""

    text: str
    tone: str = ""
    ratio: float | None = None
    swatch: Swatch | None = None
    hint: str = ""
    href: Ref | None = None


# ── Contexte d'une vue ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class InspectContext:
    """Ce qu'une vue reçoit en plus de sa tranche et du frame."""

    #: lecture seule : ``query_mind``, ``query_views``, ``content``
    store: Any
    #: les ports (caches des plugins : courrier, flux, Forge…)
    ports: Mapping[str, Any]
    #: la requête brute (``?q=…``), des chaînes
    params: Mapping[str, str] = field(default_factory=dict)
    #: un instant, lisible en heure locale
    when: Callable[[int], str] = str
    #: le journal : ``events(types, limit=50, where=(champ, valeur), before=seq, correlations=…)``
    #: → événements décodés (contenus résolus, « oubliés » à ``None``), du plus récent
    #: au plus ancien
    journal: Callable[..., list[Any]] | None = None
    #: ``tally(type, champ)`` → (valeur, nombre, dernier instant), par valeur
    counter: Callable[[str, str], list[tuple[Any, int, int]]] | None = None
    #: la clé de l'objet, sur une fiche
    subject: str = ""
    #: les filtres déclarés (``Param``), validés
    values: Mapping[str, Any] = field(default_factory=dict)
    now: int = 0
    #: les séries mesurées : ``sampler(clé, depuis, jusqu'à, points)``
    sampler: Callable[..., list[tuple[int, float]]] | None = None

    def events(self, types: Sequence[Any], limit: int = 50, *, where: tuple[str, Any] | None = None,
               before: int | None = None, correlations: Sequence[str] | None = None) -> list[Any]:
        """Les derniers événements de ces types (``EventType`` ou noms), d'un
        champ donné, ou de ces épisodes."""
        if self.journal is None:
            return []
        names = [getattr(t, "name", t) for t in types]
        return self.journal(names, limit, where=where, before=before, correlations=correlations)

    def tally(self, event_type: Any, field: str) -> list[tuple[Any, int, int]]:
        if self.counter is None:
            return []
        return self.counter(getattr(event_type, "name", event_type), field)

    def param(self, name: str, default: str = "") -> str:
        return str(self.params.get(name, default) or default).strip()[:200]

    def int_param(self, name: str, default: int = 0) -> int:
        try:
            return int(self.params.get(name, default))
        except (TypeError, ValueError):
            return default

    def value(self, name: str) -> Any:
        """La valeur validée d'un filtre déclaré."""
        return self.values.get(name)

    def pager(self, param: str = "page", size: int = 50, *, total: int | None = None, max_size: int = 200) -> Pager:
        """La page demandée (``?page=``, ``?taille=``), bornée."""
        size = max(1, min(self.int_param("taille", size) or size, max_size))
        number = max(1, self.int_param(param, 1))
        if total is not None:
            number = min(number, max(1, math.ceil(total / size)))
        return Pager(param=param, number=number, size=size, total=total)

    def series(self, key: str, since: int, until: int | None = None, points: int = 240) -> list[tuple[int, float]]:
        """Une série mesurée (``@f.series``), moyennée par tranches."""
        if self.sampler is None:
            return []
        return self.sampler(key, since, until if until is not None else self.now, points)


def rows(items: Sequence[Sequence[Cell]]) -> tuple[tuple[Cell, ...], ...]:
    return tuple(tuple(r) for r in items)
