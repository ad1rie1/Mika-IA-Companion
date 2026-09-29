"""Preuve M8 — sauvegarde → restauration → même état.

Une journée vécue pour de vrai (conversation, consolidation, index) ; on
archive, on restaure ailleurs, et l'on retrouve : le même état rejoué, les
mêmes souvenirs, le même index de vecteurs une fois reconstruit (``views.db``
n'est pas sauvegardée), ses secrets lisibles, ses ateliers et ses apps. Une
archive altérée est refusée sans rien toucher ; un dossier occupé n'est
remplacé qu'à la demande, et mis de côté.
"""

from __future__ import annotations

import asyncio
import tarfile
from pathlib import Path

import pytest

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.store_sqlite import SqliteStore
from mika.app import backup
from mika.app.cli import replay_verify
from mika.app.settings import SecretBox, Settings
from mika.contracts import memory as memory_c
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.mika import AFTERNOON, boot, build, connect, said

WEEK = [
    "Mardi j'ai un entretien d'embauche chez Ubisoft, je stresse un peu",
    "Samedi c'est le mariage de ma sœur Julie à Lyon",
    "Mon chat Moustache est malade depuis dimanche",
    "Je me suis mise à la course à pied, cinq kilomètres ce matin",
    "J'ai fini de lire Dune hier soir, c'était génial",
    "Au fait je déménage le mois prochain à Nantes",
]
CANARY_KEY = "sk-ant-api-canari-7f3a"


def live(data: Path, *, start: int = AFTERNOON, talk: bool = True) -> dict:
    """Fait vivre Mika sur ``data`` ; rend ce qu'on comparera."""
    clock = SimClock(start)
    llm = PersonaSimLLM(clock, seed=1, latency=2.0, abstain_rate=0.0)
    kernel, clock, _, _ = build(data, lambda req: None, clock=clock, llm=llm)

    async def main() -> dict:
        await boot(kernel)
        if talk:
            await connect(kernel, "user_2", "Alice")
            for text in WEEK:
                await (await kernel.perceive(said("user_2", text))).reply
                await asyncio.sleep(60)
        await asyncio.sleep(15 * 60)  # consolidation, puis index des vecteurs
        await kernel.lanes.join()
        out = {
            "items": sorted(kernel.mind.store.query_mind(
                f"SELECT id, kind, text, about, status FROM {memory_c.ITEMS_TABLE}")),
            "vectors": kernel.ports["vectors"].digest(),
            "indexed": len(kernel.ports["vectors"].indexed()),
        }
        await kernel.stop()
        return out

    return run_virtual(clock, main)


def settle(data: Path) -> None:
    """Ce qui vit hors du journal : un secret chiffré, un atelier, une app."""

    async def run() -> None:
        store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
        await store.open()
        settings = Settings(store, SecretBox.for_data(data))
        await settings.open()
        await settings.save_llm(LLMConfig(backends={"claude": BackendSpec(kind="claude", model="claude-sonnet-5",
                                                                          api_key=CANARY_KEY)}))
        await store.close()

    asyncio.run(run())
    (data / "ateliers" / "3-bonjour").mkdir(parents=True)
    (data / "ateliers" / "3-bonjour" / "bonjour.py").write_text("print('bonjour')\n", encoding="utf-8")
    (data / "forge" / "cafe").mkdir(parents=True)
    (data / "forge" / "cafe" / "manifest.yaml").write_text("title: Veille café\n", encoding="utf-8")


def secret_of(data: Path) -> str:
    async def run() -> str:
        store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
        await store.open()
        settings = Settings(store, SecretBox.for_data(data))
        key = settings.llm().backends["claude"].api_key
        await store.close()
        return key

    return asyncio.run(run())


