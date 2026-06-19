"""Shared serialization helpers for dashboard API views.

Kept purposefully thin — dashboard views are read-only snapshots, not
REST serializers. If we ever need bidirectional I/O we promote these to
DRF serializers.
"""
from __future__ import annotations


def iso(dt):
    """ISO-format a datetime or return None if falsy."""
    return dt.isoformat() if dt else None


def paginate(
    request, *, default: int = 50, cap: int = 500,
    limit_key: str = "limit", offset_key: str = "offset",
) -> tuple[int, int]:
    """Read ``limit`` / ``offset`` from querystring with safe defaults.

    Returns (limit, offset) clamped to [1, cap] and [0, +inf). The
    querystring keys are overridable so a single view can paginate two
    independent lists (e.g. ``summary_limit`` / ``summary_offset``).
    """
    try:
        limit = int(request.GET.get(limit_key, default))
    except (TypeError, ValueError):
        limit = default
    try:
        offset = int(request.GET.get(offset_key, 0))
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(cap, limit)), max(0, offset)


def pick(request, key: str, default=None):
    """Read an optional query parameter; return ``default`` if blank."""
    v = request.GET.get(key)
    return v if v not in (None, "") else default
