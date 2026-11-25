"""Fusionner une pull request : le geste d'une personne, et de personne d'autre (ADR 0288), sur le vrai atelier et un
faux hôte branché comme port :

- le propriétaire fusionne, au commit qu'il a lu : la demande est un fait, la fusion part après le commit du journal,
  par le port ; l'hôte la reçoit avec ce commit ;
- le moteur l'apprend ensuite comme toute fusion — le processus qui relit l'hôte pose ``pull_seen`` : l'objectif est
  clos, son ticket traité, la base récupérée ; la réponse de la fusion ne clôt rien elle-même ;
- elle se refuse à qui ne tranche pas, quand la branche a bougé (dans l'atelier, chez l'hôte), quand l'hôte la dit
  impossible à fusionner ; un refus de l'hôte au moment de fusionner se garde, et ne clôt rien ;
- ``merge.blocked`` dit, de l'état seul, pourquoi une pull request n'est pas prête ;
- **la fusion relit la CI** (ADR 0292) : juste après un envoi l'hôte ne dit encore aucune vérification — la fusion
  attend, et l'hôte se relit à l'écart court ; au moment de fusionner, l'action relit les vérifications du commit de
  tête et la base où la pull request entre ; une seule demande à la fois ; une réponse perdue se dit « on ne sait
  pas », et l'hôte se relit aussitôt ;
- **aucun autre chemin ne fusionne** : ``merge_asked`` n'est écrit que par l'action d'une personne, ``merge_pull``
  n'est appelé que par l'effet de ce fait ; ni outil, ni capacité, ni processus.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import replace
from pathlib import Path

import mika
from mika.app.me.api import form as fixed_form
from mika.contracts import projects as c
from mika.faculties.projects import inspect_merge, merge
from mika.faculties.projects.faculty import (
    MERGE_ANSWERED,
    MERGE_ASKED,
    MERGE_CUT,
    PULL_SEEN,
    Objective,
    Project,
    branch_of,
)
from mika.faculties.projects.tracker import AddArgs, ItemArg, items_add
from mika.kernel.clock import MINUTE
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_NONE,
    CHECKS_PASSED,
    CHECKS_PENDING,
    MERGE_BLOCKED,
    MERGE_UNKNOWN,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
    Checks,
    Merged,
    Pull,
)
from mika.runtime.operations import perform
from tests.fixtures.mika import connect
from tests.unit.test_project_milestones import reach_all
from tests.unit.test_project_pulls import NO_RUN, URL, Host, _objective, _report, _start, live, needs_bwrap
from tests.unit.test_project_tickets import PLAN, _do, _entry
from tests.unit.test_project_tracker import _run
from tests.unit.test_projects import create, events, row_form, wait

SRC = Path(mika.__file__).parent


def merging(host: Host) -> Host:
    """Le faux hôte des pull requests apprend à fusionner : ce qu'on lui a demandé (``merges``), et ce qu'il répond
    (``refuse`` : pourquoi il refuse ; vide : il fusionne)."""
    host.merges, host.refuse = [], ""

    async def merge_pull(url: str, number: int, *, sha: str) -> Merged:
        host.merges.append((url, number, sha))
        if host.refuse:
            return Merged(number=number, why=host.refuse, error="non")
        host.says = replace(host.says, state=PULL_MERGED)
        return Merged(number=number, merged=True, sha="d" * 40)

    host.merge_pull = merge_pull
    return host


async def _fuse(kernel, pid: int, oid: int, head: str, by: str = "user_1"):
    return await perform(kernel, inspect_merge.ACTION, fixed_form(fixed={"objective": str(oid), "head": head}),
                         by=by, subject=str(pid))


@needs_bwrap
def test_the_owner_merges_at_the_commit_he_read_and_the_engine_learns_it_like_any_merge(tmp_path):
    async def scenario(kernel, shop, host):
        ws, out = shop.ws, {}
        merging(host)
        await connect(kernel, "user_2", "Léa")
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil", remote=URL,
                           reread="never", **NO_RUN)
        assert (await perform(kernel, "projects.tickets_regler", row_form(
            {}, ticket_review=c.REVIEW_LARGE, small_files="3", small_lines="40", protected=""), by="user_1",
            subject=str(pid), nonce="r1")).ok
        await ws.write(pid, "LISEZMOI.md", "# Le site\n")
        await ws.commit(pid, "la base")
        await items_add(AddArgs(list_name="tickets", items=[ItemArg(title="Corriger un prix")]),
                        _run(kernel, pid, "items_add"))
        await _do(kernel, pid, item="1", **{**PLAN, "small": True})
        oid = _entry(kernel, pid, 1).item.objective
        await _start(kernel, pid, oid)
        await ws.write(pid, "tarifs.html", "un\ndeux\ntrois\n")
        await reach_all(kernel, pid, oid)
        await _report(kernel, pid, oid, "done")
        await wait(3)
        o = _objective(kernel, pid, oid)
        branch = branch_of(o)
        head = await ws._ref(pid, f"refs/heads/{branch}")
        host.says = replace(host.says, sha=head, mergeable=True)
        out["ready"] = (o.pull, o.pull_state, _entry(kernel, pid, 1).item.pull, merge.blocked(
            kernel.mind.frame().state("projects").projects[pid], o))
        # son commit vient de partir : l'hôte n'a pas encore dit ses vérifications — la fusion attend (ADR 0292)
        out["fresh"] = await _fuse(kernel, pid, oid, head)
        await wait(4)
        # qui ne tranche pas ne fusionne pas ; ni sans nommer le commit lu, ni pour un autre commit
        out["stranger"] = await _fuse(kernel, pid, oid, head, by="user_2")
        out["unnamed"] = await _fuse(kernel, pid, oid, "")
        out["moved_here"] = await _fuse(kernel, pid, oid, "0" * 40)
        host.says = replace(host.says, sha="e" * 40)  # chez l'hôte, la branche est ailleurs
        out["moved_there"] = await _fuse(kernel, pid, oid, head)
        host.says = replace(host.says, sha=head, mergeable=False)  # l'hôte la dit impossible à fusionner
        out["host_says_no"] = await _fuse(kernel, pid, oid, head)
        host.says = replace(host.says, mergeable=True)
        out["nothing_asked"] = (len(events(kernel, MERGE_ASKED)), list(host.merges))
        # l'hôte refuse au moment de fusionner : le refus se garde, rien ne se clôt
        host.refuse = MERGE_BLOCKED
        out["asked"] = await _fuse(kernel, pid, oid, head)
        await wait(2)
        o = _objective(kernel, pid, oid)
        out["refused"] = (o.merge_refused, o.merge_asked_at, o.pull_state, o.status,
                          _entry(kernel, pid, 1).item.closed, list(host.merges))
        out["refused_answer"] = events(kernel, MERGE_ANSWERED)[-1].data
        # il recommence : l'hôte fusionne, puis le processus qui relit l'hôte l'apprend
        host.refuse, reads = "", host.reads
        shop.incoming = await shop.accepted(pid, branch)
        out["again"] = await _fuse(kernel, pid, oid, head)
        asked = events(kernel, MERGE_ASKED)[-1]
        out["asked_event"] = asked.data
        await wait(3)
        o, item = _objective(kernel, pid, oid), _entry(kernel, pid, 1).item
        out["merged"] = (o.pull_state, o.status, o.pulls_merged, o.merge_asked_at, o.merge_refused, item.status,
                         item.closed)
        answered, seen = events(kernel, MERGE_ANSWERED)[-1], events(kernel, PULL_SEEN)[-1]
        out["order"] = (asked.seq < answered.seq < seen.seq, answered.data.merged, answered.data.commit,
                        seen.data.state, host.reads > reads)
        out["merges"] = list(host.merges)
        out["base"] = (await shop.base(pid), shop.incoming)
        out["twice"] = await _fuse(kernel, pid, oid, head)
        out["person"] = kernel.mind.frame().state("projects").projects[pid].owner
        return out

    out = live(tmp_path, scenario)
    assert out["ready"] == (12, PULL_OPEN, c.PULL_READY, "")
    assert not out["fresh"].ok and out["fresh"].message == inspect_merge.BLOCK_WORDS[merge.UNCHECKED]
    assert not out["stranger"].ok and out["stranger"].message == inspect_merge.NOT_YOURS
    assert not out["unnamed"].ok and out["unnamed"].errors == {"head": "valeur requise"}
    assert not out["moved_here"].ok and "a bougé depuis ce que tu as lu" in out["moved_here"].message
    assert not out["moved_there"].ok and "Chez l'hôte" in out["moved_there"].message
    assert not out["host_says_no"].ok and out["host_says_no"].message == inspect_merge.BLOCK_WORDS[merge.CONFLICTS]
    assert out["nothing_asked"] == (0, [])  # aucun de ces refus n'a rien écrit ni rien fait partir
    # le refus de l'hôte au moment de fusionner
    assert out["asked"].ok and out["asked"].message == inspect_merge.ASKED
    head = out["asked_event"].sha
    assert out["refused"] == (MERGE_BLOCKED, 0, PULL_OPEN, c.DONE, "", [(URL, 12, head)])
    assert (out["refused_answer"].merged, out["refused_answer"].why) == (False, MERGE_BLOCKED)
    # la fusion : demandée par une personne, pour le commit lu ; apprise par la relecture de l'hôte
    assert out["again"].ok
    asked = out["asked_event"]
    assert (asked.number, asked.branch, len(asked.sha), bool(asked.by)) == (12, "work/objective-2", 40, True)
    assert out["merges"] == [(URL, 12, head), (URL, 12, head)]
    assert out["order"] == (True, True, "d" * 40, PULL_MERGED, True)
    assert out["merged"] == (PULL_MERGED, c.DONE, 1, 0, "", c.STAGE_TREATED, c.DONE)
    assert out["base"][0] == out["base"][1]  # la base se récupère, comme après toute fusion
    assert not out["twice"].ok and out["twice"].message == inspect_merge.BLOCK_WORDS[merge.MERGED]


def test_a_pull_request_is_merged_only_when_it_is_ready():
    p = Project(id=1, title_ref="t", authority=c.USER, created_at=0, remote=URL, flow=c.FLOW_PR)
    o = Objective(id=3, text_ref="t", branch="work/objective-3", pull=12, pull_state=PULL_OPEN, pull_at=5)
    assert merge.blocked(p, o) == ""
    said = {merge.NO_PULL: replace(o, pull_state="", pull=0), merge.PROPOSED: replace(o, pull_state="", pull_proposal=7),
            merge.MERGED: replace(o, pull_state=PULL_MERGED), merge.CLOSED: replace(o, pull_state=PULL_CLOSED),
            merge.UNREAD: replace(o, pull_at=0), merge.ASKED: replace(o, merge_asked_at=9),
            merge.CONFLICTS: replace(o, pull_conflicts=True), merge.CHANGES: replace(o, pull_changes=True),
            merge.RUNNING: replace(o, checks=CHECKS_PENDING, checks_sha="a"), merge.UNSENT: replace(o, unsent=True),
            merge.FAILED: replace(o, checks=CHECKS_FAILED, checks_sha="a")}
    assert {why: merge.blocked(p, x) for why, x in said.items()} == {why: why for why in said}
    # une pull request fraîche dont l'hôte ne dit encore aucune vérification : jugée à l'instant (ADR 0292)
    assert merge.blocked(p, o, 5 + MINUTE) == merge.blocked(p, replace(o, checks=CHECKS_NONE), 5 + MINUTE) \
        == merge.UNCHECKED
    assert merge.blocked(p, o, 5 + merge.CHECKS_GRACE_US) == "" == merge.blocked(
        p, replace(o, checks=CHECKS_PASSED, checks_sha="a"), 5 + MINUTE)
    assert {*said, merge.UNCHECKED} == set(merge.BLOCKS) == set(inspect_merge.BLOCK_WORDS)  # chacune a ses mots
    assert merge.blocked(p, replace(o, checks=CHECKS_PASSED, checks_sha="a")) == ""
    assert merge.blocked(replace(p, flow=c.FLOW_DIRECT), o) == merge.blocked(replace(p, status=c.ARCHIVED), o) \
        == merge.NO_PULL
    assert MERGE_CUT in inspect_merge.REFUSED_WORDS and MERGE_BLOCKED in inspect_merge.REFUSED_WORDS


@needs_bwrap
def test_an_interrupted_merge_is_never_replayed_and_a_stale_one_never_leaves(tmp_path):
    async def scenario(kernel, shop, host):
        merging(host)
        host.says = Pull(number=12, state=PULL_OPEN, head="work/objective-1", base="main")
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page", remote=URL, reread="never",
                           **NO_RUN)
        p = kernel.mind.frame().state("projects").projects[pid]
        o = replace(p.objectives[0], pull=12, branch="work/objective-1")
        ask = merge.asking(p, o, "a" * 40, "user_1")
        # la pull request n'est pas ouverte dans l'état : la demande n'est plus celle qu'une personne a vue
        await kernel.mind.append([ask], emitter="projects", correlation="t")
        await wait(1)
        stale = events(kernel, MERGE_ANSWERED)[-1].data
        cut = merge._cut(events(kernel, MERGE_ASKED)[-1], kernel.ports, "délai dépassé")
        return stale, cut, list(host.merges)

    stale, cut, merges = live(tmp_path, scenario)
    assert (stale.merged, stale.why) == (False, "stale") and merges == []
    assert [(d.type.name, d.data.merged, d.data.why) for d in cut] == [(MERGE_ANSWERED.name, False, MERGE_CUT)]


# ── Aucun autre chemin ne fusionne ────────────────────────────────────────


def _mentions(name: str) -> dict[str, set[str]]:
    """Où ce nom apparaît dans le code du moteur : par fichier, les fonctions qui le portent (``""`` : hors de toute
    fonction) — un attribut, un nom, une chaîne, ou la fonction elle-même."""
    out: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owners: dict[int, str] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                for node in ast.walk(fn):
                    owners[id(node)] = fn.name  # la fonction la plus intérieure l'emporte : parcourue en dernier
        for node in ast.walk(tree):
            hit = (isinstance(node, ast.Attribute) and node.attr == name) or \
                (isinstance(node, ast.Name) and node.id == name) or \
                (isinstance(node, ast.Constant) and node.value == name) or \
                (isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name) or \
                (isinstance(node, ast.alias) and node.name == name)
            if hit:
                out.setdefault(str(path.relative_to(SRC)), set()).add(owners.get(id(node), ""))
    return out


@needs_bwrap
def test_only_the_gesture_of_a_person_merges(tmp_path):
    def named(kernel):
        registry = kernel.mind.registry
        emitting = sorted(key for key, spec in registry.actions.items() if MERGE_ASKED.name in spec.emits)
        effects = sorted(spec.type.name for specs in registry.effects.values() for spec in specs
                         if spec.fn.__module__.endswith(".merge"))
        return [*registry.tools, *registry.capabilities], list(registry.processes), emitting, effects

    async def scenario(kernel, shop, host):
        return named(kernel)

    names, processes, emitting, effects = live(tmp_path, scenario)
    # ni outil, ni capacité, ni processus ne porte de quoi fusionner : une seule action, et l'effet de son fait
    assert names and processes and not [n for n in (*names, *processes) if "merge" in n or "fusion" in n]
    assert emitting == [inspect_merge.ACTION] and effects == [MERGE_ASKED.name]
    # le fait n'est écrit que par ``merge.asking``, que seule l'action d'une personne appelle (un décorateur compte
    # pour sa fonction : le réducteur du fait, l'action qui le déclare, l'effet qu'il déclenche)
    assert _mentions("MERGE_ASKED") == {
        "faculties/projects/faculty.py": {"", "_merge_asked"}, "faculties/projects/inspect_merge.py": {"", "_fuse"},
        "faculties/projects/merge.py": {"", "_merge", "asking"}}
    trees = {str(path.relative_to(SRC)): ast.parse(path.read_text("utf-8")) for path in sorted(SRC.rglob("*.py"))}
    # le fait se nomme aussi par sa chaîne — c'est son nom d'événement que le journal porte, pas celui d'une
    # constante : qui le nomme ainsi est compté aussi, et ne fait que le lire (ni brouillon, ni émission)
    named_so = {**_mentions(MERGE_ASKED.name), **_mentions(MERGE_ASKED.name.rsplit(".", 1)[-1])}
    assert MERGE_ASKED.name == "projects.merge_asked" and set(named_so) == {
        "app/domains/projects/__init__.py", "faculties/projects/feed.py", "faculties/projects/faculty.py"}
    writers = [where for where in named_so if where != "faculties/projects/faculty.py" for node in ast.walk(trees[where])
               if isinstance(node, ast.Attribute) and node.attr in ("draft", "emit")]
    assert writers == []
    drafts = [where for where, tree in trees.items() for node in ast.walk(tree)
              if isinstance(node, ast.Attribute) and node.attr == "draft" and isinstance(node.value, ast.Name)
              and node.value.id == "MERGE_ASKED"]
    assert drafts == ["faculties/projects/merge.py"]
    callers = [where for where, tree in trees.items() for node in ast.walk(tree)
               if isinstance(node, ast.Attribute) and node.attr == "asking" and isinstance(node.value, ast.Name)
               and node.value.id == "merge"]
    assert callers == ["faculties/projects/inspect_merge.py"]
    # la méthode du port n'est appelée que par l'effet de ce fait ; ailleurs, elle n'est que déclarée ou implémentée
    assert _mentions("merge_pull") == {
        "adapters/workshop/github.py": {"merge_pull"}, "app/domains/projects/demo_git.py": {"merge_pull"},
        "ports/workshop.py": {"merge_pull"}, "faculties/projects/merge.py": {"_merge"}}


# ── La fusion relit la CI, la base, et ne part qu'une fois (ADR 0292) ─────


def checking(host: Host) -> Host:
    """Le faux hôte apprend à dire les vérifications d'un commit (``checks_say``), et note qu'on les lui a lues."""
    host.checks_say, host.checked = Checks(state=CHECKS_NONE), []

    async def checks(url: str, sha: str) -> Checks:
        host.checked.append(sha)
        return replace(host.checks_say, sha=sha)

    host.checks = checks
    return host


async def _ready(kernel, shop, host) -> tuple[int, int, str]:
    """Un projet par pull requests dont un objectif vient d'aboutir : sa pull request est ouverte chez l'hôte, à
    l'instant — (le projet, l'objectif, le commit au bout de sa branche)."""
    ws = shop.ws
    pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil", remote=URL,
                       reread="never", **NO_RUN)
    await ws.write(pid, "LISEZMOI.md", "# Le site\n")
    await ws.commit(pid, "la base")
    oid = 1
    await _start(kernel, pid, oid)
    await ws.write(pid, "tarifs.html", "un\ndeux\ntrois\n")
    await reach_all(kernel, pid, oid)
    await _report(kernel, pid, oid, "done")
    await wait(3)
    head = await ws._ref(pid, f"refs/heads/{branch_of(_objective(kernel, pid, oid))}")
    host.says = replace(host.says, sha=head, mergeable=True)
    return pid, oid, head


@needs_bwrap
def test_a_merge_waits_for_the_checks_of_a_fresh_commit_then_reads_them_at_the_host(tmp_path):
    async def scenario(kernel, shop, host):
        out: dict = {}
        checking(merging(host))
        pid, oid, head = await _ready(kernel, shop, host)
        o = _objective(kernel, pid, oid)
        # juste après l'envoi : l'hôte dit « aucune vérification » — il ne les a pas encore créées
        out["state"] = (o.pull_state, o.checks, bool(o.pull_at))
        out["fresh"] = await _fuse(kernel, pid, oid, head)
        # … et il se relit à l'écart court, pas dix minutes plus tard : elles tournent, le journal l'apprend dans
        # la minute
        reads = host.reads
        host.checks_say = Checks(state=CHECKS_PENDING)
        await wait(2)
        out["reread_soon"] = host.reads > reads
        out["pending"] = (_objective(kernel, pid, oid).checks, await _fuse(kernel, pid, oid, head))
        host.checks_say = Checks(state=CHECKS_PASSED)
        await wait(12)
        out["passed"] = _objective(kernel, pid, oid).checks
        # le journal les croit passées ; chez l'hôte un nouveau passage tourne, puis échoue, puis il ne répond plus :
        # l'action relit les vérifications du commit de tête, et rien ne part
        host.checks_say = Checks(state=CHECKS_PENDING)
        out["running_there"] = await _fuse(kernel, pid, oid, head)
        host.checks_say = Checks(state=CHECKS_FAILED, failed=("tests",))
        out["failed_there"] = await _fuse(kernel, pid, oid, head)
        host.checks_say = Checks(error="GitHub ne répond pas")
        out["silent_there"] = await _fuse(kernel, pid, oid, head)
        out["checked"] = (head in host.checked, len(events(kernel, MERGE_ASKED)), list(host.merges))
        # la pull request a été reciblée chez l'hôte : elle n'entre plus dans la branche du projet
        host.checks_say = Checks(state=CHECKS_PASSED)
        host.says = replace(host.says, base="develop")
        out["wrong_base"] = await _fuse(kernel, pid, oid, head)
        host.says = replace(host.says, base="main")
        out["merged"] = await _fuse(kernel, pid, oid, head)
        return out

    out = live(tmp_path, scenario)
    assert out["state"][0] == PULL_OPEN and out["state"][1] in ("", CHECKS_NONE) and out["state"][2]
    assert not out["fresh"].ok and out["fresh"].message == inspect_merge.BLOCK_WORDS[merge.UNCHECKED]
    assert out["reread_soon"]
    assert out["pending"][0] == CHECKS_PENDING and not out["pending"][1].ok
    assert out["pending"][1].message == inspect_merge.BLOCK_WORDS[merge.RUNNING]
    assert out["passed"] == CHECKS_PASSED
    assert not out["running_there"].ok and out["running_there"].message == inspect_merge.BLOCK_WORDS[merge.RUNNING]
    assert not out["failed_there"].ok and out["failed_there"].message == inspect_merge.BLOCK_WORDS[merge.FAILED]
    assert not out["silent_there"].ok and "ne dit pas où en sont les vérifications" in out["silent_there"].message
    assert out["checked"] == (True, 0, [])  # relues chez l'hôte, et aucun de ces refus n'a rien fait partir
    assert not out["wrong_base"].ok and "« develop »" in out["wrong_base"].message \
        and "« main »" in out["wrong_base"].message
    assert out["merged"].ok


@needs_bwrap
def test_two_merges_asked_together_leave_once(tmp_path):
    async def scenario(kernel, shop, host):
        checking(merging(host)).checks_say = Checks(state=CHECKS_PASSED)
        pid, oid, head = await _ready(kernel, shop, host)
        await wait(4)
        first, second = await asyncio.gather(_fuse(kernel, pid, oid, head), _fuse(kernel, pid, oid, head))
        asked = len(events(kernel, MERGE_ASKED))
        await wait(3)
        o = _objective(kernel, pid, oid)
        return first, second, asked, list(host.merges), (o.pull_state, o.merge_refused, o.merge_asked_at)

    first, second, asked, merges, state = live(tmp_path, scenario)
    # de deux demandes parties ensemble, une seule s'écrit et une seule part : l'autre n'a rien fait, et l'état ne
    # garde aucun refus alors que la pull request est fusionnée
    assert sorted((first.ok, second.ok)) == [False, True]
    assert asked == 1 and len(merges) == 1
    assert state == (PULL_MERGED, "", 0)


@needs_bwrap
def test_a_lost_answer_says_it_is_not_known_and_the_host_is_read_again_at_once(tmp_path):
    async def scenario(kernel, shop, host):
        checking(merging(host)).checks_say = Checks(state=CHECKS_PASSED)
        pid, oid, head = await _ready(kernel, shop, host)
        await wait(15)  # le rythme ordinaire : une relecture toutes les dix minutes
        host.refuse = MERGE_UNKNOWN  # la demande est partie, sa réponse s'est perdue
        asked = await _fuse(kernel, pid, oid, head)
        reads = host.reads
        await wait(2)
        o = _objective(kernel, pid, oid)
        unsure = (o.merge_refused, merge.unsure(o), merge.merging(o), host.reads > reads)
        # … et elle avait eu lieu : la relecture de l'hôte l'apprend, comme toute fusion
        host.says = replace(host.says, state=PULL_MERGED)
        await wait(2)
        o = _objective(kernel, pid, oid)
        return asked, unsure, (o.pull_state, o.status, o.merge_refused)

    asked, unsure, learnt = live(tmp_path, scenario)
    assert asked.ok
    assert unsure == (MERGE_UNKNOWN, True, False, True)
    assert "On ne sait pas" in inspect_merge.REFUSED_WORDS[MERGE_UNKNOWN]
    assert "n'a pas eu lieu" not in inspect_merge.REFUSED_WORDS[MERGE_UNKNOWN]
    assert learnt == (PULL_MERGED, c.DONE, "")
