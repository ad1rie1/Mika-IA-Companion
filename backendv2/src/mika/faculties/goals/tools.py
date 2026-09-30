"""Les outils des buts.

Dans un pas (``STEP``) : ``report_step`` (le verdict, qui clôt le pas),
``goal_note`` (son carnet), ``goal_drop`` (renoncer — seulement à ce qu'elle
a entrepris d'elle-même). En conversation : ``goal_remind`` (un rappel à
l'heure dite) et ``create_project`` (un travail confié — seulement par sa
propriétaire).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.faculties.goals.faculty import GOALS, NOTED, Goal, GoalsState, params, workable
from mika.kernel import schedule
from mika.kernel.clock import MINUTE, instant, local
from mika.kernel.events import Content, Draft
from mika.kernel.frame import Frame
from mika.vocab.episodes import Kind, goal_of
from mika.vocab.privacy import Sensitivity

REPORT, NOTE, DROP = "report_step", "goal_note", "goal_drop"
#: ce qui n'est pas du travail (dire où on en est, renoncer)
NOT_WORK = frozenset({REPORT, DROP})
PROJECT_BUNDLES = ("goals", "memory", "workshop")


def _goal(ctx: Any) -> Goal | None:
    ep = ctx.frame.episode
    gid = goal_of(ep.target) if ep is not None else None
    s: GoalsState = ctx.frame.state("goals")
    g = s.goals.get(gid) if gid is not None else None
    return g if g is not None and workable(g, ctx.frame.now) else None


def title_of(ctx: Any, g: Goal) -> Content:
    store = ctx.ports.get("store")
    text = store.content([g.title_ref]).get(g.title_ref) if store is not None and g.title_ref else None
    return Content.of(text or "(un but dont le titre est oublié)", level=g.sensitivity)


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


GOALS.bundle("goals", "rappels, projets confiés ; noter et rendre compte de ton travail")


@GOALS.tool(REPORT, description="Conclure ce pas de travail par un verdict. « done » n'est cru que si tu as "
            "réellement fait quelque chose (un outil qui a produit un résultat) pendant ce but.",
            args=ReportArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=1)
async def report_step(args: ReportArgs, ctx: Any) -> str:
    g = _goal(ctx)
    if g is None:
        return "Ce but n'est plus en cours."
    worked = tuple(sorted({name for name, ok in ctx.calls if ok and name not in NOT_WORK}))
    proven = args.verdict == c.DONE and (g.evidence + len(worked)) > 0
    summary = Content.of(args.summary.strip(), level=g.sensitivity)
    drafts: list[Any] = [c.STEP_REPORTED.draft(
        goal=g.id, kind=g.kind, verdict=args.verdict, summary=summary, notable=args.notable,
        wait_s=args.wait_minutes * 60, proven=proven, tools=worked, owner=g.owner, about=g.about,
        wait_for=g.owner if args.verdict == c.WAIT and args.until_they_answer and g.owner else None)]
    atelier = ctx.ports.get("workshop")
    if atelier is not None and "workshop" in g.bundles and atelier.exists(g.id):
        await atelier.commit(g.id, args.summary)  # un commit par pas qui a changé quelque chose
    if proven:
        drafts.append(closing(ctx, g, c.ACHIEVED, result=args.summary.strip(), notable=args.notable))
    elif args.verdict == c.BLOCKED:
        drafts.append(closing(ctx, g, c.STUCK, reason=args.summary))
    await ctx.emit(*drafts)
    if proven:
        return "C'est noté : tu l'as mené à bout."
    if args.verdict == c.DONE:
        return ("Tu dis avoir fini, mais rien de concret n'a encore été fait dans ce but (aucun outil n'a produit "
                "de résultat) : ce n'est pas fini. Fais-le, ou dis honnêtement où tu en es.")
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
async def goal_note(args: NoteArgs, ctx: Any) -> str:
    g = _goal(ctx)
    if g is None:
        return "Ce but n'est plus en cours."
    await ctx.emit(NOTED.draft(goal=g.id, text=Content.of(args.text.strip(), level=g.sensitivity), owner=g.owner,
                               about=g.about))
    return "Noté dans ton carnet."


class DropArgs(BaseModel):
    why: str = Field(min_length=1, max_length=300, description="pourquoi tu y renonces")


@GOALS.tool(DROP, description="Renoncer à ce but (seulement à ce que tu as entrepris de toi-même).",
            args=DropArgs, bundle="goals", episodes=[Kind.STEP], max_calls_per_episode=1)
async def goal_drop(args: DropArgs, ctx: Any) -> str:
    g = _goal(ctx)
    if g is None:
        return "Ce but n'est plus en cours."
    if g.authority == c.USER:
        return ("C'est un travail qu'on t'a confié : tu ne peux pas y renoncer de toi-même. Si tu n'y arrives pas, "
                "dis-le (report_step, « blocked »).")
    await ctx.emit(closing(ctx, g, c.ABANDONED, reason=args.why))
    return "D'accord, tu laisses ça de côté."


# ── En conversation ───────────────────────────────────────────────────────


def _person(frame: Frame) -> tuple[str, str] | None:
    ep = frame.episode
    if ep is None or not ep.target:
        return None
    return ep.target, frame.get(identity_c.PERSON(ep.target))


class RemindArgs(BaseModel):
    when: str = Field(description="quand, en heure locale : AAAA-MM-JJTHH:MM (par exemple 2026-09-30T15:00)")
    what: str = Field(min_length=1, max_length=300, description="ce qu'il faudra rappeler, en quelques mots")
    urgent: bool = Field(default=False, description="vrai seulement si c'est important à l'heure pile, "
                                                    "même en pleine nuit")


@GOALS.tool("goal_remind", description="Promettre un rappel à la personne à qui tu parles, à une heure dite.",
            args=RemindArgs, bundle="goals", episodes=[Kind.REPLY], max_calls_per_episode=3)
async def goal_remind(args: RemindArgs, ctx: Any) -> str:
    who = _person(ctx.frame)
    if who is None:
        return "Il n'y a personne à qui faire ce rappel."
    handle, person = who
    tz = ctx.frame.env.tz_of(ctx.frame.root)
    try:
        dt = datetime.fromisoformat(args.when.strip())
    except ValueError:
        return "Je ne lis pas cette date : écris-la AAAA-MM-JJTHH:MM, en heure locale."
    due = instant(dt if dt.tzinfo is not None else dt.replace(tzinfo=tz))
    now = ctx.frame.now
    if due <= now + MINUTE // 2:
        return "Cette heure est déjà passée : donne une date à venir."
    if due > now + 366 * 24 * 60 * MINUTE:
        return "C'est trop loin : un rappel dans l'année, pas au-delà."
    level = int(Sensitivity.PERSONAL)
    await ctx.emit(c.GOAL_OPENED.draft(
        kind=c.REMINDER, authority=c.USER, title=Content.of(args.what.strip(), level=level), owner=person,
        address=handle, about=(person,), due=due, urgent=args.urgent, source="tool", sensitivity=level))
    when = local(due, tz)
    return f"C'est noté : rappel le {when:%d/%m à %H:%M}" + (" (urgent : même la nuit)." if args.urgent else ".")


class ProjectArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=4000, description="le cadre : ce qu'il faut faire, "
                                                                          "comment, et ce qui est hors sujet")
    schedule: str = Field(default="manual", description="manual, interval:2h, ou cron:0 9 * * MON-FRI")
    max_steps: int = Field(default=0, ge=0, le=50, description="0 : la valeur par défaut")
    approval: bool = Field(default=True, description="ce qui sort de la machine attend un accord")


def project_opened(*, title: str, details: str, owner: str | None, address: str | None, rule: str,
                   approval: bool, max_steps: int, source: str, level: int, due: int | None = None) -> Draft[Any]:
    """L'ouverture d'un projet confié (par sa propriétaire en conversation, ou
    par un opérateur depuis la console) : un cadre, un atelier, des pas."""
    return c.GOAL_OPENED.draft(
        kind=c.PROJECT, authority=c.USER, title=Content.of(title.strip(), level=level),
        details=Content.of(details.strip(), level=level) if details.strip() else None, owner=owner,
        address=address, about=(owner,) if owner else (), due=due, bundles=PROJECT_BUNDLES, max_steps=max_steps,
        schedule=rule.strip(), approval=approval, source=source, sensitivity=level)


@GOALS.tool("create_project", description="Accepter un projet que ta propriétaire te confie : il aura son "
            "atelier (un dossier, des programmes isolés) et tu y avanceras par pas.",
            args=ProjectArgs, bundle="goals", episodes=[Kind.REPLY], max_calls_per_episode=1,
            owner_only=True)
async def create_project(args: ProjectArgs, ctx: Any) -> str:
    who = _person(ctx.frame)
    if who is None or not ctx.frame.get(identity_c.IS_OWNER(who[1])):
        return ("Seule ta propriétaire peut te confier un projet. Tu peux proposer d'y réfléchir ensemble, mais "
                "pas l'accepter comme un travail.")
    handle, person = who
    try:
        schedule.parse(args.schedule)
    except ValueError as exc:
        return f"Règle d'agenda refusée : {exc}"
    p = params(ctx.frame.env.params_of("goals", ctx.frame.root))
    commit = await ctx.emit(project_opened(
        title=args.title, details=args.instructions, owner=person, address=handle, rule=args.schedule,
        approval=args.approval, max_steps=args.max_steps or p.project_steps, source="tool",
        level=int(Sensitivity.PERSONAL)))
    number = f" (n° {commit.seqs[-1]})" if commit.seqs else ""
    return f"Projet accepté{number} : tu y travailleras dans ton atelier."
