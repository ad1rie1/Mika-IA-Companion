"""L'enveloppe JSON des vues d'apps forgées : ``{"version": 2, "blocks": [...]}``.

Une app forgée (écrite par le modèle, exécutée en bac à sable, donc non fiable)
rend ses vues d'opérateur en JSON. ``decode`` en fait des blocs du vocabulaire
de ``kernel/inspect.py`` ; ``encode`` fait l'inverse (tests, vues natives qui
veulent se sérialiser) ; ``schema`` publie le contrat en JSON Schema.

Contrat de ``decode`` :

- **jamais d'exception, jamais de rendu partiel** : à la première violation, la
  vue entière devient une seule ``Note(tone="danger", title="Vue invalide")``
  qui nomme le chemin JSON du problème (``blocks[2].rows[5][1] : …``) ;
- **clés fermées** partout (une clé inconnue invalide la vue), clés requises
  vérifiées, types **exacts** (``type(x) is str``, pas ``isinstance``) : un objet
  exotique qui redéfinirait ``__len__``, ``__eq__`` ou ``__hash__`` n'atteint
  jamais le code du décodeur, et ``True`` n'est pas un entier ;
- **bornes** (``Limits``) : imbrication, blocs au total, lignes, colonnes,
  éléments de liste, caractères par texte et au total, points d'une courbe,
  séries. Un texte trop long invalide la vue, il n'est jamais tronqué ;
- **liens** : une autre vue de la même app, résolue par la ``LinkPolicy`` de
  l'hôte (inconnue → invalide), ou une adresse ``http(s)`` avec un hôte, sans
  identifiants ni caractère de contrôle. Rien d'autre (``javascript:``,
  ``data:``, chemins relatifs, ``//hôte``) ;
- **émotions** : ``emotions`` est l'ensemble des noms canoniques, injecté par
  l'appelant (le noyau ne connaît pas ``mika.vocab``) ; vide, tout mot ascii en
  minuscules est admis.

Le formulaire (``"form"``) donne un ``ActionSlot`` dont ``action`` est la clé
*locale* à l'app : c'est à l'hôte de la qualifier (``<propriétaire>.<nom>``).
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from types import MappingProxyType
from typing import Any, NamedTuple, Protocol
from urllib.parse import urlsplit

from mika.kernel.inspect import (
    PAGE_PARAM,
    TONES,
    ActionSlot,
    Badge,
    Block,
    Chart,
    Code,
    Column,
    Disclosure,
    Entry,
    Fields,
    Grid,
    Meter,
    Nav,
    NavItem,
    Note,
    Pager,
    Prose,
    Ref,
    Row,
    Section,
    Series,
    Stat,
    Stats,
    Swatch,
    Table,
    Text,
    Timeline,
    Toolbar,
    When,
    Workspace,
    is_page_param,
    tone,
)

VERSION = 2


@dataclass(frozen=True, slots=True)
class Limits:
    """Les bornes d'une vue décodée. ``depth`` compte les niveaux de blocs (le
    détail d'une ligne et la tendance d'une statistique compris), ``blocks`` les
    blocs à toutes profondeurs, ``items`` les éléments d'une liste qui n'est ni
    de blocs, ni de lignes, ni de colonnes, ``points`` les points d'une courbe
    (toutes séries)."""

    depth: int = 8
    blocks: int = 200
    rows: int = 200
    columns: int = 30
    items: int = 200
    chars: int = 10_000
    total_chars: int = 300_000
    points: int = 2_000
    series: int = 4


class LinkPolicy(Protocol):
    """La résolution des liens vers une autre vue de la même app (fournie par
    l'hôte, qui sait de quelle app il s'agit). ``None`` : vue inconnue."""

    def view(self, key: str, params: Mapping[str, str]) -> Ref | None: ...


class Invalid(ValueError):
    """Une violation du contrat, au chemin JSON ``path`` (``""`` : la racine)."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path or 'enveloppe'} : {message}")
        self.path = path
        self.message = message


# ── Formes ────────────────────────────────────────────────────────────────


class _Shape(NamedTuple):
    required: tuple[str, ...]
    optional: tuple[str, ...]
    allowed: frozenset[str]


#: les langues d'un bloc ``code`` : un diff unifié se colore ligne à ligne
CODE_LANGS = ("diff",)


def _shape(required: tuple[str, ...], optional: tuple[str, ...] = ()) -> _Shape:
    return _Shape(required, optional, frozenset((*required, *optional)))


# Les clés de chaque objet (requises, facultatives). Le décodeur et le schéma
# lisent les mêmes tables : ils ne peuvent pas diverger.
_BLOCKS: dict[str, _Shape] = {
    "table": _shape(("type", "columns", "rows"), ("title", "caption", "empty", "pagination", "filters")),
    "fields": _shape(("type", "items"), ("title", "columns")),
    "note": _shape(("type", "text"), ("tone", "title")),
    "prose": _shape(("type", "text"), ("title", "clamp", "reading")),
    "code": _shape(("type", "text"), ("title", "lang")),
    "stats": _shape(("type", "items"), ("title",)),
    "timeline": _shape(("type", "items"), ("title", "empty")),
    "chart": _shape(("type", "series"),
                    ("kind", "title", "unit", "y", "zero", "since", "until", "empty", "table")),
    "workspace": _shape(("type", "sidebar", "items")),
    "toolbar": _shape(("type", "items"), ("title",)),
    "grid": _shape(("type", "items"), ("columns",)),
    "section": _shape(("type", "title", "items"), ("description",)),
    "disclosure": _shape(("type", "title", "items"), ("open",)),
    "form": _shape(("type", "action"), ("initial", "title", "compact", "presentation")),
    "nav": _shape(("type", "items"), ("title",)),
}
_TEXT_KINDS = ("text", "mono", "num", "muted")
_CELLS: dict[str, _Shape] = {
    **{k: _shape(("kind", "text"), ("tone", "hint", "clamp", "secondary", "emphasis")) for k in _TEXT_KINDS},
    "badge": _shape(("kind", "text"), ("tone",)),
    "meter": _shape(("kind", "ratio"), ("text", "tone")),
    "emotion": _shape(("kind", "key"), ("text", "weight")),
    "when": _shape(("kind", "at"), ("relative",)),
    "link": _shape(("kind", "text"), ("view", "params", "url")),
}
# un lien en position ``href`` (ligne, statistique, entrée) : texte facultatif
_HREF = _shape(("kind",), ("text", "view", "params", "url"))
_ENVELOPE = _shape(("version", "blocks"))
_COLUMN = _shape(("key", "label"), ("align", "hint", "detail"))
_ROW = _shape(("cells",), ("tone", "href", "detail"))
_PAGER = _shape(("page", "total", "per_page"), ("param",))
_FIELD = _shape(("label", "value"), ("hint",))
_STAT = _shape(("label", "value"), ("sub", "tone", "href", "trend"))
_ENTRY = _shape(("at", "title"), ("text", "meta", "tone", "href"))
_SERIES = _shape(("label", "points"), ("slot",))
_NAV_ITEM = _shape(("text", "href"), ("count", "active", "tone"))

