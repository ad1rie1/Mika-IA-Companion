"""La vue de l'atelier d'un projet lu (ADR 0260), vue de la faculté des projets — l'atelier en mémoire tient lieu du
vrai, que ``tests/contract/test_workshop_views.py`` garde.

- ses outils lisent la vue sous ``liens/<n>/`` : le dernier commit du projet lu, pas son travail en cours ;
- ``ws_write`` et ``ws_edit`` la refusent, en clair, et rien ne s'écrit nulle part ;
- le droit se relit à chaque appel : repris, la lecture s'arrête à l'appel suivant, la vue est supprimée, et ses
  programmes ne la reçoivent plus ;
- le prompt dit où est chaque vue, le commit vu, son âge et le début de son arbre — ou pourquoi il n'y en a pas ;
- le ménage suit le lien, le droit et les deux projets, après le commit, sans attendre que le lecteur retravaille ;
- aucun fichier d'une vue ne part par le partage de fichiers d'un projet ;
- la fiche dit ce qu'un lien donne, les fichiers compris.
"""

from __future__ import annotations

import itertools

from mika.contracts import projects as c
from mika.contracts import shares as shares_c
from mika.faculties.projects import links
from mika.faculties.projects.atelier import no_view_words, tidy_views
from mika.faculties.projects.faculty import written
from mika.faculties.projects.inspect import GIVES_FILES, READS_TITLE, gives_words
from mika.faculties.projects.prompt import VIEW_TREE_SHOWN, _links_section, _texts, _views
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import EpisodeRef, Frame
from mika.runtime.operations import perform
from mika.runtime.tools import ToolContext
from mika.vocab.access import OWNER, STEER_NO, STEER_READ
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import phrase
from tests.fixtures.atelier import Atelier
from tests.unit import test_shares as shares
from tests.unit.test_project_access import facing, set_access
from tests.unit.test_project_links import WORLD, _line, _project, _read, _state
from tests.unit.test_projects import create, form, live
from tests.unit.test_projects_console import tab, tables

_CALLS = itertools.count(1)
#: ce que le projet lu a enregistré, et ce qu'il a en cours
README, MODULE = "Le produit fait ceci.\n", "x = 1\n"


async def _pair(kernel) -> tuple[int, int]:
    """Deux projets d'Adrien : « Le produit », qui a enregistré deux fichiers et en a un en cours, et « Faire
    connaître », qui le lit."""
    produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module")
    connaitre = await create(kernel, "p2", title="Faire connaître", objectives="Écrire un article")
    atelier = kernel.ports["workshop"]
    await atelier.write(produit, "README.md", README)
    await atelier.write(produit, "src/module.py", MODULE)
    assert await atelier.commit(produit, "première version")
    await atelier.write(produit, "README.md", "À moitié réécrit.\n")  # en cours : pas enregistré
    await atelier.write(produit, "brouillon.md", "pas encore\n")
    await _link(kernel, connaitre, produit, nonce="l1")
    return produit, connaitre


async def _link(kernel, reader: int, *targets: int, nonce: str) -> None:
    """Le propriétaire règle ce que lit ``reader`` : exactement ``targets``."""
    known = kernel.mind.frame().state("projects").projects
    off = tuple(f"lit_{t}" for t in known if t != reader and t not in targets)
    got = await perform(kernel, "projects.liens", form(off, **{f"lit_{t}": "on" for t in targets}), by="user_1",
                        subject=str(reader), nonce=nonce)
    assert got.ok, got


def _ctx(kernel, name: str, pid: int, port=None) -> ToolContext:
    """Un appel d'outil pendant une exécution du projet ``pid`` ; ``port`` : un autre atelier que celui du noyau."""
    mind, n = kernel.mind, next(_CALLS)
    episode = EpisodeRef(f"ep-vue-{n}", Kind.WORK, target=project_target(pid))
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, facing("user_1", owner=True), episode)
    ports = kernel.ports if port is None else {**kernel.ports, "workshop": port}
    return ToolContext(mind, mind.registry.tools[name], f"appel-vue-{n}", f"ep-vue-{n}", frame, ports=ports)


