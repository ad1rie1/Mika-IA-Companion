"""Les outils des projets.

Pendant une exécution (``WORK`` ou ``JOB``) : ``report_run`` (le verdict, qui la
clôt), ``project_note`` (son carnet), ``project_decide`` (une décision
technique, qui peut en remplacer une autre), ``project_objective_add`` (un
objectif de plus). En conversation : ``create_project`` (un projet qu'on lui
confie — seulement quelqu'un qui s'occupe d'elle) et ``start_project`` (un
projet à elle — aussi pendant une exploration qui s'avère plus grosse qu'une
envie). Partout : ``project_close`` (clore un projet à elle).

**« Fait » se prouve** : pour un objectif ponctuel, un commit non vide pendant
l'objectif (ce qu'elle a écrit dans l'atelier), ou un brouillon de mail, une
app forgée. Lancer ``ls``, lire, noter ou décider ne prouvent rien. Un « fait »
qui ne se prouve pas **n'est pas un verdict** : il est refusé sans rien écrire,
et elle peut encore conclure honnêtement (``report_run`` admet trois appels,
un seul verdict).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import (
    ARCHIVED,
    DECIDED,
    DECISIONS_KEPT,
    DEFAULT_BUNDLES,
    NOTED,
    OBJECTIVE_ADDED,
    OBJECTIVES_KEPT,
    PROJECTS,
    PUSH,
    Objective,
    Project,
    ProjectsState,
    cadence,
    check_schedule,
    decision_at,
    in_force,
    live,
    living,
    objective_at,
    objective_of,
    params,
)
from mika.kernel.clock import HOUR
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.vocab.episodes import PROJECT_KINDS, Kind, goal_of, project_of, project_target
from mika.vocab.privacy import Sensitivity

REPORT, NOTE, DECIDE, OBJECTIVE_ADD = "report_run", "project_note", "project_decide", "project_objective_add"
#: ce qui change quelque chose (le compte rendu le dit) : écrire, modifier, un programme qui a réussi, un
#: brouillon, une app forgée
CHANGING = frozenset({"ws_write", "ws_edit", "ws_run", "email_draft", "forge_write"})
#: …et ce qui, hors de l'atelier, **prouve** qu'une exécution a produit (dans l'atelier, c'est le commit)
PRODUCING = frozenset({"email_draft", "forge_write"})
RUNS = list(PROJECT_KINDS)
#: le nom de l'opérateur ou de la propriétaire, ou ces mots quand on ne le sait pas
CARETAKER = "la personne qui s'occupe de toi"

PROJECTS.bundle("projects", "tes projets : en ouvrir un, en accepter un qu'on te confie, en clore un à toi ; pendant "
                            "une exécution, la conclure, ton carnet, tes décisions techniques, tes objectifs")


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
    return f"« {names[0]} »" if len(names) == 1 else CARETAKER


GONE = "Ce projet n'est plus actif (en pause ou archivé) : arrête-toi là."


def written(p: Project) -> int:
    """Le niveau de ce qu'elle écrit pendant une exécution (compte rendu, carnet, décisions, résultat) : elle y
    voit toute sa mémoire, ce qui en sort est au moins personnel."""
    return max(p.sensitivity, int(Sensitivity.PERSONAL))


def wrap_up(ctx: Any, out: Any) -> Any:
    """Au-delà de quelques appels, chaque résultat lui rappelle de conclure : une exécution qui s'arrête sans
    verdict ne compte pas comme du travail (et le délai d'une exécution est court)."""
    pm = params(ctx.frame.env.params_of("projects", ctx.frame.root))
    done = any(name == REPORT and ok for name, ok in ctx.calls)
    if done or len(ctx.calls) + 1 < pm.wrap_up_after:
        return out
    note = "\n(Ton exécution touche à sa fin : conclus maintenant par report_run — « continue » si ce n'est pas fini.)"
    if isinstance(out, ToolResult):
        return ToolResult(ok=out.ok, content=out.content + note)
    return f"{out}{note}"


def still_open(project: int, objective: int) -> Guard:
    """Une clôture ne vaut que pour un objectif encore ouvert (l'opérateur a pu le retirer entre-temps)."""
    return Guard("objectif ouvert", predicate=lambda view, k=(project, objective):
                 view.get(c.OBJECTIVE_STATUS(k)) == c.OPEN)


class ReportArgs(BaseModel):
    verdict: Literal["continue", "done", "blocked", "wait"] = Field(
        description="continue : tu reprendras à une prochaine exécution ; done : l'objectif visé est fait (pour un "
                    "objectif constant : ce passage est fait) ; blocked : tu n'y arrives pas ; wait : tu attends "
                    "quelque chose (dis combien de temps)")
    summary: str = Field(min_length=1, max_length=1500, description="ce que tu as fait, où tu en es, ce qui reste")
    notable: float = Field(default=0.5, ge=0.0, le=1.0,
                           description="à quel point ce résultat compte (0 : ordinaire, 1 : à raconter)")
    wait_minutes: int = Field(default=0, ge=0, le=1440)
    needs_you: str = Field(default="", max_length=600,
                           description="ce qu'il te faudrait de qui t'a confié ce projet pour avancer (une réponse, "
                                       "un accès, une décision) ; vide : rien — sinon tu le lui diras")


def _proof(ctx: Any, sha: str) -> str:
    """Ce qui prouve que cette exécution a produit : un commit non vide, sinon un brouillon ou une app réussis."""
    if sha:
        return "commit"
    return "outil" if any(ok and name in PRODUCING for name, ok in ctx.calls) else ""


def commit_message(p: Project, o: Objective | None) -> str:
    """Un message de commit neutre : il part peut-être vers un dépôt distant, il ne nomme personne et ne raconte
    rien (le compte rendu, lui, reste dans sa vie, là où l'oubli l'atteint)."""
    return f"exécution {p.runs} · objectif n° {o.id}" if o is not None else f"exécution {p.runs}"


@PROJECTS.tool(REPORT, description="Conclure cette exécution par un verdict sur l'objectif visé. « done » n'est cru, "
               "pour un objectif ponctuel, que si quelque chose a été produit pour lui (un fichier écrit dans "
               "l'atelier, un brouillon, une app) ; sinon il est refusé et tu peux conclure autrement.",
               args=ReportArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=3)
async def report_run(args: ReportArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return GONE
    if any(name == REPORT and ok for name, ok in ctx.calls):
        return ToolResult(ok=False, content="Tu as déjà conclu cette exécution : arrête-toi là.")
    p, o = got
    worked = tuple(sorted({name for name, ok in ctx.calls if ok and name in CHANGING}))
    summary = args.summary.strip()
    port = ctx.ports.get("workshop")
    sha = ""
    if port is not None and port.exists(p.id):
        sha = await port.commit(p.id, commit_message(p, o))  # un commit par exécution qui a changé quelque chose
    proof = _proof(ctx, sha)
    gone = o is not None and o.status != c.OPEN  # retiré ou clos pendant qu'elle y travaillait
    proven = args.verdict == c.DONE and o is not None and not gone and (bool(proof) or o.evidence > 0)
    if args.verdict == c.DONE and o is not None and not gone and o.kind == c.ONCE and not proven:
        # pas un verdict : rien ne s'écrit, elle peut encore conclure honnêtement
        return ToolResult(ok=False, content=(
            "Pas encore : rien n'a été produit pour cet objectif (aucun fichier écrit dans l'atelier, aucun brouillon, "
            "aucune app). Lancer une commande, lire ou noter ne suffit pas. Fais-le, ou conclus honnêtement avec "
            "« continue », « blocked » ou « wait »."))
    need = args.needs_you.strip()
    report = c.RUN_REPORTED.draft(
        project=p.id, objective=o.id if o is not None else 0, verdict=args.verdict,
        summary=Content.of(summary, level=written(p)), notable=args.notable, mode=p.mode, proven=proven,
        tools=worked, commit=sha, proof=proof, wait_s=args.wait_minutes * 60, owner=p.owner, about=p.about,
        need=Content.of(need, level=written(p)) if need else None)
    if o is not None and not gone and o.kind == c.ONCE and (proven or args.verdict == c.BLOCKED):
        try:
            await ctx.emit(report, closing(ctx, p, o, c.DONE if proven else c.BLOCKED, summary, args.notable),
                           guard=still_open(p.id, o.id))
        except Superseded:  # l'objectif a changé entre-temps : le compte rendu reste, la clôture non
            if ctx.mind.frame().get(c.OBJECTIVE_STATUS((p.id, o.id))) == c.OPEN:
                raise  # c'est la garde de l'exécution qui a cédé (le projet n'est plus actif)
            await ctx.emit(report)
            gone = True
    else:
        await ctx.emit(report)
    pushed = ""
    if sha and p.auto_push and p.remote:
        pushed = {"proposed": " L'envoi au dépôt distant est proposé (il attend un accord).",
                  "sent": " L'envoi au dépôt distant est parti.",
                  "pending": " Un envoi au dépôt distant attend déjà un accord : celui-ci suivra."}.get(
            await propose_push(ctx, p, "après l'exécution"), "")
    kept = f" Enregistré dans l'atelier ({sha})." if sha else ""
    asked = " Tu le diras à qui t'a confié ce projet." if need else ""
    if gone:
        return ("C'est noté, mais cet objectif n'est plus ouvert (il a été retiré ou clos pendant que tu y "
                "travaillais) : ton compte rendu reste, rien n'est coché." + kept + pushed)
    if o is None:
        return "C'est noté." + kept + pushed + asked
    if o.kind == c.CONSTANT:
        if args.verdict in (c.DONE, c.BLOCKED):
            pm = params(ctx.frame.env.params_of("projects", ctx.frame.root))
            hours = max(1, round(cadence(o, pm) / HOUR))
            return f"Passage noté : cet objectif constant reviendra dans {hours} h environ.{kept}{pushed}{asked}"
        return "C'est noté : tu reprendras cet objectif à une prochaine exécution." + kept + pushed + asked
    if proven:
        return f"C'est noté : l'objectif n° {o.id} est atteint.{kept}{pushed}"
    if args.verdict == c.BLOCKED:
        return f"C'est noté : tu bloques sur l'objectif n° {o.id}.{kept}{asked}"
    if args.verdict == c.WAIT:
        return f"D'accord : tu y reviendras dans {max(10, args.wait_minutes)} minutes au plus tôt.{kept}{asked}"
    return "C'est noté : tu reprendras à une prochaine exécution." + kept + pushed + asked


def closing(ctx: Any, p: Project, o: Objective, status: str, result: str, notable: float) -> Draft[Any]:
    return c.OBJECTIVE_CLOSED.draft(
        project=p.id, objective=o.id, status=status, mode=p.mode, authority=p.authority,
        title=text_of(ctx, o.text_ref, p.sensitivity, "(un objectif dont le texte est oublié)"),
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
    text: str = Field(min_length=1, max_length=2000, description="ce que tu veux garder pour la suite")


@PROJECTS.tool(NOTE, description="Écrire dans le carnet de ce projet (ce que tu as trouvé, compris, ce qui reste).",
               args=NoteArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=4)
async def project_note(args: NoteArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return GONE
    p, _ = got
    await ctx.emit(NOTED.draft(project=p.id, text=Content.of(args.text.strip(), level=written(p)), owner=p.owner,
                               about=p.about))
    return wrap_up(ctx, "Noté dans le carnet du projet.")


class DecideArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="la question tranchée, en quelques mots "
                                                                 "(« stockage des réglages »)")
    choice: str = Field(min_length=1, max_length=1500, description="ce qui est choisi")
    context: str = Field(default="", max_length=2000, description="ce qui rendait la décision nécessaire")
    options: str = Field(default="", max_length=2000, description="les options envisagées")
    reason: str = Field(default="", max_length=1500, description="pourquoi ce choix plutôt qu'un autre")
    replaces: int = Field(default=0, ge=0, description="le numéro d'une décision en vigueur qu'elle remplace (0 : "
                                                       "aucune)")


@PROJECTS.tool(DECIDE, description="Consigner une décision technique de ce projet (ce qui est choisi, pourquoi). Elle "
               "sera relue à chaque exécution ; pour revenir sur une décision, remplace-la (replaces).",
               args=DecideArgs, bundle="projects", episodes=RUNS, max_calls_per_episode=4)
async def project_decide(args: DecideArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return GONE
    p, o = got
    if args.replaces:
        old = decision_at(p, args.replaces)
        if old is None or old.status != c.IN_FORCE:
            return ToolResult(ok=False, content=f"Il n'y a pas de décision n° {args.replaces} en vigueur à remplacer.")
    elif in_force(p) >= DECISIONS_KEPT:
        return ToolResult(ok=False, content=f"Ce projet a déjà {DECISIONS_KEPT} décisions en vigueur : remplace-en "
                                            "une (replaces) plutôt que d'en ajouter.")
    level = written(p)

    def opt(text: str) -> Content | None:
        return Content.of(text.strip(), level=level) if text.strip() else None

    number = p.decision_seq + 1
    commit = await ctx.emit(DECIDED.draft(
        project=p.id, decision=number, title=Content.of(args.title.strip(), level=level),
        choice=Content.of(args.choice.strip(), level=level), context=opt(args.context), options=opt(args.options),
        reason=opt(args.reason), replaces=args.replaces, objective=o.id if o is not None else 0, author="self",
        owner=p.owner, about=p.about))
    more = f" (elle remplace la décision n° {args.replaces})" if args.replaces else ""
    return wrap_up(ctx, f"Décision n° {_attributed(ctx, p.id, commit, 'title', 'decisions', number)} consignée{more}.")


class ObjectiveArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="l'objectif, en une phrase")
    kind: Literal["once", "constant"] = Field(default="once", description="once : à faire une fois ; constant : à "
                                                                          "entretenir, il revient régulièrement")
    cadence_hours: int = Field(default=0, ge=0, le=24 * 30, description="un constant : toutes les combien d'heures "
                                                                        "(0 : la valeur par défaut)")


@PROJECTS.tool(OBJECTIVE_ADD, description="Ajouter un objectif à ce projet (une étape à part entière, qu'une "
               "exécution pourra viser).", args=ObjectiveArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=3)
async def project_objective_add(args: ObjectiveArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return GONE
    p, _ = got
    if living(p) >= OBJECTIVES_KEPT:
        return ToolResult(ok=False, content=f"Ce projet a déjà {OBJECTIVES_KEPT} objectifs ouverts ou bloqués.")
    number = p.objective_seq + 1
    commit = await ctx.emit(OBJECTIVE_ADDED.draft(
        project=p.id, objective=number, text=Content.of(args.text.strip(), level=written(p)), kind=args.kind,
        cadence_us=args.cadence_hours * HOUR, author="self", owner=p.owner, about=p.about))
    number = _attributed(ctx, p.id, commit, "text", "objectives", number)
    return wrap_up(ctx, f"Objectif n° {number} ajouté ({'constant' if args.kind == c.CONSTANT else 'ponctuel'}).")


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
    description: str = Field(default="", max_length=4000, description="le cadre : ce qu'il faut faire, comment, ce "
                                                                      "qui est hors sujet")
    objectives: list[str] = Field(default_factory=list, max_length=12,
                                  description="les objectifs à atteindre une fois (un par élément)")
    constants: list[str] = Field(default_factory=list, max_length=12,
                                 description="les objectifs constants, à entretenir (« améliorer la sécurité »)")
    mode: Literal["persona", "plain"] = Field(default="persona", description="persona : tu y travailles toi-même, "
                                                                             "avec ton humeur et tes avis ; plain : "
                                                                             "un travail impersonnel")
    schedule: str = Field(default="asap", description="asap : dès que possible ; demand : seulement quand on le "
                                                      "lance ; interval:2h ; cron:0 9 * * MON-FRI")


@PROJECTS.tool("create_project", description="Accepter un projet qu'on te confie (seulement quelqu'un qui s'occupe de "
               "toi) : il aura son atelier (un dossier, son dépôt git), ses objectifs et ses décisions, et tu y "
               "avanceras par exécutions.",
               args=CreateArgs, bundle="projects", episodes=[Kind.REPLY], max_calls_per_episode=1, owner_only=True)
async def create_project(args: CreateArgs, ctx: Any) -> Any:
    who = _person(ctx.frame)
    if who is None or not ctx.frame.get(identity_c.IS_OWNER(who[1])):
        return ToolResult(ok=False, content=f"Seul(e) {caretaker(ctx.frame)} peut te confier un projet. Si l'idée te "
                                            "plaît, tu peux en ouvrir un à toi (start_project).")
    handle, person = who
    try:
        rule = check_schedule(args.schedule)
    except ValueError as exc:
        return ToolResult(ok=False, content=f"Règle d'agenda refusée : {exc}")
    level = int(Sensitivity.PERSONAL)
    commit = await ctx.emit(opened(
        title=args.title, description=args.description, authority=c.USER, mode=args.mode, owner=person,
        address=handle, about=(person,), level=level, source="tool", schedule_rule=rule))
    pid = commit.seqs[-1] if commit.seqs else None
    if pid is None:
        return ToolResult(ok=False, content="Le projet n'a pas pu être créé.")
    goals = args.objectives or ([] if args.constants else [args.title])
    await ctx.emit(*objectives_of(pid, goals, args.constants, author="owner", owner=person, about=(person,),
                                  level=level))
    return f"Projet accepté (n° {pid}) : tu y travailleras dans son atelier, objectif par objectif."


class StartArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000, description="ce que tu veux faire, et pourquoi")
    objectives: list[str] = Field(default_factory=list, max_length=12, description="tes premiers objectifs")
    constants: list[str] = Field(default_factory=list, max_length=12, description="ce que tu veux entretenir")


def _own_live(s: ProjectsState) -> int:
    """Ses projets à elle qui l'occupent encore : vivants **et** avec un objectif ouvert (un projet dont tout est
    fait ne l'empêche pas d'en ouvrir un autre)."""
    return sum(1 for p in s.projects.values() if live(p) and p.authority == c.SELF
               and any(o.status == c.OPEN for o in p.objectives))


def _talking_to_owner(frame: Frame) -> bool:
    """En conversation, elle ne s'engage (ou ne se dégage) que devant quelqu'un qui s'occupe d'elle."""
    ep = frame.episode
    if ep is None or ep.kind != Kind.REPLY:
        return True
    who = _person(frame)
    return who is not None and bool(frame.get(identity_c.IS_OWNER(who[1])))


@PROJECTS.tool("start_project", description="Ouvrir un projet à toi : un vrai travail suivi (un dossier, son dépôt git, "
               "des objectifs), plus gros qu'une envie passagère. Tu y travailleras par exécutions ; ce qui sortirait "
               "de la machine attendra un accord.", args=StartArgs, bundle="projects",
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
        return ToolResult(ok=False, content="Tu n'ouvres pas de projet sur la demande de quelqu'un que tu ne connais "
                                            "pas assez.")
    if _own_live(s) >= pm.live_self_max:
        return ToolResult(ok=False, content=(
            f"Tu as déjà {_own_live(s)} projet(s) à toi en cours (au plus {pm.live_self_max}) : mènes-en un à bout, "
            "ou clos-en un (project_close) avant d'en ouvrir un autre."))
    gid = goal_of(ep.target) if ep is not None else None
    source = f"goal:{gid}" if gid is not None else "conversation"
    twin = next((p for p in s.projects.values() if live(p) and gid is not None and p.source == source), None)
    if twin is not None:
        return ToolResult(ok=False, content=f"Tu as déjà ouvert un projet depuis cette envie (n° {twin.id}) : "
                                            "travailles-y plutôt.")
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
        return ToolResult(ok=False, content="Le projet n'a pas pu être ouvert.")
    goals = args.objectives or ([] if args.constants else [args.title])
    await ctx.emit(*objectives_of(pid, goals, args.constants, author="self", owner=None, about=about, level=level))
    more = " L'exploration d'où il vient s'arrête là : c'est devenu un projet." if gid is not None else ""
    return f"Projet ouvert (n° {pid}) : il est à toi. Tu y avanceras par exécutions, dans son atelier.{more}"


class CloseArgs(BaseModel):
    project: int = Field(ge=1, description="le numéro de ton projet")
    ending: Literal["done", "dropped"] = Field(description="done : il a fait son temps, tu en as fini ; dropped : tu "
                                                           "y renonces")
    why: str = Field(min_length=1, max_length=600, description="pourquoi, en une ou deux phrases (dans son carnet)")


ENDING_REASON = {"done": "clos par elle : il a fait son temps", "dropped": "clos par elle : elle y renonce"}


@PROJECTS.tool("project_close", description="Clore un de tes projets à toi (pas un projet qu'on t'a confié) : il a "
               "fait son temps, ou tu y renonces. Son dossier et son histoire restent ; un opérateur peut le "
               "restaurer.", args=CloseArgs, bundle="projects", episodes=[Kind.REPLY, Kind.STEP, *RUNS],
               max_calls_per_episode=1, owner_only=True)
async def project_close(args: CloseArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    p = frame.state("projects").projects.get(args.project)
    if p is None or not live(p):
        return ToolResult(ok=False, content=f"Tu n'as pas de projet vivant n° {args.project}.")
    if p.authority != c.SELF:
        return ToolResult(ok=False, content="Ce projet t'a été confié : ce n'est pas à toi de le clore. Si tu n'y "
                                            "arrives pas, dis-le (report_run « blocked », et ce qu'il te faudrait).")
    if not _talking_to_owner(frame):
        return ToolResult(ok=False, content="Pas sur la demande de quelqu'un que tu ne connais pas assez.")
    level = written(p)
    # sa raison va dans son carnet (un contenu, que l'oubli atteint) ; l'archivage n'en garde qu'une étiquette
    await ctx.emit(NOTED.draft(project=p.id, text=Content.of(f"Clos : {args.why.strip()}", level=level),
                               owner=p.owner, about=p.about),
                   ARCHIVED.draft(project=p.id, reason=ENDING_REASON[args.ending], by="self", ending=args.ending,
                                  owner=p.owner, about=p.about))
    return "C'est fait : ce projet est clos." if args.ending == "done" else "C'est fait : tu le laisses de côté."
