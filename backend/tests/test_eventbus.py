"""EventBus — routing, ordering, isolation, and the wiring that replaced
the hard-coded fan-out in ``ModuleManager.emit_event``.

The old emitter awaited a special-cased conscience callback, looped over
running modules, then imported ``projects.runner`` inline. Two of its three
consumers were named in the emitter's own source. These tests pin the
properties that made that arrangement replaceable — and the ones that make
it safe to let Mika add subscribers at runtime.
"""

import asyncio

import pytest

from modules.types import ModuleEvent
from utils.eventbus import (
    PRIORITY_DEFAULT,
    PRIORITY_LATE,
    PRIORITY_OBSERVER,
    DeliveryMode,
    EventBus,
    _pattern_matches,
)


def _event(event_type="thing.happened", source="somewhere", **data):
    return ModuleEvent(event_type=event_type, source_module=source, data=data)


# ---------------------------------------------------------------------------
# 1. Pattern matching
# ---------------------------------------------------------------------------


class TestPatternMatching:
    """Only a trailing star, on purpose: the vocabulary is dotted namespaces
    and a general glob invites patterns nobody can reason about once the
    subscriber list is written by an LLM."""

    def test_star_matches_everything(self):
        assert _pattern_matches("*", "anything.at.all")

    def test_exact_match(self):
        assert _pattern_matches("email.received", "email.received")

    def test_exact_pattern_rejects_other_types(self):
        assert not _pattern_matches("email.received", "email.sent")

    def test_namespace_prefix(self):
        assert _pattern_matches("forge.*", "forge.compteur.tick")

    def test_namespace_prefix_rejects_siblings(self):
        assert not _pattern_matches("forge.*", "email.received")

    def test_namespace_prefix_does_not_match_the_bare_namespace(self):
        # "forge.*" means "something inside forge", not forge itself.
        assert not _pattern_matches("forge.*", "forge")


# ---------------------------------------------------------------------------
# 2. Delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDelivery:

    async def test_matching_subscriber_receives_the_event(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="a", pattern="email.*")

        await bus.emit(_event("email.received"))
        assert [e.event_type for e in seen] == ["email.received"]

    async def test_non_matching_subscriber_is_not_woken(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="a", pattern="email.*")

        await bus.emit(_event("rss.new_entry"))
        assert seen == []

    async def test_a_subscriber_does_not_receive_its_own_events(self):
        """Generalised from the old ``module.name != event.source_module``.

        The Forge relies on this: it fans an event out to sibling forged
        modules itself, excluding the emitter, and would double-deliver if
        the bus handed the event back to it.
        """
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="forge")

        await bus.emit(_event("forge.counter.tick", source="forge"))
        assert seen == []

    async def test_receive_own_opt_in(self):
        bus = EventBus()
        seen = []
        bus.subscribe(
            lambda e: _record(seen, e), name="forge", receive_own=True,
        )

        await bus.emit(_event("forge.counter.tick", source="forge"))
        assert len(seen) == 1

    async def test_emit_with_no_subscribers_is_a_no_op(self):
        await EventBus().emit(_event())


# ---------------------------------------------------------------------------
# 3. Ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOrdering:

    async def test_priority_decides_delivery_order(self):
        """The conscience must file its Observation before anything reacts —
        that ordering used to be implicit in the emitter's source (callback
        first, then the module loop). It is now a declared priority."""
        bus = EventBus()
        order = []
        bus.subscribe(lambda e: _record(order, "late"), name="c",
                      priority=PRIORITY_LATE)
        bus.subscribe(lambda e: _record(order, "default"), name="b",
                      priority=PRIORITY_DEFAULT)
        bus.subscribe(lambda e: _record(order, "observer"), name="a",
                      priority=PRIORITY_OBSERVER)

        await bus.emit(_event())
        assert order == ["observer", "default", "late"]

    async def test_equal_priority_is_ordered_by_name(self):
        bus = EventBus()
        order = []
        for name in ("zeta", "alpha", "mu"):
            bus.subscribe(lambda e, n=name: _record(order, n), name=name)

        await bus.emit(_event())
        assert order == ["alpha", "mu", "zeta"]


