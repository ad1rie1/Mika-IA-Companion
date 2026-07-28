"""`BaseModule` — what a module is actually required to provide.

The interface carried fourteen hooks. Measured across the nine concrete
modules, the two that were `@abstractmethod` — `instantiate` and `shutdown` —
were the two that three of them had no use for: `memory_tools`,
`identity_tools` and `project_tools` are tool facades over subsystems the
ASGI lifespan already owns, and wrote empty bodies purely to satisfy the ABC.
Meanwhile `deliver()` was declared here and implemented by **nobody**.

So the interface was simultaneously too demanding and too broad, in opposite
directions. These tests pin the corrected contract.
"""

from __future__ import annotations

import inspect

import pytest

from modules.base import BaseModule


def _concrete_modules() -> list[type]:
    """Every BaseModule subclass the app actually registers."""
    import django.apps  # noqa: F401  (ensures apps are loaded)

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    return [c for c in walk(BaseModule) if not inspect.isabstract(c)]


# ---------------------------------------------------------------------------
# 1. The minimum
# ---------------------------------------------------------------------------


class TestMinimalModule:

    def test_a_module_needs_only_a_name(self):
        """The tool-facade shape this codebase keeps growing: no resources
        to open, nothing to close, one list of tools."""

        class ToolsOnly(BaseModule):
            def return_tools(self):
                return []

        module = ToolsOnly("tools_only")
        assert module.name == "tools_only"

    @pytest.mark.asyncio
    async def test_lifecycle_defaults_are_no_ops(self):
        class ToolsOnly(BaseModule):
            pass

        module = ToolsOnly("tools_only")
        await module.instantiate()
        await module.shutdown()

    @pytest.mark.asyncio
    async def test_it_starts_and_stops_through_the_manager(self):
        """End-to-end: the default lifecycle is enough to be run."""
        class ToolsOnly(BaseModule):
            pass

        from modules.lifecycle import ModuleLifecycle
        from modules.registry import ModuleRegistry
        from utils.eventbus import EventBus

        lifecycle = ModuleLifecycle(ModuleRegistry(), EventBus())
        module = ToolsOnly("tools_only")

        assert await lifecycle._start_module(module) is True
        assert module.is_running
        await lifecycle._stop_module(module)
        assert not module.is_running

    def test_every_optional_hook_has_a_usable_default(self):
        class Bare(BaseModule):
            pass

        module = Bare("bare")
        assert module.is_available() is True
        assert module.return_tools() == []
        assert module.get_capabilities() == []
        assert module.get_routes() == []
        assert module.get_views() == []
        assert module.get_models() == []
        assert module.config_schema() == []
        assert module.get_context("user_1") == ""
        assert module.get_status().name == "bare"


# ---------------------------------------------------------------------------
# 2. Delivery is not a module capability
# ---------------------------------------------------------------------------


class TestDeliveryMovedOff:

    def test_base_module_no_longer_declares_deliver(self):
        """It returned False for every module that ever existed."""
        assert not hasattr(BaseModule, "deliver")

    def test_no_concrete_module_implements_it_either(self):
        """The measurement that justified moving it. If this ever fails, a
        module has genuinely grown outbound delivery — good; `can_deliver`
        will pick it up by duck-typing, no inheritance needed."""
        implementers = [c.__name__ for c in _concrete_modules() if "deliver" in c.__dict__]
        assert implementers == []

    def test_the_capability_lives_with_delivery(self):
        from communication.delivery import Deliverable, can_deliver

        class Channel:
            is_running = True

            async def deliver(self, output, interlocutor):
                return True

        assert can_deliver(Channel())
        assert isinstance(Channel(), Deliverable)

    def test_something_without_deliver_is_rejected(self):
        from communication.delivery import can_deliver

        class NotAChannel:
            is_running = True

        assert not can_deliver(NotAChannel())

    def test_the_real_telegram_channel_qualifies(self):
        """The only implementer in the codebase — and never a module."""
        from communication.channels.telegram import TelegramChannel
        from communication.delivery import can_deliver

        assert can_deliver(TelegramChannel)
        assert not issubclass(TelegramChannel, BaseModule)

    @pytest.mark.asyncio
    async def test_delivering_to_a_non_deliverer_says_so(self):
        """Previously this reached `channel.deliver(...)`, raised
        AttributeError, and was reported as "deliver() failed"."""
        from unittest.mock import patch

        from pipeline.broadcast import _deliver_via_module

        class Module:
            is_running = True

        class Target:
            channel = "some_module"
            person_id = "user_1"

        with patch("communication.delivery.get_channel", return_value=Module()):
            assert await _deliver_via_module(Target(), object()) is False


# ---------------------------------------------------------------------------
# 3. The registered modules still satisfy the contract
# ---------------------------------------------------------------------------


class TestRegisteredModules:

    def test_the_app_registers_modules(self):
        assert _concrete_modules(), "aucun BaseModule concret trouvé"

    @pytest.mark.django_db
    def test_each_declares_a_name(self):
        # list_all() reads ModuleState, hence the DB mark.
        from modules.manager import module_manager

        for entry in module_manager.list_all():
            assert entry["name"]

    def test_event_attributes_have_sane_defaults(self):
        class Bare(BaseModule):
            pass

        module = Bare("bare")
        assert module.EVENT_PATTERN == "*"
        assert module.EVENT_MODE == "await"
        assert module.EVENT_TIMEOUT is None
