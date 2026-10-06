"""Les outils des projets.

Pendant une exécution (``WORK`` ou ``JOB``) : ``report_run`` (le verdict, qui la
clôt), ``project_note`` (son carnet), ``project_decide`` (une décision
technique, qui peut en remplacer une autre), ``project_objective_add`` (un
objectif de plus). En conversation : ``create_project`` (un projet qu'on lui
confie — seulement quelqu'un qui s'occupe d'elle), ``start_project`` (un
projet à elle — aussi pendant une exploration qui s'avère plus grosse qu'une
envie) et ``project_steer`` (le piloter de vive voix avec qui s'occupe d'elle :
un objectif de plus, une consigne, s'y mettre maintenant, la pause, la
reprise — jamais son cadre). Partout : ``project_close`` (clore un projet à
elle).

**« Fait » se prouve** : pour un objectif ponctuel, un commit non vide pendant
l'objectif (ce qu'elle a écrit dans l'atelier), ou un brouillon de mail, une
app forgée. Lancer ``ls``, lire, noter ou décider ne prouvent rien. Un « fait »
qui ne se prouve pas **n'est pas un verdict** : il est refusé sans rien écrire,
et elle peut encore conclure honnêtement (``report_run`` admet trois appels,
un seul verdict).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import (
    AMENDED,
    ARCHIVED,
    DECIDED,
    DECISIONS_KEPT,
    DEFAULT_BUNDLES,
    NOTED,
    NUDGED,
    OBJECTIVE_ADDED,
    OBJECTIVES_KEPT,
    PAUSED,
    PROJECTS,
    PUSH,
    RESUMED,
    Objective,
    Project,
    ProjectsState,
    busy,
    cadence,
    check_schedule,
    decision_at,
    in_force,
    live,
    living,
    nudged,
    objective_at,
    objective_of,
    outgoing,
    params,
    pick,
    written,
)
from mika.kernel.clock import HOUR
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.vocab.episodes import PROJECT_KINDS, Kind, goal_of, project_of, project_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity, hearable
from mika.vocab.words import stems

REPORT, NOTE, DECIDE, OBJECTIVE_ADD = "report_run", "project_note", "project_decide", "project_objective_add"
#: ce qui change quelque chose (le compte rendu le dit) : écrire, modifier, un programme qui a réussi, un
#: brouillon, une app forgée
CHANGING = frozenset({"ws_write", "ws_edit", "ws_run", "email_draft", "forge_write"})
#: …et ce qui, hors de l'atelier, **prouve** qu'une exécution a produit (dans l'atelier, c'est le commit)
PRODUCING = frozenset({"email_draft", "forge_write"})
RUNS = list(PROJECT_KINDS)

PROJECTS.bundle("projects", phrase("projects.bundle"))


def current(ctx: Any) -> tuple[Project, Objective | None] | None:
    """Le projet de l'exécution en cours et l'objectif qu'elle vise (``None`` : plus actif)."""
    ep = ctx.frame.episode
    pid = project_of(ep.target) if ep is not None else None
    s: ProjectsState = ctx.frame.state("projects")
    p = s.projects.get(pid) if pid is not None else None
    if p is None or p.status != c.ACTIVE:
        return None
    got = objective_of(ep.attrs.get("subject")) if ep is not None else None
    o = objective_at(p, got[1]) if got is not None and got[0] == p.id else None
    return p, o


def text_of(ctx: Any, ref: str, level: int, empty: str) -> Content:
    store = ctx.ports.get("store")
    text = store.content([ref]).get(ref) if store is not None and ref else None
    return Content.of(text or empty, level=level)


def caretaker(frame: Frame) -> str:
    """Qui s'occupe d'elle, par son prénom (jamais « ta propriétaire »)."""
    names = [n for n in (frame.get(identity_c.IDENTITY(o)).name for o in frame.get(identity_c.OWNERS)) if n]
    return f"« {names[0]} »" if len(names) == 1 else phrase("projects.caretaker")


def gone() -> str:
    """La réponse de chaque outil d'exécution quand le projet n'est plus actif."""
    return phrase("projects.tools.gone")


def wrap_up(ctx: Any, out: Any) -> Any:
    """Au-delà de quelques appels, chaque résultat lui rappelle de conclure : une exécution qui s'arrête sans
    verdict ne compte pas comme du travail (et le délai d'une exécution est court)."""
    pm = params(ctx.frame.env.params_of("projects", ctx.frame.root))
    done = any(name == REPORT and ok for name, ok in ctx.calls)
    if done or len(ctx.calls) + 1 < pm.wrap_up_after:
        return out
    note = phrase("projects.tools.wrap_up")
    if isinstance(out, ToolResult):
        return ToolResult(ok=out.ok, content=out.content + note)
    return f"{out}{note}"


