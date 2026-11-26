"""Tenir les jalons d'un objectif (ADR 0273) : ses outils.

Pendant une exécution qui vise un objectif ponctuel :

- **``project_milestones``** pose un jalon, en révise un ou en retire un. À sa première exécution elle affine ceux
  que le plan a posés, sans avoir à dire pourquoi ; ensuite une révision garde sa raison, un retrait toujours. Un
  jalon atteint ne se défait pas ; un point d'arrêt qu'elle a dit prêt est au propriétaire, elle n'y touche plus.
  Et elle ne défait pas ce qui n'est pas à elle seule (ADR 0278, ``milestones.milestone_guard``) : ni un point
  d'arrêt, ni un jalon qu'un autre a posé ou que le propriétaire a refusé, ni un jalon d'un plan qu'une personne
  a validé — celui-là, elle peut seulement lui donner une vérification. L'outil le refuse en disant pourquoi, et
  de le demander (« needs_you »).
- **``milestone_reach``** dit un jalon atteint, et comment. Ce qu'il fait dépend de la vérification du jalon :
  - une **commande** : c'est l'outil qui la lance, dans l'atelier, sans réseau, dans le temps de programmes qui
    reste à l'exécution (``atelier.program_time_left``). Elle doit réussir : un résumé borné de ce qu'elle a rendu
    est gardé en preuve. En échec, rien ne s'écrit, et elle lit pourquoi ;
  - un **point d'arrêt** : le jalon est dit prêt — avec comment elle l'a rempli et le commit de l'atelier — et
    attend le propriétaire ; l'objectif attend avec lui (``rhythm.held_back``) ;
  - un **élément** du registre : il est relu maintenant (``tracker.py``) et doit avoir le statut attendu ;
  - sinon elle dit comment il est rempli, et c'est sa parole.

Un objectif constant n'a pas de jalons : les deux outils s'y refusent.

Un jalon tel qu'elle le pose dans son plan (``MilestoneArg``, que lit ``PlanStep`` dans ``framing_tools.py``) et
pourquoi un jalon demandé est refusé, en mots (``bad_milestone``, que lisent le cadrage et ``project_milestones``) sont
ici aussi.

En conversation, **``project_milestone``** : le propriétaire du projet, ou qui s'occupe d'elle, valide ou refuse un
point d'arrêt — la forme de la validation du plan d'un ticket (``tracker_tools.project_item``). L'outil n'est offert que
devant qui peut piloter un projet vivant dont un point d'arrêt attend. La console fait le même geste
(``inspect_milestones.py``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.faculties.projects import milestones, tracker, tracker_tools
from mika.faculties.projects.access import steering
from mika.faculties.projects.atelier import open_views, program_time_left
from mika.faculties.projects.faculty import (
    PROJECTS,
    Milestone,
    Objective,
    Project,
    ProjectsState,
    inherited_for,
    live,
    milestone_at,
    milestones_of,
    next_milestone,
    objective_at,
    open_milestones,
    waiting_in,
    written_for,
)
from mika.faculties.projects.inspect_common import unchanged
from mika.faculties.projects.milestones import milestone_guard
from mika.faculties.projects.steer import STEERABLE, steerable
from mika.faculties.projects.tool_common import (
    RUNS,
    caretaker,
    changed_reply,
    contents_of,
    emit_gesture,
    gone_reply,
    running_project,
    speaker,
)
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.text import clipped
from mika.ports.workshop import RunResult, describe
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import family, phrase

POSE, REACH, SETTLE = "project_milestones", "milestone_reach", "project_milestone"
ADD, REVISE, DROP = "add", "revise", "drop"
VALIDATE, REFUSE = "validate", "refuse"
#: le temps d'une commande de vérification, au plus (secondes) — borné en plus par ce qui reste à l'exécution
COMMAND_TIMEOUT_S = 120.0
#: ce qu'on garde de la sortie d'une commande réussie (la fin : c'est là qu'un banc d'essai conclut), et ce qu'elle
#: lit d'une commande en échec
PROOF_TAIL, FAILED_SHOWN = 400, 1500


def _no(content: str) -> ToolResult:
    return ToolResult(ok=False, content=content)


def _target(ctx: Any) -> tuple[Project, Objective] | ToolResult | str:
    """Le projet et l'objectif ponctuel que vise cette exécution, ou pourquoi ses jalons ne s'y tiennent pas."""
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, o = got
    if o is None:
        return _no(phrase("projects.tools.milestones.no_objective"))
    if o.kind != c.ONCE:  # un constant a sa liste de passage, pas de jalons
        return _no(phrase("projects.tools.milestones.constant"))
    if o.status != c.OPEN:
        return _no(phrase("projects.tools.milestones.closed", id=o.id))
    return p, o


def _found(o: Objective, number: int) -> Milestone | ToolResult:
    """Le jalon qu'elle désigne, s'il est encore à elle : ni atteint, ni retiré, ni entre les mains du
    propriétaire."""
    m = milestone_at(o, number)
    if m is None:
        known = ", ".join(str(x.id) for x in milestones_of(o)) or phrase("projects.tools.milestones.no_number")
        return _no(phrase("projects.tools.milestones.unknown", id=number, known=known))
    if m.status == c.REACHED:
        return _no(phrase("projects.tools.milestones.reached", id=m.id))
    if m.status == c.DROPPED:
        return _no(phrase("projects.tools.milestones.dropped", id=m.id))
    return m


def _fresh(ctx: Any, p: Project, o: Objective) -> Objective | None:
    after = ctx.mind.frame().state("projects").projects.get(p.id)
    return objective_at(after, o.id) if after is not None else None


# ── Un jalon tel qu'elle le pose, et pourquoi il est refusé ───────────────


class MilestoneArg(BaseModel):
    """Un jalon tel qu'elle le pose (ADR 0273) : son texte, et comment il se vérifiera."""

    text: str = Field(min_length=1, max_length=milestones.TEXT_MAX, description=phrase("projects.tools.milestone.text"))
    check: Literal["prose", "command", "owner", "item"] = Field(
        default="prose", description=phrase("projects.tools.milestone.check"))
    argv: list[str] = Field(default_factory=list, max_length=milestones.ARGV_MAX,
                            description=phrase("projects.tools.milestone.argv"))
    item_list: str = Field(default="", max_length=40, description=phrase("projects.tools.milestone.item_list"))
    item: str = Field(default="", max_length=61, description=phrase("projects.tools.milestone.item"))
    item_status: str = Field(default="", max_length=24, description=phrase("projects.tools.milestone.item_status"))

    def spec(self) -> milestones.Spec:
        return milestones.Spec(self.text, self.check, tuple(self.argv), self.item_list, self.item, self.item_status)


