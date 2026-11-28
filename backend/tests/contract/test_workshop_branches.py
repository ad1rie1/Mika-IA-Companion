"""Les branches de travail d'un atelier (ADR 0274), sur le vrai adaptateur :

- une branche de travail naît de la base à sa première demande, et se retrouve ensuite ; la base ne reçoit rien ;
- un travail resté non enregistré sur une branche de travail y est rangé avant de changer ; resté sur la base, il
  suit sur la branche — la base n'est jamais une branche de travail ;
- ``span`` mesure le vrai diff d'une branche face à sa base, pas une somme par enregistrement ;
- une récupération n'avance que la base quand l'atelier est sur une branche de travail : ni l'arbre ni la branche en
  cours ne bougent, et seulement en ligne droite ;
- la vue qu'un projet lecteur a de cet atelier (ADR 0260) ne montre que la base ;
- la base se ramène dans la branche de travail (ADR 0280) : sans conflit, elle y entre et l'enregistrement de
  l'exécution la garde ; en conflit, les marques restent dans les fichiers, nommés, jusqu'à ce qu'ils soient
  résolus — la base elle-même n'est jamais écrite.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

from mika.adapters.workshop import BwrapWorkshop
from mika.ports.workshop import BASE_BRANCH

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
URL = "https://github.com/moi/depot.git"
ONE, TWO = "work/objective-1", "work/objective-2"


def go(coro):
    return asyncio.run(coro)


def _based(tmp_path) -> tuple[BwrapWorkshop, str]:
    """Un atelier dont la base a un fichier enregistré ; rend l'atelier et le commit de sa base."""
    ws = BwrapWorkshop(tmp_path)
    go(ws.write(1, "a.py", "x = 1\n"))
    assert go(ws.commit(1, "la base"))
    return ws, go(ws._ref(1, f"refs/heads/{BASE_BRANCH}"))


def _files(ws: BwrapWorkshop, project: int = 1) -> set[str]:
    return {p.name for p in ws.folder(project).iterdir() if p.is_file() and p.name != ".gitignore"}


def _fetching(ws: BwrapWorkshop, sha: str) -> None:
    """Sans réseau : « récupérer » pose ce commit comme ce que le dépôt distant vient de donner."""
    real = ws._git

    async def fake_git(project, *args, **kw):
        if "fetch" in args:  # ce que ``git fetch`` laisse : le commit récupéré, dans ``FETCH_HEAD``
            (ws.folder(project) / ".git" / "FETCH_HEAD").write_text(f"{sha}\t\tbranch 'main' of {URL}\n")
            return await real(project, "rev-parse", "HEAD")
        return await real(project, *args, **kw)

    ws._git = fake_git  # type: ignore[method-assign]


def _accepted(ws: BwrapWorkshop, branch: str, parent: str) -> str:
    """Le commit que l'hôte aurait fait en acceptant cette branche sur la base (un commit de plus, hors de toute
    branche d'ici)."""
    made = go(ws._git(1, "commit-tree", f"refs/heads/{branch}^{{tree}}", "-p", parent, "-m", "accepté chez l'hôte"))
    assert made.ok
    return made.stdout.strip()


@needs_bwrap
def test_a_work_branch_is_born_from_the_base_and_found_again(tmp_path):
    ws, base = _based(tmp_path)
    first = go(ws.work_on(1, ONE))
    assert (first.branch, first.created, first.base, first.ahead, first.why) == (ONE, True, base, 0, "")
    assert go(ws.branch(1)) == ONE
    go(ws.write(1, "b.py", "y = 2\n"))
    assert go(ws.commit(1, "le travail"))
    again = go(ws.work_on(1, ONE))
    assert (again.branch, again.created, again.ahead, again.stowed) == (ONE, False, 1, "")
    # la base n'a rien reçu : le commit du travail est sur sa branche seulement
    assert go(ws._ref(1, f"refs/heads/{BASE_BRANCH}")) == base
    assert go(ws._ahead(1, ONE)) == 1


@needs_bwrap
def test_an_interrupted_work_is_stowed_on_its_branch_before_switching(tmp_path):
    ws, base = _based(tmp_path)
    go(ws.work_on(1, ONE))
    go(ws.write(1, "b.py", "y = 2\n"))
    assert go(ws.commit(1, "le travail"))
    go(ws.write(1, "c.py", "z = 3\n"))  # une exécution interrompue : rien d'enregistré
    moved = go(ws.work_on(1, TWO, stow="travail interrompu, rangé"))
    assert (moved.branch, moved.created, moved.stowed_on) == (TWO, True, ONE) and moved.stowed
    # la nouvelle branche part de la base : elle n'a rien de l'autre travail, et rien n'y traîne
    assert _files(ws) == {"a.py"} and go(ws.pending(1)) == []
    assert go(ws._ref(1, f"refs/heads/{BASE_BRANCH}")) == base
    # le travail interrompu est sur sa branche, enregistré sous le message donné
    back = go(ws.work_on(1, ONE))
    assert back.branch == ONE and back.ahead == 2 and _files(ws) == {"a.py", "b.py", "c.py"}
    assert go(ws.commits(1, 1))[0].title == "travail interrompu, rangé"


