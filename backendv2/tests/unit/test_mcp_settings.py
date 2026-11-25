"""Ce qu'un serveur MCP fait d'elle, écrit dans les réglages (``app/domains/tools/store.py``, ADR 0128, 0131) — sur des
réglages réels :

- brancher crée sa fiche, et refuse un nom pris, par l'opérateur ou par un serveur du système ;
- régler réécrit sa fiche, ce qui en dépend calculé sur la fiche relue ; un nom inconnu est refusé ;
- un serveur du système ne règle que ses accès, rangés à part, et rien de ce qui suit son plugin ;
- retirer ôte sa fiche, même masquée par un serveur du système du même nom, et refuse un serveur du système sans
  fiche et un nom inconnu ;
- deux écritures qui se croisent ne s'effacent pas (``Settings.writing``) ;
- le client MCP retire par là (``unplug``) ; sans de quoi enregistrer, il refuse.
"""

from __future__ import annotations

import asyncio

import pytest

from mika.adapters.mcp.config import McpConfig, McpServer
from mika.adapters.mcp.hub import McpHub
from mika.adapters.mcp.system import SystemServers
from mika.adapters.store_sql.store import SqlStore
from mika.app.domains.tools import system as system_mcp
from mika.app.domains.tools.settings import ToolsSettings
from mika.app.domains.tools.store import McpSettingsStore
from mika.app.settings import SecretBox, Settings
from mika.plugins import web

NOTES = {"purpose": "ses notes", "transport": "distant", "url": "https://notes.example.test/mcp"}
AGENDA = {"purpose": "son agenda", "transport": "distant", "url": "https://agenda.example.test/mcp"}


@pytest.fixture
async def settings(tmp_path):
    store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await store.open()
    s = Settings(store, SecretBox.for_data(tmp_path))
    await s.open()
    yield s.of(ToolsSettings)
    await store.close()


def _store(settings: ToolsSettings) -> McpSettingsStore:
    """Le magasin des fiches, avec le serveur ``web`` qu'apporte le plugin système du même nom."""
    system = SystemServers(lambda: system_mcp.provided(lambda owner: web.WebParams() if owner == "web" else None),
                           access=settings.mcp_system_access)
    return McpSettingsStore(settings, system)


async def test_plugging_creates_its_card_and_refuses_a_name_already_taken(settings):
    store = _store(settings)
    await store.settle("notes", NOTES, create=True)
    assert settings.mcp().servers["notes"].purpose == "ses notes"
    with pytest.raises(ValueError, match="un serveur s'appelle déjà « notes »"):
        await store.settle("notes", AGENDA, create=True)
    with pytest.raises(ValueError, match="un serveur s'appelle déjà « web »"):  # le nom d'un serveur du système
        await store.settle("web", AGENDA, create=True)
    assert set(settings.mcp().servers) == {"notes"} and settings.mcp().servers["notes"].purpose == "ses notes"


async def test_settling_rewrites_its_card_from_the_card_read_again(settings):
    store = _store(settings)
    await store.settle("notes", NOTES, create=True)
    await store.settle("notes", {"when_to_use": "quand on parle de ses carnets"})
    kept = settings.mcp().servers["notes"]
    assert kept.when_to_use == "quand on parle de ses carnets" and kept.purpose == "ses notes"
    # ce qui dépend de la fiche se calcule sur celle qu'on relit
    await store.settle("notes", lambda spec: {"purpose": spec.purpose + ", et ses brouillons"})
    assert settings.mcp().servers["notes"].purpose == "ses notes, et ses brouillons"
    with pytest.raises(ValueError, match="ce serveur ne se règle pas ici : un serveur du système"):
        await store.settle("absent", {"when_to_use": "jamais"})
    with pytest.raises(ValueError, match="il n'existe plus"):
        await store.settle("absent", lambda spec: {"when_to_use": "jamais"})
    with pytest.raises(ValueError):  # une fiche invalide n'est pas écrite
        await store.settle("notes", {"enabled": "peut-être"})
    assert settings.mcp().servers["notes"].enabled is True