async def _tool(kernel, name: str, pid: int, port=None, **args) -> tuple[bool, str]:
    """Un appel d'outil de l'atelier, ses arguments validés comme la boucle les valide : (réussi, ce qu'il rend)."""
    spec = kernel.mind.registry.tools[name]
    out = await spec.handler(spec.args.model_validate(args), _ctx(kernel, name, pid, port))
    return (out.ok, out.content) if isinstance(out, ToolResult) else (True, str(out))


# ── La règle ──────────────────────────────────────────────────────────────


def test_the_views_open_to_a_project_are_those_its_links_and_their_rows_give_now():
    """Dans l'ordre de ses liens ; un lien sans les fichiers, un lien suspendu et un lecteur archivé n'en ont pas."""
    files = _line(OWNER, see=True, steer=STEER_READ, files=True)
    s = _state(_project(1), _project(2, access=(files,)), _project(3, access=(_line(OWNER, see=True),)),
               _project(4, access=(files,)), _project(5, access=(files,), status=c.ARCHIVED))
    s = _read(s, 1, 4, 3, 2, 5)
    reader = s.projects[1]
    assert links.views(s, reader, WORLD) == (4, 2)
    assert all(links.views_workshop(s, 1, t, WORLD) == (t in (4, 2)) for t in (2, 3, 4, 5, 9))
    archived = _state(*(p if p.id != 1 else _project(1, reads=reader.reads, status=c.ARCHIVED)
                        for p in s.projects.values()))
    assert links.views(archived, archived.projects[1], WORLD) == ()
    assert links.views(s, s.projects[2], WORLD) == ()  # il ne lit rien


def test_a_link_says_the_files_it_gives():
    assert gives_words(links.Grant(True, STEER_READ, True)).endswith(GIVES_FILES)
    assert gives_words(links.Grant(True, STEER_NO, True)) == f"son titre et son état ; {GIVES_FILES}"
    assert "fichiers" not in gives_words(links.Grant(True, STEER_READ, False))
    assert gives_words(links.Grant(False, STEER_READ, True)) == "rien"  # sans le voir, rien — pas même ses fichiers


# ── Ses outils ────────────────────────────────────────────────────────────


def test_her_tools_read_the_last_commit_of_a_linked_project_under_liens(tmp_path):
    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        at = f"liens/{produit}"
        await kernel.ports["workshop"].write(connaitre, "notes.md", "mes notes\n")
        return produit, {
            "list": await _tool(kernel, "ws_list", connaitre, path=at),
            "sub": await _tool(kernel, "ws_list", connaitre, path=f"{at}/src/"),
            "read": await _tool(kernel, "ws_read", connaitre, path=f"{at}/README.md"),
            "detour": await _tool(kernel, "ws_read", connaitre, path=f"./src/../{at}/src/module.py"),
            "draft": await _tool(kernel, "ws_read", connaitre, path=f"{at}/brouillon.md"),
            "out": await _tool(kernel, "ws_read", connaitre, path=f"{at}/../../secret"),
            "root": await _tool(kernel, "ws_list", connaitre, path=""),
            "liens": await _tool(kernel, "ws_list", connaitre, path="liens"),
            "unlinked": await _tool(kernel, "ws_read", connaitre, path="liens/99/README.md"),
            "theirs": await _tool(kernel, "ws_list", produit, path=""),
        }

    produit, out = live(tmp_path, scenario)
    at = f"liens/{produit}"
    assert out["list"] == (True, f"{at}/README.md ({len(README.encode())} o)\n{at}/src/module.py (6 o)")
    assert out["sub"] == (True, f"{at}/src/module.py (6 o)")
    assert out["read"] == (True, README) and out["detour"] == (True, MODULE)  # ce qui est enregistré, pas l'en-cours
    assert not out["draft"][0] and f"{at}/brouillon.md n'existe pas" in out["draft"][1]
    assert not out["out"][0]  # un chemin qui sort de la vue retombe dans son atelier, où il n'y a rien
    entry = phrase("projects.workshop.view_entry", path=f"{at}/", id=produit)
    assert out["root"] == (True, f"notes.md (10 o)\n{entry}")  # la racine de son atelier dit aussi ses vues
    assert out["liens"] == (True, entry)
    assert not out["unlinked"][0] and "dans l'atelier" in out["unlinked"][1]  # pas un lien : un chemin à lui
    assert "liens" not in out["theirs"][1]  # le projet lu ne voit rien de qui le lit


