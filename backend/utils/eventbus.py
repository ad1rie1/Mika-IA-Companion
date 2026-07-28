"""EventBus — the one place a signal fans out to everything that cares.

Before this, ``ModuleManager.emit_event`` *was* the bus, and it was not
really one: it awaited a specially-cased conscience callback, then looped
over running modules, then imported ``projects.runner`` inline to poke it.
Two of its three consumers were wired by name. Adding a fourth meant
editing the emitter — which is the exact shape of coupling a plugin system
exists to avoid, and it mattered here because modules are written *by Mika
at runtime*: the set of things that react to a signal is not known when the
core is compiled.

Deliberately generic. It never imports ``modules``: a subscriber only needs
an event carrying ``event_type`` and ``source_module`` (see ``Event``), so
this module sits in ``utils`` with no dependencies and everything upstream
may import it — including ``modules`` itself, which would otherwise be an
inverted dependency for conscience/projects/pipeline.

Two delivery modes, because the difference is load-bearing:

  AWAIT  the emitter waits for the subscriber. Correct when the emitter's
         next step depends on the reaction, or when ordering is observable
         (the conscience must have filed its Observation before anything
         downstream reads it).
  SPAWN  detached. Correct for anything slow. This is the mode that did
         not exist before: because everything was awaited, an RSS poll
         emitting an entry paid for the conscience's LLM interpretation
         inline, and a hung subscriber hung the emitter forever.

Failures never propagate to the emitter and never abort the fan-out — one
broken subscriber must not silence every other. They are counted per
subscription instead of being swallowed, so "this handler has failed 400
times" is answerable rather than invisible.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Event(Protocol):
    """The minimum an event must carry to be routable.

    Structural, not a base class: ``modules.types.ModuleEvent`` already
    satisfies it, and so will anything else that grows a need to travel on
    the bus, without inheriting from — or importing — this module.
    """

    event_type: str
    source_module: str


class DeliveryMode(str, Enum):
    AWAIT = "await"
    SPAWN = "spawn"


# Priority bands. Lower runs first. Named so a subscription site states its
# intent ("I must observe before the rest") instead of an unexplained int.
PRIORITY_OBSERVER = 10   # sees the event before anyone reacts to it
PRIORITY_DEFAULT = 50    # ordinary reactors (modules)
PRIORITY_LATE = 90       # bookkeeping that may depend on the above


@dataclass
class Subscription:
    """One registered interest in a subset of the event stream."""

    name: str
    pattern: str
    handler: Callable[[Any], Awaitable[None]]
    mode: DeliveryMode = DeliveryMode.AWAIT
    priority: int = PRIORITY_DEFAULT
    # Bound only for AWAIT delivery: a SPAWN subscriber is already off the
    # emitter's await chain, so a deadline there would only truncate its own
    # work. ``None`` means "no deadline", which is the honest default for
    # handlers the core ships; forged/plugin handlers should set one.
    timeout: float | None = None
    # A module does not receive the events it emits itself. Generalised from
    # the old ``module.name != event.source_module`` check: the rule is now
    # "a subscriber named like the source is the source".
    receive_own: bool = False

    # -- observability ------------------------------------------------
    delivered: int = field(default=0, init=False)
    failed: int = field(default=0, init=False)
    last_error: str = field(default="", init=False)
    last_error_at: float = field(default=0.0, init=False)

    def matches(self, event_type: str, source_module: str) -> bool:
        if not self.receive_own and self.name == source_module:
            return False
        return _pattern_matches(self.pattern, event_type)


# Events whose type starts with this are *internal*: engine lifecycle
# signals rather than things that happened in the world. A wildcard does not
# reach them — exactly like a shell glob and a dotfile — so they must be
# named explicitly to be received.
#
# Not decoration. Wildcard subscribers here are not a corner case: the
# conscience subscribes to ``*`` to interpret everything it can see, and the
# Forge relays ``*`` to sandboxed modules **Mika writes at runtime**, some of
# which declare ``events: ["*"]``. Without the reserve, adding one internal
# signal — say "a conversation turn finished" — would wake her signal
# interpreter and every forged module on every single turn, which is both an
# LLM call per turn and an obvious feedback loop.
INTERNAL_PREFIX = "_"


def _pattern_matches(pattern: str, event_type: str) -> bool:
    """``*`` = every public event, ``prefix.*`` = that namespace, else exact.

    Only a trailing star is supported, on purpose: the event vocabulary is
    dotted namespaces (``email.received``, ``forge.<module>.<type>``), and a
    general glob would invite patterns nobody can reason about when the
    subscriber list is written by an LLM.

    A pattern that is itself internal (``_turn.*``) matches internal events;
    that is what "opt in explicitly" means.
    """
    internal_event = event_type.startswith(INTERNAL_PREFIX)
    if internal_event and not pattern.startswith(INTERNAL_PREFIX):
        return False
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


class EventBus:
    """Fan-out registry. One instance is enough; see ``event_bus`` below."""

    def __init__(self) -> None:
        self._subs: dict[str, Subscription] = {}
        # Detached deliveries, held so they are not garbage-collected
        # mid-flight — a dropped task loses its exception silently.
        self._inflight: set[asyncio.Task] = set()
        self._emitted = 0

    # ── Subscription ──────────────────────────────────────────────

    def subscribe(
        self,
        handler: Callable[[Any], Awaitable[None]],
        *,
        name: str,
        pattern: str = "*",
        mode: DeliveryMode = DeliveryMode.AWAIT,
        priority: int = PRIORITY_DEFAULT,
        timeout: float | None = None,
        receive_own: bool = False,
    ) -> Subscription:
        """Register ``handler``; replaces any subscription of the same name.

        Replace-on-duplicate rather than raise: a module that is stopped and
        restarted, or a forged module hot-reloaded, re-subscribes under the
        same name, and the alternative is either a leak or a mandatory
        unsubscribe every caller would eventually forget.
        """
        sub = Subscription(
            name=name, pattern=pattern, handler=handler, mode=mode,
            priority=priority, timeout=timeout, receive_own=receive_own,
        )
        if name in self._subs:
            logger.debug("EventBus: replacing subscription '%s'", name)
        self._subs[name] = sub
        return sub

    def unsubscribe(self, name: str) -> bool:
        """Drop a subscription. Returns whether one was actually removed."""
        return self._subs.pop(name, None) is not None

    def subscriptions(self) -> list[Subscription]:
        """All current subscriptions, in delivery order."""
        return sorted(self._subs.values(), key=lambda s: (s.priority, s.name))

    def subscribers_for(self, event_type: str, source_module: str = "") -> list[Subscription]:
        """Which subscriptions a given event would reach, in delivery order."""
        return [s for s in self.subscriptions() if s.matches(event_type, source_module)]

    # ── Emission ──────────────────────────────────────────────────

    async def emit(self, event: Event) -> None:
        """Deliver ``event`` to every matching subscriber.

        AWAIT subscribers run in priority order, one after another, and the
        caller does not return until they are done. SPAWN subscribers are
        launched and left to run. Never raises: an emitter is reporting that
        something happened, and there is nothing useful it could do about a
        subscriber that mishandled the news.
        """
        self._emitted += 1
        event_type = getattr(event, "event_type", "")
        source = getattr(event, "source_module", "")

        for sub in self.subscribers_for(event_type, source):
            if sub.mode is DeliveryMode.SPAWN:
                self._spawn(sub, event)
            else:
                await self._deliver(sub, event)

    def _spawn(self, sub: Subscription, event: Event) -> None:
        try:
            task = asyncio.create_task(
                self._deliver(sub, event), name=f"bus:{sub.name}",
            )
        except RuntimeError:
            # No running loop (sync context). Degrade to skipping rather
            # than exploding in the emitter's face.
            logger.warning(
                "EventBus: cannot spawn '%s' outside an event loop", sub.name,
            )
            return
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _deliver(self, sub: Subscription, event: Event) -> None:
        try:
            if sub.timeout is not None:
                await asyncio.wait_for(sub.handler(event), timeout=sub.timeout)
            else:
                await sub.handler(event)
            sub.delivered += 1
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            sub.failed += 1
            sub.last_error = f"timeout after {sub.timeout}s"
            sub.last_error_at = time.time()
            logger.warning(
                "EventBus: subscriber '%s' timed out on %s after %ss",
                sub.name, getattr(event, "event_type", "?"), sub.timeout,
            )
        except Exception as exc:
            sub.failed += 1
            sub.last_error = f"{type(exc).__name__}: {exc}"
            sub.last_error_at = time.time()
            logger.exception(
                "EventBus: subscriber '%s' failed on %s",
                sub.name, getattr(event, "event_type", "?"),
            )

    async def drain(self) -> None:
        """Wait for in-flight SPAWN deliveries. For shutdown and for tests."""
        inflight = [t for t in self._inflight if not t.done()]
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)

    async def cancel_inflight(self) -> None:
        """Cancel and reap detached deliveries, for a prompt shutdown."""
        inflight = [t for t in self._inflight if not t.done()]
        for task in inflight:
            task.cancel()
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        self._inflight.clear()

    # ── Introspection ─────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Delivery counters — what the logs cannot tell you at a glance.

        Exists because the previous fan-out swallowed every subscriber
        exception into a log line: a handler broken since boot looked
        exactly like a handler with nothing to do.
        """
        return {
            "emitted": self._emitted,
            "subscriptions": [
                {
                    "name": s.name,
                    "pattern": s.pattern,
                    "mode": s.mode.value,
                    "priority": s.priority,
                    "delivered": s.delivered,
                    "failed": s.failed,
                    "last_error": s.last_error,
                }
                for s in self.subscriptions()
            ],
        }

    def reset(self) -> None:
        """Drop every subscription and counter. Tests only."""
        self._subs.clear()
        self._inflight.clear()
        self._emitted = 0


event_bus = EventBus()
