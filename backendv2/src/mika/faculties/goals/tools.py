"""Les outils des buts.

Dans un pas (``STEP``) : ``report_step`` (le verdict, qui clôt le pas),
``goal_note`` (son carnet), ``goal_reflect`` (ce qu'une réflexion lui a
apporté), ``goal_task_add`` / ``goal_task_update`` (son plan de travail, que
l'opérateur tient aussi), ``goal_drop`` (renoncer — seulement à ce qu'elle a
entrepris d'elle-même). En conversation : ``goal_remind`` (un rappel à l'heure
dite), ``goal_remind_change`` (le décommander ou le déplacer, quand la personne
qui l'a demandé le lui dit — seulement les siens). Les projets sont une faculté
à part (``projects``, ADR 0031).

**« Fini » se prouve** par ce qui touche autre chose que sa tête : lire un
article de ses flux, écrire dans un atelier… Noter, chercher dans sa mémoire,
tenir son plan ou ouvrir un projet ne prouvent rien. Une réflexion sur ce qu'on
lui a confié se prouve en l'écrivant vraiment (``goal_reflect`` : quelques
phrases à elle, pas la redite de ce qu'on lui a dit). Un « fini » non prouvé est
noté mais **n'est pas un verdict** : le pas peut encore conclure. Un refus est
toujours un refus (``ToolResult(ok=False)``), jamais une réussite. La **dernière
séance** qu'un but s'accorde (une réflexion, une rêverie n'en ont qu'une) se
clôt sur ce qu'elle a fait, même si le modèle dit « je reprendrai » : il n'y aura
pas d'autre séance (ADR 0053).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.faculties.goals.faculty import (
    GOAL_REFRAMED,
    GOALS,
    INNER_BUNDLES,
    NOTED,
    TASK_ADDED,
    TASK_CHANGED,
    TASKS_KEPT,
    Goal,
    GoalsState,
    budget,
    musing,
    params,
    task_at,
    workable,
)
from mika.kernel.clock import MINUTE, instant, local
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.vocab.episodes import Kind, goal_of
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity, hearable
from mika.vocab.words import stems

REPORT, NOTE, DROP, REFLECT = "report_step", "goal_note", "goal_drop", "goal_reflect"
TASK_ADD, TASK_UPDATE = "goal_task_add", "goal_task_update"
#: ce qui n'est pas du travail : dire où on en est, renoncer, tenir son plan, noter, fouiller sa mémoire, ouvrir
#: un projet (l'exploration continue alors là-bas)
NOT_WORK = frozenset({REPORT, DROP, TASK_ADD, TASK_UPDATE, NOTE, REFLECT, "memory_search", "start_project"})
#: une réflexion se prouve par quelques phrases à elle
REFLECT_MIN_WORDS = 15
_WORD = re.compile(r"[\wÀ-ÿ']+")


def proves(ctx: Any, name: str) -> bool:
    """Ce que fait cet outil prouve-t-il un travail (il touche autre chose que sa tête) ?"""
    if name in NOT_WORK:
        return False
    spec = ctx.mind.registry.tools.get(name) if getattr(ctx, "mind", None) is not None else None
    return spec is not None and spec.bundle not in INNER_BUNDLES


def reflective(g: Goal) -> bool:
    """Une exploration née de ce qu'on lui a confié, d'une croyance revue, ou une rêverie : son travail, c'est d'y
    repenser — et de l'écrire."""
    if g.origin:
        return g.origin in (c.FROM_EXCHANGE, c.FROM_REVISION) or musing(g)
    return g.kind == c.EXPLORATION and g.source.startswith("thought:")


def last_session(g: Goal, ctx: Any) -> bool:
    """Cette séance est la dernière que ce but s'accorde (elle est déjà comptée à son départ)."""
    return g.steps >= budget(g, params(ctx.frame.env.params_of("goals", ctx.frame.root)))


def _goal(ctx: Any) -> Goal | None:
    ep = ctx.frame.episode
    gid = goal_of(ep.target) if ep is not None else None
    s: GoalsState = ctx.frame.state("goals")
    g = s.goals.get(gid) if gid is not None else None
    return g if g is not None and workable(g, ctx.frame.now) else None


#: un ancien journal mettait dans le titre d'une exploration le texte d'où elle venait (« En savoir plus — « Jeux
#: rétro… » (Le Journal) ») : on en garde ses mots à elle (leur clé dans sa voix), le reste est une citation. Les
#: débuts reconnaissent un texte déjà écrit au journal : ils restent ici, tels qu'ils y sont.
LEGACY_NOTICED, LEGACY_CLEARER = "En savoir plus — ", "Y voir plus clair — "


