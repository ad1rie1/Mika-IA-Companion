"""Les onglets des destinations, chacun dans sa forme (ADR 0177) : un module par destination (``vie``, ``memoire``…)
déclare ses onglets (``TABS`` : « destination/onglet » → ``Tab``), que ``pages.DRAWN`` réunit.

Un onglet lit les blocs que sa faculté déclare, rendus une fois et numérotés comme la console les numérote : leurs
ancres, leur pagination, leur bascule « Tableau » et les jetons de leurs formulaires restent ceux de la console
(``Got``). Il en fait la page qu'il veut, sur le vocabulaire commun des pages dessinées (``handmade/shared/tab.html``,
``handmade/base.css``) ; il lit aussi les faits d'une faculté quand ses blocs ne disent pas ce que la page montre
(``Look``). Un bloc qu'il attend et ne trouve pas (un titre changé) : il rend ``None``, et la console retombe sur les
blocs — la vue de la faculté reste la source, pour la console en MCP comme pour ce repli.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from markupsafe import Markup

from mika.app.handmade.blocks import head, lift
from mika.app.handmade.lists import Roles, shaped_as
from mika.inspector import render
from mika.inspector.ui import UI, Drawn, env
from mika.kernel.inspect import Column, Row, Table, When

#: les sortes de blocs rendus qui en contiennent d'autres
NESTED = ("disclosure", "grid", "section", "toolbar")
#: le titre que la console donne aux colonnes qu'une liste replie dans le détail de ses lignes
FOLDED = "Informations complémentaires"


def text(c: Mapping[str, Any] | None) -> str:
    """Le texte d'une cellule rendue (vide : pas de cellule)."""
    return str((c or {}).get("text") or "")


def blank(c: Mapping[str, Any] | None) -> bool:
    """Une cellule qui ne dit rien : absente, vide ou « — »."""
    return text(c).strip() in ("", "—")


@dataclass(slots=True)
class Line:
    """Une ligne d'une liste de la faculté, rendue : ses cellules par le libellé de leur colonne (``c``), celles
    que la faculté range au détail (``extra`` : ses colonnes repliées), son lien, son ton, son détail (des blocs
    rendus : ``inner`` dans un gabarit) ; et, pour une liste qui déclare ses rôles, son titre, ses étiquettes, son
    texte et ses faits."""

    c: dict[str, dict[str, Any]]
    extra: dict[str, dict[str, Any]]
    href: str
    tone: str
    detail: list[dict[str, Any]]
    open: bool
    row: dict[str, Any]

    def get(self, label: str) -> dict[str, Any] | None:
        """Une cellule, visible ou repliée, par le libellé de sa colonne."""
        return self.c.get(label) or self.extra.get(label)

    def text(self, label: str) -> str:
        return text(self.get(label))

    def __getitem__(self, label: str) -> dict[str, Any]:
        return self.get(label) or {"t": "text", "text": "—", "kind": "muted"}

    @property
    def rest(self) -> list[dict[str, Any]]:
        """Son détail sans les colonnes repliées (que ``extra`` a déjà lues)."""
        return [d for d in self.detail if not (d.get("t") == "fields" and d.get("title") == FOLDED)]


def lines(table: Mapping[str, Any] | None) -> list[Line]:
    """Les lignes d'une liste rendue, prêtes à lire par colonne."""
    if not table:
        return []
    labels = [c["label"] for c in table["columns"]]
    out = []
    for r in table["rows"]:
        extra: dict[str, dict[str, Any]] = {}
        for d in r.get("detail", []):
            if d.get("t") == "fields" and d.get("title") == FOLDED:
                extra.update({p["label"]: p["value"] for p in d["pairs"]})
        out.append(Line(dict(zip(labels, r["cells"], strict=False)), extra, r.get("href", ""), r.get("tone", ""),
                        r.get("detail", []), bool(r.get("open")), r))
    return out


