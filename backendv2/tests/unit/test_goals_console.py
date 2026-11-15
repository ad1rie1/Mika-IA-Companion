"""La console des buts, par ses intentions.

- la fiche d'un but se lit neuve (inconnu : une note, pas une exception) et
  après qu'il a vécu un pas : en-tête, recherche, résumé, pas, carnet,
  effets, épisodes, atelier (fichiers, changements, historique) ; la fiche
  d'une personne montre ses buts ;
- un opérateur lui confie un projet, le suspend, le reprend, lui donne une
  consigne, le clôt — chaque fois par le moteur d'actions : ses événements
  sont journalisés « extérieurs », l'audit nomme l'opérateur ; un formulaire
  invalide dit ce qui ne va pas champ par champ ; une action qui n'a pas de
  sens (reprendre un but actif) n'est pas offerte ;
- un but suspendu ne fait aucun pas, ne se rappelle pas et son envie ne
  s'use pas ; repris, il repart ;
- une consigne se lit au pas suivant ;
- clore annule sans rien lui faire ressentir ;
- les buts vivants ne se filtrent que par ce qu'un but vivant peut être ;
  un ancien projet se cherche parmi les clos.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from types import SimpleNamespace

import pytest

from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.goals.actions import parse_due
from mika.faculties.goals.faculty import (
    GOAL_AMENDED,
    GOAL_PAUSED,
    GOAL_RESUMED,
    GOALS,
    Goal,
    GoalsState,
    _set,
    desire,
    params,
)
from mika.faculties.goals.inspect import _steps_tab
from mika.kernel.clock import HOUR, MINUTE, US, instant, local
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Code,
    Disclosure,
    Fields,
    Found,
    Grid,
    Head,
    InspectContext,
    Meter,
    Note,
    Prose,
    Ref,
    Row,
    Section,
    Table,
    Text,
    Timeline,
    Toolbar,
)
from mika.ports.workshop import OutsideWorkshop, RunResult
from mika.runtime.effects import with_content
from mika.runtime.inspection import Inspection
from mika.runtime.operations import offered, perform
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from mika.vocab.episodes import Kind, goal_target
from tests.fixtures.mika import PARIS, at_paris, boot, build, connect

MONDAY = at_paris(2026, 9, 28, 14, 0)


# ── Un atelier en mémoire ─────────────────────────────────────────────────


class Atelier:
    """Le port d'atelier, sans bubblewrap : des fichiers en mémoire, un
    historique à la git (le titre d'un pas, comme l'adaptateur le forme)."""

    def __init__(self) -> None:
        self.files: dict[int, dict[str, str]] = {}
        self.dirty: dict[int, list[str]] = {}
        self.commits: dict[int, list[tuple[str, str]]] = {}

    def exists(self, goal: int) -> bool:
        return goal in self.files

    async def tree(self, goal: int, path: str = ".") -> list[str]:
        return [f"{p} ({len(t.encode())} o)" for p, t in sorted(self.files.get(goal, {}).items())]

    async def read(self, goal: int, path: str) -> str:
        return self.files[goal][path]

    async def write(self, goal: int, path: str, content: str) -> str:
        self.files.setdefault(goal, {})[path] = content
        self.dirty.setdefault(goal, []).append(path)
        self.commits.setdefault(goal, [("a000000", "atelier ouvert")])
        return path

    async def edit(self, goal: int, path: str, old: str, new: str) -> str:
        return await self.write(goal, path, self.files[goal][path].replace(old, new))

    async def write_bytes(self, goal: int, path: str, data: bytes) -> str:
        if ".." in path.split("/") or path.startswith("/"):
            raise OutsideWorkshop(f"hors de l'atelier : {path}")
        return await self.write(goal, path, data.decode("latin-1"))

    async def read_bytes(self, goal: int, path: str, limit: int) -> bytes:
        return self.files[goal][path].encode("latin-1")[:limit]

    async def run(self, goal: int, argv, *, timeout_s=None, network: bool = False) -> RunResult:
        return RunResult(tuple(argv), 0, stdout="tests : ok\n")

    async def commit(self, goal: int, message: str) -> str:
        if not self.dirty.get(goal):
            return ""
        sha = f"c{len(self.commits[goal]):06d}"
        self.commits[goal].append((sha, re.sub(r"\s+", " ", message).strip()[:72]))
        self.dirty[goal] = []
        return sha

    async def diff(self, goal: int) -> str:
        return "".join(f"+++ b/{p}\n+{self.files[goal][p][:40]}\n" for p in self.dirty.get(goal, []))

    async def log(self, goal: int, n: int = 10, *, offset: int = 0) -> str:
        rows = list(reversed(self.commits.get(goal, [])))[offset:offset + n]
        return "\n".join(f"{sha} {title}" for sha, title in rows)


# ── Outils ────────────────────────────────────────────────────────────────


def form(unchecked: tuple[str, ...] = (), **values: str) -> dict[str, list[str]]:
    """Une soumission : chaque champ rendu (``_champs``) ; une case décochée n'est pas envoyée."""
    return {"_champs": [*values, *unchecked], **{k: [v] for k, v in values.items()}}