def test_backup_restore_rebuild_gives_back_the_same_life(tmp_path, monkeypatch):
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest, restored = tmp_path / "data", tmp_path / "archives", tmp_path / "restauree"
    before = live(data)
    assert before["items"] and before["indexed"] > 0  # une vraie journée : souvenirs et vecteurs
    settle(data)
    original = backup.state_of(data / "mind.db")

    made = backup.backup(data, dest)
    assert (made.head, made.state) == original  # l'état rejoué depuis la copie est celui du dossier
    assert made.archive.name.startswith("mika-") and made.files >= 4
    with tarfile.open(made.archive) as tar:
        names = tar.getnames()
    assert "data/mind.db" in names and "data/secret.key" in names and "data/MANIFEST.json" in names
    assert "data/ateliers/3-bonjour/bonjour.py" in names and "data/forge/cafe/manifest.yaml" in names
    assert not any(n.startswith("data/views.db") for n in names)  # jetable : reconstruite
    assert backup.verify(made.archive).state == made.state

    back = backup.restore(made.archive, restored)
    assert (back.head, back.state) == original
    assert not (restored / "views.db").exists()
    assert asyncio.run(replay_verify(restored))["identiques"]  # rejeu depuis la genèse = instantané + queue
    assert secret_of(restored) == CANARY_KEY  # ses clés restent lisibles
    assert (restored / "ateliers" / "3-bonjour" / "bonjour.py").read_text() == "print('bonjour')\n"

    # elle redémarre sur la copie : les vues se reconstruisent à l'identique
    after = live(restored, start=AFTERNOON + 3600 * 10**6, talk=False)
    assert after["items"] == before["items"]
    assert after["vectors"] == before["vectors"] and after["indexed"] == before["indexed"]


def test_an_altered_archive_is_refused_and_nothing_is_touched(tmp_path, monkeypatch):
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    unpacked = tmp_path / "déballée"
    with tarfile.open(made.archive) as tar:
        tar.extractall(unpacked, filter="data")
    target = unpacked / "data" / "mind.db"
    raw = bytearray(target.read_bytes())
    raw[len(raw) // 2] ^= 0xFF  # un octet de travers suffit
    target.write_bytes(bytes(raw))
    forged = dest / "mika-falsifiee.tar.gz"
    with tarfile.open(forged, "w:gz") as tar:
        tar.add(unpacked / "data", arcname="data")
    victim = tmp_path / "cible"
    with pytest.raises(backup.BackupError, match="altéré"):
        backup.restore(forged, victim)
    assert not victim.exists()
    with pytest.raises(backup.BackupError, match="altéré"):
        backup.verify(forged)


def test_an_archive_that_does_not_replay_to_its_manifest_is_refused(tmp_path, monkeypatch):
    """Des sommes justes ne suffisent pas : la copie doit rejouer à l'état annoncé."""
    import json

    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    unpacked = tmp_path / "déballée"
    with tarfile.open(made.archive) as tar:
        tar.extractall(unpacked, filter="data")
    manifest = unpacked / "data" / "MANIFEST.json"
    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["state"] = "0" * 32  # un autre état annoncé, fichiers intacts
    manifest.write_text(json.dumps(content), encoding="utf-8")
    forged = dest / "mika-autre-etat.tar.gz"
    with tarfile.open(forged, "w:gz") as tar:
        tar.add(unpacked / "data", arcname="data")
    victim = tmp_path / "cible"
    with pytest.raises(backup.BackupError, match="ne rejoue pas"):
        backup.restore(forged, victim)
    assert not victim.exists()
    with pytest.raises(backup.BackupError, match="ne rejoue pas"):
        backup.verify(forged)


def test_an_occupied_folder_is_replaced_only_on_demand_and_kept_aside(tmp_path, monkeypatch):
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    occupied = tmp_path / "occupee"
    occupied.mkdir()
    (occupied / "mind.db").write_bytes(b"une autre vie")
    with pytest.raises(backup.BackupError, match="n'est pas vide"):
        backup.restore(made.archive, occupied)
    assert (occupied / "mind.db").read_bytes() == b"une autre vie"
    done = backup.restore(made.archive, occupied, force=True)
    aside = [p for p in tmp_path.iterdir() if p.name.startswith("occupee.avant-restauration-")]
    assert len(aside) == 1 and (aside[0] / "mind.db").read_bytes() == b"une autre vie"
    assert done.state == made.state
    with pytest.raises(backup.BackupError, match="destination"):
        backup.backup(data, data / "archives")


def test_old_archives_are_pruned(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    for day in range(1, 5):
        backup.backup(data, dest, keep=2, now=datetime(2026, 9, day, 3, 0, tzinfo=UTC))
    assert sorted(p.name for p in dest.glob("mika-*.tar.gz")) == ["mika-20260903-030000.tar.gz",
                                                                  "mika-20260904-030000.tar.gz"]