# ---------------------------------------------------------------------------
# 4. AWAIT vs SPAWN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeliveryModes:

    async def test_await_mode_blocks_the_emitter(self):
        bus = EventBus()
        done = []

        async def slow(event):
            await asyncio.sleep(0.05)
            done.append(1)

        bus.subscribe(slow, name="slow", mode=DeliveryMode.AWAIT)
        await bus.emit(_event())
        assert done == [1]

    async def test_spawn_mode_returns_before_the_subscriber_finishes(self):
        """The mode that did not exist before. Everything was awaited, so an
        RSS poll emitting an entry paid for the conscience's LLM
        interpretation inline."""
        bus = EventBus()
        started = asyncio.Event()
        done = []

        async def slow(event):
            started.set()
            await asyncio.sleep(0.05)
            done.append(1)

        bus.subscribe(slow, name="slow", mode=DeliveryMode.SPAWN)
        await bus.emit(_event())

        assert done == []               # emitter did not wait
        await asyncio.wait_for(started.wait(), timeout=1)
        await bus.drain()
        assert done == [1]              # but the work did happen

    async def test_drain_waits_for_spawned_work(self):
        bus = EventBus()
        done = []

        async def handler(event):
            await asyncio.sleep(0.01)
            done.append(1)

        bus.subscribe(handler, name="s", mode=DeliveryMode.SPAWN)
        await bus.emit(_event())
        await bus.drain()
        assert done == [1]

    async def test_cancel_inflight_reaps_spawned_work(self):
        bus = EventBus()

        async def forever(event):
            await asyncio.sleep(3600)

        bus.subscribe(forever, name="s", mode=DeliveryMode.SPAWN)
        await bus.emit(_event())
        await bus.cancel_inflight()
        assert bus._inflight == set()


# ---------------------------------------------------------------------------
# 5. Failure isolation — the property the whole design rests on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFailureIsolation:

    async def test_a_broken_subscriber_does_not_stop_the_fan_out(self):
        """One bad plugin must not silence every other. With modules written
        at runtime this is not a hypothetical."""
        bus = EventBus()
        seen = []

        async def boom(event):
            raise RuntimeError("boom")

        bus.subscribe(boom, name="a", priority=10)
        bus.subscribe(lambda e: _record(seen, "b"), name="b", priority=20)
        bus.subscribe(lambda e: _record(seen, "c"), name="c", priority=30)

        await bus.emit(_event())
        assert seen == ["b", "c"]

    async def test_emit_never_raises(self):
        bus = EventBus()

        async def boom(event):
            raise RuntimeError("boom")

        bus.subscribe(boom, name="a")
        await bus.emit(_event())        # must not raise

    async def test_failures_are_counted_not_swallowed(self):
        """The old fan-out logged and moved on, so a handler broken since
        boot looked exactly like a handler with nothing to do."""
        bus = EventBus()

        async def boom(event):
            raise ValueError("nope")

        bus.subscribe(boom, name="a")
        await bus.emit(_event())
        await bus.emit(_event())

        sub = bus.subscriptions()[0]
        assert sub.failed == 2
        assert sub.delivered == 0
        assert "ValueError: nope" in sub.last_error

    async def test_successful_deliveries_are_counted(self):
        bus = EventBus()
        bus.subscribe(lambda e: _noop(), name="a")
        await bus.emit(_event())
        assert bus.subscriptions()[0].delivered == 1

    async def test_timeout_bounds_an_await_subscriber(self):
        bus = EventBus()

        async def hang(event):
            await asyncio.sleep(30)

        bus.subscribe(hang, name="a", timeout=0.05)
        await asyncio.wait_for(bus.emit(_event()), timeout=2)

        sub = bus.subscriptions()[0]
        assert sub.failed == 1
        assert "timeout" in sub.last_error

    async def test_stats_report_every_subscription(self):
        bus = EventBus()
        bus.subscribe(lambda e: _noop(), name="a", pattern="email.*")
        await bus.emit(_event("email.received"))

        stats = bus.stats()
        assert stats["emitted"] == 1
        assert stats["subscriptions"][0]["name"] == "a"
        assert stats["subscriptions"][0]["delivered"] == 1


# ---------------------------------------------------------------------------
# 6. Subscription management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscriptionManagement:

    async def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="a")

        assert bus.unsubscribe("a") is True
        await bus.emit(_event())
        assert seen == []

    async def test_duplicate_name_replaces_rather_than_leaks(self):
        """A hot-reloaded forged module re-subscribes under the same name.
        Raising would break reload; appending would double-deliver."""
        bus = EventBus()
        calls = []
        bus.subscribe(lambda e: _record(calls, "old"), name="a")
        bus.subscribe(lambda e: _record(calls, "new"), name="a")

        await bus.emit(_event())
        assert calls == ["new"]
        assert len(bus.subscriptions()) == 1


class TestSubscriptionIntrospection:
    """Synchronous surface — no event loop needed to ask what would route
    where, which is what makes it usable from an admin view."""

    def test_unsubscribe_unknown_name_is_false(self):
        assert EventBus().unsubscribe("nope") is False

    def test_subscribers_for_previews_routing(self):
        bus = EventBus()
        bus.subscribe(lambda e: _noop(), name="a", pattern="email.*")
        bus.subscribe(lambda e: _noop(), name="b", pattern="rss.*")

        names = [s.name for s in bus.subscribers_for("email.received")]
        assert names == ["a"]

    def test_reset_clears_everything(self):
        bus = EventBus()
        bus.subscribe(lambda e: _noop(), name="a")
        bus.reset()
        assert bus.subscriptions() == []
        assert bus.stats()["emitted"] == 0