def titled(g: Goal, texts: Mapping[str, str]) -> tuple[str, str]:
    """(son titre, dans ses mots à elle ; ce qui vient d'ailleurs, à ne montrer que **cité** — vide : rien).

    Une exploration née d'un signal (un titre d'article, l'objet d'un mail, ce qu'une app a dit) vient d'un texte
    qu'elle n'a pas écrit : il reste à part, et ne se montre qu'en citation, inerte. Un ancien journal le mettait
    dans le titre même : on l'en sépare au rendu (le journal, lui, ne se réécrit pas)."""
    title = texts.get(g.title_ref, "")
    if g.kind != c.EXPLORATION or not title:
        return title, ""
    if g.origin == c.FROM_SIGNAL:
        return title, texts.get(g.details_ref, "")
    if not g.origin and g.source.startswith("thought:"):
        if title.startswith(LEGACY_NOTICED):
            return phrase("goals.title.noticed"), title[len(LEGACY_NOTICED):].strip()
        if title.startswith(LEGACY_CLEARER):
            return phrase("goals.title.legacy_thought"), title[len(LEGACY_CLEARER):].strip()
        return phrase("goals.title.thought"), title
    return title, ""


def title_of(ctx: Any, g: Goal) -> Content:
    """Le titre qu'une clôture emporte (son journal, ce qu'elle racontera) : ses mots à elle, jamais un texte venu
    d'ailleurs."""
    store = ctx.ports.get("store")
    texts = store.content([g.title_ref]) if store is not None and g.title_ref else {}
    mine, _ = titled(g, texts)
    return Content.of(mine or phrase("goals.title.forgotten"), level=g.sensitivity)


def closing(ctx: Any, g: Goal, status: str, *, result: str | None = None, notable: float = 0.0,
            reason: str = "") -> Any:
    return c.GOAL_CLOSED.draft(
        goal=g.id, status=status, kind=g.kind, authority=g.authority, title=title_of(ctx, g),
        result=Content.of(result, level=g.sensitivity) if result else None, notable=notable, reason=reason[:300],
        source=g.source, owner=g.owner, about=g.about, sensitivity=g.sensitivity)


class ReportArgs(BaseModel):
    verdict: Literal["continue", "done", "blocked", "wait"] = Field(
        description=phrase("goals.tools.report.verdict"))
    summary: str = Field(min_length=1, max_length=1200, description=phrase("goals.tools.report.summary"))
    notable: float = Field(default=0.5, ge=0.0, le=1.0, description=phrase("goals.tools.report.notable"))
    wait_minutes: int = Field(default=0, ge=0, le=1440)
    until_they_answer: bool = Field(default=False, description=phrase("goals.tools.report.until_they_answer"))


GOALS.bundle("goals", phrase("goals.bundle"))


def _gone() -> ToolResult:
    """La réponse de chaque outil de séance quand le but s'est clos entre-temps."""
    return ToolResult(ok=False, content=phrase("goals.tools.gone"))


