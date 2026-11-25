"""Le réglage des données touristiques (ADR 0245) : la clé de DATAtourisme scellée dans les réglages (jamais en clair
dans ``mind.db``), jamais réaffichée par la console ni écrite dans une trace ; le réglage d'abord, sinon
``MIKA_DATATOURISME_API_KEY`` ; les départements lus comme on les tape ; les bornes des demandes (par heure, jusqu'à la
limite de l'API ; par seconde), relues à chaque demande."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mika.adapters.maps.config import KEY_ENV, KEY_SET, TourismConfig, department_code, tourism_key
from mika.adapters.store_sql import SqlStore
from mika.app.domains.maps.settings import TOURISM_KEY, MapsSettings
from mika.app.settings import SecretBox, Settings
from mika.kernel import forms

KEY = "cle-de-test-scellee-42"


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
        await settings.save_tourism_config(TourismConfig(api_key=KEY, zones=("59", "62"), per_hour=500))
        raw = [r[0] for r in store.query_mind("SELECT value FROM settings")]
        return raw, settings._get(TOURISM_KEY), settings.tourism_config()

    raw, kept, read = _run(tmp_path, scenario)
    assert all(KEY not in r for r in raw) and "api_key" not in kept and kept["api_key_sealed"]
    assert read == TourismConfig(api_key=KEY, zones=("59", "62"), per_hour=500)
    assert not (tmp_path / "mind.db").read_bytes().count(KEY.encode())


def test_an_unreadable_setting_keeps_the_key_and_falls_back_to_the_defaults(tmp_path):
    async def scenario(store, settings):
        await settings.save_tourism_config(TourismConfig(api_key=KEY))
        data = dict(settings._get(TOURISM_KEY))
        await settings._put(TOURISM_KEY, {**data, "zones": ["99"], "per_hour": 5000})
        return settings.tourism_config()

    assert _run(tmp_path, scenario) == TourismConfig(api_key=KEY)


def test_the_key_never_shows_in_a_trace_nor_in_the_console_form():
    cfg = TourismConfig(api_key=KEY)
    assert KEY not in repr(cfg) and KEY not in str(cfg)
    [field] = [f for f in forms.describe(TourismConfig) if f.path == "api_key"]
    assert field.secret and field.kind == "secret"
    assert forms.as_text(field, KEY) == ""
    # un réglage refusé ne recopie jamais la clé dans son erreur
    with pytest.raises(ValidationError) as caught:
        TourismConfig(api_key=KEY, horizon_days=1)
    assert KEY not in str(caught.value)


def test_the_setting_comes_first_then_the_environment(monkeypatch):
    assert tourism_key(TourismConfig()) == ("", "")
    monkeypatch.setenv("MIKA_DATATOURISME_API_KEY", " cle-de-l-environnement ")
    assert tourism_key(TourismConfig()) == ("cle-de-l-environnement", KEY_ENV)
    assert tourism_key(TourismConfig(api_key=KEY)) == (KEY, KEY_SET)


def test_departments_read_as_they_are_typed():
    assert TourismConfig(zones="59, 62\n2a 6 59").zones == ("06", "2A", "59", "62")
    assert department_code("974") == "974"
    for wrong in ("99", "20", "abc", "5900"):
        with pytest.raises(ValueError):
            department_code(wrong)
    with pytest.raises(ValidationError):
        TourismConfig(zones=("59", "99"))


@pytest.mark.parametrize(("field", "value"), [("per_hour", 0), ("per_hour", 1001), ("per_second", 0.0),
                                              ("per_second", 10.5), ("horizon_days", 400), ("night_hour", 24)])
def test_the_bounds_of_the_requests_stay_within_the_api(field, value):
    with pytest.raises(ValidationError):
        TourismConfig(**{field: value})
    assert TourismConfig(per_hour=1000, per_second=10).per_hour == 1000
