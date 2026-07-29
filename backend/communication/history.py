"""Conversation history as the frontend needs it — the catch-up read layer.

A ``speech`` frame is fire-and-forget: ``group_send`` to a group with no
member is silently dropped, and nothing ever replayed it. The browser's
chat therefore kept its own ``localStorage`` list and never reconciled it
with the server, so every reply produced while a tab was disconnected —
a restart, a timeout, a laptop lid — was recorded in the database and
invisible in the UI forever, while the user's own message stayed on screen
because it is painted before it is sent. The asymmetry read as "she
ignored me".

Two questions, deliberately separate (same rule as ``memory/read.py``:
one function per *question*, returning rows and never formatted output):

- :func:`recent_for` — "what should I show a client that just opened?"
- :func:`after_for` — "what did this client miss?", answered by pk.

They are not the same call. The first is bounded by a window the UI can
render; the second must return *everything* newer or the cursor would
advance past messages that were never displayed, and the gap would be
permanent — which is precisely the bug this module exists to close. It is
capped anyway, and says so via ``truncated`` rather than silently
dropping the middle of a conversation.

Ordering is by ``pk``, not ``created_at``. ``Message`` uses
``auto_now_add``, whose resolution collides on rapid inserts (the model's
own Meta already sorts on pk as a tiebreaker), and a cursor has to be
totally ordered to be a cursor at all.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# What a fresh client is shown. Matches ChatOverlay's MAX_MESSAGES ceiling
# so the wire never carries bubbles the UI would immediately evict.
DEFAULT_LIMIT = 50

# Hard ceiling on a catch-up. A client away for a week does not need the
# week — it needs the tail, plus the honest statement that it is a tail.
MAX_LIMIT = 200


def _visible(queryset):
    """Messages a person may see in their own chat.

    ``is_internal`` marks engine scaffolding: the "user" prompt of an
    INTERNAL_TRIGGER (the greeting brief Mika writes to herself, a module's
    notify_ai text) and the fallback *reply* of a failed turn. Neither was
    said by anyone. Her real answer to a greeting is not flagged, so
    "Hey ! Bienvenue bienvenue" still shows — the flag is a property of
    the message, not of the side it sits on.

    Exactly the rule ``_rehydrate_short_term`` applies to the buffer the
    model reads. The two must agree: a client showing a fallback that the
    model has no memory of saying is a conversation about nothing.
    """
    return queryset.exclude(is_internal=True)


def _serialize(row) -> dict:
    """One Message as the wire carries it.

    ``ts`` is epoch milliseconds because the browser reads it straight into
    ``new Date()``; an ISO string would make the client parse a timezone
    it has no opinion about.
    """
    return {
        "id": row.pk,
        "role": row.role,
        "text": row.content,
        "ts": int(row.created_at.timestamp() * 1000),
        "source": row.source,
        "emotion": row.emotion or "",
        "emotion_intensity": row.emotion_intensity or 0.0,
        "attachments": row.attachments_meta or [],
    }


async def recent_for(person_id: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """The tail of this person's conversation, oldest first.

    Empty for a person_id that has never spoken — which is a fact, not a
    failure: a first-time visitor has no history and the client renders an
    empty thread rather than an error.
    """
    if not person_id:
        return []
    limit = max(1, min(int(limit), MAX_LIMIT))

    from memory.models import Message

    rows = [
        row
        async for row in _visible(
            Message.objects.filter(person_id=person_id)
        ).order_by("-pk")[:limit]
    ]
    rows.reverse()
    return [_serialize(row) for row in rows]


async def after_for(
    person_id: str, after_id: int, limit: int = MAX_LIMIT,
) -> tuple[list[dict], bool]:
    """Everything this person missed since ``after_id``, oldest first.

    Returns ``(messages, truncated)``. ``truncated`` is True when the gap
    was larger than ``limit`` and the *oldest* missed messages were left
    out — the client keeps the newest, which is what it is looking at.
    It matters that this is reported: a silent cap would let the cursor
    jump over messages that were never rendered, re-creating the hole
    this whole path exists to fill, and it would look exactly like a
    complete sync.
    """
    if not person_id:
        return [], False
    limit = max(1, min(int(limit), MAX_LIMIT))

    from memory.models import Message

    query = _visible(
        Message.objects.filter(person_id=person_id, pk__gt=int(after_id))
    )
    # One extra row is the cheapest possible "is there more?" — a count()
    # would be a second query against a table six background loops write to.
    rows = [row async for row in query.order_by("-pk")[: limit + 1]]
    truncated = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return [_serialize(row) for row in rows], truncated
