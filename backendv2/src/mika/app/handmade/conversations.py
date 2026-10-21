"""Conversations, dessinées (ADR 0121) : ses messages en conversation (le rendu de l'onglet Échanges d'une fiche, pour
toutes les personnes), ses réponses que l'opératrice a jugées — le message, sa réponse, l'avis et ce qu'elle aurait dû
dire —, les questions qui attendent.

Les données restent celles de la faculté du fil (``transcript`` : ses onglets ``messages``, ``jugees``,
``questions``, leurs filtres et leur pagination) ; une forme qu'un onglet ne reconnaît pas rend la main à ses blocs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look
from mika.app.handmade.person.echanges import exchanges
from mika.inspector import render
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY
from mika.kernel.inspect import Badge, Column, Row, Table, Text, When


def messages(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """Conversations › Messages : toutes ses conversations, jour par jour, chaque message avec qui."""
    return exchanges(ui, "", blocks, query)


def _labels(table: Table) -> dict[str, int]:
    return {(c.label if isinstance(c, Column) else str(c)): i for i, c in enumerate(table.columns)}


def judged(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """Conversations › Ses réponses jugées : le message, sa réponse, ton avis, ce qu'elle aurait dû dire."""
    table = next((b for b in blocks if isinstance(b, Table) and "sa réponse" in _labels(b)), None)
    if table is None:
        return None
    look = Look.of(ui, DAY)
    shown = render.Env(when=ui.when_long, now=look.now)
    at = _labels(table)

    def cell(row: Row, label: str) -> Any:
        i = at.get(label)
        return row.cells[i] if i is not None and i < len(row.cells) else None

    def text(value: Any) -> str:
        return value.text if isinstance(value, Text) else ("" if value in (None, "—") else str(value))

    verdicts = []
    for raw in table.rows:
        row = raw if isinstance(raw, Row) else Row(tuple(raw))
        verdict, when = cell(row, "avis"), cell(row, "quand")
        should = text(cell(row, "ce qu'elle aurait dû dire"))
        verdicts.append({
            "ok": isinstance(verdict, Badge) and verdict.tone == "ok",
            "verdict": verdict.text if isinstance(verdict, Badge) else text(verdict),
            "who": render.cell(cell(row, "avec"), shown) if cell(row, "avec") is not None else None,
            "when": f"{look.date(when.at)}, {look.hm(when.at)}" if isinstance(when, When) and when.at else "",
            "asked": text(cell(row, "on lui avait écrit")), "said": text(cell(row, "sa réponse")),
            "should": "" if should == "—" else should, "why": render.href(row.href) if row.href else "",
        })
    pager = render.block(table, shown, query).get("pager")
    return Markup(env.get_template("handmade/conversations/judged.html").render(
        verdicts=verdicts, pager=pager, empty=table.empty))
