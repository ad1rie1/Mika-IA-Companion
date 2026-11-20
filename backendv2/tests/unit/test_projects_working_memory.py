"""La mémoire de travail d'une exécution (ADR 0253) : chaque objectif garde ses comptes rendus et ses notes à lui.

Elle était celle du projet entier : dès que plusieurs objectifs constants alternent, chacun ne retrouvait qu'un ou
deux de ses propres comptes rendus parmi les cinq du projet. L'objectif garde les siens ; l'exécution qui le vise les
lit d'abord, puis ce qui s'est fait sur le reste du projet ; une exécution sans objectif visé lit le projet comme
avant."""

from __future__ import annotations

from types import SimpleNamespace

from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    NOTED,
    NOTES_KEPT,
    OBJECTIVE_NOTES_KEPT,
    OBJECTIVE_REPORTS_KEPT,
    PROJECTS,
    REPORTS_KEPT,
    Objective,
    Project,
    ProjectsState,
    _noted,
    _reported,
)
from mika.faculties.projects.faculty import params as projects_params
from mika.faculties.projects.prompt import (
    NOTES_TOTAL,
    OWN_REPORT_CLIP,
    REPORT_CLIP,
    REPORTS_SHOWN,
    _refs,
    _run_section,
)
from mika.faculties.projects.tools import NoteArgs, ReportArgs, project_note, report_run
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.events import Content
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import phrase
from tests.unit.test_projects import create, events, live
from tests.unit.test_projects_framing import _ctx

PM = projects_params(None)


def _cx():
    return SimpleNamespace(params=PM, facts=SimpleNamespace(get=lambda key: None))


def _ev(at: int, data, correlation: str = "e"):
    return SimpleNamespace(correlation=correlation, at=at, data=data)


def _three_constants() -> ProjectsState:
    objectives = tuple(Objective(id=i, text_ref=f"o{i}", kind=c.CONSTANT) for i in (1, 2, 3))
    p = Project(id=1, title_ref="t", authority=c.USER, created_at=0, plan_state=c.PLANNED, objectives=objectives)
    return ProjectsState(projects=FrozenDict({1: p}))


def _report(s: ProjectsState, at: int, objective: int, ref: str, verdict: str = c.DONE) -> ProjectsState:
    data = c.RUN_REPORTED.payload(project=1, objective=objective, verdict=verdict, summary=Content(ref=ref))
    return _reported(s, _ev(at, data), _cx())


# ── Ce que l'état garde ────────────────────────────────────────────────────


def test_each_objective_keeps_its_own_reports_while_others_work():
    """Trois constants alternent sur quatre tours : le projet ne garde que les cinq derniers comptes rendus, où
    chacun n'a qu'un ou deux des siens ; chaque objectif garde ses trois derniers à lui, dans l'ordre."""
    s = _three_constants()
    for turn in range(4):
        for oid in (1, 2, 3):
            s = _report(s, (turn * 3 + oid) * HOUR, oid, f"r{turn}.{oid}")
    p = s.projects[1]
    assert len(p.reports) == REPORTS_KEPT == 5
    assert [ref for *_, ref in p.reports] == ["r2.2", "r2.3", "r3.1", "r3.2", "r3.3"]
    for o in p.objectives:
        assert [ref for *_, ref in o.reports] == [f"r{turn}.{o.id}" for turn in (1, 2, 3)]
        assert len(o.reports) == OBJECTIVE_REPORTS_KEPT == 3
        assert [verdict for _, verdict, _ in o.reports] == [c.DONE] * 3
        assert o.note_ref == f"r3.{o.id}"  # le dernier reste aussi « où tu en étais »


def test_a_report_without_text_or_without_objective_leaves_objectives_alone():
    s = _three_constants()
    s = _report(s, HOUR, 1, "r1")
    silent = c.RUN_REPORTED.payload(project=1, objective=1, verdict=c.CONTINUE, summary=Content(text="sans référence"))
    s = _reported(s, _ev(2 * HOUR, silent), _cx())
    s = _report(s, 3 * HOUR, 0, "sans-objectif")  # un réveil par API ne vise aucun objectif
    p = s.projects[1]
    assert [ref for *_, ref in p.objectives[0].reports] == ["r1"]
    assert [ref for *_, ref in p.reports] == ["r1", "sans-objectif"]
    assert all(o.reports == () for o in p.objectives[1:])


