"""Les tableaux de droits réglés d'un domaine (ADR 0316) : sa part de réglages les range et les rend
(``SettingsPart.access_tables``), la porte des réglages les réunit dans ``Rights.tables`` sans nommer aucun domaine.

- **Tirés à l'ouverture** : la porte parcourt ``DOMAINS`` et prend la part de chaque domaine qui en range, que
  quelqu'un l'ait prise ou non — un tableau réglé vaut dès l'ouverture. Une part qui n'en range pas n'est pas prise.
- **Relus quand la part le demande** (``Settings.reread_rights``), après avoir écrit : ils valent à l'épisode suivant ;
  les autres droits (canaux, familles) ne bougent pas.
- **Deux domaines qui disent la même sorte** sont refusés à l'ouverture, en les nommant.
- ``Rights.sort`` : les tableaux d'une sorte, vides si rien n'y est réglé.

Les domaines y sont factices : une fiche et un module de réglages posés pour le test (``monkeypatch``).
"""

from __future__ import annotations

import asyncio
import sys
import types
from collections.abc import Mapping
from typing import Any

import pytest

from mika.adapters.store_sql import SqlStore
from mika.app import settings as settings_m
from mika.app.domains.domain import Domain
from mika.app.settings import SecretBox, Settings, SettingsPart
from mika.vocab.access import Table, ToolRule
from mika.vocab.rights import Rights

KEY = "coffre_droits"
LINE = ToolRule(who=("proprietaire",), read="seule")


class VaultSettings(SettingsPart):
    """Un coffre factice : le tableau réglé de chaque secret, sous sa clé."""

    def access_tables(self) -> Mapping[str, Mapping[str, Table[Any]]]:
        return {"secrets": {k: Table[ToolRule].model_validate(v) for k, v in dict(self._get(KEY) or {}).items()}}

    async def save(self, name: str, table: Table[ToolRule]) -> None:
        await self._put(KEY, {**dict(self._get(KEY) or {}), name: table.model_dump(mode="json")})
        self.door.reread_rights()


class TwinSettings(VaultSettings):
    """Un second domaine qui dit la même sorte."""


class PlainSettings(SettingsPart):
    """Un domaine qui ne range aucun tableau."""


def _domains(monkeypatch: pytest.MonkeyPatch, **parts: type[SettingsPart]) -> None:
    fiches = []
    for name, kind in parts.items():
        module = types.ModuleType(f"tests_k1_{name}_settings")
        module.SETTINGS = kind  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, module.__name__, module)
        fiches.append(Domain(name, settings=module.__name__))
    monkeypatch.setattr(settings_m, "DOMAINS", (Domain("sans_reglages"), *fiches))


def _run(tmp_path, body):
    async def run():
        store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        try:
            return await body(store)
        finally:
            await store.close()

    return asyncio.run(run())


def test_the_door_pulls_the_tables_at_opening_and_rereads_them_when_asked(tmp_path, monkeypatch):
    _domains(monkeypatch, coffre=VaultSettings, simple=PlainSettings)
    table = Table[ToolRule](lines=(LINE,), default=ToolRule())

    async def body(store):
        first = Settings(store, SecretBox.for_data(tmp_path))
        await first.open()
        assert first.access_tables().sort("secrets") == {}  # la sorte est dite, rien n'y est réglé
        await first.of(VaultSettings).save("cle-ssh", table)
        after_save = first.access_tables()
        family = Table[ToolRule](lines=(), default=ToolRule())
        await first.save_family("memoire", family)
        kept = first.access_tables()
        fresh = Settings(store, SecretBox.for_data(tmp_path))
        untaken = set(fresh._parts)
        await fresh.open()
        return after_save, kept, untaken, fresh, family

    after_save, kept, untaken, fresh, family = _run(tmp_path, body)
    assert after_save.sort("secrets") == {"cle-ssh": table}  # relu dès l'écriture
    assert kept.sort("secrets") == {"cle-ssh": table} and kept.families == {"memoire": family}
    assert not untaken  # rien n'a pris les réglages du coffre avant l'ouverture…
    assert fresh.access_tables().sort("secrets") == {"cle-ssh": table}  # … et ils valent dès l'ouverture
    assert set(fresh._parts) == {VaultSettings}  # une part sans tableau n'est pas prise
    assert fresh.access_tables().sort("rien") == {}


def test_two_domains_that_say_the_same_sort_are_refused_at_opening(tmp_path, monkeypatch):
    _domains(monkeypatch, coffre=VaultSettings, jumeau=TwinSettings)

    async def body(store):
        await Settings(store, SecretBox.for_data(tmp_path)).open()

    with pytest.raises(ValueError, match="« secrets » est dit deux fois") as refused:
        _run(tmp_path, body)
    assert "le domaine « coffre »" in str(refused.value) and "le domaine « jumeau »" in str(refused.value)


def test_a_sort_reads_empty_when_nothing_is_set():
    assert Rights().sort("agendas") == {}
    table = Table[ToolRule](lines=(), default=ToolRule())
    assert Rights(tables={"secrets": {"a": table}}).sort("secrets") == {"a": table}
