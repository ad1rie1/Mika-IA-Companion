"""Les blocs de la console, en texte : pour un client qui lit (un agent MCP).

Le même vocabulaire que les pages (``kernel/inspect.py``), rendu en lignes
lisibles : tables en listes, champs en « libellé : valeur », liens montrés par
leur cible (``vue:memory/souvenirs?q=…``, ``fiche:person/42``) pour qu'un agent
puisse les suivre. Récursion bornée, texte borné : une vue énorme se coupe en
le disant.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mika.inspector.render import relative
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Chart,
    Code,
    Column,
    Disclosure,
    Fields,
    Grid,
    Meter,
    Nav,
    Note,
    Prose,
    Ref,
    Row,
    Section,
    Stats,
    Swatch,
    Table,
    Text,
    Timeline,
    When,
)

MAX_DEPTH = 8
CELL_MAX = 600
TOTAL_MAX = 60_000
CUT = "…[coupé]"


def target(ref: Ref) -> str:
    """Où mène un lien, dans les termes des outils (vue, fiche)."""
    params = "&".join(f"{k}={v}" for k, v in ref.params)
    if ref.kind == "view":
        return f"vue:{ref.key}" + (f"?{params}" if params else "")
    if ref.kind == "subject":
        return f"fiche:{ref.key}" + (f"?{params}" if params else "")
    return f"{ref.kind}:{ref.key}"


def cell(value: Any, when: Callable[[int], str], now: int) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float):
        return f"{value:.3g}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Ref):
        return f"{value.text} ({target(value)})"
    if isinstance(value, Text):
        return _clip(value.text)
    if isinstance(value, Badge):
        return f"[{value.text}]"
    if isinstance(value, Meter):
        return value.text or (f"{value.ratio:.0%}" if value.ratio == value.ratio else "—")
    if isinstance(value, Swatch):
        return value.text
    if isinstance(value, When):
        return relative(value.at, now) if value.relative else when(value.at)
    return _clip(str(value))


def render(blocks: Sequence[Any], when: Callable[[int], str], now: int) -> str:
    lines: list[str] = []
    for b in blocks:
        _block(b, lines, when, now, 0)
    text = "\n".join(lines).strip()
    return text if len(text) <= TOTAL_MAX else text[:TOTAL_MAX - len(CUT)] + CUT


def _block(b: Any, out: list[str], when: Callable[[int], str], now: int, depth: int) -> None:
    pad = "  " * depth
    if depth > MAX_DEPTH:
        out.append(f"{pad}(trop imbriqué)")
        return

    def c(v: Any) -> str:
        return cell(v, when, now)

    title = getattr(b, "title", "") or ""
    if isinstance(b, Note):
        out.append(f"{pad}{'[' + b.tone + '] ' if b.tone else ''}{(title + ' : ') if title else ''}{b.text}")
    elif isinstance(b, Prose):
        out += [f"{pad}## {title}"] if title else []
        out.append(f"{pad}{_clip(b.text, 20_000)}")
    elif isinstance(b, Code):
        out += [f"{pad}## {title}"] if title else []
        out.append(f"{pad}```\n{_clip(b.text, 20_000)}\n{pad}```")
    elif isinstance(b, Fields):
        out += [f"{pad}## {title}"] if title else []
        out += [f"{pad}- {label} : {c(value)}" for label, value in b.pairs]
    elif isinstance(b, Stats):
        out += [f"{pad}## {title}"] if title else []
        out += [f"{pad}- {s.label} : {c(s.value)}{(' (' + s.sub + ')') if s.sub else ''}" for s in b.items]
    elif isinstance(b, Table):
        _table(b, out, when, now, depth)
    elif isinstance(b, Timeline):
        out += [f"{pad}## {title}"] if title else []
        if not b.entries:
            out.append(f"{pad}{b.empty or '(rien)'}")
        for e in b.entries:
            out.append(f"{pad}- {when(e.at)} — {e.title}{(' : ' + _clip(e.text)) if e.text else ''}")
    elif isinstance(b, Chart):
        out += [f"{pad}## {title}"] if title else []
        for s in b.series:
            last = s.points[-1] if s.points else None
            shown = "—" if last is None else (f"{last[1]:.0%}" if b.unit == "%" else f"{last[1]:.3g}{b.unit}")
            out.append(f"{pad}- {s.label} : {len(s.points)} points, dernier {shown}")
    elif isinstance(b, (Section, Disclosure)):
        out.append(f"{pad}## {title}")
        if isinstance(b, Section) and b.description:
            out.append(f"{pad}{b.description}")
        for item in b.items:
            _block(item, out, when, now, depth + 1)
    elif isinstance(b, Grid):
        for item in b.items:
            _block(item, out, when, now, depth)
    elif isinstance(b, Nav):
        out += [f"{pad}## {title}"] if title else []
        out += [f"{pad}- {i.text} ({target(i.href)})" for i in b.items]
    elif isinstance(b, ActionSlot):
        out.append(f"{pad}(action d'opérateur « {b.action} » : dans la console seulement)")
    else:
        out.append(f"{pad}(bloc inconnu : {type(b).__name__})")


def _table(b: Table, out: list[str], when: Callable[[int], str], now: int, depth: int) -> None:
    pad = "  " * depth
    if b.title:
        out.append(f"{pad}## {b.title}")
    labels = [col.label if isinstance(col, Column) else str(col) for col in b.columns]
    if not b.rows:
        out.append(f"{pad}{b.empty or '(vide)'}")
    for row in b.rows:
        cells = row.cells if isinstance(row, Row) else row
        parts = [f"{label} : {cell(v, when, now)}" for label, v in zip(labels, cells, strict=False) if v not in (None, "")]
        link = f" → {target(row.href)}" if isinstance(row, Row) and row.href is not None else ""
        out.append(f"{pad}- " + " · ".join(parts) + link)
        if isinstance(row, Row):
            for d in row.detail:
                _block(d, out, when, now, depth + 1)
    if b.pager is not None:
        p = b.pager
        total = f" sur {p.pages}" if p.total is not None else ""
        out.append(f"{pad}(page {p.number}{total} ; paramètre « {p.param} »)")


def _clip(text: str, limit: int = CELL_MAX) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - len(CUT)] + CUT