@needs_bwrap
def test_the_base_is_never_a_work_branch_and_what_was_left_on_it_follows(tmp_path):
    ws, base = _based(tmp_path)
    refused = go(ws.work_on(1, BASE_BRANCH))
    assert not refused.branch and "base" in refused.why and go(ws.branch(1)) == BASE_BRANCH
    assert not go(ws.work_on(1, "../ailleurs")).branch
    # un fichier déposé pendant que l'atelier est sur sa base : il n'y est jamais enregistré, il suit sur la branche
    go(ws.write(1, "apport.txt", "à lire\n"))
    placed = go(ws.work_on(1, ONE, stow="rangé"))
    assert (placed.branch, placed.stowed) == (ONE, "") and go(ws.pending(1)) == ["apport.txt"]
    assert go(ws._ref(1, f"refs/heads/{BASE_BRANCH}")) == base


@needs_bwrap
def test_a_span_is_the_real_diff_of_a_branch_against_its_base(tmp_path):
    ws, base = _based(tmp_path)
    assert go(ws.span(1, ONE)) is None  # une branche inconnue
    go(ws.work_on(1, ONE))
    empty = go(ws.span(1, ONE))
    assert empty is not None and (empty.files, empty.commits) == ((), ())
    go(ws.write(1, "a.py", "x = 1\ny = 2\n"))
    go(ws.write(1, "né.py", "z = 3\n"))
    assert go(ws.commit(1, "premier pas"))
    go(ws.write(1, "a.py", "x = 1\ny = 3\n"))  # la même ligne, réécrite : une ligne de plus face à la base, pas deux
    assert go(ws.commit(1, "second pas"))
    span = go(ws.span(1, ONE))
    assert span is not None and set(span.files) == {"a.py", "né.py"}  # un chemin accentué se lit tel quel
    assert (span.insertions, span.deletions) == (2, 0)
    assert [k.title for k in span.commits] == ["second pas", "premier pas"]
    assert span.base == base and span.head == go(ws.head(1))


@needs_bwrap
def test_a_pull_only_advances_the_base_when_the_workshop_is_on_a_work_branch(tmp_path):
    ws, base = _based(tmp_path)
    go(ws.work_on(1, ONE))
    go(ws.write(1, "b.py", "y = 2\n"))
    assert go(ws.commit(1, "le travail"))
    head = go(ws.head(1))
    go(ws.write(1, "en-cours.py", "pas fini\n"))  # le travail en cours : il ne doit pas bouger
    accepted = _accepted(ws, ONE, base)
    _fetching(ws, accepted)
    got = go(ws.pull(1, URL, "main"))
    assert got.ok and accepted[:12] in got.stdout
    assert go(ws._ref(1, f"refs/heads/{BASE_BRANCH}")) == accepted  # la base a avancé…
    assert (go(ws.branch(1)), go(ws.head(1))) == (ONE, head)  # … ni la branche en cours ni son bout
    assert go(ws.pending(1)) == ["en-cours.py"] and _files(ws) == {"a.py", "b.py", "en-cours.py"}
    assert go(ws.pull(1, URL, "main")).ok  # déjà à jour : rien à faire
    # une base qui a divergé du distant ne recule ni ne saute : rien n'est récupéré
    elsewhere = go(ws._git(1, "commit-tree", f"{base}^{{tree}}", "-p", base, "-m", "ailleurs")).stdout.strip()
    _fetching(ws, elsewhere)
    refused = go(ws.pull(1, URL, "main"))
    assert refused.refused and "divergé" in refused.refused
    assert go(ws._ref(1, f"refs/heads/{BASE_BRANCH}")) == accepted


@needs_bwrap
def test_the_view_of_a_reader_only_shows_the_base(tmp_path):
    ws, base = _based(tmp_path)
    go(ws.work_on(1, ONE))
    go(ws.write(1, "b.py", "y = 2\n"))
    assert go(ws.commit(1, "le travail"))
    go(ws.write(2, "note.md", "le lecteur\n"))
    seen = go(ws.view(2, 1, fresh=True))
    listed = "\n".join(go(ws.view_tree(2, 1)))
    assert seen.sha == base and "a.py" in listed and "b.py" not in listed  # ni la branche, ni le travail en cours
    # accepté chez l'hôte puis récupéré : la base avance, et la vue avec elle
    accepted = _accepted(ws, ONE, base)
    _fetching(ws, accepted)
    assert go(ws.pull(1, URL, "main")).ok
    after = go(ws.view(2, 1, fresh=True))
    assert after.sha == accepted and "b.py" in "\n".join(go(ws.view_tree(2, 1)))


# ── La base ramenée dans la branche de travail (ADR 0280) ──────────────────