def events(kernel, *types) -> list:
    mind = kernel.mind
    names = {t.name for t in types}
    return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type in names]


def nested(blocks) -> list:
    """Les blocs, et ceux qu'ils contiennent (cartes, sections, détails dépliables), dans l'ordre."""
    out: list = []
    for b in blocks:
        out.append(b)
        if isinstance(b, (Grid, Section, Disclosure, Toolbar)):
            out += nested(b.items)
    return out


def flat(blocks: list[Block]) -> str:
    out: list[str] = []

    def cell(v) -> str:
        if isinstance(v, (Ref, Text, Badge, Meter)):
            return v.text
        return "" if v is None else str(v)

    for b in nested(blocks):
        if isinstance(b, Table):
            out += [b.title, *(cell(v) for r in b.rows for v in (r.cells if isinstance(r, Row) else r))]
            if not b.rows:
                out.append(b.empty)
        elif isinstance(b, Fields):
            out += [b.title, *(f"{k} : {cell(v)}" for k, v in b.pairs)]
        elif isinstance(b, Timeline):
            out += [b.title, *(f"{e.title} · {e.text} · {e.meta}" for e in b.entries)]
            if not b.entries:
                out.append(b.empty)
        elif isinstance(b, (Note, Code, Prose)):
            out.append(b.text)
        elif isinstance(b, (Section, Disclosure)):
            out.append(b.title)
    return "\n".join(out)


def field(blocks: list[Block], name: str):
    for b in nested(blocks):
        if isinstance(b, Fields):
            for k, v in b.pairs:
                if k == name:
                    return v
    raise KeyError(name)


def table(blocks: list[Block], title: str) -> Table:
    return next(b for b in blocks if isinstance(b, Table) and b.title == title)


async def tab(kernel, name: str, subject: str, **params: str) -> list[Block]:
    ins = Inspection(kernel)
    spec = ins.find("goals", name)
    assert spec is not None, name
    blocks = await ins.arun(spec, params, subject=subject)
    failed = [b.text for b in blocks if isinstance(b, Note) and b.text.startswith("Cette vue a échoué")]
    assert not failed, failed
    return blocks


def live(tmp_path, scenario, *, mode: str = "liar", start: int = MONDAY, ports=None):
    clock = SimClock(start)
    llm = PersonaSimLLM(clock, seed=1, abstain_rate=0.0, latency=2.0)
    llm.step_mode = mode
    kernel, clock, _, _ = build(tmp_path, None, clock=clock, llm=llm, ports=ports or {})

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, llm)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def explore(kernel, title: str = "Explorer : les jeux rétro", *, desire_: float = 1.0,
                  origin: str = goals_c.FROM_EXCHANGE) -> int:
    # une réflexion (ce qu'on lui a confié) : une séance s'y prouve en écrivant ce qu'elle en pense ; une
    # exploration née d'un signal (``FROM_SIGNAL``) peut, elle, bloquer (une réflexion en reste là, ADR 0053)
    commit = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
        kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of(title, level=0), bundles=("goals",),
        max_steps=8, source="genese", sensitivity=0, desire=desire_, origin=origin)],
        emitter="goals", correlation="genese", origin=Origin.GENESIS)
    return commit.seqs[-1]


def steps_of(kernel, gid: int) -> list:
    return [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == "STEP" and e.data.target == f"goal:{gid}"]


# ── L'échéance tapée à la main ────────────────────────────────────────────


def test_a_due_date_is_read_the_french_way_and_refused_when_unreadable():
    now = at_paris(2026, 9, 28, 14, 0)
    expected = instant(datetime(2026, 10, 2, 18, 0, tzinfo=PARIS))
    for text in ("2026-10-02 18:00", "2026-10-02T18:00", "2026-10-02 18h", "02/10/2026 18:00", "02/10/2026 à 18h00",
                 "02/10 18h", "2026-10-02"):
        assert parse_due(text, PARIS, now) == expected, text
    assert parse_due("02/10/26 18h", PARIS, now) == expected
    assert local(parse_due("15/09 9h", PARIS, now), PARIS).year == 2027  # sans année et passé : l'an prochain
    for text, why in (("demain soir", "illisible"), ("2026-02-30 10:00", "n'existe pas"),
                      ("2026-09-01 10:00", "déjà passée"), ("2035-01-01", "trop loin"), ("2026-10-02 25:00", "n.existe pas")):
        with pytest.raises(ValueError, match=why):
            parse_due(text, PARIS, now)