def test_a_view_is_never_written(tmp_path):
    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        atelier = kernel.ports["workshop"]
        at = f"liens/{produit}"
        before = {pid: dict(atelier.files.get(pid, {})) for pid in (produit, connaitre)}
        out = {
            "write": await _tool(kernel, "ws_write", connaitre, path=f"{at}/README.md", content="réécrit"),
            "new": await _tool(kernel, "ws_write", connaitre, path=f"{at}/nouveau.md", content="ajouté"),
            "detour": await _tool(kernel, "ws_write", connaitre, path=f"x/../{at}/y.md", content="par un détour"),
            "edit": await _tool(kernel, "ws_edit", connaitre, path=f"{at}/README.md", old="ceci", new="cela"),
        }
        # un droit repris ne rend pas la place : « liens/<n>/ » reste la vue, fermée
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture"}, nonce="a1")
        out["closed"] = await _tool(kernel, "ws_write", connaitre, path=f"{at}/README.md", content="réécrit")
        unchanged = {pid: dict(atelier.files.get(pid, {})) for pid in (produit, connaitre)} == before
        out["own"] = await _tool(kernel, "ws_write", connaitre, path="liens/utiles.md", content="des liens à lui")
        return produit, out, unchanged, atelier.files[connaitre]

    produit, out, unchanged, mine = live(tmp_path, scenario)
    refusal = phrase("projects.workshop.view_read_only", path=f"liens/{produit}/", id=produit)
    for attempt in ("write", "new", "detour", "edit", "closed"):
        assert out[attempt] == (False, refusal), attempt
    assert "n'écrit jamais dans un autre" in refusal and f"liens/{produit}/" in refusal
    assert unchanged  # rien ne s'est écrit, ni chez lui ni chez le projet lu
    assert out["own"][0] and mine == {"liens/utiles.md": "des liens à lui"}  # le reste de « liens/ » est à lui


def test_a_right_taken_back_cuts_the_reading_at_the_next_call(tmp_path):
    """Le droit se relit à chaque appel d'outil : pas besoin d'attendre l'exécution suivante, ni le ménage."""

    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        mine = Atelier()  # l'atelier que voient ses outils : le ménage d'après commit (celui du noyau) n'y touche pas
        for path, text in ((("README.md"), README), ("src/module.py", MODULE)):
            await mine.write(produit, path, text)
        await mine.commit(produit, "première version")
        at = f"liens/{produit}/README.md"
        out = {"read": await _tool(kernel, "ws_read", connaitre, mine, path=at),
               "ran": await _tool(kernel, "ws_run", connaitre, mine, argv=["grep", "-r", "ceci", "liens"])}
        out["mounted"], out["posed"] = mine.ran[-1], set(mine.views)
        # le propriétaire du projet lu ne donne plus ses fichiers (il le laisse encore lire)
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture"}, nonce="a1")
        out["cut"] = await _tool(kernel, "ws_read", connaitre, mine, path=at)
        out["gone"], out["dropped"] = set(mine.views), mine.dropped[-1]
        out["list"] = await _tool(kernel, "ws_list", connaitre, mine, path=f"liens/{produit}")
        out["root"] = await _tool(kernel, "ws_list", connaitre, mine, path="")
        await _tool(kernel, "ws_run", connaitre, mine, argv=["cat", at])
        out["unmounted"] = mine.ran[-1]
        # il les redonne : la lecture revient au premier appel
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture", "files": True}, nonce="a2")
        out["back"] = await _tool(kernel, "ws_read", connaitre, mine, path=at)
        return produit, connaitre, out

    produit, connaitre, out = live(tmp_path, scenario)
    assert out["read"] == (True, README) and out["posed"] == {(connaitre, produit)}
    assert out["mounted"] == (connaitre, ("grep", "-r", "ceci", "liens"), (produit,))  # ses programmes la voient
    closed = phrase("projects.workshop.view_closed", id=produit)
    assert out["cut"] == (False, closed) == out["list"] and "ne t'est pas ouverte" in closed
    assert out["gone"] == set() and out["dropped"] == (connaitre, ())  # supprimée par l'appel lui-même
    assert "liens" not in out["root"][1]
    assert out["unmounted"] == (connaitre, ("cat", f"liens/{produit}/README.md"), ())  # ses programmes non plus
    assert out["back"] == (True, README)


