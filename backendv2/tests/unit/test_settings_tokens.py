"""Les jetons qu'on ne fait que vérifier — celui des appareils (``POST /api/perceptions``), celui de la console en
MCP — sont gardés en empreinte SHA-256, jamais scellés (une fuite de ``mind.db`` et de ``secret.key`` ne les rend
pas réutilisables) ; ceux que les réglages d'avant gardaient scellés valent déjà par leur empreinte à la lecture et
sont convertis à l'ouverture (déchiffrés, hachés, le scellé retiré). ``secret.key`` naît en 0600, d'un seul coup."""

from __future__ import annotations

import asyncio
import os
import stat

from cryptography.fernet import Fernet

from mika.adapters.store_sql import SqlStore
from mika.app.settings import CONSOLE_MCP_KEY, SENSORS_KEY, SecretBox, Settings, token_digest


def _run(tmp_path, scenario):
    async def run():
        store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        try:
            box = SecretBox.for_data(tmp_path)
            settings = Settings(store, box)
            await settings.open()
            return await scenario(store, box, settings)
        finally:
            await store.close()

    return asyncio.run(run())


def _rows(store) -> list[str]:
    return [r[0] for r in store.query_mind("SELECT value FROM settings")]


def test_a_new_token_is_kept_only_as_its_digest(tmp_path):
    async def scenario(store, box, settings):
        sensors, console = await settings.new_sensors_token(), await settings.new_console_mcp_token()
        return sensors, console, _rows(store), settings.sensors_digest(), settings.console_mcp_digest(), \
            settings._get(SENSORS_KEY), settings._get(CONSOLE_MCP_KEY)

    sensors, console, rows, sensors_digest, console_digest, sensors_row, console_row = _run(tmp_path, scenario)
    assert sensors_digest == token_digest(sensors) and console_digest == token_digest(console)
    assert all(sensors not in r and console not in r for r in rows)
    assert sensors_row == {"digest": sensors_digest} and console_row == {"digest": console_digest}


def test_a_token_sealed_by_the_old_settings_is_hashed_at_open_and_already_valid_before(tmp_path):
    async def scenario(store, box, settings):
        await settings._put(SENSORS_KEY, {"token_sealed": box.seal("ancien-jeton")})
        await settings._put(CONSOLE_MCP_KEY, {"token_sealed": box.seal("console-d-avant"), "network": True,
                                              "served": ["vues"]})
        other = Settings(store, box)  # pas encore ouvert : rien converti, et pourtant l'empreinte vaut déjà
        before = (other.sensors_digest(), other.console_mcp_digest())
        fresh = Settings(store, box)
        await fresh.open()  # le redémarrage suivant
        return before, fresh._get(SENSORS_KEY), fresh._get(CONSOLE_MCP_KEY), fresh.console_mcp_network(), \
            fresh.console_mcp_served(), _rows(store)

    before, sensors_row, console_row, network, served, rows = _run(tmp_path, scenario)
    assert before == (token_digest("ancien-jeton"), token_digest("console-d-avant"))
    assert sensors_row == {"digest": token_digest("ancien-jeton")}
    assert console_row == {"digest": token_digest("console-d-avant"), "network": True, "served": ["vues"]}
    assert network and served == ("vues",)
    assert all("token_sealed" not in r for r in rows)


def test_a_sealed_token_that_no_longer_opens_is_dropped_and_closes_the_network(tmp_path):
    other = SecretBox(Fernet.generate_key())  # une autre ``secret.key`` : le scellé ne s'ouvre plus

    async def scenario(store, box, settings):
        await settings._put(CONSOLE_MCP_KEY, {"token_sealed": other.seal("x"), "network": True, "served": ["vues"]})
        fresh = Settings(store, box)
        await fresh.open()
        return fresh.console_mcp_digest(), fresh._get(CONSOLE_MCP_KEY), fresh.console_mcp_network()

    digest, row, network = _run(tmp_path, scenario)
    assert digest == "" and row == {"served": ["vues"]} and not network  # le jeton ne valait déjà plus


def test_the_secret_key_is_born_private_whatever_the_umask(tmp_path, monkeypatch):
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data = tmp_path / "data"
    old = os.umask(0)
    try:
        box = SecretBox.for_data(data)
    finally:
        os.umask(old)
    path = data / "secret.key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert SecretBox.for_data(data).open(box.seal("x")) == "x"  # relue : la même clé