def still_open(project: int, objective: int) -> Guard:
    """Une clôture ne vaut que pour un objectif encore ouvert (l'opérateur a pu le retirer entre-temps)."""
    return Guard("objectif ouvert", predicate=lambda view, k=(project, objective):
                 view.get(c.OBJECTIVE_STATUS(k)) == c.OPEN)


class ReportArgs(BaseModel):
    verdict: Literal["continue", "done", "blocked", "wait"] = Field(
        description=phrase("projects.tools.report.verdict"))
    summary: str = Field(min_length=1, max_length=1500, description=phrase("projects.tools.report.summary"))
    notable: float = Field(default=0.5, ge=0.0, le=1.0, description=phrase("projects.tools.report.notable"))
    wait_minutes: int = Field(default=0, ge=0, le=1440)
    needs_you: str = Field(default="", max_length=600, description=phrase("projects.tools.report.needs_you"))


def _proof(ctx: Any, sha: str) -> str:
    """Ce qui prouve que cette exécution a produit : un commit non vide, sinon un brouillon ou une app réussis."""
    if sha:
        return "commit"
    return "outil" if any(ok and name in PRODUCING for name, ok in ctx.calls) else ""


def _mode(ctx: Any) -> str:
    """Le mode de cette exécution : celui de son épisode — un réveil impersonnel sur un projet à elle n'est pas son
    travail à elle (ADR 0068)."""
    ep = ctx.frame.episode
    return c.PLAIN if ep is not None and ep.kind == Kind.JOB else c.PERSONA


def commit_message(p: Project, o: Objective | None) -> str:
    """Un message de commit neutre : il part peut-être vers un dépôt distant, il ne nomme personne et ne raconte
    rien (le compte rendu, lui, reste dans sa vie, là où l'oubli l'atteint)."""
    return phrase("projects.commit.run_objective", run=p.runs, objective=o.id) if o is not None else \
        phrase("projects.commit.run", run=p.runs)