def test_a_note_stays_with_the_objective_it_was_written_for():
    """Le carnet du projet garde toutes les notes, comme avant ; l'objectif visé garde les trois dernières des
    siennes ; une note d'avant, qui ne dit pas son objectif, reste au carnet seul."""
    s = _three_constants()
    for n, oid in enumerate((1, 2, 1, 1, 0, 1, 3)):
        s = _noted(s, _ev(n * MINUTE, NOTED.payload(project=1, text=Content(ref=f"n{n}"), objective=oid)), _cx())
    p = s.projects[1]
    assert p.notes == tuple(f"n{n}" for n in range(7)) and len(p.notes) <= NOTES_KEPT
    assert p.objectives[0].notes == ("n2", "n3", "n5") and len(p.objectives[0].notes) == OBJECTIVE_NOTES_KEPT
    assert p.objectives[1].notes == ("n1",) and p.objectives[2].notes == ("n6",)
    unknown = _noted(s, _ev(HOUR, NOTED.payload(project=1, text=Content(ref="perdue"), objective=99)), _cx())
    assert unknown.projects[1].notes[-1] == "perdue"  # un objectif inconnu : la note reste au carnet
    assert [o.notes for o in unknown.projects[1].objectives] == [o.notes for o in p.objectives]


def test_the_state_is_rebuilt_from_the_journal():
    """Rien à convertir : l'état d'avant ne portait pas la mémoire des objectifs, il se reconstruit."""
    assert PROJECTS.state_version >= 12


# ── Ce que l'exécution lit ─────────────────────────────────────────────────


async def _work(kernel, pid: int, oid: int, text: str, note: str = "") -> None:
    """Une exécution sur un objectif : une note au carnet (s'il y en a une), puis son compte rendu."""
    subject = f"objective:{pid}:{oid}"
    if note:
        await project_note(NoteArgs(text=note), _ctx(kernel, "project_note", Kind.WORK, project_target(pid),
                                                     subject=subject))
    said = await report_run(ReportArgs(verdict=c.CONTINUE, summary=text),
                            _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=subject))
    assert "refus" not in str(said).lower(), said


def _section(kernel, pid: int, oid: int | None) -> tuple[str, Project]:
    frame = kernel.mind.frame()
    s = frame.state("projects")
    p = s.projects[pid]
    target = next((o for o in p.objectives if o.id == oid), None)
    attrs = {"subject": f"objective:{pid}:{oid}"} if oid else {}
    run = _ctx(kernel, "report_run", Kind.WORK, project_target(pid), **attrs)
    texts = kernel.ports["store"].content(_refs(p, target))
    return _run_section(s, run.frame, {"projects": {"texts": texts}}).content, p


