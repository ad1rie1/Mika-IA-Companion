"""Tests d'intégration de l'hôte Forge — cycle de vie complet.

Écrire → charger → tick → événements → disjoncteur → commandes →
vues → config dynamique → outils MCP. DB réelle (transaction=True :
les handlers tournent dans des threads, il faut des commits visibles).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from django.utils import timezone
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async

from modules.types import ModuleEvent

pytestmark = pytest.mark.django_db(transaction=True)


CODE_BASIC = """
def on_tick(api):
    n = api.storage.get('compteur', 'ticks', default=0)
    api.storage.set('compteur', 'ticks', n + 1)
    api.log(f"tick {n + 1}")

def on_event(api, event):
    api.storage.set('evenements', event['type'], event['data'])

def get_context(api):
    n = api.storage.get('compteur', 'ticks', default=0)
    return f"{n} ticks effectués"

def view_stats(api, params):
    n = api.storage.get('compteur', 'ticks', default=0)
    return {
        'columns': [{'key': 'nom', 'label': 'Nom'}, {'key': 'val', 'label': 'Valeur'}],
        'rows': [{'id': 'ticks', 'nom': 'ticks', 'val': n}],
        'html': '<script>alert(1)</script>',
    }

def view_stats_detail(api, item_id):
    return {'fields': [{'label': 'id', 'value': item_id}]}
