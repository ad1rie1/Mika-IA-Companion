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
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

#: les tons d'une cellule, d'une ligne, d'une note
TONES = ("", "info", "ok", "warn", "danger", "muted")
_LEGACY_TONES = {"ko": "danger", "mut": "muted"}


@dataclass(frozen=True, slots=True)
class Download:
    """Un document natif à télécharger depuis une fiche (jamais un bloc Forge)."""

    name: str
    data: bytes


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
    ``"<sorte>/<clé>"``, la fiche d'un objet), ``"why"`` (clé = le seq d'une
    de ses paroles : « pourquoi a-t-elle dit ça ? »), ``"url"`` (http(s)
    seulement, revérifié au rendu)."""

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

    @staticmethod
    def why(seq: int, text: str = "pourquoi ?") -> Ref:
        """« Pourquoi a-t-elle dit ça ? » : la page qui explique une de ses paroles (le numéro de
        l'événement ``episode.utterance`` — pour un message d'elle dans le fil, son numéro)."""
        return Ref("why", str(seq), text)


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
    secondary: str = ""
    emphasis: bool = False


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
    #: Information secondaire : conservée dans le détail de chaque ligne.
    detail: bool = False


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
    reading: bool = False
    #: source HTML d'un document natif, assainie par le rendu ; jamais acceptée d'une app Forge
    html: str = ""


@dataclass(frozen=True, slots=True)
class Code:
    text: str
    title: str = ""
    #: ``""`` | ``"diff"`` : un diff unifié, que le rendu colore ligne à ligne (ajouts, retraits, blocs)
    lang: str = ""


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
    #: une pagination, comme une table (sans elle, le rendu découpe une longue chronologie)
    pager: Pager | None = None


@dataclass(frozen=True, slots=True)
class Grid:
    items: tuple[Any, ...]
    #: 1 à 3
    columns: int = 2


@dataclass(frozen=True, slots=True)
class Workspace:
    """Une navigation latérale et un espace de travail, empilés sur mobile."""

    sidebar: tuple[Any, ...]
    items: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Toolbar:
    """Les actions d'une vue, regroupées sur une ligne."""

    items: tuple[Any, ...]
    title: str = "Actions"


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
    presentation: str = "form"


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


@dataclass(frozen=True, slots=True)
class Filters:
    """Un formulaire de consultation, produit par l'hôte depuis des paramètres
    déclarés. ``keep`` conserve le contexte (fiche, vue), jamais la pagination.
    Les apps déclarent ces paramètres dans leur manifeste, sans HTML."""

    params: tuple[Param, ...]
    values: tuple[tuple[str, str], ...] = ()
    keep: tuple[tuple[str, str], ...] = ()
    title: str = "Filtrer"


Block = (Table | Fields | Note | Prose | Code | Stats | Timeline | Chart | Grid | Workspace | Toolbar | Section | Disclosure
         | ActionSlot | Nav | Filters)
BLOCKS: tuple[type, ...] = (Table, Fields, Note, Prose, Code, Stats, Timeline, Chart, Grid, Section, Disclosure,
                            ActionSlot, Nav, Filters, Workspace, Toolbar)


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


#: réservés à la console (pagination, onglet, retour des actions) ; ``pg<n>`` : les pages
#: qu'ajoute le rendu à une table qui n'en a pas, ``pile`` : le chemin d'une pagination à curseur
RESERVED = frozenset({"page", "taille", "onglet", "fait", "avant", "q_global", "pile", "flash"})
PAGE_PARAM = r"page(?:_[a-z][a-z0-9_]{0,39})?"