@PROJECTS.tool(REPORT, description=phrase("projects.tools.report.description"), args=ReportArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=3)
async def report_run(args: ReportArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return gone()
    if any(name == REPORT and ok for name, ok in ctx.calls):
        return ToolResult(ok=False, content=phrase("projects.tools.report.already"))
    p, o = got
    worked = tuple(sorted({name for name, ok in ctx.calls if ok and name in CHANGING}))
    summary = args.summary.strip()
    port = ctx.ports.get("workshop")
    sha = ""
    if port is not None and port.exists(p.id):
        sha = await port.commit(p.id, commit_message(p, o))  # un commit par exécution qui a changé quelque chose
    proof = _proof(ctx, sha)
    closed = o is not None and o.status != c.OPEN  # retiré ou clos pendant qu'elle y travaillait
    proven = args.verdict == c.DONE and o is not None and not closed and (bool(proof) or o.evidence > 0)
    if args.verdict == c.DONE and o is not None and not closed and o.kind == c.ONCE and not proven:
        # pas un verdict : rien ne s'écrit, elle peut encore conclure honnêtement
        return ToolResult(ok=False, content=phrase("projects.tools.report.not_yet"))
    need = args.needs_you.strip()
    report = c.RUN_REPORTED.draft(
        project=p.id, objective=o.id if o is not None else 0, verdict=args.verdict,
        summary=Content.of(summary, level=written(p)), notable=args.notable, mode=_mode(ctx), proven=proven,
        tools=worked, commit=sha, proof=proof, wait_s=args.wait_minutes * 60, owner=p.owner, about=p.about,
        need=Content.of(need, level=written(p)) if need else None)
    if o is not None and not closed and o.kind == c.ONCE and (proven or args.verdict == c.BLOCKED):
        try:
            await ctx.emit(report, closing(ctx, p, o, c.DONE if proven else c.BLOCKED, summary, args.notable),
                           guard=still_open(p.id, o.id))
        except Superseded:  # l'objectif a changé entre-temps : le compte rendu reste, la clôture non
            if ctx.mind.frame().get(c.OBJECTIVE_STATUS((p.id, o.id))) == c.OPEN:
                raise  # c'est la garde de l'exécution qui a cédé (le projet n'est plus actif)
            await ctx.emit(report)
            closed = True
    else:
        await ctx.emit(report)
    pushed = ""
    if sha and p.auto_push and p.remote:
        sent = await propose_push(ctx, p, phrase("projects.tools.report.push_why"))
        pushed = phrase("projects.tools.report.push_proposed") if sent == "proposed" else \
            phrase("projects.tools.report.push_sent") if sent == "sent" else \
            phrase("projects.tools.report.push_pending") if sent == "pending" else ""
    kept = phrase("projects.tools.report.kept", sha=sha) if sha else ""
    asked = phrase("projects.tools.report.asked") if need else ""
    if closed:
        return phrase("projects.tools.report.gone", kept=kept, pushed=pushed)
    if o is None:
        return phrase("projects.tools.report.noted", kept=kept, pushed=pushed, asked=asked)
    if o.kind == c.CONSTANT:
        if args.verdict in (c.DONE, c.BLOCKED):
            pm = params(ctx.frame.env.params_of("projects", ctx.frame.root))
            hours = max(1, round(cadence(o, pm) / HOUR))
            return phrase("projects.tools.report.constant", hours=hours, kept=kept, pushed=pushed, asked=asked)
        return phrase("projects.tools.report.constant_continue", kept=kept, pushed=pushed, asked=asked)
    if proven:
        return phrase("projects.tools.report.done", id=o.id, kept=kept, pushed=pushed)
    if args.verdict == c.BLOCKED:
        return phrase("projects.tools.report.blocked", id=o.id, kept=kept, asked=asked)
    if args.verdict == c.WAIT:
        return phrase("projects.tools.report.wait", minutes=max(10, args.wait_minutes), kept=kept, asked=asked)
    return phrase("projects.tools.report.continue", kept=kept, pushed=pushed, asked=asked)


def closing(ctx: Any, p: Project, o: Objective, status: str, result: str, notable: float) -> Draft[Any]:
    return c.OBJECTIVE_CLOSED.draft(
        project=p.id, objective=o.id, status=status, mode=p.mode, authority=p.authority,
        title=text_of(ctx, o.text_ref, p.sensitivity, phrase("projects.tools.report.forgotten")),
        result=Content.of(result, level=written(p)) if result else None, notable=notable if status == c.DONE
        else 0.0, owner=p.owner, about=p.about, sensitivity=p.sensitivity)


async def pinned(port: Any, project: int) -> tuple[str, str]:
    """Le commit courant de l'atelier et son titre : ce qu'un envoi approuvé enverra, et rien d'autre."""
    sha = await port.head(project) if port is not None and port.exists(project) else ""
    commits = await port.commits(project, 1) if sha else []
    return sha, commits[0].title if commits else ""


def push_summary(p: Project, sha: str, title: str, why: str) -> str:
    return (f"Pousser le commit {sha[:12]} (« {title[:120]} ») vers {p.remote}, branche {p.branch} — {why}")[:600]


def pending_push(frame: Frame, project: int) -> bool:
    """Un envoi de ce projet attend-il déjà un accord ?"""
    return any(v.capability == PUSH and project_of(v.context) == project for v in frame.get(rt.PENDING_EFFECTS))


async def propose_push(ctx: Any, p: Project, why: str) -> str:
    """Proposer d'envoyer l'atelier au dépôt distant (exécuté tout de suite ou après accord, selon le projet) :
    le commit est épinglé au moment de proposer — l'accord vaut pour ce qui a été montré, pas pour ce que
    l'atelier deviendra d'ici là. Un seul envoi attend un accord à la fois : les suivants le suivront (rien ne
    s'empile). Rend ``proposed``, ``sent``, ``pending`` (un envoi attend déjà) ou ``nothing``."""
    if p.approval and pending_push(ctx.frame, p.id):
        return "pending"
    sha, title = await pinned(ctx.ports.get("workshop"), p.id)
    if not sha:
        return "nothing"
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=PUSH, owner=PROJECTS.name, context=project_target(p.id), approval=p.approval,
        args_json=json.dumps({"project": p.id, "url": p.remote, "branch": p.branch, "sha": sha}),
        summary=Content.of(push_summary(p, sha, title, why), level=0), about=tuple(x for x in (p.owner, *p.about) if x)))
    return "proposed" if p.approval else "sent"


class NoteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description=phrase("projects.tools.note.text"))


@PROJECTS.tool(NOTE, description=phrase("projects.tools.note.description"), args=NoteArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=4)
async def project_note(args: NoteArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return gone()
    p, _ = got
    await ctx.emit(NOTED.draft(project=p.id, text=Content.of(args.text.strip(), level=written(p)), owner=p.owner,
                               about=p.about))
    return wrap_up(ctx, phrase("projects.tools.note.done"))


class DecideArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200, description=phrase("projects.tools.decide.title"))
    choice: str = Field(min_length=1, max_length=1500, description=phrase("projects.tools.decide.choice"))
    context: str = Field(default="", max_length=2000, description=phrase("projects.tools.decide.context"))
    options: str = Field(default="", max_length=2000, description=phrase("projects.tools.decide.options"))
    reason: str = Field(default="", max_length=1500, description=phrase("projects.tools.decide.reason"))
    replaces: int = Field(default=0, ge=0, description=phrase("projects.tools.decide.replaces"))


