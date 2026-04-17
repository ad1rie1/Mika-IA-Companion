"""Shared serialization helpers for dashboard API views.

Kept purposefully thin — dashboard views are read-only snapshots, not
REST serializers. If we ever need bidirectional I/O we promote these to
DRF serializers.
"""
from __future__ import annotations


def iso(dt):
    """ISO-format a datetime or return None if falsy."""
    return dt.isoformat() if dt else None


def paginate(request, *, default: int = 50, cap: int = 500) -> tuple[int, int]:
    """Read ``limit`` / ``offset`` from querystring with safe defaults.

    Returns (limit, offset) clamped to [1, cap] and [0, +inf).
    """
    try:
        limit = int(request.GET.get("limit", default))
    except (TypeError, ValueError):
        limit = default
    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(cap, limit)), max(0, offset)


def pick(request, key: str, default=None):
    """Read an optional query parameter; return ``default`` if blank."""
    v = request.GET.get(key)
    return v if v not in (None, "") else default
