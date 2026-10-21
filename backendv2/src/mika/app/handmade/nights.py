"""Pensées › Nuits, dessinée (ADR 0121) : son journal de la nuit en page de carnet, ce qu'elle en raconte à
n'importe qui, sa journée en cours telle qu'elle pourra la dire demain ; puis ses nuits, une carte par nuit — son
journal et ses rêves ensemble, ce dont elle s'est souvenue au réveil.

Les données restent celles de la faculté de soi (son onglet ``nuits`` : ses textes, son historique paginé au
journal) ; cette page n'en change que la forme. Le fil « en bref » de la faculté redisait l'historique : il se tait.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from markupsafe import Markup

from mika.app.handmade import MONTHS, WEEKDAYS
from mika.app.handmade.lists import listing
from mika.inspector.ui import UI, env
from mika.kernel.inspect import Prose, Table

#: les textes de l'onglet, reconnus au début de leur titre : (le début, sa place dans la page)
TEXTS = (("Journal du ", "journal"), ("Ce qu'elle en raconte", "told"), ("Sa journée en cours", "today"))
#: ce que dit la colonne « souvenu au réveil » d'un rêve
REMEMBERED = {"oui": "souvenu au réveil", "non": "oublié au réveil"}
#: ce que dit la colonne « concerne » quand une nuit ne concerne personne : il se tait
NOBODY = "personne"


def day_label(iso: str) -> str:
    """« 2026-10-20 » : « lundi 20 oct. » (tel quel s'il n'est pas une date)."""
    try:
        d = date.fromisoformat(iso.strip())
    except ValueError:
        return iso
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def _day_in(title: str) -> str:
    """La journée nommée dans un titre de la faculté : « Journal du 2026-10-20, en entier », « … (2026-10-21) »."""
    for part in title.replace("(", " ").replace(")", " ").replace(",", " ").split():
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    return ""


def _text(cell: Mapping[str, Any] | None) -> str:
    return str((cell or {}).get("text") or "")


def nights(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """Pensées › Nuits : le journal, ce qu'elle en raconte, sa journée en cours, puis une carte par nuit."""
    table = next((b for b in blocks if isinstance(b, Table)), None)
    if table is None:
        return None
    texts: dict[str, dict[str, str]] = {}
    for b in blocks:
        if isinstance(b, Prose):
            known = next((place for start, place in TEXTS if b.title.startswith(start)), None)
            if known is None:
                return None  # un texte qu'elle ne connaît pas : les blocs de la faculté
            texts[known] = {"text": b.text, "day": day_label(_day_in(b.title))}
    history = listing(table, ui.env(), query)
    # l'historique suit l'ordre d'écriture (un rêve s'écrit à part de son journal) : une carte par nuit, la plus
    # récente d'abord, son journal puis ses rêves
    by_night: dict[str, list[dict[str, Any]]] = {}
    for row in history["rows"]:
        fields = {f["label"]: f["value"] for f in row["fields"]}
        kind = (row["badges"] or [{}])[0]
        remembered = _text(fields.get("souvenu au réveil")).casefold()
        about = fields.get("concerne")
        by_night.setdefault(_text(fields.get("nuit")), []).append({
            "kind": kind, "journal": _text(kind).casefold() == "journal",
            "text": (row["body"] or [{}])[0].get("value"),
            "about": about if _text(about) not in ("", NOBODY) else None,
            "remembered": REMEMBERED.get(remembered, ""), "awake": remembered == "oui",
            "detail": row.get("detail") or [],
        })
    groups = [{"night": night, "label": day_label(night), "entries": sorted(entries, key=lambda e: not e["journal"])}
              for night, entries in sorted(by_night.items(), reverse=True)]
    return Markup(env.get_template("handmade/pensees/nuits.html").render(
        journal=texts.get("journal"), told=texts.get("told"), today=texts.get("today"), groups=groups,
        history=history, forms={}))