def _two_tickets(tmp_path) -> tuple[BwrapWorkshop, str, str]:
    """Deux branches de travail parties de la même base, qui changent la même ligne ; la première est acceptée chez
    l'hôte, et la base récupérée. Rend l'atelier (sur la seconde), la base d'avant et la base d'après."""
    ws, base = _based(tmp_path)
    assert go(ws.work_on(1, ONE)).created
    go(ws.write(1, "a.py", "x = 2\n"))
    go(ws.write(1, "b.py", "y = 1\n"))
    assert go(ws.commit(1, "le premier ticket"))
    assert go(ws.work_on(1, TWO)).created
    go(ws.write(1, "a.py", "x = 3\n"))
    assert go(ws.commit(1, "le second ticket"))
    moved = _accepted(ws, ONE, base)
    _fetching(ws, moved)
    assert go(ws.pull(1, URL, "main")).ok and go(ws.base(1)) == moved
    return ws, base, moved


@needs_bwrap
def test_the_base_comes_into_the_working_branch_and_its_conflicts_stay_in_the_files_named(tmp_path):
    ws, _, moved = _two_tickets(tmp_path)
    tip = go(ws.head(1))
    assert go(ws.unresolved(1)) == []  # rien n'est en cours
    # ni la base ni une autre branche que celle où l'atelier se trouve
    assert "base" in go(ws.take_base(1, BASE_BRANCH)).why and "n'est pas sur" in go(ws.take_base(1, ONE)).why
    go(ws.write(1, "notes.md", "pas encore enregistré\n"))
    got = go(ws.take_base(1, TWO, stow="rangé avant la base"))
    # ce qui n'était pas enregistré est rangé d'abord ; le conflit est nommé, ses marques sont dans le fichier
    assert (got.branch, got.base, got.conflicts, got.why) == (TWO, moved, ("a.py",), "") and got.stowed
    text = go(ws.read(1, "a.py"))
    assert "<<<<<<< " in text and "x = 3" in text and "x = 2" in text and ">>>>>>> " in text
    assert go(ws.read(1, "b.py")) == "y = 1\n"  # ce qui ne se contredit pas est entré
    assert go(ws.unresolved(1)) == ["a.py"]
    # rien n'est écrit sur la base, rien n'est enregistré : la branche est où le rangement l'a laissée
    assert go(ws.base(1)) == moved and go(ws.head(1)) == got.stowed != tip
    # redemandée pendant qu'elle est en cours : la même réponse, rien ne bouge
    again = go(ws.take_base(1, TWO))
    assert (again.branch, again.base, again.conflicts) == (TWO, moved, ("a.py",))
    # elle résout dans le fichier, puis l'enregistrement de l'exécution garde la base et sa résolution
    go(ws.write(1, "a.py", "x = 3  # la base disait 2\n"))
    assert go(ws.unresolved(1)) == []
    sha = go(ws.commit(1, "objectif n° 2"))
    assert sha and go(ws.head(1)) == sha and not go(ws.pending(1))
    parents = go(ws._git(1, "rev-list", "--parents", "-n", "1", sha)).stdout.split()[1:]
    assert parents == [got.stowed, moved]  # la base est entrée dans la branche, pas l'inverse
    assert go(ws.base(1)) == moved
    span = go(ws.span(1, TWO))
    assert set(span.files) == {"a.py", "notes.md"} and span.base == moved  # son diff face à la base : son travail seul
    done = go(ws.take_base(1, TWO))
    assert done.already and (done.branch, done.conflicts) == (TWO, ())


@needs_bwrap
def test_a_base_without_conflict_comes_in_and_a_branch_with_nothing_of_its_own_just_follows(tmp_path):
    ws, base = _based(tmp_path)
    assert go(ws.work_on(1, ONE)).created
    go(ws.write(1, "b.py", "y = 1\n"))
    assert go(ws.commit(1, "le premier ticket"))
    assert go(ws.work_on(1, TWO)).created
    go(ws.write(1, "c.py", "z = 1\n"))
    worked = go(ws.commit(1, "le second ticket"))
    moved = _accepted(ws, ONE, base)
    _fetching(ws, moved)
    assert go(ws.pull(1, URL, "main")).ok
    got = go(ws.take_base(1, TWO))
    assert (got.branch, got.base, got.conflicts, got.already, got.stowed) == (TWO, moved, (), False, "")
    assert _files(ws) == {"a.py", "b.py", "c.py"} and go(ws.head(1)) == worked  # entrée, pas encore enregistrée
    sha = go(ws.commit(1, "objectif n° 2"))
    assert sha and go(ws.span(1, TWO)).files == ("c.py",) and go(ws.base(1)) == moved
    # une branche qui n'a rien à elle rejoint la base en ligne droite : rien à enregistrer
    assert go(ws.work_on(1, "work/objective-3")).created
    later = _accepted(ws, TWO, moved)
    _fetching(ws, later)
    assert go(ws.pull(1, URL, "main")).ok
    followed = go(ws.take_base(1, "work/objective-3"))
    assert (followed.base, followed.conflicts, followed.why) == (later, (), "")
    assert go(ws.head(1)) == later and not go(ws.pending(1)) and go(ws.unresolved(1)) == []
