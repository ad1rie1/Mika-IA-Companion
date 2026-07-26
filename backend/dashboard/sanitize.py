"""Payload sanitization for module-supplied dashboard data.

The generic view renderer (``dashboard/js/views/module_default.js``) injects
`html` keys via `innerHTML`, so any module that pipes untrusted content (an
email body, an RSS item, a scraped page) through `{html: ...}` would be
stored XSS on the admin interface — which also holds the config editor and
its secrets.

The Forge already stripped those keys for AI-forged modules; this is the
same guard applied to *every* module, with `ModuleView.allow_raw_html` as
the explicit opt-in for a module that owns and escapes its own markup.
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
