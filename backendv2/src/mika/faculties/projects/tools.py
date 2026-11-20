"""Les outils des projets.

Pendant une exécution (``WORK`` ou ``JOB``) : ``report_run`` (le verdict, qui la
clôt), ``project_note`` (son carnet), ``project_decide`` (une décision
technique, qui peut en remplacer une autre), ``project_objective_add`` (un
objectif de plus), ``project_plan`` (son plan : ce qui conclut une séance de
cadrage, ou le revoir en cours de route — ADR 0145). En conversation :
``create_project`` (un projet qu'on lui
confie — seulement quelqu'un qui s'occupe d'elle), ``start_project`` (un
projet à elle — aussi pendant une exploration qui s'avère plus grosse qu'une
envie). Partout : ``project_close`` (clore un projet à elle). Le pilotage de
vive voix (``project_steer`` : un objectif de plus, une consigne, s'y mettre
maintenant, la pause, la reprise — jamais son cadre) vit dans ``steer.py``,
qui lit les aides d'ici (``speaker``, ``their_words``, ``contents_of``…).

**Ce qu'un projet lit des autres** (ADR 0257) se demande ici de deux façons :
``create_project`` le pose d'emblée (``reads`` : qui le confie en est le
propriétaire), et ``project_plan`` le demande (``reads``) — le lien se pose
alors quand le propriétaire du projet valide le plan. Les règles sont dans
``links.py``.

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
from sqlalchemy import select

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.projects import links
from mika.faculties.projects.faculty import (
    ARCHIVED,
    DECIDED,
    DECISIONS_KEPT,
    DEFAULT_BUNDLES,
    LINKS_MAX,
    LINKS_SET,
    NOTED,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    OBJECTIVES_KEPT,
    PLAN_PROPOSED,
    PROJECTS,
    PUSH_CAPABILITY,
    REFRAMED,
    SELF_BUNDLES,
    Objective,
    Project,
    ProjectsState,
    check_schedule,
    decision_at,
    frame_of,
    in_force,
    live,
    living,
    objective_at,
    objective_of,
    objectives_of,
    opened,
    params,
    written,
)
from mika.faculties.projects.rhythm import cadence
from mika.kernel.clock import HOUR
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import ToolResult, proving_tools
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.vocab.episodes import PROJECT_KINDS, Kind, goal_of, goal_target, project_of, project_target
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import stems

REPORT, NOTE, DECIDE, OBJECTIVE_ADD = "report_run", "project_note", "project_decide", "project_objective_add"
EQUIP = "project_equip"
#: ce qui change quelque chose (le compte rendu le dit) : écrire, modifier, un programme qui a réussi, un
#: brouillon, une app forgée
CHANGING = frozenset({"ws_write", "ws_edit", "ws_run", "email_draft", "forge_write", "forge_edit"})
#: hors de l'atelier (où c'est le commit), ce qui **prouve** qu'une exécution a produit se déclare sur l'outil
#: (``ToolResult.proof`` : un brouillon, une app essayée qui marche — ADR 0104) : aucun nom ici
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


#: ce qu'on garde des mots de qui parle (ADR 0145) : ses derniers messages avant sa réponse, au plus
REQUEST_CHARS, REQUEST_LINES = 2000, 8


def their_words(ctx: Any) -> str:
    """Les mots de la personne à qui elle répond, tels quels : ses messages en privé depuis la dernière réponse de
    Mika, jusqu'à celui auquel elle répond, du plus ancien au plus récent — ce qu'un projet garde de sa demande, ce
    qu'une consigne garde de sa voix (ADR 0145). Rien hors d'une réponse, ni dans un salon."""
    store = ctx.ports.get("store")
    ep = ctx.frame.episode
    if store is None or ep is None or ep.kind != Kind.REPLY or not ep.target or ep.attrs.get("room"):
        return ""
    person = ctx.frame.get(identity_c.PERSON(ep.target))
    handles = list(ctx.frame.get(identity_c.HANDLES(person)) or ()) if person else []
    t = transcript_c.thread_table()
    query = select(t.c.role, t.c.text).where(t.c.person.in_(handles or [ep.target]), t.c.room.is_(None))
    upto = ep.attrs.get("reply_to")
    if isinstance(upto, int):
        query = query.where(t.c.id <= upto)
    said: list[str] = []
    for role, text in store.query_mind(query.order_by(t.c.id.desc()).limit(REQUEST_LINES * 2)):
        if role != "user":
            break  # sa dernière réponse : ce qui précède a déjà eu la sienne
        if str(text or "").strip():
            said.append(str(text).strip())
        if len(said) >= REQUEST_LINES:
            break
    return "\n".join(reversed(said))[-REQUEST_CHARS:]


#: ce qu'un projet garde de la conversation où il a été demandé (ADR 0161) : ses derniers messages, tant qu'ils se
#: suivent (une pause plus longue ouvre une autre conversation), et au plus tant de caractères
EXCHANGE_LINES, EXCHANGE_GAP, EXCHANGE_CHARS = 16, 2 * HOUR, 3000


def exchange(ctx: Any, person: str | None, handles: list[str], *, upto: int | None = None,
             upto_at: int | None = None) -> str:
    """La conversation en privé qui a mené à une demande, telle qu'elle s'est dite : les messages de la personne et
    les siens, du plus ancien au plus récent, jusqu'au message ``upto`` (ou à l'instant ``upto_at``) — une demande se
    précise souvent en plusieurs échanges, et son dernier message seul n'en garde qu'un bout (ADR 0161)."""
    store = ctx.ports.get("store")
    if store is None or not handles:
        return ""
    t = transcript_c.thread_table()
    query = select(t.c.role, t.c.text, t.c.at).where(t.c.person.in_(handles), t.c.room.is_(None))
    if upto is not None:
        query = query.where(t.c.id <= upto)
    if upto_at is not None:
        query = query.where(t.c.at <= upto_at)
    name = identity_c.person_name(ctx.frame, person or "") or phrase("projects.request.them")
    said: list[str] = []
    size, after = 0, None
    for role, text, at in store.query_mind(query.order_by(t.c.id.desc()).limit(EXCHANGE_LINES)):
        if after is not None and after - at > EXCHANGE_GAP:
            break
        after = at
        text = str(text or "").strip()
        if not text:
            continue
        who = name if role == "user" else phrase("projects.request.you")
        line = phrase("projects.request.line", who=who, text=text)
        if said and size + len(line) > EXCHANGE_CHARS:
            break
        said.append(line)
        size += len(line) + 1
    return "\n".join(reversed(said))[-EXCHANGE_CHARS:]


def their_request(ctx: Any) -> str:
    """Ce qu'un projet ouvert en réponse garde de sa demande : la conversation qui y a mené, jusqu'au message
    auquel elle répond (``exchange``) — rien hors d'une réponse, ni dans un salon."""
    ep = ctx.frame.episode
    if ep is None or ep.kind != Kind.REPLY or not ep.target or ep.attrs.get("room"):
        return ""
    person = ctx.frame.get(identity_c.PERSON(ep.target))
    handles = list(ctx.frame.get(identity_c.HANDLES(person)) or ()) if person else []
    upto = ep.attrs.get("reply_to")
    return exchange(ctx, person, handles or [ep.target], upto=upto if isinstance(upto, int) else None)


