"""La vue de l'atelier d'un projet lu (ADR 0260), contre l'atelier réel : git, et bubblewrap quand il est là.

- la vue montre le dernier commit de la branche de base du projet lu : ni son travail en cours, ni la branche où son
  atelier se trouve ;
- elle ne bouge pas pendant une exécution, et se repose à la suivante si la tête a bougé ; la vue d'avant est effacée ;
- rien ne s'écrit dans le dépôt du projet lu, ni dans son dossier ;
- un programme du lecteur la lit sous ``liens/<n>/`` et ne peut pas y écrire ; une commande réseau ne la voit pas ;
- un chemin qui en sort (``..``, un chemin absolu, un lien symbolique) est refusé ;
- sans commit, ou au-delà de sa place, pas de vue ; des appels en même temps n'en posent qu'une, et une pose coupée
  ne laisse rien d'à moitié fait ;
- la vue n'est pas dans l'atelier du lecteur : ni son arbre, ni ses fichiers, ni son git ne la comptent, et là où elle
  se monte rien ne s'écrit ;
- le ménage ne laisse rien : ni la vue, ni le dossier vide où elle se montait.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from pathlib import Path

import pytest

from mika.adapters import cage
from mika.adapters.workshop import BASE_BRANCH, VIEWS_DIRNAME, BwrapWorkshop, Limits
from mika.ports.workshop import NO_COMMIT, TOO_BIG, UNREADABLE, OutsideWorkshop, view_place, viewed

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
needs_pasta = pytest.mark.skipif(not all(shutil.which(x) for x in ("bwrap", "pasta", "ip")),
                                 reason="bubblewrap, pasta ou ip absent")
#: le projet lu, et celui qui le lit
READ, READER = 1, 2


def go(coro):
    return asyncio.run(coro)


def _committed(ws: BwrapWorkshop, project: int = READ, **files: str) -> str:
    """Écrit ces fichiers dans l'atelier du projet et les enregistre ; rend le commit (complet)."""
    for name, text in files.items():
        go(ws.write(project, name.replace("__", "/"), text))
    assert go(ws.commit(project, "un pas"))
    return go(ws.head(project))


