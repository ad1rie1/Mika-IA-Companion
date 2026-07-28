"""CSRF — the protection that only started mattering once sessions did.

While every endpoint was anonymous, a forged cross-site request bought an
attacker nothing they couldn't already do by calling the API directly. With a
logged-in owner session there are endpoints worth forging: the dashboard
rewrites provider API keys and reads the whole conversation history.

These tests use ``Client(enforce_csrf_checks=True)`` **on purpose**. The
default test client disables CSRF entirely, so a suite written without it will
happily pass against a completely unprotected application — the same way the
WebSocket suite passed while every connection was being refused.
"""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def strict():
    """A client that actually enforces CSRF, unlike the default one."""
    return Client(enforce_csrf_checks=True)


def _json_post(client, url, token=None, **payload):
    headers = {"content_type": "application/json"}
    if token is not None:
        headers["HTTP_X_CSRFTOKEN"] = token
    return client.post(url, data=json.dumps(payload), **headers)


class TestMiddlewareIsActive:

    def test_csrf_middleware_is_installed(self):
        from django.conf import settings
        assert (
            "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE
        ), "sans le middleware, les tokens ne sont jamais verifies"

    def test_no_endpoint_opts_out(self):
        """A middleware every view exempts itself from protects nothing."""
        import pathlib
        import re

        backend = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in backend.rglob("*.py"):
            if "/tests/" in str(path) or "/migrations/" in str(path):
                continue
            if re.search(r"\bcsrf_exempt\b", path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(backend)))
        assert offenders == [], f"csrf_exempt encore present: {offenders}"

    def test_trusted_origins_mirror_cors(self):
        from django.conf import settings
        assert settings.CSRF_TRUSTED_ORIGINS, "un SPA cross-origin ne pourrait pas poster"

    def test_cookie_is_readable_by_the_spa(self):
        """The SPA must read the cookie to echo it back in the header."""
        from django.conf import settings
        assert settings.CSRF_COOKIE_HTTPONLY is False


class TestTokenIsRequired:

    def test_login_without_a_token_is_refused(self, strict):
        get_user_model().objects.create_user(username="alice", password="pw-12345")
        resp = _json_post(strict, "/auth/login", username="alice", password="pw-12345")
        assert resp.status_code == 403

    def test_login_with_a_token_succeeds(self, strict):
        get_user_model().objects.create_user(username="alice", password="pw-12345")
        # whoami plants the cookie — it is the client's first call for exactly
        # this reason.
        strict.get("/auth/whoami")
        token = strict.cookies["csrftoken"].value

        resp = _json_post(
            strict, "/auth/login", token=token,
            username="alice", password="pw-12345",
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_bootstrap_without_a_token_is_refused(self, strict):
        resp = _json_post(
            strict, "/auth/bootstrap", username="owner", password="corr3ct-h0rse",
        )
        assert resp.status_code == 403
        assert not get_user_model().objects.exists()

    def test_a_stale_token_is_refused(self, strict):
        get_user_model().objects.create_user(username="alice", password="pw-12345")
        strict.get("/auth/whoami")
        resp = _json_post(
            strict, "/auth/login", token="not-the-real-token",
            username="alice", password="pw-12345",
        )
        assert resp.status_code == 403


class TestProtectedSurfaces:
    """The endpoints that actually hold something worth stealing."""

    def test_project_creation_needs_a_token(self, strict):
        resp = _json_post(strict, "/api/projects/create", title="forged")
        assert resp.status_code == 403

    def test_dashboard_config_write_needs_a_token(self, strict):
        """The config editor holds the provider API keys."""
        user = get_user_model().objects.create_user(
            username="owner", password="pw", is_staff=True,
        )
        strict.force_login(user)
        resp = strict.patch(
            "/dashboard/api/config/values",
            data=json.dumps({"key": "ai.claude.api_key", "value": "stolen"}),
            content_type="application/json",
        )
        assert resp.status_code == 403


class TestWhoamiPlantsTheCookie:

    def test_cookie_is_set_on_first_call(self, strict):
        resp = strict.get("/auth/whoami")
        assert resp.status_code == 200
        assert "csrftoken" in resp.cookies, (
            "sans ce cookie, le client n'a aucun token a renvoyer et le login "
            "echoue avec un 403 impossible a diagnostiquer"
        )