def framing_run(ctx: Any, p: Project) -> bool:
    """Cette exécution est-elle la séance de cadrage de ``p`` (ADR 0145) ?"""
    ep = ctx.frame.episode
    return ep is not None and p.plan_state == c.TO_FRAME and frame_of(ep.attrs.get("subject")) == p.id


def text_of(ctx: Any, ref: str, level: int, empty: str) -> Content:
    store = ctx.ports.get("store")
    text = store.content([ref]).get(ref) if store is not None and ref else None
    return Content.of(text or empty, level=level)


def contents_of(ctx: Any, refs: list[str]) -> Mapping[str, str]:
    """Les textes gardés de ces références, lus d'un coup (les références vides écartées)."""
    store = ctx.ports.get("store")
    wanted = [r for r in refs if r]
    return store.content(wanted) if store is not None and wanted else {}


def named_projects(ctx: Any, s: ProjectsState, ids: tuple[int, ...]) -> str:
    """Des projets nommés à la suite (« n° 3 « Le produit », n° 5 « Le site » ») : ce qu'un lien pose (ADR 0257)."""
    found = [s.projects[i] for i in ids if i in s.projects]
    texts = contents_of(ctx, [t.title_ref for t in found])
    return ", ".join(phrase("projects.links.named", id=t.id,
                            title=texts.get(t.title_ref) or phrase("projects.run.no_title")) for t in found)


def refused_lines(refused: tuple[tuple[int, str], ...]) -> str:
    """Les projets qu'un lien ne peut pas viser, un par ligne, chacun avec sa raison (``links.refusal``)."""
    words = family("projects.links.refused")
    return "\n".join(phrase("projects.links.refused_line", id=t, why=words[why]) for t, why in refused)


def caretaker(frame: Frame) -> str:
    """Qui s'occupe d'elle, par son prénom (jamais « ta propriétaire »)."""
    return identity_c.keepers(frame, quoted=True)


def gone() -> str:
    """La réponse de chaque outil d'exécution quand le projet n'est plus actif."""
    return phrase("projects.tools.gone")


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
    how_met: str = Field(default="", max_length=600, description=phrase("projects.tools.report.how_met"))


def _proof(ctx: Any, sha: str, o: Objective | None = None) -> str:
    """Ce qui prouve que cette exécution a produit : un commit non vide, sinon un brouillon ou une app réussis. Une
    réparation d'app (ADR 0104) ne se prouve que par l'app réécrite et essayée : un fichier de l'atelier ne répare
    rien."""
    tool = "outil" if proving_tools(ctx.calls, getattr(ctx, "proofs", ()), lambda name: False) else ""
    if o is not None and o.app:
        return tool
    return "commit" if sha else tool