# pré-contrôle avant de connaître le type : toute clé d'un bloc, d'une cellule
_ANY_BLOCK = _shape((), tuple(sorted({k for s in _BLOCKS.values() for k in s.allowed})))
_ANY_CELL = _shape((), tuple(sorted({k for s in _CELLS.values() for k in s.allowed})))

_I64 = 2**63 - 1
_URL_MAX = 2048
_ALIGNS = ("", "num", "fit")
_CHART_KINDS = ("line", "bars", "spark")
_UNITS = ("", "%", "$")
_SLOTS = 4
_GRID_COLUMNS = 3

_ACTION = re.compile(r"[a-z][a-z0-9_]{0,47}")
_PARAM = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}")
_VIEW = re.compile(r"[a-z][a-z0-9_-]{0,47}(?:/[a-z][a-z0-9_-]{0,47}){0,3}")
_WORD = re.compile(r"[a-z]{1,32}")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,47}")
# contrôles C0 (hors tabulation et fins de ligne), DEL, C1, demi-substituts
# (un substitut isolé ferait échouer l'encodage UTF-8 au rendu)
_FORBIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")

_KIND_FR: tuple[tuple[type, str], ...] = (
    (dict, "un objet"), (list, "une liste"), (tuple, "une liste"), (str, "un texte"),
    (bool, "un booléen"), (int, "un entier"), (float, "un nombre"), (type(None), "null"),
)


def _kind(value: Any) -> str:
    """Le genre d'une valeur, en français (comparaison d'identité : aucun code
    de la valeur n'est exécuté)."""
    t = type(value)
    for known, name in _KIND_FR:
        if t is known:
            return name
    return "une valeur d'un autre type"


def _is_list(value: Any) -> bool:
    t = type(value)
    return t is list or t is tuple


def _show(text: str, width: int = 40) -> str:
    """Un texte non fiable, montrable dans un message : court et imprimable."""
    head = "".join(c if c.isprintable() else "?" for c in text[:width])
    return head + ("…" if len(text) > width else "")


def _at(path: str, key: str) -> str:
    step = f".{key}" if _IDENT.fullmatch(key) else f"[« {_show(key)} »]"
    return f"{path}{step}" if path else step.removeprefix(".")


def _ix(path: str, index: int) -> str:
    return f"{path}[{index}]"


# ── Décodage ──────────────────────────────────────────────────────────────


def decode(payload: Any, *, links: LinkPolicy | None = None, limits: Limits = Limits(),
           emotions: frozenset[str] = frozenset()) -> list[Block]:
    """Les blocs d'une enveloppe, ou une seule note « Vue invalide » qui nomme
    le premier problème. ``links`` résout les liens vers les autres vues de
    l'app (absent : ces liens sont refusés) ; ``emotions`` : les noms admis
    pour une pastille d'émotion (vide : tout mot ascii en minuscules)."""
    decoder = _Decoder(links, limits, emotions)
    try:
        return decoder.envelope(payload)
    except Invalid as exc:
        text = str(exc)
    # une entrée pathologique (récursion, objet qui refuse une opération,
    # nombre démesuré) finit comme toute autre violation, jamais en exception
    except (RecursionError, TypeError, OverflowError) as exc:
        text = f"{decoder.where or 'enveloppe'} : contenu illisible ({type(exc).__name__})"
    return [Note(text, tone="danger", title="Vue invalide")]