@GOALS.tool(REPORT, description=phrase("goals.tools.report.description"), args=ReportArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=3, ends_loop=True)
async def report_step(args: ReportArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return _gone()
    if any(name == REPORT and ok for name, ok in ctx.calls):
        return ToolResult(ok=False, content=phrase("goals.tools.report.already"))
    worked = tuple(sorted({name for name, ok in ctx.calls if ok and (proves(ctx, name) or
                                                                       (name == REFLECT and reflective(g)))}))
    if last_session(g, ctx) and args.verdict in (c.CONTINUE, c.WAIT) and (g.evidence + len(worked)) > 0:
        # sa dernière séance (une réflexion, une rêverie : la seule) : ce qu'elle a écrit la clôt, même si le modèle
        # dit qu'il reprendra — il n'y aura pas d'autre séance (sonde réelle du 2026-10-03 : « continue » après
        # chaque réflexion écrite, quatre séances d'enquête, puis l'invention)
        args = args.model_copy(update={"verdict": c.DONE})
    proven = args.verdict == c.DONE and (g.evidence + len(worked)) > 0
    summary = Content.of(args.summary.strip(), level=g.sensitivity)
    drafts: list[Any] = [c.STEP_REPORTED.draft(
        goal=g.id, kind=g.kind, verdict=args.verdict, summary=summary, notable=args.notable,
        wait_s=args.wait_minutes * 60, proven=proven, tools=worked, owner=g.owner, about=g.about,
        wait_for=g.owner if args.verdict == c.WAIT and args.until_they_answer and g.owner else None)]
    if proven:
        drafts.append(closing(ctx, g, c.ACHIEVED, result=args.summary.strip(), notable=args.notable,
                              reason=c.MUSED if musing(g) else ""))
    elif args.verdict == c.BLOCKED and reflective(g):
        # rêvasser, repenser à ce qu'on lui a confié : ça ne se rate pas — elle en reste là, sans « je bloque »
        drafts.append(closing(ctx, g, c.ABANDONED, reason=c.DISSIPATED if musing(g) else c.LET_GO))
    elif args.verdict == c.BLOCKED:
        drafts.append(closing(ctx, g, c.STUCK, reason=args.summary))
    await ctx.emit(*drafts)
    if proven:
        left = [t.id for t in g.tasks if t.status not in (c.TASK_DONE,)]
        if left:
            return phrase("goals.tools.report.done_with_left", count=len(left),
                          tasks=", ".join(map(str, left[:6])))
        return phrase("goals.tools.report.done")
    if args.verdict == c.DONE:  # noté, mais pas un verdict : la séance peut encore conclure
        how = phrase("goals.tools.report.how_reflect") if reflective(g) else phrase("goals.tools.report.how_work")
        return ToolResult(ok=False, content=phrase("goals.tools.report.not_yet", how=how))
    if args.verdict == c.BLOCKED and reflective(g):
        return phrase("goals.tools.report.let_go")
    if args.verdict == c.BLOCKED:
        return phrase("goals.tools.report.blocked")
    if args.verdict == c.WAIT:
        if args.until_they_answer and g.owner:
            return phrase("goals.tools.report.wait_answer")
        return phrase("goals.tools.report.wait", minutes=max(10, args.wait_minutes))
    return phrase("goals.tools.report.continue")


class NoteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description=phrase("goals.tools.note.text"))


@GOALS.tool(NOTE, description=phrase("goals.tools.note.description"), args=NoteArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=4)
async def goal_note(args: NoteArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return _gone()
    await ctx.emit(NOTED.draft(goal=g.id, text=Content.of(args.text.strip(), level=g.sensitivity), owner=g.owner,
                               about=g.about))
    return phrase("goals.tools.note.done")


class ReflectArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description=phrase("goals.tools.reflect.text"))


def _words(text: str) -> set[str]:
    return {w.lower().strip("'") for w in _WORD.findall(text) if len(w.strip("'")) > 2}


@GOALS.tool(REFLECT, description=phrase("goals.tools.reflect.description"), args=ReflectArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=2)
async def goal_reflect(args: ReflectArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return _gone()
    if not reflective(g):
        return ToolResult(ok=False, content=phrase("goals.tools.reflect.not_reflection"))
    text = args.text.strip()
    mine = _words(text)
    if len(_WORD.findall(text)) < REFLECT_MIN_WORDS:
        return ToolResult(ok=False, content=phrase("goals.tools.reflect.too_short"))
    store = ctx.ports.get("store")
    given = store.content([r for r in (g.title_ref, g.details_ref) if r]) if store is not None else {}
    said = _words(" ".join(given.values()))
    if mine and len(mine & said) / len(mine) > 0.6:
        return ToolResult(ok=False, content=phrase("goals.tools.reflect.echo"))
    await ctx.emit(NOTED.draft(goal=g.id, text=Content.of(text, level=g.sensitivity), owner=g.owner, about=g.about))
    return phrase("goals.tools.reflect.done")


class TaskAddArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500, description=phrase("goals.tools.task_add.text"))


class TaskUpdateArgs(BaseModel):
    task: int = Field(ge=1, description=phrase("goals.tools.task_update.task"))
    status: Literal["todo", "doing", "done", "blocked"] = Field(
        description=phrase("goals.tools.task_update.status"))
    note: str = Field(default="", max_length=1000, description=phrase("goals.tools.task_update.note"))


@GOALS.tool(TASK_ADD, description=phrase("goals.tools.task_add.description"), args=TaskAddArgs,
            bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=5)