def bad_milestone(why: str) -> str:
    """Pourquoi un jalon demandé est refusé, en mots (``milestones.problem``)."""
    return family("projects.milestones.refused")[why]


# ── Poser, réviser, retirer ───────────────────────────────────────────────


class PoseArgs(BaseModel):
    what: Literal["add", "revise", "drop"] = Field(description=phrase("projects.tools.milestones.what"))
    milestone: int = Field(default=0, ge=0, description=phrase("projects.tools.milestones.milestone"))
    text: str = Field(default="", max_length=milestones.TEXT_MAX, description=phrase("projects.tools.milestone.text"))
    check: Literal["", "prose", "command", "owner", "item"] = Field(
        default="", description=phrase("projects.tools.milestone.check"))
    argv: list[str] = Field(default_factory=list, max_length=milestones.ARGV_MAX,
                            description=phrase("projects.tools.milestone.argv"))
    item_list: str = Field(default="", max_length=40, description=phrase("projects.tools.milestone.item_list"))
    item: str = Field(default="", max_length=61, description=phrase("projects.tools.milestone.item"))
    item_status: str = Field(default="", max_length=24, description=phrase("projects.tools.milestone.item_status"))
    reason: str = Field(default="", max_length=milestones.REASON_MAX,
                        description=phrase("projects.tools.milestones.reason"))


def _spec(args: PoseArgs, m: Milestone | None, texts: Any) -> milestones.Spec:
    """Le jalon demandé — pour une révision, ce qu'il devient : ce qu'elle ne redit pas reste."""
    if m is None:
        return milestones.Spec(args.text, args.check or c.CHECK_PROSE, tuple(args.argv), args.item_list, args.item,
                               args.item_status)
    return milestones.Spec(
        args.text.strip() or texts.get(m.text_ref, ""), args.check or m.check,
        tuple(args.argv) or milestones.decoded(texts.get(m.command_ref)), args.item_list.strip() or m.item_list,
        args.item.strip() or m.item_key, args.item_status.strip() or m.item_status)


def _worded(x: milestones.Spec) -> str:
    return " ".join(x.text.split())


def _checked(x: milestones.Spec) -> tuple[Any, ...]:
    """Comment un jalon demandé se vérifie : ce qui ne sert pas à sa vérification ne compte pas."""
    return (x.check, x.argv if x.check == c.CHECK_COMMAND else (),
            (x.item_list, x.item_key, x.item_status) if x.check == c.CHECK_ITEM else ())


