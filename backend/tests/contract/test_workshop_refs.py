"""Le dépôt d'un atelier lu à une référence (ADR 0288), sur le vrai adaptateur — ce que l'écran d'une personne lit :

- ses branches, la base d'abord, avec leur avance et leur retard ;
- un dossier et un fichier d'une branche ou d'un commit, lus dans les objets de git : jamais l'arbre de travail ;
- **rien ne sort du dépôt** : ni ``..``, ni un chemin absolu, ni ``.git`` ; un lien symbolique se dit, il ne se
  suit pas ; un fichier binaire ou trop gros se dit, sans son contenu ;
- l'histoire d'une branche, de toutes, d'un chemin : chaque commit avec sa branche, s'il est d'elle, ses parents ;
- un commit et son message entier ; un diff par fichier, ses lignes numérotées avant et après, borné.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mika.adapters.workshop import BwrapWorkshop
from mika.ports.workshop import (
    BASE_BRANCH,
    ENTRY_DIR,
    ENTRY_FILE,
    ENTRY_LINK,
    FILE_ADDED,
    FILE_DELETED,
    FILE_MODIFIED,
    OutsideWorkshop,
)

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
ONE = "work/objective-1"


def go(coro):
    return asyncio.run(coro)


def _repo(tmp_path) -> tuple[BwrapWorkshop, str, str]:
    """Un atelier : une base de deux fichiers, puis une branche de travail qui en change un, en ajoute un et en
    retire un. Rend l'atelier, le commit de la base et celui de la branche."""
    ws = BwrapWorkshop(tmp_path)
    go(ws.write(1, "README.md", "# Outils\n\nUn outil.\n"))
    go(ws.write(1, "outils/scan.py", "PORT = 22\n\n\ndef scan():\n    return []\n"))
    go(ws.write(1, "outils/vieux.py", "x = 1\n"))
    base = go(ws.commit(1, "la base"))
    go(ws.work_on(1, ONE))
    go(ws.write(1, "outils/scan.py", "PORT = 22\nDELAI = 2\n\n\ndef scan():\n    return [PORT]\n"))
    go(ws.write(1, "outils/rdp.py", "def connect():\n    ...\n"))
    (ws.folder(1) / "outils" / "vieux.py").unlink()
    head = go(ws.commit(1, "rdp : le module"))
    return ws, base, head


@needs_bwrap
def test_branches_say_their_head_and_their_gap_with_the_base(tmp_path):
    ws, base, head = _repo(tmp_path)
    found = go(ws.branches(1))
    assert [(b.name, b.base, b.current, b.ahead, b.behind) for b in found] == [
        (BASE_BRANCH, True, False, 0, 0), (ONE, False, True, 1, 0)]
    assert (found[0].head.sha, found[1].head.sha, found[1].head.title) == (base, head, "rdp : le module")
    assert found[1].head.local and found[1].head.parents == (base,)  # signé par l'atelier : elle
    assert go(ws.branches(2)) == []


@needs_bwrap
def test_a_folder_and_a_file_are_read_at_a_branch_not_in_the_working_tree(tmp_path):
    ws, base, head = _repo(tmp_path)
    go(ws.write(1, "brouillon.md", "pas enregistré\n"))  # dans l'arbre de travail seulement
    root = go(ws.ref_tree(1, BASE_BRANCH))
    assert [(e.path, e.kind) for e in root] == [("outils", ENTRY_DIR), (".gitignore", ENTRY_FILE),
                                                 ("README.md", ENTRY_FILE)]
    assert next(e for e in root if e.path == "README.md").size == len("# Outils\n\nUn outil.\n")
    assert [e.path for e in go(ws.ref_tree(1, BASE_BRANCH, "outils"))] == ["outils/scan.py", "outils/vieux.py"]
    assert [e.path for e in go(ws.ref_tree(1, ONE, "outils/"))] == ["outils/rdp.py", "outils/scan.py"]
    assert [e.path for e in go(ws.ref_tree(1, base[:10], "./outils"))] == ["outils/scan.py", "outils/vieux.py"]
    # un fichier : celui de la référence, pas celui du disque
    assert go(ws.ref_file(1, BASE_BRANCH, "outils/scan.py")).text == "PORT = 22\n\n\ndef scan():\n    return []\n"
    here = go(ws.ref_file(1, ONE, "outils/scan.py"))
    assert (here.sha, here.kind, here.binary, here.too_big) == (head, ENTRY_FILE, False, False)
    assert "DELAI = 2" in here.text and here.size == len(here.text)
    # une référence inconnue ; un chemin qui n'y est pas ; un dossier qui n'est pas un fichier
    assert go(ws.ref_tree(1, "work/inconnue")) is None and go(ws.ref_file(1, "f" * 40, "README.md")) is None
    assert go(ws.ref_tree(2, BASE_BRANCH)) is None
    for path in ("brouillon.md", "outils", "outils/absent.py", ""):
        with pytest.raises(FileNotFoundError):
            go(ws.ref_file(1, BASE_BRANCH, path))
    with pytest.raises(FileNotFoundError):
        go(ws.ref_tree(1, BASE_BRANCH, "README.md"))


