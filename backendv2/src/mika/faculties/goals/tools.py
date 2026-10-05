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
#: rétro… » (Le Journal) ») : on en garde ses mots à elle, le reste est une citation
LEGACY_TITLES = (("En savoir plus — ", "En savoir plus sur ce que j'ai remarqué"),
                 ("Y voir plus clair — ", "Y voir plus clair sur ce qui me trotte dans la tête"))
LEGACY_DEFAULT = "Repenser à ce qui me trotte dans la tête"


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
        for prefix, mine in LEGACY_TITLES:
            if title.startswith(prefix):
                return mine, title[len(prefix):].strip()
        return LEGACY_DEFAULT, title
    return title, ""


def title_of(ctx: Any, g: Goal) -> Content:
    """Le titre qu'une clôture emporte (son journal, ce qu'elle racontera) : ses mots à elle, jamais un texte venu
    d'ailleurs."""
    store = ctx.ports.get("store")
    texts = store.content([g.title_ref]) if store is not None and g.title_ref else {}
    mine, _ = titled(g, texts)
    return Content.of(mine or "(un but dont le titre est oublié)", level=g.sensitivity)


def closing(ctx: Any, g: Goal, status: str, *, result: str | None = None, notable: float = 0.0,
            reason: str = "") -> Any:
    return c.GOAL_CLOSED.draft(
        goal=g.id, status=status, kind=g.kind, authority=g.authority, title=title_of(ctx, g),
        result=Content.of(result, level=g.sensitivity) if result else None, notable=notable, reason=reason[:300],
        source=g.source, owner=g.owner, about=g.about, sensitivity=g.sensitivity)


class ReportArgs(BaseModel):
    verdict: Literal["continue", "done", "blocked", "wait"] = Field(
        description="continue : tu reprendras plus tard ; done : c'est fait ; blocked : tu n'y arrives pas ; "
                    "wait : tu attends quelque chose (dis combien de temps)")
    summary: str = Field(min_length=1, max_length=1200, description="où tu en es, ou ce que tu as trouvé")
    notable: float = Field(default=0.5, ge=0.0, le=1.0,
                           description="à quel point ce résultat compte pour toi (0 : ordinaire, 1 : à raconter)")
    wait_minutes: int = Field(default=0, ge=0, le=1440)
    until_they_answer: bool = Field(default=False, description="avec « wait » : tu attends la réponse de la "
                                                               "personne concernée — tu reprendras dès qu'elle écrit")


GOALS.bundle("goals", "tes rappels et tes explorations ; noter et rendre compte d'une séance")


@GOALS.tool(REPORT, description="Conclure cette séance de travail par un verdict. « done » n'est cru que si tu as "
            "réellement fait quelque chose pendant ce but (lu, écrit, cherché ailleurs que dans ta mémoire ; pour une "
            "réflexion, l'avoir écrite avec goal_reflect) ; sinon il est noté, refusé, et tu peux conclure autrement.",
            args=ReportArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=3, ends_loop=True)
async def report_step(args: ReportArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return ToolResult(ok=False, content="Ce but n'est plus en cours.")
    if any(name == REPORT and ok for name, ok in ctx.calls):
        return ToolResult(ok=False, content="Tu as déjà conclu cette séance : arrête-toi là.")
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
            return (f"C'est noté : tu l'as mené à bout — mais ton plan avait encore {len(left)} tâche(s) non "
                    f"cochée(s) ({', '.join(map(str, left[:6]))}).")
        return "C'est noté : tu l'as mené à bout."
    if args.verdict == c.DONE:  # noté, mais pas un verdict : la séance peut encore conclure
        how = ("écris ce que ta réflexion t'a apporté (goal_reflect)" if reflective(g) else
               "va lire, chercher ou faire quelque chose ailleurs que dans ta mémoire")
        return ToolResult(ok=False, content=(
            f"Pas encore : rien de concret n'a été fait pour ce but (noter ou fouiller ta mémoire ne suffit pas). "
            f"Pour en venir à bout, {how} ; sinon dis honnêtement où tu en es (« continue », « blocked », "
            "« wait »)."))
    if args.verdict == c.BLOCKED and reflective(g):
        return "D'accord : tu en restes là pour l'instant."
    if args.verdict == c.BLOCKED:
        return "C'est noté : tu bloques là-dessus."
    if args.verdict == c.WAIT:
        if args.until_they_answer and g.owner:
            return "D'accord : tu reprendras dès que la personne concernée t'aura répondu (ou à l'échéance)."
        return f"D'accord : tu y reviendras dans {max(10, args.wait_minutes)} minutes au plus tôt."
    return "C'est noté : tu reprendras plus tard."


class NoteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description="ce que tu veux garder pour la suite")