def _same(a: milestones.Spec, b: milestones.Spec) -> bool:
    """Deux demandes qui posent le même jalon : le même texte, la même vérification."""
    return (_worded(a), _checked(a)) == (_worded(b), _checked(b))


def _held(ctx: Any, m: Milestone, draft: Any) -> ToolResult | None:
    """Le refus d'un geste qui déferait un jalon qui n'est pas à elle seule (ADR 0278) — la règle du réducteur,
    lue d'avance : pourquoi, et qu'elle le demande à qui s'occupe d'elle."""
    why = milestone_guard(m, draft.data)
    if not why:
        return None
    return _no(phrase("projects.tools.milestones.not_yours", id=m.id, who=caretaker(ctx.frame),
                      why=family("projects.tools.milestones.held")[why]))


@PROJECTS.tool(POSE, acts=True, description=phrase("projects.tools.milestones.description"),
               label=phrase("projects.tools.milestones.label"), args=PoseArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=8)
async def project_milestones(args: PoseArgs, ctx: Any) -> Any:
    got = _target(ctx)
    if not isinstance(got, tuple):
        return got
    p, o = got
    level, inherited = written_for(p, o), inherited_for(p, o)
    who = caretaker(ctx.frame)
    if args.what == ADD:
        if len(milestones_of(o)) >= c.MILESTONES_MAX:
            return _no(phrase("projects.tools.milestones.full", count=c.MILESTONES_MAX))
        spec = _spec(args, None, {})
        if why := milestones.problem(spec):
            return _no(phrase("projects.tools.milestones.bad", why=bad_milestone(why)))
        number = o.milestone_seq + 1
        await ctx.emit(milestones.adding(p, o.id, number, spec, level=level, inherited=inherited))
        after = _fresh(ctx, p, o)
        posed = after.milestone_seq if after is not None else number  # un ajout concurrent a pu prendre ce numéro
        return phrase("projects.tools.milestones.added", id=posed, left=c.MILESTONES_MAX - len(milestones_of(after)))
    m = _found(o, args.milestone)
    if isinstance(m, ToolResult):
        return m
    if m.ready_at:  # dit prêt : la main est au propriétaire
        return _no(phrase("projects.tools.milestones.waiting", id=m.id, who=who))
    reason = args.reason.strip()
    if args.what == DROP:
        if not reason:
            return _no(phrase("projects.tools.milestones.no_reason"))
        draft = milestones.changing(p, o.id, m, level=level, inherited=inherited, status=c.DROPPED, reason=reason)
        if refused := _held(ctx, m, draft):
            return refused
        await ctx.emit(draft)
        return phrase("projects.tools.milestones.removed", id=m.id)
    if not reason and not milestones.refining(o):  # passé sa première exécution, une révision garde sa raison
        return _no(phrase("projects.tools.milestones.no_reason"))
    texts = contents_of(ctx, milestones.refs(o))
    spec = _spec(args, m, texts)
    if why := milestones.problem(spec):
        return _no(phrase("projects.tools.milestones.bad", why=bad_milestone(why)))
    before = _spec(PoseArgs(what=REVISE), m, texts)
    if _same(spec, before):
        return _no(phrase("projects.tools.milestones.nothing", id=m.id))
    # la révision ne porte que ce qu'elle change : c'est ce que juge la règle de ce qu'elle peut défaire
    draft = milestones.changing(p, o.id, m, level=level, inherited=inherited, spec=spec, reason=reason,
                                same_text=_worded(spec) == _worded(before),
                                same_check=_checked(spec) == _checked(before))
    if refused := _held(ctx, m, draft):
        return refused
    await ctx.emit(draft)
    return phrase("projects.tools.milestones.revised", id=m.id)


# ── Dire un jalon atteint ─────────────────────────────────────────────────


class ReachArgs(BaseModel):
    milestone: int = Field(ge=1, description=phrase("projects.tools.reach.milestone"))
    how: str = Field(min_length=1, max_length=milestones.HOW_MAX, description=phrase("projects.tools.reach.how"))


def proof_of(result: RunResult) -> str:
    """Ce qu'on garde d'une commande réussie : ce qu'elle était, son code, sa durée, et la fin de ce qu'elle a
    écrit — un fait arrivé, borné."""
    tail = result.stdout.strip()[-PROOF_TAIL:]
    return result.summary() + (f"\n{tail}" if tail else "")