# ── Buts vivants, clos : leurs filtres ────────────────────────────────────


def kinds_offered(view: str) -> dict[str, str]:
    spec = next(s for s in GOALS.inspectors if s.name == view)
    return dict(next(p for p in spec.typed if p.name == "sorte").choices)


def test_live_goals_are_filtered_only_by_what_a_live_goal_can_be():
    # un ancien projet encore vivant est clos à la première passe de tend : parmi les vivants, rien à trouver
    assert kinds_offered("vivants") == {goals_c.REMINDER: "rappel", goals_c.EXPLORATION: "exploration"}
    # un vieux journal garde ses anciens projets parmi les clos
    assert kinds_offered("clos")[goals_c.PROJECT] == "ancien projet"


# ── La fiche d'un but ─────────────────────────────────────────────────────


def test_a_goal_is_found_with_or_without_its_ligature(tmp_path):
    """« coeur » trouve « cœur » : le repli du noyau, le même que celui de sa mémoire (audit K0-15)."""

    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        gid = str(await explore(kernel, "Explorer : le cœur des vieilles bornes"))
        return gid, {typed: ins.search("goal", typed) for typed in ("coeur", "CŒUR", "tricot")}

    gid, found = live(tmp_path, scenario, mode="honest")
    assert [f.key for f in found["coeur"]] == [gid] and [f.key for f in found["CŒUR"]] == [gid]
    assert found["tricot"] == []


def test_the_goal_fiche_fresh_then_after_an_exploration_lived_a_step(tmp_path):
    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        fresh = {
            "head": ins.head("goal", "1"), "search": ins.search("goal", ""),
            "tabs": [v.name for v in ins.tabs("goal")], "person_tabs": [v.name for v in ins.tabs("person")],
            "unknown": await tab(kernel, "resume", "999"), "nowhere": await tab(kernel, "seances", ""),
            "vivants": await tab(kernel, "vivants", ""), "clos": await tab(kernel, "clos", ""),
        }
        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = str(await explore(kernel, "Explorer : les jeux rétro"))
        opened = {"head": ins.head("goal", gid), "vivants": await tab(kernel, "vivants", ""),
                  "politique": await tab(kernel, "politique", gid), "by_number": ins.search("goal", f"#{gid}"),
                  "by_title": ins.search("goal", "RÉTRO"), "none": ins.search("goal", "tricot")}
        for _ in range(3 * 60):
            if events(kernel, goals_c.STEP_REPORTED):
                break
            await asyncio.sleep(MINUTE / US)
        await kernel.lanes.join()
        after = {name: await tab(kernel, name, gid) for name in ("resume", "seances", "carnet", "decisions")}
        after["head"] = ins.head("goal", f"#{gid}")
        after["clos"] = await tab(kernel, "clos", "")
        return fresh, opened, after, gid, events(kernel, goals_c.STEP_REPORTED)

    fresh, opened, after, gid, reported = live(tmp_path, scenario, mode="honest")
    # neuve : rien, et le dit
    assert fresh["head"] is None and fresh["search"] == []
    # un seul onglet pour ses séances : chacune, avec son compte rendu et de quoi relire son prompt (audit K5-12)
    assert fresh["tabs"] == ["resume", "politique", "seances", "carnet", "decisions"]
    assert "buts" in fresh["person_tabs"] and "projets" in fresh["person_tabs"]
    assert "Aucun but « 999 »" in flat(fresh["unknown"]) and fresh["unknown"][0].tone == "warn"
    assert "fiche d'un but" in flat(fresh["nowhere"])
    assert "aucun but en cours" in flat(fresh["vivants"]) and "aucun but clos" in flat(fresh["clos"])
    # ouverte d'elle-même : son en-tête, la liste des vivants, la recherche
    head = opened["head"]
    assert isinstance(head, Head) and head.key == gid and head.title == "Explorer : les jeux rétro"
    assert [b.text for b in head.badges] == ["exploration", "à elle", "en cours"]
    facts = dict(head.facts)
    assert facts["avancement"].text == "0 / 8 séances" and isinstance(facts["envie"], Meter)
    assert facts["prochaine séance"] == "dès que possible"
    assert head.default_tab == "resume"
    row = table(opened["vivants"], "Buts vivants").rows[0]
    assert isinstance(row, Row) and row.href == Ref.subject("goal", gid, f"#{gid}")
    assert [f.key for f in opened["by_number"]] == [gid] and [f.key for f in opened["by_title"]] == [gid]
    assert isinstance(opened["by_title"][0], Found) and "exploration" in opened["by_title"][0].subtitle
    assert opened["none"] == []
    # ses réglages : on la pilote (sa priorité), on ne la réécrit pas
    policy = opened["politique"]
    assert "ne se réécrit pas" in flat(policy) and any(isinstance(b, ActionSlot) and b.action == "goals.priorite"
                                                       for b in policy)
    assert "Son rythme" in flat(policy) and "Quand elle s'arrête" in flat(policy)
    # après une séance (cherchée, notée, finie avec preuve) : chaque onglet le dit
    assert reported and reported[0].data.proven
    assert after["head"].key == gid  # « #12 » : la fiche canonique
    resume = after["resume"]
    assert field(resume, "titre") == "Explorer : les jeux rétro" and field(resume, "statut").text == "abouti"
    assert field(resume, "d'où il vient") == "genese"
    pas = table(after["seances"], "Ses séances")
    assert field(after["seances"], "séances faites")  # « Où il en est », en tête
    worked = next(r for r in pas.rows if r.cells[1] == "séance de travail")
    assert [c.text for c in worked.cells[4:6]] == ["fini", "prouvé"]
    assert "goal_reflect" in worked.cells[7]  # ce qui a prouvé
    assert worked.href == Ref("episode", reported[0].correlation, "")
    assert worked.cells[9] == "1" == str(sum(r.correlation == worked.href.key for r in reported))  # « comptes rendus »
    assert worked.cells[10].params == (("onglet", "prompt"),) and worked.cells[13].params == (("onglet", "decision"),)
    assert (worked.cells[3].text, worked.cells[3].tone) == ("terminé", "ok")  # les mots de la page Épisodes
    assert "En y repensant" in flat(after["carnet"])
    decided = table(after["decisions"], "Ce que l'arbitre en a pensé").rows
    assert decided and any(r.cells[1].text == "choisi" for r in decided) and decided[0].detail
    closed = table(after["clos"], "Buts clos")
    assert closed.rows[0].cells[0] == Ref.subject("goal", gid, f"#{gid}") and closed.rows[0].cells[4].text == "abouti"