#: ce qui ne regarde rien de réel : tenir le projet, lister, lire un guide — un passage qui n'a fait que ça n'a rien
#: vu (ADR 0161)
BOOKKEEPING = frozenset({REPORT, NOTE, DECIDE, OBJECTIVE_ADD, EQUIP, "project_plan", "forge_help", "forge_list",
                         "ws_list"})


def consulted(ctx: Any) -> bool:
    """Le passage a-t-il regardé quelque chose de réel (une base, une app, un fichier, le web) ?"""
    return any(ok and name not in BOOKKEEPING for name, ok in ctx.calls)


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


@PROJECTS.tool(REPORT, acts=True, description=phrase("projects.tools.report.description"), label=phrase("projects.tools.report.label"), args=ReportArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=3, ends_loop=True)
async def report_run(args: ReportArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return gone()
    if any(name == REPORT and ok for name, ok in ctx.calls):
        return ToolResult(ok=False, content=phrase("projects.tools.report.already"))
    p, o = got
    if framing_run(ctx, p):  # une séance de cadrage conclut par son plan (ADR 0145)
        return ToolResult(ok=False, content=phrase("projects.tools.report.framing"))
    how = args.how_met.strip()
    if args.verdict == c.DONE and o is not None and o.kind == c.ONCE and o.done_when_ref and not how:
        criterion = contents_of(ctx, [o.done_when_ref]).get(o.done_when_ref, "")
        return ToolResult(ok=False, content=phrase("projects.tools.report.how_met_missing", criterion=criterion))
    worked = tuple(sorted({name for name, ok in ctx.calls if ok and name in CHANGING}))
    summary = args.summary.strip()
    if how:
        summary = f"{summary}\n{phrase('projects.tools.report.met', how=how)}"[:2000]
    port = ctx.ports.get("workshop")
    sha = ""
    if port is not None and port.exists(p.id):
        sha = await port.commit(p.id, commit_message(p, o))  # un commit par exécution qui a changé quelque chose
    proof = _proof(ctx, sha, o)
    closed = o is not None and o.status != c.OPEN  # retiré ou clos pendant qu'elle y travaillait
    # un ponctuel se prouve par ce qu'il a produit, dans cette exécution ou une d'avant ; le passage d'un constant
    # (un bilan, une veille) par ce qu'il a regardé de réel dans celle-ci — son compte rendu est ce qu'il rend (ADR
    # 0161)
    earned = (o.evidence > 0 if o.kind == c.ONCE else consulted(ctx)) if o is not None else False
    proven = args.verdict == c.DONE and o is not None and not closed and (bool(proof) or earned)
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
            unseen = phrase("projects.tools.report.unseen") if args.verdict == c.DONE and not proven else ""
            return phrase("projects.tools.report.constant", hours=hours, kept=kept, pushed=pushed,
                          asked=asked) + unseen
        return phrase("projects.tools.report.constant_continue", kept=kept, pushed=pushed, asked=asked)
    if proven:
        return phrase("projects.tools.report.done", id=o.id, kept=kept, pushed=pushed)
    if args.verdict == c.BLOCKED:
        return phrase("projects.tools.report.blocked", id=o.id, kept=kept, asked=asked)
    if args.verdict == c.WAIT:
        return phrase("projects.tools.report.wait", minutes=max(10, args.wait_minutes), kept=kept, asked=asked)
    return phrase("projects.tools.report.continue", kept=kept, pushed=pushed, asked=asked)


def closing(ctx: Any, p: Project, o: Objective, status: str, result: str, notable: float) -> Draft[Any]:
    # ce qu'il en reste se dit au niveau du projet — et au moins à celui de ce qu'il a lu des autres (ADR 0257)
    level = max(p.sensitivity, p.read_level)
    return c.OBJECTIVE_CLOSED.draft(
        project=p.id, objective=o.id, status=status, mode=p.mode, authority=p.authority,
        title=text_of(ctx, o.text_ref, level, phrase("projects.tools.report.forgotten")),
        result=Content.of(result, level=written(p)) if result else None, notable=notable if status == c.DONE
        else 0.0, owner=p.owner, about=p.about, sensitivity=level)


async def pinned(port: Any, project: int) -> tuple[str, str]:
    """Le commit courant de l'atelier et son titre : ce qu'un envoi approuvé enverra, et rien d'autre."""
    sha = await port.head(project) if port is not None and port.exists(project) else ""
    commits = await port.commits(project, 1) if sha else []
    return sha, commits[0].title if commits else ""


def push_summary(p: Project, sha: str, title: str, why: str) -> str:
    return (f"Pousser le commit {sha[:12]} (« {title[:120]} ») vers {p.remote}, branche {p.branch} — {why}")[:600]


def pending_push(frame: Frame, project: int) -> bool:
    """Un envoi de ce projet attend-il déjà un accord ?"""
    return any(v.capability == PUSH_CAPABILITY and project_of(v.context) == project
               for v in frame.get(rt.PENDING_EFFECTS))


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
        capability=PUSH_CAPABILITY, owner=PROJECTS.name, context=project_target(p.id), approval=p.approval,
        args_json=json.dumps({"project": p.id, "url": p.remote, "branch": p.branch, "sha": sha}),
        summary=Content.of(push_summary(p, sha, title, why), level=0), about=tuple(x for x in (p.owner, *p.about) if x)))
    return "proposed" if p.approval else "sent"


class NoteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description=phrase("projects.tools.note.text"))


@PROJECTS.tool(NOTE, acts=True, description=phrase("projects.tools.note.description"), label=phrase("projects.tools.note.label"), args=NoteArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=4)
async def project_note(args: NoteArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return gone()
    p, o = got
    await ctx.emit(NOTED.draft(project=p.id, text=Content.of(args.text.strip(), level=written(p)), owner=p.owner,
                               about=p.about, objective=o.id if o is not None else 0))
    return phrase("projects.tools.note.done")


class DecideArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200, description=phrase("projects.tools.decide.title"))
    choice: str = Field(min_length=1, max_length=1500, description=phrase("projects.tools.decide.choice"))
    context: str = Field(default="", max_length=2000, description=phrase("projects.tools.decide.context"))
    options: str = Field(default="", max_length=2000, description=phrase("projects.tools.decide.options"))
    reason: str = Field(default="", max_length=1500, description=phrase("projects.tools.decide.reason"))
    replaces: int = Field(default=0, ge=0, description=phrase("projects.tools.decide.replaces"))


@PROJECTS.tool(DECIDE, acts=True, description=phrase("projects.tools.decide.description"), label=phrase("projects.tools.decide.label"), args=DecideArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=4)
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
    return phrase("projects.tools.decide.done",
                               id=attributed(ctx, p.id, commit, "title", "decisions", number), more=more)


class ObjectiveArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500, description=phrase("projects.tools.objective_add.text"))
    kind: Literal["once", "constant"] = Field(default="once", description=phrase("projects.tools.objective_add.kind"))
    cadence_hours: int = Field(default=0, ge=0, le=24 * 30,
                               description=phrase("projects.tools.objective_add.cadence_hours"))


@PROJECTS.tool(OBJECTIVE_ADD, acts=True, description=phrase("projects.tools.objective_add.description"),
               label=phrase("projects.tools.objective_add.label"), args=ObjectiveArgs,
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
    number = attributed(ctx, p.id, commit, "text", "objectives", number)
    kind = phrase("projects.tools.objective_add.constant") if args.kind == c.CONSTANT else \
        phrase("projects.tools.objective_add.once")
    return phrase("projects.tools.objective_add.done", id=number, kind=kind)


PLAN_TOOL = "project_plan"
#: les étapes d'un plan, ses questions, au plus
PLAN_STEPS, PLAN_QUESTIONS = 12, 3


class PlanStep(BaseModel):
    """Une étape de son plan : un objectif, gardé (``keep``), réécrit ou nouveau."""

    text: str = Field(min_length=1, max_length=500, description=phrase("projects.tools.plan.step_text"))
    done_when: str = Field(default="", max_length=500, description=phrase("projects.tools.plan.done_when"))
    kind: Literal["once", "constant"] = Field(default="once", description=phrase("projects.tools.objective_add.kind"))
    cadence_hours: int = Field(default=0, ge=0, le=24 * 30,
                               description=phrase("projects.tools.constant.cadence_hours"))
    after: int = Field(default=0, ge=0, le=PLAN_STEPS, description=phrase("projects.tools.plan.after"))
    keep: int = Field(default=0, ge=0, description=phrase("projects.tools.plan.keep"))


class PlanQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=400, description=phrase("projects.tools.plan.question"))
    advice: str = Field(min_length=1, max_length=400, description=phrase("projects.tools.plan.advice"))


class PlanArgs(BaseModel):
    aim: str = Field(min_length=1, max_length=600, description=phrase("projects.tools.plan.aim"))
    deliverables: str = Field(min_length=1, max_length=1200, description=phrase("projects.tools.plan.deliverables"))
    approach: str = Field(min_length=1, max_length=2500, description=phrase("projects.tools.plan.approach"))
    out_of_scope: str = Field(default="", max_length=800, description=phrase("projects.tools.plan.out_of_scope"))
    steps: list[PlanStep] = Field(min_length=1, max_length=PLAN_STEPS, description=phrase("projects.tools.plan.steps"))
    questions: list[PlanQuestion] = Field(default_factory=list, max_length=PLAN_QUESTIONS,
                                          description=phrase("projects.tools.plan.questions"))
    tell: bool = Field(default=False, description=phrase("projects.tools.plan.tell"))
    #: les projets que ce plan demande à lire (ADR 0257) : le lien se pose quand le propriétaire le valide
    reads: list[int] = Field(default_factory=list, max_length=LINKS_MAX,
                             description=phrase("projects.tools.plan.reads"))


def plan_text(args: PlanArgs) -> str:
    """Son plan en clair, tel qu'il se relit (exécutions, récit, console)."""
    lines = [phrase("projects.plan.aim", text=args.aim.strip()),
             phrase("projects.plan.deliverables", text=args.deliverables.strip()),
             phrase("projects.plan.approach", text=args.approach.strip())]
    if args.out_of_scope.strip():
        lines.append(phrase("projects.plan.out_of_scope", text=args.out_of_scope.strip()))
    return "\n".join(lines)


