"""Config reads must survive being called from the ASGI event loop.

``config_service.get()`` and ``list_rows()`` are synchronous by design —
they are called from provider constructors, engine ``__init__``s and prompt
builders — but half of those call sites run under the ASGI loop, where
Django refuses ORM access on the loop thread.

Both failure modes were live and neither was obvious from the outside:

  - ``list_rows()`` raised ``SynchronousOnlyOperation`` on *every* AI call
    (the router resolves ``ai.models`` each time it routes a role), so every
    conversation turn answered "Oups, j'ai eu un petit bug...".
  - ``get()`` swallowed the *same* exception in ``_resolve``'s bare
    ``except Exception`` and returned the schema default, so a provider key
    configured in the dashboard read back as absent — a wrong answer, not an
    error.

The reads run inside a real event loop here, which is the only place the bug
exists: the same calls from a sync test pass either way.

``transaction=True`` throughout: the wrapper hands the query to a worker
thread, which opens its own connection and therefore sees only *committed*
rows — the same reason ``test_forge_host.py`` carries it.
"""
from __future__ import annotations

import asyncio
import threading

import pytest
from django.core.exceptions import SynchronousOnlyOperation

from configs import service as service_mod
from configs.registry import registry
from configs.service import ConfigService, config_service
from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def declared_keys():
    """A record_list + a scalar key, registered for the duration of a test."""
    entries = (
        ConfigSection(key="test_async", label="Test async"),
        ConfigItem(
            key="test_async.models",
            type="record_list",
            section="test_async",
            label="Modèles",
            record=ConfigRecord(
                name="model_declaration",
                label="Modèle",
                fields=(
                    record_item(key="internal_name", type="str", label="Nom"),
                    record_item(key="provider", type="str", label="Fournisseur"),
                ),
            ),
        ),
        ConfigItem(
            key="test_async.scalar",
            type="str",
            section="test_async",
            label="Scalaire",
            default="défaut",
        ),
    )
    registry.register(entries)
    yield
    registry.unregister(key_prefix="test_async.", section_key="test_async")
    config_service.invalidate_cache()


class TestReadsUnderTheEventLoop:
    """The reported crash, and the silent variant of it."""

    def test_list_rows_from_async_context(self, declared_keys):
        config_service.add_row("test_async.models", {
            "internal_name": "rapide", "provider": "claude",
        })

        async def _read():
            return config_service.list_rows("test_async.models")

        rows = asyncio.run(_read())
        assert [r["payload"]["internal_name"] for r in rows] == ["rapide"]

    def test_get_from_async_context_returns_the_stored_value(self, declared_keys):
        """The silent one: a stored value must not read back as its default."""
        config_service.set("test_async.scalar", "configuré")
        # A fresh service instance — the singleton's cache would hide the bug,
        # and a cold cache is exactly the state a provider constructor hits.
        svc = ConfigService()

        async def _read():
            return svc.get("test_async.scalar")

        assert asyncio.run(_read()) == "configuré"

    def test_sync_callers_are_not_routed_off_loop(self):
        """The inline path stays inline — no thread hop for the sync call sites."""
        seen: list[str] = []

        def _probe(*_args, **_kwargs):
            seen.append(threading.current_thread().name)
            return None

        service_mod.db_read(_probe, "test_async.scalar")
        assert seen == [threading.current_thread().name]

    def test_async_callers_are_routed_off_loop(self):
        """...and the async path really does leave the loop thread."""
        seen: list[str] = []

        def _probe(*_args, **_kwargs):
            seen.append(threading.current_thread().name)
            return None

        async def _go():
            service_mod.db_read(_probe, "test_async.scalar")
            return threading.current_thread().name

        loop_thread = asyncio.run(_go())
        assert seen and seen[0] != loop_thread


class TestTheRawQueryStillRaises:
    """Non-vacuity: without the wrapper, these reads really do blow up.

    If Django ever stopped guarding async ORM access, the tests above would
    pass for the wrong reason and this one turns red to say so.
    """

    def test_orm_from_async_context_is_refused(self):
        from configs.models import ConfigValue

        async def _read():
            return ConfigValue.objects.filter(key="whatever").first()

        with pytest.raises(SynchronousOnlyOperation):
            asyncio.run(_read())
