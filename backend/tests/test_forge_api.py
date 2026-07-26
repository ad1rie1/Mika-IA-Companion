"""Tests des garde-fous de ForgeAPI — stockage (quotas), HTTP (allowlist,
IP privées), notify (cooldown), emit (rate limit), config."""
from __future__ import annotations

import pytest

from modules.plugins.forge.api import (
    ForgeAPI,
    ForgeAPIError,
    ForgeStorage,
    _assert_public_host,
)
from modules.plugins.forge.store import validate_manifest


def _make_api(monkeypatch=None, **manifest_overrides) -> ForgeAPI:
    data = {"title": "Test", **manifest_overrides}
    manifest, errors = validate_manifest(data, "api_test")
    assert not errors, errors

    class _HostStub:
        def __init__(self):
            self.notifications = []
            self.emitted = []

        async def notify_from_forged(self, name, summary, details, urgency):
            self.notifications.append(summary)

        async def emit_from_forged(self, name, event_type, data):
            self.emitted.append(event_type)

    return ForgeAPI("api_test", manifest, _HostStub())


# ---------------------------------------------------------------------------
# Stockage
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStorage:
    def test_roundtrip_and_count(self):
        s = ForgeStorage("api_test")
        s.set("notes", "aa", {"v": 1})
        s.set("notes", "bb", [1, 2, 3])
        assert s.get("notes", "aa") == {"v": 1}
        assert s.get("notes", "zz", default="rien") == "rien"
        assert s.count("notes") == 2
        assert s.keys("notes") == ["aa", "bb"]
        found = s.find("notes", limit=10)
        assert {f["key"] for f in found} == {"aa", "bb"}
        assert s.delete("notes", "aa") is True
        assert s.delete("notes", "aa") is False
        assert s.clear("notes") == 1

    def test_isolation_between_modules(self):
        a, b = ForgeStorage("mod_aa"), ForgeStorage("mod_bb")
        a.set("data", "kk", 1)
        assert b.get("data", "kk") is None
        assert b.count() == 0

    def test_record_quota(self, monkeypatch):
        monkeypatch.setattr(
            "modules.plugins.forge.api._limit",
            lambda key, default: 2 if key == "forge.max_records_per_module" else default,
        )
        s = ForgeStorage("api_test")
        s.set("cc", "k1", 1)
        s.set("cc", "k2", 2)
        with pytest.raises(ForgeAPIError, match="quota"):
            s.set("cc", "k3", 3)
        s.set("cc", "k1", 99)  # mise à jour d'une clé existante: toujours OK

    def test_value_size_quota(self, monkeypatch):
        monkeypatch.setattr(
            "modules.plugins.forge.api._limit",
            lambda key, default: 1 if key == "forge.max_value_kb" else default,
        )
        s = ForgeStorage("api_test")
        with pytest.raises(ForgeAPIError, match="grosse"):
            s.set("cc", "big", "x" * 2048)

    def test_non_serializable_handled(self):
        s = ForgeStorage("api_test")
        s.set("cc", "dt", {"objet": object()})  # default=str l'aplatit
        assert isinstance(s.get("cc", "dt")["objet"], str)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class TestHttp:
    def test_scheme_rejected(self):
        api = _make_api(allowed_domains=["exemple.fr"])
        with pytest.raises(ForgeAPIError, match="schéma"):
            api.http_get("ftp://exemple.fr/x")

    def test_domain_not_allowed(self):
        api = _make_api(allowed_domains=["exemple.fr"])
        with pytest.raises(ForgeAPIError, match="non autorisé"):
            api.http_get("https://evil.com/x")

    def test_no_domains_by_default(self):
        api = _make_api()
        with pytest.raises(ForgeAPIError, match="non autorisé"):
            api.http_get("https://exemple.fr/")

    def test_private_ip_blocked_even_if_allowed(self):
        api = _make_api(allowed_domains=["127.0.0.1"])
        with pytest.raises(ForgeAPIError, match="non publique"):
            api.http_get("http://127.0.0.1:8000/api/dev/sleep/wake")

    def test_public_host_guard_direct(self):
        with pytest.raises(ForgeAPIError):
            _assert_public_host("localhost")
        with pytest.raises(ForgeAPIError):
            _assert_public_host("192.168.1.10")

    def test_call_budget(self, monkeypatch):
        api = _make_api(allowed_domains=["exemple.fr"])
        api._http_calls_this_run = 10
        with pytest.raises(ForgeAPIError, match="trop d'appels"):
            api.http_get("https://exemple.fr/")


# ---------------------------------------------------------------------------
# Signaux
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSignals:
    def test_notify_cooldown(self, monkeypatch):
        monkeypatch.setattr(
            "modules.plugins.forge.api._limit",
            lambda key, default: 9999 if key == "forge.notify_cooldown_s" else default,
        )
        api = _make_api()
        assert api.notify_ai("premier") is True
        assert api.notify_ai("deuxième") is False  # cooldown

    def test_emit_rate_limit(self, monkeypatch):
        monkeypatch.setattr(
            "modules.plugins.forge.api._limit",
            lambda key, default: 2 if key == "forge.emit_rate_per_min" else default,
        )
        api = _make_api()
        assert api.emit("un", {}) is True
        assert api.emit("deux", {}) is True
        assert api.emit("trois", {}) is False  # limite atteinte

    def test_emit_requires_type(self):
        api = _make_api()
        with pytest.raises(ForgeAPIError):
            api.emit("", {})


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_unknown_key_raises(self):
        api = _make_api(config=[{"key": "ville", "label": "Ville",
                                 "type": "str", "default": "Paris"}])
        with pytest.raises(ForgeAPIError, match="inconnue"):
            api.config.get("pays")

    @pytest.mark.django_db
    def test_declared_key_falls_back_to_default(self):
        api = _make_api(config=[{"key": "ville", "label": "Ville",
                                 "type": "str", "default": "Paris"}])
        assert api.config.get("ville") == "Paris"

    def test_rows_requires_record_list(self):
        api = _make_api(config=[{"key": "ville", "label": "Ville",
                                 "type": "str"}])
        with pytest.raises(ForgeAPIError):
            api.config.rows("ville")