def test_a_run_reads_its_own_objective_first_then_the_rest_of_the_project(tmp_path):
    """Trois missions constantes alternent. Celle qui reprend lit son dernier compte rendu en entier, ses deux
    d'avant et ses notes à elle, puis ce qui s'est fait ailleurs : cinq comptes rendus en tout, les siens d'abord.
    Avant, elle n'aurait retrouvé qu'un des siens parmi les cinq du projet."""

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Produit", constants="Auditer le code\nPublier un article\nSuivre",
                           cadence_hours="24")
        ids = [o.id for o in kernel.mind.frame().state("projects").projects[pid].objectives]
        for turn in range(4):
            for oid, name in zip(ids, ("audit", "article", "suivi"), strict=True):
                await _work(kernel, pid, oid, f"{name} passe {turn}", note=f"note {name} {turn}" if turn else "")
        return _section(kernel, pid, ids[0]), _section(kernel, pid, None), ids

    (section, p), (bare, _), ids = live(tmp_path, scenario)
    audit = ids[0]
    assert len(p.objectives[0].reports) == 3
    # son dernier compte rendu, en entier, sur la ligne « où tu en étais »
    assert phrase("projects.run.note", note="audit passe 3") in section
    # ses deux d'avant, dans l'ordre, sous leur titre — pas le dernier une seconde fois
    own = section.split(phrase("projects.run.own_reports"), 1)[1].split(phrase("projects.run.own_notebook"), 1)[0]
    assert own.index("audit passe 1") < own.index("audit passe 2") and "audit passe 3" not in own
    assert "audit passe 0" not in section  # au-delà de ce qu'il garde
    # ses notes à lui, pas celles des autres missions
    notes = section.split(phrase("projects.run.own_notebook"), 1)[1].split(phrase("projects.run.others"), 1)[0]
    assert [n for n in ("note audit 1", "note audit 2", "note audit 3") if n in notes] == \
        ["note audit 1", "note audit 2", "note audit 3"]
    assert "article" not in notes and "suivi" not in notes
    # le reste du projet : ce qui s'est fait ailleurs, jamais un des siens, cinq lignes en tout
    rest = section.split(phrase("projects.run.other_reports"), 1)[1].split(phrase("projects.run.notebook"), 1)[0]
    lines = [line for line in rest.splitlines() if line.startswith("- ")]
    assert len(lines) == REPORTS_SHOWN - 2 == 3 and not any(f"objectif n° {audit}," in line for line in lines)
    assert [word for line in lines for word in ("article passe 2", "suivi passe 2", "article passe 3",
                                                "suivi passe 3") if word in line] == \
        ["suivi passe 2", "article passe 3", "suivi passe 3"]
    # le carnet du reste du projet : au plus cinq notes en tout, aucune des siennes en double
    carnet = section.split(phrase("projects.run.notebook"), 1)[1]
    shown = [line for line in carnet.splitlines() if line.startswith("- note ")]
    assert len(shown) == NOTES_TOTAL - 3 == 2 and not any("audit" in line for line in shown)
    # sans objectif visé (un réveil par API) : le projet, comme avant
    assert phrase("projects.run.reports") in bare and phrase("projects.run.own_reports") not in bare
    assert phrase("projects.run.other_reports") not in bare
    assert len([line for line in bare.split(phrase("projects.run.reports"), 1)[1].splitlines()
                if line.startswith("- il y a")]) == 5


def test_a_fresh_objective_still_reads_the_last_five_reports_of_the_project(tmp_path):
    """Une étape qui commence n'a rien à elle : elle lit les cinq derniers comptes rendus du projet, comme avant —
    ce que l'étape d'avant lui laisse ne se perd pas."""

    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Produit", objectives="Écrire le module\nLe documenter")
        first, second = [o.id for o in kernel.mind.frame().state("projects").projects[pid].objectives]
        for n in range(6):
            await _work(kernel, pid, first, f"module passe {n}")
        return _section(kernel, pid, second)

    section, p = live(tmp_path, scenario)
    assert p.objectives[1].reports == () and phrase("projects.run.own_reports") not in section
    rest = section.split(phrase("projects.run.other_reports"), 1)[1]
    assert [n for n in range(6) if f"module passe {n}" in rest] == [1, 2, 3, 4, 5]


def test_her_own_reports_are_quoted_longer_than_those_of_the_rest(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Produit", constants="Auditer\nPublier", cadence_hours="24")
        audit, publish = [o.id for o in kernel.mind.frame().state("projects").projects[pid].objectives]
        long = "x" * 1400
        await _work(kernel, pid, audit, f"audit ancien {long}")
        await _work(kernel, pid, publish, f"article {long}")
        await _work(kernel, pid, audit, "audit récent")
        return _section(kernel, pid, audit)

    section, _ = live(tmp_path, scenario)
    own = next(line for line in section.splitlines() if "audit ancien" in line)
    other = next(line for line in section.splitlines() if "article x" in line)
    assert OWN_REPORT_CLIP - 40 < own.count("x") <= OWN_REPORT_CLIP
    assert REPORT_CLIP - 40 < other.count("x") <= REPORT_CLIP < own.count("x")


def test_a_note_written_during_a_run_names_its_objective(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Produit", constants="Auditer", cadence_hours="24")
        [oid] = [o.id for o in kernel.mind.frame().state("projects").projects[pid].objectives]
        await _work(kernel, pid, oid, "un passage", note="le module réseau est couvert")
        return [e for e in events(kernel, NOTED) if e.data.project == pid], oid

    [noted], oid = live(tmp_path, scenario)
    assert noted.data.objective == oid and noted.data.text.text == "le module réseau est couvert"