def is_page_param(name: str) -> bool:
    """Les pages nommées permettent à plusieurs collections d'une app de coexister."""
    return re.fullmatch(PAGE_PARAM, name) is not None


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
    adresse rend la clé de sa personne : la console y redirige)."""

    key: str
    title: str
    subtitle: str = ""
    badges: tuple[Badge, ...] = ()
    facts: tuple[tuple[str, Cell], ...] = ()
    #: d'autres clés du même objet (ses adresses) : recherche, oubli
    aliases: tuple[str, ...] = ()
    back: Ref | None = None
    automatic_actions: bool = True
    default_tab: str = ""
    #: Vide : actions communes ; sinon, seulement sur ces onglets de gestion.
    action_tabs: tuple[str, ...] = ()


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
        """Un entier de la requête (un curseur, une page), ramené dans [0, 2⁶³−1] : un nombre géant
        ou négatif ne doit jamais atteindre SQLite (``OverflowError``) ; illisible, le défaut."""
        return int_query(self.params.get(name), default)

    def value(self, name: str) -> Any:
        """La valeur validée d'un filtre déclaré."""
        return self.values.get(name)

    def pager(self, param: str = "page", size: int = 50, *, total: int | None = None, max_size: int = 200) -> Pager:
        """La page demandée (``?page=``, ``?taille=``), bornée — son décalage aussi tient dans SQLite."""
        size = max(1, min(self.int_param("taille", size) or size, max_size))
        number = min(max(1, self.int_param(param, 1)), INT_MAX // size)
        if total is not None:
            number = min(number, max(1, math.ceil(total / size)))
        return Pager(param=param, number=number, size=size, total=total)

    def older(self, types: Sequence[Any], size: int = 50, *, param: str = "avant",
              where: tuple[str, Any] | None = None, correlations: Sequence[str] | None = None
              ) -> tuple[list[Any], Pager]:
        """Une page du journal à curseur, lue juste : ``size + 1`` événements pour savoir s'il en
        reste (« Plus anciens » n'apparaît que s'il mène quelque part), le curseur pris sur le dernier
        montré. Voir ``cursor_page``."""
        found = self.events(types, size + 1, where=where, before=self.int_param(param, 0) or None,
                            correlations=correlations)
        return cursor_page(found, size, param=param, current=self.int_param(param, 0))

    def series(self, key: str, since: int, until: int | None = None, points: int = 240) -> list[tuple[int, float]]:
        """Une série mesurée (``@f.series``), moyennée par tranches."""
        if self.sampler is None:
            return []
        return self.sampler(key, since, until if until is not None else self.now, points)


#: le plus grand entier que SQLite sait lire (un curseur, un décalage)
INT_MAX = 2**63 - 1


def int_query(raw: Any, default: int = 0) -> int:
    """Un entier lu dans une requête, ramené dans [0, ``INT_MAX``] ; illisible : le défaut."""
    try:
        value = int(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default
    return min(max(0, value), INT_MAX)


def cursor_page(found: Sequence[Any], size: int, *, param: str = "avant", current: int = 0,
                cursor: Callable[[Any], int] = lambda e: e.seq) -> tuple[list[Any], Pager]:
    """La brique commune des historiques à curseur : ``found`` a été lu avec **``size + 1``** lignes
    (du plus récent au plus ancien). Rend la page à montrer et sa pagination :

    - une ligne de plus que la page ⇒ « Plus anciens » mène à la suite (curseur : la dernière montrée) ;
      sans elle, pas de lien vers une page vide (exactement ``size`` lignes : c'est la fin) ;
    - première page complète (pas de curseur, rien après) ⇒ le total est **connu** : on le dit, au lieu
      d'un « total non connu » pour trois lignes ;
    - ``current`` : la valeur actuelle du curseur (``ctx.int_param(param)``), 0 sur la première page."""
    shown = list(found[:size])
    if len(found) > size and shown:
        return shown, Pager(param=param, size=max(1, size), older=((param, str(cursor(shown[-1]))),))
    if not current:
        return shown, Pager(param=param, size=max(1, size), total=len(shown))
    return shown, Pager(param=param, size=max(1, size))


# ── Nombres, pourcentages, dates : à la française ─────────────────────────

_NNBSP = " "  # espace fine insécable : « 12 345 », « 42 % »
_MINUS = "−"
_DAYS_FR = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
_MONTHS_FR = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def num_fr(value: float | int | None, digits: int | None = None, *, signed: bool = False) -> str:
    """Un nombre à la française : virgule décimale, milliers séparés par une espace fine
    (« 12 345,6 »), « − » pour le signe ; ``digits`` : décimales fixes (sinon trois chiffres
    significatifs, jamais d'exposant) ; ``signed`` : « +0,42 ». ``None`` ou non fini : « — »."""
    if value is None or isinstance(value, bool) or not math.isfinite(float(value)):
        return "—"
    if isinstance(value, int) and digits is None:
        text = f"{abs(value):,d}"
    elif digits is not None:
        text = f"{abs(value):,.{digits}f}"
    elif abs(value) >= 1000:
        text = f"{abs(value):,.0f}"
    else:
        text = f"{abs(value):.3g}"
        if "e" in text:
            text = f"{abs(value):.6f}".rstrip("0").rstrip(".") or "0"
    text = text.replace(",", _NNBSP).replace(".", ",")
    negative = value < 0 and any(c not in "0," for c in text.replace(_NNBSP, ""))
    sign = _MINUS if negative else ("+" if signed and value > 0 else "")
    return sign + text


def pct_fr(ratio: float | None, digits: int = 0) -> str:
    """Une part en pourcentage à la française : 0,423 → « 42 % »."""
    if ratio is None or not math.isfinite(float(ratio)):
        return "—"
    return f"{num_fr(ratio * 100, digits)}{_NNBSP}%"


def money_fr(amount: float | None, unit: str = "$") -> str:
    """Un coût : « 0,0034 $ » sous un centime, « 1,25 $ » au-delà."""
    if amount is None or not math.isfinite(float(amount)):
        return "—"
    digits = 4 if 0 < abs(amount) < 0.01 else 2
    return f"{num_fr(amount, digits)}{_NNBSP}{unit}"


def day_fr(year: int, month: int, day: int, weekday: int, *, with_year: bool = False) -> str:
    """Un jour à la française (« mer. 1 oct. », « mer. 1 oct. 2026 ») ; ``weekday`` : 0 = lundi."""
    text = f"{_DAYS_FR[weekday % 7]} {day} {_MONTHS_FR[(month - 1) % 12]}"
    return f"{text} {year}" if with_year else text


#: ce que veut dire une erreur, pour un opérateur (jamais un ``repr`` Python)
_ERRORS_FR: Mapping[str, str] = {
    "TimeoutError": "délai dépassé", "CancelledError": "interrompu", "PermissionError": "permission refusée",
    "FileNotFoundError": "fichier introuvable", "IsADirectoryError": "c'est un dossier, pas un fichier",
    "NotADirectoryError": "ce n'est pas un dossier", "FileExistsError": "le fichier existe déjà",
    "ConnectionRefusedError": "connexion refusée", "ConnectionResetError": "connexion coupée",
    "ConnectionError": "connexion impossible", "OSError": "erreur du système", "KeyError": "élément introuvable",
    "LookupError": "introuvable", "IndexError": "élément introuvable", "ValueError": "valeur refusée",
    "ZoneInfoNotFoundError": "fuseau horaire inconnu", "UnconfiguredRole": "aucun modèle configuré",
    "MissingPersona": "persona manquante", "PromptBudgetError": "prompt trop long pour le budget",
    "MemoryError": "mémoire épuisée", "RecursionError": "erreur interne (récursion)",
    "TypeError": "erreur interne (type inattendu)", "AttributeError": "erreur interne (attribut manquant)",
    "AssertionError": "erreur interne (vérification)", "NotImplementedError": "pas encore possible",
    "RuntimeError": "erreur", "StoreSealed": "magasin fermé", "ListingFailed": "liste indisponible",
    "ClaudeCodeError": "erreur de Claude Code", "ImapError": "erreur du serveur de courrier",
}
_PY_NAME = re.compile(r"^([A-Z][A-Za-z0-9_]*): ?(.*)$", re.S)
#: un ``repr`` d'exception gardé en texte (« TimeoutError() », « KeyError('x') »)
_PY_REPR = re.compile(r"^([A-Z][A-Za-z0-9_]*)\((.*)\)$", re.S)


def describe_error(error: BaseException | str) -> str:
    """Une erreur en français, pour un opérateur : son sens (« délai dépassé », « fichier
    introuvable »), puis son message s'il en a un — jamais un ``repr`` ni un nom de classe nu.
    Accepte une exception, un texte « NomDeClasse: message » ou un ``repr`` gardé en texte
    (« TimeoutError() », la dernière erreur d'un effet)."""
    if isinstance(error, BaseException):
        name = type(error).__name__
        if isinstance(error, OSError) and error.strerror:
            message = error.strerror + (f" : {error.filename}" if error.filename else "")
        elif isinstance(error, KeyError) and error.args:
            message = str(error.args[0])
        else:
            message = str(error)
    else:
        match = _PY_REPR.match(error.strip()) or _PY_NAME.match(error.strip())
        if match is None or not (match.group(1) in _ERRORS_FR or match.group(1).endswith(("Error", "Exception"))):
            return error.strip()
        name, message = match.group(1), match.group(2)
    message = message.strip().strip("'\"").strip()
    meaning = _ERRORS_FR.get(name)
    if meaning is None:
        return message or f"erreur inattendue ({name})"
    return f"{meaning} : {message}" if message and message.casefold() != meaning.casefold() else meaning


def rows(items: Sequence[Sequence[Cell]]) -> tuple[tuple[Cell, ...], ...]:
    return tuple(tuple(r) for r in items)


def walk_blocks(blocks: Sequence[Any]):
    """Parcourt toute composition, y compris navigation latérale et détails de ligne."""
    for b in blocks:
        yield b
        if isinstance(b, Workspace):
            yield from walk_blocks(b.sidebar)
        if isinstance(b, Grid | Workspace | Toolbar | Section | Disclosure):
            yield from walk_blocks(b.items)
        elif isinstance(b, Table):
            for row in b.rows:
                if isinstance(row, Row):
                    yield from walk_blocks(row.detail)
