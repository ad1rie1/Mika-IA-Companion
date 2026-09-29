"""Des blocs typés (``kernel/inspect.py``) aux modèles que lisent les gabarits.

Le seul endroit où un lien devient une adresse, où une cellule devient une
forme affichable. Tout texte reste du texte : l'échappement est celui de
Jinja ; le seul balisage produit à la main vient de ``svg.py``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from mika.inspector.svg import chart_svg
from mika.kernel.clock import US
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
    Note,
    Pager,
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
    tone,
)

PREFIX = "/inspecteur"
#: au-delà, un texte long se replie (« lire la suite »)
CLAMP_DEFAULT = 600
#: jamais plus que ceci n'est envoyé au navigateur pour une cellule ou un texte
TEXT_MAX = 100_000


def safe_url(href: str) -> str:
    """Une URL http(s) avec un hôte, sans identifiants ni caractères de contrôle ; sinon « »."""
    if not href or any(ord(c) < 32 or c == "\\" for c in href):
        return ""
    parts = urlsplit(href)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return ""
    return href


def href(ref: Ref) -> str:
    """L'adresse d'un lien de la console (clés encodées, jamais d'autre hôte)."""
    if ref.kind == "url":
        return safe_url(ref.key)
    if ref.kind == "local":  # une adresse de la console déjà construite par la console
        return ref.key if ref.key.startswith(PREFIX + "/") and "//" not in ref.key else ""
    query = ("?" + urlencode(ref.params)) if ref.params else ""
    if ref.kind == "episode":
        return f"{PREFIX}/episode/{quote(ref.key, safe='')}{query}"
    if ref.kind == "event":
        return f"{PREFIX}/evenement/{quote(ref.key, safe='')}"
    if ref.kind == "subject":
        kind, _, key = ref.key.partition("/")
        return f"{PREFIX}/fiche/{quote(kind, safe='')}/{quote(key, safe='')}{query}"
    owner, _, name = ref.key.partition("/")
    return f"{PREFIX}/facultes/{quote(owner, safe='')}/{quote(name, safe='')}{query}"


def relative(at: int, now: int) -> str:
    """« il y a 3 min », « dans 2 h », « à l'instant »."""
    if not at:
        return "—"
    delta = (now - at) / US
    future = delta < 0
    delta = abs(delta)
    if delta < 45:
        return "à l'instant"
    for unit, size in (("j", 86_400), ("h", 3_600), ("min", 60)):
        if delta >= size:
            n = int(delta // size)
            return f"dans {n} {unit}" if future else f"il y a {n} {unit}"
    return "à l'instant"


@dataclass(frozen=True, slots=True)
class Env:
    """Ce qu'il faut pour rendre : l'heure (lisible, relative), les actions offertes."""

    when: Callable[[int], str]
    now: int
    actions: Mapping[str, Any] | None = None
    #: une graduation courte : ``stamp(instant, étendue)``
    stamp: Callable[[int, int], str] | None = None


def cell(value: Any, env: Env) -> dict[str, Any]:
    if isinstance(value, Ref):
        link = href(value)
        return {"t": "link", "text": value.text, "href": link, "external": value.kind == "url"} if link else \
            {"t": "text", "text": value.text}
    if isinstance(value, Text):
        text = value.text[:TEXT_MAX]
        return {"t": "text", "kind": value.kind, "text": text, "tone": tone(value.tone), "hint": value.hint,
                "clamp": value.clamp and len(text) > value.clamp, "short": text[:value.clamp] if value.clamp else ""}
    if isinstance(value, Badge):
        return {"t": "badge", "text": value.text, "tone": tone(value.tone)}
    if isinstance(value, Meter):
        ratio = value.ratio if isinstance(value.ratio, int | float) and math.isfinite(value.ratio) else None
        if ratio is None:
            return {"t": "text", "text": "—"}
        ratio = min(1.0, max(0.0, float(ratio)))
        return {"t": "meter", "ratio": ratio, "text": value.text or f"{ratio:.0%}", "tone": tone(value.tone)}
    if isinstance(value, Swatch):
        return {"t": "swatch", "text": value.text, "palette": value.palette, "key": value.key,
                "weight": None if value.weight is None else f"{value.weight:.0%}"}
    if isinstance(value, When):
        return {"t": "when", "text": relative(value.at, env.now) if value.relative else env.when(value.at),
                "exact": env.when(value.at) if value.at else ""}
    if value is None:
        return {"t": "text", "text": "—", "kind": "muted"}
    if isinstance(value, bool):
        return {"t": "text", "text": "oui" if value else "non"}
    if isinstance(value, float):
        return {"t": "text", "text": f"{value:.3g}", "kind": "num"}
    if isinstance(value, int):
        return {"t": "text", "text": str(value), "kind": "num"}
    text = str(value)[:TEXT_MAX]
    return {"t": "text", "text": text, "clamp": len(text) > CLAMP_DEFAULT, "short": text[:CLAMP_DEFAULT]}


def _pager(p: Pager | None, query: Mapping[str, str]) -> dict[str, Any] | None:
    if p is None:
        return None
    base = {k: v for k, v in query.items() if k != p.param}

    def url(**over: Any) -> str:
        return "?" + urlencode({**base, **{k: v for k, v in over.items() if v is not None}})

    if p.total is None:
        if not p.older:
            return None
        return {"cursor": True, "older": "?" + urlencode({**{k: v for k, v in query.items() if k != "avant"},
                                                             **dict(p.older)})}
    pages = p.pages
    if pages <= 1:
        return {"cursor": False, "pages": 1, "total": p.total, "first": 1 if p.total else 0, "last": p.total,
                "links": []}
    shown = sorted({1, pages, p.number - 1, p.number, p.number + 1} & set(range(1, pages + 1)))
    links: list[dict[str, Any]] = []
    for i, n in enumerate(shown):
        if i and n - shown[i - 1] > 1:
            links.append({"gap": True})
        links.append({"n": n, "href": url(**{p.param: n}), "current": n == p.number})
    return {"cursor": False, "pages": pages, "total": p.total, "first": p.offset + 1,
            "last": min(p.total, p.offset + p.size), "links": links,
            "prev": url(**{p.param: p.number - 1}) if p.number > 1 else "",
            "next": url(**{p.param: p.number + 1}) if p.number < pages else ""}


def block(b: Any, env: Env, query: Mapping[str, str], depth: int = 0) -> dict[str, Any]:
    if depth > 8:
        return {"t": "note", "text": "Trop d'imbrication.", "tone": "danger"}
    if isinstance(b, Table):
        columns = [c if isinstance(c, Column) else Column(str(c)) for c in b.columns]
        rows = []
        for r in b.rows:
            if isinstance(r, Row):
                rows.append({"cells": [cell(v, env) for v in r.cells], "tone": tone(r.tone),
                             "href": href(r.href) if r.href else "",
                             "detail": [block(x, env, query, depth + 1) for x in r.detail]})
            else:
                rows.append({"cells": [cell(v, env) for v in r], "tone": "", "href": "", "detail": []})
        return {"t": "table", "title": b.title, "empty": b.empty, "caption": b.caption,
                "columns": [{"label": c.label, "align": c.align, "hint": c.hint} for c in columns],
                "rows": rows, "pager": _pager(b.pager, query), "detail": any(r["detail"] for r in rows)}
    if isinstance(b, Fields):
        hints = dict(b.hints)
        return {"t": "fields", "title": b.title, "columns": max(1, min(b.columns, 3)),
                "pairs": [{"label": k, "value": cell(v, env), "hint": hints.get(k, "")} for k, v in b.pairs]}
    if isinstance(b, Note):
        return {"t": "note", "text": b.text, "tone": tone(b.tone) or "info", "title": b.title}
    if isinstance(b, Prose):
        text = b.text[:TEXT_MAX]
        return {"t": "prose", "text": text, "title": b.title,
                "clamp": bool(b.clamp) and len(text) > b.clamp, "short": text[:b.clamp] if b.clamp else ""}
    if isinstance(b, Code):
        return {"t": "code", "text": b.text[:TEXT_MAX], "title": b.title}
    if isinstance(b, Stats):
        return {"t": "stats", "title": b.title, "items": [
            {"label": s.label, "value": cell(s.value, env), "sub": s.sub, "tone": tone(s.tone),
             "href": href(s.href) if s.href else "",
             "trend": chart_svg(s.trend, env.when, env.stamp) if s.trend is not None else ""} for s in b.items]}
    if isinstance(b, Timeline):
        return {"t": "timeline", "title": b.title, "empty": b.empty, "entries": [
            {"at": env.when(e.at), "rel": relative(e.at, env.now), "title": e.title, "text": e.text,
             "tone": tone(e.tone), "href": href(e.href) if e.href else "", "meta": e.meta} for e in b.entries]}
    if isinstance(b, Chart):
        points = [(at, v) for s in b.series for at, v in s.points]
        return {"t": "chart", "title": b.title, "empty": b.empty, "has": bool(points),
                "svg": chart_svg(b, env.when, env.stamp) if points else "",
                "table": _chart_table(b, env) if b.table and points else None}
    if isinstance(b, Grid):
        return {"t": "grid", "columns": max(1, min(b.columns, 3)),
                "items": [block(x, env, query, depth + 1) for x in b.items]}
    if isinstance(b, Section):
        return {"t": "section", "title": b.title, "description": b.description,
                "items": [block(x, env, query, depth + 1) for x in b.items]}
    if isinstance(b, Disclosure):
        return {"t": "disclosure", "title": b.title, "open": b.open,
                "items": [block(x, env, query, depth + 1) for x in b.items]}
    if isinstance(b, ActionSlot):
        return {"t": "action", "key": b.action, "initial": dict(b.initial), "title": b.title, "compact": b.compact,
                "slot": f"{b.action}|{json.dumps(dict(b.initial), sort_keys=True)}"}
    return {"t": "note", "text": f"Bloc inconnu : {type(b).__name__}", "tone": "danger"}


def _chart_table(b: Chart, env: Env) -> dict[str, Any]:
    stamps = sorted({at for s in b.series for at, _ in s.points})[-200:]
    by = [dict(s.points) for s in b.series]
    unit = b.unit
    fmt = (lambda v: f"{v:.0%}") if unit == "%" else (lambda v: f"{v:.3g}")
    return {"columns": [s.label for s in b.series],
            "rows": [{"at": env.when(at), "values": ["" if at not in d else fmt(d[at]) for d in by]}
                     for at in reversed(stamps)]}


def blocks(items: Sequence[Any], env: Env, query: Mapping[str, str]) -> list[dict[str, Any]]:
    return [block(b, env, query) for b in items]
