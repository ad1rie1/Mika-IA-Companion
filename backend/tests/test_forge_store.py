"""Tests de la couche disque de la Forge — manifest, versions, corbeille.

Pas de DB : tout est filesystem dans un tmp_path.
"""
from __future__ import annotations

import pytest

from modules.plugins.forge import store


@pytest.fixture
def forge_dir(tmp_path, settings):
    settings.FORGE_DIR = str(tmp_path / "forge_modules")
    return tmp_path / "forge_modules"


MANIFEST_OK = {
    "title": "Veille météo",
    "description": "Surveille la météo",
    "schedule": "interval:10m",
    "events": ["rss.new_entry", "chat.*"],
    "views": [{"key": "releves", "label": "Relevés", "icon": "☁"}],
    "config": [
        {"key": "ville", "label": "Ville", "type": "str", "default": "Paris"},
        {"key": "cles", "label": "Clés", "type": "record_list",
         "fields": [{"key": "nom", "label": "Nom", "type": "str"},
                    {"key": "secret", "label": "Secret", "type": "secret"}]},
    ],
    "allowed_domains": ["wttr.in"],
    "context": True,
}


class TestManifestValidation:
    def test_valid_manifest(self, forge_dir):
        manifest, errors = store.validate_manifest(MANIFEST_OK, "veille_meteo")
        assert errors == []
        assert manifest.title == "Veille météo"
        assert manifest.events == ["rss.new_entry", "chat.*"]
        assert manifest.views[0].key == "releves"
        assert manifest.config[1]["fields"][1]["sensitive"] is True
        assert manifest.allowed_domains == ["wttr.in"]

    def test_title_required(self, forge_dir):
        _, errors = store.validate_manifest({}, "abc")
        assert any("title" in e for e in errors)

    def test_bad_names(self, forge_dir):
        for bad in ("AB", "1abc", "a" * 40, "hello-world", "a b"):
            _, errors = store.validate_manifest({"title": "x"}, bad)
            assert errors, f"{bad!r} aurait dû être refusé"

    def test_reserved_name(self, forge_dir):
        _, errors = store.validate_manifest({"title": "x"}, "forge")
        assert any("réservé" in e for e in errors)

    def test_bad_schedule(self, forge_dir):
        _, errors = store.validate_manifest(
            {"title": "x", "schedule": "toutes-les-heures"}, "abc",
        )
        assert any("schedule" in e for e in errors)

    def test_event_schedule_not_supported_via_schedule_field(self, forge_dir):
        _, errors = store.validate_manifest(
            {"title": "x", "schedule": "event:email.new"}, "abc",
        )
        assert errors  # les événements passent par 'events', pas 'schedule'

    def test_bad_event_pattern(self, forge_dir):
        _, errors = store.validate_manifest(
            {"title": "x", "events": ["rss.*.*bad!"]}, "abc",
        )
        assert any("motif" in e for e in errors)

    def test_duplicate_view_keys(self, forge_dir):
        _, errors = store.validate_manifest(
            {"title": "x",
             "views": [{"key": "aa", "label": "A"}, {"key": "aa", "label": "B"}]},
            "abc",
        )
        assert any("dupliquée" in e for e in errors)

    def test_bad_config_type(self, forge_dir):
        _, errors = store.validate_manifest(
            {"title": "x", "config": [{"key": "aa", "type": "blob"}]}, "abc",
        )
        assert any("type invalide" in e for e in errors)

    def test_nested_record_list_forbidden(self, forge_dir):
        _, errors = store.validate_manifest(
            {"title": "x", "config": [
                {"key": "aa", "type": "record_list",
                 "fields": [{"key": "bb", "type": "record_list",
                             "fields": [{"key": "cc", "type": "str"}]}]},
            ]}, "abc",
        )
        assert any("imbriqué" in e for e in errors)

    def test_bad_domain(self, forge_dir):
        _, errors = store.validate_manifest(
            {"title": "x", "allowed_domains": ["http://wttr.in"]}, "abc",
        )
        assert any("domaine" in e for e in errors)


class TestStoreLifecycle:
    def test_write_read_roundtrip(self, forge_dir):
        store.write_module("meteo_watch", MANIFEST_OK, "def on_tick(api):\n    pass\n")
        assert store.module_exists("meteo_watch")
        data = store.read_module("meteo_watch")
        assert data["manifest_raw"]["title"] == "Veille météo"
        assert "on_tick" in data["code"]
        assert data["state"]["enabled"] is True

    def test_versions_archived_on_rewrite(self, forge_dir):
        store.write_module("abc", {"title": "v1"}, "x = 1\n")
        assert store.list_versions("abc") == []
        store.write_module("abc", {"title": "v2"}, "x = 2\n")
        assert len(store.list_versions("abc")) == 1

    def test_rollback_restores_previous(self, forge_dir):
        store.write_module("abc", {"title": "v1"}, "x = 1\n")
        store.write_module("abc", {"title": "v2"}, "x = 2\n")
        ts = store.rollback("abc")
        assert ts
        data = store.read_module("abc")
        assert data["manifest_raw"]["title"] == "v1"
        # le rollback a archivé v2 → un second rollback fait l'aller-retour
        store.rollback("abc")
        assert store.read_module("abc")["manifest_raw"]["title"] == "v2"

    def test_rollback_without_versions(self, forge_dir):
        store.write_module("abc", {"title": "v1"}, "x = 1\n")
        with pytest.raises(store.StoreError):
            store.rollback("abc")

    def test_erase_moves_to_trash(self, forge_dir):
        store.write_module("abc", {"title": "v1"}, "x = 1\n")
        dest = store.erase("abc")
        assert not store.module_exists("abc")
        assert "_trash" in dest
        assert "abc" not in store.list_module_names()

    def test_state_disable_enable(self, forge_dir):
        store.write_module("abc", {"title": "t"}, "x = 1\n")
        store.write_state("abc", enabled=False, disabled_reason="test")
        state = store.read_state("abc")
        assert state["enabled"] is False
        assert state["disabled_reason"] == "test"

    def test_list_ignores_underscore_dirs(self, forge_dir):
        store.write_module("abc", {"title": "t"}, "x = 1\n")
        (forge_dir / "_trash").mkdir(exist_ok=True)
        (forge_dir / "_random").mkdir(exist_ok=True)
        assert store.list_module_names() == ["abc"]

    def test_path_traversal_impossible(self, forge_dir):
        for bad in ("../evil", "a/../../b", "a/b", ".."):
            with pytest.raises(store.StoreError):
                store.read_module(bad)

    def test_versions_pruned(self, forge_dir):
        store.write_module("abc", {"title": "v0"}, "x = 0\n")
        for i in range(1, store.MAX_VERSIONS_KEPT + 4):
            store.write_module("abc", {"title": f"v{i}"}, f"x = {i}\n")
        assert len(store.list_versions("abc")) == store.MAX_VERSIONS_KEPT
