"""Tests for per-person module context scoping (owner vs public, leak prevention).

« Owner » est le niveau propriétaire de ``identity/roles.py`` : opérateur
(``is_staff``), ``OWNER_PERSON_IDS``, canaux internes. Un ``user_*`` sans
``is_staff`` est un compte de conversation et ne voit pas le contexte privé.
"""

import pytest
from django.contrib.auth import get_user_model

from old.backend.identity import roles
from old.backend.modules.base import BaseModule
from old.backend.modules.collectors import is_owner
from old.backend.modules.manager import ModuleManager


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


@pytest.fixture
def operateur(db):
    roles.invalidate()
    return get_user_model().objects.create_user(
        username="ops", password="x", is_staff=True,
    )


@pytest.fixture
def invite(db):
    roles.invalidate()
    return get_user_model().objects.create_user(username="inv", password="x")


class TestIsOwner:

    def test_operator_account_is_owner(self, operateur):
        assert is_owner(f"user_{operateur.pk}") is True

    def test_chat_account_is_not_owner(self, invite):
        assert is_owner(f"user_{invite.pk}") is False

    def test_conscience_is_owner(self):
        assert is_owner("conscience_mika") is True

    def test_module_internal_is_owner(self):
        assert is_owner("module_email") is True

    def test_anonymous_is_not_owner(self):
        assert is_owner("anon_abcd1234") is False

    def test_empty_is_not_owner(self):
        assert is_owner("") is False

    def test_external_contact_is_not_owner(self):
        assert is_owner("tg_999") is False


@pytest.mark.django_db
class TestCollectContextScoping:

    def _manager_with(self, *modules):
        mgr = ModuleManager()
        for m in modules:
            mgr.registry.activate(_running(m))
        return mgr

    def test_owner_context_hidden_from_anonymous(self):
        mgr = self._manager_with(_OwnerModule("email"))
        assert mgr.collect_context("anon_x") == ""

    def test_owner_context_shown_to_owner(self, operateur):
        mgr = self._manager_with(_OwnerModule("email"))
        ctx = mgr.collect_context(f"user_{operateur.pk}")
        assert "3 nouveaux emails" in ctx

    def test_owner_context_hidden_from_chat_account(self, invite):
        mgr = self._manager_with(_OwnerModule("email"))
        assert mgr.collect_context(f"user_{invite.pk}") == ""

    def test_public_context_shown_to_anyone(self):
        mgr = self._manager_with(_PublicModule("greeter"))
        assert "bonjour anon_x" in mgr.collect_context("anon_x")

    def test_person_id_threaded_to_module(self):
        mgr = self._manager_with(_PublicModule("greeter"))
        assert "bonjour tg_42" in mgr.collect_context("tg_42")

    def test_mixed_modules_filtered_correctly(self, operateur):
        mgr = self._manager_with(_OwnerModule("email"), _PublicModule("greeter"))
        anon = mgr.collect_context("anon_x")
        assert "emails" not in anon and "bonjour" in anon
        owner = mgr.collect_context(f"user_{operateur.pk}")
        assert "emails" in owner and "bonjour" in owner
