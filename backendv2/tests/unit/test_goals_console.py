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
- clore annule sans rien lui faire ressentir.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import pytest

from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.goals.actions import parse_due
from mika.faculties.goals.faculty import GOAL_AMENDED, GOAL_PAUSED, GOAL_RESUMED, desire, params
from mika.kernel.clock import HOUR, MINUTE, US, instant, local
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import (
    Badge,
    Block,
    Code,
    Fields,
    Found,
    Head,
    Meter,
    Note,
    Ref,
    Row,
    Table,
    Text,
    Timeline,
)
from mika.ports.workshop import RunResult
from mika.runtime.effects import with_content
from mika.runtime.inspection import Inspection
from mika.runtime.operations import offered, perform
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
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


def flat(blocks: list[Block]) -> str:
    out: list[str] = []

    def cell(v) -> str:
        if isinstance(v, (Ref, Text, Badge, Meter)):
            return v.text
        return "" if v is None else str(v)

    for b in blocks:
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
        elif isinstance(b, (Note, Code)):
            out.append(b.text)
    return "\n".join(out)


def field(blocks: list[Block], name: str):
    for b in blocks:
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


async def explore(kernel, title: str = "Explorer : les jeux rétro", *, desire_: float = 1.0) -> int:
    commit = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
        kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of(title, level=0), bundles=("goals",),
        max_steps=8, source="genese", sensitivity=0, desire=desire_)], emitter="goals", correlation="genese",
        origin=Origin.GENESIS)
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


# ── La fiche d'un but ─────────────────────────────────────────────────────