def pairs(fields: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Les faits d'un bloc ``Fields`` rendu, par leur libellé."""
    return {p["label"]: p["value"] for p in (fields or {}).get("pairs", [])}


def tiles(stats: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Les chiffres d'un bloc ``Stats`` rendu, par leur libellé (leur valeur, leur sous-titre, leur ton, leur
    lien)."""
    return {s["label"]: s for s in (stats or {}).get("items", [])}


def instant(c: Any) -> int:
    """L'instant d'une cellule déclarée (0 : ce n'est pas un instant)."""
    return c.at if isinstance(c, When) and c.at else 0


def gauge(c: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Une jauge rendue : sa part en largeur (0–100), son texte, son ton ; rien si la cellule n'en est pas une."""
    if not c or c.get("t") != "meter":
        return None
    return {"w": round(100 * c["ratio"], 1), "text": c["text"], "tone": c.get("tone") or ""}


def number(c: Mapping[str, Any] | None) -> float | None:
    """Un nombre écrit à la française dans une cellule (« 0,040 ») ; rien s'il n'y en a pas."""
    try:
        return float(text(c).split()[0].replace(",", "."))
    except (ValueError, IndexError):
        return None


def rest(line: Line, shown: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Le détail d'une ligne, et ce que ses colonnes repliées disent que la page ne montre pas déjà (``shown`` : leurs
    libellés) — son numéro, son importance… : rien ne se perd de ce que la faculté donne."""
    out, known = list(line.rest), set(shown)
    for d in line.detail:
        if d.get("t") == "fields" and d.get("title") == FOLDED:
            left = [p for p in d["pairs"] if p["label"] not in known]
            if left:
                out.append({**d, "pairs": left})
    return out


def subpanes(panes: Sequence[dict[str, Any]], first: str = "") -> list[dict[str, Any]]:
    """Des sous-onglets, celui qu'on feuillette en premier : une page plus ancienne d'une liste revient sans ancre,
    et la console montre alors la première section."""
    return sorted(panes, key=lambda p: p["id"] != first) if first else list(panes)


def anchored(table: dict[str, Any] | None, pane: str) -> dict[str, Any] | None:
    """Une liste dans un sous-onglet : ses liens de pagination y reviennent (l'ancre de sa section), au lieu du
    premier. Seuls les liens changent (« first » d'une pagination numérotée est un rang, pas un lien)."""
    p = (table or {}).get("pager")
    if not p:
        return table
    for key in ("prev", "next", "older", "newer", "first"):
        if isinstance(p.get(key), str) and p[key].startswith("?"):
            p[key] = f"{p[key]}#{pane}"
    for link in p.get("links", []):
        if link.get("href"):
            link["href"] = f"{link['href']}#{pane}"
    return table


def _declared(blocks: Sequence[Any]) -> Iterator[Table]:
    """Les listes telles que la faculté les a déclarées, celles des grilles, des replis et des espaces de travail
    comprises."""
    for b in blocks:
        if isinstance(b, Table):
            yield b
            continue
        for attr in ("items", "sidebar"):
            inner = getattr(b, attr, None)
            if isinstance(inner, tuple | list):
                yield from _declared(inner)


def raw_lines(got: Got, table: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Les cellules telles que la faculté les a déclarées (un instant, un lien, une jauge) derrière chaque ligne
    rendue d'une liste, par le libellé de leur colonne : celles de la page montrée, dans le même ordre."""
    if not table:
        return []
    found = got.raw_table(str(table.get("title") or ""))
    if found is None:
        return []
    rows = [r if isinstance(r, Row) else Row(tuple(r)) for r in found.rows]
    if found.pager is None:  # une liste que le rendu pagine : sa page commence plus loin
        rows = rows[max(0, int((table.get("pager") or {}).get("first") or 1) - 1):]
    labels = [c.label if isinstance(c, Column) else str(c) for c in found.columns]
    return [dict(zip(labels, r.cells, strict=False)) for r in rows[:len(table["rows"])]]


def paged(table: Mapping[str, Any] | None) -> bool:
    """Une liste qui a plus d'une page."""
    p = (table or {}).get("pager") or {}
    return any(p.get(k) for k in ("prev", "next", "older", "newer"))


@dataclass(slots=True)
class Got:
    """Les blocs d'un onglet, rendus comme la console les rend (``items``), à lire par sorte et par titre ; et ce
    qu'il faut pour en faire une page : la console (``ui``), les paramètres de l'adresse (``query``), l'affichage
    des dates (``env``), les blocs tels que la faculté les a déclarés (``raw``), les formulaires que la console a
    préparés pour leurs actions (``forms``)."""

    ui: UI
    raw: list[Any]
    query: Mapping[str, str]
    forms: Mapping[str, Any]
    env: render.Env = field(init=False)
    items: list[dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        self.env = self.ui.env()
        self.items = render.blocks(self.raw, self.env, self.query)

    def walk(self, items: Sequence[dict[str, Any]] | None = None) -> Iterator[dict[str, Any]]:
        """Tous les blocs rendus, ceux qu'un repli, une grille, une section ou un espace de travail contiennent
        compris, dans l'ordre de la page (le détail d'une ligne n'en est pas)."""
        for b in self.items if items is None else items:
            yield b
            if b.get("t") in NESTED:
                yield from self.walk(b.get("items", []))
            elif b.get("t") == "workspace":
                yield from self.walk(b.get("sidebar", []) + b.get("items", []))

    def every(self, t: str, title: str = "") -> list[dict[str, Any]]:
        """Les blocs de cette sorte dont le titre commence par ``title``."""
        return [b for b in self.walk() if b.get("t") == t and str(b.get("title") or "").startswith(title)]

    def first(self, t: str, title: str = "") -> dict[str, Any] | None:
        return next(iter(self.every(t, title)), None)

    def table(self, title: str = "") -> dict[str, Any] | None:
        return self.first("table", title)

    def stats(self, title: str = "") -> dict[str, Any] | None:
        return self.first("stats", title)

    def fields(self, title: str = "") -> dict[str, Any] | None:
        return self.first("fields", title)

    def chart(self, title: str = "") -> dict[str, Any] | None:
        return self.first("chart", title)

    def timeline(self, title: str = "") -> dict[str, Any] | None:
        return self.first("timeline", title)

    def disclosure(self, title: str = "") -> dict[str, Any] | None:
        return self.first("disclosure", title)

    def notes(self) -> list[dict[str, Any]]:
        """Les notes de la page (à la racine et dans ses replis), dans l'ordre."""
        return self.every("note")

    def nav(self, title: str = "") -> dict[str, Any] | None:
        return self.first("nav", title)

    def toolbar(self) -> dict[str, Any] | None:
        return self.first("toolbar")

    def actions(self) -> list[dict[str, Any]]:
        """Les actions de la page (hors du détail des lignes)."""
        return self.every("action")

    def raw_table(self, title: str = "") -> Table | None:
        """La première liste, telle que la faculté l'a déclarée (ses cellules : un instant, un lien), dont le titre
        commence par ``title``."""
        return next((t for t in _declared(self.raw) if t.title.startswith(title)), None)

    def lines(self, title: str = "") -> list[Line]:
        """Les lignes de la première liste dont le titre commence par ``title``."""
        return lines(self.table(title))

    def card(self, table: dict[str, Any] | None, roles: Roles | None = None) -> dict[str, Any] | None:
        """Une liste rendue, prête pour ``entries`` (``handmade/shared/list_macros.html``) : une carte par élément."""
        return shaped_as(table, roles=roles) if table else None

    def head(self, links: Sequence[tuple[str, str]] = (), items: Sequence[Mapping[str, Any]] = ()) -> Markup:
        """Les actions de la page, pour sa barre de titre (ADR 0176)."""
        return head(links, items, self.forms)

    def lift(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """La barre d'outils de la page (ses actions, pour la barre de titre), et les autres blocs."""
        return lift(self.items)

    def draw(self, template: str, **context: Any) -> Markup:
        """Un gabarit de ``handmade/``, avec les formulaires de la page (``forms``) et les tableaux sobres
        (``tables``) que les macros des pages dessinées lisent."""
        context.setdefault("forms", self.forms)
        context.setdefault("tables", "table")
        return Markup(env.get_template(template).render(**context))


class Tab(Drawn):
    """Un onglet dans sa forme (ADR 0177) : ``draw(got)`` rend son HTML, un couple (HTML, blocs que la console rend
    après), un triplet (HTML, blocs, actions de la page pour la barre de titre), ou ``None`` (ses blocs, tels
    quels). ``styles`` : les feuilles de ses gabarits (sous ``static/``), en plus de ``handmade/base.css`` ;
    ``panel`` faux : il dit lui-même ce que disait le panneau de l'onglet ; ``last`` : son HTML vient après les
    blocs et le panneau que la console garde."""

    def __init__(self, draw: Callable[[Got], Any], *styles: str, panel: bool = True, last: bool = False) -> None:
        self.draw = draw
        self.styles = styles
        self.panel, self.last = panel, last

    def render(self, ui: UI, items: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        return self.draw(Got(ui, list(items), query, forms or {}))
