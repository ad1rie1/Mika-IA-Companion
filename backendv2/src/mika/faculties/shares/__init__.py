"""``shares`` : les fichiers qu'elle envoie à la personne à qui elle parle (ADR 0062)."""

from __future__ import annotations

from mika.faculties.shares import inspect, prompt, tools  # noqa: F401 — contributions
from mika.faculties.shares.faculty import (
    PORT,
    SHARES,
    FileRow,
    SharesParams,
    SharesState,
    of_people,
    row,
    rows,
)

__all__ = ["PORT", "SHARES", "FileRow", "SharesParams", "SharesState", "of_people", "row", "rows"]