async def _run_check(ctx: Any, p: Project, m: Milestone, port: Any) -> str | ToolResult:
    """Lancer la commande d'un jalon et rendre sa preuve ; en échec, ou si elle ne peut pas partir, pourquoi."""
    argv = milestones.decoded(contents_of(ctx, [m.command_ref]).get(m.command_ref))
    if not argv:
        return _no(phrase("projects.tools.reach.command_forgotten", id=m.id))
    if port is None:  # comme ``ws_run`` : l'atelier s'ouvre à sa première commande
        return _no(phrase("projects.tools.reach.no_workshop", id=m.id))
    left = program_time_left(ctx)
    if left < 2:
        return _no(phrase("projects.workshop.no_time"))
    # sans réseau, et avec les vues qui lui sont ouvertes maintenant — comme ses autres programmes (``ws_run``)
    result = await port.run(p.id, list(argv), timeout_s=min(COMMAND_TIMEOUT_S, left),
                            views=await open_views(ctx, p, port))
    if not result.ok:
        return _no(phrase("projects.tools.reach.command_failed", id=m.id, output=describe(result, FAILED_SHOWN)))
    return proof_of(result)


def _item_check(ctx: Any, p: Project, m: Milestone) -> str | ToolResult:
    """Relire l'élément d'un jalon : il existe, et il a le statut attendu — sa preuve le dit ; sinon pourquoi."""
    found = tracker_tools.found_entry(ctx, p, m.item_list, m.item_key)
    if isinstance(found, ToolResult):
        return found
    lst, e = found
    wanted = tracker.read_status(lst, m.item_status)
    if wanted is None:
        return _no(phrase("projects.tools.items.bad_status", status=m.item_status, name=lst.name,
                          statuses=tracker.statuses_said(lst)))
    if e.item.status != wanted:
        return _no(phrase("projects.tools.reach.item_elsewhere", id=m.id, handle=tracker.handle(e.item),
                          status=tracker.status_words(lst.name, e.item.status),
                          wanted=tracker.status_words(lst.name, wanted)))
    return phrase("projects.milestones.item_proof", handle=tracker.handle(e.item), name=lst.name,
                  status=tracker.status_words(lst.name, wanted))


@PROJECTS.tool(REACH, acts=True, description=phrase("projects.tools.reach.description"),
               label=phrase("projects.tools.reach.label"), args=ReachArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=8)
async def milestone_reach(args: ReachArgs, ctx: Any) -> Any:
    got = _target(ctx)
    if not isinstance(got, tuple):
        return got
    p, o = got
    m = _found(o, args.milestone)
    if isinstance(m, ToolResult):
        return m
    who = caretaker(ctx.frame)
    if m.ready_at:
        return _no(phrase("projects.tools.milestones.waiting", id=m.id, who=who))
    port = ctx.ports.get("workshop")
    # le commit de l'atelier à ce moment-là ; le compte rendu de cette exécution y mettra le sien, qui contient son
    # travail (``faculty._reported``) — l'outil n'enregistre rien lui-même : un commit par exécution, mesuré une fois
    head = await port.head(p.id) if port is not None and port.exists(p.id) else ""
    level, inherited = written_for(p, o), inherited_for(p, o)
    how = args.how.strip()
    if m.check == c.CHECK_OWNER:
        await ctx.emit(milestones.changing(p, o.id, m, level=level, inherited=inherited, ready=True, how=how,
                                           commit=head[:40]))
        return phrase("projects.tools.reach.ready", id=m.id, who=who)
    proof: str | ToolResult = ""
    if m.check == c.CHECK_COMMAND:
        proof = await _run_check(ctx, p, m, port)
    elif m.check == c.CHECK_ITEM:
        proof = _item_check(ctx, p, m)
    if isinstance(proof, ToolResult):
        return proof
    await ctx.emit(milestones.changing(p, o.id, m, level=level, inherited=inherited, status=c.REACHED, how=how,
                                       proof=proof, commit=head[:40]))
    after = _fresh(ctx, p, o)
    reached = milestone_at(after, m.id) if after is not None else None
    if reached is None or reached.status != c.REACHED:  # retiré ou révisé pendant qu'elle le disait atteint
        return _no(phrase("projects.tools.milestones.moved", id=m.id))
    coming = next_milestone(after)
    if coming is not None:
        text = contents_of(ctx, [coming.text_ref]).get(coming.text_ref) or phrase("projects.milestones.forgotten")
        return phrase("projects.tools.reach.done_next", id=m.id, next=coming.id,
                      text=clipped(text, milestones.TEXT_SHOWN))
    if open_milestones(after):  # il ne reste que ce qui attend le propriétaire
        return phrase("projects.tools.reach.done_waiting", id=m.id, who=who)
    return phrase("projects.tools.reach.done_all", id=m.id)