def questions_text(args: PlanArgs) -> str:
    return "\n".join(phrase("projects.plan.question", n=i, question=q.question.strip(), advice=q.advice.strip())
                     for i, q in enumerate(args.questions, start=1))


def _plan_problems(p: Project, steps: list[PlanStep]) -> list[str]:
    """Ce qui ne va pas dans ses étapes, en mots (rien : il s'écrit)."""
    alive = {o.id for o in p.objectives if o.status in (c.OPEN, c.BLOCKED)}
    problems: list[str] = []
    kept: set[int] = set()
    for i, step in enumerate(steps, start=1):
        if step.kind == c.ONCE and not step.done_when.strip():
            problems.append(phrase("projects.tools.plan.no_criterion", n=i))
        if step.after and step.after >= i:
            problems.append(phrase("projects.tools.plan.bad_after", n=i))
        if step.keep and (step.keep not in alive or step.keep in kept):
            problems.append(phrase("projects.tools.plan.bad_keep", n=i, id=step.keep))
        kept.add(step.keep)
    return problems


def _read_problems(s: ProjectsState, p: Project, wanted: tuple[int, ...], world: links.World) -> list[str]:
    """Ce que son plan ne peut pas demander à lire, en mots (ADR 0257) : un projet que le sien ne peut pas lire
    (``links.refusal``), ou que la personne qui a demandé le projet ne peut pas voir — son plan le nommerait
    devant elle."""
    _, refused = links.chosen(s, p, (*p.reads, *wanted), world)
    why = dict(refused)
    askable = {t.id for t in links.askable(s, p, world)}
    words = family("projects.links.refused")
    problems = []
    for target in wanted:
        reason = why.get(target) or ("" if target in p.reads or target in askable else links.HIDDEN)
        if reason:
            problems.append(phrase("projects.tools.plan.bad_read", id=target, why=words[reason]))
    return problems


@PROJECTS.tool(PLAN_TOOL, acts=True, description=phrase("projects.tools.plan.description"),
               label=phrase("projects.tools.plan.label"), args=PlanArgs,
               bundle="projects", episodes=RUNS, max_calls_per_episode=2)
async def project_plan(args: PlanArgs, ctx: Any) -> Any:
    """Écrire son plan (une séance de cadrage), ou le revoir en cours de route (ADR 0145) : ses objectifs vivants
    deviennent ceux du plan — gardés, réécrits ou nouveaux, dans son ordre, chacun avec son critère et ce dont il
    dépend ; ceux qu'il ne garde pas sont retirés (sauf une réparation d'app). Un plan qui pose des questions sur un
    projet qu'on lui a demandé attend sa réponse ; sinon il vaut d'office. Ce qu'il demande à lire (``reads``, ADR
    0257) attend de même, quand qui répondra au plan en est le propriétaire : le lien se pose à sa validation."""
    got = current(ctx)
    if got is None:
        return gone()
    p, _ = got
    s: ProjectsState = ctx.frame.state("projects")
    world = links.world_of(ctx.frame)
    wanted = tuple(dict.fromkeys(args.reads))
    problems = [*_plan_problems(p, args.steps), *_read_problems(s, p, wanted, world)]
    if problems:
        return ToolResult(ok=False, content=phrase("projects.tools.plan.refused", problems="\n".join(problems)))
    kept = {s.keep for s in args.steps if s.keep}
    dropped = [o for o in p.objectives if o.status in (c.OPEN, c.BLOCKED) and o.id not in kept and not o.app]
    if living(p) - len(dropped) + sum(1 for s in args.steps if not s.keep) > OBJECTIVES_KEPT:
        return ToolResult(ok=False, content=phrase("projects.tools.objective_add.full", count=OBJECTIVES_KEPT))
    level = written(p)
    who: dict[str, Any] = {"owner": p.owner, "about": p.about}
    ids, number = [], p.objective_seq
    for step in args.steps:
        if step.keep:
            ids.append(step.keep)
        else:
            number += 1
            ids.append(number)
    drafts: list[Draft[Any]] = [OBJECTIVE_CHANGED.draft(
        project=p.id, objective=o.id, status=c.DROPPED, note=Content.of(phrase("projects.tools.plan.dropped"),
                                                                         level=level), **who) for o in dropped]
    for i, (step, oid) in enumerate(zip(args.steps, ids, strict=True), start=1):
        text = Content.of(step.text.strip(), level=level)
        done_when = Content.of(step.done_when.strip(), level=level) if step.done_when.strip() else None
        every = step.cadence_hours * HOUR if step.kind == c.CONSTANT else 0
        after = ids[step.after - 1] if step.after else 0
        if step.keep:
            old = objective_at(p, oid)
            reopened = c.OPEN if old is not None and old.status == c.BLOCKED else None  # un plan neuf, une chance neuve
            drafts.append(OBJECTIVE_CHANGED.draft(project=p.id, objective=oid, status=reopened, text=text,
                                                  kind=step.kind, cadence_us=every, done_when=done_when, after=after,
                                                  rank=i, **who))
        else:
            drafts.append(OBJECTIVE_ADDED.draft(project=p.id, objective=oid, text=text, kind=step.kind,
                                                cadence_us=every, done_when=done_when, after=after, rank=i,
                                                author="self", **who))
    framing_now = p.plan_state in (c.TO_FRAME, c.PROPOSED)
    asked = bool(p.asked_by)
    # ce qu'il demande à lire de nouveau attend, comme une question, quand qui répondra peut poser le lien
    new_links = tuple(t for t in wanted if t not in p.reads)
    linking = bool(new_links) and links.may_link(p, p.asked_by or "", world)
    approved = not framing_now or not asked or not (args.questions or linking)
    tell = asked if framing_now else args.tell
    questions = questions_text(args)
    drafts.append(PLAN_PROPOSED.draft(project=p.id, plan=Content.of(plan_text(args), level=level),
                                      questions=Content.of(questions, level=level) if questions else None,
                                      approved=approved, tell=tell, reads=wanted, **who))
    await ctx.emit(*drafts)
    # ce qu'il demande à lire : lié à la validation de son propriétaire, sinon à poser dans la console
    reading = "" if not new_links else phrase("projects.tools.plan.reads_wait") if linking and not approved \
        else phrase("projects.tools.plan.reads_later")
    if not framing_now:
        return phrase("projects.tools.plan.revised", steps=len(args.steps), dropped=len(dropped)) + reading
    # le plan conclut sa séance de cadrage : la boucle s'arrête là (ADR 0161)
    if not approved:
        return ToolResult(content=phrase("projects.tools.plan.waits", steps=len(args.steps)) + reading, ends=True)
    return ToolResult(content=phrase("projects.tools.plan.starts", steps=len(args.steps)) + reading, ends=True)


