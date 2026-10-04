"""Schéma JSON publiable du contrat de rendu ; aucune dépendance runtime."""
from __future__ import annotations


def schema():
    string = {"type": "string"}
    tone = {"enum": ["", "info", "ok", "warn", "danger"]}
    href = {"type": "string", "description": "Chemin local /, ? ou #, ou URL HTTP(S)."}
    scalar = {"type": ["string", "number", "boolean", "null"]}
    ref = lambda name: {"$ref": f"#/$defs/{name}"}
    def array(items, maximum=200):
        return {"type": "array", "items": items, "maxItems": maximum}
    def obj(properties, required=()):
        return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}
    cell = obj({"kind": {"enum": ["text", "mono", "num", "badge", "emotion", "link", "meter", "bool", "muted"]},
                "text": scalar, "title": string, "tone": tone, "href": href,
                "ratio": {"type": ["number", "null"]}, "emotion": string, "clamp": {"type": "boolean"}}, ["kind"])
    value = {"oneOf": [scalar, ref("cell")]}
    column = obj({"key": string, "label": string, "align": {"enum": ["", "num", "fit"]}, "hint": string}, ["key", "label"])
    row = obj({"cells": {"oneOf": [array(value, 30), {"type": "object", "additionalProperties": value}]},
               "href": href, "tone": tone, "detail": ref("block")}, ["cells"])
    paging = obj({"page": {"type": "integer", "minimum": 1}, "per_page": {"type": "integer", "minimum": 1, "maximum": 200},
                  "total": {"type": "integer", "minimum": 0}, "param": string}, ["page", "per_page", "total"])
    choices = array(obj({"value": string, "label": string}, ["value", "label"]), 100)
    filter_ = obj({"key": string, "label": string, "kind": {"enum": ["search", "select"]},
                   "choices": choices, "placeholder": string}, ["key", "label", "kind"])
    defs = {"cell": cell, "column": column, "row": row, "pagination": paging, "filter": filter_}
    blocks = []
    def block(kind, properties, required=()):
        blocks.append(obj({"type": {"const": kind}, "title": string, **properties}, ["type", *required]))
    for kind in ("blocks", "grid", "section", "disclosure"):
        props = {"items": array(ref("block"))}
        if kind == "grid": props["columns"] = {"type": "integer", "minimum": 1, "maximum": 3}
        if kind == "section": props["description"] = string
        if kind == "disclosure": props["open"] = {"type": "boolean"}
        block(kind, props, ["items"])
    for kind in ("prose", "code", "note"):
        block(kind, {"text": string, **({"tone": tone} if kind == "note" else {})}, ["text"])
    block("fields", {"items": array(obj({"label": string, "value": value}, ["label", "value"]))}, ["items"])
    block("stats", {"items": array(obj({"label": string, "value": scalar, "sub": string, "tone": tone, "href": href}, ["label", "value"]))}, ["items"])
    block("timeline", {"items": array(obj({"title": string, "text": string, "meta": string, "tone": tone, "href": href}, ["title"])), "empty": string}, ["items"])
    block("table", {"columns": array(ref("column"), 30), "rows": array(ref("row")), "empty": string,
                    "pagination": ref("pagination"), "filters": array(ref("filter"), 20)}, ["columns", "rows"])
    block("form", {"action": string, "initial": {"type": "object", "additionalProperties": scalar}}, ["action"])
    defs["block"] = {"oneOf": blocks}
    key = {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,47}$"}
    defs["input"] = obj({"key": key, "label": string,
        "type": {"enum": ["text", "textarea", "integer", "number", "boolean", "select", "email", "url", "hidden"]},
        "required": {"type": "boolean", "description": "Par défaut false pour boolean, true pour les autres types."}, "initial": scalar, "help": string,
        "minimum": {"type": "number"}, "maximum": {"type": "number"},
        "max_length": {"type": "integer", "minimum": 1, "maximum": 20000},
        "choices": array({"oneOf": [string, obj({"value": string, "label": string}, ["value", "label"])]}, 100),
    }, ["key"])
    defs["action"] = obj({"key": key, "label": string, "description": string, "confirm": string,
                          "danger": {"type": "boolean"}, "fields": array(ref("input"), 30)}, ["key"])
    defs["view"] = obj({"key": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,31}$"}, "label": string,
                        "description": string, "icon": string, "order": {"type": "integer"},
                        "page_params": {**array({"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9_]{0,47}$",
                                                  "not": {"enum": ["page", "per_page"]}}, 20), "uniqueItems": True},
                        "actions": array(ref("action"), 20)}, ["key"])
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "GestionSystème — panneau v2",
            **obj({"version": {"const": 2}, "blocks": array(ref("block"))}, ["version", "blocks"]), "$defs": defs}