class _Decoder:
    __slots__ = ("blocks_left", "chars_left", "emotions", "limits", "links", "where")

    def __init__(self, links: LinkPolicy | None, limits: Limits, emotions: frozenset[str]) -> None:
        self.links = links
        self.limits = limits
        self.emotions = emotions
        self.blocks_left = limits.blocks
        self.chars_left = limits.total_chars
        #: le chemin du dernier bloc abordé (pour une erreur sans chemin propre)
        self.where = ""

    # ── primitives ──

    def obj(self, value: Any, path: str, shape: _Shape) -> dict[str, Any]:
        if type(value) is not dict:
            raise Invalid(path, f"un objet est attendu, pas {_kind(value)}")
        for key in value:
            if type(key) is not str:
                raise Invalid(path, "clé non textuelle")
            if key not in shape.allowed:
                raise Invalid(path, f"champ inconnu « {_show(key)} »")
        for key in shape.required:
            if key not in value:
                raise Invalid(path, f"champ requis « {key} » manquant")
        return value

    def seq(self, value: Any, path: str, maximum: int, what: str) -> list[Any] | tuple[Any, ...]:
        if not _is_list(value):
            raise Invalid(path, f"une liste est attendue, pas {_kind(value)}")
        if len(value) > maximum:
            raise Invalid(path, f"plus de {maximum} {what}")
        return value

    def string(self, value: Any, path: str) -> str:
        if type(value) is not str:
            raise Invalid(path, f"un texte est attendu, pas {_kind(value)}")
        if len(value) > self.limits.chars:
            raise Invalid(path, f"texte de plus de {self.limits.chars} caractères")
        if _FORBIDDEN.search(value):
            raise Invalid(path, "caractère de contrôle ou invalide dans le texte")
        self.chars_left -= len(value)
        if self.chars_left < 0:
            raise Invalid(path, f"plus de {self.limits.total_chars} caractères au total")
        return value

    def integer(self, value: Any, path: str, lo: int = 0, hi: int = _I64) -> int:
        if type(value) is not int:
            raise Invalid(path, f"un entier est attendu, pas {_kind(value)}")
        if value < lo or value > hi:
            raise Invalid(path, f"entier hors de [{lo}, {hi}]")
        return value

    def number(self, value: Any, path: str) -> float:
        if type(value) is int:
            if -_I64 - 1 <= value <= _I64:
                return float(value)
            raise Invalid(path, "nombre hors bornes")
        if type(value) is not float:
            raise Invalid(path, f"un nombre est attendu, pas {_kind(value)}")
        if not math.isfinite(value):
            raise Invalid(path, "nombre non fini")
        return value

    def boolean(self, value: Any, path: str) -> bool:
        if type(value) is not bool:
            raise Invalid(path, f"un booléen est attendu, pas {_kind(value)}")
        return value

    def choice(self, value: Any, path: str, options: tuple[str, ...], unknown: str) -> str:
        """Une valeur d'une liste fermée ; ``unknown`` : « unité inconnue »…"""
        text = self.string(value, path)
        if text not in options:
            known = ", ".join(f"« {o} »" for o in options)
            raise Invalid(path, f"{unknown} « {_show(text)} » (au choix : {known})")
        return text

    def tone(self, value: Any, path: str) -> str:
        text = self.string(value, path)
        known = tone(text)
        if text and not known:
            raise Invalid(path, f"ton inconnu « {_show(text)} »")
        return known

    def mapping(self, value: Any, path: str, what: str) -> list[tuple[str, Any]]:
        """Un objet ouvert (paramètres, valeurs initiales) : des noms de
        paramètre, au plus ``items`` entrées."""
        if type(value) is not dict:
            raise Invalid(path, f"un objet est attendu, pas {_kind(value)}")
        if len(value) > self.limits.items:
            raise Invalid(path, f"plus de {self.limits.items} {what}")
        out: list[tuple[str, Any]] = []
        for key, item in value.items():
            if type(key) is not str or not _PARAM.fullmatch(key):
                shown = _show(key) if type(key) is str else _kind(key)
                raise Invalid(path, f"nom invalide « {shown} » (attendu : {_PARAM.pattern})")
            out.append((key, item))
        return out

    # ── cellules et liens ──

    def cell(self, value: Any, path: str) -> Any:
        t = type(value)
        if value is None or t is bool:
            return value
        if t is int:
            return self.integer(value, path, -_I64 - 1, _I64)
        if t is float:
            if not math.isfinite(value):
                raise Invalid(path, "nombre non fini")
            return value
        if t is str:
            return self.string(value, path)
        if t is not dict:
            raise Invalid(path, f"une cellule est un scalaire ou un objet, pas {_kind(value)}")
        self.obj(value, path, _ANY_CELL)
        if "kind" not in value:
            raise Invalid(path, "champ requis « kind » manquant")
        kind = value["kind"]
        if type(kind) is not str:
            raise Invalid(_at(path, "kind"), f"un texte est attendu, pas {_kind(kind)}")
        shape = _CELLS.get(kind)
        if shape is None:
            raise Invalid(path, f"type de cellule inconnu « {_show(kind)} »")
        if kind == "link":
            return self.link(value, path, shape)
        d = self.obj(value, path, shape)
        get = d.get
        if kind in _TEXT_KINDS:
            return Text(self.string(d["text"], _at(path, "text")), kind=kind,
                        tone=self.tone(get("tone", ""), _at(path, "tone")),
                        hint=self.string(get("hint", ""), _at(path, "hint")),
                        clamp=self.integer(get("clamp", 0), _at(path, "clamp"), 0, self.limits.chars),
                        secondary=self.string(get("secondary", ""), _at(path, "secondary")),
                        emphasis=self.boolean(get("emphasis", False), _at(path, "emphasis")))
        if kind == "badge":
            return Badge(self.string(d["text"], _at(path, "text")),
                         tone=self.tone(get("tone", ""), _at(path, "tone")))
        if kind == "meter":
            ratio = self.number(d["ratio"], _at(path, "ratio"))
            return Meter(min(1.0, max(0.0, ratio)), text=self.string(get("text", ""), _at(path, "text")),
                         tone=self.tone(get("tone", ""), _at(path, "tone")))
        if kind == "emotion":
            return self.swatch(d, path)
        return When(self.integer(d["at"], _at(path, "at")),
                    relative=self.boolean(get("relative", True), _at(path, "relative")))

    def swatch(self, d: dict[str, Any], path: str) -> Swatch:
        kp = _at(path, "key")
        key = self.string(d["key"], kp)
        if self.emotions:
            if key not in self.emotions:
                raise Invalid(kp, f"émotion inconnue « {_show(key)} »")
        elif not _WORD.fullmatch(key):
            raise Invalid(kp, f"émotion : un mot ascii en minuscules est attendu, pas « {_show(key)} »")
        weight = None
        if "weight" in d:
            weight = min(1.0, max(0.0, self.number(d["weight"], _at(path, "weight"))))
        return Swatch(self.string(d.get("text", key), _at(path, "text")), "emotion", key, weight)

    def link(self, value: Any, path: str, shape: _Shape = _HREF) -> Ref:
        d = self.obj(value, path, shape)
        kind = d["kind"]
        if type(kind) is not str or kind != "link":
            raise Invalid(_at(path, "kind"), "« link » est attendu")
        text = self.string(d.get("text", ""), _at(path, "text"))
        has_view, has_url = "view" in d, "url" in d
        if has_view == has_url:
            raise Invalid(path, "un lien porte soit « view », soit « url »")
        if has_url:
            if "params" in d:
                raise Invalid(_at(path, "params"), "« params » ne va qu'avec « view »")
            return Ref("url", self.url(d["url"], _at(path, "url")), text)
        vp = _at(path, "view")
        key = self.string(d["view"], vp)
        if not _VIEW.fullmatch(key):
            raise Invalid(vp, f"clé de vue invalide « {_show(key)} »")
        params = self.params(d.get("params", {}), _at(path, "params"))
        if self.links is None:
            raise Invalid(vp, "les liens vers une autre vue ne sont pas permis ici")
        ref = self.links.view(key, MappingProxyType(dict(params)))
        if not isinstance(ref, Ref):
            raise Invalid(vp, f"vue inconnue « {_show(key)} »")
        return replace(ref, text=text)

    def params(self, value: Any, path: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for key, item in self.mapping(value, path, "paramètres"):
            ip = _at(path, key)
            if type(item) is int:
                out.append((key, str(self.integer(item, ip, -_I64 - 1, _I64))))
            elif type(item) is str:
                out.append((key, self.string(item, ip)))
            else:
                raise Invalid(ip, f"un texte ou un entier est attendu, pas {_kind(item)}")
        return out

    def url(self, value: Any, path: str) -> str:
        """Une adresse ``http(s)://hôte…`` : ni identifiants, ni espace, ni
        caractère de contrôle ou invisible, ni barre oblique inverse."""
        text = self.string(value, path)
        if len(text) > _URL_MAX:
            raise Invalid(path, f"adresse de plus de {_URL_MAX} caractères")
        if not text.isprintable() or " " in text or "\\" in text:
            raise Invalid(path, "caractère interdit dans l'adresse")
        try:
            parts = urlsplit(text)
            port = parts.port
        except ValueError:
            raise Invalid(path, "adresse illisible") from None
        if parts.scheme.lower() not in ("http", "https"):
            raise Invalid(path, "seules les adresses http(s) sont permises")
        if not parts.netloc or not parts.hostname:
            raise Invalid(path, "adresse sans hôte")
        if "@" in parts.netloc or parts.username is not None or parts.password is not None:
            raise Invalid(path, "identifiants interdits dans l'adresse")
        if port == 0:
            raise Invalid(path, "port invalide")
        return text

    # ── blocs ──

    def envelope(self, payload: Any) -> list[Block]:
        d = self.obj(payload, "", _ENVELOPE)
        version = d["version"]
        if type(version) is not int or version != VERSION:
            raise Invalid("version", f"la version {VERSION} est attendue")
        return list(self.blocks(d["blocks"], "blocks", 1))

    def blocks(self, value: Any, path: str, depth: int) -> tuple[Block, ...]:
        if not _is_list(value):
            raise Invalid(path, f"une liste de blocs est attendue, pas {_kind(value)}")
        if len(value) > self.blocks_left:
            raise Invalid(path, f"plus de {self.limits.blocks} blocs au total")
        return tuple(self.block(item, _ix(path, i), depth) for i, item in enumerate(value))

    def block(self, value: Any, path: str, depth: int) -> Block:
        self.where = path
        if depth > self.limits.depth:
            raise Invalid(path, f"imbrication au-delà de {self.limits.depth} niveaux")
        self.blocks_left -= 1
        if self.blocks_left < 0:
            raise Invalid(path, f"plus de {self.limits.blocks} blocs au total")
        self.obj(value, path, _ANY_BLOCK)
        if "type" not in value:
            raise Invalid(path, "champ requis « type » manquant")
        kind = value["type"]
        if type(kind) is not str:
            raise Invalid(_at(path, "type"), f"un texte est attendu, pas {_kind(kind)}")
        shape = _BLOCKS.get(kind)
        if shape is None:
            raise Invalid(_at(path, "type"), f"type de bloc inconnu « {_show(kind)} »")
        d = self.obj(value, path, shape)
        match kind:
            case "table":
                return self.table(d, path, depth)
            case "fields":
                return self.fields(d, path)
            case "note":
                return Note(self.string(d["text"], _at(path, "text")),
                            tone=self.tone(d.get("tone", ""), _at(path, "tone")),
                            title=self.string(d.get("title", ""), _at(path, "title")))
            case "prose":
                return Prose(self.string(d["text"], _at(path, "text")),
                             title=self.string(d.get("title", ""), _at(path, "title")),
                             clamp=self.integer(d.get("clamp", 0), _at(path, "clamp"), 0, self.limits.chars),
                             reading=self.boolean(d.get("reading", False), _at(path, "reading")))
            case "code":
                lang = self.choice(d["lang"], _at(path, "lang"), ("", *CODE_LANGS), "langue inconnue") \
                    if "lang" in d else ""
                return Code(self.string(d["text"], _at(path, "text")),
                            title=self.string(d.get("title", ""), _at(path, "title")), lang=lang)
            case "stats":
                return self.stats(d, path, depth)
            case "timeline":
                return self.timeline(d, path)
            case "chart":
                return self.chart(d, path)
            case "workspace":
                return Workspace(self.blocks(d["sidebar"], _at(path, "sidebar"), depth + 1),
                                 self.blocks(d["items"], _at(path, "items"), depth + 1))
            case "toolbar":
                return Toolbar(self.blocks(d["items"], _at(path, "items"), depth + 1),
                               title=self.string(d.get("title", "Actions"), _at(path, "title")))
            case "grid":
                return Grid(self.blocks(d["items"], _at(path, "items"), depth + 1),
                            columns=self.integer(d.get("columns", 2), _at(path, "columns"), 1, _GRID_COLUMNS))
            case "section":
                return Section(self.string(d["title"], _at(path, "title")),
                               self.blocks(d["items"], _at(path, "items"), depth + 1),
                               description=self.string(d.get("description", ""), _at(path, "description")))
            case "disclosure":
                return Disclosure(self.string(d["title"], _at(path, "title")),
                                  self.blocks(d["items"], _at(path, "items"), depth + 1),
                                  open=self.boolean(d.get("open", False), _at(path, "open")))
            case "nav":
                return self.nav(d, path)
            case _:
                return self.form(d, path)

    def table(self, d: dict[str, Any], path: str, depth: int) -> Table:
        cpath = _at(path, "columns")
        columns: list[str | Column] = []
        keys: list[str] = []
        for i, raw in enumerate(self.seq(d["columns"], cpath, self.limits.columns, "colonnes")):
            p = _ix(cpath, i)
            column: str | Column
            if type(raw) is str:
                # une colonne nue est sa propre clé
                key = column = self.string(raw, p)
            else:
                c = self.obj(raw, p, _COLUMN)
                key = self.string(c["key"], _at(p, "key"))
                column = Column(self.string(c["label"], _at(p, "label")),
                                align=self.choice(c.get("align", ""), _at(p, "align"), _ALIGNS, "alignement inconnu"),
                                hint=self.string(c.get("hint", ""), _at(p, "hint")),
                                detail=self.boolean(c.get("detail", False), _at(p, "detail")))
            if not key:
                raise Invalid(p, "clé de colonne vide")
            if key in keys:
                raise Invalid(p, f"clé de colonne en double « {_show(key)} »")
            keys.append(key)
            columns.append(column)
        rpath = _at(path, "rows")
        rows = tuple(self.row(raw, _ix(rpath, i), keys, depth)
                     for i, raw in enumerate(self.seq(d["rows"], rpath, self.limits.rows, "lignes")))
        kw: dict[str, Any] = {}
        for name in ("title", "caption", "empty"):
            if name in d:
                kw[name] = self.string(d[name], _at(path, name))
        if "pagination" in d:
            kw["pager"] = self.pager(d["pagination"], _at(path, "pagination"), len(rows))
        if "filters" in d:
            kw["filters"] = self.filters(d["filters"], _at(path, "filters"))
        return Table(tuple(columns), rows, **kw)

    def row(self, raw: Any, path: str, keys: list[str], depth: int) -> tuple[Any, ...] | Row:
        if _is_list(raw):
            return self.cells(raw, path, len(keys))
        if type(raw) is not dict:
            raise Invalid(path, f"une ligne est une liste de cellules ou un objet, pas {_kind(raw)}")
        r = self.obj(raw, path, _ROW)
        cp = _at(path, "cells")
        values = r["cells"]
        if _is_list(values):
            cells = self.cells(values, cp, len(keys))
        elif type(values) is dict:
            # les clés doivent être exactement celles des colonnes
            for key in values:
                if type(key) is not str or key not in keys:
                    shown = _show(key) if type(key) is str else _kind(key)
                    raise Invalid(cp, f"colonne inconnue « {shown} »")
            for key in keys:
                if key not in values:
                    raise Invalid(cp, f"cellule manquante pour la colonne « {_show(key)} »")
            cells = tuple(self.cell(values[key], _at(cp, key)) for key in keys)
        else:
            raise Invalid(cp, f"une liste ou un objet de cellules est attendu, pas {_kind(values)}")
        href = self.link(r["href"], _at(path, "href")) if "href" in r else None
        detail = self.blocks(r["detail"], _at(path, "detail"), depth + 1) if "detail" in r else ()
        return Row(cells, href=href, tone=self.tone(r.get("tone", ""), _at(path, "tone")), detail=detail)

    def cells(self, values: list[Any] | tuple[Any, ...], path: str, count: int) -> tuple[Any, ...]:
        if len(values) != count:
            raise Invalid(path, f"{len(values)} cellules pour {count} colonnes")
        return tuple(self.cell(v, _ix(path, j)) for j, v in enumerate(values))

    def pager(self, value: Any, path: str, rows: int) -> Pager:
        p = self.obj(value, path, _PAGER)
        param = self.string(p.get("param", "page"), _at(path, "param"))
        if not is_page_param(param):
            raise Invalid(_at(path, "param"), "attendu : page ou page_<nom> (lettres minuscules, chiffres, _)")
        number = self.integer(p["page"], _at(path, "page"), 1)
        total = self.integer(p["total"], _at(path, "total"))
        size = self.integer(p["per_page"], _at(path, "per_page"), 1, self.limits.rows)
        last = max(1, -(-total // size))
        if number > last:
            raise Invalid(_at(path, "page"), f"page {number} au-delà de la dernière ({last})")
        room = min(size, total - (number - 1) * size)
        if rows > room:
            raise Invalid(path, f"{rows} lignes pour une page qui en compte au plus {room}")
        return Pager(param=param, number=number, size=size, total=total)

    def filters(self, value: Any, path: str) -> tuple[str, ...]:
        names: list[str] = []
        for i, raw in enumerate(self.seq(value, path, self.limits.items, "filtres")):
            name = self.string(raw, _ix(path, i))
            if not _PARAM.fullmatch(name) or name in names:
                raise Invalid(_ix(path, i), f"nom de filtre invalide ou en double « {_show(name)} »")
            names.append(name)
        return tuple(names)

    def fields(self, d: dict[str, Any], path: str) -> Fields:
        ipath = _at(path, "items")
        pairs: list[tuple[str, Any]] = []
        hints: list[tuple[str, str]] = []
        for i, raw in enumerate(self.seq(d["items"], ipath, self.limits.items, "champs")):
            p = _ix(ipath, i)
            f = self.obj(raw, p, _FIELD)
            label = self.string(f["label"], _at(p, "label"))
            pairs.append((label, self.cell(f["value"], _at(p, "value"))))
            hint = self.string(f.get("hint", ""), _at(p, "hint"))
            if hint:
                hints.append((label, hint))
        return Fields(tuple(pairs), title=self.string(d.get("title", ""), _at(path, "title")), hints=tuple(hints),
                      columns=self.integer(d.get("columns", 1), _at(path, "columns"), 1, _GRID_COLUMNS))

    def stats(self, d: dict[str, Any], path: str, depth: int) -> Stats:
        ipath = _at(path, "items")
        items: list[Stat] = []
        for i, raw in enumerate(self.seq(d["items"], ipath, self.limits.items, "statistiques")):
            p = _ix(ipath, i)
            s = self.obj(raw, p, _STAT)
            trend = None
            if "trend" in s:
                tp = _at(p, "trend")
                trend = self.block(s["trend"], tp, depth + 1)
                if not isinstance(trend, Chart):
                    raise Invalid(tp, "une courbe (« chart ») est attendue")
            items.append(Stat(self.string(s["label"], _at(p, "label")), self.cell(s["value"], _at(p, "value")),
                              sub=self.string(s.get("sub", ""), _at(p, "sub")),
                              tone=self.tone(s.get("tone", ""), _at(p, "tone")),
                              href=self.link(s["href"], _at(p, "href")) if "href" in s else None,
                              trend=trend))
        return Stats(tuple(items), title=self.string(d.get("title", ""), _at(path, "title")))

    def nav(self, d: dict[str, Any], path: str) -> Nav:
        ipath = _at(path, "items")
        items: list[NavItem] = []
        for i, raw in enumerate(self.seq(d["items"], ipath, self.limits.items, "liens")):
            p = _ix(ipath, i)
            n = self.obj(raw, p, _NAV_ITEM)
            count: int | str | None = None
            if "count" in n:
                cp = _at(p, "count")
                count = self.integer(n["count"], cp) if type(n["count"]) is int else self.string(n["count"], cp)
            items.append(NavItem(self.string(n["text"], _at(p, "text")), self.link(n["href"], _at(p, "href")),
                                 count=count, active=self.boolean(n.get("active", False), _at(p, "active")),
                                 tone=self.tone(n.get("tone", ""), _at(p, "tone"))))
        return Nav(tuple(items), title=self.string(d.get("title", ""), _at(path, "title")))

    def timeline(self, d: dict[str, Any], path: str) -> Timeline:
        ipath = _at(path, "items")
        entries: list[Entry] = []
        for i, raw in enumerate(self.seq(d["items"], ipath, self.limits.items, "entrées")):
            p = _ix(ipath, i)
            e = self.obj(raw, p, _ENTRY)
            entries.append(Entry(self.integer(e["at"], _at(p, "at")), self.string(e["title"], _at(p, "title")),
                                 text=self.string(e.get("text", ""), _at(p, "text")),
                                 tone=self.tone(e.get("tone", ""), _at(p, "tone")),
                                 href=self.link(e["href"], _at(p, "href")) if "href" in e else None,
                                 meta=self.string(e.get("meta", ""), _at(p, "meta"))))
        kw = {"empty": self.string(d["empty"], _at(path, "empty"))} if "empty" in d else {}
        return Timeline(tuple(entries), title=self.string(d.get("title", ""), _at(path, "title")), **kw)

    def chart(self, d: dict[str, Any], path: str) -> Chart:
        spath = _at(path, "series")
        budget = self.limits.points
        series: list[Series] = []
        for i, raw in enumerate(self.seq(d["series"], spath, self.limits.series, "séries")):
            p = _ix(spath, i)
            s = self.obj(raw, p, _SERIES)
            pp = _at(p, "points")
            points = self.seq(s["points"], pp, self.limits.points, "points")
            budget -= len(points)
            if budget < 0:
                raise Invalid(pp, f"plus de {self.limits.points} points au total")
            decoded: list[tuple[int, float]] = []
            for j, point in enumerate(points):
                q = _ix(pp, j)
                if not _is_list(point) or len(point) != 2:
                    raise Invalid(q, "un point est une paire [instant, valeur]")
                decoded.append((self.integer(point[0], _ix(q, 0)), self.number(point[1], _ix(q, 1))))
            series.append(Series(self.string(s["label"], _at(p, "label")), tuple(decoded),
                                 slot=self.integer(s.get("slot", 0), _at(p, "slot"), 0, _SLOTS)))
        kw: dict[str, Any] = {}
        if "kind" in d:
            kw["kind"] = self.choice(d["kind"], _at(path, "kind"), _CHART_KINDS, "genre de courbe inconnu")
        if "unit" in d:
            kw["unit"] = self.choice(d["unit"], _at(path, "unit"), _UNITS, "unité inconnue")
        for name in ("title", "empty"):
            if name in d:
                kw[name] = self.string(d[name], _at(path, name))
        if "y" in d:
            yp = _at(path, "y")
            bounds = self.seq(d["y"], yp, 2, "bornes")
            if len(bounds) != 2:
                raise Invalid(yp, "une paire [bas, haut] est attendue")
            lo, hi = self.number(bounds[0], _ix(yp, 0)), self.number(bounds[1], _ix(yp, 1))
            if not lo < hi:
                raise Invalid(yp, "le bas doit être inférieur au haut")
            kw["y"] = (lo, hi)
        if "zero" in d:
            kw["zero"] = self.number(d["zero"], _at(path, "zero"))
        for name in ("since", "until"):
            if name in d:
                kw[name] = self.integer(d[name], _at(path, name))
        if "since" in kw and "until" in kw and kw["since"] > kw["until"]:
            raise Invalid(_at(path, "since"), "« since » est postérieur à « until »")
        if "table" in d:
            kw["table"] = self.boolean(d["table"], _at(path, "table"))
        return Chart(tuple(series), **kw)

    def form(self, d: dict[str, Any], path: str) -> ActionSlot:
        ap = _at(path, "action")
        action = self.string(d["action"], ap)
        if not _ACTION.fullmatch(action):
            raise Invalid(ap, f"clé d'action invalide « {_show(action)} » (attendu : {_ACTION.pattern})")
        ip = _at(path, "initial")
        initial = tuple((key, self.scalar_text(item, _at(ip, key)))
                        for key, item in self.mapping(d.get("initial", {}), ip, "valeurs initiales"))
        return ActionSlot(action, initial=initial, title=self.string(d.get("title", ""), _at(path, "title")),
                          compact=self.boolean(d.get("compact", False), _at(path, "compact")),
                          presentation=self.choice(d.get("presentation", "form"), _at(path, "presentation"),
                                                   ("form", "button"), "présentation inconnue"))

    def scalar_text(self, value: Any, path: str) -> str:
        """Une valeur initiale de formulaire, en texte (vrai → ``"1"``, faux et
        ``null`` → ``""``)."""
        t = type(value)
        if value is None or value is False:
            return ""
        if value is True:
            return "1"
        if t is int:
            return str(self.integer(value, path, -_I64 - 1, _I64))
        if t is float:
            return repr(self.number(value, path))
        if t is str:
            return self.string(value, path)
        raise Invalid(path, f"une valeur scalaire est attendue, pas {_kind(value)}")


# ── Encodage ──────────────────────────────────────────────────────────────


@functools.cache
def _defaults(cls: type) -> dict[str, Any]:
    return {f.name: f.default for f in fields(cls)}


def _put(out: dict[str, Any], obj: Any, *names: str) -> None:
    """Ajoute les attributs qui diffèrent de leur valeur par défaut."""
    defaults = _defaults(type(obj))
    for name in names:
        value = getattr(obj, name)
        if value != defaults[name]:
            out[name] = value


def encode(blocks: Sequence[Block]) -> dict[str, Any]:
    """L'enveloppe de ces blocs, que ``decode`` relit à l'identique (un lien de
    vue s'encode par sa clé : la ``LinkPolicy`` du décodage doit la reconnaître).
    Ce que l'enveloppe ne sait pas dire (un lien d'épisode, une pagination par
    curseur, une autre palette…) lève ``ValueError``."""
    return {"version": VERSION, "blocks": [_enc_block(b) for b in blocks]}


def _enc_block(b: Any) -> dict[str, Any]:
    match b:
        case Table():
            return _enc_table(b)
        case Fields():
            return _enc_fields(b)
        case Note():
            out = {"type": "note", "text": b.text}
            _put(out, b, "tone", "title")
            return out
        case Prose():
            if b.html:
                raise ValueError("le HTML natif ne fait pas partie du langage Forge")
            out = {"type": "prose", "text": b.text}
            _put(out, b, "title", "clamp", "reading")
            return out
        case Code():
            out = {"type": "code", "text": b.text}
            _put(out, b, "title", "lang")
            return out
        case Stats():
            out = {"type": "stats", "items": [_enc_stat(s) for s in b.items]}
            _put(out, b, "title")
            return out
        case Timeline():
            out = {"type": "timeline", "items": [_enc_entry(e) for e in b.entries]}
            _put(out, b, "title", "empty")
            return out
        case Chart():
            return _enc_chart(b)
        case Workspace():
            return {"type": "workspace", "sidebar": [_enc_block(x) for x in b.sidebar],
                    "items": [_enc_block(x) for x in b.items]}
        case Toolbar():
            out = {"type": "toolbar", "items": [_enc_block(x) for x in b.items]}
            _put(out, b, "title")
            return out
        case Grid():
            out = {"type": "grid", "items": [_enc_block(x) for x in b.items]}
            _put(out, b, "columns")
            return out
        case Section():
            out = {"type": "section", "title": b.title, "items": [_enc_block(x) for x in b.items]}
            _put(out, b, "description")
            return out
        case Disclosure():
            out = {"type": "disclosure", "title": b.title, "items": [_enc_block(x) for x in b.items]}
            _put(out, b, "open")
            return out
        case Nav():
            items = []
            for i in b.items:
                item: dict[str, Any] = {"text": i.text, "href": _enc_link(i.href)}
                _put(item, i, "count", "active", "tone")
                items.append(item)
            out = {"type": "nav", "items": items}
            _put(out, b, "title")
            return out
        case ActionSlot():
            out = {"type": "form", "action": b.action}
            if b.initial:
                out["initial"] = dict(b.initial)
            _put(out, b, "title", "compact", "presentation")
            return out
    raise ValueError(f"bloc non exprimable dans l'enveloppe : {type(b).__name__}")


def _enc_table(t: Table) -> dict[str, Any]:
    used = {c for c in t.columns if isinstance(c, str)}
    columns: list[Any] = []
    for i, c in enumerate(t.columns):
        if isinstance(c, str):
            columns.append(c)
            continue
        key = f"c{i}"
        while key in used:
            key += "_"
        used.add(key)
        col = {"key": key, "label": c.label}
        _put(col, c, "align", "hint", "detail")
        columns.append(col)
    out: dict[str, Any] = {"type": "table", "columns": columns, "rows": [_enc_row(r) for r in t.rows]}
    _put(out, t, "title", "caption", "empty")
    if t.pager is not None:
        p = t.pager
        if not is_page_param(p.param) or p.older or p.total is None:
            raise ValueError("pagination non exprimable dans l'enveloppe (page ou page_<nom>, avec un total)")
        out["pagination"] = {"page": p.number, "total": p.total, "per_page": p.size}
        if p.param != "page":
            out["pagination"]["param"] = p.param
    if t.filters:
        out["filters"] = list(t.filters)
    return out


def _enc_row(r: Any) -> Any:
    if not isinstance(r, Row):
        return [_enc_cell(c) for c in r]
    out: dict[str, Any] = {"cells": [_enc_cell(c) for c in r.cells]}
    _put(out, r, "tone")
    if r.href is not None:
        out["href"] = _enc_link(r.href)
    if r.detail:
        out["detail"] = [_enc_block(x) for x in r.detail]
    return out


def _enc_fields(f: Fields) -> dict[str, Any]:
    # les aides s'accrochent, dans l'ordre, au premier champ de même libellé
    pending = list(f.hints)
    items: list[dict[str, Any]] = []
    for label, value in f.pairs:
        item = {"label": label, "value": _enc_cell(value)}
        if pending and pending[0][0] == label:
            item["hint"] = pending.pop(0)[1]
        items.append(item)
    if pending:
        raise ValueError("aides de champs non exprimables (un libellé absent, ou hors de l'ordre des champs)")
    out: dict[str, Any] = {"type": "fields", "items": items}
    _put(out, f, "title", "columns")
    return out


def _enc_stat(s: Stat) -> dict[str, Any]:
    out: dict[str, Any] = {"label": s.label, "value": _enc_cell(s.value)}
    _put(out, s, "sub", "tone")
    if s.href is not None:
        out["href"] = _enc_link(s.href)
    if s.trend is not None:
        out["trend"] = _enc_chart(s.trend)
    return out


def _enc_entry(e: Entry) -> dict[str, Any]:
    out: dict[str, Any] = {"at": e.at, "title": e.title}
    _put(out, e, "text", "meta", "tone")
    if e.href is not None:
        out["href"] = _enc_link(e.href)
    return out


def _enc_chart(c: Chart) -> dict[str, Any]:
    series = []
    for s in c.series:
        item: dict[str, Any] = {"label": s.label, "points": [[at, v] for at, v in s.points]}
        _put(item, s, "slot")
        series.append(item)
    out: dict[str, Any] = {"type": "chart", "series": series}
    _put(out, c, "kind", "title", "unit", "zero", "since", "until", "empty", "table")
    if c.y is not None:
        out["y"] = list(c.y)
    return out


def _enc_cell(c: Any) -> Any:
    if c is None or isinstance(c, (bool, int, float, str)):
        return c
    match c:
        case Ref():
            return _enc_link(c)
        case Text():
            out = {"kind": c.kind, "text": c.text}
            _put(out, c, "tone", "hint", "clamp", "secondary", "emphasis")
            return out
        case Badge():
            out = {"kind": "badge", "text": c.text}
            _put(out, c, "tone")
            return out
        case Meter():
            out = {"kind": "meter", "ratio": c.ratio}
            _put(out, c, "text", "tone")
            return out
        case Swatch():
            if c.palette != "emotion":
                raise ValueError(f"palette « {c.palette} » non exprimable dans l'enveloppe")
            out = {"kind": "emotion", "key": c.key, "text": c.text}
            _put(out, c, "weight")
            return out
        case When():
            out = {"kind": "when", "at": c.at}
            _put(out, c, "relative")
            return out
    raise ValueError(f"cellule non exprimable dans l'enveloppe : {type(c).__name__}")


def _enc_link(ref: Ref) -> dict[str, Any]:
    if ref.kind == "url":
        return {"kind": "link", "text": ref.text, "url": ref.key}
    if ref.kind == "view":
        out: dict[str, Any] = {"kind": "link", "text": ref.text, "view": ref.key}
        if ref.params:
            out["params"] = dict(ref.params)
        return out
    raise ValueError(f"lien « {ref.kind} » non exprimable dans l'enveloppe (seuls « view » et « url » le sont)")


# ── Schéma ────────────────────────────────────────────────────────────────


def _pattern(regex: re.Pattern[str]) -> str:
    return f"^{regex.pattern}$"


def _obj(shape: _Shape, props: Mapping[str, Any]) -> dict[str, Any]:
    """Un objet fermé : ses propriétés sont exactement celles de la forme
    (une clé sans schéma lève ``KeyError`` : la table et le schéma divergent)."""
    return {"type": "object", "properties": {k: props[k] for k in (*shape.required, *shape.optional)},
            "required": list(shape.required), "additionalProperties": False}


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/$defs/{name}"}


def _array(items: Any, maximum: int) -> dict[str, Any]:
    return {"type": "array", "items": items, "maxItems": maximum}


def schema(*, limits: Limits = Limits()) -> dict[str, Any]:
    """Le JSON Schema (draft 2020-12) de l'enveloppe. Tout objet y est fermé
    (``additionalProperties: false``), sauf les dictionnaires ouverts par nature
    (paramètres d'un lien, valeurs initiales, cellules par colonne), dont les
    noms sont contraints par ``propertyNames``. Le schéma est plus large que le
    décodeur sur ce qu'il ne sait pas dire (cohérence des colonnes et de la
    pagination, totaux, vues connues, noms d'émotions injectés)."""
    text = {"type": "string", "maxLength": limits.chars}
    tones = {"enum": list(TONES)}
    number = {"type": "number"}
    flag = {"type": "boolean"}
    instant = {"type": "integer", "minimum": 0, "maximum": _I64}
    clamp = {"type": "integer", "minimum": 0, "maximum": limits.chars}
    param_name = {"type": "string", "pattern": _pattern(_PARAM)}
    scalar = {"type": ["string", "number", "boolean", "null"], "maxLength": limits.chars}
    blocks = _array(_ref("block"), limits.blocks)

    link_props = {"kind": {"const": "link"}, "text": text,
                  "view": {"type": "string", "pattern": _pattern(_VIEW)},
                  "params": {"type": "object", "maxProperties": limits.items, "propertyNames": param_name,
                             "additionalProperties": {"type": ["string", "integer"], "maxLength": limits.chars}},
                  "url": {"type": "string", "maxLength": _URL_MAX,
                          "pattern": r"^[Hh][Tt][Tt][Pp][Ss]?://[^/?#@\s\\]+(?:[/?#][^\s\\]*)?$"}}
    view_link = _obj(_shape(("kind", "view"), ("text", "params")), link_props)
    url_link = _obj(_shape(("kind", "url"), ("text",)), link_props)

    cell_props = {"text": text, "tone": tones, "hint": text, "clamp": clamp, "ratio": number,
                  "key": {"type": "string", "pattern": _pattern(_WORD)}, "weight": number,
                  "at": instant, "relative": flag, "secondary": text, "emphasis": flag}
    cells: list[Any] = [scalar]
    for kind, shape in _CELLS.items():
        if kind == "link":
            cells.append({"allOf": [_ref("link"), {"required": ["text"]}]})
        else:
            cells.append(_obj(shape, {**cell_props, "kind": {"const": kind}}))

    column = _obj(_COLUMN, {"key": {"type": "string", "minLength": 1, "maxLength": limits.chars}, "label": text,
                            "align": {"enum": list(_ALIGNS)}, "hint": text, "detail": {"type": "boolean"}})
    cell_list = _array(_ref("cell"), limits.columns)
    cell_map = {"type": "object", "maxProperties": limits.columns,
                "propertyNames": {"minLength": 1, "maxLength": limits.chars}, "additionalProperties": _ref("cell")}
    row = _obj(_ROW, {"cells": {"oneOf": [cell_list, cell_map]}, "tone": tones, "href": _ref("link"),
                      "detail": blocks})
    pager = _obj(_PAGER, {"page": {"type": "integer", "minimum": 1, "maximum": _I64}, "total": instant,
                          "per_page": {"type": "integer", "minimum": 1, "maximum": limits.rows},
                          "param": {"type": "string", "pattern": "^" + PAGE_PARAM + "$"}})
    point = {"type": "array", "prefixItems": [instant, number], "items": False, "minItems": 2}
    series = _obj(_SERIES, {"label": text, "points": _array(point, limits.points),
                            "slot": {"type": "integer", "minimum": 0, "maximum": _SLOTS}})
    columns_1_3 = {"type": "integer", "minimum": 1, "maximum": _GRID_COLUMNS}

    common = {"title": text, "caption": text, "empty": text, "text": text, "tone": tones, "description": text,
              "open": flag, "reading": flag, "compact": flag, "clamp": clamp, "presentation": {"enum": ["form", "button"]}}
    specific: dict[str, dict[str, Any]] = {
        "table": {"columns": _array({"oneOf": [{"type": "string", "minLength": 1, "maxLength": limits.chars},
                                               _ref("column")]}, limits.columns),
                  "rows": _array({"oneOf": [cell_list, _ref("row")]}, limits.rows),
                  "pagination": _ref("pagination"),
                  "filters": {**_array(param_name, limits.items), "uniqueItems": True}},
        "fields": {"items": _array(_obj(_FIELD, {"label": text, "value": _ref("cell"), "hint": text}),
                                   limits.items),
                   "columns": columns_1_3},
        "note": {}, "prose": {}, "code": {"lang": {"enum": ["", *CODE_LANGS]}},
        "stats": {"items": _array(_obj(_STAT, {"label": text, "value": _ref("cell"), "sub": text, "tone": tones,
                                               "href": _ref("link"), "trend": _ref("chart")}), limits.items)},
        "timeline": {"items": _array(_obj(_ENTRY, {"at": instant, "title": text, "text": text, "meta": text,
                                                   "tone": tones, "href": _ref("link")}), limits.items)},
        "chart": {"kind": {"enum": list(_CHART_KINDS)}, "series": _array(series, limits.series),
                  "unit": {"enum": list(_UNITS)},
                  "y": {"type": "array", "prefixItems": [number, number], "items": False, "minItems": 2},
                  "zero": number, "since": instant, "until": instant, "table": flag},
        "workspace": {"items": blocks, "sidebar": blocks},
        "toolbar": {"items": blocks},
        "grid": {"items": blocks, "columns": columns_1_3},
        "section": {"items": blocks},
        "disclosure": {"items": blocks},
        "nav": {"items": _array(_obj(_NAV_ITEM, {"text": text, "href": _ref("link"), "tone": tones, "active": flag,
                                                 "count": {"oneOf": [{"type": "integer", "minimum": 0,
                                                                      "maximum": _I64}, text]}}), limits.items)},
        "form": {"action": {"type": "string", "pattern": _pattern(_ACTION)},
                 "initial": {"type": "object", "maxProperties": limits.items, "propertyNames": param_name,
                             "additionalProperties": scalar}},
    }
    variants = {kind: _obj(shape, {**common, **specific[kind], "type": {"const": kind}})
                for kind, shape in _BLOCKS.items()}
    # aiguillage sur « type » (``if``/``then``) plutôt qu'un ``oneOf`` : seule la
    # variante désignée descend dans les enfants, la validation reste linéaire
    # (un ``oneOf`` descendrait trois fois — grille, section, dépliant — à
    # chaque niveau d'imbrication)
    dispatch = {"type": "object", "required": ["type"],
                "properties": {**{k: {} for k in _ANY_BLOCK.optional}, "type": {"enum": list(variants)}},
                "additionalProperties": False,
                "allOf": [{"if": {"properties": {"type": {"const": kind}}}, "then": _ref(f"block_{kind}")}
                          for kind in variants]}
    defs: dict[str, Any] = {
        "block": dispatch,
        **{f"block_{kind}": variant for kind, variant in variants.items()},
        "chart": _ref("block_chart"),
        "cell": {"oneOf": cells},
        "link": {"oneOf": [view_link, url_link]},
        "column": column,
        "row": row,
        "pagination": pager,
    }
    envelope = _obj(_ENVELOPE, {"version": {"const": VERSION}, "blocks": blocks})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Mika — enveloppe des vues d'apps forgées", **envelope, "$defs": defs}