def test_the_goal_episodes_say_their_outcome_with_the_words_of_the_episodes_page():
    """L'onglet des séances d'un but dit l'issue de chaque épisode comme la page Épisodes : une séance trop longue
    est « trop longue » (pas « délai dépassé »), un récit d'elle mené à bien « a parlé » (pas « fait »), et une séance
    qui n'a pas fini est « en cours » (audit K5-06)."""
    done = Goal(id=1, kind=goals_c.EXPLORATION, authority=goals_c.SELF, title_ref="t", opened_at=0,
                status=goals_c.ACHIEVED, notable=0.9, owner="user_1")
    started = [  # du plus récent au plus ancien, comme le journal les rend
        SimpleNamespace(seq=3, correlation="s3", at=MONDAY + 3 * HOUR, data=rt.EpisodeStarted(
            kind=Kind.STEP, target=goal_target(1), reason=goals_c.WORK)),
        SimpleNamespace(seq=2, correlation="i2", at=MONDAY + 2 * HOUR, data=rt.EpisodeStarted(
            kind=Kind.INITIATIVE, target="user_1", reason=goals_c.SHARE, subject=goal_target(1))),
        SimpleNamespace(seq=1, correlation="s1", at=MONDAY + HOUR, data=rt.EpisodeStarted(
            kind=Kind.STEP, target=goal_target(1), reason=goals_c.WORK)),
    ]
    ended = {"i2": rt.EpisodeEnded(kind=Kind.INITIATIVE, outcome="done", target="user_1"),
             "s1": rt.EpisodeEnded(kind=Kind.STEP, outcome="timeout", target=goal_target(1))}

    def journal(names, limit, *, where=None, before=None, correlations=None):
        if names == [rt.EPISODE_STARTED.name]:
            field_, value = where
            return [e for e in started if getattr(e.data, field_) == value][:limit]
        if names == [rt.EPISODE_ENDED.name]:
            return [SimpleNamespace(correlation=c, data=ended[c]) for c in correlations or () if c in ended]
        assert names == [goals_c.STEP_REPORTED.name]
        return []

    frame = SimpleNamespace(get=lambda fact: SimpleNamespace(name="Adrien"))
    blocks = _steps_tab(_set(GoalsState(), done), frame, InspectContext(store=None, ports={}, journal=journal,
                                                                        subject="1"))
    issues = [(r.cells[3].text, r.cells[3].tone) for r in table(blocks, "Ses séances").rows]
    assert issues == [("en cours", "info"), ("a parlé", "ok"), ("trop long", "danger")]


