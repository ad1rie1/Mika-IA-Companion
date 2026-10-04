"""Tests for backend auth endpoints and protection of configuration views."""

import json

import pytest


@pytest.fixture
def user(db):
    from django.contrib.auth.models import User
    return User.objects.create_user(username="mika_admin", password="s3cret")


def _login(client, username, password):
    return client.post(
        "/auth/login",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )


@pytest.mark.django_db
class TestAuthEndpoints:

    def test_health_is_public(self, client):
        assert client.get("/health").status_code == 200

    def test_login_success(self, client, user):
        resp = _login(client, "mika_admin", "s3cret")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_login_bad_credentials(self, client, user):
        resp = _login(client, "mika_admin", "wrong")
        assert resp.status_code == 401

    def test_whoami_anonymous(self, client):
        assert client.get("/auth/whoami").json()["authenticated"] is False

    def test_whoami_after_login(self, client, user):
        _login(client, "mika_admin", "s3cret")
        body = client.get("/auth/whoami").json()
        assert body["authenticated"] is True
        assert body["username"] == "mika_admin"

    def test_logout(self, client, user):
        _login(client, "mika_admin", "s3cret")
        client.get("/auth/logout")
        assert client.get("/auth/whoami").json()["authenticated"] is False


@pytest.mark.django_db
class TestConfigViewProtection:

    def test_personality_requires_auth(self, client):
        assert client.get("/personality").status_code == 401

    def test_personality_accessible_after_login(self, client, user):
        _login(client, "mika_admin", "s3cret")
        resp = client.get("/personality")
        assert resp.status_code == 200
        assert "name" in resp.json()
