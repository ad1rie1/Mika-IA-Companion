"""L'extension de Teams en zip (ADR 0246) : ses fichiers sous ``mika-teams/``, sans ses tests ni sa doc, jamais un
fichier caché ni un lien ; rien au-delà de ses bornes ; sa version lue dans son manifeste."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from mika.app.me import teams_extension
from mika.app.me.teams_extension import packed, version_of


def extension(root: Path, version: object = "1.2.3") -> Path:
    folder = root / "Extension"
    (folder / "lib").mkdir(parents=True)
    (folder / "tests").mkdir()
    (folder / ".git").mkdir()
    (folder / "manifest.json").write_text(json.dumps({"manifest_version": 3, "version": version}), encoding="utf-8")
    (folder / "background.js").write_text("// le service", encoding="utf-8")
    (folder / "lib" / "signals.js").write_text("// une bibliothèque", encoding="utf-8")
    (folder / "lib" / "README.md").write_text("un README plus bas reste : seul celui de la racine est sa doc")
    (folder / "tests" / "signals.test.js").write_text("// un test", encoding="utf-8")
    (folder / "package.json").write_text("{}", encoding="utf-8")
    (folder / "README.md").write_text("la doc", encoding="utf-8")
    (folder / ".env").write_text("SECRET=1", encoding="utf-8")
    (folder / ".git" / "config").write_text("[core]", encoding="utf-8")
    return folder


def names(data: bytes | None) -> list[str]:
    assert data is not None
    return sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())


def test_its_files_go_under_one_folder_without_tests_doc_or_hidden_files(tmp_path):
    assert names(packed(extension(tmp_path))) == [
        "mika-teams/background.js", "mika-teams/lib/README.md", "mika-teams/lib/signals.js", "mika-teams/manifest.json"]


def test_a_link_never_takes_what_lies_outside(tmp_path):
    folder = extension(tmp_path)
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    (outside / "secret.txt").write_text("hors du dossier", encoding="utf-8")
    (folder / "lien.txt").symlink_to(outside / "secret.txt")
    (folder / "dossier").symlink_to(outside, target_is_directory=True)
    assert not any("secret" in n or "lien" in n or "dossier" in n for n in names(packed(folder)))


def test_beyond_its_bounds_nothing_leaves(tmp_path, monkeypatch):
    folder = extension(tmp_path)
    monkeypatch.setattr(teams_extension, "MAX_FILES", 3)
    assert packed(folder) is None
    monkeypatch.setattr(teams_extension, "MAX_FILES", 400)
    monkeypatch.setattr(teams_extension, "MAX_BYTES", 10)
    assert packed(folder) is None


def test_a_file_dated_before_1980_still_leaves(tmp_path):
    folder = extension(tmp_path)
    os.utime(folder / "background.js", (0, 0))  # une copie qui a perdu ses dates : 1970
    assert "mika-teams/background.js" in names(packed(folder))


def test_its_version_comes_from_its_manifest(tmp_path):
    assert version_of(extension(tmp_path)) == "1.2.3"
    assert version_of(None) is None
    assert version_of(tmp_path / "absente") is None


@pytest.mark.parametrize("version", ["", "1.2.3.4.5", "1.2-beta", "1.2/../x", 3, None])
def test_an_unreadable_version_is_no_extension(tmp_path, version):
    assert version_of(extension(tmp_path, version)) is None


def test_an_unreadable_manifest_is_no_extension(tmp_path):
    folder = extension(tmp_path)
    (folder / "manifest.json").write_text("pas du JSON", encoding="utf-8")
    assert version_of(folder) is None