def test_the_goal_sessions_tab_gives_each_episode_its_report():
    """Un seul onglet « Séances » (audit K5-12) : une ligne par épisode du but, la séance avec son compte rendu
    (verdict, preuve, résumé, outils, notable), la parole et la séance en cours avec « — » à sa place ; en détail, de
    quoi relire chacune (prompt, outils, appels, décision)."""
    done = Goal(id=1, kind=goals_c.EXPLORATION, authority=goals_c.SELF, title_ref="t", opened_at=0,
                status=goals_c.ACTIVE, notable=0.9, owner="user_1", steps=1, max_steps=8)
    started = [  # du plus récent au plus ancien, comme le journal les rend
        SimpleNamespace(seq=3, correlation="s3", at=MONDAY + 3 * HOUR, data=rt.EpisodeStarted(
            kind=Kind.STEP, target=goal_target(1), reason=goals_c.WORK)),
        SimpleNamespace(seq=2, correlation="i2", at=MONDAY + 2 * HOUR, data=rt.EpisodeStarted(
            kind=Kind.INITIATIVE, target="user_1", reason=goals_c.SHARE, subject=goal_target(1))),
        SimpleNamespace(seq=1, correlation="s1", at=MONDAY + HOUR, data=rt.EpisodeStarted(
            kind=Kind.STEP, target=goal_target(1), reason=goals_c.WORK)),
    ]
    ended = {"i2": rt.EpisodeEnded(kind=Kind.INITIATIVE, outcome="done", target="user_1"),
             "s1": rt.EpisodeEnded(kind=Kind.STEP, outcome="done", target=goal_target(1))}
    reported = {"s1": goals_c.StepReported(goal=1, verdict=goals_c.DONE, summary=Content.of("Trois consoles listées"),
                                           notable=0.7, proven=True, tools=("goal_reflect", "goal_note"))}

    def journal(names, limit, *, where=None, before=None, correlations=None):
        if names == [rt.EPISODE_STARTED.name]:
            field_, value = where
            return [e for e in started if getattr(e.data, field_) == value][:limit]
        if names == [rt.EPISODE_ENDED.name]:
            return [SimpleNamespace(correlation=c, data=ended[c]) for c in correlations or () if c in ended]
        assert names == [goals_c.STEP_REPORTED.name] and where is None  # lu par corrélation, pas à part
        return [SimpleNamespace(correlation=c, data=reported[c]) for c in correlations or () if c in reported]

    frame = SimpleNamespace(get=lambda fact: SimpleNamespace(name="Adrien"))
    blocks = _steps_tab(_set(GoalsState(), done), frame, InspectContext(store=None, ports={}, journal=journal,
                                                                        subject="1"))
    assert field(blocks, "séances faites") == "1 / 8"  # « Où il en est » d'abord
    sessions = table(blocks, "Ses séances")
    assert [c.label for c in sessions.columns] == [
        "quand", "épisode", "vers", "issue", "verdict", "preuve", "résumé", "outils utilisés", "notable",
        "comptes rendus", "prompt", "outils", "appels", "décision"]
    assert [c.label for c in sessions.columns if c.detail] == [
        "vers", "comptes rendus", "prompt", "outils", "appels", "décision"]
    current, told, worked = sessions.rows
    assert [r.cells[1] for r in sessions.rows] == ["séance de travail", "raconter", "séance de travail"]
    assert told.cells[2] == "Adrien" and worked.cells[2] == "—"  # « vers » : qui elle visait en en parlant
    # la séance : son compte rendu
    assert [c.text for c in worked.cells[4:7]] == ["fini", "prouvé", "Trois consoles listées"]
    assert worked.cells[7] == "goal_reflect, goal_note" and worked.cells[8] == "0,7" and worked.cells[9] == "1"
    # une parole, une séance en cours : pas de compte rendu
    assert told.cells[4:10] == ("—",) * 6 and current.cells[4:10] == ("—",) * 6
    # chaque ligne mène à son épisode, et en détail à de quoi le relire
    for row in sessions.rows:
        corr = row.href.key
        assert row.href == Ref("episode", corr, "")
        assert [(r.key, r.params) for r in row.cells[10:14]] == [
            (corr, (("onglet", "prompt"),)), (corr, (("onglet", "outils"),)), (corr, (("onglet", "appels"),)),
            (corr, (("onglet", "decision"),))]
    assert sessions.caption.startswith("« prompt »")


