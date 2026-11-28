"""Le réglage des avis (ADR 0256) : la clé de Google scellée dans les réglages (jamais en clair dans ``mind.db``),
jamais réaffichée par la console ni écrite dans une trace ou une erreur ; le réglage d'abord, sinon
``MIKA_GOOGLE_PLACES_API_KEY`` ; un réglage illisible garde la clé et revient aux défauts."""

from __future__ import annotations

import asyncio
import os

import pytest
from pydantic import ValidationError

from mika.adapters.maps.config import KEY_ENV, KEY_SET, ReviewsConfig, reviews_key
from mika.adapters.store_sql import SqlStore
from mika.app.domains.maps.settings import REVIEWS_KEY, MapsSettings
from mika.app.settings import SecretBox, Settings
from mika.kernel import forms

KEY = "cle-google-scellee-42"


def _run(tmp_path, scenario):
    async def run():
        store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        try:
            settings = Settings(store, SecretBox.for_data(tmp_path))
            await settings.open()
            return await scenario(store, settings.of(MapsSettings))
        finally:
            await store.close()

    return asyncio.run(run())


def test_the_key_is_sealed_in_the_settings_and_read_back(tmp_path):
    async def scenario(store, settings):
        await settings.save_reviews_config(ReviewsConfig(api_key=KEY, details_per_month=2500, cache_days=10))
        raw = [r[0] for r in store.query_mind("SELECT value FROM settings")]
        return raw, settings._get(REVIEWS_KEY), settings.reviews_config()

    raw, kept, read = _run(tmp_path, scenario)
    assert all(KEY not in r for r in raw) and "api_key" not in kept and kept["api_key_sealed"]
    assert read == ReviewsConfig(api_key=KEY, details_per_month=2500, cache_days=10)
    assert not (tmp_path / "mind.db").read_bytes().count(KEY.encode())


def test_an_unreadable_setting_keeps_the_key_and_falls_back_to_the_defaults(tmp_path):
    async def scenario(store, settings):
        await settings.save_reviews_config(ReviewsConfig(api_key=KEY))
        data = dict(settings._get(REVIEWS_KEY))
        await settings._put(REVIEWS_KEY, {**data, "per_day": 500_000})
        return settings.reviews_config()

    assert _run(tmp_path, scenario) == ReviewsConfig(api_key=KEY)


def test_the_key_never_shows_in_a_trace_nor_in_the_console_form():
    cfg = ReviewsConfig(api_key=KEY)
    assert KEY not in repr(cfg) and KEY not in str(cfg)
    [field] = [f for f in forms.describe(ReviewsConfig) if f.path == "api_key"]
    assert field.secret and field.kind == "secret"
    assert forms.as_text(field, KEY) == ""
    with pytest.raises(ValidationError) as caught:
        ReviewsConfig(api_key=KEY, per_second=50)
    assert KEY not in str(caught.value)


def test_the_setting_comes_first_then_the_environment(monkeypatch):
    assert reviews_key(ReviewsConfig()) == ("", "")
    monkeypatch.setenv("MIKA_GOOGLE_PLACES_API_KEY", " cle-de-l-environnement ")
    assert reviews_key(ReviewsConfig()) == ("cle-de-l-environnement", KEY_ENV)
    assert reviews_key(ReviewsConfig(api_key=KEY)) == (KEY, KEY_SET)


def test_the_tests_never_see_the_key_of_whoever_runs_them():
    assert "MIKA_GOOGLE_PLACES_API_KEY" not in os.environ and os.environ.get("MIKA_ENV_FILE") == ""
