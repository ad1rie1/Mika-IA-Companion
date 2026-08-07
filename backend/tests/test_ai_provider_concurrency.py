"""Le plafond d'appels simultanés appartient à tous les providers.

Il est né pour Ollama, où le parallélisme est *faux* : un serveur local met
les appels en file au lieu de les exécuter de front, et cette file-là est
comptée dans le timeout de chacun — la concurrence n'y achète pas du débit,
elle transforme « lent » en « échoué ». Mais la raison de plafonner ne
disparaît pas chez un hébergé, elle change : le parallélisme y est réel,
seulement il est facturé et contingenté, et une rafale de boucles de fond
suffit à dépasser une limite de débit.

D'où la règle que ce fichier épingle : **le champ existe partout, seul le
défaut est propre au provider** (1 pour ollama, illimité ailleurs, donc
exactement le comportement d'avant le sémaphore).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


def _make_router(limits: dict[str, int]):
    """Un routeur nu dont ``_concurrency_limit`` est dicté par le test.

    ``AIRouter()`` lit la configuration au démarrage ; ce qui est testé ici
    est la mécanique du créneau, pas le chemin de lecture (couvert plus bas
    sur le registre lui-même).
    """
    from ai.router import AIRouter

    r = AIRouter.__new__(AIRouter)
    r._providers = {}
    r._role_to_internal = {}
    r._declared_models = None
    r._semaphores = {}
    r._semaphore_loop = None
    r._concurrency_limit = lambda name: limits.get(name, 0)
    return r


class TestSchemaDeclaration:
    """Le champ est déclaré pour chaque provider, pas seulement pour Ollama."""

    def test_every_provider_declares_the_knob(self):
        from ai.router import _PROVIDER_CLASSES
        from configs.registry import registry

        declared = {i.key for i in registry.all_items()}
        missing = [
            name for name in _PROVIDER_CLASSES
            if f"ai.{name}.max_concurrent_calls" not in declared
        ]
        assert not missing, f"providers sans plafond configurable : {missing}"

    @pytest.mark.parametrize("provider,expected", [
        ("claude", 0),
        ("openai", 0),
        ("gemini", 0),
        ("glm", 0),
        ("ollama", 1),
        ("ollama_cloud", 0),
    ])
    def test_defaults_cap_only_the_local_server(self, provider, expected):
        # Asserté sur le *registre* : le cache de ``config_service`` est
        # amorcé depuis la vraie base pendant ``AppConfig.ready()``.
        from configs.registry import registry

        item = registry.get(f"ai.{provider}.max_concurrent_calls")
        assert item is not None
        assert item.default == expected

    def test_zero_is_reachable_so_a_cap_can_be_lifted(self):
        # min=1 rendrait « illimité » inexprimable depuis le formulaire, et
        # le seul moyen de rendre son parallélisme à un hébergé plafonné par
        # erreur serait de supprimer la ligne en base.
        from ai.router import _PROVIDER_CLASSES
        from configs.registry import registry

        for name in _PROVIDER_CLASSES:
            item = registry.get(f"ai.{name}.max_concurrent_calls")
            assert item.min == 0, name
            assert item.max is not None and item.max >= 3, name

    def test_fallback_table_never_caps_a_provider_it_does_not_name(self):
        # La table de repli sert quand la base est illisible. Un provider
        # absent doit y retomber sur « illimité » — pas sur un plafond
        # inventé qui n'apparaîtrait dans aucun formulaire.
        from ai.router import _PROVIDER_FALLBACK_CONCURRENCY

        assert _PROVIDER_FALLBACK_CONCURRENCY == {"ollama": 1}


class TestSemaphoreConstruction:

    async def test_zero_means_no_semaphore_at_all(self):
        r = _make_router({"claude": 0})
        assert r._provider_semaphore("claude") is None

    async def test_a_positive_limit_builds_a_semaphore_of_that_size(self):
        r = _make_router({"claude": 3})
        sem = r._provider_semaphore("claude")
        assert sem is not None
        assert sem._value == 3

    async def test_each_provider_gets_its_own_slot(self):
        r = _make_router({"claude": 3, "ollama": 1})
        assert r._provider_semaphore("claude") is not r._provider_semaphore("ollama")
        assert r._provider_semaphore("ollama")._value == 1

    async def test_the_semaphore_is_reused_across_calls(self):
        r = _make_router({"claude": 3})
        assert r._provider_semaphore("claude") is r._provider_semaphore("claude")


class TestSerialisation:
    """Ce que le plafond fait réellement au débit."""

    @staticmethod
    def _router_for(provider: str, limit: int, monkeypatch):
        from ai import router as router_module

        r = _make_router({provider: limit})
        r._resolve = lambda role: (provider, "m", 0.7, "interne")
        r._get_provider = lambda name: MagicMock()
        r._call_timeout = lambda override: 30.0
        monkeypatch.setattr(router_module, "quota_tracker", MagicMock())
        monkeypatch.setattr(router_module, "_reset_usage", lambda: None)
        monkeypatch.setattr(router_module, "_take_usage", lambda: None)
        return r

    async def _run(self, r, n: int, role):
        """Lance ``n`` appels de front, renvoie le pic de simultanéité."""
        live = 0
        peak = 0

        async def invoke(provider, model, temperature):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1
            return "ok", "ok"

        await asyncio.gather(*[
            r._metered_call(role, "sys", "usr", invoke) for _ in range(n)
        ])
        return peak

    async def test_a_capped_provider_never_runs_more_than_its_limit(self, monkeypatch):
        from ai.router import AIRole

        r = self._router_for("claude", 3, monkeypatch)
        assert await self._run(r, 8, AIRole.CONVERSATION) == 3

    async def test_a_one_slot_provider_runs_strictly_one_at_a_time(self, monkeypatch):
        from ai.router import AIRole

        r = self._router_for("ollama", 1, monkeypatch)
        assert await self._run(r, 5, AIRole.CONVERSATION) == 1

    async def test_an_uncapped_provider_keeps_its_parallelism(self, monkeypatch):
        # La raison d'être du défaut à 0 : rien ne change pour une
        # installation hébergée tant que l'utilisateur n'a rien réglé.
        from ai.router import AIRole

        r = self._router_for("claude", 0, monkeypatch)
        assert await self._run(r, 8, AIRole.CONVERSATION) == 8

    async def test_the_slot_is_released_when_the_call_raises(self, monkeypatch):
        from ai.router import AIRole

        r = self._router_for("claude", 1, monkeypatch)

        async def boom(provider, model, temperature):
            raise RuntimeError("provider down")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await r._metered_call(AIRole.CONVERSATION, "s", "u", boom)

        # Un créneau fuité rendrait le troisième appel bloquant, pas rouge.
        assert r._provider_semaphore("claude")._value == 1

    async def test_a_nested_call_reuses_its_caller_slot(self, monkeypatch):
        """Un outil MCP relançant le modèle depuis la boucle d'outils.

        Sans la garde par ContextVar, l'appel imbriqué attendrait un créneau
        que son propre appelant détient : interblocage jusqu'au timeout.
        """
        from ai.router import AIRole

        r = self._router_for("claude", 1, monkeypatch)

        async def inner(provider, model, temperature):
            return "inner", "inner"

        async def outer(provider, model, temperature):
            await asyncio.wait_for(
                r._metered_call(AIRole.VISION_CAPTION, "s", "u", inner),
                timeout=1.0,
            )
            return "outer", "outer"

        await asyncio.wait_for(
            r._metered_call(AIRole.CONVERSATION, "s", "u", outer), timeout=2.0,
        )
        assert r._provider_semaphore("claude")._value == 1