@PROJECTS.tool(DECIDE, description=phrase("projects.tools.decide.description"), args=DecideArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=4)
async def project_decide(args: DecideArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return gone()
    p, o = got
    if args.replaces:
        old = decision_at(p, args.replaces)
        if old is None or old.status != c.IN_FORCE:
            return ToolResult(ok=False, content=phrase("projects.tools.decide.unknown", id=args.replaces))
    elif in_force(p) >= DECISIONS_KEPT:
        return ToolResult(ok=False, content=phrase("projects.tools.decide.full", count=DECISIONS_KEPT))
    level = written(p)

    def opt(text: str) -> Content | None:
        return Content.of(text.strip(), level=level) if text.strip() else None

    number = p.decision_seq + 1
    commit = await ctx.emit(DECIDED.draft(
        project=p.id, decision=number, title=Content.of(args.title.strip(), level=level),
        choice=Content.of(args.choice.strip(), level=level), context=opt(args.context), options=opt(args.options),
        reason=opt(args.reason), replaces=args.replaces, objective=o.id if o is not None else 0, author="self",
        owner=p.owner, about=p.about))
    more = phrase("projects.tools.decide.replaced", id=args.replaces) if args.replaces else ""
    return wrap_up(ctx, phrase("projects.tools.decide.done",
                               id=_attributed(ctx, p.id, commit, "title", "decisions", number), more=more))


class ObjectiveArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500, description=phrase("projects.tools.objective_add.text"))
    kind: Literal["once", "constant"] = Field(default="once", description=phrase("projects.tools.objective_add.kind"))
    cadence_hours: int = Field(default=0, ge=0, le=24 * 30,
                               description=phrase("projects.tools.objective_add.cadence_hours"))


@PROJECTS.tool(OBJECTIVE_ADD, description=phrase("projects.tools.objective_add.description"), args=ObjectiveArgs,
               bundle="projects", episodes=RUNS, max_calls_per_episode=3)
async def project_objective_add(args: ObjectiveArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return gone()
    p, _ = got
    if living(p) >= OBJECTIVES_KEPT:
        return ToolResult(ok=False, content=phrase("projects.tools.objective_add.full", count=OBJECTIVES_KEPT))
    number = p.objective_seq + 1
    commit = await ctx.emit(OBJECTIVE_ADDED.draft(
        project=p.id, objective=number, text=Content.of(args.text.strip(), level=written(p)), kind=args.kind,
        cadence_us=args.cadence_hours * HOUR, author="self", owner=p.owner, about=p.about))
    number = _attributed(ctx, p.id, commit, "text", "objectives", number)
    kind = phrase("projects.tools.objective_add.constant") if args.kind == c.CONSTANT else \
        phrase("projects.tools.objective_add.once")
    return wrap_up(ctx, phrase("projects.tools.objective_add.done", id=number, kind=kind))


def _attributed(ctx: Any, project: int, commit: Any, field: str, kind: str, asked: int) -> int:
    """Le numéro que le réducteur a vraiment donné (un ajout concurrent a pu prendre celui qu'on visait)."""
    seq = commit.seqs[-1] if commit is not None and commit.seqs else None
    p = ctx.frame.state("projects").projects.get(project)
    if seq is None or p is None:
        return asked
    ref = f"{seq}.{field}"
    found = next((x.id for x in getattr(p, kind) if (x.text_ref if kind == "objectives" else x.title_ref) == ref),
                 None)
    return found if found is not None else asked


# ── En conversation : créer un projet ─────────────────────────────────────


def _person(frame: Frame) -> tuple[str, str] | None:
    ep = frame.episode
    if ep is None or not ep.target or ep.kind != Kind.REPLY:
        return None
    return ep.target, frame.get(identity_c.PERSON(ep.target))


def opened(*, title: str, description: str, authority: str, mode: str, owner: str | None, address: str | None,
           about: tuple[str, ...], level: int, source: str, schedule_rule: str = "", approval: bool = True,
           priority: str = c.NORMAL, bundles: tuple[str, ...] = DEFAULT_BUNDLES, days: str = c.EVERY_DAY,
           start_min: int = 0, end_min: int = 24 * 60, runs_per_day: int = 0, remote: str = "",
           branch: str = "main", auto_push: bool = False) -> Draft[Any]:
    """L'ouverture d'un projet (par une propriétaire, un opérateur, ou elle)."""
    return c.PROJECT_CREATED.draft(
        title=Content.of(title.strip(), level=level),
        description=Content.of(description.strip(), level=level) if description.strip() else None,
        authority=authority, mode=mode, owner=owner, address=address, about=about, bundles=bundles,
        schedule=schedule_rule.strip(), days=days, start_min=start_min, end_min=end_min, runs_per_day=runs_per_day,
        approval=approval, priority=priority, remote=remote.strip(), branch=branch.strip() or "main",
        auto_push=auto_push, source=source, sensitivity=level)


def objectives_of(project: int, lines: list[str], constants: list[str], *, author: str, by: str = "",
                  owner: str | None, about: tuple[str, ...], level: int, cadence_us: int = 0) -> list[Draft[Any]]:
    """Les objectifs d'un projet qui vient d'être créé : les ponctuels, puis les constants."""
    out: list[Draft[Any]] = []
    rows = [(t, c.ONCE) for t in lines] + [(t, c.CONSTANT) for t in constants]
    for i, (text, kind) in enumerate(((t.strip(), k) for t, k in rows if t.strip()), start=1):
        out.append(OBJECTIVE_ADDED.draft(project=project, objective=i, text=Content.of(text[:500], level=level),
                                         kind=kind, cadence_us=cadence_us if kind == c.CONSTANT else 0,
                                         author=author, by=by, owner=owner, about=about))
    return out


class CreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000,
                             description=phrase("projects.tools.create.description_arg"))
    objectives: list[str] = Field(default_factory=list, max_length=12,
                                  description=phrase("projects.tools.create.objectives"))
    constants: list[str] = Field(default_factory=list, max_length=12,
                                 description=phrase("projects.tools.create.constants"))
    mode: Literal["persona", "plain"] = Field(default="persona", description=phrase("projects.tools.create.mode"))
    schedule: str = Field(default="asap", description=phrase("projects.tools.create.schedule"))