def test_a_view_that_cannot_be_posed_is_said_by_the_tools(tmp_path):
    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        vide = await create(kernel, "p3", title="Le site", objectives="Le mettre en ligne")
        await _link(kernel, connaitre, produit, vide, nonce="l2")
        atelier = kernel.ports["workshop"]
        none = await _tool(kernel, "ws_list", connaitre, path=f"liens/{vide}")
        ran = await _tool(kernel, "ws_run", connaitre, argv=["ls", "liens"])
        atelier.view_bytes = 10
        await atelier.view(connaitre, produit, fresh=True)  # au départ de l'exécution suivante : trop gros
        big = await _tool(kernel, "ws_read", connaitre, path=f"liens/{produit}/README.md")
        return produit, vide, none, big, ran, atelier.ran[-1]

    produit, vide, none, big, ran, mounted = live(tmp_path, scenario)
    assert none == (False, phrase("projects.workshop.view_none", id=vide, why=no_view_words("no_commit")))
    assert big == (False, phrase("projects.workshop.view_none", id=produit, why=no_view_words("too_big")))
    assert "rien enregistré" in none[1] and "trop volumineux" in big[1]
    assert ran[0] and mounted[2] == (produit, vide)  # le droit est là ; l'atelier ne monte que ce qui est posé
    assert no_view_words("une raison inconnue") == no_view_words("unreadable")


# ── Le prompt ─────────────────────────────────────────────────────────────


async def _links_text(kernel, pid: int, *, posed: bool = True) -> tuple[str | None, int]:
    """La section « CE QUE CE PROJET LIT » au départ d'une exécution de ce projet, et son niveau ; ``posed`` faux :
    l'enrichisseur des vues n'a pas rendu à temps."""
    run = _ctx(kernel, "ws_list", pid)
    s = run.frame.state("projects")
    enrich = {"projects": await _texts(s, run.frame, kernel.ports)}
    if posed and (found := await _views(s, run.frame, kernel.ports)) is not None:
        enrich["projects_views"] = found
    body = _links_section(s, run.frame, enrich)
    return (body.content, body.level) if body is not None else (None, 0)


