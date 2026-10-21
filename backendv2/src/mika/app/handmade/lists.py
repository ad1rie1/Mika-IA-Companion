"""Une liste d'une faculté, dessinée en cartes (ADR 0121) : ce que partagent les pages et les onglets dessinés qui
montrent des éléments — la mémoire d'une personne, ses fichiers, ses buts, une file, un journal.

Une faculté déclare déjà le rôle de chaque colonne de sa liste (le texte, les badges, les champs) ; le rendu de la
console en tire une ligne par élément. Ce module reprend ces lignes telles quelles — leur texte, leurs liens, leur
détail repliable, leur pagination — et n'en change que la forme : une carte par liste, une entrée par élément.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import Markup

from mika.inspector import render
from mika.inspector.ui import UI, env
from mika.kernel.inspect import Fields, Note, Stats, Table, Text


def counts(blocks: Sequence[Any]) -> list[dict[str, str]]:
    """Les chiffres que la faculté met en tête (``Stats``) : une ligne de compteurs."""
    stats = next((b for b in blocks if isinstance(b, Stats)), None)
    if stats is None:
        return []
    out = []
    for s in stats.items:
        value = s.value.text if isinstance(s.value, Text) else str(s.value)
        out.append({"label": s.label.lower(), "value": value, "sub": s.sub})
    return out


#: des étiquettes qui disent l'état ordinaire d'un élément (rien à signaler) : elles se taisent
ORDINARY = frozenset({"anodin", "actif", "active"})
#: des champs qui nomment à qui se rapporte l'élément : sur la fiche de cette personne, son nom seul se tait
WHOSE = frozenset({"concerne", "de qui", "à qui", "de", "avec", "à"})
#: des libellés de colonne qui nomment l'élément : son titre, dans une liste qui n'a pas de rôles
TITLES = frozenset({"titre", "nom", "intitulé", "sujet", "objet", "texte", "question", "but", "projet", "outil", "app",
                    "flux", "réveil", "adresse", "fichier", "pièce", "service", "serveur", "processus", "appareil"})
#: des libellés de date (ou de numéro) qui ne disent rien de plus que leur valeur : remontée près du titre, elle
#: les perd
PLAIN_TIMES = frozenset({"quand", "date", "heure", "le", "moment", "n°"})
#: une liste dont aucun texte ne dépasse tant de lettres se lit en lignes serrées
DENSE = 140


@dataclass(frozen=True, slots=True)
class Roles:
    """Ce que dit chaque colonne d'une liste qui n'a pas déclaré ses rôles (un tableau simple), par son libellé : le
    titre de l'élément (sinon sa première cellule qui est un lien), ses étiquettes, son texte, sa date ; les autres
    sont des faits, sauf celles qui se taisent. ``tiles`` : des tuiles côte à côte plutôt qu'une liste."""

    title: str = ""
    badges: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    time: str = ""
    skip: tuple[str, ...] = ()
    tiles: bool = False


def _text(cell: Mapping[str, Any]) -> str:
    return str(cell.get("text") or "")


def _roled(row: dict[str, Any], labels: Sequence[str], roles: Roles) -> None:
    cells = dict(zip(labels, row["cells"], strict=False))
    # sa date : celle que l'onglet nomme, sinon sa première cellule datée ; son titre : celui que l'onglet nomme,
    # sinon celui que son libellé désigne
    time = roles.time if roles.time in cells else \
        ("" if roles.title or roles.badges else next((k for k, v in cells.items() if v.get("t") == "when"), ""))
    title = roles.title if roles.title in cells else _title_of(cells, row.get("href", ""), time)
    row["heading"] = cells.get(title)
    row["time"] = cells.get(time)
    row["time_said"] = "" if time.casefold() in PLAIN_TIMES else time
    row["badges"] = [cells[k] for k in roles.badges if k in cells]
    row["body"] = [{"label": k, "value": cells[k]} for k in roles.body if k in cells]
    taken = {title, time, *roles.badges, *roles.body, *roles.skip}
    row["fields"] = [{"label": k, "value": v, "hint": ""} for k, v in cells.items() if k not in taken]


def _title_of(cells: Mapping[str, Mapping[str, Any]], href: str, time: str) -> str:
    """Le titre d'un élément dont la liste n'a pas de rôles : la colonne qui le nomme (« titre », « nom »…), sinon
    celle qui mène où mène la ligne, sinon son premier texte, sinon son premier lien, sinon sa première cellule."""
    named = next((k for k in cells if k.casefold() in TITLES), None)
    if named is not None:
        return named
    own = next((k for k, v in cells.items() if v.get("t") == "link" and href and v.get("href") == href), None)
    if own is not None:
        return own
    texts = (k for k, v in cells.items() if k != time and v.get("t") == "text" and v.get("kind") != "num"
             and _text(v) not in ("", "—"))
    links = (k for k, v in cells.items() if v.get("t") == "link")
    return next(texts, None) or next(links, None) or next((k for k in cells if k != time), "")