async def goal_task_add(args: TaskAddArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return _gone()
    if len(g.tasks) >= TASKS_KEPT:
        return ToolResult(ok=False, content=phrase("goals.tools.task_add.full", count=TASKS_KEPT))
    number = g.task_seq + 1
    await ctx.emit(TASK_ADDED.draft(goal=g.id, task=number, text=Content.of(args.text.strip(), level=g.sensitivity),
                                    author="self", owner=g.owner, about=g.about))
    return phrase("goals.tools.task_add.done", number=number)


@GOALS.tool(TASK_UPDATE, description=phrase("goals.tools.task_update.description"), args=TaskUpdateArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=8)
async def goal_task_update(args: TaskUpdateArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return _gone()
    t = task_at(g, args.task)
    if t is None:
        return ToolResult(ok=False, content=phrase("goals.tools.task_update.unknown", task=args.task))
    note = Content.of(args.note.strip(), level=g.sensitivity) if args.note.strip() else None
    await ctx.emit(TASK_CHANGED.draft(goal=g.id, task=t.id, status=args.status, note=note, author="self",
                                      owner=g.owner, about=g.about))
    return phrase("goals.tools.task_update.done", task=t.id, status=family("goals.task")[args.status])


class DropArgs(BaseModel):
    why: str = Field(min_length=1, max_length=300, description=phrase("goals.tools.drop.why"))


@GOALS.tool(DROP, description=phrase("goals.tools.drop.description"), args=DropArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=1)
async def goal_drop(args: DropArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return _gone()
    if g.authority == c.USER:
        return ToolResult(ok=False, content=phrase("goals.tools.drop.confided"))
    await ctx.emit(closing(ctx, g, c.ABANDONED, reason=args.why))
    return phrase("goals.tools.drop.done")


# ── En conversation ───────────────────────────────────────────────────────


def _person(frame: Frame) -> tuple[str, str] | None:
    ep = frame.episode
    if ep is None or not ep.target:
        return None
    return ep.target, frame.get(identity_c.PERSON(ep.target))


def _due(when: str, frame: Frame) -> int | str:
    """L'heure dite d'un rappel (``AAAA-MM-JJTHH:MM``, en heure locale) — ou pourquoi elle ne convient pas : à
    venir, dans l'année."""
    tz = frame.env.tz_of(frame.root)
    try:
        dt = datetime.fromisoformat(when.strip())
    except ValueError:
        return phrase("goals.tools.date.unreadable")
    due = instant(dt if dt.tzinfo is not None else dt.replace(tzinfo=tz))
    now = frame.now
    if due <= now + MINUTE // 2:
        return phrase("goals.tools.date.past")
    if due > now + 366 * 24 * 60 * MINUTE:
        return phrase("goals.tools.date.too_far")
    return due


class RemindArgs(BaseModel):
    when: str = Field(description=phrase("goals.tools.remind.when"))
    what: str = Field(min_length=1, max_length=300, description=phrase("goals.tools.remind.what"))
    urgent: bool = Field(default=False, description=phrase("goals.tools.remind.urgent"))


@GOALS.tool("goal_remind", description=phrase("goals.tools.remind.description"), args=RemindArgs, bundle="goals", episodes=[Kind.REPLY], max_calls_per_episode=3)
async def goal_remind(args: RemindArgs, ctx: Any) -> Any:
    who = _person(ctx.frame)
    if who is None:
        return ToolResult(ok=False, content=phrase("goals.tools.remind.nobody"))
    handle, person = who
    due = _due(args.when, ctx.frame)
    if isinstance(due, str):
        return ToolResult(ok=False, content=due)
    level = int(Sensitivity.PERSONAL)
    await ctx.emit(c.GOAL_OPENED.draft(
        kind=c.REMINDER, authority=c.USER, title=Content.of(args.what.strip(), level=level), owner=person,
        address=handle, about=(person,), due=due, urgent=args.urgent, source="tool", sensitivity=level))
    when = date_time(local(due, ctx.frame.env.tz_of(ctx.frame.root)))
    return phrase("goals.tools.remind.done_urgent", when=when) if args.urgent else \
        phrase("goals.tools.remind.done", when=when)


CANCEL, MOVE = "cancel", "move"
#: la raison de sa clôture quand la personne le décommande : « annulé », sans rien ressentir ni rien raconter
NO_LONGER_NEEDED = "la personne n'en a plus besoin"
#: les mots du rappel lui-même (des radicaux) : ils ne disent pas duquel il s'agit
_REMINDER_STEMS = frozenset({"rappel", "penser", "oublie", "noubli"})


class RemindChangeArgs(BaseModel):
    what: str = Field(min_length=1, max_length=300, description=phrase("goals.tools.remind_change.what"))
    action: Literal["cancel", "move"] = Field(description=phrase("goals.tools.remind_change.action"))
    when: str = Field(default="", description=phrase("goals.tools.remind_change.when"))


def _reminders(s: GoalsState, person: str, now: int) -> list[Goal]:
    """Les rappels encore à dire que cette personne lui a demandés, du plus proche au plus lointain."""
    return sorted((g for g in s.goals.values() if g.kind == c.REMINDER and g.owner == person and not g.delivered
                   and workable(g, now)), key=lambda g: (g.due or 0, g.id))


def _which(reminders: list[Goal], what: str, texts: Mapping[str, str]) -> Goal | None:
    """Le rappel dont il s'agit : le seul qu'il y a, sinon celui qui a le plus de mots du sujet en commun avec ce
    qu'elle en dit — s'il est seul dans ce cas (sinon rien : elle demande lequel)."""
    if len(reminders) == 1:
        return reminders[0]
    said = stems(what) - _REMINDER_STEMS
    scored = [(len(said & stems(texts.get(g.title_ref, ""))), g) for g in reminders]
    best = max((n for n, _ in scored), default=0)
    top = [g for n, g in scored if n == best]
    return top[0] if best and len(top) == 1 else None


def _shown(g: Goal, texts: Mapping[str, str], frame: Frame, person: str) -> str:
    """Un rappel en mots : son heure, et son texte s'il peut s'entendre ici (la règle de « ce que tu as en
    train »)."""
    when = phrase("goals.tools.remind_change.of_date", when=date_time(local(g.due, frame.env.tz_of(frame.root)))) \
        if g.due is not None else ""
    title, aud = texts.get(g.title_ref, ""), frame.audience
    if title and aud is not None and hearable(g.about, g.sensitivity, person, aud.level, aud.witness_level,
                                              aud.private_ok):
        return phrase("goals.tools.remind_change.titled", when=when, title=title)
    return when


@GOALS.tool("goal_remind_change", description=phrase("goals.tools.remind_change.description"),
            args=RemindChangeArgs, bundle="goals", episodes=[Kind.REPLY], max_calls_per_episode=3,
            rule="seulement un rappel encore à dire, demandé par la personne à qui elle parle")
async def goal_remind_change(args: RemindChangeArgs, ctx: Any) -> Any:
    who = _person(ctx.frame)
    if who is None:
        return ToolResult(ok=False, content=phrase("goals.tools.remind_change.nobody"))
    _handle, person = who
    due = _due(args.when, ctx.frame) if args.action == MOVE else None
    if isinstance(due, str):
        return ToolResult(ok=False, content=due if args.when.strip() else
                          phrase("goals.tools.remind_change.no_time"))
    s: GoalsState = ctx.frame.state("goals")
    reminders = _reminders(s, person, ctx.frame.now)
    if not reminders:
        return ToolResult(ok=False, content=phrase("goals.tools.remind_change.none"))
    store = ctx.ports.get("store")
    refs = [g.title_ref for g in reminders if g.title_ref]
    texts = store.content(refs) if store is not None and refs else {}
    g = _which(reminders, args.what, texts)
    if g is None:
        listed = "\n".join(phrase("goals.tools.remind_change.listed", shown=_shown(r, texts, ctx.frame, person))
                           for r in reminders)
        return ToolResult(ok=False, content=phrase("goals.tools.remind_change.which", listed=listed))
    shown = _shown(g, texts, ctx.frame, person)
    if due is not None and due == g.due:
        return phrase("goals.tools.remind_change.same", shown=shown)
    if args.action == CANCEL:
        draft = closing(ctx, g, c.CANCELLED, reason=NO_LONGER_NEEDED)
    else:  # une nouvelle heure : ses tentatives repartent de zéro (le réducteur)
        draft = GOAL_REFRAMED.draft(goal=g.id, due=due, owner=g.owner, about=g.about)
    still = Guard("rappel encore à dire", predicate=lambda view, gid=g.id: view.get(c.STATUS(gid)) == c.ACTIVE)
    try:
        await ctx.emit(draft, guard=still)
    except Superseded:
        if ctx.mind.frame().get(c.STATUS(g.id)) == c.ACTIVE:
            raise  # c'est la garde de la conversation qui a cédé
        return ToolResult(ok=False, content=phrase("goals.tools.remind_change.changed"))
    if due is None:
        return phrase("goals.tools.remind_change.cancelled", shown=shown)
    when = date_time(local(due, ctx.frame.env.tz_of(ctx.frame.root)))
    return phrase("goals.tools.remind_change.moved", shown=shown, when=when)


def date_time(at: datetime) -> str:
    """« 30/09 à 15:00 » : le jour et l'heure d'un rappel."""
    return phrase("goals.date_time", date=f"{at:%d/%m}", time=f"{at:%H:%M}")