@needs_bwrap
def test_nothing_leaves_the_repository(tmp_path):
    ws, base, _ = _repo(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("le mot de passe\n")
    os.symlink(secret, ws.folder(1) / "lien")  # un lien qui sort de l'atelier, enregistré dans le dépôt
    os.symlink("/etc/passwd", ws.folder(1) / "outils" / "comptes")
    head = go(ws.commit(1, "des liens"))
    for path in ("../secret.txt", "outils/../../secret.txt", "/etc/passwd", str(secret), ".git/config", "a\x00b"):
        for read in (ws.ref_file, ws.ref_tree):
            with pytest.raises(OutsideWorkshop):
                go(read(1, ONE, path))
        with pytest.raises(OutsideWorkshop):
            go(ws.history(1, ONE, path=path))
        with pytest.raises(OutsideWorkshop):
            go(ws.diff_of(1, base, head, path=path))
    # une référence ne nomme qu'une branche ou un commit : ni une expression de révision, ni une option
    for ref in ("main..work/objective-1", "HEAD~1", "--all", "-n1", "main:README.md", "refs/heads/main@{1}", ""):
        assert go(ws.ref_tree(1, ref)) is None and go(ws.ref_file(1, ref, "README.md")) is None
    # un lien symbolique se dit ; il ne se suit pas, et rien de sa cible n'est rendu
    kinds = {e.path: e.kind for e in go(ws.ref_tree(1, ONE))}
    assert kinds["lien"] == ENTRY_LINK
    for path in ("lien", "outils/comptes"):
        found = go(ws.ref_file(1, ONE, path))
        assert (found.kind, found.text, found.binary, found.too_big) == (ENTRY_LINK, "", False, False)
    with pytest.raises(FileNotFoundError):
        go(ws.ref_tree(1, ONE, "lien"))  # pas un dossier : on n'entre pas par lui


@needs_bwrap
def test_a_binary_or_too_big_file_is_said_without_its_content(tmp_path):
    ws, _, _ = _repo(tmp_path)
    go(ws.write_bytes(1, "logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256))))
    go(ws.write(1, "gros.txt", "ligne\n" * 2000))
    go(ws.commit(1, "des fichiers"))
    image = go(ws.ref_file(1, ONE, "logo.png"))
    assert (image.binary, image.too_big, image.text) == (True, False, "") and image.size > 256
    big = go(ws.ref_file(1, ONE, "gros.txt", limit=1000))
    assert (big.binary, big.too_big, big.text, big.size) == (False, True, "", 12_000)
    assert go(ws.ref_file(1, ONE, "gros.txt", limit=20_000)).text == "ligne\n" * 2000


@needs_bwrap
def test_the_history_says_the_branch_who_signed_and_the_parents(tmp_path):
    ws, base, head = _repo(tmp_path)
    everywhere = go(ws.history(1))
    assert everywhere.total == 3 and [k.title for k in everywhere.commits] == ["rdp : le module", "la base",
                                                                                "atelier ouvert"]
    assert [k.branch for k in everywhere.commits] == [ONE, BASE_BRANCH, BASE_BRANCH]
    assert all(k.local for k in everywhere.commits) and everywhere.commits[0].parents == (base,)
    top = everywhere.commits[0]
    assert (top.sha, top.files, top.insertions, top.deletions) == (head, 3, 4, 2)
    on_base = go(ws.history(1, BASE_BRANCH))
    assert on_base.total == 2 and [k.sha for k in on_base.commits][0] == base
    # page par page ; par chemin : ceux qui l'ont touché
    assert [k.title for k in go(ws.history(1, ONE, n=1, offset=1)).commits] == ["la base"]
    touched = go(ws.history(1, ONE, path="outils/rdp.py"))
    assert (touched.total, [k.sha for k in touched.commits]) == (1, [head])
    assert go(ws.history(1, ONE, path="outils/vieux.py")).total == 2
    assert go(ws.history(1, "work/inconnue")) is None and go(ws.history(2)) is None
    # un commit d'un autre (récupéré d'ailleurs) n'est pas d'elle
    made = go(ws._git(1, "-c", "user.name=Karim", "-c", "user.email=karim@exemple.test", "commit", "--allow-empty",
                      "-q", "-m", "un mot de Karim"))
    assert made.ok
    foreign = go(ws.history(1, ONE, n=1)).commits[0]
    assert (foreign.title, foreign.author, foreign.local) == ("un mot de Karim", "Karim", False)


@needs_bwrap
def test_a_commit_and_its_diff_file_by_file_with_numbered_lines(tmp_path):
    ws, base, head = _repo(tmp_path)
    found = go(ws.change(1, head[:12]))
    assert (found.commit.sha, found.commit.branch, found.commit.parents, found.body) == (head, ONE, (base,), "")
    assert go(ws.change(1, "f" * 40)) is None and go(ws.change(1, "main")) is None
    files = go(ws.diff_of(1, base, head))
    assert [(f.path, f.status, f.insertions, f.deletions, f.binary, f.cut) for f in files] == [
        ("outils/rdp.py", FILE_ADDED, 2, 0, False, False),
        ("outils/scan.py", FILE_MODIFIED, 2, 1, False, False),
        ("outils/vieux.py", FILE_DELETED, 0, 1, False, False)]
    scan = files[1].hunks[0]
    assert scan.header.startswith("@@ -1,5 +1,6 @@")
    assert [(x.kind, x.old, x.new, x.text) for x in scan.lines] == [
        (" ", 1, 1, "PORT = 22"), ("+", 0, 2, "DELAI = 2"), (" ", 2, 3, ""), (" ", 3, 4, ""),
        (" ", 4, 5, "def scan():"), ("-", 5, 0, "    return []"), ("+", 0, 6, "    return [PORT]")]
    assert [(x.kind, x.old, x.new) for x in files[2].hunks[0].lines] == [("-", 1, 0)]
    # un seul fichier ; depuis le début du dépôt
    assert [f.path for f in go(ws.diff_of(1, base, head, path="outils/scan.py"))] == ["outils/scan.py"]
    assert {f.path for f in go(ws.diff_of(1, "", base))} == {".gitignore", "README.md", "outils/scan.py",
                                                            "outils/vieux.py"}
    assert go(ws.diff_of(1, base, "f" * 40)) is None and go(ws.diff_of(2, base, head)) is None


@needs_bwrap
def test_a_diff_too_long_is_cut_and_says_so_and_a_binary_has_no_lines(tmp_path):
    ws, base, _ = _repo(tmp_path)
    go(ws.write(1, "a.txt", "".join(f"ligne {i}\n" for i in range(50))))
    go(ws.write(1, "b.txt", "".join(f"autre {i}\n" for i in range(50))))
    go(ws.write_bytes(1, "logo.png", b"\x00\x01\x02binaire"))
    head = go(ws.commit(1, "beaucoup"))
    whole = {f.path: f for f in go(ws.diff_of(1, base, head))}
    assert not whole["a.txt"].cut and len(whole["a.txt"].hunks[0].lines) == 50
    assert (whole["logo.png"].binary, whole["logo.png"].hunks, whole["logo.png"].cut) == (True, (), False)
    cut = {f.path: f for f in go(ws.diff_of(1, base, head, lines=60))}
    # ce qui tient est rendu ; le fichier où la borne tombe est coupé, les suivants gardent leurs seuls comptes
    assert not cut["a.txt"].cut and sum(len(h.lines) for h in cut["a.txt"].hunks) == 50
    assert cut["b.txt"].cut and sum(len(h.lines) for h in cut["b.txt"].hunks) == 10
    later = [f for f in go(ws.diff_of(1, base, head, lines=60)) if f.path > "b.txt" and not f.binary]
    assert later and all(f.cut and not f.hunks and (f.insertions or f.deletions) for f in later)
    counts = go(ws.diff_of(1, base, head, lines=0))
    assert all((f.cut or f.binary) and not f.hunks for f in counts) and counts[0].insertions == 50