def test_a_session_that_reported_more_than_once_shows_its_last_report_and_all_of_them():
    """Relecture de K5-12 : un « fini » sans preuve est noté (``STEP_REPORTED``) sans clore la séance, qui peut rendre
    compte encore, jusqu'au plafond de l'outil. Le journal les rend du plus récent au plus ancien : la ligne montre le
    dernier (« fini · prouvé », pas le premier « sans preuve »), le détail les dit tous, et la page lit ceux de tous ses
    épisodes — une lecture bornée à un compte rendu par épisode coupait ceux des plus anciens, montrés « — »."""
    g = Goal(id=1, kind=goals_c.EXPLORATION, authority=goals_c.SELF, title_ref="t", opened_at=0,
             status=goals_c.ACHIEVED, notable=0.9, owner="user_1", steps=3, max_steps=8, unproven=3)
    step = Kind.STEP

    def started_(seq, corr):
        return SimpleNamespace(seq=seq, correlation=corr, at=MONDAY + seq * HOUR, data=rt.EpisodeStarted(
            kind=step, target=goal_target(1), reason=goals_c.WORK))

    started = [started_(3, "s3"), started_(2, "s2"), started_(1, "s1")]

    def report(seq, corr, verdict, proven=False, summary="noté"):
        return SimpleNamespace(seq=seq, correlation=corr, data=goals_c.StepReported(
            goal=1, verdict=verdict, summary=Content.of(summary), proven=proven))

    reports = [  # trois pour la plus récente, deux pour la suivante, un pour la plus ancienne
        report(36, "s3", goals_c.DONE, proven=True, summary="Liste prouvée"),
        report(35, "s3", goals_c.DONE), report(34, "s3", goals_c.DONE),
        report(25, "s2", goals_c.CONTINUE), report(24, "s2", goals_c.DONE),
        report(14, "s1", goals_c.CONTINUE, summary="Un premier tri"),
    ]

    def journal(names, limit, *, where=None, before=None, correlations=None):
        if names == [rt.EPISODE_STARTED.name]:
            field_, value = where
            return [e for e in started if getattr(e.data, field_) == value][:limit]
        if names == [rt.EPISODE_ENDED.name]:
            return [SimpleNamespace(correlation=c, data=rt.EpisodeEnded(kind=step, outcome="done",
                                                                         target=goal_target(1)))
                    for c in correlations or ()][:limit]
        assert names == [goals_c.STEP_REPORTED.name]
        # comme le journal : du plus récent au plus ancien, toutes corrélations mêlées, et borné
        return [e for e in reports if e.correlation in (correlations or ())][:limit]

    frame = SimpleNamespace(get=lambda fact: SimpleNamespace(name="Adrien"))
    sessions = table(_steps_tab(_set(GoalsState(), g), frame,
                                InspectContext(store=None, ports={}, journal=journal, subject="1")), "Ses séances")
    last, middle, first = sessions.rows
    # la dernière séance : « fini » sans preuve deux fois, puis prouvé ; la ligne dit le dernier
    assert [c.text for c in last.cells[4:7]] == ["fini", "prouvé", "Liste prouvée"]
    assert last.cells[9] == "3 : fini · sans preuve, puis fini · sans preuve, puis fini · prouvé"
    # « fini » sans preuve, puis « continuer » : la séance continue, sans preuve à dire
    assert last.cells[4].tone == "ok" and middle.cells[4].text == "continuer" and middle.cells[5] == "—"
    assert middle.cells[9] == "2 : fini · sans preuve, puis continuer"
    # la plus ancienne de la page a bien rendu compte : pas de « — » comme une parole
    assert [c.text for c in first.cells[4:7:2]] == ["continuer", "Un premier tri"] and first.cells[9] == "1"


# ── Les actions de l'opérateur ────────────────────────────────────────────


