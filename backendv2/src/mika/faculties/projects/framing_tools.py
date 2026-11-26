"""Le cadrage d'un projet (ADR 0145, 0161) : l'outil ``project_plan``, ses arguments et ses règles.

Sa séance de cadrage écrit son plan avec ``project_plan``, qui la conclut et arrête la boucle ; en cours de route, il
le revoit. Ses objectifs vivants deviennent ceux du plan — gardés, réécrits ou nouveaux, dans son ordre, chacun avec
son critère et ce dont il dépend ; ceux qu'il ne garde pas sont retirés (sauf une réparation d'app). Un plan qui pose
des questions sur un projet qu'on lui a demandé attend sa réponse ; sinon il vaut d'office.

- **Ses arguments** (``PlanArgs``, ``PlanStep``, ``PlanQuestion``) : les jalons grossiers de chaque étape
  (``PlanStep.milestones``, des ``reaching.MilestoneArg``, ADR 0273), la liste de passage d'un constant
  (``each_pass``), ce qui le déclenche (``on``, ADR 0265), les projets que le plan demande à lire (``reads``,
  ADR 0257 : le lien se pose quand le propriétaire le valide).
- **Ses règles** (``_plan_problems``, ``_read_problems``) : ce qui ne va pas dans ses étapes, et ce qu'il ne peut pas
  demander à lire — refusé en mots, rien ne s'écrit.
- **Son texte** (``plan_text``, ``questions_text``), tel qu'il se relit.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.faculties.projects import links, milestones, triggers
from mika.faculties.projects.faculty import (
    LINKS_MAX,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    OBJECTIVES_KEPT,
    PLAN_PROPOSED,
    PROJECTS,
    ROUTINE_LINE_MAX,
    ROUTINE_LINES,
    Project,
    ProjectsState,
    living,
    milestones_of,
    objective_at,
    subjects_of,
    written,
)
from mika.faculties.projects.reaching import MilestoneArg, bad_milestone
from mika.faculties.projects.tool_common import RUNS, gone_reply, running_project
from mika.kernel.clock import HOUR
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import ToolResult
from mika.vocab.phrasebook import family, phrase

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
    #: un constant : ce qui le déclenche en plus de sa cadence, et s'il n'a aucune cadence (ADR 0265)
    on: list[str] = Field(default_factory=list, max_length=triggers.TRIGGERS_MAX,
                          description=phrase("projects.tools.trigger.declared"))
    only_on_event: bool = Field(default=False, description=phrase("projects.tools.trigger.only_on_event"))
    #: un constant : son premier passage vient tout de suite, pas une cadence après (ADR 0280)
    at_once: bool = Field(default=False, description=phrase("projects.tools.constant.at_once"))
    #: un ponctuel : ses jalons grossiers, que sa première exécution affinera ; un constant : ce que chaque passage
    #: doit faire (ADR 0273)
    milestones: list[MilestoneArg] = Field(default_factory=list, max_length=c.MILESTONES_MAX,
                                           description=phrase("projects.tools.plan.milestones"))
    each_pass: list[str] = Field(default_factory=list, max_length=ROUTINE_LINES,
                                 description=phrase("projects.tools.plan.each_pass"))


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


def _plan_problems(p: Project, steps: list[PlanStep], reads: Collection[int] | None = None) -> list[str]:
    """Ce qui ne va pas dans ses étapes, en mots (rien : il s'écrit). ``reads`` : les projets qu'un déclencheur peut
    nommer (ADR 0265) — ceux que le projet lit, et ceux que ce plan demande à lire ; ``None`` : ses liens."""
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
        # ses jalons (ADR 0273) : un ponctuel seulement ; un constant a sa liste de passage, et lui seul
        if step.kind == c.CONSTANT and step.milestones:
            problems.append(phrase("projects.tools.plan.constant_milestones", n=i))
        if step.kind == c.ONCE and any(x.strip() for x in step.each_pass):
            problems.append(phrase("projects.tools.plan.once_each_pass", n=i))
        for j, asked in enumerate(step.milestones if step.kind == c.ONCE else (), start=1):
            if why := milestones.problem(asked.spec()):
                problems.append(phrase("projects.tools.plan.bad_milestone", n=i, m=j, why=bad_milestone(why)))
        try:
            triggers.accepted(p.id, p.reads if reads is None else reads, step.kind == c.CONSTANT, step.on,
                              step.only_on_event)
        except triggers.BadTrigger as exc:
            problems.append(phrase("projects.tools.plan.bad_trigger", n=i, text=exc.text,
                                   why=family("projects.triggers.refused")[exc.why]))
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
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    s: ProjectsState = ctx.frame.state("projects")
    world = links.world_of(ctx.frame)
    wanted = tuple(dict.fromkeys(args.reads))
    # un déclencheur peut nommer un projet que ce plan demande à lire : il ne déclenchera qu'une fois le lien posé
    problems = [*_plan_problems(p, args.steps, {*p.reads, *wanted}), *_read_problems(s, p, wanted, world)]
    if problems:
        return ToolResult(ok=False, content=phrase("projects.tools.plan.refused", problems="\n".join(problems)))
    kept = {s.keep for s in args.steps if s.keep}
    dropped = [o for o in p.objectives if o.status in (c.OPEN, c.BLOCKED) and o.id not in kept and not o.app]
    if living(p) - len(dropped) + sum(1 for s in args.steps if not s.keep) > OBJECTIVES_KEPT:
        return ToolResult(ok=False, content=phrase("projects.tools.objective_add.full", count=OBJECTIVES_KEPT))
    # son plan nomme les projets qu'il demande à lire avant tout lien : il s'écrit au niveau le plus haut parmi le
    # sien et les leurs, et l'oubli d'une de leurs personnes l'atteint aussi (ADR 0262)
    named = [s.projects[t] for t in wanted if t in s.projects]
    level = max([written(p), *(written(t) for t in named)])
    inherited = tuple(dict.fromkeys((*p.read_about, *(x for t in named for x in subjects_of(t)))))
    who: dict[str, Any] = {"owner": p.owner, "about": p.about, "read_about": inherited}
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
        # ce qui le déclenche (ADR 0265), déjà vérifié : une étape gardée le redit, comme sa cadence
        on = triggers.kept(step.on) if step.kind == c.CONSTANT else ()
        only = step.only_on_event and bool(on)
        first = step.at_once and step.kind == c.CONSTANT
        # un constant : ce que chaque passage doit faire (ADR 0273) ; une étape gardée qui n'en dit rien garde la sienne
        each = milestones.routine_text(x[:ROUTINE_LINE_MAX] for x in step.each_pass) if step.kind == c.CONSTANT else ""
        routine = Content.of(each, level=level) if each else None
        specs = [m.spec() for m in step.milestones] if step.kind == c.ONCE else []
        if step.keep:
            old = objective_at(p, oid)
            reopened = c.OPEN if old is not None and old.status == c.BLOCKED else None  # un plan neuf, une chance neuve
            drafts.append(OBJECTIVE_CHANGED.draft(project=p.id, objective=oid, status=reopened, text=text,
                                                  kind=step.kind, cadence_us=every, done_when=done_when, after=after,
                                                  rank=i, on=on, only_on_event=only, routine=routine,
                                                  at_once=first, **who))
            # une étape gardée qui a déjà ses jalons les garde : ils se révisent un à un (project_milestones), avec
            # leur raison — un plan revu ne les réécrit pas en bloc
            if old is not None and not milestones_of(old):
                drafts += milestones.posed(p, oid, specs, level=level, inherited=inherited, after=old.milestone_seq)
        else:
            drafts.append(OBJECTIVE_ADDED.draft(project=p.id, objective=oid, text=text, kind=step.kind,
                                                cadence_us=every, done_when=done_when, after=after, rank=i,
                                                author="self", on=on, only_on_event=only, routine=routine,
                                                at_once=first, **who))
            drafts += milestones.posed(p, oid, specs, level=level, inherited=inherited)
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
