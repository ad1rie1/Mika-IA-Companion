"""Distributed request tracing for the conversation pipeline.

Strategy: a ContextVar holds the current request_id.  Because asyncio tasks
inherit their parent's context at creation time, every coroutine awaited
inside process_message() automatically sees the same request_id — with no
changes to any function signature.

A logging.Filter injects the value into every LogRecord so the format string
can reference %(request_id)s across the entire backend.

Usage:
    # In process_message():
    rid = set_new_request_id()          # generates + sets, returns the id
    logger.info("rid=%s", rid)          # explicit if you need it

    # Anywhere else (context already set by process_message):
    get_request_id()                    # "a3f1c8b2" or "-" outside a request

The same mechanism carries the *person* of the current turn. Tool handlers
are called by the provider with only their declared arguments, so without an
ambient value a tool like ``identity_whoami_with`` would have to make the
model repeat a person_id it never sees. The ContextVar lets "the person I am
talking to" be implicit, exactly as it is in the conversation.
"""

import logging
import uuid
from contextvars import ContextVar

# Default value "-" appears in logs for background tasks that have no request
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
# Who the current turn is with. Empty outside a conversation (background
# loops, cron ticks) — callers must treat "" as "no person in scope".
_person_id: ContextVar[str] = ContextVar("person_id", default="")


def set_new_request_id() -> str:
    """Generate a fresh 8-char hex ID, store it in the current context, return it."""
    rid = uuid.uuid4().hex[:8]
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    """Return the request_id active in the current async context."""
    return _request_id.get()


def set_current_person_id(person_id: str) -> None:
    """Bind the person this turn is with, for the rest of the async context."""
    _person_id.set(person_id or "")


def current_person_id() -> str:
    """The person_id of the turn in progress, or "" outside one."""
    return _person_id.get()


class RequestIdFilter(logging.Filter):
    """Inject request_id into every log record.

    Registered once in settings.LOGGING and applied to all handlers so that
    every log line emitted during a request is correlated by its request_id.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()  # type: ignore[attr-defined]
        return True
