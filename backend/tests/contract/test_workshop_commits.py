"""Les commits d'un atelier, sur le vrai adaptateur (ADR 0277) :

- un commit n'a qu'une forme là où il se compare : son identifiant complet (``commit``, ``head``, ``commits``,
  ``span``) ; l'abrégé n'est qu'un affichage (``log``) ;
- la copie d'un commit, pour une relecture : posée à part, elle montre le commit épinglé et pas l'arbre de
  l'atelier ; une commande y écrit sans rien laisser dans l'atelier ; effacée, plus rien ne s'y lance ;
- ce que le dépôt distant possède (``sent``) : le dernier envoi réussi, la dernière récupération, par adresse ;
- une base qui n'a que son amorce prend l'histoire du dépôt distant, même quand la première exécution est partie
  avant toute récupération : son travail est rejoué sur la nouvelle base, qui ne reçoit rien de lui.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

from mika.adapters.workshop import REVIEWS_DIRNAME, BwrapWorkshop
from mika.ports.workshop import BASE_BRANCH, NO_COMMIT

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
URL = "https://github.com/moi/depot.git"
ONE = "work/objective-1"


def go(coro):
    return asyncio.run(coro)


def _shop(tmp_path) -> BwrapWorkshop:
    return BwrapWorkshop(tmp_path, credentials=lambda: {"token": "ghp_SECRET", "hosts": ["github.com"]})


def _offline(ws: BwrapWorkshop, incoming: str = "") -> list[str]:
    """Sans réseau : un envoi est noté au lieu de partir ; « récupérer » pose ``incoming`` comme ce que le dépôt
    distant vient de donner."""
    real, pushed = ws._git, []

    async def fake_git(project, *args, **kw):
        if "push" in args:
            pushed.append(next(a for a in args if ":refs/heads/" in a))
            return await real(project, "rev-parse", "HEAD")
        if "fetch" in args:
            if incoming:
                (ws.folder(project) / ".git" / "FETCH_HEAD").write_text(f"{incoming}\t\tbranch 'main' of {URL}\n")
            return await real(project, "rev-parse", "HEAD")
        return await real(project, *args, **kw)

    ws._git = fake_git  # type: ignore[method-assign]
    return pushed


@needs_bwrap
def test_a_commit_has_one_form_wherever_it_is_compared(tmp_path):
    ws = BwrapWorkshop(tmp_path)
    go(ws.write(1, "a.py", "x = 1\n"))
    made = go(ws.commit(1, "la base"))
    assert len(made) == 40 and made == go(ws.head(1)) == go(ws.commits(1, 1))[0].sha
    go(ws.work_on(1, ONE))
    go(ws.write(1, "b.py", "y = 2\n"))
    worked = go(ws.commit(1, "un travail"))
    span = go(ws.span(1, ONE))
    assert worked == span.head == span.commits[0].sha and span.base == made
    # l'abrégé n'est qu'un affichage : jamais la même chaîne
    shown = go(ws.log(1, 1)).split()[0]
    assert shown != worked and worked.startswith(shown) and len(shown) < 40
    # un travail rangé avant de changer de branche se dit lui aussi par son identifiant complet
    go(ws.write(1, "c.py", "z = 3\n"))
    placed = go(ws.work_on(1, "work/objective-2"))
    assert len(placed.stowed) == 40 and placed.stowed == go(ws._ref(1, f"refs/heads/{ONE}"))


@needs_bwrap
def test_a_review_reads_and_runs_in_a_copy_of_the_pinned_commit_and_leaves_the_workshop_alone(tmp_path):
    ws = BwrapWorkshop(tmp_path)
    go(ws.write(1, "page.html", "<h1>Accueil</h1>\n"))
    go(ws.write(1, "outils/dire.sh", "#!/bin/sh\necho relu\n"))
    (ws.folder(1) / "outils" / "dire.sh").chmod(0o755)
    pinned = go(ws.commit(1, "le travail conclu"))
    # l'atelier continue de bouger : un commit de plus, puis un fichier pas encore enregistré
    go(ws.write(1, "page.html", "<h1>Autre chose</h1>\n"))
    later = go(ws.commit(1, "la suite"))
    go(ws.write(1, "brouillon.md", "pas enregistré\n"))
    assert go(ws.checkout(1, pinned)) == "" and go(ws.checkout(1, pinned[:10])) == ""  # déjà posée : telle quelle
    home = tmp_path / REVIEWS_DIRNAME / "projet-1"
    assert [d.name for d in home.iterdir()] == [pinned]
    listed = go(ws.copy_tree(1, pinned))
    assert any(x.startswith("page.html ") for x in listed) and not [x for x in listed if "brouillon" in x]
    assert go(ws.copy_read(1, pinned, "page.html")) == "<h1>Accueil</h1>\n"  # le commit épinglé, pas l'arbre
    with pytest.raises(FileNotFoundError):
        go(ws.copy_read(1, pinned, "brouillon.md"))
    with pytest.raises(ValueError):
        go(ws.copy_read(1, pinned, "../projet-1/page.html"))
    # une commande y écrit ce qu'elle veut : rien n'en reste dans l'atelier
    ran = go(ws.copy_run(1, pinned, ["sh", "-c", "cat page.html; echo trace > trace.txt; mkdir dist; pwd"]))
    assert ran.ok and "<h1>Accueil</h1>" in ran.stdout and str(ws.folder(1)) in ran.stdout
    assert go(ws.copy_run(1, pinned, ["sh", "outils/dire.sh"])).stdout.strip() == "relu"  # un script du commit relu
    assert "n'est pas autorisé" in go(ws.copy_run(1, pinned, ["outils/dire.sh"])).refused  # la même palette
    assert any(x.startswith("trace.txt ") for x in go(ws.copy_tree(1, pinned)))
    assert not (ws.folder(1) / "trace.txt").exists() and not (ws.folder(1) / "dist").exists()
    assert go(ws.pending(1)) == ["brouillon.md"] and go(ws.head(1)) == later and go(ws.branch(1)) == BASE_BRANCH
    assert go(ws.read(1, "page.html")) == "<h1>Autre chose</h1>\n"
    # pas de dépôt dans la copie, pas de réseau, et rien hors de sa palette
    assert not go(ws.copy_run(1, pinned, ["git", "status"])).ok
    assert "n'est pas autorisé" in go(ws.copy_run(1, pinned, ["curl", "https://exemple.test"])).refused
    # un autre commit remplace la copie ; effacée, plus rien ne s'y lit ni ne s'y lance
    assert go(ws.checkout(1, later)) == "" and [d.name for d in home.iterdir()] == [later]
    assert go(ws.checkout(1, "f" * 40)) != "" and go(ws.checkout(2, pinned)) == NO_COMMIT
    go(ws.discard(1))
    assert not home.exists() and "aucune copie" in go(ws.copy_run(1, later, ["ls"])).refused
    with pytest.raises(FileNotFoundError):
        go(ws.copy_tree(1, later))


@needs_bwrap
def test_the_workshop_remembers_what_the_remote_has_per_address(tmp_path):
    ws = _shop(tmp_path)
    go(ws.write(1, "a.py", "x = 1\n"))
    first = go(ws.commit(1, "la base"))
    pushed = _offline(ws)
    assert go(ws.sent(1, URL, "main")) == ""  # jamais envoyé ni récupéré : il n'en sait rien
    assert go(ws.push(1, URL, "main", first)).ok and pushed == [f"{first}:refs/heads/main"]
    assert go(ws.sent(1, URL, "main")) == first
    go(ws.write(1, "b.py", "y = 2\n"))
    second = go(ws.commit(1, "la suite"))
    assert go(ws.sent(1, URL, "main")) == first  # ce qui n'est pas parti n'y est pas
    # le diff de ce que le distant n'a pas : la suite seulement
    patch = go(ws.patch(1, go(ws.sent(1, URL, "main")), second))
    assert "b.py" in patch and "a.py" not in patch
    assert go(ws.push(1, URL, "main", second[:12])).ok and go(ws.sent(1, URL, "main")) == second
    # une autre adresse, une autre branche : rien de ce que l'ancienne avait ne passe pour envoyé
    assert go(ws.sent(1, "https://github.com/moi/autre.git", "main")) == "" and go(ws.sent(1, URL, "dev")) == ""
    assert go(ws.sent(1, "pas une adresse", "main")) == "" and go(ws.sent(9, URL, "main")) == ""
    # la référence est à part des branches : ni l'historique ni l'état de l'atelier ne la voient
    assert go(ws.count(1)) == 3 and go(ws.pending(1)) == []


def _remote_root(ws: BwrapWorkshop, name: str, text: str) -> str:
    """Un commit racine sans rien de commun avec l'amorce de l'atelier : l'histoire qu'un dépôt distant a déjà."""
    (ws.folder(1) / name).write_text(text)
    assert go(ws._git(1, "add", name)).ok
    tree = go(ws._git(1, "write-tree")).stdout.strip()
    assert go(ws._git(1, "reset", "-q")).ok
    (ws.folder(1) / name).unlink()
    made = go(ws._git(1, "commit-tree", tree, "-m", "histoire du distant"))
    assert made.ok
    return made.stdout.strip()


@needs_bwrap
def test_a_bare_base_takes_the_remote_history_even_after_a_first_run_worked(tmp_path):
    ws = _shop(tmp_path)
    go(ws.write(1, "page.html", "<h1>Accueil</h1>\n"))  # la première exécution part avant toute récupération
    remote = _remote_root(ws, "README.md", "# Le dépôt\n")  # ce que le distant a déjà : sans rien de l'atelier
    assert go(ws.work_on(1, ONE)).branch == ONE
    worked = go(ws.commit(1, "exécution n° 1"))
    assert go(ws.work_on(1, "work/objective-2")).created  # une autre branche, sans rien à elle
    assert go(ws.work_on(1, ONE)).branch == ONE
    go(ws.write(1, "brouillon.md", "pas enregistré\n"))
    amorce = go(ws._ref(1, f"refs/heads/{BASE_BRANCH}"))
    _offline(ws, remote)
    got = go(ws.pull(1, URL, "main"))
    assert got.ok and "prend l'histoire du dépôt distant" in got.stdout
    # la base est exactement ce que le distant a : rien du travail n'y est entré
    assert go(ws._ref(1, f"refs/heads/{BASE_BRANCH}")) == remote != amorce
    span = go(ws.span(1, ONE))
    assert span is not None and span.base == remote and span.files == ("page.html",)
    assert [k.title for k in span.commits] == ["exécution n° 1"] and span.head != worked
    parents = go(ws._git(1, "rev-list", "--parents", "-1", span.head)).stdout.split()
    assert parents == [span.head, remote]  # rejoué, un seul parent : aucune fusion
    # l'atelier est resté sur sa branche, avec son travail, ce qui n'était pas enregistré et les fichiers du distant
    assert go(ws.branch(1)) == ONE and go(ws.head(1)) == span.head and go(ws.pending(1)) == ["brouillon.md"]
    assert go(ws.read(1, "page.html")) == "<h1>Accueil</h1>\n" and go(ws.read(1, "README.md")) == "# Le dépôt\n"
    assert go(ws._ref(1, "refs/heads/work/objective-2")) == remote
    # ensuite la base n'avance plus qu'en ligne droite
    assert "déjà à jour" in go(ws.pull(1, URL, "main")).stdout


@needs_bwrap
def test_a_base_with_work_of_its_own_still_refuses_a_diverged_remote_and_a_clash_changes_nothing(tmp_path):
    ws = _shop(tmp_path)
    go(ws.write(1, "a.py", "x = 1\n"))
    assert go(ws.commit(1, "enregistré sur la base, avant les pull requests"))
    go(ws.work_on(1, ONE))
    base = go(ws._ref(1, f"refs/heads/{BASE_BRANCH}"))
    _offline(ws, _remote_root(ws, "README.md", "# Le dépôt\n"))
    refused = go(ws.pull(1, URL, "main"))
    assert not refused.ok and "ont divergé" in refused.refused and go(ws._ref(1, f"refs/heads/{BASE_BRANCH}")) == base
    # le même fichier des deux côtés : le travail ne se rejoue pas, rien ne bouge
    other = _shop(tmp_path / "autre")
    go(other.write(1, "README.md", "# Le mien\n"))
    go(other.work_on(1, ONE))
    worked = go(other.commit(1, "exécution n° 1"))
    amorce = go(other._ref(1, f"refs/heads/{BASE_BRANCH}"))
    clash = _remote_root(other, "README.md", "# Le leur\n")
    go(other.write(1, "README.md", "# Le mien\n"))
    assert go(other.pending(1)) == []
    _offline(other, clash)
    refused = go(other.pull(1, URL, "main"))
    assert not refused.ok and "ne se rejoue pas" in refused.refused
    assert go(other._ref(1, f"refs/heads/{BASE_BRANCH}")) == amorce and go(other.head(1)) == worked


@needs_bwrap
def test_a_commit_is_hers_only_when_signed_and_laid_by_the_whole_workshop_address(tmp_path):
    """Un commit n'est dit d'elle que signé **et** posé par l'adresse entière de l'atelier (ADR 0292) : celui d'un
    autre compte dont l'adresse finit seulement comme elle — venu du dépôt distant — porte le drapeau « venu
    d'ailleurs ». Et ``.env`` ne s'enregistre jamais, même nommé."""
    ws = _shop(tmp_path)

    async def scenario():
        await ws.write(1, "a.txt", "un\n")
        mine = await ws.commit(1, "le sien")
        await ws.write(1, "b.txt", "deux\n")
        await ws._git(1, "add", "-A")
        await ws._git(1, "-c", "user.name=Quelqu'un", "-c", "user.email=intrus@atelier.local", "commit", "-q", "-m",
                      "venu d'ailleurs, sous une adresse qui finit comme la sienne")
        other = await ws.head(1)
        await ws.write(1, ".env", "CLE=secret\n")
        await ws.write(1, "conf/.env.production", "CLE=secret\n")
        nothing = await ws.commit(1, "des secrets", [".env"])
        await ws.write(1, "c.txt", "trois\n")
        last = await ws.commit(1, "le reste")
        tracked = (await ws._git(1, "ls-files")).stdout.split()
        return mine, other, nothing, last, tracked, {k.sha: k.local for k in (await ws.history(1, n=10)).commits}

    mine, other, nothing, last, tracked, local = go(scenario())
    assert local[mine] is True and local[last] is True and local[other] is False
    assert nothing == "" and "c.txt" in tracked
    assert ".env" not in tracked and "conf/.env.production" not in tracked
