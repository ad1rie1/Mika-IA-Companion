"""La sauvegarde sur un serveur MariaDB (ADR 0101, point 10) — seulement dans la voie ``--mariadb``.

Une journée vécue, ses bases sur le serveur et une app forgée avec sa base : l'archive porte le dossier et une copie
SQL de chaque base (``views`` exceptée) ; elle se vérifie en rejouant ``mind`` rechargé dans une base de travail ; elle
se restaure sous un autre préfixe (une autre installation sur le même serveur) et l'on retrouve la même vie, la même
base d'app ; ``views`` repart vide. Une copie altérée est refusée sans rien toucher ; des bases en service ne sont
remplacées qu'à la demande, copiées d'abord dans le dossier mis de côté ; une archive de fichiers ne se restaure pas
sur un serveur.
"""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

import pytest

from mika.adapters.database import Target
from mika.adapters.forge.bases import ForgeBases
from mika.app import backup, backup_server
from tests.fixtures import backend
from tests.fixtures.mika import AFTERNOON
from tests.unit.test_backup import live


@pytest.fixture(autouse=True)
def _server_only(monkeypatch):
    if not backend.active():
        pytest.skip("la voie MariaDB (--mariadb)")
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)


def _prefix() -> str:
    return os.environ["MIKA_DATABASE_PREFIX"]


def _app_base(data: Path) -> ForgeBases:
    """Une app forgée (son code dans le dossier) et sa base sur le serveur."""
    (data / "forge" / "cafe").mkdir(parents=True, exist_ok=True)
    (data / "forge" / "cafe" / "main.py").write_text("def view(api):\n    return 1\n", encoding="utf-8")
    bases = ForgeBases(data / "forge", server=backend.url(), prefix=_prefix())
    bases.execute("cafe", "CREATE TABLE prix (jour VARCHAR(10) PRIMARY KEY, euros INTEGER)")
    bases.execute("cafe", "INSERT INTO prix VALUES ('lundi', 3)")
    return bases


def _other_prefix(monkeypatch) -> str:
    """Une autre installation sur le même serveur : un autre préfixe (supprimé à la fin du test, lui aussi)."""
    first, second = _prefix(), backend.prefix()
    monkeypatch.setenv("MIKA_DATABASE_PREFIX", second)
    return first


def test_a_server_archive_restores_the_same_life_and_app_base_elsewhere(tmp_path, monkeypatch):
    data, dest, restored = tmp_path / "data", tmp_path / "archives", tmp_path / "restauree"
    before = live(data)
    assert before["items"]
    _app_base(data).close()

    made = backup.backup(data, dest)
    with tarfile.open(made.archive) as tar:
        names = tar.getnames()
    assert {"bases/mind.sql", "bases/mail.sql", "bases/feeds.sql", "bases/teams.sql", "bases/forge/cafe.sql",
            "data/MANIFEST.json", "data/forge/cafe/main.py"} <= set(names)
    assert not any(n.startswith("bases/views") or n.endswith(".db") for n in names)  # rien que le serveur garde
    assert backup.verify(made.archive).state == made.state

    first = _other_prefix(monkeypatch)
    back = backup.restore(made.archive, restored)
    assert (back.head, back.state) == (made.head, made.state)
    assert not backup_server.exists(Target(url=backend.url(), name=f"{_prefix()}views"))  # se reconstruira
    after = live(restored, start=AFTERNOON + 3600 * 10**6, talk=False)
    assert after["items"] == before["items"]
    app = ForgeBases(restored / "forge", server=backend.url(), prefix=_prefix())
    try:
        assert app.query("cafe", "SELECT jour, euros FROM prix") == [{"jour": "lundi", "euros": 3}]
    finally:
        app.close()
    backend.drop_session_prefix(first)


def test_an_altered_copy_is_refused_and_nothing_is_touched(tmp_path, monkeypatch):
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    unpacked = tmp_path / "déballée"
    with tarfile.open(made.archive) as tar:
        tar.extractall(unpacked, filter="data")
    copy = unpacked / "bases" / "mind.sql"
    copy.write_text(copy.read_text(encoding="utf-8").replace("INSERT INTO", "INSERT  INTO", 1), encoding="utf-8")
    altered = tmp_path / "alteree.tar.gz"
    with tarfile.open(altered, "w:gz") as tar:
        tar.add(unpacked / "data", arcname="data")
        tar.add(unpacked / "bases", arcname="bases")
    with pytest.raises(backup.BackupError, match="altérée"):
        backup.verify(altered)
    first = _other_prefix(monkeypatch)
    with pytest.raises(backup.BackupError, match="altérée"):
        backup.restore(altered, tmp_path / "ailleurs")
    assert not (tmp_path / "ailleurs").exists()
    assert not backup_server.named_like(backend.url(), _prefix())  # aucune base faite sous le nouveau préfixe
    backend.drop_session_prefix(first)


def test_bases_in_service_are_replaced_only_on_demand_and_copied_aside(tmp_path, monkeypatch):
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    _app_base(data).close()
    made = backup.backup(data, dest)
    late = ForgeBases(data / "forge", server=backend.url(), prefix=_prefix())
    late.execute("tardive", "CREATE TABLE t (x INTEGER)")  # une app née après l'archive
    late.close()
    with pytest.raises(backup.BackupError, match="--force"):
        backup.restore(made.archive, data)
    back = backup.restore(made.archive, data, force=True)
    aside = next(w for w in back.warnings if "copiées" in w).split(" : ", 1)[1]
    assert {p.name for p in Path(aside).iterdir()} >= {"mind.sql", "mail.sql", "forge"}
    assert (Path(aside) / "forge" / "tardive.sql").exists()  # copiée, puis supprimée du serveur
    assert not backup_server.exists(Target(url=backend.url(), name=f"{_prefix()}forge_tardive"))
    assert backup_server.exists(Target(url=backend.url(), name=f"{_prefix()}forge_cafe"))


def test_a_file_archive_is_not_restored_on_a_server(tmp_path, monkeypatch):
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    unpacked = tmp_path / "déballée"
    with tarfile.open(made.archive) as tar:
        tar.extractall(unpacked, filter="data")
    manifest = json.loads((unpacked / "data" / "MANIFEST.json").read_text())
    for key in ("engine", "bases"):
        manifest.pop(key)
    (unpacked / "data" / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    files_only = tmp_path / "fichiers.tar.gz"
    with tarfile.open(files_only, "w:gz") as tar:
        tar.add(unpacked / "data", arcname="data")
    _other_prefix(monkeypatch)
    with pytest.raises(backup.BackupError, match="fichiers SQLite"):
        backup.restore(files_only, tmp_path / "ailleurs")
