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
from channels.routing import URLRouter
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
class TestAsgiAuthWiring:
    """The real socket, through the real ASGI stack.

    These exist because the previous tests only ever checked the *negative*
    half of the contract — that an anonymous connection is refused — and that
    half passed while the application was completely unreachable: the
    WebSocket router had no ``AuthMiddlewareStack``, so ``scope["user"]`` was
    never populated and every connection, valid session or not, was closed
    with 4401. Asserting a door is locked proves nothing about the key.
    """

    #: Any allow-listed dev origin; a browser always sends one.
    ORIGIN = b"http://localhost:3000"

    @classmethod
    async def _connect(cls, cookie_header: bytes | None, origin: bytes | None = b""):
        from channels.testing import WebsocketCommunicator
        from config.asgi import inner_app

        headers = []
        if origin is not None:
            headers.append((b"origin", origin or cls.ORIGIN))
        if cookie_header:
            headers.append((b"cookie", cookie_header))
        comm = WebsocketCommunicator(inner_app, "/ws", headers=headers)
        try:
            return await comm.connect(timeout=5)
        finally:
            await comm.disconnect()

    @pytest.mark.asyncio
    async def test_a_valid_session_is_accepted(self):
        from channels.db import database_sync_to_async

        user = await database_sync_to_async(
            get_user_model().objects.create_user
        )(username="ws_probe", password="pw-probe-12345")

        def _session_cookie():
            client = Client()
            client.force_login(user)
            return f"sessionid={client.cookies['sessionid'].value}".encode()

        cookie = await database_sync_to_async(_session_cookie)()
        connected, _ = await self._connect(cookie)
        assert connected is True, (
            "une session valide doit pouvoir ouvrir le WebSocket — sans "
            "AuthMiddlewareStack, scope['user'] est absent et tout est refuse"
        )

    @pytest.mark.asyncio
    async def test_anonymous_is_still_refused_through_the_real_stack(self):
        connected, code = await self._connect(None)
        assert connected is False
        assert code == 4401

    @pytest.mark.asyncio
    async def test_a_foreign_origin_is_rejected(self):
        """Cross-site WebSocket hijacking.

        CORS does not apply to WebSockets: any page the user visits can open
        the socket, and the browser attaches their session cookie. Without an
        origin check, a third-party page gets an authenticated conversation
        with Mika — reading back memories and profiles as the owner.
        """
        from channels.db import database_sync_to_async

        user = await database_sync_to_async(
            get_user_model().objects.create_user
        )(username="ws_victim", password="pw-probe-12345")

        def _session_cookie():
            client = Client()
            client.force_login(user)
            return f"sessionid={client.cookies['sessionid'].value}".encode()

        cookie = await database_sync_to_async(_session_cookie)()
        connected, _ = await self._connect(cookie, origin=b"https://evil.example")
        assert connected is False, (
            "une page tierce ne doit pas pouvoir ouvrir une session WebSocket "
            "authentifiee avec les cookies de la victime"
        )

    @pytest.mark.asyncio
    async def test_a_missing_origin_is_rejected(self):
        """Browsers always send Origin on a WebSocket handshake."""
        connected, _ = await self._connect(None, origin=None)
        assert connected is False

    def test_the_websocket_stack_is_wrapped(self):
        """Guards the wiring itself, not just its effect.

        Asserts the shape rather than an exact class: the stack legitimately
        grows layers (origin validation was added after session auth), and a
        test pinned to one concrete type breaks on every addition while
        catching nothing extra.
        """
        from config import asgi

        ws_app = asgi.inner_app.application_mapping["websocket"]
        assert not isinstance(ws_app, URLRouter), (
            "URLRouter nu = pas de scope['user'] = 4401 pour tout le monde, "
            "et aucune verification d'origine"
        )


@pytest.mark.django_db(transaction=True)
class TestConsumerGate:
    """The consumer's own decision, isolated from the ASGI stack."""

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
