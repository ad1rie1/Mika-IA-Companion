"""Tests for per-person module context scoping (owner vs public, leak prevention)."""

import pytest

from modules.base import BaseModule
from modules.manager import ModuleManager, _is_owner


class _FakeModule(BaseModule):
    async def instantiate(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def is_available(self):
        return True


class _OwnerModule(_FakeModule):
    CONTEXT_VISIBILITY = "owner"

    def get_context(self, person_id: str = "") -> str:
        return "3 nouveaux emails"


class _PublicModule(_FakeModule):
    CONTEXT_VISIBILITY = "public"

    def get_context(self, person_id: str = "") -> str:
        return f"bonjour {person_id}"


def _running(module):
    module._running = True
    return module


class TestIsOwner:

    def test_authenticated_user_is_owner(self):
        assert _is_owner("user_7") is True

    def test_conscience_is_owner(self):
        assert _is_owner("conscience_mika") is True

    def test_module_internal_is_owner(self):
        assert _is_owner("module_email") is True

    def test_anonymous_is_not_owner(self):
        assert _is_owner("anon_abcd1234") is False

    def test_empty_is_not_owner(self):
        assert _is_owner("") is False

    def test_external_contact_is_not_owner(self):
        assert _is_owner("tg_999") is False


class TestCollectContextScoping:

    def _manager_with(self, *modules):
        mgr = ModuleManager()
        for m in modules:
            mgr._modules[m.name] = _running(m)
        return mgr

    def test_owner_context_hidden_from_anonymous(self):
        mgr = self._manager_with(_OwnerModule("email"))
        assert mgr.collect_context("anon_x") == ""

    def test_owner_context_shown_to_owner(self):
        mgr = self._manager_with(_OwnerModule("email"))
        ctx = mgr.collect_context("user_1")
        assert "3 nouveaux emails" in ctx

    def test_public_context_shown_to_anyone(self):
        mgr = self._manager_with(_PublicModule("greeter"))
        assert "bonjour anon_x" in mgr.collect_context("anon_x")

    def test_person_id_threaded_to_module(self):
        mgr = self._manager_with(_PublicModule("greeter"))
        assert "bonjour tg_42" in mgr.collect_context("tg_42")

    def test_mixed_modules_filtered_correctly(self):
        mgr = self._manager_with(_OwnerModule("email"), _PublicModule("greeter"))
        anon = mgr.collect_context("anon_x")
        assert "emails" not in anon and "bonjour" in anon
        owner = mgr.collect_context("user_1")
        assert "emails" in owner and "bonjour" in owner