# ---------------------------------------------------------------------------
# 7. Wiring — the consumers that used to be named inside the emitter
# ---------------------------------------------------------------------------


class TestCoreSubscribersAreDeclaredNotHardcoded:

    def test_projects_subscribes_itself_at_app_ready(self):
        """`event:<type>` schedule rules used to be served by an inline
        ``from projects.runner import project_runner`` at the tail of
        emit_event. The interest is now declared by the projects app."""
        from utils.eventbus import event_bus

        assert "projects" in {s.name for s in event_bus.subscriptions()}

    def test_projects_runs_late(self):
        from utils.eventbus import event_bus

        sub = next(s for s in event_bus.subscriptions() if s.name == "projects")
        assert sub.priority == PRIORITY_LATE

    def test_emit_event_no_longer_names_its_consumers(self):
        """The regression guard: emit_event must stay a delegation."""
        import inspect

        from modules.manager import ModuleManager

        src = inspect.getsource(ModuleManager.emit_event)
        assert "project_runner" not in src
        assert "_conscience_callback" not in src
        assert "bus.emit" in src


@pytest.mark.asyncio
class TestConscienceSubscription:

    async def test_set_conscience_registers_an_observer_subscription(self):
        """The compatibility shim still used by ASGI startup."""
        from modules.manager import ModuleManager
        from utils.eventbus import event_bus

        previous = event_bus._subs.get("conscience")
        try:
            seen = []
            ModuleManager().set_conscience(lambda e: _record(seen, e))

            sub = next(
                s for s in event_bus.subscriptions() if s.name == "conscience"
            )
            assert sub.priority == PRIORITY_OBSERVER
            assert sub.mode is DeliveryMode.AWAIT

            await event_bus.emit(_event("chat.message", source="frontend"))
            assert len(seen) == 1
        finally:
            event_bus.unsubscribe("conscience")
            if previous is not None:
                event_bus._subs["conscience"] = previous


# ---------------------------------------------------------------------------
# 8. Module attachment is owned by the lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestModuleAttachment:
    """Subscribing at start and unsubscribing at stop is what makes the
    subscriber list the truth, rather than something re-derived from
    ``is_running`` on every single event."""

    def _module(self, name="probe", seen=None):
        from modules.base import BaseModule

        class _Probe(BaseModule):
            async def instantiate(self): ...
            async def shutdown(self): ...
            async def on_event(self, event):
                (seen if seen is not None else []).append(event)

        return _Probe(name)

    async def _lifecycle(self, bus):
        from modules.lifecycle import ModuleLifecycle
        from modules.registry import ModuleRegistry

        return ModuleLifecycle(ModuleRegistry(), bus)

    async def test_starting_a_module_subscribes_it(self):
        bus = EventBus()
        lifecycle = await self._lifecycle(bus)
        module = self._module()

        await lifecycle._start_module(module)
        assert "probe" in {s.name for s in bus.subscriptions()}

    async def test_stopping_a_module_unsubscribes_it(self):
        bus = EventBus()
        lifecycle = await self._lifecycle(bus)
        module = self._module()

        await lifecycle._start_module(module)
        await lifecycle._stop_module(module)
        assert bus.subscriptions() == []

    async def test_a_module_that_failed_to_start_is_not_subscribed(self):
        """Delivering to a module whose instantiate() blew up turns one
        broken plugin into an exception on every signal in the system."""
        from modules.base import BaseModule

        class _Broken(BaseModule):
            async def instantiate(self):
                raise RuntimeError("no credentials")

            async def shutdown(self): ...

        bus = EventBus()
        lifecycle = await self._lifecycle(bus)

        assert await lifecycle._start_module(_Broken("broken")) is False
        assert bus.subscriptions() == []

    async def test_module_declares_its_pattern_and_mode(self):
        from modules.base import BaseModule

        class _Picky(BaseModule):
            EVENT_PATTERN = "email.*"
            EVENT_MODE = "spawn"
            EVENT_TIMEOUT = 5.0

            async def instantiate(self): ...
            async def shutdown(self): ...

        bus = EventBus()
        lifecycle = await self._lifecycle(bus)
        await lifecycle._start_module(_Picky("picky"))

        sub = bus.subscriptions()[0]
        assert sub.pattern == "email.*"
        assert sub.mode is DeliveryMode.SPAWN
        assert sub.timeout == 5.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _record(sink, value):
    sink.append(value)


async def _noop():
    return None