def _snapshot(folder: Path) -> dict[str, tuple[int, int, str]]:
    """Tout ce que porte un dossier, dépôt compris : chaque fichier avec sa taille, sa date et son empreinte."""
    out = {}
    for path in sorted(folder.rglob("*")):
        st = path.lstat()
        if path.is_symlink():
            out[str(path.relative_to(folder))] = (0, st.st_mtime_ns, os.readlink(path))
        elif path.is_file():
            out[str(path.relative_to(folder))] = (st.st_size, st.st_mtime_ns,
                                                  hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            out[str(path.relative_to(folder)) + "/"] = (0, st.st_mtime_ns, "")
    return out


def _posed(ws: BwrapWorkshop, reader: int = READER, target: int = READ) -> list[str]:
    """Ce qui est posé là où se garde la vue : les noms de ses dossiers."""
    home = ws.root / VIEWS_DIRNAME / f"projet-{reader}" / f"projet-{target}"
    return sorted(p.name for p in home.iterdir()) if home.is_dir() else []


# ── Le chemin d'une vue ───────────────────────────────────────────────────


def test_the_place_of_a_view_is_said_and_read_the_same_way():
    assert view_place(3) == "liens/3" and view_place(3, "src/a.py") == "liens/3/src/a.py" == view_place(3, "/src/a.py/")
    assert viewed("liens/3") == (3, ".") == viewed("./liens/3/") and viewed("liens/3/src/a.py") == (3, "src/a.py")
    assert viewed("x/../liens/3/a") == (3, "a")  # réduit avant d'être jugé : un détour ne cache pas la vue
    for own in ("", ".", "liens", "liens/notes.md", "src/liens/3", "/liens/3", "liens/03/a", "liens/3/..", "liens/-3"):
        assert viewed(own) is None, own


# ── Ce que la vue montre ──────────────────────────────────────────────────


@needs_bwrap
def test_a_view_shows_the_last_commit_never_the_work_in_progress(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    sha = _committed(ws, **{"README.md": "version une\n", "src__outil.py": "x = 1\n"})
    go(ws.write(READ, "README.md", "à moitié écrit\n"))  # du travail en cours, pas enregistré
    go(ws.write(READ, "brouillon.md", "pas encore\n"))
    view = go(ws.view(READER, READ, fresh=True))
    assert view.sha == sha and view.project == READ and not view.why
    assert view.at == go(ws.commits(READ, 1))[0].at > 0  # la date du commit, telle que git l'a daté
    assert go(ws.view_read(READER, READ, "README.md")) == "version une\n"
    assert go(ws.view_read(READER, READ, "src/outil.py")) == "x = 1\n"
    tree = go(ws.view_tree(READER, READ))
    assert tree == ["liens/1/.gitignore (55 o)", "liens/1/README.md (12 o)", "liens/1/src/outil.py (6 o)"]
    assert go(ws.view_tree(READER, READ, "src")) == ["liens/1/src/outil.py (6 o)"]
    assert go(ws.view_tree(READER, READ, "README.md")) == ["liens/1/README.md (12 o)"]
    with pytest.raises(FileNotFoundError, match="liens/1/brouillon.md"):
        go(ws.view_read(READER, READ, "brouillon.md"))
    assert _posed(ws) == [sha]  # un dossier au nom du commit, sans dépôt dedans
    assert not (ws.root / VIEWS_DIRNAME / "projet-2" / "projet-1" / sha / ".git").exists()


@needs_bwrap
def test_a_view_stays_put_during_a_run_and_is_posed_again_when_the_head_moved(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    first = _committed(ws, **{"a.txt": "un\n"})
    assert go(ws.view(READER, READ, fresh=True)).sha == first
    second = _committed(ws, **{"a.txt": "deux\n", "b.txt": "nouveau\n"})
    # pendant l'exécution du lecteur, ses outils lisent la vue telle qu'elle a été posée
    assert go(ws.view(READER, READ)).sha == first and go(ws.view_read(READER, READ, "a.txt")) == "un\n"
    again = go(ws.view(READER, READ, fresh=True))  # au départ de l'exécution suivante
    assert again.sha == second != first and go(ws.view_read(READER, READ, "a.txt")) == "deux\n"
    assert go(ws.view_read(READER, READ, "b.txt")) == "nouveau\n"
    assert _posed(ws) == [second]  # la vue d'avant est effacée : une seule à la fois
    assert go(ws.view(READER, READ, fresh=True)).sha == second and _posed(ws) == [second]  # rien n'a bougé : rien


@needs_bwrap
def test_calls_at_once_pose_one_view_and_a_pose_cut_short_leaves_no_half_view(tmp_path):
    """Ses outils peuvent être appelés en parallèle, et l'échéance d'un enrichisseur peut couper une pose."""
    ws = BwrapWorkshop(tmp_path / "ateliers")
    sha = _committed(ws, **{"a.txt": "un\n", "src__b.py": "y = 2\n"})

    async def cut_short() -> None:
        try:
            await asyncio.wait_for(ws.view(READER, READ, fresh=True), 0.02)
        except TimeoutError:
            pass

    go(cut_short())

    async def at_once():
        return await asyncio.gather(ws.view(READER, READ, fresh=True), ws.view(READER, READ),
                                    ws.view(READER, READ, fresh=True), ws.drop_views(READER, keep=[READ]))

    views = go(at_once())[:3]
    assert {v.sha for v in views} == {sha} and _posed(ws) == [sha]  # une vue entière, et rien d'une pose inachevée
    assert go(ws.view_read(READER, READ, "src/b.py")) == "y = 2\n"


@needs_bwrap
def test_the_view_reads_the_base_branch_not_where_the_workshop_stands(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    base = _committed(ws, **{"a.txt": "accepté\n"})
    assert go(ws.branch(READ)) == BASE_BRANCH == "main"
    assert go(ws._git(READ, "checkout", "-q", "-b", "objectif-7")).ok  # une branche de travail (le lot L8)
    work = _committed(ws, **{"a.txt": "en discussion\n", "essai.txt": "pas accepté\n"})
    assert go(ws.branch(READ)) == "objectif-7" and go(ws.head(READ)) == work != base
    view = go(ws.view(READER, READ, fresh=True))
    assert view.sha == base and go(ws.view_read(READER, READ, "a.txt")) == "accepté\n"
    assert all("essai.txt" not in line for line in go(ws.view_tree(READER, READ)))
    assert go(ws._git(READ, "checkout", "-q", "--detach", base)).ok  # une tête détachée : la base se lit encore
    assert go(ws.view(READER, READ, fresh=True)).sha == base


@needs_bwrap
def test_nothing_is_written_in_the_project_read(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    _committed(ws, **{"a.txt": "un\n", "src__b.py": "y = 2\n"})
    go(ws.write(READ, "en-cours.txt", "pas enregistré\n"))
    status = go(ws._git(READ, "status", "--porcelain")).stdout
    before = _snapshot(ws.folder(READ))  # chaque fichier, son dépôt compris : sa taille, sa date, son empreinte
    go(ws.view(READER, READ, fresh=True))
    go(ws.view_tree(READER, READ))
    go(ws.view_read(READER, READ, "a.txt"))
    assert go(ws.run(READER, ["cat", "liens/1/a.txt"], views=[READ])).ok
    assert go(ws.run(READER, ["sh", "-c", "echo x > liens/1/a.txt; rm -rf liens/1; true"], views=[READ])).ok
    go(ws.view(READER, READ, fresh=True))  # relue : toujours rien
    go(ws.drop_views(READER))
    assert _snapshot(ws.folder(READ)) == before  # pas un octet, pas une date
    assert not (ws.folder(READ) / ".git" / "worktrees").exists()
    assert go(ws._git(READ, "status", "--porcelain")).stdout == status


@needs_bwrap
def test_the_git_that_poses_a_view_reads_the_repository_read_only(tmp_path):
    """Ce qui tient la promesse, c'est la cage : le dépôt du projet lu y est monté en lecture seule."""
    ws = BwrapWorkshop(tmp_path / "ateliers")
    _committed(ws, **{"a.txt": "un\n"})
    repo, where = ws.folder(READ) / ".git", tmp_path / "pose"
    where.mkdir()
    refused = go(ws._view_git(repo, where, "update-ref", "refs/heads/voleur", "HEAD"))
    assert not refused.ok and not (repo / "refs" / "heads" / "voleur").exists()
    assert go(ws._view_git(repo, where, "rev-parse", f"refs/heads/{BASE_BRANCH}")).ok  # lire, oui


# ── Ce que voient les programmes du lecteur ───────────────────────────────


@needs_bwrap
def test_a_program_reads_the_view_where_the_tools_say_and_cannot_write_it(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    sha = _committed(ws, **{"a.txt": "ce que dit le produit\n", "src__outil.py": "x = 1\n"})
    go(ws.write(READER, "notes.md", "mes notes\n"))
    read = go(ws.run(READER, ["cat", "liens/1/a.txt"], views=[READ]))
    assert read.ok and read.stdout == "ce que dit le produit\n"
    found = go(ws.run(READER, ["grep", "-rl", "x = 1", "liens/1"], views=[READ]))
    assert found.ok and found.stdout.strip() == "liens/1/src/outil.py"  # le même chemin que ses outils et son prompt
    for attempt in ("echo x > liens/1/a.txt", "echo x > liens/1/nouveau.txt", "rm liens/1/a.txt",
                    "mkdir liens/1/dossier", "mv liens/1/a.txt liens/1/b.txt", "chmod 777 liens/1/a.txt"):
        tried = go(ws.run(READER, ["sh", "-c", attempt], views=[READ]))
        assert not tried.ok, attempt
    posed = ws.root / VIEWS_DIRNAME / "projet-2" / "projet-1" / sha
    assert (posed / "a.txt").read_text() == "ce que dit le produit\n"
    assert sorted(p.name for p in posed.iterdir()) == [".gitignore", "a.txt", "src"]
    copied = go(ws.run(READER, ["cp", "liens/1/a.txt", "copie.txt"], views=[READ]))  # chez lui, il écrit
    assert copied.ok and (ws.folder(READER) / "copie.txt").read_text() == "ce que dit le produit\n"
    # sans la vue (un droit retiré) : le même programme ne lit rien
    assert not go(ws.run(READER, ["cat", "liens/1/a.txt"])).ok
    # les cages ne se montent que ce qu'on leur donne : le dépôt du projet lu n'y est pas
    assert not go(ws.run(READER, ["ls", str(ws.folder(READ))], views=[READ])).ok


def test_the_view_is_mounted_read_only_after_the_workshop(tmp_path):
    """La ligne de commande de la cage : la vue se monte en lecture seule, par-dessus l'atelier lié en écriture."""
    ws = BwrapWorkshop(tmp_path / "ateliers", bwrap="/usr/bin/bwrap")
    root = ws._open(READER)
    source, at = tmp_path / "vue", root / "liens" / "1"
    args = ws._sandbox(root, ["true"], "", protect_git=True, read_only=[(source, at)])
    mount = cage.read_only(source, at)
    assert mount == ["--ro-bind", str(source), str(at)]
    where = next(i for i in range(len(args)) if args[i:i + 3] == mount)
    assert where > args.index("--bind") and where < args.index("--chdir")
    assert ws._sandbox(root, ["true"], "") == [a for i, a in enumerate(args) if not where <= i < where + 3]


@needs_pasta
def test_a_network_command_does_not_see_the_view(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    _committed(ws, **{"a.txt": "pas pour Internet\n"})
    go(ws.write(READER, "notes.md", "mes notes\n"))
    go(ws.view(READER, READ, fresh=True))
    assert go(ws.run(READER, ["cat", "liens/1/a.txt"], views=[READ])).ok
    # la commande réseau tourne (elle lit l'atelier du lecteur), et la vue n'y est pas
    seen = go(ws.run(READER, ["sh", "-c", "cat notes.md && ! test -e liens/1/a.txt"], network=True, views=[READ]))
    assert seen.ok and seen.stdout == "mes notes\n", seen
    out = go(ws.run(READER, ["cat", "liens/1/a.txt"], network=True, views=[READ]))
    assert not out.ok and "pas pour Internet" not in out.stdout


@needs_bwrap
def test_a_mount_point_taken_by_a_file_gets_nothing_and_the_program_is_told(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    _committed(ws, **{"a.txt": "un\n"})
    go(ws.write(READER, "liens", "un fichier à lui, qui porte ce nom\n"))
    out = go(ws.run(READER, ["cat", "liens"], views=[READ]))
    assert out.ok and out.stdout == "un fichier à lui, qui porte ce nom\n"
    assert any("liens/1/ n'est pas montée" in note for note in out.notes)
    assert go(ws.view_read(READER, READ, "a.txt")) == "un\n"  # ses outils la lisent quand même


# ── Les chemins d'une vue ─────────────────────────────────────────────────


@needs_bwrap
def test_a_path_that_leaves_the_view_is_refused(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    secret = tmp_path / "dehors.txt"
    secret.write_text("CANARI")
    go(ws.write(READ, "a.txt", "un\n"))
    folder = ws.folder(READ)
    (folder / "fuite").symlink_to(secret)  # un lien enregistré dans le dépôt lu, qui sort de la vue
    (folder / "dossier").symlink_to(tmp_path)
    (folder / "voisin").symlink_to("../../../projet-1/a.txt")
    (folder / "dedans").symlink_to("a.txt")
    assert go(ws.commit(READ, "des liens"))
    go(ws.view(READER, READ, fresh=True))
    for bad in ("fuite", "dossier/dehors.txt", "voisin", "../projet-1/a.txt", "../../../projet-1/a.txt", "/etc/passwd"):
        with pytest.raises(OutsideWorkshop):
            go(ws.view_read(READER, READ, bad))
        with pytest.raises(OutsideWorkshop):
            go(ws.view_tree(READER, READ, bad))
    assert go(ws.view_read(READER, READ, "dedans")) == "un\n"  # un lien qui reste dans la vue se suit
    assert "liens/1/fuite (lien)" in go(ws.view_tree(READER, READ))  # une entrée, jamais suivie
    leaked = go(ws.run(READER, ["cat", "liens/1/fuite"], views=[READ]))  # dans la cage, il ne mène nulle part
    assert not leaked.ok and "CANARI" not in leaked.stdout


def test_reading_a_view_that_is_not_posed_fails(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers", bwrap="")
    with pytest.raises(FileNotFoundError, match="aucune vue"):
        go(ws.view_read(READER, READ, "a.txt"))
    with pytest.raises(FileNotFoundError, match="aucune vue"):
        go(ws.view_tree(READER, READ))


# ── Pas de vue ────────────────────────────────────────────────────────────


@needs_bwrap
def test_a_project_without_a_commit_has_no_view(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    never = go(ws.view(READER, READ, fresh=True))  # il n'a jamais ouvert son atelier
    assert not never.sha and never.why == NO_COMMIT and _posed(ws) == []
    _committed(ws, **{"a.txt": "un\n"})
    assert go(ws.view(READER, READ)).why == NO_COMMIT  # ce que l'exécution en cours a vu au départ
    assert go(ws.view(READER, READ, fresh=True)).sha  # la suivante
    assert go(ws._git(READ, "branch", "-m", "ailleurs")).ok  # plus de branche de base : plus de vue
    gone = go(ws.view(READER, READ, fresh=True))
    assert not gone.sha and gone.why == NO_COMMIT and _posed(ws) == []
    assert go(ws.view(READ, READ, fresh=True)).why == NO_COMMIT  # jamais de lui-même


def test_without_bubblewrap_no_view_is_posed(tmp_path):
    """Git ne lit le dépôt d'un autre projet que dans la cage : jamais de repli aux droits du serveur."""
    ws = BwrapWorkshop(tmp_path / "ateliers", bwrap="")
    (ws.folder(READ) / ".git").mkdir(parents=True)
    view = go(ws.view(READER, READ, fresh=True))
    assert not view.sha and view.why == UNREADABLE and not (ws.root / VIEWS_DIRNAME).exists()


@needs_bwrap
def test_a_commit_bigger_than_a_view_has_no_view(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers", limits=Limits(view_bytes=4000))
    small = _committed(ws, **{"a.txt": "x" * 1000})
    assert go(ws.view(READER, READ, fresh=True)).sha == small
    _committed(ws, **{"gros.txt": "y" * 5000})
    big = go(ws.view(READER, READ, fresh=True))
    assert not big.sha and big.why == TOO_BIG
    assert _posed(ws) == []  # ni le commit trop gros, ni la vue d'avant, qui ne dit plus où en est le projet
    with pytest.raises(FileNotFoundError):
        go(ws.view_read(READER, READ, "a.txt"))
    # la place d'une vue n'est pas celle de l'atelier du lecteur : il écrit toujours chez lui
    assert go(ws.write(READER, "notes.md", "z" * 3000)) == "notes.md"


# ── La vue n'est pas dans l'atelier du lecteur ────────────────────────────


@needs_bwrap
def test_the_view_is_no_file_of_the_reader_and_nothing_is_written_where_it_mounts(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    _committed(ws, **{"a.txt": "du projet lu\n"})
    go(ws.write(READER, "notes.md", "mes notes\n"))
    assert go(ws.commit(READER, "mes notes"))
    go(ws.view(READER, READ, fresh=True))
    assert go(ws.run(READER, ["cat", "liens/1/a.txt"], views=[READ])).ok  # la vue a été montée chez lui
    # son arbre, ses fichiers, son git : rien de la vue
    assert go(ws.tree(READER)) == [".gitignore (55 o)", "notes.md (10 o)"]
    assert go(ws.tree(READER, "liens")) == [] and go(ws.pending(READER)) == []
    assert go(ws.commit(READER, "rien de neuf")) == ""
    for path in ("liens/1/a.txt", "liens/1"):
        with pytest.raises(FileNotFoundError):  # ce par quoi part un fichier partagé, ou téléchargé de la console
            go(ws.read_bytes(READER, path, 100))
        with pytest.raises(FileNotFoundError):
            go(ws.read(READER, path))
    # là où la vue se monte, rien ne s'écrit : le fichier resterait caché dessous
    for path in ("liens/1/a.txt", "liens/1/nouveau.txt", "x/../liens/1/y.txt", "liens/1"):
        with pytest.raises(OutsideWorkshop):
            go(ws.write(READER, path, "x"))
        with pytest.raises(OutsideWorkshop):
            go(ws.write_bytes(READER, path, b"x"))
    with pytest.raises((OutsideWorkshop, FileNotFoundError)):
        go(ws.edit(READER, "liens/1/a.txt", "du", "le"))
    assert go(ws.write(READER, "liens/notes.md", "à lui\n")) == "liens/notes.md"  # le reste de « liens/ » est à lui
    assert not any((ws.folder(READER) / "liens" / "1").iterdir())


@needs_bwrap
def test_dropping_views_leaves_nothing_behind(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    _committed(ws, READ, **{"a.txt": "un\n"})
    _committed(ws, 3, **{"c.txt": "trois\n"})
    go(ws.view(READER, READ, fresh=True))
    go(ws.view(READER, 3, fresh=True))
    assert go(ws.run(READER, ["cat", "liens/1/a.txt", "liens/3/c.txt"], views=[READ, 3])).stdout == "un\ntrois\n"
    mounts = ws.folder(READER) / "liens"
    assert sorted(p.name for p in mounts.iterdir()) == ["1", "3"]
    go(ws.drop_views(READER, keep=[3]))  # le lien vers le projet 1 est retiré, ou suspendu
    assert _posed(ws, READER, READ) == [] and len(_posed(ws, READER, 3)) == 1
    assert sorted(p.name for p in mounts.iterdir()) == ["3"]
    with pytest.raises(FileNotFoundError):
        go(ws.view_read(READER, READ, "a.txt"))
    assert go(ws.view_read(READER, 3, "c.txt")) == "trois\n"
    go(ws.drop_views(READER))  # le projet lecteur est archivé
    assert not (ws.root / VIEWS_DIRNAME / "projet-2").exists() and not mounts.exists()
    go(ws.drop_views(READER))  # idempotent : un effet rejoué ne casse rien
    # le projet lu disparaît : sa vue ne lui survit pas
    go(ws.view(READER, READ, fresh=True))
    shutil.rmtree(ws.folder(READ))
    assert go(ws.view(READER, READ, fresh=True)).why == NO_COMMIT and _posed(ws) == []


@needs_bwrap
def test_what_the_reader_keeps_in_its_own_liens_folder_survives_the_cleaning(tmp_path):
    ws = BwrapWorkshop(tmp_path / "ateliers")
    _committed(ws, **{"a.txt": "un\n"})
    go(ws.write(READER, "liens/utiles.md", "des liens à lui\n"))
    assert go(ws.run(READER, ["cat", "liens/1/a.txt", "liens/utiles.md"], views=[READ])).ok
    go(ws.drop_views(READER))
    assert (ws.folder(READER) / "liens" / "utiles.md").read_text() == "des liens à lui\n"
    assert not (ws.folder(READER) / "liens" / "1").exists()
