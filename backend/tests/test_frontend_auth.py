"""Frontend authentication — the gate the identity model is built on.

The web client is the one channel where Mika can be *certain* who she is
talking to. That certainty comes from a verified session, so the consumer
refuses unauthenticated connections by default.

Which creates a first-run problem: a fresh clone has no account, and telling
someone to go run ``createsuperuser`` before they can see anything is a poor
introduction. ``/auth/bootstrap`` closes that window — it creates the first
account and only the first.
"""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return Client()


def _post(client, url, **payload):
    return client.post(
        url, data=json.dumps(payload), content_type="application/json",
    )


class TestDefaults:

    def test_consumer_auth_is_required_by_default(self):
        """The frontend must not be anonymous — see identity/trust.py."""
        from django.conf import settings
        assert settings.CONSUMER_REQUIRE_AUTH is True


class TestWhoami:

    def test_reports_the_bootstrap_window_when_no_user_exists(self, client):
        body = client.get("/auth/whoami").json()
        assert body["authenticated"] is False
        assert body["needs_bootstrap"] is True
        assert body["auth_required"] is True

    def test_bootstrap_closes_once_a_user_exists(self, client):
        get_user_model().objects.create_user(username="a", password="x")
        body = client.get("/auth/whoami").json()
        assert body["needs_bootstrap"] is False

    def test_reports_the_server_issued_person_id(self, client):
        user = get_user_model().objects.create_user(username="alice", password="pw")
        client.force_login(user)

        body = client.get("/auth/whoami").json()
        assert body["authenticated"] is True
        assert body["person_id"] == f"user_{user.pk}"
        assert body["display_name"] == "alice"

    def test_display_name_prefers_the_full_name(self, client):
        user = get_user_model().objects.create_user(
            username="alice", password="pw", first_name="Alice", last_name="Martin",
        )
        client.force_login(user)
        assert client.get("/auth/whoami").json()["display_name"] == "Alice Martin"


class TestBootstrap:

    def test_creates_the_first_account_and_logs_it_in(self, client):
        resp = _post(client, "/auth/bootstrap",
                     username="owner", password="corr3ct-h0rse-battery")
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["created"] is True
        assert body["person_id"].startswith("user_")

        user = get_user_model().objects.get(username="owner")
        assert user.is_superuser, "le premier compte est celui du propriétaire"
        # The session is live, so the WebSocket handshake will authenticate.
        assert client.get("/auth/whoami").json()["authenticated"] is True

    def test_refuses_once_any_account_exists(self, client):
        get_user_model().objects.create_user(username="first", password="pw")
        resp = _post(client, "/auth/bootstrap", username="second", password="pw2")
        assert resp.status_code == 409
        assert not get_user_model().objects.filter(username="second").exists()

    def test_rejects_a_weak_password(self, client):
        resp = _post(client, "/auth/bootstrap", username="owner", password="123")
        assert resp.status_code == 400
        assert not get_user_model().objects.exists()

    def test_requires_both_fields(self, client):
        assert _post(client, "/auth/bootstrap", username="owner").status_code == 400
        assert _post(client, "/auth/bootstrap", password="pw").status_code == 400
        assert not get_user_model().objects.exists()

    def test_malformed_body_is_rejected_not_crashed(self, client):
        resp = client.post(
            "/auth/bootstrap", data="not json", content_type="application/json",
        )
        assert resp.status_code == 400


class TestLogin:

    def test_valid_credentials_return_the_identity(self, client):
        get_user_model().objects.create_user(username="alice", password="pw-12345")
        body = _post(client, "/auth/login", username="alice", password="pw-12345").json()
        assert body["authenticated"] is True
        assert body["person_id"].startswith("user_")

    def test_invalid_credentials_are_401(self, client):
        get_user_model().objects.create_user(username="alice", password="pw-12345")
        resp = _post(client, "/auth/login", username="alice", password="wrong")
        assert resp.status_code == 401

    def test_logout_clears_the_session(self, client):
        user = get_user_model().objects.create_user(username="alice", password="pw")
        client.force_login(user)
        client.get("/auth/logout")
        assert client.get("/auth/whoami").json()["authenticated"] is False


@pytest.mark.django_db(transaction=True)
class TestConsumerGate:
    """The socket itself, not just the HTTP surface."""

    @pytest.mark.asyncio
    async def test_unauthenticated_connection_is_refused_when_required(self):
        from unittest.mock import AsyncMock, patch
        from communication.channels.web_frontend import WebSocketConsumer

        c = WebSocketConsumer.__new__(WebSocketConsumer)
        c.scope = {"user": None}
        c.channel_layer = AsyncMock()
        c.channel_name = "test"
        c.accept = AsyncMock()
        c.close = AsyncMock()

        with patch("communication.channels.web_frontend.settings") as fake:
            fake.CONSUMER_REQUIRE_AUTH = True
            await c.connect()

        c.close.assert_awaited_once()
        c.accept.assert_not_awaited()