def test_a_run_is_told_where_each_view_is_the_commit_seen_and_what_it_holds(tmp_path):
    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        vide = await create(kernel, "p3", title="Le site", objectives="Le mettre en ligne")
        await _link(kernel, connaitre, produit, vide, nonce="l2")
        atelier = kernel.ports["workshop"]
        out = {"start": await _links_text(kernel, connaitre), "sha": await atelier.head(produit)}
        out["late"] = await _links_text(kernel, connaitre, posed=False)
        # le projet lu enregistre son travail : l'exécution suivante le voit, pas les outils de celle en cours
        assert await atelier.commit(produit, "deuxième version")
        out["during"] = await _tool(kernel, "ws_read", connaitre, path=f"liens/{produit}/README.md")
        out["next"] = await _links_text(kernel, connaitre)
        out["after"] = await _tool(kernel, "ws_read", connaitre, path=f"liens/{produit}/README.md")
        for n in range(VIEW_TREE_SHOWN + 5):
            await atelier.write(produit, f"docs/page-{n:02d}.md", "page\n")
        assert await atelier.commit(produit, "la documentation")
        out["long"] = await _links_text(kernel, connaitre)
        atelier.view_bytes = 10
        out["big"] = await _links_text(kernel, connaitre)
        atelier.view_bytes = None
        # son propriétaire ne donne plus ses fichiers : plus un mot de la vue, et elle est supprimée
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture"}, nonce="a1")
        out["closed"] = await _links_text(kernel, connaitre)
        out["posed"] = set(atelier.views)
        # ses fichiers, sans le détail : la vue, sans « seulement le titre »
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "files": True}, nonce="a2")
        out["files_only"] = await _links_text(kernel, connaitre)
        return produit, vide, connaitre, kernel.mind.frame().state("projects").projects[produit], out

    produit, vide, connaitre, target, out = live(tmp_path, scenario)
    at = f"liens/{produit}/"
    start, level = out["start"]
    opened = phrase("projects.links.view.open", path=at, sha=out["sha"][:7],
                    age=phrase("projects.links.view.age", ago="1 minute"))
    assert opened.split(" (")[0] in start and f"({out['sha'][:7]}, d'il y a " in start
    assert "jamais son travail en cours" in start and "tu n'y écris pas" in start
    assert f"  - {at}README.md ({len(README.encode())} o)\n  - {at}src/module.py (6 o)" in start
    assert "brouillon.md" not in start  # ce qui n'est pas enregistré n'est pas dans la vue
    assert level == written(target)  # les noms de ses fichiers sont au niveau de ce qu'il écrit
    # un projet lu qui n'a rien enregistré : pas de vue, et c'est dit
    assert phrase("projects.links.view.absent", why=no_view_words("no_commit")) in start
    # la vue pas encore posée : le chemin est dit quand même, ses outils la poseront
    late = out["late"][0]
    assert phrase("projects.links.view.later", path=at) in late and "README.md" not in late
    # elle ne bouge pas pendant l'exécution ; la suivante voit le nouveau commit
    assert out["during"] == (True, README) and out["after"] == (True, "À moitié réécrit.\n")
    assert out["sha"][:7] not in out["next"][0] and f"  - {at}brouillon.md" in out["next"][0]
    # un arbre long : son début seulement, et où lire la suite
    long = out["long"][0]
    assert long.count(f"  - {at}") == VIEW_TREE_SHOWN and phrase("projects.links.view.more", path=at) in long
    assert phrase("projects.links.view.absent", why=no_view_words("too_big")) in out["big"][0]
    closed = out["closed"][0]  # il ne reste que la ligne de l'autre projet lu, qui n'a rien enregistré
    assert at not in closed and closed.count("Ses fichiers") == 1 and (connaitre, produit) not in out["posed"]
    files_only = out["files_only"][0]
    assert "Ses fichiers : la vue de son atelier est dans " + at in files_only
    assert phrase("projects.links.title_only") not in files_only and "comptes rendus" not in files_only


# ── Le ménage ─────────────────────────────────────────────────────────────


def test_the_cleaning_follows_the_link_the_right_and_both_projects(tmp_path):
    """Après le commit, sans qu'aucun outil soit appelé : un lecteur qui ne retravaille jamais ne garde rien."""

    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        atelier = kernel.ports["workshop"]

        async def posed() -> bool:
            await kernel.effects.drain()
            return (connaitre, produit) in atelier.views

        async def pose() -> None:
            assert (await atelier.view(connaitre, produit, fresh=True)).sha

        out = {}
        await pose()
        out["start"] = await posed()
        await _link(kernel, connaitre, nonce="l2")  # le lien est retiré
        out["unlinked"] = await posed()
        await _link(kernel, connaitre, produit, nonce="l3")
        await pose()
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture"}, nonce="a1")
        out["right"] = await posed()  # le droit est repris
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture", "files": True}, nonce="a2")
        await pose()
        out["kept"] = await posed()  # le droit tient : la vue reste
        assert (await perform(kernel, "projects.archiver", form(), by="user_1", subject=str(produit), nonce="x1")).ok
        out["target"] = await posed()  # le projet lu est archivé : le lien est suspendu
        assert (await perform(kernel, "projects.restaurer", form(), by="user_1", subject=str(produit), nonce="x2")).ok
        await pose()
        assert (await perform(kernel, "projects.archiver", form(), by="user_1", subject=str(connaitre), nonce="x3")).ok
        out["reader"] = await posed()  # le lecteur est archivé
        return out

    out = live(tmp_path, scenario)
    assert out == {"start": True, "unlinked": False, "right": False, "kept": True, "target": False, "reader": False}