async def test_a_system_server_settles_only_its_access_kept_apart(settings):
    store = _store(settings)
    with pytest.raises(ValueError, match="seuls ses accès se règlent ici"):
        await store.settle("web", {"purpose": "autre chose", "default_read": "carte"})
    with pytest.raises(ValueError):  # validés sur sa fiche : un accès invalide n'est pas rangé
        await store.settle("web", {"default_read": "peut-être"})
    assert settings.mcp_system_access() == {}
    await store.settle("web", {"default_read": "carte"})
    assert settings.mcp_system_access() == {"web": {"default_read": "carte"}}
    assert "web" not in settings.mcp().servers  # rien dans les fiches de l'opérateur
    assert store.system.config(settings.mcp()).servers["web"].default_read == "carte"


async def test_removing_takes_its_card_out_and_refuses_a_system_server_or_an_unknown_name(settings):
    store = _store(settings)
    await store.settle("notes", NOTES, create=True)
    await store.settle("agenda", AGENDA, create=True)
    await store.remove("notes")
    assert set(settings.mcp().servers) == {"agenda"}
    with pytest.raises(ValueError, match="ce serveur n'existe plus"):
        await store.remove("notes")
    with pytest.raises(ValueError, match="un serveur du système suit les paramètres de son plugin : il ne se retire"):
        await store.remove("web")
    assert set(settings.mcp().servers) == {"agenda"}


async def test_removing_a_card_hidden_by_a_system_server_of_the_same_name_takes_it_out(settings):
    """Une fiche « web » branchée quand le plugin web était inactif, masquée depuis par le serveur du système : elle se
    retire, et le serveur du système reste ce que son plugin en fait."""
    store = _store(settings)
    await settings.save_mcp(McpConfig(servers={"web": McpServer.model_validate(NOTES)}))
    assert store.system.config(settings.mcp()).servers["web"].purpose != "ses notes"  # masquée
    await store.remove("web")
    assert "web" not in settings.mcp().servers
    assert "web" in store.system.config(settings.mcp()).servers
    with pytest.raises(ValueError, match="un serveur du système suit les paramètres de son plugin : il ne se retire"):
        await store.remove("web")  # sans fiche, le serveur du système ne se retire pas ici


async def test_a_removal_and_a_setting_at_once_do_not_erase_each_other(settings, monkeypatch):
    """Une écriture qui prend son temps : sous ``Settings.writing``, l'autre attend puis relit — ni le serveur retiré
    ne revient, ni le réglage de l'autre ne se perd."""
    store = _store(settings)
    await store.settle("notes", NOTES, create=True)
    await store.settle("agenda", AGENDA, create=True)
    real = settings.save_mcp

    async def slow(cfg: McpConfig) -> McpConfig:
        await asyncio.sleep(0)
        return await real(cfg)

    monkeypatch.setattr(settings, "save_mcp", slow)
    await asyncio.gather(store.remove("notes"), store.settle("agenda", {"when_to_use": "quand on parle de demain"}))
    servers = settings.mcp().servers
    assert set(servers) == {"agenda"} and servers["agenda"].when_to_use == "quand on parle de demain"


def _no_network(name, spec):
    raise OSError("pas de réseau dans ce test")


async def test_the_mcp_client_unplugs_through_the_store_and_refuses_without_it(settings):
    store = _store(settings)
    await store.settle("notes", NOTES, create=True)
    hub = McpHub(settings.mcp, dict, lambda reviews: asyncio.sleep(0), connect=_no_network,
                 settle=store.settle, remove=store.remove)
    changes: list[int] = []
    hub.on_change(lambda: changes.append(1))
    assert hub.status("notes") is not None
    await hub.unplug("notes")
    assert "notes" not in settings.mcp().servers and hub.status("notes") is None and changes
    with pytest.raises(ValueError, match="ce serveur n'existe plus"):
        await hub.unplug("notes")
    await hub.aclose()
    bare = McpHub(settings.mcp, dict, lambda reviews: asyncio.sleep(0), connect=_no_network)
    with pytest.raises(ValueError, match="les réglages des serveurs ne s'enregistrent pas d'ici"):
        await bare.unplug("agenda")
    await bare.aclose()
