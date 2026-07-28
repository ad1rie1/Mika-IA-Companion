"""Payload sanitization for module-supplied data.

**This is now defence in depth, not the primary control.** It was written
because the old dashboard's generic renderer injected `html` keys via
`innerHTML`, so a module piping untrusted content (an email body, an RSS
item, a scraped page) through `{html: ...}` was stored XSS on the admin
interface — which also holds the config editor and its secrets.

GestionSystème removed that class of bug instead of filtering it: a panel
returns *typed cells*, and the renderer has no path from a payload key to
markup at all. So nothing depends on this function for safety any more.

It is kept, and still applied by the Forge, for one reason: forged modules
are written by the AI at runtime and executed in-process. Stripping keys
that *look* like markup costs nothing and does not assume the renderer will
never change. Its home moved to ``utils/`` when the ``dashboard`` app was
deleted — the Forge was its last consumer, and a security helper should not
live inside whichever UI happened to need it first.
"""
from __future__ import annotations

MAX_DEPTH = 12
STRIPPED_KEYS = frozenset({"html", "js", "template"})


def sanitize_payload(value, *, _depth: int = 0):
    """Recursively drop keys that would be rendered as raw markup."""
    if _depth > MAX_DEPTH:
        return None
    if isinstance(value, dict):
        return {
            k: sanitize_payload(v, _depth=_depth + 1)
            for k, v in value.items()
            if str(k).lower() not in STRIPPED_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(v, _depth=_depth + 1) for v in value]
    return value


def sanitize_view_result(result, view):
    """Sanitize a handler result unless its view opted into raw HTML."""
    if getattr(view, "allow_raw_html", False):
        return result
    return sanitize_payload(result)