def test_the_goal_fiche_fresh_then_after_a_project_lived_a_step(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        fresh = {
            "head": ins.head("goal", "1"), "search": ins.search("goal", ""),
            "tabs": [v.name for v in ins.tabs("goal")], "person_tabs": [v.name for v in ins.tabs("person")],
            "unknown": await tab(kernel, "resume", "999"), "nowhere": await tab(kernel, "pas", ""),
            "atelier": await tab(kernel, "atelier", "12"),
            "vivants": await tab(kernel, "vivants", ""), "clos": await tab(kernel, "clos", ""),
            "projets": await tab(kernel, "projets", ""),
        }
        await connect(kernel, "user_1", "Adrien", operator=True)
        got = await perform(kernel, "goals.confier", form(title="Un script de bonjour",
                                                          details="Écrire bonjour.py et le tester.",
                                                          due="2026-10-02 18:00"), by="user_1", nonce="c1")
        assert got.ok, got
        gid = str(events(kernel, goals_c.GOAL_OPENED)[-1].seq)
        opened = {"head": ins.head("goal", gid), "vivants": await tab(kernel, "vivants", ""),
                  "projets": await tab(kernel, "projets", ""), "politique": await tab(kernel, "politique", gid),
                  "by_number": ins.search("goal", f"#{gid}"), "by_title": ins.search("goal", "BONJOUR"),
                  "none": ins.search("goal", "tricot")}
        for _ in range(3 * 60):
            if events(kernel, goals_c.STEP_REPORTED):
                break
            await asyncio.sleep(MINUTE / US)
        await kernel.lanes.join()
        after = {name: await tab(kernel, name, gid) for name in ("resume", "pas", "carnet", "effets", "episodes",
                                                               "atelier", "decisions", "projets")}
        after["head"] = ins.head("goal", f"#{gid}")
        after["clos"] = await tab(kernel, "clos", "")
        after["person"] = await ins.arun(next(v for v in ins.tabs("person") if v.owner == "goals"), {},
                                         subject="user_1")
        frame = kernel.mind.frame()
        return fresh, opened, after, gid, events(kernel, goals_c.STEP_REPORTED), frame.env.tz_of(frame.root)

    fresh, opened, after, gid, reported, tz = live(tmp_path, scenario, mode="honest", ports={"workshop": atelier})
    # neuve : rien, et le dit
    assert fresh["head"] is None and fresh["search"] == []
    assert fresh["tabs"] == ["resume", "politique", "pas", "carnet", "effets", "decisions", "episodes", "atelier"]
    assert "aucun projet en cours" in flat(fresh["projets"])
    assert "buts" in fresh["person_tabs"]
    assert "Aucun but « 999 »" in flat(fresh["unknown"]) and fresh["unknown"][0].tone == "warn"
    assert "fiche d'un but" in flat(fresh["nowhere"]) and "Aucun but « 12 »" in flat(fresh["atelier"])
    assert "aucun but en cours" in flat(fresh["vivants"]) and "aucun but clos" in flat(fresh["clos"])
    # ouvert par l'opérateur : son en-tête, la liste des vivants, la recherche
    head = opened["head"]
    assert isinstance(head, Head) and head.key == gid and head.title == "Un script de bonjour"
    assert [b.text for b in head.badges] == ["projet", "confié", "en cours"]
    facts = dict(head.facts)
    assert facts["pas"] == f"0 / {params(None).project_steps}" and facts["envie"].startswith("engagement")
    assert isinstance(facts["pour qui"], Ref) and facts["pour qui"].key == "person/user_1"
    row = table(opened["vivants"], "Buts vivants").rows[0]
    assert isinstance(row, Row) and row.href == Ref.subject("goal", gid, f"#{gid}")
    assert [f.key for f in opened["by_number"]] == [gid] and [f.key for f in opened["by_title"]] == [gid]
    assert isinstance(opened["by_title"][0], Found) and "projet" in opened["by_title"][0].subtitle
    assert opened["none"] == []
    # la liste des projets : son état, son avancement, son agenda, ce qu'il a le droit de faire sortir
    project = table(opened["projets"], "Projets en cours").rows[0]
    assert project.href == Ref.subject("goal", gid, f"#{gid}") and project.cells[0].text == "Un script de bonjour"
    assert project.cells[2].text == "en cours" and project.cells[3].text == f"0 / {params(None).project_steps}"
    assert project.cells[6] == "dès qu'elle peut (manuel)" and project.cells[7].text == "sort avec ton accord"
    # son cadre et sa politique : le cadre confié en entier, sa liberté, son rythme
    policy = opened["politique"]
    frame_text = next(b for b in policy if type(b).__name__ == "Prose")
    assert frame_text.text == "Écrire bonjour.py et le tester." and "sort avec ton accord" in flat(policy)
    assert "Son rythme" in flat(policy) and "Quand elle s'arrête" in flat(policy)
    # après un pas (écrit, lancé, fini avec preuve) : chaque onglet le dit
    assert reported and reported[0].data.proven
    assert after["head"].key == gid  # « #12 » : la fiche canonique
    resume = after["resume"]
    assert field(resume, "titre") == "Un script de bonjour" and field(resume, "statut").text == "abouti"
    assert field(resume, "échéance").at == instant(datetime(2026, 10, 2, 18, 0, tzinfo=tz))  # en heure locale
    assert field(resume, "d'où il vient") == "operator"
    pas = table(after["pas"], "Ses pas")
    assert [c.text for c in pas.rows[0].cells[1:3]] == ["fini", "prouvé"]
    assert "ws_write" in pas.rows[0].cells[4] and pas.rows[0].cells[6].kind == "episode"
    assert "aucune consigne" in flat(after["carnet"])
    assert "aucune demande" in flat(after["effets"])
    assert "pas de travail" in flat(after["episodes"])
    # chaque épisode mène à son prompt exact, ses outils, ses appels, sa décision ; son pas y dit son résultat
    episode = table(after["episodes"], "Ses épisodes").rows[-1]
    assert episode.cells[6].params == (("onglet", "prompt"),) and episode.cells[9].params == (("onglet", "decision"),)
    assert episode.cells[4].text == "fini"
    # l'arbitre l'a pesé : le tirage qui a donné ce pas, ses preuves
    decided = table(after["decisions"], "Ce que l'arbitre en a pensé").rows
    assert decided and any(r.cells[1].text == "choisi" for r in decided) and decided[0].detail
    assert "abouti" in flat(after["projets"]) and "Projets clos" in flat(after["projets"])
    atelier_tab = after["atelier"]
    files = table(atelier_tab, "Ses fichiers")
    assert [r[0].text for r in files.rows] == ["bonjour.py", "test_bonjour.py"]
    history = next(b for b in atelier_tab if isinstance(b, Timeline))
    # le plus récent d'abord ; un enregistrement sans pas le dit (il n'a pas de date à lui)
    assert [e.meta for e in history.entries] == ["c000001", "a000000 · sans pas associé"]
    assert history.entries[0].at == reported[0].at and history.entries[0].href.kind == "episode"
    assert history.entries[1].title == "atelier ouvert" and history.entries[1].at == 0
    assert "Rien de changé depuis le dernier pas" in flat(atelier_tab)
    closed = table(after["clos"], "Buts clos")
    assert closed.rows[0].cells[0] == Ref.subject("goal", gid, f"#{gid}") and closed.rows[0].cells[4].text == "abouti"
    assert "Un script de bonjour" in flat(after["person"]) and "pour elle ou lui" in flat(after["person"])


def test_the_workshop_tab_without_workshop_says_so(tmp_path):
    async def scenario(kernel, llm):
        gid = await explore(kernel)
        return await tab(kernel, "atelier", str(gid))

    blocks = live(tmp_path, scenario)
    assert "seuls les projets confiés" in flat(blocks)


# ── Les actions de l'opérateur ────────────────────────────────────────────


def test_workshop_history_reaches_commits_older_than_five_hundred(tmp_path):
    atelier = Atelier()
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        result = await perform(kernel, "goals.confier", form(title="Historique de l'atelier", details="Vérifier les versions."),
                               by="user_1", nonce="long-history")
        assert result.ok
        gid = events(kernel, goals_c.GOAL_OPENED)[-1].seq
        await atelier.write(gid, "notes.txt", "exemple")
        atelier.commits[gid] = [(f"c{i:06}", f"Version {i}") for i in range(555)]
        first = await tab(kernel, "atelier", str(gid))
        last = await tab(kernel, "atelier", str(gid), avant_commits="550")
        return next(b for b in first if isinstance(b, Timeline)), next(b for b in last if isinstance(b, Timeline))
    first, last = live(tmp_path, scenario, ports={"workshop": atelier})
    assert len(first.entries) == 25 and first.pager.older == (("avant_commits", "25"),)
    assert len(last.entries) == 5 and last.entries[-1].title == "Version 0" and not last.pager.older


def test_every_operator_action_goes_through_the_engine(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Bea")
        out = {}
        out["bad"] = await perform(kernel, "goals.confier", form(title="  ", due="lundi prochain",
                                                                 schedule="tous les jours", owner="personne_x"),
                                   by="user_1", nonce="n1")
        out["too_long"] = await perform(kernel, "goals.confier", form(title="x" * 121, max_steps="99"),
                                        by="user_1", nonce="n2")
        out["ok"] = await perform(kernel, "goals.confier", form(("approval",), title="Ranger les notes de Bea",
                                                                schedule="cron:0 9 * * MON", owner="user_2"),
                                  by="user_1", nonce="n3")
        out["again"] = await perform(kernel, "goals.confier", form(("approval",), title="Ranger les notes de Bea",
                                                                   schedule="cron:0 9 * * MON", owner="user_2"),
                                     by="user_1", nonce="n3")
        gid = str(events(kernel, goals_c.GOAL_OPENED)[-1].seq)
        spec = kernel.registry.actions
        out["offered_active"] = {k: offered(kernel, spec[f"goals.{k}"], gid)
                                 for k in ("pause", "reprendre", "consigne", "clore")}
        out["resume_active"] = await perform(kernel, "goals.reprendre", form(), by="user_1", subject=gid, nonce="n4")
        out["no_subject"] = await perform(kernel, "goals.pause", form(), by="user_1", nonce="n5")
        out["pause"] = await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="n6")
        out["offered_paused"] = {k: offered(kernel, spec[f"goals.{k}"], gid)
                                 for k in ("pause", "reprendre", "consigne", "clore")}
        out["status_paused"] = kernel.mind.frame().get(goals_c.STATUS(int(gid)))
        out["live_paused"] = [g.status for g in kernel.mind.frame().get(goals_c.LIVE)]
        out["empty_order"] = await perform(kernel, "goals.consigne", form(instruction="   "), by="user_1",
                                           subject=gid, nonce="n7")
        out["order"] = await perform(kernel, "goals.consigne", form(instruction="Classe-les par date."),
                                     by="user_1", subject=gid, nonce="n8")
        out["resume"] = await perform(kernel, "goals.reprendre", form(), by="user_1", subject=gid, nonce="n9")
        esteem = kernel.mind.frame().get(self_c.ESTEEM)
        out["close"] = await perform(kernel, "goals.clore", form(), by="user_1", subject=gid, nonce="n10")
        out["esteem"] = (esteem, kernel.mind.frame().get(self_c.ESTEEM))
        out["offered_closed"] = {k: offered(kernel, spec[f"goals.{k}"], gid)
                                 for k in ("pause", "reprendre", "consigne", "clore")}
        out["unknown"] = offered(kernel, spec["goals.pause"], "999") or offered(kernel, spec["goals.pause"], "abc")
        out["events"] = {t.name: events(kernel, t) for t in (goals_c.GOAL_OPENED, GOAL_PAUSED, GOAL_RESUMED,
                                                              GOAL_AMENDED, goals_c.GOAL_CLOSED, rt.OPERATED)}
        out["carnet"] = await tab(kernel, "carnet", gid)
        out["resume_tab"] = await tab(kernel, "resume", gid)
        out["gid"] = gid
        return out

    out = live(tmp_path, scenario)
    bad = out["bad"]
    assert not bad.ok and set(bad.errors) == {"title", "due", "schedule", "owner"}  # chaque champ dit ce qui ne va pas
    assert "illisible" in bad.errors["due"] and "règle refusée" in bad.errors["schedule"]
    assert "personne inconnue" in bad.errors["owner"]
    assert set(out["too_long"].errors) == {"title", "max_steps"} and "120" in out["too_long"].errors["title"]
    assert out["ok"].ok and out["again"].deduped  # un double envoi ne refait rien
    ev = out["events"]
    [opened] = ev[goals_c.GOAL_OPENED.name]
    assert opened.origin is Origin.EXTERNAL and opened.correlation.startswith("opérateur:goals.confier")
    d = opened.data
    assert (d.kind, d.authority, d.source, d.owner, d.about) == (goals_c.PROJECT, goals_c.USER, "operator", "user_2",
                                                                 ("user_2",))
    assert d.approval is False and d.schedule == "cron:0 9 * * MON" and "workshop" in d.bundles  # case décochée
    assert d.address is None  # confié pour Bea par l'opérateur : on ne lui parle pas au nom de Bea
    assert out["offered_active"] == {"pause": True, "reprendre": False, "consigne": True, "clore": True}
    assert not out["resume_active"].ok and "pas possible" in out["resume_active"].message
    assert not out["no_subject"].ok
    assert out["pause"].ok and out["status_paused"] == goals_c.PAUSED and out["live_paused"] == [goals_c.PAUSED]
    assert out["offered_paused"] == {"pause": False, "reprendre": True, "consigne": True, "clore": True}
    assert not out["empty_order"].ok and "instruction" in out["empty_order"].errors
    assert out["order"].ok and out["resume"].ok and out["close"].ok
    assert out["offered_closed"] == {"pause": False, "reprendre": False, "consigne": False, "clore": False}
    assert not out["unknown"]
    for t in (GOAL_PAUSED, GOAL_RESUMED, GOAL_AMENDED, goals_c.GOAL_CLOSED):
        [e] = ev[t.name]
        assert e.origin is Origin.EXTERNAL and e.correlation.startswith("opérateur:goals.")
        assert e.data.goal == int(out["gid"])
    assert ev[GOAL_AMENDED.name][0].data.instruction.text == "Classe-les par date."
    assert ev[GOAL_AMENDED.name][0].data.by == "user_1" and ev[GOAL_PAUSED.name][0].data.by == "user_1"
    closed = ev[goals_c.GOAL_CLOSED.name][0].data
    assert closed.status == goals_c.CANCELLED and "opérateur" in closed.reason
    assert out["esteem"][0] == out["esteem"][1]  # annuler ne lui fait rien ressentir
    audit = {(e.data.action, e.data.outcome) for e in ev[rt.OPERATED.name]}
    assert {("goals.confier", "done"), ("goals.confier", "refused"), ("goals.pause", "done"),
            ("goals.reprendre", "done"), ("goals.consigne", "done"), ("goals.clore", "done")} <= audit
    assert all(e.data.by == "user_1" for e in ev[rt.OPERATED.name])
    assert all(e.data.subject == out["gid"] for e in ev[rt.OPERATED.name] if e.data.action == "goals.pause")
    assert "Classe-les par date." in flat(out["carnet"]) and "« Adrien » (user_1)" in flat(out["carnet"])
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


def test_a_confided_project_is_due_in_local_time(tmp_path):
    async def scenario(kernel, llm):
        got = await perform(kernel, "goals.confier", form(title="Préparer l'exposé", due="02/10/2026 à 18h"),
                            by="user_1", nonce="d1")
        assert got.ok, got
        frame = kernel.mind.frame()
        [opened] = events(kernel, goals_c.GOAL_OPENED)
        return opened.data, frame.env.tz_of(frame.root)

    d, tz = live(tmp_path, scenario)
    assert d.due == instant(datetime(2026, 10, 2, 18, 0, tzinfo=tz))
    assert d.owner == "user_1" and d.address == "user_1"  # sans « pour qui » : pour l'opérateur, qui l'a demandé
    assert d.details is None and d.schedule == "manual" and d.approval is True


def test_the_badges_say_what_needs_the_operator(tmp_path):
    async def scenario(kernel, llm):
        ins = Inspection(kernel)
        views = {v.name: v for v in ins.in_section("buts")}
        await connect(kernel, "user_1", "Adrien", operator=True)
        await perform(kernel, "goals.confier", form(title="Un script", schedule="cron:0 9 * * MON"), by="user_1",
                      nonce="b1")
        gid = events(kernel, goals_c.GOAL_OPENED)[-1].seq
        await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="goals.networked", owner="goals", args_json="{}", summary=Content.of("installer requests"),
            approval=True, context=f"goal:{gid}")], emitter="runtime", correlation="t", origin=Origin.TOOL)
        waiting = ins.badge(views["vivants"])
        effects = await tab(kernel, "effets", str(gid))
        await kernel.mind.append([goals_c.GOAL_CLOSED.draft(
            goal=gid, status=goals_c.STUCK, kind=goals_c.PROJECT, authority=goals_c.USER,
            title=Content.of("Un script"), reason="bloquée")], emitter="goals", correlation="t",
            origin=Origin.GENESIS)
        return [v for v in views], waiting, ins.badge(views["clos"]), effects

    names, waiting, stuck, effects = live(tmp_path, scenario)
    assert names == ["projets", "vivants", "clos"]
    assert waiting == (1, "attendent ton accord") and stuck == (1, "confiés : bloqués ou en échec")
    assert "attend ton accord" in flat(effects) and "installer requests" in flat(effects)
    approvals = next(b for b in effects if isinstance(b, Fields))
    assert approvals.pairs[0][1].kind == "local" and approvals.pairs[0][1].key == "/inspecteur/approbations"