"""

MANIFEST_BASIC = dict(
    title="Compteur",
    description="Compte les ticks",
    schedule="interval:5s",
    events=["unittest.*"],
    views=[{"key": "stats", "label": "Stats"}],
    config=[{"key": "ville", "label": "Ville", "type": "str",
             "default": "Paris"}],
    context_enabled=True,
)


@pytest.fixture(autouse=True)
def _clean_forge_tables():
    yield
    from modules.plugins.forge.models import ForgeLog, ForgeRecord
    ForgeRecord.objects.all().delete()
    ForgeLog.objects.all().delete()


@pytest.fixture
async def host(tmp_path, settings):
    settings.FORGE_DIR = str(tmp_path / "forge_modules")
    from modules.plugins.forge.module import ForgeModule
    module = ForgeModule()
    module.set_notify_ai(AsyncMock())
    await module.instantiate()
    yield module
    await module.shutdown()
    # nettoie les sections de config dynamiques
    from configs.registry import registry
    registry.unregister(key_prefix="forge.")


async def _create_basic(host, name="compteur_test", **overrides):
    patch = {**MANIFEST_BASIC, **overrides}
    context = patch.pop("context_enabled", True)
    manifest_patch = {
        "title": patch.get("title"),
        "description": patch.get("description"),
        "schedule": patch.get("schedule"),
        "events": patch.get("events"),
        "views": patch.get("views"),
        "config": patch.get("config"),
        "allowed_domains": patch.get("allowed_domains"),
        "context": context,
    }
    return await host.write_module(
        name, code=overrides.get("code", CODE_BASIC),
        manifest_patch=manifest_patch,
    )


# ---------------------------------------------------------------------------
# Écriture + chargement
# ---------------------------------------------------------------------------


class TestWriteAndLoad:
    async def test_create_loads_module(self, host):
        result = await _create_basic(host)
        assert result["ok"], result
        assert "compteur_test" in host._loaded
        lm = host._loaded["compteur_test"]
        assert set(lm.handlers) >= {"on_tick", "on_event", "get_context",
                                    "view_stats", "view_stats_detail"}
        assert lm.next_run_at is not None

    async def test_invalid_code_rejected_atomically(self, host):
        result = await _create_basic(host, code="import os\n")
        assert not result["ok"]
        assert any("import interdit" in e for e in result["errors"])
        assert "compteur_test" not in host._loaded

    async def test_update_archives_and_hot_reloads(self, host):
        await _create_basic(host)
        v2 = "def on_tick(api):\n    api.log('v2')\n"
        result = await host.write_module(
            "compteur_test", code=v2, manifest_patch={},
        )
        assert result["ok"]
        assert result["version"] == 2
        assert host._loaded["compteur_test"].handlers.keys() == {"on_tick"}

    async def test_broken_update_reports_and_rollback_recovers(self, host):
        await _create_basic(host)
        # code valide au sandbox mais qui explose au chargement (top-level)
        broken = "x = 1 / 0\n"
        result = await host.write_module(
            "compteur_test", code=broken, manifest_patch={},
        )
        assert not result["ok"]
        assert "compteur_test" not in host._loaded
        assert "compteur_test" in host._load_errors
        outcome = await host.command("compteur_test", "rollback")
        assert outcome["ok"], outcome
        assert "compteur_test" in host._loaded

    async def test_max_modules_enforced(self, host, monkeypatch):
        async def tiny_cfg(key, default):
            return 1 if key == "forge.max_modules" else default
        monkeypatch.setattr("modules.plugins.forge.module._cfg_async", tiny_cfg)
        assert (await _create_basic(host, name="premier_mod"))["ok"]
        result = await _create_basic(host, name="deuxieme_mod")
        assert not result["ok"]
        assert any("limite" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Exécution: ticks, storage, contexte
# ---------------------------------------------------------------------------


class TestExecution:
    async def test_tick_writes_storage_and_context(self, host):
        await _create_basic(host)
        lm = host._loaded["compteur_test"]
        lm.next_run_at = timezone.now() - timedelta(seconds=1)
        due = host._due_modules()
        assert lm in due
        await host._run_ticks(due)
        from modules.plugins.forge.models import ForgeRecord
        row = await sync_to_async(
            lambda: ForgeRecord.objects.get(
                module_name="compteur_test", collection="compteur", key="ticks",
            ).value,
            thread_sensitive=False,
        )()
        assert row == 1
        assert "1 ticks" in lm.context_cache
        assert lm.next_run_at > timezone.now() - timedelta(seconds=1)
        ctx = host.get_context("user_test")
        assert "compteur_test" in ctx or "1 module" in ctx

    async def test_failing_handler_recorded(self, host):
        code = "def on_tick(api):\n    raise ValueError('boom')\n"
        await _create_basic(host, code=code)
        lm = host._loaded["compteur_test"]
        ok, _, error = await host._run_handler(lm, "on_tick", (), source="tick")
        assert not ok
        assert "boom" in error
        assert lm.consecutive_failures == 1
        assert "boom" in (lm.last_error or "")

    async def test_timeout_interrupts(self, host):
        code = "def on_tick(api):\n    while True:\n        pass\n"
        await _create_basic(host, code=code, schedule="")
        lm = host._loaded["compteur_test"]
        ok, _, error = await host._run_handler(
            lm, "on_tick", (), source="tick", timeout_s=0.5,
        )
        assert not ok
        assert "temps" in error or "bloqué" in error

    async def test_breaker_disables_and_notifies(self, host, monkeypatch):
        async def cfg(key, default):
            return 2 if key == "forge.max_consecutive_failures" else default
        monkeypatch.setattr("modules.plugins.forge.module._cfg_async", cfg)
        code = "def on_tick(api):\n    raise RuntimeError('panne')\n"
        await _create_basic(host, code=code)
        lm = host._loaded["compteur_test"]
        await host._run_handler(lm, "on_tick", (), source="tick")
        assert "compteur_test" in host._loaded
        await host._run_handler(lm, "on_tick", (), source="tick")
        # disjoncteur: déchargé + état persisté + Mika prévenue
        assert "compteur_test" not in host._loaded
        from modules.plugins.forge import store
        state = await sync_to_async(store.read_state,
                                    thread_sensitive=False)("compteur_test")
        assert state["enabled"] is False
        assert "échecs" in (state["disabled_reason"] or "")
        assert host._notify_ai.await_count == 1

    async def test_test_module_returns_logs_and_result(self, host):
        await _create_basic(host)
        result = await host.test_module("compteur_test", "get_context", None)
        assert result["ok"], result
        assert "ticks" in str(result.get("result"))


# ---------------------------------------------------------------------------
# Événements
# ---------------------------------------------------------------------------


class TestEvents:
    async def test_bus_event_dispatched_to_subscriber(self, host):
        await _create_basic(host)
        await host.on_event(ModuleEvent(
            event_type="unittest.ping", source_module="rss",
            data={"x": 1},
        ))
        for _ in range(50):
            if not host._event_tasks:
                break
            await asyncio.sleep(0.05)
        from modules.plugins.forge.models import ForgeRecord
        value = await sync_to_async(
            lambda: ForgeRecord.objects.get(
                module_name="compteur_test", collection="evenements",
                key="unittest.ping",
            ).value,
            thread_sensitive=False,
        )()
        assert value == {"x": 1}

    async def test_non_matching_event_ignored(self, host):
        await _create_basic(host)
        await host.on_event(ModuleEvent(
            event_type="email.new", source_module="email", data={},
        ))
        assert not host._event_tasks

    async def test_emit_fans_out_to_sibling_not_self(self, host):
        emitter = """
