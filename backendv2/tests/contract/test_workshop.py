"""L'atelier réel (bubblewrap) contre son contrat.

- un chemin est résolu puis vérifié : ``..``, un chemin absolu et le lien
  symbolique qui sort du dossier sont refusés ; ``.git`` ne s'écrit pas ;
- une édition ambiguë échoue au lieu de deviner ;
- un programme ne voit ni l'environnement du serveur (ses clés), ni le
  réseau, ni le reste du disque ; un délai tue tout son groupe ; la sortie
  est bornée ;
- sans bubblewrap, rien ne s'exécute (pas de repli aux droits du serveur) ;
- git : une amorce, puis un commit seulement quand quelque chose a changé.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mika.adapters.workshop import BwrapWorkshop
from mika.ports.workshop import OutsideWorkshop

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")


def go(coro):
    return asyncio.run(coro)


def test_paths_are_resolved_then_checked(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers", bwrap="")
    outside = tmp_path / "dehors"
    outside.mkdir()
    (outside / "secret.txt").write_text("CANARI")
    folder = ws.folder(1)
    folder.mkdir(parents=True)
    (folder / "fuite").symlink_to(outside)
    for bad in ("../dehors/secret.txt", "/etc/passwd", "fuite/secret.txt", "fuite/nouveau.txt"):
        with pytest.raises(OutsideWorkshop):
            go(ws.write(1, bad, "x"))
    with pytest.raises(OutsideWorkshop):
        go(ws.read(1, "fuite/secret.txt"))
    for organ in (".git/config", ".atelier-home/.bashrc"):
        with pytest.raises(OutsideWorkshop):
            go(ws.write(1, organ, "x"))
    assert (outside / "secret.txt").read_text() == "CANARI" and not (outside / "nouveau.txt").exists()


def test_an_ambiguous_edit_fails_instead_of_guessing(tmp_path):
    ws = BwrapWorkshop(tmp_path, bwrap="")
    go(ws.write(1, "a.py", "x = 1\nx = 1\n"))
    with pytest.raises(ValueError, match="2 fois"):
        go(ws.edit(1, "a.py", "x = 1", "x = 2"))
    with pytest.raises(ValueError, match="introuvable"):
        go(ws.edit(1, "a.py", "y = 1", "y = 2"))
    go(ws.edit(1, "a.py", "x = 1\nx = 1", "x = 3"))
    assert go(ws.read(1, "a.py")) == "x = 3\n"


def test_without_bubblewrap_nothing_runs(tmp_path):
    ws = BwrapWorkshop(tmp_path, bwrap="")
    r = go(ws.run(1, ["python3", "-c", "print('hors de la cage')"]))
    assert not r.ok and "bubblewrap" in r.refused and r.returncode is None


def test_a_program_outside_the_allowlist_is_refused_by_name(tmp_path):
    ws = BwrapWorkshop(tmp_path)
    r = go(ws.run(1, ["curl", "https://exemple.org"]))
    assert r.refused and "curl" in r.refused and "python3" in r.refused


@needs_bwrap
def test_a_program_sees_neither_the_server_secrets_nor_the_network_nor_the_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("MIKA_SECRET_KEY", "CANARI-cle")
    ws = BwrapWorkshop(tmp_path / "ateliers")
    env = go(ws.run(1, ["python3", "-c", "import os; print(sorted(os.environ.items()))"]))
    assert env.ok and "CANARI" not in env.stdout and "MIKA_ATELIER" in env.stdout
    net = go(ws.run(1, ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), 2)"]))
    assert not net.ok
    home = os.path.expanduser("~")
    disk = go(ws.run(1, ["python3", "-c", f"open({home + '/mika-evasion.txt'!r}, 'w').write('x')"]))
    assert not disk.ok and not os.path.exists(home + "/mika-evasion.txt")
    mine = go(ws.run(1, ["python3", "-c", "open('dedans.txt', 'w').write('ok')"]))
    assert mine.ok and (ws.folder(1) / "dedans.txt").read_text() == "ok"


@needs_bwrap
def test_a_timeout_kills_the_whole_group_and_output_is_bounded(tmp_path):
    ws = BwrapWorkshop(tmp_path, max_output_chars=1000)
    slow = go(ws.run(1, ["sh", "-c", "sleep 30 & sleep 30"], timeout_s=1))
    assert slow.timed_out and not slow.ok and slow.duration_ms < 10_000
    loud = go(ws.run(1, ["python3", "-c", "print('x' * 100000)"]))
    assert loud.ok and loud.truncated and len(loud.stdout) < 2000


@needs_bwrap
def test_git_seals_its_start_then_commits_only_what_changed(tmp_path):
    ws = BwrapWorkshop(tmp_path)
    go(ws.write(1, "notes.md", "premier jet\n"))
    first = go(ws.commit(1, "premier pas"))
    assert first
    assert go(ws.commit(1, "rien de neuf")) == ""  # jamais de commit vide
    go(ws.edit(1, "notes.md", "premier jet", "deuxième jet"))
    assert "deuxième jet" in go(ws.diff(1))
    assert go(ws.commit(1, "deuxième pas"))
    assert go(ws.log(1)).splitlines()[0].endswith("deuxième pas")
    assert [ln.split(" ", 1)[1] for ln in go(ws.log(1)).splitlines()] == ["deuxième pas", "premier pas",
                                                                            "atelier ouvert"]
    assert go(ws.log(1, 1, offset=1)).splitlines()[0].endswith("premier pas")
    assert not go(ws.log(1, 1, offset=3)).strip()