class EquipArgs(BaseModel):
    tool: SelfBundle = Field(description=phrase("projects.tools.equip.tool"))
    why: str = Field(min_length=1, max_length=300, description=phrase("projects.tools.equip.why"))


@PROJECTS.tool(EQUIP, acts=True, description=phrase("projects.tools.equip.description"),
               label=phrase("projects.tools.equip.label"), args=EquipArgs, bundle="projects",
               episodes=RUNS, max_calls_per_episode=2)
async def project_equip(args: EquipArgs, ctx: Any) -> Any:
    """Se donner un lot de plus, sur un projet à elle (``SELF_BUNDLES``) : en main à l'exécution suivante — les
    outils d'une exécution sont fixés quand elle commence. Un projet confié garde le cadre qu'on lui a donné : elle
    le demande (``needs_you``)."""
    got = current(ctx)
    if got is None:
        return gone()
    p, _ = got
    if p.authority != c.SELF:
        return ToolResult(ok=False, content=phrase("projects.tools.equip.confided"))
    words = family("projects.bundle_words")[args.tool]
    if args.tool in p.bundles:
        return ToolResult(ok=False, content=phrase("projects.tools.equip.already", what=words))
    level = written(p)
    await ctx.emit(REFRAMED.draft(project=p.id, bundles=(*p.bundles, args.tool), owner=p.owner, about=p.about),
                   NOTED.draft(project=p.id, owner=p.owner, about=p.about, text=Content.of(
                       phrase("projects.tools.equip.note", what=words, why=args.why.strip()), level=level)))
    return phrase("projects.tools.equip.done", what=words)


def attributed(ctx: Any, project: int, commit: Any, field: str, kind: str, asked: int) -> int:
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


def speaker(frame: Frame) -> tuple[str, str] | None:
    """Qui lui parle, en réponse : son adresse et sa personne (``None`` hors d'une réponse)."""
    ep = frame.episode
    if ep is None or not ep.target or ep.kind != Kind.REPLY:
        return None
    return ep.target, frame.get(identity_c.PERSON(ep.target))


class ConstantArg(BaseModel):
    """Un constant et sa cadence, dès la création : un bilan de la semaine ne revient pas chaque jour (ADR 0144)."""
    text: str = Field(min_length=1, max_length=500, description=phrase("projects.tools.constant.text"))
    cadence_hours: int = Field(default=0, ge=0, le=24 * 30, description=phrase("projects.tools.constant.cadence_hours"))


def _constants(xs: list[str | ConstantArg]) -> list[str | tuple[str, int]]:
    """Les constants d'un outil, tels que ``objectives_of`` les lit : un texte, ou un texte et sa cadence en µs."""
    return [(x.text, x.cadence_hours * HOUR) if isinstance(x, ConstantArg) else x for x in xs]


#: un lot qu'elle peut se donner (``SELF_BUNDLES``, dans le même ordre : un test les garde égaux)
SelfBundle = Literal["memory", "rss", "forge", "forge_apps"]


class CreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000,
                             description=phrase("projects.tools.create.description_arg"))
    objectives: list[str] = Field(default_factory=list, max_length=12,
                                  description=phrase("projects.tools.create.objectives"))
    constants: list[str | ConstantArg] = Field(default_factory=list, max_length=12,
                                               description=phrase("projects.tools.create.constants"))
    mode: Literal["persona", "plain"] = Field(default="persona", description=phrase("projects.tools.create.mode"))
    schedule: str = Field(default="asap", description=phrase("projects.tools.create.schedule"))
    #: ce qu'il aura en main, choisi avec qui le confie — la Forge pour une app (ADR 0161)
    tools: list[SelfBundle] = Field(default_factory=list, max_length=4, description=phrase("projects.tools.create.tools"))
    #: ses autres projets que celui-ci lira (ADR 0257) : qui le confie en est le propriétaire, c'est lui qui pose le lien
    reads: list[int | str] = Field(default_factory=list, max_length=LINKS_MAX,
                                   description=phrase("projects.tools.create.reads"))


def _pointed(said: str, rows: list[tuple[int, str]]) -> int | None:
    """Le projet qu'elle nomme pour un lien : son numéro tel quel, sinon le seul dont le titre partage le plus de
    mots avec ce qu'elle en dit — jamais « le seul qu'il y a » : un lien ne se devine pas."""
    raw = said.strip().lower().removeprefix("n°").removeprefix("#").strip()
    if raw.isdigit():
        return int(raw)
    said_stems = stems(said)
    scored = [(len(said_stems & stems(text)), i) for i, text in rows]
    best = max((n for n, _ in scored), default=0)
    top = [i for n, i in scored if n == best]
    return top[0] if best and len(top) == 1 else None


async def _read_from_birth(ctx: Any, project: int, person: str, asked: list[int | str]) -> str:
    """Ce qu'un projet confié lit dès sa naissance (ADR 0257) : qui le confie en est le propriétaire, et le demande
    en face. Un projet qu'on ne reconnaît pas, ou qui ne peut pas être lu, n'empêche pas le projet de naître : la
    réponse le dit, et le lien se pose plus tard sur sa fiche."""
    s: ProjectsState = ctx.frame.state("projects")
    p = s.projects.get(project)
    world = links.world_of(ctx.frame)
    if p is None or not links.may_link(p, person, world):
        return ""
    options = links.candidates(s, p, world)
    texts = contents_of(ctx, [t.title_ref for t in options])
    rows = [(t.id, texts.get(t.title_ref, "")) for t in options]
    found: list[int] = []
    unknown = ""
    for words in map(str, asked):
        target = _pointed(words, rows)
        if target is None:
            unknown += phrase("projects.tools.create.link_unknown", said=words.strip()[:80])
        else:
            found.append(target)
    kept, refused = links.chosen(s, p, found, world)
    said = ""
    if kept:
        await ctx.emit(LINKS_SET.draft(project=p.id, reads=kept, by=person))
        said = phrase("projects.tools.create.linked", projects=named_projects(ctx, s, kept))
    if refused:
        said += phrase("projects.tools.create.link_refused", refused=refused_lines(refused))
    return said + unknown


@PROJECTS.tool("create_project", acts=True, description=phrase("projects.tools.create.description"), label=phrase("projects.tools.create.label"), args=CreateArgs, bundle="projects", episodes=[Kind.REPLY], max_calls_per_episode=1, owner_only=True)
async def create_project(args: CreateArgs, ctx: Any) -> Any:
    who = speaker(ctx.frame)
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
        address=handle, about=(person,), level=level, source="tool", schedule_rule=rule, request=their_request(ctx),
        asked_by=person, framing=True, bundles=own_bundles(args.tools)))
    pid = commit.seqs[-1] if commit.seqs else None
    if pid is None:
        return ToolResult(ok=False, content=phrase("projects.tools.create.failed"))
    goals = args.objectives or ([] if args.constants else [args.title])
    await ctx.emit(*objectives_of(pid, goals, _constants(args.constants), author="owner", owner=person,
                                  about=(person,), level=level))
    reading = await _read_from_birth(ctx, pid, person, args.reads) if args.reads else ""
    return phrase("projects.tools.create.done", id=pid) + reading


class StartArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000, description=phrase("projects.tools.start.description_arg"))
    objectives: list[str] = Field(default_factory=list, max_length=12,
                                  description=phrase("projects.tools.start.objectives"))
    constants: list[str | ConstantArg] = Field(default_factory=list, max_length=12,
                                               description=phrase("projects.tools.start.constants"))
    tools: list[SelfBundle] = Field(default_factory=list, max_length=4, description=phrase("projects.tools.start.tools"))


def own_bundles(*sources: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Les lots d'un projet à elle : ceux de tout projet, plus ce qu'elle s'est donné parmi ``SELF_BUNDLES`` (ses
    outils, ceux de l'exploration d'où il naît) — rien d'autre ne passe."""
    wanted = {b for src in sources for b in src}
    return tuple(dict.fromkeys((*DEFAULT_BUNDLES, *(b for b in SELF_BUNDLES if b in wanted))))


