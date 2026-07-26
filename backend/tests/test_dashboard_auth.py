"""The dashboard auth gate.

The dashboard exposes the conversation history and the config editor (with
provider API keys) over 66 URL patterns, none of which checked auth.
Decorating each invites the next route to be added without the decorator, so
the gate covers the prefix in one middleware.
"""
from __future__ import annotations

import pytest


def _response(path, *, require_auth, user=None):
    from unittest.mock import MagicMock

    from dashboard.middleware import DashboardAuthMiddleware
    from django.test import override_settings

    sentinel = MagicMock(name="downstream-response")
    mw = DashboardAuthMiddleware(lambda r: sentinel)
    request = MagicMock()
    request.path = path
    request.user = user

    with override_settings(DASHBOARD_REQUIRE_AUTH=require_auth,
                           LOGIN_URL="/admin/login/"):
        return mw(request), sentinel


def _user(*, authenticated=True, staff=True):
    from unittest.mock import MagicMock
    u = MagicMock()
    u.is_authenticated = authenticated
    u.is_staff = staff
    return u


class TestGateDisabled:

    def test_passes_through_when_disabled(self):
        got, sentinel = _response(
            "/dashboard/souvenirs/", require_auth=False, user=_user(
                authenticated=False, staff=False))
        assert got is sentinel


class TestGateEnabled:

    def test_anonymous_html_is_redirected_to_login(self):
        got, sentinel = _response(
            "/dashboard/souvenirs/", require_auth=True,
            user=_user(authenticated=False, staff=False))
        assert got is not sentinel
        assert got.status_code == 302
        assert "/admin/login/" in got["Location"]
        # The destination is preserved so login lands back on the page.
        assert "next=/dashboard/souvenirs/" in got["Location"]

    def test_anonymous_api_gets_401_json_not_a_redirect(self):
        got, sentinel = _response(
            "/dashboard/api/messages", require_auth=True,
            user=_user(authenticated=False, staff=False))
        assert got is not sentinel
        assert got.status_code == 401

    def test_staff_user_is_allowed(self):
        got, sentinel = _response(
            "/dashboard/api/config/values", require_auth=True,
            user=_user(authenticated=True, staff=True))
        assert got is sentinel

    def test_authenticated_non_staff_is_refused(self):
        # A chat-frontend account must not inherit the config editor.
        got, sentinel = _response(
            "/dashboard/api/config/values", require_auth=True,
            user=_user(authenticated=True, staff=False))
        assert got is not sentinel
        assert got.status_code == 401

    def test_missing_user_attribute_is_refused(self):
        got, sentinel = _response(
            "/dashboard/", require_auth=True, user=None)
        assert got is not sentinel
        assert got.status_code == 302

    @pytest.mark.parametrize("path", [
        "/", "/health", "/ws", "/api/projects/", "/admin/login/",
    ])
    def test_non_dashboard_paths_are_never_gated(self, path):
        got, sentinel = _response(
            path, require_auth=True,
            user=_user(authenticated=False, staff=False))
        assert got is sentinel, f"{path} must not be gated"


class TestDefaults:

    def test_gate_is_off_by_default(self):
        # A fresh install has no superuser; locking the owner out of their own
        # admin before they can create one is worse than loopback exposure.
        from django.conf import settings
        assert settings.DASHBOARD_REQUIRE_AUTH is False

    def test_server_binds_loopback_by_default(self):
        from django.conf import settings
        assert settings.API_HOST == "127.0.0.1"

    def test_cors_is_not_wildcarded(self):
        from django.conf import settings
        assert settings.CORS_ALLOW_ALL_ORIGINS is False
        assert settings.CORS_ALLOWED_ORIGINS