@PROJECTS.tool("create_project", description=phrase("projects.tools.create.description"), args=CreateArgs, bundle="projects", episodes=[Kind.REPLY], max_calls_per_episode=1, owner_only=True)
async def create_project(args: CreateArgs, ctx: Any) -> Any:
    who = _person(ctx.frame)
    if who is None or not owner_speaks(ctx.frame):
        return ToolResult(ok=False, content=phrase("projects.tools.create.not_owner", who=caretaker(ctx.frame)))
    handle, person = who
    try:
        rule = check_schedule(args.schedule)
    except ValueError as exc:
        return ToolResult(ok=False, content=phrase("projects.tools.create.bad_schedule", error=exc))
    level = int(Sensitivity.PERSONAL)
    commit = await ctx.emit(opened(
        title=args.title, description=args.description, authority=c.USER, mode=args.mode, owner=person,
        address=handle, about=(person,), level=level, source="tool", schedule_rule=rule))
    pid = commit.seqs[-1] if commit.seqs else None
    if pid is None:
        return ToolResult(ok=False, content=phrase("projects.tools.create.failed"))
    goals = args.objectives or ([] if args.constants else [args.title])
    await ctx.emit(*objectives_of(pid, goals, args.constants, author="owner", owner=person, about=(person,),
                                  level=level))
    return phrase("projects.tools.create.done", id=pid)


class StartArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000, description=phrase("projects.tools.start.description_arg"))
    objectives: list[str] = Field(default_factory=list, max_length=12,
                                  description=phrase("projects.tools.start.objectives"))
    constants: list[str] = Field(default_factory=list, max_length=12, description=phrase("projects.tools.start.constants"))


def _own_live(s: ProjectsState) -> int:
    """Ses projets à elle qui l'occupent encore : vivants **et** avec un objectif ouvert (un projet dont tout est
    fait ne l'empêche pas d'en ouvrir un autre)."""
    return sum(1 for p in s.projects.values() if live(p) and p.authority == c.SELF
               and any(o.status == c.OPEN for o in p.objectives))


def owner_speaks(frame: Frame) -> bool:
    """Celle qui lui parle s'occupe-t-elle d'elle ? Jugé sur l'adresse qui parle et là où elle parle
    (``audience.owner`` : jamais dans un groupe public ni un salon) — l'offre des outils le filtre déjà, le
    gestionnaire le revérifie."""
    aud = frame.audience
    return aud is not None and aud.owner


def _talking_to_owner(frame: Frame) -> bool:
    """En conversation, elle ne s'engage (ou ne se dégage) que devant quelqu'un qui s'occupe d'elle."""
    ep = frame.episode
    if ep is None or ep.kind != Kind.REPLY:
        return True
    return _person(frame) is not None and owner_speaks(frame)


@PROJECTS.tool("start_project", description=phrase("projects.tools.start.description"), args=StartArgs, bundle="projects",
               episodes=[Kind.REPLY, Kind.STEP], max_calls_per_episode=1, owner_only=True)