def _own_live(s: ProjectsState) -> int:
    """Ses projets à elle qui l'occupent encore : vivants **et** avec un objectif ouvert (un projet dont tout est
    fait ne l'empêche pas d'en ouvrir un autre). Un projet qu'on lui a demandé n'en est pas un : ce plafond garde ses
    heures creuses de ses propres envies, jamais d'une demande de qui s'occupe d'elle (ADR 0161)."""
    return sum(1 for p in s.projects.values() if live(p) and p.authority == c.SELF and not p.asked_by
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
    return speaker(frame) is not None and owner_speaks(frame)


@PROJECTS.tool("start_project", acts=True, description=phrase("projects.tools.start.description"),
               label=phrase("projects.tools.start.label"), args=StartArgs, bundle="projects",
               episodes=[Kind.REPLY, Kind.STEP], max_calls_per_episode=1, owner_only=True)
async def start_project(args: StartArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    s: ProjectsState = frame.state("projects")
    pm = params(frame.env.params_of("projects", frame.root))
    ep = frame.episode
    who = speaker(frame)
    # en conversation, seulement avec quelqu'un qui s'occupe d'elle : un inconnu ne fixe pas le travail de ses
    # heures creuses
    if not _talking_to_owner(frame):
        return ToolResult(ok=False, content=phrase("projects.tools.start.stranger"))
    asking = ep is not None and ep.kind == Kind.REPLY  # en réponse : qui lui parle le lui demande
    gid = goal_of(ep.target) if ep is not None else None
    source = goal_target(gid) if gid is not None else "conversation"
    twin = next((p for p in s.projects.values() if live(p) and gid is not None and p.source == source), None)
    if twin is not None:
        return ToolResult(ok=False, content=phrase("projects.tools.start.twin", id=twin.id))
    about: tuple[str, ...] = (who[1],) if who is not None else ()
    level = int(Sensitivity.PERSONAL) if about else int(Sensitivity.NONE)
    inherited: tuple[str, ...] = ()
    # en conversation, il naît à cadrer, avec la conversation qui l'a demandé (ADR 0145, 0161)
    request, asked_by = (their_request(ctx), who[1] if who is not None else None) if asking else ("", None)
    if gid is not None:
        goal = next((g for g in frame.get(goals_c.LIVE) if g.id == gid), None)
        about = goal.about if goal is not None else ()
        # ce que le but disait d'autrui reste au moins aussi protégé dans le projet
        level = max(goal.sensitivity if goal is not None else 0, int(Sensitivity.PERSONAL) if about else 0)
        # l'exploration devenue projet garde ses mains (la Forge d'une app à réparer, ses flux…)
        inherited = goal.bundles if goal is not None else ()
        if goal is not None and goal.origin == goals_c.FROM_PROMISE and goal.owner:
            # une promesse de travail faite à quelqu'un : il l'a demandé — à cadrer, avec la conversation qui y a
            # mené, comme en réponse (ADR 0161) ; une exploration à elle a déjà réfléchi
            handles = list(frame.get(identity_c.HANDLES(goal.owner)) or (goal.owner,))
            request = exchange(ctx, goal.owner, handles, upto_at=goal.origin_at or None)
            asked_by = goal.owner
    if asked_by is None and _own_live(s) >= pm.live_self_max:
        return ToolResult(ok=False, content=phrase("projects.tools.start.too_many", count=_own_live(s),
                                                   max=pm.live_self_max))
    commit = await ctx.emit(opened(
        title=args.title, description=args.description, authority=c.SELF, mode=c.PERSONA, owner=None, address=None,
        about=about, level=level, source=source, bundles=own_bundles(args.tools, inherited), request=request,
        asked_by=asked_by, framing=asking or asked_by is not None))
    pid = commit.seqs[-1] if commit.seqs else None
    if pid is None:
        return ToolResult(ok=False, content=phrase("projects.tools.start.failed"))
    goals = args.objectives or ([] if args.constants else [args.title])
    await ctx.emit(*objectives_of(pid, goals, _constants(args.constants), author="self", owner=None, about=about,
                                  level=level))
    if gid is not None and asked_by is None:
        return phrase("projects.tools.start.done", id=pid, more=phrase("projects.tools.start.from_goal"))
    more = phrase("projects.tools.start.from_goal") if gid is not None else ""
    return phrase("projects.tools.start.framing", id=pid) + more


class CloseArgs(BaseModel):
    project: int = Field(ge=1, description=phrase("projects.tools.close.project"))
    ending: Literal["done", "dropped"] = Field(description=phrase("projects.tools.close.ending"))
    why: str = Field(min_length=1, max_length=600, description=phrase("projects.tools.close.why"))


ENDING_REASON = {"done": "clos par elle : il a fait son temps", "dropped": "clos par elle : elle y renonce"}


@PROJECTS.tool("project_close", acts=True, description=phrase("projects.tools.close.description"),
               label=phrase("projects.tools.close.label"), args=CloseArgs, bundle="projects",
               episodes=[Kind.REPLY, Kind.STEP, *RUNS],
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