# ── En conversation : trancher un point d'arrêt ───────────────────────────


def may_settle(audience: Any, kind: str, frame: Any = None) -> bool:
    """Seulement devant qui une ligne d'accès laisse changer un projet vivant dont un point d'arrêt attend (ADR
    0133, 0273) ; sans ce qu'elle vit, non."""
    if frame is None:
        return False
    s: ProjectsState = frame.state("projects")
    return any(waiting_in(p) and steering(p, audience, kind, frame) in c.CHANGES
               for p in s.projects.values() if live(p))


class SettleArgs(BaseModel):
    project: str = Field(min_length=1, max_length=200, description=phrase("projects.tools.steer.project"))
    what: Literal["validate", "refuse"] = Field(description=phrase("projects.tools.breakpoint.what"))
    objective: int = Field(default=0, ge=0, description=phrase("projects.tools.breakpoint.objective"))
    milestone: int = Field(default=0, ge=0, description=phrase("projects.tools.breakpoint.milestone"))
    text: str = Field(default="", max_length=milestones.REASON_MAX,
                      description=phrase("projects.tools.breakpoint.text"))


def settling(p: Project, o: Objective, m: Milestone, what: str, *, author: str, by: str, text: str = "") -> Any:
    """Le brouillon du geste du propriétaire sur un point d'arrêt — le seul endroit qui le fait, pour la
    conversation comme pour la console : validé, il est atteint ; refusé, il revient à elle avec sa raison."""
    return milestones.changing(p, o.id, m, level=written_for(p, o), inherited=inherited_for(p, o), author=author,
                               by=by, status=c.REACHED if what == VALIDATE else None, refused=what == REFUSE,
                               reason=text)


@PROJECTS.tool(SETTLE, acts=True, description=phrase("projects.tools.breakpoint.description"),
               label=phrase("projects.tools.breakpoint.label"), args=SettleArgs, bundle="projects",
               episodes=[Kind.REPLY], max_calls_per_episode=3, fits=may_settle,
               rule="seulement en privé, devant qui peut piloter un projet vivant dont un point d'arrêt attend")
async def project_milestone(args: SettleArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    who = speaker(frame)
    aud = frame.audience
    if who is None or aud is None:
        return _no(phrase("projects.tools.steer.not_owner", who=caretaker(frame)))
    person = who[1]
    s: ProjectsState = frame.state("projects")
    mine = [p for p in sorted(s.projects.values(), key=lambda x: x.id)
            if waiting_in(p) and steerable(p, aud, frame) in c.CHANGES and tracker.hears(p, person, aud)]
    if not mine:
        return _no(phrase("projects.tools.breakpoint.none"))
    got = tracker_tools.chosen_project(ctx, args.project, mine)
    if isinstance(got, ToolResult):
        return got
    p, title = got
    if not tracker.settles(frame, p, person):  # le propriétaire du projet, ou qui s'occupe d'elle : personne d'autre
        return _no(phrase("projects.tools.breakpoint.not_theirs", title=title, who=caretaker(frame)))
    chosen = [(o, m) for o, m in waiting_in(p) if args.objective in (0, o.id) and args.milestone in (0, m.id)]
    if len(chosen) != 1:
        listed = ", ".join(phrase("projects.tools.breakpoint.one", objective=o.id, id=m.id) for o, m in waiting_in(p))
        return _no(phrase("projects.tools.breakpoint.which", title=title, listed=listed))
    o, m = chosen[0]
    text = args.text.strip()
    if args.what == REFUSE and not text:
        return _no(phrase("projects.tools.breakpoint.no_reason"))
    draft = settling(p, o, m, args.what, author="owner", by=person, text=text)
    if await emit_gesture(ctx, draft, unchanged(p.id, STEERABLE)) is None:
        return changed_reply()
    after = _fresh(ctx, p, o)
    now = milestone_at(after, m.id) if after is not None else None
    if now is None or now.ready_at or (args.what == VALIDATE and now.status != c.REACHED):
        return changed_reply()  # il n'attendait plus : rien n'a changé
    if args.what == VALIDATE:
        return phrase("projects.tools.breakpoint.validated", id=m.id, objective=o.id, title=title)
    return phrase("projects.tools.breakpoint.refused", id=m.id, objective=o.id, title=title)