@GOALS.tool(NOTE, description="Écrire dans le carnet de ce but (ce que tu as trouvé, compris, décidé).",
            args=NoteArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=4)
async def goal_note(args: NoteArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return ToolResult(ok=False, content="Ce but n'est plus en cours.")
    await ctx.emit(NOTED.draft(goal=g.id, text=Content.of(args.text.strip(), level=g.sensitivity), owner=g.owner,
                               about=g.about))
    return "Noté dans ton carnet."


class ReflectArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000,
                      description="ce que ta réflexion t'a apporté, en quelques phrases à toi : ce que tu comprends "
                                  "mieux, ce qui pourrait aider, ce que tu aimerais lui dire ou lui demander")


def _words(text: str) -> set[str]:
    return {w.lower().strip("'") for w in _WORD.findall(text) if len(w.strip("'")) > 2}


@GOALS.tool(REFLECT, description="Écrire ce qu'une réflexion t'a apporté (seulement quand tu repenses à ce qu'on "
            "t'a confié, ou à ce que tu croyais) : quelques phrases à toi, pas la redite de ce qu'on t'a dit.",
            args=ReflectArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=2)
async def goal_reflect(args: ReflectArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return ToolResult(ok=False, content="Ce but n'est plus en cours.")
    if not reflective(g):
        return ToolResult(ok=False, content="Ce but n'est pas une réflexion : avance-le en allant chercher ailleurs "
                                            "(tes outils), et garde tes notes avec goal_note.")
    text = args.text.strip()
    mine = _words(text)
    if len(_WORD.findall(text)) < REFLECT_MIN_WORDS:
        return ToolResult(ok=False, content="Un peu court pour une réflexion : dis ce que tu en penses vraiment, en "
                                            "quelques phrases.")
    store = ctx.ports.get("store")
    given = store.content([r for r in (g.title_ref, g.details_ref) if r]) if store is not None else {}
    said = _words(" ".join(given.values()))
    if mine and len(mine & said) / len(mine) > 0.6:
        return ToolResult(ok=False, content="Tu redis surtout ce qu'on t'a dit : écris ce que toi, tu en penses.")
    await ctx.emit(NOTED.draft(goal=g.id, text=Content.of(text, level=g.sensitivity), owner=g.owner, about=g.about))
    return "Gardé : c'est ta réflexion."


class TaskAddArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="une étape à faire, en une phrase")


class TaskUpdateArgs(BaseModel):
    task: int = Field(ge=1, description="le numéro de la tâche (dans ton plan de travail)")
    status: Literal["todo", "doing", "done", "blocked"] = Field(
        description="todo : à faire ; doing : en cours ; done : faite ; blocked : tu bloques dessus")
    note: str = Field(default="", max_length=1000, description="son résultat, ou pourquoi tu bloques")


@GOALS.tool(TASK_ADD, description="Ajouter une étape à ton plan de travail pour ce but.", args=TaskAddArgs,
            bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=5)