def test_the_cleaning_is_read_on_the_current_state_and_can_be_replayed(tmp_path):
    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        atelier = Atelier()
        frame = kernel.mind.frame()
        ports = {"workshop": atelier, "frame": lambda: frame}
        for _ in range(2):  # un effet rejoué refait le même ménage
            await tidy_views(None, ports)
        every = sorted(frame.state("projects").projects)
        await tidy_views(None, {"frame": lambda: frame})  # sans atelier : rien
        return produit, connaitre, every, atelier.dropped

    produit, connaitre, every, dropped = live(tmp_path, scenario)
    expected = [(pid, (produit,) if pid == connaitre else ()) for pid in every]
    assert dropped == expected * 2 and (connaitre, (produit,)) in dropped  # chaque projet : ce qu'il garde maintenant


# ── Rien n'en sort ────────────────────────────────────────────────────────


def test_no_file_of_a_view_leaves_through_a_project_share(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, store, llm, deliveries):
        produit = await shares._project(kernel, "p1", title="Le produit")
        connaitre = await shares._project(kernel, "p2", title="Faire connaître")
        await atelier.write(produit, "secret.md", "ce que dit le produit")
        await atelier.commit(produit, "première version")
        await atelier.write(connaitre, "notes.md", "mes notes")
        await _link(kernel, connaitre, produit, nonce="l1")
        assert (await atelier.view(connaitre, produit, fresh=True)).sha  # la vue est posée
        at = f"liens/{produit}/secret.md"
        out = {
            "view": await shares.call(kernel, "share_project_file", "user_1", project=connaitre, path=at),
            "detour": await shares.call(kernel, "share_project_file", "user_1", project=connaitre,
                                        path=f"notes.md/../{at}"),
            "tree": await shares.call(kernel, "project_files", "user_1", project=connaitre),
            "under": await shares.call(kernel, "project_files", "user_1", project=connaitre, path=f"liens/{produit}"),
            "own": await shares.call(kernel, "share_project_file", "user_1", project=connaitre, path="notes.md"),
        }
        return out, shares.journal(kernel, shares_c.SHARED)

    out, shared = shares.live(tmp_path, scenario, atelier=atelier)
    assert not out["view"].ok and not out["detour"].ok
    assert "secret.md" not in out["tree"].content and "secret.md" not in out["under"].content
    assert "notes.md" in out["tree"].content
    assert out["own"].ok and [e.data.name.text for e in shared] == ["notes.md"]  # seul son propre fichier est parti


# ── La fiche ──────────────────────────────────────────────────────────────


def test_the_fiche_says_the_files_a_link_gives(tmp_path):
    async def scenario(kernel, llm):
        produit, connaitre = await _pair(kernel)
        full = tables(await tab(kernel, "comportement", str(connaitre)))[READS_TITLE].rows
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture"}, nonce="a1")
        read = tables(await tab(kernel, "comportement", str(connaitre)))[READS_TITLE].rows
        return full, read

    full, read = live(tmp_path, scenario)
    assert full[0][2].text.endswith(GIVES_FILES) and "son dernier commit, en lecture seule" in GIVES_FILES
    assert "fichiers" not in read[0][2].text and "ses comptes rendus" in read[0][2].text
