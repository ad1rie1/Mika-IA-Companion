"""``attachments`` : ce qu'on lui envoie dans une conversation — gardé, lu de près, relié à ce qu'elle sait
(ADR 0106)."""

from __future__ import annotations

from mika.faculties.attachments import inspect, tools  # noqa: F401 — contributions
from mika.faculties.attachments.faculty import (
    ATTACHMENTS,
    PORT,
    AttachmentsParams,
    AttachmentsState,
    FileRow,
    file_id,
    row,
    rows,
)

__all__ = ["ATTACHMENTS", "PORT", "AttachmentsParams", "AttachmentsState", "FileRow", "file_id", "row", "rows"]