def test_every_operator_action_goes_through_the_engine(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        out = {}
        gid = str(await explore(kernel, "Explorer : les jeux rétro"))
        spec = kernel.registry.actions
        out["offered_active"] = {k: offered(kernel, spec[f"goals.{k}"], gid)
                                 for k in ("pause", "reprendre", "consigne", "clore")}
        out["resume_active"] = await perform(kernel, "goals.reprendre", form(), by="user_1", subject=gid, nonce="n4")
        out["no_subject"] = await perform(kernel, "goals.pause", form(), by="user_1", nonce="n5")
        out["pause"] = await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="n6")
        out["again"] = await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="n6")
        out["offered_paused"] = {k: offered(kernel, spec[f"goals.{k}"], gid)
                                 for k in ("pause", "reprendre", "consigne", "clore")}
        out["status_paused"] = kernel.mind.frame().get(goals_c.STATUS(int(gid)))
        out["live_paused"] = [g.status for g in kernel.mind.frame().get(goals_c.LIVE)]
        out["empty_order"] = await perform(kernel, "goals.consigne", form(instruction="   "), by="user_1",
                                           subject=gid, nonce="n7")
        out["order"] = await perform(kernel, "goals.consigne", form(instruction="Ne regarde que les années 90."),
                                     by="user_1", subject=gid, nonce="n8")
        out["resume"] = await perform(kernel, "goals.reprendre", form(), by="user_1", subject=gid, nonce="n9")
        esteem = kernel.mind.frame().get(self_c.ESTEEM)
        out["close"] = await perform(kernel, "goals.clore", form(), by="user_1", subject=gid, nonce="n10")
        out["esteem"] = (esteem, kernel.mind.frame().get(self_c.ESTEEM))
        out["offered_closed"] = {k: offered(kernel, spec[f"goals.{k}"], gid)
                                 for k in ("pause", "reprendre", "consigne", "clore")}
        out["unknown"] = offered(kernel, spec["goals.pause"], "999") or offered(kernel, spec["goals.pause"], "abc")
        out["events"] = {t.name: events(kernel, t) for t in (GOAL_PAUSED, GOAL_RESUMED, GOAL_AMENDED,
                                                              goals_c.GOAL_CLOSED, rt.OPERATED)}
        out["carnet"] = await tab(kernel, "carnet", gid)
        out["resume_tab"] = await tab(kernel, "resume", gid)
        out["gid"] = gid
        return out

    out = live(tmp_path, scenario)
    ev = out["events"]
    assert out["offered_active"] == {"pause": True, "reprendre": False, "consigne": True, "clore": True}
    assert not out["resume_active"].ok and "pas possible" in out["resume_active"].message
    assert not out["no_subject"].ok
    assert out["pause"].ok and not out["again"].ok  # déjà en pause : le second envoi ne refait rien
    assert out["status_paused"] == goals_c.PAUSED and out["live_paused"] == [goals_c.PAUSED]
    assert out["offered_paused"] == {"pause": False, "reprendre": True, "consigne": True, "clore": True}
    assert not out["empty_order"].ok and "instruction" in out["empty_order"].errors
    assert out["order"].ok and out["resume"].ok and out["close"].ok
    assert out["offered_closed"] == {"pause": False, "reprendre": False, "consigne": False, "clore": False}
    assert not out["unknown"]
    for t in (GOAL_PAUSED, GOAL_RESUMED, GOAL_AMENDED, goals_c.GOAL_CLOSED):
        [e] = ev[t.name]
        assert e.origin is Origin.EXTERNAL and e.correlation.startswith("opérateur:goals.")
        assert e.data.goal == int(out["gid"])
    assert ev[GOAL_AMENDED.name][0].data.instruction.text == "Ne regarde que les années 90."
    assert ev[GOAL_AMENDED.name][0].data.by == "user_1" and ev[GOAL_PAUSED.name][0].data.by == "user_1"
    closed = ev[goals_c.GOAL_CLOSED.name][0].data
    assert closed.status == goals_c.CANCELLED and "opérateur" in closed.reason
    assert out["esteem"][0] == out["esteem"][1]  # annuler ne lui fait rien ressentir
    audit = {(e.data.action, e.data.outcome) for e in ev[rt.OPERATED.name]}
    assert {("goals.pause", "done"), ("goals.reprendre", "done"), ("goals.consigne", "done"),
            ("goals.clore", "done")} <= audit
    assert all(e.data.by == "user_1" for e in ev[rt.OPERATED.name])
    assert all(e.data.subject == out["gid"] for e in ev[rt.OPERATED.name] if e.data.action == "goals.pause")
    assert "Ne regarde que les années 90." in flat(out["carnet"]) and "de Adrien" in flat(out["carnet"])
    assert field(out["resume_tab"], "statut").text == "annulé" and field(out["resume_tab"], "consignes reçues") == 1


# ── Suspendre : ni pas, ni rappel, ni usure ───────────────────────────────


