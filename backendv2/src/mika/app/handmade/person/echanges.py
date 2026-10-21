"""L'onglet Échanges de la fiche d'une personne, dessiné (ADR 0121) : une conversation, jour par jour — la personne
à gauche, elle à droite, de la couleur de ce qu'elle ressentait en écrivant. Sans personne (``key`` vide), toutes ses
conversations : Conversations › Messages, chaque message avec qui l'a écrit ou à qui elle répondait.

Les données restent celles de la faculté du fil (``transcript``, son onglet ``echanges``) : ses lignes disent déjà,
pour chaque message reçu, s'il a eu sa réponse, s'il attend, ou pourquoi il est resté sans réponse ; pour chacune de
ses réponses, son épisode et son « pourquoi ». Cette page n'en change que la forme ; une forme qu'elle ne reconnaît
pas (aucune table de messages) rend la main aux blocs de la faculté.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade import Look, emotion
from mika.contracts import identity as identity_c
from mika.inspector import render
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY
from mika.kernel.inspect import Badge, Column, Disclosure, Prose, Row, Stats, Swatch, Table, Text, When
from mika.vocab import affect as A

#: un message plus long se replie (« lire la suite »)
FOLD_CHARS = 700


def _cells(table: Table) -> dict[str, int]:
    """La place de chaque colonne de la faculté, par son libellé."""
    return {(c.label if isinstance(c, Column) else str(c)): i for i, c in enumerate(table.columns)}


def _text(cell: Any) -> str:
    if isinstance(cell, Text):
        return cell.text
    return "" if cell is None else str(cell)


def exchanges(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    table = next((b for b in blocks if isinstance(b, Table) and "texte" in _cells(b)), None)
    if table is None:
        return None
    look = Look.of(ui, DAY)
    shown = render.Env(when=ui.when_long, now=look.now)
    at = _cells(table)
    # qui parle : sur la fiche d'une personne, utile seulement si elle a plusieurs adresses ; sur la page de toutes
    # les conversations (``key`` vide), toujours
    several = not key or len(look.frame.get(identity_c.HANDLES(key)) or ()) > 1

    def cell(row: Row, label: str) -> Any:
        i = at.get(label)
        return row.cells[i] if i is not None and i < len(row.cells) else None

    messages: list[dict[str, Any]] = []
    for raw in reversed(table.rows):  # la page va du plus récent au plus ancien : on la lit dans l'ordre
        row = raw if isinstance(raw, Row) else Row(tuple(raw))
        speaker = cell(row, "qui parle")
        mine = isinstance(speaker, Badge) and speaker.text == "elle"
        when = cell(row, "quand")
        stamp = when.at if isinstance(when, When) else 0
        felt = cell(row, "émotion")
        e = emotion(felt.key) if isinstance(felt, Swatch) else None
        full = next((p.text for p in row.detail if isinstance(p, Prose)), "") or _text(cell(row, "texte"))
        answer = cell(row, "réponse")
        place = cell(row, "où")
        messages.append({
            "mine": mine, "muted": row.tone == "muted", "day": look.date(stamp) if stamp else "",
            "time": look.hm(stamp) if stamp else "", "text": full, "long": len(full) > FOLD_CHARS,
            "short": full[:FOLD_CHARS].rstrip() + "…" if len(full) > FOLD_CHARS else full,
            "emotion": e.value if e is not None else "", "word": A.FR[e] if e is not None else "",
            "room": str(place) if place and str(place) != "en privé" else "",
            "who": render.cell(cell(row, "avec"), shown) if several and cell(row, "avec") is not None else None,
            "answer": render.cell(answer, shown) if answer not in (None, "") else None,
            "why": render.href(row.href) if row.href else "",
            "episode": render.cell(cell(row, "épisode"), shown) if cell(row, "épisode") not in (None, "—") else None,
            "number": render.cell(cell(row, "n°"), shown) if cell(row, "n°") is not None else None,
        })
    days = []
    for m in messages:
        if not days or days[-1]["day"] != m["day"]:
            days.append({"day": m["day"], "messages": []})
        days[-1]["messages"].append(m)
    stats = next((b for b in blocks if isinstance(b, Stats)), None)
    counts = [{"label": s.label, "value": _text(s.value)} for s in stats.items] if stats is not None else []
    folded = next((b for b in blocks if isinstance(b, Disclosure)), None)
    summaries = []
    if folded is not None:
        inner = next((b for b in folded.items if isinstance(b, Table)), None)
        for r in inner.rows if inner is not None else ():
            row = r if isinstance(r, Row) else Row(tuple(r))
            who, upto, text = (row.cells + (None, None, None))[:3]
            summaries.append({"who": render.cell(who, shown), "upto": render.cell(upto, shown), "text": _text(text)})
    got = render.block(table, shown, query)
    # la même liste en tableau, filtres gardés : la console la rend (``wants_table``)
    as_table = "?" + urlencode({**{k: v for k, v in query.items() if k != "flash"}, f"vue_{got['id']}": "table"})
    return Markup(env.get_template("handmade/person/tabs/echanges.html").render(
        name=look.name(key) if key else "", days=days, counts=counts, summaries=summaries, pager=got.get("pager"),
        empty=table.empty, as_table=as_table))