async def start_project(args: StartArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    s: ProjectsState = frame.state("projects")
    pm = params(frame.env.params_of("projects", frame.root))
    ep = frame.episode
    who = _person(frame)
    # en conversation, seulement avec quelqu'un qui s'occupe d'elle : un inconnu ne fixe pas le travail de ses
    # heures creuses
    if not _talking_to_owner(frame):
        return ToolResult(ok=False, content=phrase("projects.tools.start.stranger"))
    if _own_live(s) >= pm.live_self_max:
        return ToolResult(ok=False, content=phrase("projects.tools.start.too_many", count=_own_live(s),
                                                   max=pm.live_self_max))
    gid = goal_of(ep.target) if ep is not None else None
    source = f"goal:{gid}" if gid is not None else "conversation"
    twin = next((p for p in s.projects.values() if live(p) and gid is not None and p.source == source), None)
    if twin is not None:
        return ToolResult(ok=False, content=phrase("projects.tools.start.twin", id=twin.id))
    about: tuple[str, ...] = (who[1],) if who is not None else ()
    level = int(Sensitivity.PERSONAL) if about else int(Sensitivity.NONE)
    if gid is not None:
        goal = next((g for g in frame.get(goals_c.LIVE) if g.id == gid), None)
        about = goal.about if goal is not None else ()
        # ce que le but disait d'autrui reste au moins aussi protégé dans le projet
        level = max(goal.sensitivity if goal is not None else 0, int(Sensitivity.PERSONAL) if about else 0)
    commit = await ctx.emit(opened(
        title=args.title, description=args.description, authority=c.SELF, mode=c.PERSONA, owner=None, address=None,
        about=about, level=level, source=source))
    pid = commit.seqs[-1] if commit.seqs else None
    if pid is None:
        return ToolResult(ok=False, content=phrase("projects.tools.start.failed"))
    goals = args.objectives or ([] if args.constants else [args.title])
    await ctx.emit(*objectives_of(pid, goals, args.constants, author="self", owner=None, about=about, level=level))
    more = phrase("projects.tools.start.from_goal") if gid is not None else ""
    return phrase("projects.tools.start.done", id=pid, more=more)


class CloseArgs(BaseModel):
    project: int = Field(ge=1, description=phrase("projects.tools.close.project"))
    ending: Literal["done", "dropped"] = Field(description=phrase("projects.tools.close.ending"))
    why: str = Field(min_length=1, max_length=600, description=phrase("projects.tools.close.why"))


ENDING_REASON = {"done": "clos par elle : il a fait son temps", "dropped": "clos par elle : elle y renonce"}


@PROJECTS.tool("project_close", description=phrase("projects.tools.close.description"), args=CloseArgs, bundle="projects", episodes=[Kind.REPLY, Kind.STEP, *RUNS],
               max_calls_per_episode=1, owner_only=True)
async def project_close(args: CloseArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    p = frame.state("projects").projects.get(args.project)
    if p is None or not live(p):
        return ToolResult(ok=False, content=phrase("projects.tools.close.unknown", id=args.project))
    if p.authority != c.SELF:
        return ToolResult(ok=False, content=phrase("projects.tools.close.confided"))
    if not _talking_to_owner(frame):
        return ToolResult(ok=False, content=phrase("projects.tools.close.stranger"))
    level = written(p)
    # sa raison va dans son carnet (un contenu, que l'oubli atteint) ; l'archivage n'en garde qu'une étiquette
    await ctx.emit(NOTED.draft(project=p.id, text=Content.of(phrase("projects.tools.close.note", why=args.why.strip()),
                                                             level=level),
                               owner=p.owner, about=p.about),
                   ARCHIVED.draft(project=p.id, reason=ENDING_REASON[args.ending], by="self", ending=args.ending,
                                  owner=p.owner, about=p.about))
    return phrase("projects.tools.close.done") if args.ending == "done" else phrase("projects.tools.close.dropped")


# ── En conversation : piloter un projet ───────────────────────────────────


STEER = "project_steer"
ADD, INSTRUCT, NOW, PAUSE, RESUME = "add", "instruct", "now", "pause", "resume"
#: un projet qu'on pilote encore (archivé, il ne fait plus rien)
STEERABLE = (c.ACTIVE, c.PAUSED)
#: les projets, les objectifs qu'elle énumère quand elle ne sait pas duquel il s'agit
LISTED = 12
#: la raison d'une pause demandée en conversation (qui l'a demandée : ``by``, que la console nomme)
PAUSED_IN_TALK = "mis en pause en conversation"


class SteerArgs(BaseModel):
    project: str = Field(min_length=1, max_length=200, description=phrase("projects.tools.steer.project"))
    what: Literal["add", "instruct", "now", "pause", "resume"] = Field(
        description=phrase("projects.tools.steer.what"))
    text: str = Field(default="", max_length=2000, description=phrase("projects.tools.steer.text"))
    kind: Literal["once", "constant"] = Field(default="once", description=phrase("projects.tools.steer.kind"))
    cadence_hours: int = Field(default=0, ge=0, le=24 * 30, description=phrase("projects.tools.steer.cadence_hours"))
    objective: str = Field(default="", max_length=200, description=phrase("projects.tools.steer.objective"))


def steers(p: Project, person: str | None) -> bool:
    """Cette personne pilote-t-elle ce projet avec elle ? Un projet vivant qu'elle lui a confié, ou un projet à elle
    (qui s'occupe d'elle le pilote aussi). Qu'elle s'occupe d'elle et parle en privé se juge à part
    (``audience.owner``)."""
    return live(p) and bool(person) and (p.owner == person or p.authority == c.SELF)


def _contents(ctx: Any, refs: list[str]) -> Mapping[str, str]:
    store = ctx.ports.get("store")
    wanted = [r for r in refs if r]
    return store.content(wanted) if store is not None and wanted else {}


def _which(said: str, rows: list[tuple[int, str]]) -> int | None:
    """Le numéro dont il s'agit : dit tel quel (« 3 », « n° 3 »), sinon le seul qu'il y a, sinon celui qui a le
    plus de mots en commun avec ce qu'elle en dit — s'il est seul dans ce cas (sinon rien : elle demande lequel)."""
    raw = said.strip().lower().removeprefix("n°").removeprefix("#").strip()
    if raw.isdigit():
        return int(raw) if any(i == int(raw) for i, _ in rows) else None
    if len(rows) == 1:
        return rows[0][0]
    said_stems = stems(said)
    scored = [(len(said_stems & stems(text)), i) for i, text in rows]
    best = max((n for n, _ in scored), default=0)
    top = [i for n, i in scored if n == best]
    return top[0] if best and len(top) == 1 else None


def _listed(rows: list[tuple[int, str]], empty: str) -> str:
    """Les projets (ou les objectifs) parmi lesquels elle n'a pas su choisir, un par ligne."""
    return "\n".join(phrase("projects.tools.steer.item", id=i, text=text or empty) for i, text in rows[:LISTED])


def _in_state(project: int, wanted: tuple[str, ...]) -> Guard:
    """Un geste ne vaut que si le projet est toujours dans cet état (un opérateur a pu le mettre en pause ou
    l'archiver entre-temps)."""
    return Guard("projet inchangé", predicate=lambda view, k=project: view.get(c.STATUS(k)) in wanted)


async def _steered(ctx: Any, draft: Draft[Any], guard: Guard) -> Any:
    """Écrire un geste sous sa garde ; ``None`` quand c'est elle qui a cédé (le projet a changé entre-temps)."""
    try:
        return await ctx.emit(draft, guard=guard)
    except Superseded:
        if guard.predicate is not None and guard.predicate(ctx.mind.frame().view):
            raise  # c'est la garde de la conversation qui a cédé
        return None


def _changed() -> ToolResult:
    """La réponse d'un geste quand le projet a changé sous elle (une garde a cédé) : rien n'a changé."""
    return ToolResult(ok=False, content=phrase("projects.tools.steer.changed"))


@PROJECTS.tool(STEER, description=phrase("projects.tools.steer.description"), args=SteerArgs, bundle="projects",
               episodes=[Kind.REPLY], max_calls_per_episode=2, owner_only=True,
               rule="seulement en privé avec qui s'occupe d'elle, sur un projet vivant qu'elle lui a confié ou un "
                    "projet à elle")
async def project_steer(args: SteerArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    who = _person(frame)
    aud = frame.audience
    if who is None or aud is None or not owner_speaks(frame):
        return ToolResult(ok=False, content=phrase("projects.tools.steer.not_owner", who=caretaker(frame)))
    person = who[1]
    s: ProjectsState = frame.state("projects")
    # ceux dont le détail peut s'entendre ici (la règle de « TES PROJETS ») : on ne pilote pas à l'aveugle
    mine = [p for p in sorted(s.projects.values(), key=lambda x: x.id) if steers(p, person)
            and hearable(p.about, written(p), person, aud.level, aud.witness_level, aud.private_ok)]
    if not mine:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.none"))
    texts = _contents(ctx, [p.title_ref for p in mine])
    rows = [(p.id, texts.get(p.title_ref, "")) for p in mine]
    pid = _which(args.project, rows)
    if pid is None:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.which_project", listed=_listed(
            rows, phrase("projects.tools.steer.untitled"))))
    p = s.projects[pid]
    title = phrase("projects.tools.steer.quoted", text=texts[p.title_ref]) if texts.get(p.title_ref) else \
        phrase("projects.tools.steer.numbered", id=p.id)
    if args.what == NOW:
        return await _steer_now(args, ctx, s, p, person, title)
    if args.what == PAUSE:
        if p.status == c.PAUSED:
            return phrase("projects.tools.steer.already_paused", title=title)
        draft = PAUSED.draft(project=p.id, reason=PAUSED_IN_TALK, by=person, owner=p.owner, about=p.about)
        if await _steered(ctx, draft, _in_state(p.id, (c.ACTIVE,))) is None:
            return _changed()
        return phrase("projects.tools.steer.paused", title=title)
    if args.what == RESUME:
        if p.status == c.ACTIVE:
            return phrase("projects.tools.steer.not_paused", title=title)
        draft = RESUMED.draft(project=p.id, by=person, owner=p.owner, about=p.about)
        if await _steered(ctx, draft, _in_state(p.id, (c.PAUSED,))) is None:
            return _changed()
        return phrase("projects.tools.steer.resumed", title=title)
    text = args.text.strip()
    if not text:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.no_objective") if args.what == ADD
                          else phrase("projects.tools.steer.no_instruction"))
    if args.what == INSTRUCT:
        draft = AMENDED.draft(project=p.id, instruction=Content.of(text, level=p.sensitivity), by=person,
                              owner=p.owner, about=p.about)
        if await _steered(ctx, draft, _in_state(p.id, STEERABLE)) is None:
            return _changed()
        return phrase("projects.tools.steer.instructed", title=title)
    if len(text) > 500:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.too_long"))
    if living(p) >= OBJECTIVES_KEPT:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.full", title=title, count=OBJECTIVES_KEPT))
    number = p.objective_seq + 1
    commit = await _steered(ctx, OBJECTIVE_ADDED.draft(
        project=p.id, objective=number, text=Content.of(text, level=written(p)), kind=args.kind,
        cadence_us=args.cadence_hours * HOUR if args.kind == c.CONSTANT else 0, author="owner", by=person,
        owner=p.owner, about=p.about), _in_state(p.id, STEERABLE))
    if commit is None:
        return _changed()
    number = _attributed(ctx, p.id, commit, "text", "objectives", number)
    kind = phrase("projects.tools.objective_add.constant") if args.kind == c.CONSTANT else \
        phrase("projects.tools.objective_add.once")
    return phrase("projects.tools.steer.added", id=number, title=title, kind=kind)