async def goal_task_add(args: TaskAddArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return ToolResult(ok=False, content="Ce but n'est plus en cours.")
    if len(g.tasks) >= TASKS_KEPT:
        return ToolResult(ok=False, content=f"Ton plan a déjà {TASKS_KEPT} tâches : termine ou regroupe-en.")
    number = g.task_seq + 1
    await ctx.emit(TASK_ADDED.draft(goal=g.id, task=number, text=Content.of(args.text.strip(), level=g.sensitivity),
                                    author="self", owner=g.owner, about=g.about))
    return f"Ajoutée à ton plan : tâche {number}."


@GOALS.tool(TASK_UPDATE, description="Mettre à jour une tâche de ton plan de travail (en cours, faite, bloquée…).",
            args=TaskUpdateArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=8)
async def goal_task_update(args: TaskUpdateArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return ToolResult(ok=False, content="Ce but n'est plus en cours.")
    t = task_at(g, args.task)
    if t is None:
        return ToolResult(ok=False, content=f"Il n'y a pas de tâche {args.task} dans ton plan.")
    note = Content.of(args.note.strip(), level=g.sensitivity) if args.note.strip() else None
    await ctx.emit(TASK_CHANGED.draft(goal=g.id, task=t.id, status=args.status, note=note, author="self",
                                      owner=g.owner, about=g.about))
    return f"Tâche {t.id} : {TASK_WORDS[args.status]}."


TASK_WORDS = {c.TODO: "à faire", c.DOING: "en cours", c.TASK_DONE: "faite", c.TASK_BLOCKED: "bloquée"}


class DropArgs(BaseModel):
    why: str = Field(min_length=1, max_length=300, description="pourquoi tu y renonces")


@GOALS.tool(DROP, description="Renoncer à ce but (seulement à ce que tu as entrepris de toi-même).",
            args=DropArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=1)
async def goal_drop(args: DropArgs, ctx: Any) -> Any:
    g = _goal(ctx)
    if g is None:
        return ToolResult(ok=False, content="Ce but n'est plus en cours.")
    if g.authority == c.USER:
        return ToolResult(ok=False, content=(
            "C'est quelque chose qu'on t'a confié : tu ne peux pas y renoncer de toi-même. Si tu n'y arrives pas, "
            "dis-le (report_step, « blocked »)."))
    await ctx.emit(closing(ctx, g, c.ABANDONED, reason=args.why))
    return "D'accord, tu laisses ça de côté."


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
        return "Je ne lis pas cette date : écris-la AAAA-MM-JJTHH:MM, en heure locale."
    due = instant(dt if dt.tzinfo is not None else dt.replace(tzinfo=tz))
    now = frame.now
    if due <= now + MINUTE // 2:
        return "Cette heure est déjà passée : donne une date à venir."
    if due > now + 366 * 24 * 60 * MINUTE:
        return "C'est trop loin : un rappel dans l'année, pas au-delà."
    return due


class RemindArgs(BaseModel):
    when: str = Field(description="quand, en heure locale : AAAA-MM-JJTHH:MM (par exemple 2026-09-30T15:00)")
    what: str = Field(min_length=1, max_length=300, description="ce qu'il faudra rappeler, en quelques mots")
    urgent: bool = Field(default=False, description="vrai seulement si c'est important à l'heure pile, "
                                                    "même en pleine nuit")


@GOALS.tool("goal_remind", description="Promettre un rappel à la personne à qui tu parles, à une heure dite.",
            args=RemindArgs, bundle="goals", episodes=[Kind.REPLY], max_calls_per_episode=3)
async def goal_remind(args: RemindArgs, ctx: Any) -> Any:
    who = _person(ctx.frame)
    if who is None:
        return ToolResult(ok=False, content="Il n'y a personne à qui faire ce rappel.")
    handle, person = who
    due = _due(args.when, ctx.frame)
    if isinstance(due, str):
        return ToolResult(ok=False, content=due)
    level = int(Sensitivity.PERSONAL)
    await ctx.emit(c.GOAL_OPENED.draft(
        kind=c.REMINDER, authority=c.USER, title=Content.of(args.what.strip(), level=level), owner=person,
        address=handle, about=(person,), due=due, urgent=args.urgent, source="tool", sensitivity=level))
    when = local(due, ctx.frame.env.tz_of(ctx.frame.root))
    return f"C'est noté : rappel le {when:%d/%m à %H:%M}" + (" (urgent : même la nuit)." if args.urgent else ".")


CANCEL, MOVE = "cancel", "move"
#: la raison de sa clôture quand la personne le décommande : « annulé », sans rien ressentir ni rien raconter
NO_LONGER_NEEDED = "la personne n'en a plus besoin"
#: les mots du rappel lui-même (des radicaux) : ils ne disent pas duquel il s'agit
_REMINDER_STEMS = frozenset({"rappel", "penser", "oublie", "noubli"})


class RemindChangeArgs(BaseModel):
    what: str = Field(min_length=1, max_length=300, description="de quel rappel il s'agit, en quelques mots")
    action: Literal["cancel", "move"] = Field(description="cancel : le décommander (il ne sert plus) ; move : le "
                                                          "déplacer à l'heure donnée dans « when »")
    when: str = Field(default="", description="avec « move » : la nouvelle heure, en heure locale : "
                                              "AAAA-MM-JJTHH:MM (par exemple 2026-09-30T19:00)")


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
    when = f" du {local(g.due, frame.env.tz_of(frame.root)):%d/%m à %H:%M}" if g.due is not None else ""
    title, aud = texts.get(g.title_ref, ""), frame.audience
    if title and aud is not None and hearable(g.about, g.sensitivity, person, aud.level, aud.witness_level,
                                              aud.private_ok):
        return f"{when} (« {title} »)"
    return when


@GOALS.tool("goal_remind_change", description="Décommander un rappel que la personne à qui tu parles t'a demandé "
            "(il ne sert plus), ou le déplacer à une autre heure — au lieu d'en promettre un second.",
            args=RemindChangeArgs, bundle="goals", episodes=[Kind.REPLY], max_calls_per_episode=3,
            rule="seulement un rappel encore à dire, demandé par la personne à qui elle parle")
async def goal_remind_change(args: RemindChangeArgs, ctx: Any) -> Any:
    who = _person(ctx.frame)
    if who is None:
        return ToolResult(ok=False, content="Il n'y a personne dont changer le rappel.")
    _handle, person = who
    due = _due(args.when, ctx.frame) if args.action == MOVE else None
    if isinstance(due, str):
        return ToolResult(ok=False, content=due if args.when.strip() else
                          "Dis à quelle heure le déplacer : AAAA-MM-JJTHH:MM, en heure locale.")
    s: GoalsState = ctx.frame.state("goals")
    reminders = _reminders(s, person, ctx.frame.now)
    if not reminders:
        return ToolResult(ok=False, content="Cette personne n'a aucun rappel en attente avec toi (déjà dit, ou "
                                            "jamais promis) : rien n'a changé.")
    store = ctx.ports.get("store")
    refs = [g.title_ref for g in reminders if g.title_ref]
    texts = store.content(refs) if store is not None and refs else {}
    g = _which(reminders, args.what, texts)
    if g is None:
        listed = "\n".join(f"- le rappel{_shown(r, texts, ctx.frame, person)}" for r in reminders)
        return ToolResult(ok=False, content=(
            f"Cette personne a plusieurs rappels en attente, et je ne sais pas duquel il s'agit :\n{listed}\n"
            "Rien n'a changé : demande-lui lequel, puis recommence avec ses mots."))
    shown = _shown(g, texts, ctx.frame, person)
    if due is not None and due == g.due:
        return f"Le rappel{shown} est déjà prévu à cette heure-là : rien à changer."
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
        return ToolResult(ok=False, content="Ce rappel a changé entre-temps (déjà dit, ou clos) : rien n'a changé.")
    if due is None:
        return f"C'est décommandé : le rappel{shown} ne partira pas."
    when = local(due, ctx.frame.env.tz_of(ctx.frame.root))
    return f"C'est noté : le rappel{shown} est déplacé au {when:%d/%m à %H:%M}."