def test_a_paused_goal_takes_no_step_and_resumes_afterwards(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = await explore(kernel, desire_=0.8)
        remind = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.REMINDER, authority=goals_c.USER, title=Content.of("sortir le linge", level=2),
            owner="user_1", address="user_1", about=("user_1",), due=kernel.mind.clock.now() + 20 * MINUTE,
            source="tool", sensitivity=2)], emitter="goals", correlation="genese", origin=Origin.GENESIS)
        rid = remind.seqs[-1]
        for key in (gid, rid):
            got = await perform(kernel, "goals.pause", form(), by="user_1", subject=str(key), nonce=f"p{key}")
            assert got.ok, got
        paused_at = kernel.mind.clock.now()
        p = params(kernel.mind.frame().env.params_of("goals", kernel.mind.root))

        def wanted() -> float:
            return desire(kernel.mind.frame().state("goals").goals[gid], kernel.mind.clock.now(), p)

        before = wanted()
        await asyncio.sleep(6 * HOUR / US)
        during = {"steps": [e.at for e in steps_of(kernel, gid) if e.at > paused_at], "desire": wanted(),
                  "reminded": [e for e in events(kernel, rt.EPISODE_STARTED) if goals_c.REMIND in e.data.reason],
                  "closed": events(kernel, goals_c.GOAL_CLOSED),
                  "status": kernel.mind.frame().get(goals_c.STATUS(gid))}
        for key in (gid, rid):
            got = await perform(kernel, "goals.reprendre", form(), by="user_1", subject=str(key), nonce=f"r{key}")
            assert got.ok, got
        resumed_at = kernel.mind.clock.now()
        just_after = wanted()
        await asyncio.sleep(HOUR / US)
        after = {"steps": [e.at for e in steps_of(kernel, gid) if e.at > resumed_at],
                 "reminded": [e for e in events(kernel, rt.EPISODE_STARTED) if goals_c.REMIND in e.data.reason
                              and e.at > resumed_at]}
        return before, during, just_after, after, rid

    before, during, just_after, after, rid = live(tmp_path, scenario)
    assert during["steps"] == []  # six heures de pause : aucun pas
    assert during["desire"] == pytest.approx(before)  # l'envie ne s'use pas en pause
    assert during["reminded"] == [] and during["closed"] == []  # ni rappel dit, ni rappel « trop tard »
    assert during["status"] == goals_c.PAUSED
    assert just_after == pytest.approx(before)  # reprise : elle repart d'où elle était
    assert after["steps"]  # repris, il avance de nouveau
    assert after["reminded"]  # et le rappel se dit (en retard, mais dans la demi-journée)


# ── Une consigne se lit au pas suivant ────────────────────────────────────


def test_an_instruction_reaches_the_next_step_prompt(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = await explore(kernel)
        for _ in range(60):
            if steps_of(kernel, gid):
                break
            await asyncio.sleep(MINUTE / US)
        await kernel.lanes.join()
        got = await perform(kernel, "goals.consigne", form(instruction="Ne regarde que les jeux des années 90."),
                            by="user_1", subject=str(gid), nonce="c1")
        assert got.ok, got
        issued = len(llm.calls)
        for _ in range(2 * 60):
            if any(c.role == "step" for c in llm.calls[issued:]):
                break
            await asyncio.sleep(MINUTE / US)
        before = [c for c in llm.calls[:issued] if c.role == "step"]
        after = [c for c in llm.calls[issued:] if c.role == "step"]
        return before, after

    before, after = live(tmp_path, scenario)

    def prompt(req) -> str:
        return "\n".join([req.system_stable, *(m.content for m in req.messages)])

    assert before and after
    assert all("années 90" not in prompt(r) for r in before)
    text = prompt(after[0])
    assert "Consignes reçues depuis (à suivre ; la plus récente prime) :\n- Ne regarde que les jeux des années 90." \
        in text


def test_the_badges_say_what_needs_the_operator(tmp_path):
    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        views = {v.name: v for v in ins.in_section("buts")}
        await connect(kernel, "user_1", "Adrien", operator=True)
        remind = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.REMINDER, authority=goals_c.USER, title=Content.of("sortir le linge", level=2),
            owner="user_1", address="user_1", about=("user_1",), due=kernel.mind.clock.now() + 20 * MINUTE,
            source="tool", sensitivity=2)], emitter="goals", correlation="t", origin=Origin.GENESIS)
        await kernel.mind.append([goals_c.GOAL_CLOSED.draft(
            goal=remind.seqs[-1], status=goals_c.FAILED, kind=goals_c.REMINDER, authority=goals_c.USER,
            title=Content.of("sortir le linge"), reason="pas pu le dire")], emitter="goals", correlation="t",
            origin=Origin.GENESIS)
        return list(views), ins.badge(views["clos"])

    names, stuck = live(tmp_path, scenario)
    assert names == ["vivants", "clos"]  # ses projets ont leur menu à eux
    assert stuck == (1, "confiés : bloqués ou en échec")