def listing(table: Table, shown: render.Env, query: Mapping[str, str], name: str = "",
            roles: Roles | None = None, counter: list[int] | None = None) -> dict[str, Any]:
    """Une liste de la faculté, rendue par la console (ses lignes, sa pagination), prête pour une carte.
    ``counter`` : partagé par les listes d'une même page, il leur donne des clés distinctes (leur ancre, leur
    pagination) — dans l'ordre où la console les numérote."""
    return shaped(render.block(table, shown, query, 0, counter), name, roles)


def shaped(got: dict[str, Any], name: str = "", roles: Roles | None = None) -> dict[str, Any]:
    """(voir ``shaped_as`` : l'état ordinaire ne se tait que sur la fiche de quelqu'un, ``name`` donné)"""
    return shaped_as(got, name, roles, quiet=bool(name))


def shaped_as(got: dict[str, Any], name: str = "", roles: Roles | None = None, *, quiet: bool = False) -> dict[str, Any]:
    """Une liste déjà rendue par la console, prête pour une carte — sans ce qui ne dit rien sur cette fiche : l'état
    ordinaire, un champ vide, le nom de la personne dont c'est la fiche, une pagination d'une seule page. Une liste
    sans rôles déclarés (un tableau simple) prend ceux de ``roles`` (par défaut : sa première cellule qui est un
    lien en titre, le reste en faits)."""
    if roles is None and not got.get("layout"):
        roles = Roles()
    title = got["title"]
    if got.get("count") is None and title.endswith(")") and " (" in title:  # « Ses souvenirs (3) »
        title = title.rsplit(" (", 1)[0]
    labels = [c["label"] for c in got["columns"]]
    for row in got["rows"]:
        if roles is not None:
            _roled(row, labels, roles)
        row["badges"] = [b for b in row.get("badges", []) if not (quiet and _text(b).casefold() in ORDINARY)]
        row["fields"] = [f for f in row.get("fields", []) if _text(f["value"]) not in ("", "—")
                         and not (f["label"] in WHOSE and name and _text(f["value"]) == name)]
        _lift_time(row)
        # le titre (ou la date, le numéro) mène déjà où mène la ligne : pas de second lien
        row["linked"] = any(c.get("t") == "link" and (not row.get("href") or c.get("href") == row["href"])
                            for c in (row.get("heading") or {}, row.get("time") or {}))
    pager = got.get("pager") or {}
    paged = any(pager.get(k) for k in ("prev", "next", "older", "newer"))
    tiles = bool(roles and roles.tiles)
    dense = not tiles and all(len(_text(b["value"])) <= DENSE for r in got["rows"] for b in r.get("body", []))
    return {**got, "title": title, "pager": pager if paged else None, "raw_pager": pager or None,
            "tiles": tiles, "dense": dense}


def _lift_time(row: dict[str, Any]) -> None:
    """Un élément qui a un titre et pas de date à côté : sa première date passe à droite du titre, avec son libellé
    quand il dit quelque chose (« né il y a 2 h », « échéance dans 3 j »)."""
    if row.get("time") or not row.get("heading"):
        return
    index = next((i for i, f in enumerate(row["fields"]) if f["value"].get("t") == "when"), None)
    if index is None:
        return
    lifted = row["fields"].pop(index)
    row["time"] = lifted["value"]
    row["time_said"] = "" if lifted["label"].casefold() in PLAIN_TIMES else lifted["label"]


def drawn(roles: Roles, kind: str) -> Callable[[UI, str, Sequence[Any], Mapping[str, str]], Markup | None]:
    """Un onglet fait de listes simples, dessiné : ses chiffres, ses faits (une place occupée), ses listes en cartes,
    ses notes. Sans liste, les blocs de la faculté."""

    def draw(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
        tables = [b for b in blocks if isinstance(b, Table)]
        if not tables:
            return None
        shown, name, counter = ui.env(), ui.names.name_of(key), [0]
        sections = [{**listing(t, shown, query, name, roles, counter), "kind": kind} for t in tables]
        facts = [render.block(b, shown, query) for b in blocks if isinstance(b, Fields)]
        notes = [{"text": b.text, "title": b.title, "tone": b.tone} for b in blocks if isinstance(b, Note)]
        return Markup(env.get_template("handmade/shared/lists.html").render(
            counts=counts(blocks), facts=facts, sections=sections, notes=notes))

    return draw
