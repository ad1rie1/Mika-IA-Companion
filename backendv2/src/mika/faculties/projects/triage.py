"""Traiter les tickets (ADR 0270) : ses gestes sur un ticket, et ce qui suit de lui-même.

Les règles du parcours sont pures et ailleurs (``tickets.py``) ; ici, ce qui agit :

- **Son geste en exécution** (``ticket_step``) : le passage qui traite les tickets conclut chaque ticket qu'il a eu
  sous les yeux — le prendre, poser sa question, écrire son plan, y répondre et le fermer, proposer de l'écarter.
  Sans geste, le ticket reste « non lu ». Un plan jugé petit, sur un projet qui ne fait valider que ce qui n'est pas
  petit, est validé par elle : son objectif naît dans le même geste.
- **Ce qui suit** (le processus ``projects.tickets``) : l'objectif constant « Traiter les tickets » naît au premier
  ticket entre ses mains qu'un autre qu'elle a ouvert — une fois par projet (``Project.triage``), et le réducteur lui
  pose aussitôt ce ticket pour cause : il part au rythme du projet, pas hors de son agenda (ADR 0272) ; l'objectif né
  d'un ticket referme son ticket quand il aboutit, le dit quand il bloque, le rend à l'analyse quand on le retire ;
  un ticket fermé retire son objectif, sous une garde plutôt qu'une clé : rouvert, il est retiré de nouveau.
- **La borne d'un petit ticket** (``small_gate``, posée sur le compte rendu : ``tools.REPORT_GATES``) : à chaque
  compte rendu d'une exécution de son objectif, ce qu'elle a enregistré se mesure ; au-delà de la borne, le « fait »
  ne s'écrit pas et le ticket repasse en attente de validation. Sur un projet qui passe par des pull requests (ADR
  0274), c'est le diff entier de sa branche face à sa base qui se mesure, pas une somme par exécution.
- **Le ticket et la pull request de son objectif** (``follow_ups``, ``pull_fact`` ; ADR 0274) : sur un tel projet,
  le ticket validé attend sa pull request, la dit prête quand elle est ouverte chez l'hôte, ne se ferme « traité »
  qu'à sa fusion, et la redit attendue quand elle revient refusée.
- **Ce que l'exécution en lit** (``triage_lines``, ``own_lines`` ; la section ``project_tickets`` de ``prompt.py``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import tickets, tools, tracker, triggers
from mika.faculties.projects.faculty import (
    CHECKS_SEEN,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    OBJECTIVES_KEPT,
    PLAN_ANSWERED,
    PROJECTS,
    PULL_SEEN,
    REFRAMED,
    RESUMED,
    REVIEWED,
    Item,
    Objective,
    Project,
    ProjectsState,
    awaits_her,
    by_pulls,
    checks_pass,
    living,
    objective_at,
    ticket_held,
    unreviewed,
    written,
)
from mika.faculties.projects.rhythm import framing
from mika.faculties.projects.tool_common import RUNS, caretaker, gone_reply, running_project
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp, ToolResult
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.kernel.text import clipped
from mika.ports.workshop import PULL_MERGED, PULL_OPEN
from mika.vocab.phrasebook import family, phrase

# ── Son geste en exécution ────────────────────────────────────────────────

STEP = "ticket_step"
TAKE, ASK, PLAN, ANSWER, DISMISS = "take", "ask", "plan", "answer", "dismiss"
#: les étapes d'où chaque geste part : prendre un ticket non lu ; poser une question tant qu'il est ouvert ; écrire
#: (ou revoir) son plan tant qu'il n'est pas validé ; y répondre ou proposer de l'écarter avant tout plan
FROM = {
    TAKE: (c.STAGE_UNREAD,),
    ASK: (c.STAGE_UNREAD, c.STAGE_ANALYSIS, c.STAGE_DECISION, c.STAGE_VALIDATION, c.STAGE_WORKING,
          c.STAGE_PR_PENDING),
    PLAN: (c.STAGE_UNREAD, c.STAGE_ANALYSIS, c.STAGE_DECISION, c.STAGE_VALIDATION),
    ANSWER: (c.STAGE_UNREAD, c.STAGE_ANALYSIS),
    DISMISS: (c.STAGE_UNREAD, c.STAGE_ANALYSIS),
}


class StepArgs(BaseModel):
    item: str = Field(min_length=1, max_length=12, description=phrase("projects.tools.tickets.arg.item"))
    what: Literal["take", "ask", "plan", "answer", "dismiss"] = Field(
        description=phrase("projects.tools.tickets.arg.what"))
    text: str = Field(default="", max_length=tracker.NOTE_MAX, description=phrase("projects.tools.tickets.arg.text"))
    changes: str = Field(default="", max_length=tickets.PLAN_PART_MAX,
                         description=phrase("projects.tools.tickets.arg.changes"))
    where: str = Field(default="", max_length=tickets.PLAN_PART_MAX,
                       description=phrase("projects.tools.tickets.arg.where"))
    steps: list[str] = Field(default_factory=list, max_length=tickets.STEPS_MAX,
                             description=phrase("projects.tools.tickets.arg.steps"))
    untouched: str = Field(default="", max_length=tickets.PLAN_PART_MAX,
                           description=phrase("projects.tools.tickets.arg.untouched"))
    small: bool = Field(default=False, description=phrase("projects.tools.tickets.arg.small"))


def _no(content: str) -> ToolResult:
    return ToolResult(ok=False, content=content)


def stage_words(item: Item) -> str:
    return tracker.status_words(c.TICKETS, item.status)


def _drafts(args: StepArgs, p: Project, item: Item) -> tuple[list[Draft[Any]], Guard | None] | ToolResult:
    """Ce qu'un geste écrit et la garde sous laquelle il s'écrit, ou son refus."""
    got = _written(args, p, item)
    if isinstance(got, ToolResult):
        return got
    # un plan validé par elle fait naître un objectif : son numéro doit être encore libre au moment d'écrire
    return got, tracker.free_number(p, item) if len(got) > 1 else None


def _written(args: StepArgs, p: Project, item: Item) -> list[Draft[Any]] | ToolResult:
    text = args.text.strip()
    if args.what == TAKE:
        return [tracker.changing(p, item, taken=True)]
    if args.what == ASK:
        if not text:
            return _no(phrase("projects.tools.tickets.no_text"))
        return [tracker.noting(p, item, text, kind=c.NOTE_QUESTION)]
    if args.what == ANSWER:
        if not text:
            return _no(phrase("projects.tools.tickets.no_text"))
        return [tracker.changing(p, item, closed=c.DONE, note=text)]
    if args.what == DISMISS:
        if not text:
            return _no(phrase("projects.tools.tickets.no_text"))
        return [tracker.changing(p, item, dismissal=True, note=text)]
    if not args.changes.strip():
        return _no(phrase("projects.tools.tickets.no_changes"))
    plan = tickets.plan_text(args.changes, args.where, args.steps, args.untouched, args.small)
    note = tracker.noting(p, item, plan, kind=c.NOTE_PLAN, small=args.small)
    if not (args.small and p.ticket_review == c.REVIEW_LARGE) or not tickets.self_validates(item):
        # un ticket qui a déjà son objectif, un diff compté, ou qui a dépassé sa borne ne se revalide pas seul (ADR
        # 0272) : son nouveau plan attend le propriétaire, même jugé petit
        return [note]
    # petit, sur un projet qui ne fait valider que ce qui ne l'est pas : validé par elle, son plan quand même écrit
    # dans le fil — la validation part de l'étape que la note vient de poser, et ne nomme pas de plan (c'est celui
    # du même geste)
    waiting = tracker._noted(item, note.data, 0, 1)
    if tracker.validation_refusal(p, waiting, plan):
        return [note]
    return [note, *tracker.validating(p, waiting, plan, author=c.BY_SELF, plan_seq=0)]


@PROJECTS.tool(STEP, acts=True, description=phrase("projects.tools.tickets.description"),
               label=phrase("projects.tools.tickets.label"), args=StepArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=30)
async def ticket_step(args: StepArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    store = ctx.ports.get("store")
    e = tracker.find(store, p.id, c.TICKETS, args.item)
    if e is None:
        return _no(phrase("projects.tools.items.unknown", item=args.item, name=c.TICKETS))
    item = e.item
    if item.status not in FROM[args.what]:
        return _no(phrase("projects.tools.tickets.not_now", number=item.number, stage=stage_words(item)))
    for again in (False, True):
        got = _drafts(args, p, item)
        if isinstance(got, ToolResult):
            return got
        drafts, guard = got
        try:
            await ctx.emit(*drafts, guard=guard)
            break
        except Superseded:
            if guard is None or guard.predicate is None or guard.predicate(ctx.mind.frame().view):
                raise  # c'est la garde de l'exécution qui a cédé
            # un objectif a pris ce numéro entre-temps (ADR 0272) : elle relit le projet et recommence, une fois
            fresh = ctx.mind.frame().state("projects").projects.get(p.id)
            if again or fresh is None or fresh.status != c.ACTIVE:
                return _no(phrase("projects.tools.items.moved"))
            p = fresh
    after = tracker.entry(store, p.id, c.TICKETS, item.key)
    if after is None or after == e:  # il a changé sous elle entre-temps : rien ne s'est écrit
        return _no(phrase("projects.tools.items.moved"))
    now = after.item
    if args.what == PLAN and now.status in (c.STAGE_WORKING, c.STAGE_PR_PENDING):
        return phrase("projects.tools.tickets.done.small", number=now.number, objective=now.objective)
    if args.what == PLAN:
        return phrase("projects.tools.tickets.done.plan", number=now.number, who=caretaker(ctx.frame))
    if args.what == ASK:
        return phrase("projects.tools.tickets.done.ask", number=now.number, who=caretaker(ctx.frame))
    if args.what == DISMISS:
        return phrase("projects.tools.tickets.done.dismiss", number=now.number, who=caretaker(ctx.frame))
    if args.what == ANSWER:
        return phrase("projects.tools.tickets.done.answer", number=now.number)
    return phrase("projects.tools.tickets.done.take", number=now.number)


# ── Ce qui suit de lui-même ───────────────────────────────────────────────

#: l'écart minimal entre deux passes qui trouvent encore quelque chose à faire
RETRY_US = MINUTE


def births(s: ProjectsState) -> list[tuple[Project, Item]]:
    """Les projets actifs et planifiés à qui il faut l'objectif « Traiter les tickets » : un ticket ouvert attend
    qu'elle le traite — non lu, ou en analyse : qui que ce soit qui l'ait ouvert, elle comprise (ADR 0280 : les
    constats de son propre audit n'attendent plus le ticket d'un autre) ; un ticket proposé, lui, attend l'accord
    du propriétaire —, et aucun de leurs objectifs n'a jamais attendu ``item:tickets`` (``Project.triage``, ADR
    0272) : qui l'a retiré, ou lui a ôté son déclencheur, n'en reçoit pas un second."""
    key = triggers.item_key(c.TICKETS)
    out = []
    for p in s.projects.values():
        if p.status != c.ACTIVE or framing(p) or living(p) >= OBJECTIVES_KEPT:
            continue
        if p.triage or any(key in o.on for o in p.objectives):
            continue
        first = next((x for x in p.board.items if awaits_her(x)), None)
        if first is not None:
            out.append((p, first))
    return out


def pull_fact(p: Project, o: Objective) -> str:
    """Ce que le ticket d'un objectif doit dire de sa pull request (ADR 0274 ; ``c.PULLS``) : rien sur un projet au
    flux direct, ou pour un objectif abouti sans branche (il n'a rien à proposer : un brouillon, une app) ;
    fusionnée ; prête — ouverte chez l'hôte, son objectif abouti, ses vérifications passées (ADR 0275), et que
    l'hôte ne dit pas impossible à fusionner (ADR 0280) ; sinon attendue : elle y travaille, sa proposition attend,
    ses vérifications tournent ou ont échoué, sa branche est en conflit avec la base, ou sa pull request lui est
    revenue et l'objectif est rouvert."""
    if not by_pulls(p) or (o.status == c.DONE and not o.branch):
        return c.PULL_NONE
    if o.pull_state == PULL_MERGED and o.status == c.DONE and not o.unsent:
        return c.PULL_MERGED
    # prête : ouverte, relue chez l'hôte depuis son dernier envoi, ses vérifications ne tournent plus ni
    # n'échouent (ADR 0275) — un dépôt sans CI, ou des vérifications illisibles, ne bloquent rien —, et l'hôte ne la
    # dit pas impossible à fusionner (ADR 0280 : sa branche en conflit avec la base)
    ready = o.pull_state == PULL_OPEN and o.status == c.DONE and bool(o.pull_at) and checks_pass(o) \
        and not o.pull_conflicts
    return c.PULL_READY if ready else c.PULL_AWAITED


def follow_ups(s: ProjectsState) -> list[Draft[Any]]:
    """Les faits que l'objectif d'un ticket pose sur son ticket — chacun sous une clé de dédoublonnage qui change
    avec l'état d'où il part (le ticket tel qu'il est, l'objectif qu'il tient et sa clôture) :

    - son objectif a abouti : le ticket se ferme, traité — sur un projet qui passe par des pull requests (ADR
      0274), seulement quand la sienne est fusionnée ; d'ici là le ticket la dit attendue, puis prête ;
    - sa pull request lui est revenue (refusée, des changements demandés) : son objectif est rouvert, et le ticket
      la redit attendue ;
    - son objectif bloque (ou repart) : le ticket validé le dit ;
    - son objectif a été retiré, ou n'est pas le sien : le ticket validé repasse en analyse."""
    out: list[Draft[Any]] = []
    for p in s.projects.values():
        if p.status == c.ARCHIVED:
            continue
        for item in p.board.items:
            if item.list_name != c.TICKETS or item.closed or not item.objective:
                continue
            o = objective_at(p, item.objective)
            mine = o is not None and o.ticket == item.number
            key = f"ticket:{p.id}:{item.number}:{item.updated_at}:{item.objective}:{o.closed_at if o else 0}"
            want = pull_fact(p, o) if mine else c.PULL_NONE
            # un travail qui attend sa relecture n'est pas encore traité (ADR 0276)
            if mine and o.status == c.DONE and want in (c.PULL_NONE, c.PULL_MERGED) and not unreviewed(p, o):
                more = {"pull": want, "pull_number": o.pull} if want and item.validated_at else {}
                out.append(tracker.changing(p, item, closed=c.DONE, dedupe_key=f"{key}:fait", **more))
            elif not item.validated_at:
                continue
            elif not mine or o.status == c.DROPPED:
                out.append(tracker.changing(p, item, objective=0, dedupe_key=f"{key}:retiré"))
            elif (o.status == c.BLOCKED) != item.stuck and o.status in (c.OPEN, c.BLOCKED):
                out.append(tracker.changing(p, item, stuck=o.status == c.BLOCKED,
                                            dedupe_key=f"{key}:bloque:{int(item.stuck)}"))
            elif (want, o.pull if want == c.PULL_READY else item.pull_number) != (item.pull, item.pull_number):
                # ce qu'il dit de la pull request de son objectif a changé : attendue, prête — ou plus rien
                out.append(tracker.changing(p, item, pull=want, pull_number=o.pull if want == c.PULL_READY else 0,
                                            dedupe_key=f"{key}:pr:{want}:{o.pull}"))
    return out


def orphans(s: ProjectsState) -> list[tuple[Project, Objective, Item]]:
    """Les objectifs nés d'un ticket qui n'ont plus lieu d'être : encore vivants, alors que leur ticket est fermé
    ou ne les tient plus (un plan refusé, une validation qui n'a pas valu)."""
    out = []
    for p in s.projects.values():
        if p.status == c.ARCHIVED:
            continue
        for o in p.objectives:
            item = ticket_held(p, o) if o.status in (c.OPEN, c.BLOCKED) else None
            if item is not None and (item.closed or item.objective != o.id):
                out.append((p, o, item))
    return out


def retiring(p: Project, o: Objective, item: Item) -> Draft[Any]:
    """Le retrait d'un objectif dont le ticket est fermé ou ne le tient plus. Sans clé de dédoublonnage (ADR
    0272) : faite du ticket et de l'objectif, elle restait la même quand l'opérateur rouvrait l'objectif — rien ne
    s'écrivait plus, l'objectif restait ouvert contre la règle et le processus repartait chaque minute. Il s'écrit
    sous une garde (``still_alive``) : une fois retiré, ``orphans`` ne le rend plus."""
    return OBJECTIVE_CHANGED.draft(
        project=p.id, objective=o.id, status=c.DROPPED, by=c.BY_SELF, owner=p.owner, about=p.about,
        read_about=p.read_about,
        note=Content.of(phrase("projects.tickets.objective.dropped", number=item.number), level=written(p)))


def still_alive(keys: tuple[tuple[int, int], ...]) -> Guard:
    """Ces objectifs sont encore vivants au moment d'écrire leur retrait."""
    return Guard("objectifs encore vivants", predicate=lambda view, keys=keys: all(
        view.get(c.OBJECTIVE_STATUS(k)) in (c.OPEN, c.BLOCKED) for k in keys))


@PROJECTS.process("projects.tickets", wake_on=[*tracker.MOVES, *c.ALL, OBJECTIVE_ADDED, OBJECTIVE_CHANGED, RESUMED,
                                               PLAN_ANSWERED, PULL_SEEN, CHECKS_SEEN, REFRAMED, REVIEWED,
                                               rt.EFFECT_EXECUTED],
                  catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=40)
class Tickets:
    """Ce qui suit d'un ticket sans qu'elle y pense (ADR 0270) : l'objectif constant « Traiter les tickets » naît
    au premier ticket ouvert dont elle a la main, d'un autre ou d'elle (ADR 0280) — il naît après ce ticket, et c'est son réducteur qui le lui pose pour cause
    (``faculty._objective_added``, ADR 0272) : il part quand le travail s'est posé, dans l'agenda et la plage du
    projet, jamais sur un projet « sur demande » ; l'objectif né d'un ticket et son ticket se suivent."""

    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        if not (births(s) or follow_ups(s) or orphans(s)):
            return None
        # une passe qui n'a rien pu écrire (dédoublonnée) ne repart pas aussitôt : au pire une minute, jamais une boucle
        return frame.now if last_run is None else max(frame.now, last_run + RETRY_US)

    async def run(self, ctx: Any) -> None:
        s: ProjectsState = ctx.state
        drafts = follow_ups(s)
        for p, _first in births(s):
            # une fois par projet : ``Project.triage`` le retient ensuite (``births``)
            drafts.append(OBJECTIVE_ADDED.draft(
                project=p.id, objective=p.objective_seq + 1, kind=c.CONSTANT, author="self",
                text=Content.of(phrase("projects.tickets.constant.objective"), level=written(p)),
                on=(triggers.item_key(c.TICKETS),), only_on_event=True, read_about=p.read_about, owner=p.owner,
                about=p.about, dedupe_key=f"traiter:{p.id}"))
        if drafts:
            await ctx.emit(*drafts)
        gone = orphans(ctx.frame.state("projects"))
        if gone:
            try:
                await ctx.emit(*(retiring(p, o, item) for p, o, item in gone),
                               guard=still_alive(tuple((p.id, o.id) for p, o, _ in gone)))
            except Superseded:
                return  # l'un d'eux a changé entre-temps : la passe suivante les relit


# ── La borne d'un petit ticket, au compte rendu ───────────────────────────


def bounded(item: Item | None) -> bool:
    """Ce ticket est-il travaillé comme petit — validé par elle, sans attendre ? Sa borne se vérifie alors."""
    return item is not None and not item.closed and item.small and bool(item.validated_at) \
        and item.validated_by == c.BY_SELF


async def small_gate(ctx: Any, p: Project, o: Objective, verdict: str, pending: list[str],
                     sha: str) -> tools.Held | None:
    """Mesurer ce que cette exécution a enregistré pour un ticket pris comme petit, et retenir son « fait » s'il
    dépasse la borne : le ticket repasse en attente de validation, avec son plan et ce qu'elle a déjà fait. Un projet
    sans atelier, ou une exécution qui n'a rien enregistré, n'a rien à mesurer."""
    item = ticket_held(p, o)
    if item is not None and not item.closed and tickets.waits(item) and verdict == c.DONE:
        # son ticket attend le propriétaire (sa question, sa validation — un petit ticket qui a dépassé sa borne) :
        # son objectif ne se conclut pas « fait » d'ici là, qu'elle ait enregistré quelque chose ou non (ADR 0272)
        return tools.Held(c.CONTINUE, (), phrase("projects.tools.tickets.awaits", number=item.number,
                                                 stage=stage_words(item), who=caretaker(ctx.frame)))
    port = ctx.ports.get("workshop")
    if not bounded(item) or port is None or not sha:
        return None
    b = tickets.bounds(p)
    span = await port.span(p.id, await port.branch(p.id)) if by_pulls(p) else None
    if span is not None:
        # le vrai diff de sa branche face à sa base (ADR 0274) : tout ce que son objectif a changé, mesuré d'un
        # coup — la mesure remplace la somme des exécutions
        paths, total_files, total_lines = span.files, len(span.files), span.insertions + span.deletions
        measure = {"diff_files": total_files, "diff_lines": total_lines, "measured": True}
    else:
        paths = tickets.touched(pending)
        last = await port.commits(p.id, 1)
        files = len(paths) or (last[0].files if last else 0)
        lines = last[0].insertions + last[0].deletions if last else 0
        total_files, total_lines = item.diff_files + files, item.diff_lines + lines
        measure = {"diff_files": files, "diff_lines": lines}
    why = tickets.oversize(paths, total_files, total_lines, b)
    draft = tracker.changing(p, item, outgrown=why, **measure)
    if not why:
        return tools.Held(verdict, (draft,))
    said = phrase("projects.tools.tickets.outgrown", number=item.number, why=family("projects.tickets.oversize")[why],
                  files=total_files, lines=total_lines, max_files=b.files, max_lines=b.lines,
                  who=caretaker(ctx.frame))
    return tools.Held(c.CONTINUE if verdict == c.DONE else verdict, (draft,), said)


tools.REPORT_GATES.append(small_gate)


# ── Ce que l'exécution en lit ─────────────────────────────────────────────

#: les tickets entre ses mains que montre le passage, ceux du propriétaire qu'il nomme, et ce qu'il cite d'un titre,
#: du dernier mot d'un fil, d'un plan
TICKETS_SHOWN, WAITING_SHOWN = 12, 10
TITLE_SHOWN, LAST_SHOWN, PLAN_SHOWN = 100, 160, 900


def _last_word(frame: Frame, store: Any, p: Project, item: Item) -> str:
    """Le dernier mot du fil d'un ticket, cité : une donnée."""
    notes = tracker.thread(store, p.id, c.TICKETS, item.key, limit=1)
    if not notes:
        return ""
    note = notes[-1]
    return phrase("projects.tickets.last", by=tracker.who_words(frame, note.author, note.by),
                  text=clipped(" ".join(note.text.split()), LAST_SHOWN) or phrase("projects.tracker.forgotten"))


def ticket_line(frame: Frame, store: Any, p: Project, e: tracker.Entry) -> str:
    """Un ticket tel que le lit le passage : son étape, sa priorité, son titre cité, ce qui est attendu d'elle, le
    dernier mot de son fil."""
    item = e.item
    return phrase(
        "projects.tickets.line", number=item.number, stage=stage_words(item),
        kind=family("projects.tracker.kinds").get(item.kind, item.kind),
        priority=family("projects.tracker.priorities").get(item.priority, item.priority),
        title=clipped(e.title, TITLE_SHOWN) or phrase("projects.tracker.forgotten"),
        by=tracker.who_words(frame, item.author, item.by),
        expected=family("projects.tickets.expected").get(item.status, ""), last=_last_word(frame, store, p, item))


def triage_lines(frame: Frame, store: Any, p: Project) -> tuple[list[str], int]:
    """Ce que lit le passage qui traite les tickets : ceux qui sont entre ses mains, les plus prioritaires d'abord
    (``TICKETS_SHOWN`` au plus), puis, en une ligne, ceux qui attendent le propriétaire — sans leur titre : un
    ticket proposé n'est pas encore à elle (ADR 0272). Et le niveau le plus haut de ce qu'elle y lit."""
    mine = tracker.by_priority(store, p.id, tickets.HERS, TICKETS_SHOWN + 1)
    shown = [e for e in mine[:TICKETS_SHOWN] if not e.item.stuck]
    lines = ["- " + ticket_line(frame, store, p, e) for e in shown]
    if len(mine) > TICKETS_SHOWN:
        lines.append(phrase("projects.tickets.more"))
    theirs = [x for x in p.board.items if x.list_name == c.TICKETS and tickets.hand(x) == c.ACTOR_OWNER]
    if theirs:
        named = ", ".join(phrase("projects.tickets.waiting_one", number=x.number, stage=stage_words(x))
                          for x in theirs[:WAITING_SHOWN])
        lines.append(phrase("projects.tickets.waiting", who=caretaker(frame), tickets=named,
                            more=phrase("projects.tickets.waiting_more", count=len(theirs) - WAITING_SHOWN)
                            if len(theirs) > WAITING_SHOWN else ""))
    return lines, max([0, *(e.item.level for e in shown)])


def own_lines(frame: Frame, store: Any, p: Project, e: tracker.Entry) -> list[str]:
    """Ce que lit l'exécution d'un objectif né d'un ticket : son ticket, et son plan tel qu'il est dans le fil."""
    lines = ["- " + ticket_line(frame, store, p, e)]
    plan = tracker.note_text(store, e.item.plan_seq)
    if plan:
        lines.append(phrase("projects.tickets.plan.yours", plan=clipped(plan, PLAN_SHOWN)))
    return lines