async def _steer_now(args: SteerArgs, ctx: Any, s: ProjectsState, p: Project, person: str, title: str) -> Any:
    """« Mets-toi sur ton projet maintenant » : comme « Lancer maintenant » dans la console — sous les plafonds,
    jamais pendant son sommeil en mode Mika."""
    frame: Frame = ctx.frame
    if p.status != c.ACTIVE:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.now_paused", title=title))
    o: Objective | None = None
    if args.objective.strip():
        opened = [x for x in p.objectives if x.status == c.OPEN]
        if not opened:
            return ToolResult(ok=False, content=phrase("projects.tools.steer.no_open", title=title))
        texts = _contents(ctx, [x.text_ref for x in opened])
        rows = [(x.id, texts.get(x.text_ref, "")) for x in opened]
        oid = _which(args.objective, rows)
        if oid is None:
            return ToolResult(ok=False, content=phrase("projects.tools.steer.which_objective", listed=_listed(
                rows, phrase("projects.tools.steer.forgotten"))))
        o = objective_at(p, oid)
    if busy(s, p.id):
        return phrase("projects.tools.steer.busy", title=title)
    if nudged(p) and (o is None or p.nudged_objective == o.id):
        return phrase("projects.tools.steer.already_asked", title=title)
    if outgoing(p, frame.now):
        return ToolResult(ok=False, content=phrase("projects.tools.steer.outgoing"))
    pm = params(frame.env.params_of("projects", frame.root))
    if o is None and pick(p, frame.now, pm) is None \
            and not any(x.status == c.OPEN and x.kind == c.CONSTANT for x in p.objectives):
        return ToolResult(ok=False, content=phrase("projects.tools.steer.nothing_open", title=title))
    guard = _in_state(p.id, (c.ACTIVE,)) if o is None else _in_state(p.id, (c.ACTIVE,)) & still_open(p.id, o.id)
    draft = NUDGED.draft(project=p.id, objective=o.id if o is not None else 0, by=person, owner=p.owner,
                         about=p.about)
    if await _steered(ctx, draft, guard) is None:
        return _changed()
    on = phrase("projects.tools.steer.on_objective", id=o.id) if o is not None else ""
    return phrase("projects.tools.steer.asked", title=title, on=on)
