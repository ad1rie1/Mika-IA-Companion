"""Contrat déclaratif v2, commun aux plugins et aux apps forgées.

Aucun HTML, nom de gabarit, classe CSS ou destinataire d'action n'est accepté.
Une seule enveloppe : {"version": 2, "blocks": [...]}.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from GestionSysteme import panels as P

VERSION = 2
MAX_DEPTH = 8
MAX_BLOCKS = 200
MAX_ROWS = 200
PARAM = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")


def safe_href(value) -> str:
    """Liens HTTP(S), ancres et chemins locaux ; aucun schéma exécutable."""
    value = str(value or "").strip()
    if not value or any(ord(c) < 32 for c in value) or "\\" in value:
        return ""
    try:
        url = urlsplit(value)
    except ValueError:
        return ""
    if value.startswith("//"):
        return ""
    if url.scheme:
        return value if url.scheme.lower() in {"http", "https"} and url.netloc else ""
    return value if value.startswith(("/", "?", "#")) else ""


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("un objet est attendu")
    return value


def _keys(value, allowed, required=()):
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown or missing:
        raise ValueError(f"champs inconnus : {', '.join(map(str, sorted(unknown, key=str))) or 'aucun'} ; "
                         f"champs manquants : {', '.join(sorted(missing)) or 'aucun'}")


def _list(value, maximum=MAX_BLOCKS):
    if not isinstance(value, (list, tuple)):
        raise ValueError("une liste est attendue")
    if len(value) > maximum:
        raise ValueError(f"plus de {maximum} éléments : paginez les résultats")
    return value


def _text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return P._str(value)


def cell(value) -> P.Cell:
    if not isinstance(value, dict):
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError("une cellule doit être scalaire ou typée")
        return P.text(_text(value), clamp=True)
    _keys(value, {"kind", "text", "href", "title", "tone", "ratio", "emotion", "clamp"}, {"kind"})
    kind = str(value.get("kind", "text"))
    if kind not in P._CELL_KINDS:
        raise ValueError(f"type de cellule inconnu : {kind}")
    raw = value.get("text", "")
    if kind == "bool":
        return P.boolean(raw) if isinstance(raw, bool) else P.Cell(
            text=_text(raw), kind="bool", tone=P._tone(value.get("tone", "")))
    return P.Cell(
        text=_text(raw), kind=kind, href=safe_href(value.get("href")),
        title=str(value.get("title") or ""), tone=P._tone(value.get("tone", "")),
        ratio=P._ratio(value.get("ratio")), emotion=str(value.get("emotion") or raw),
        clamp=bool(value.get("clamp", kind == "text")),
    )


def decode(payload: dict, *, request=None):
    try:
        _object(payload)
        _keys(payload, {"version", "blocks"}, {"version", "blocks"})
        if payload.get("version") != VERSION or "blocks" not in payload:
            raise ValueError('enveloppe requise : {"version": 2, "blocks": [...]}')
        return P.Blocks(_Decoder(request).children(payload["blocks"], -1))
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        return P.Note(f"Interface invalide : {exc}", tone="danger", title="Contrat de panneau")


class _Decoder:
    def __init__(self, request):
        self.remaining = MAX_BLOCKS
        self.request = request

    def children(self, data, depth):
        return [self.block(x, depth + 1) for x in _list(data)]

    def block(self, raw, depth=0):
        self.remaining -= 1
        if depth > MAX_DEPTH or self.remaining < 0:
            raise ValueError("composition trop profonde ou trop volumineuse")
        d = _object(raw)
        kind = d.get("type")
        attributes = {
            "table": {"columns", "rows", "pagination", "filters", "empty"},
            "grid": {"items", "columns"}, "section": {"items", "description"},
            "disclosure": {"items", "open"}, "blocks": {"items"},
            "prose": {"text"}, "code": {"text"}, "note": {"text", "tone"},
            "fields": {"items"}, "stats": {"items"}, "timeline": {"items", "empty"},
            "form": {"action", "initial"},
        }
        if kind not in attributes:
            raise ValueError(f"type de bloc inconnu : {kind!r}")
        required = {"columns", "rows"} if kind == "table" else {"action"} if kind == "form" else (
            {"text"} if kind in {"prose", "code", "note"} else {"items"})
        _keys(d, attributes[kind] | {"type", "title"}, required)
        title = str(d.get("title") or "")
        if kind == "table":
            return self.table(d, depth)
        if kind in {"blocks", "grid", "section", "disclosure"}:
            items = self.children(d.get("items", []), depth)
            if kind == "grid":
                columns = d.get("columns", 2)
                if type(columns) is not int or not 1 <= columns <= 3:
                    raise ValueError("une grille comporte de 1 à 3 colonnes")
                return P.Grid(items, columns=columns)
            if kind == "section":
                return P.Section(title, items, str(d.get("description") or ""))
            if kind == "disclosure":
                return P.Disclosure(title or "Détails", items, bool(d.get("open", False)))
            return P.Blocks(items)
        if kind in {"prose", "code", "note"}:
            content = _text(d.get("text", ""))
            if kind == "note":
                return P.Note(content, tone=P._tone(d.get("tone", "info")), title=title)
            return (P.Code if kind == "code" else P.Prose)(content, title=title)
        if kind == "fields":
            fields = []
            for f in _list(d.get("items", [])):
                f = _object(f)
                _keys(f, {"label", "value"}, {"label", "value"})
                c = cell(f.get("value", ""))
                fields.append(P.Field(str(f.get("label", "")), c.text, kind=c.kind,
                                      tone=c.tone, href=c.href, ratio=c.ratio, title=c.title,
                                      emotion=c.emotion))
            return P.Fields(fields, title=title)
        if kind == "stats":
            items = []
            for s in _list(d["items"]):
                _keys(_object(s), {"label", "value", "sub", "tone", "href"}, {"label", "value"})
                items.append(P.Stat(str(s["label"]), _text(s["value"]), str(s.get("sub", "")),
                                    P._tone(s.get("tone", "")), safe_href(s.get("href"))))
            return P.Stats(items, title=title)
        if kind == "timeline":
            items = []
            for e in _list(d["items"]):
                _keys(_object(e), {"title", "text", "meta", "tone", "href"}, {"title"})
                items.append(P.TimelineEntry(str(e["title"]), _text(e.get("text", "")),
                    str(e.get("meta", "")), P._tone(e.get("tone", "")), safe_href(e.get("href"))))
            return P.Timeline(items, title=title, empty=str(d.get("empty", "Aucun événement.")))
        if kind == "form":
            return P.ActionForm(str(d.get("action", "")), _object(d.get("initial", {})), title)
        raise ValueError(f"type de bloc inconnu : {kind!r}")

    def table(self, d, depth):
        keys, columns = [], []
        for c in _list(d.get("columns", []), maximum=30):
            c = _object(c)
            _keys(c, {"key", "label", "align", "hint"}, {"key", "label"})
            key = str(c["key"])
            if not key or key in keys:
                raise ValueError("clé de colonne vide ou dupliquée")
            keys.append(key)
            columns.append(P.Column(str(c["label"]),
                align=c.get("align") if c.get("align") in {"num", "fit"} else "",
                hint=str(c.get("hint") or "")))
        rows = []
        for r in _list(d.get("rows", []), maximum=MAX_ROWS):
            r = _object(r)
            _keys(r, {"cells", "href", "tone", "detail"}, {"cells"})
            values = r.get("cells")
            if not isinstance(values, (dict, list, tuple)):
                raise ValueError("chaque ligne requiert cells (objet ou liste)")
            if isinstance(values, dict):
                _keys(values, keys, keys)
                cells = [cell(values.get(k)) for k in keys]
            else:
                cells = [cell(v) for v in values]
            if len(cells) != len(columns):
                raise ValueError("le nombre de cellules doit correspondre aux colonnes")
            detail = self.block(r["detail"], depth + 1) if r.get("detail") else None
            rows.append(P.Row(tuple(cells), href=safe_href(r.get("href")),
                              tone=P._tone(r.get("tone", "")), detail=detail))
        page = None
        if "pagination" in d:
            from GestionSysteme.tables import PageResult
            paging = _object(d["pagination"])
            _keys(paging, {"total", "per_page", "page", "param"}, {"total", "per_page", "page"})
            total, size, number = paging["total"], paging["per_page"], paging["page"]
            if any(type(n) is not int for n in (total, size, number)) or total < 0 or not 1 <= size <= MAX_ROWS or number < 1:
                raise ValueError("pagination : total positif, page ≥ 1 et per_page entre 1 et 200 attendus")
            param = str(paging.get("param", "page"))
            if not PARAM.fullmatch(param):
                raise ValueError("paramètre de pagination invalide")
            last = max(1, -(-total // size))
            if number > last or len(rows) != min(size, max(0, total - (number - 1) * size)):
                raise ValueError("pagination incohérente avec les lignes reçues")
            page = PageResult(rows, total, number, size, last, param)
        return P.Table(columns, rows, page=page, caption=str(d.get("title") or ""),
                       filters=self.filters(d.get("filters", []), page),
                       empty=str(d.get("empty", "Aucun résultat.")))

    def filters(self, specs, page):
        from GestionSysteme import tables
        from django.http import QueryDict
        from types import SimpleNamespace

        specs = _list(specs, maximum=20)
        if not specs:
            return None
        request = self.request or SimpleNamespace(GET=QueryDict(), path="")
        fs = tables.FilterSet(show_per_page=False)
        names = set()
        for spec in specs:
            spec = _object(spec)
            _keys(spec, {"key", "label", "kind", "choices", "placeholder"}, {"key", "label", "kind"})
            key = str(spec.get("key", ""))
            if not PARAM.fullmatch(key) or key in names or key == (page.param if page else "page"):
                raise ValueError("clé de filtre invalide ou dupliquée")
            names.add(key)
            label = str(spec.get("label") or key)
            kind = spec.get("kind", "search")
            if kind == "search":
                fs.add(tables.search_filter(request, key, label, placeholder=str(spec.get("placeholder", ""))))
            elif kind == "select":
                options = []
                for c in _list(spec.get("choices", []), maximum=100):
                    c = _object(c)
                    _keys(c, {"value", "label"}, {"value", "label"})
                    options.append((str(c.get("value", "")), str(c.get("label", ""))))
                fs.add(tables.select_filter(request, key, label, options))
            else:
                raise ValueError(f"type de filtre inconnu : {kind}")
        fs.prefix = "panel-" + "-".join(sorted(names))
        params = request.GET.copy()
        for key in names | {page.param if page else "page"}:
            params.pop(key, None)
        fs.hidden = [(key, value) for key, values in params.lists() for value in values]
        query = params.urlencode()
        fs.reset_url = request.path + (f"?{query}" if query else "")
        return fs