def on_tick(api):
    api.emit('alerte', {'niveau': 3})

def on_event(api, event):
    api.storage.set('recus', event['type'], 1)
"""
        listener = """
def on_event(api, event):
    api.storage.set('recus', event['type'], event['data'])
"""
        r1 = await _create_basic(
            host, name="emetteur_mod", code=emitter,
            events=["forge.emetteur_mod.*"], views=[], config=[],
        )
        assert r1["ok"], r1
        r2 = await _create_basic(
            host, name="ecouteur_mod", code=listener,
            events=["forge.emetteur_mod.*"], views=[], config=[],
        )
        assert r2["ok"], r2
        lm = host._loaded["emetteur_mod"]
        ok, _, error = await host._run_handler(lm, "on_tick", (), source="tick")
        assert ok, error
        await asyncio.sleep(0.3)  # fire-and-forget → laisser courir
        from modules.plugins.forge.models import ForgeRecord
        def _fetch():
            return {
                (r.module_name, r.key): r.value
                for r in ForgeRecord.objects.filter(collection="recus")
            }
        received = await sync_to_async(_fetch, thread_sensitive=False)()
        assert ("ecouteur_mod", "forge.emetteur_mod.alerte") in received
        assert ("emetteur_mod", "forge.emetteur_mod.alerte") not in received


# ---------------------------------------------------------------------------
# Commandes de gestion
# ---------------------------------------------------------------------------


class TestCommands:
    async def test_disable_enable_cycle(self, host):
        await _create_basic(host)
        outcome = await host.command("compteur_test", "disable")
        assert outcome["ok"]
        assert "compteur_test" not in host._loaded
        outcome = await host.command("compteur_test", "enable")
        assert outcome["ok"]
        assert "compteur_test" in host._loaded

    async def test_erase_wipes_storage_and_unloads(self, host):
        await _create_basic(host)
        lm = host._loaded["compteur_test"]
        lm.next_run_at = timezone.now() - timedelta(seconds=1)
        await host._run_ticks([lm])
        from modules.plugins.forge.models import ForgeRecord
        count_before = await sync_to_async(
            ForgeRecord.objects.filter(module_name="compteur_test").count,
            thread_sensitive=False,
        )()
        assert count_before > 0
        outcome = await host.command("compteur_test", "erase")
        assert outcome["ok"]
        assert "compteur_test" not in host._loaded
        count_after = await sync_to_async(
            ForgeRecord.objects.filter(module_name="compteur_test").count,
            thread_sensitive=False,
        )()
        assert count_after == 0

    async def test_reset_storage(self, host):
        await _create_basic(host)
        lm = host._loaded["compteur_test"]
        lm.next_run_at = timezone.now() - timedelta(seconds=1)
        await host._run_ticks([lm])
        outcome = await host.command("compteur_test", "reset_storage")
        assert outcome["ok"]
        from modules.plugins.forge.models import ForgeRecord
        count = await sync_to_async(
            ForgeRecord.objects.filter(module_name="compteur_test").count,
            thread_sensitive=False,
        )()
        assert count == 0

    async def test_unknown_command_and_module(self, host):
        assert not (await host.command("nexiste_pas", "reload"))["ok"]
        await _create_basic(host)
        assert not (await host.command("compteur_test", "explode"))["ok"]


# ---------------------------------------------------------------------------
# Vues dashboard
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, **params):
        self.GET = params


class TestViews:
    async def test_views_exposed_and_sanitized(self, host):
        await _create_basic(host)
        views = host.get_views()
        keys = {v.key for v in views}
        assert "forge" in keys
        assert "compteur_test__stats" in keys
        forged = next(v for v in views if v.key == "compteur_test__stats")
        assert forged.detail_handler is not None
        assert "Compteur" in forged.label
        payload = await forged.data_handler(_FakeRequest(page="0"))
        assert "rows" in payload
        assert "html" not in payload  # payload assaini (anti-XSS)
        detail = await forged.detail_handler(_FakeRequest(), "ticks")
        assert detail["fields"][0]["value"] == "ticks"

    async def test_view_without_handler_not_exposed(self, host):
        await _create_basic(
            host, code="def on_tick(api):\n    pass\n",
        )  # manifest déclare 'stats' mais le code n'a pas view_stats
        keys = {v.key for v in host.get_views()}
        assert "compteur_test__stats" not in keys

    async def test_admin_view_lists_modules(self, host):
        await _create_basic(host)
        admin = next(v for v in host.get_views() if v.key == "forge")
        payload = await admin.data_handler(_FakeRequest())
        modules_tab = next(t for t in payload["tabs"] if t["key"] == "modules")
        assert any(r["name"] == "compteur_test" for r in modules_tab["rows"])
        detail = await admin.detail_handler(_FakeRequest(), "compteur_test")
        assert any(f["key"] == "code" for f in detail["fields"])


# ---------------------------------------------------------------------------
# Config dynamique
# ---------------------------------------------------------------------------


class TestDynamicConfig:
    async def test_config_registered_and_resolvable(self, host):
        await _create_basic(host)
        from configs.registry import registry
        item = registry.get("forge.compteur_test.ville")
        assert item is not None
        assert item.section == "forge_compteur_test"
        value = await sync_to_async(
            lambda: __import__("configs.service", fromlist=["config_service"])
            .config_service.get("forge.compteur_test.ville"),
            thread_sensitive=False,
        )()
        assert value == "Paris"

    async def test_config_unregistered_on_erase(self, host):
        await _create_basic(host)
        from configs.registry import registry
        assert registry.get("forge.compteur_test.ville") is not None
        await host.command("compteur_test", "erase")
        assert registry.get("forge.compteur_test.ville") is None


# ---------------------------------------------------------------------------
# Outils MCP
# ---------------------------------------------------------------------------


def _tool(host, name):
    from modules.plugins.forge.tools import build_tools
    return next(t for t in build_tools(host) if t.name == name)


def _tool_text(result: dict) -> str:
    return result["content"][0]["text"]


class TestTools:
    async def test_write_then_list_then_read(self, host):
        write = _tool(host, "forge_write_module")
        result = await write.handler({
            "name": "outil_test",
            "code": "def on_tick(api):\n    api.log('via outil')\n",
            "title": "Via outil",
            "schedule": "interval:1m",
        })
        text = _tool_text(result)
        assert "OK" in text and "on_tick" in text

        listing = _tool_text(await _tool(host, "forge_list_modules").handler({}))
        assert "outil_test" in listing and "actif" in listing

        read = _tool_text(await _tool(host, "forge_read_module").handler(
            {"name": "outil_test"},
        ))
        assert "manifest.yaml" in read and "via outil" in read

    async def test_write_invalid_reports_errors(self, host):
        write = _tool(host, "forge_write_module")
        result = await write.handler({
            "name": "outil_test",
            "code": "import os\n",
            "title": "Cassé",
        })
        text = _tool_text(result)
        assert "Refusé" in text and "import interdit" in text

    async def test_command_and_test_tools(self, host):
        await _create_basic(host)
        cmd = _tool(host, "forge_command")
        assert "OK" in _tool_text(await cmd.handler(
            {"name": "compteur_test", "command": "disable"},
        ))
        assert "OK" in _tool_text(await cmd.handler(
            {"name": "compteur_test", "command": "enable"},
        ))
        test_tool = _tool(host, "forge_test_module")
        text = _tool_text(await test_tool.handler(
            {"name": "compteur_test", "handler": "on_tick"},
        ))
        assert "SUCCÈS" in text
        logs = _tool_text(await _tool(host, "forge_read_logs").handler(
            {"name": "compteur_test"},
        ))
        assert "tick 1" in logs
