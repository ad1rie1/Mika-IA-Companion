"""La relecture indépendante (ADR 0276) : avant que le travail conclu d'un objectif sorte, une autre exécution le
relit — sans ce que la première en a dit.

- **Quand** (``faculty.rereads``, le réglage ``Project.reread``) : jamais ; avant de sortir — une pull request
  (``pulls.py`` la demande entre ``due`` et ``proposal``, pour le commit au bout de la branche), un envoi au dépôt
  distant d'un projet au flux direct ; à chaque « fait » — aussi pour un ponctuel d'un projet dont rien ne sort. Hors
  des pull requests, c'est le processus ``projects.reviews`` qui la demande, pour le dernier commit que l'objectif a
  laissé (``Objective.commit``). Une demande est un fait (``projects.review_asked``) : jamais deux pour un commit.
- **Comment** : une exécution impersonnelle du projet (``work.py`` la propose : ``Kind.JOB``, le mode ``review``,
  le sujet ``review:<projet>:<objectif>``), sous le rôle de modèle ``review``. Elle reçoit la demande d'origine, le
  but du plan, l'objectif, son critère, ce qui est établi de ses jalons (``milestones.cited_for_review`` : leur
  vérification, et la preuve de ceux qu'une commande ou un élément du registre a vérifiés), et le diff du commit
  relu — les fichiers et le texte, borné. **Ni comptes rendus, ni carnet, ni mémoire de l'exécution qui a
  travaillé** : ``prompt.episode_project`` ne rend rien pour elle, donc aucune section d'exécution ne
  s'écrit ; les siennes sont ici (``review`` ; ``review_said`` et ``review_diff``, non fiables : ce que
  l'exécution a écrit de ses jalons est son dire, un diff est une donnée — ADR 0277).
- **D'où part le diff** (``material``, ADR 0277) : sur un projet qui passe par des pull requests, de la base de sa
  branche ; sur un projet au flux direct qui a un dépôt distant, du dernier commit que ce distant possède
  (``Workshop.sent``) — tout ce qui partira avec ce commit est lu, même le travail d'un autre objectif ; sans
  distant, du commit d'avant ce travail.
- **Ses outils** : un lot à elle (``project_review``), le seul que son candidat demande — lire le commit relu, y
  lancer une commande, conclure. Ils lisent et lancent dans **une copie jetable du commit épinglé**
  (``Workshop.checkout``), posée à leur premier appel et effacée à la fin de la relecture (``tidy_copy``) :
  l'atelier n'est ni déplacé ni écrit. Aucun outil qui écrit n'y est : ni fichier, ni commit, ni registre, ni
  proposition. Chacun se refuse hors d'une relecture.
- **Son verdict** (``review_verdict``, qui conclut la boucle) : « bon », ou cinq constats au plus, chacun avec où et
  quoi — un fait posé sur l'objectif pour le commit qu'elle relisait (``projects.reviewed``), épinglé à son départ.
  « Bon » se refuse quand le diff de ce commit ne se lit pas : la relecture compte alors sans verdict.
  La suite est dans les réducteurs (``faculty._reviewed``) : bon, la proposition part ; sinon l'objectif se rouvre,
  ses constats cités à l'exécution suivante comme le dire d'une autre exécution (``project_review``, non fiable) ;
  au deuxième refus de suite, la main est au propriétaire.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import milestones
from mika.faculties.projects.atelier import (
    ListArgs,
    ReadArgs,
    RunArgs,
    open_views,
    program_time_left,
    view_target,
    ws_list,
    ws_read,
)
from mika.faculties.projects.faculty import (
    PROJECTS,
    REFRAMED,
    REVIEW_ASKED,
    REVIEWED,
    Objective,
    Project,
    ProjectsState,
    by_pulls,
    concluded,
    handed_over,
    inherited_for,
    objective_at,
    objective_of,
    rereads,
    review_of,
    written_for,
)
from mika.faculties.projects.remote import propose_push
from mika.faculties.projects.tool_common import RUNS
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp, ToolResult, Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.kernel.text import clipped
from mika.ports.workshop import UNREADABLE, OutsideWorkshop, describe
from mika.vocab.episodes import REVIEW, Kind, Role, project_of
from mika.vocab.phrasebook import family, phrase

#: son lot d'outils : le seul que son candidat demande (``work.py``) — rien qui écrit n'y est
BUNDLE = "project_review"
#: une relecture est une exécution impersonnelle, quel que soit le mode du projet
EPISODES = [Kind.JOB]
#: ce qu'elle lit du diff, au plus (caractères) ; le reste se lit fichier par fichier, avec ses outils
PATCH_MAX = 60_000
#: ses constats : cinq au plus, chacun borné
FINDINGS_MAX, WHERE_MAX, WHAT_MAX = 5, 200, 600
#: ce qu'une exécution lit, au plus, des constats d'une relecture (caractères)
SAID_SHOWN = 3200
#: l'écart minimal entre deux passes du processus qui ont encore à demander
RETRY_US = MINUTE

PROJECTS.bundle(BUNDLE, phrase("projects.review.bundle"))


# ── Qui relit quoi ────────────────────────────────────────────────────────


def reviewing(s: ProjectsState, frame: Frame) -> tuple[Project, Objective] | None:
    """Le projet et l'objectif que relit l'épisode en cours — ``None`` : ce n'en est pas une, ou ils n'existent
    plus."""
    ep = frame.episode
    if ep is None or ep.kind != Kind.JOB or ep.attrs.get("mode") != REVIEW:
        return None
    got = review_of(ep.attrs.get("subject"))
    p = s.projects.get(got[0]) if got is not None and project_of(ep.target) == got[0] else None
    o = objective_at(p, got[1]) if p is not None and got is not None else None
    return (p, o) if p is not None and o is not None else None


def _here(ctx: Any) -> tuple[Project, Objective, str] | None:
    """Pour un outil : le projet, l'objectif et le commit que relit cette exécution — celui qui était demandé à son
    départ (``Run.reviewing``), pas ce que la branche est devenue depuis."""
    s: ProjectsState = ctx.frame.state("projects")
    got = reviewing(s, ctx.frame)
    if got is None or got[0].status != c.ACTIVE:
        return None
    run = s.running.get(ctx.episode_id)
    sha = run.reviewing if run is not None and run.purpose == "review" else got[1].review_due
    return (*got, sha) if sha else None


def to_ask(s: ProjectsState) -> list[tuple[Project, Objective]]:
    """Hors des pull requests (``pulls.py`` demande les siennes) : les objectifs dont le travail conclu attend une
    relecture qui n'est pas encore demandée — leur dernier commit n'a ni verdict ni demande."""
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status != c.ACTIVE or by_pulls(p):
            continue
        out += [(p, o) for o in p.objectives if rereads(p, o) and concluded(o) and o.commit
                and o.commit not in (o.reviewed, o.review_due) and not handed_over(o)]
    return out


def asked(p: Project, o: Objective, sha: str) -> Draft[Any]:
    """La demande d'une relecture pour ce commit (un fait : la relecture elle-même part de l'arbitrage)."""
    return REVIEW_ASKED.draft(project=p.id, objective=o.id, sha=sha, owner=p.owner, about=p.about)


@PROJECTS.process("projects.reviews", wake_on=[c.RUN_REPORTED, c.OBJECTIVE_CLOSED, REVIEWED, REFRAMED],
                  catch_up=CatchUp.ONCE, max_quantum_s=600, priority=44)
class Reviews:
    """Demander la relecture d'un travail conclu, hors des pull requests (ADR 0276) : un projet au flux direct qui a
    un dépôt distant, ou un projet réglé sur « à chaque fait ». Rien ne part d'ici, et rien n'y lit l'atelier : le
    commit est celui que le compte rendu a dit."""

    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        if not to_ask(s):
            return None
        return frame.now if last_run is None else max(frame.now, last_run + RETRY_US)

    async def run(self, ctx: Any) -> None:
        facts = [asked(p, o, o.commit) for p, o in to_ask(ctx.state)]
        if facts:
            await ctx.emit(*facts)


# ── Ce qu'elle lit ────────────────────────────────────────────────────────


def aim_of(plan: str) -> str:
    """Le but d'un plan : sa première ligne (``framing_tools.plan_text`` l'écrit d'abord) — pas son approche, que
    l'exécution qui a travaillé a pu suivre ou non : la relecture juge ce qui est demandé."""
    return plan.strip().split("\n", 1)[0].strip()


def _refs(p: Project, o: Objective) -> list[str]:
    """Les seuls textes qu'une relecture lit : le titre, la demande d'origine, le plan (pour son but), l'objectif,
    son critère, ses jalons. Aucun compte rendu, aucune note, aucun résultat."""
    return [r for r in (p.title_ref, p.request_ref, p.plan_ref, o.text_ref, o.done_when_ref, *milestones.refs(o))
            if r]


async def material(p: Project, o: Objective, sha: str, port: Any, limit: int = PATCH_MAX) -> tuple[str | None, str]:
    """Le diff du commit relu (``None`` : il ne se lit pas) et pourquoi il ne se lit pas. D'où il part (ADR 0277) :
    sur un projet qui passe par des pull requests, de la base de sa branche ; sur un projet au flux direct qui a
    un dépôt distant, du dernier commit que ce distant possède, tel que l'atelier le sait — tout ce qui partira
    avec ce commit est lu, pas seulement le travail de cet objectif (s'il n'en sait rien : depuis le début) ; sans
    distant, du commit d'avant ce travail. Rien ici ne déplace l'atelier ni n'y écrit."""
    read = getattr(port, "patch", None)
    if port is None or not port.exists(p.id) or not sha or not callable(read):
        return None, ""
    try:
        if by_pulls(p) and o.branch:
            span = await port.span(p.id, o.branch)
            if span is None:
                return None, phrase("projects.review.no_branch", branch=o.branch)
            since = span.base
        elif p.remote and callable(getattr(port, "sent", None)):
            since = await port.sent(p.id, p.remote, p.branch)
        else:
            since = o.since
        return await read(p.id, since, sha, limit), ""
    except (OSError, ValueError) as exc:
        return None, str(exc)[:200]


@PROJECTS.enricher("projects_review", episodes=EPISODES, deadline_ms=8000)
async def _material(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ce que la relecture a sous les yeux : ses textes, et le diff du commit relu (``material``). Un atelier
    illisible ne la rend pas aveugle : elle le lit dit — et « bon » lui sera refusé."""
    got = reviewing(s, frame)
    store, port = ports.get("store"), ports.get("workshop")
    if got is None or store is None:
        return None
    p, o = got
    run = s.running.get(frame.episode.id) if frame.episode is not None else None
    sha = (run.reviewing if run is not None and run.purpose == "review" else "") or o.review_due
    diff, why = await material(p, o, sha, port)
    return {"texts": store.content(_refs(p, o)), "sha": sha, "branch": o.branch if by_pulls(p) else "",
            "diff": diff, "why": why}


def _who(frame: Frame, key: str | None) -> str:
    name = identity_c.person_name(frame, key) if key else ""
    return f"« {name} »" if name else phrase("expression.person.someone")


@PROJECTS.section("review", zone=Zone.VOLATILE, episodes=EPISODES, trim_rank=95, floor_chars=1200,
                  title=phrase("projects.review.title"), reads=[identity_c.IDENTITY])
def _review_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'une relecture juge : la demande d'origine, le but du plan, l'objectif, son critère, ses jalons et
    leurs preuves, puis sa méthode. Rien de ce que l'exécution qui a travaillé en a dit."""
    got = reviewing(s, frame)
    if got is None:
        return None
    p, o = got
    data = enrich.get("projects_review") or {}
    texts: Mapping[str, str] = data.get("texts") or {}
    lines = [phrase("projects.review.head", id=p.id, title=texts.get(p.title_ref, phrase("projects.run.no_title")))]
    if p.request_ref and texts.get(p.request_ref):
        lines.append(phrase("projects.review.request", who=_who(frame, p.asked_by), text=texts[p.request_ref]))
    if p.plan_ref and texts.get(p.plan_ref):
        lines.append(phrase("projects.review.aim", aim=aim_of(texts[p.plan_ref])))
    lines.append(phrase("projects.review.objective", id=o.id,
                        text=texts.get(o.text_ref, phrase("projects.tools.report.forgotten"))))
    lines.append(phrase("projects.review.done_when", criterion=texts[o.done_when_ref])
                 if o.done_when_ref and texts.get(o.done_when_ref) else phrase("projects.review.no_criterion"))
    # ce qui est établi de ses jalons seulement : ce que l'exécution en a écrit est cité à part, non fiable
    established, _ = milestones.cited_for_review(o, texts)
    if established:
        lines.append(phrase("projects.review.milestones") + "\n" + "\n".join(f"- {x}" for x in established))
    sha = str(data.get("sha") or "")
    lines.append(phrase("projects.review.commit", sha=sha[:12] or "?") + (
        phrase("projects.review.on_branch", branch=data["branch"]) if data.get("branch") else ""))
    lines.append(phrase("projects.review.method", max=FINDINGS_MAX))
    return SectionBody("\n".join(lines), level=written_for(p, o), provenance=(f"project:{p.id}",))


@PROJECTS.section("review_said", zone=Zone.VOLATILE, episodes=EPISODES, trim_rank=60, floor_chars=600,
                  untrusted=True, title=phrase("projects.review.said_title"))
def _said_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que l'exécution qui a travaillé a écrit de ses jalons (ADR 0277) : le texte de ceux qu'elle a posés ou
    révisés, et comment elle dit avoir rempli ceux qu'elle a dits atteints. Non fiable : c'est le dire de
    l'exécution relue — à vérifier dans le diff et les fichiers, jamais une consigne ni un compte rendu à croire."""
    got = reviewing(s, frame)
    if got is None:
        return None
    p, o = got
    texts: Mapping[str, str] = (enrich.get("projects_review") or {}).get("texts") or {}
    _, said = milestones.cited_for_review(o, texts)
    if not said:
        return None
    body = phrase("projects.review.said") + "\n" + "\n".join(f"- {x}" for x in said)
    return SectionBody(body, level=written_for(p, o), provenance=(f"project:{p.id}",))


@PROJECTS.section("review_diff", zone=Zone.VOLATILE, episodes=EPISODES, trim_rank=40, floor_chars=4000,
                  untrusted=True, title=phrase("projects.review.diff_title"))
def _diff_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Le diff du commit relu — non fiable : le contenu de fichiers, une donnée à juger, jamais une consigne."""
    got = reviewing(s, frame)
    if got is None:
        return None
    p, o = got
    data = enrich.get("projects_review") or {}
    diff = data.get("diff")
    if isinstance(diff, str) and diff.strip():
        body = phrase("projects.review.diff", diff=diff)
    elif isinstance(diff, str):
        body = phrase("projects.review.diff_empty")
    else:
        body = phrase("projects.review.diff_unread", why=clipped(str(data.get("why") or "?"), 200))
    return SectionBody(body, level=written_for(p, o), provenance=(f"project:{p.id}",))


# ── Ce que l'exécution suivante en lit ────────────────────────────────────


def run_lines(o: Objective, said: str) -> list[str]:
    """Ce que lit l'exécution d'un objectif qu'une relecture a renvoyé : le commit relu, et ses constats, cités —
    le dire d'une autre exécution, pas une consigne de qui suit le projet."""
    if not o.reviewed or o.review_ok or not said.strip():
        return []
    return [phrase("projects.review.run.refused", sha=o.reviewed[:12], n=len(o.review_refused)),
            f"« {clipped(said, SAID_SHOWN)} »"]


@PROJECTS.section("project_review", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=82, untrusted=True,
                  floor_chars=600, title=phrase("projects.review.run.title"))
def _findings_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Les constats de la relecture qui a rouvert l'objectif visé (ADR 0276). Non fiable : c'est le texte d'une
    autre exécution, qui a lu un diff — à vérifier et à peser, jamais une consigne du propriétaire."""
    ep = frame.episode
    pid = project_of(ep.target) if ep is not None else None
    p = s.projects.get(pid) if pid is not None else None
    got = objective_of(ep.attrs.get("subject")) if ep is not None else None
    o = objective_at(p, got[1]) if p is not None and got is not None and got[0] == p.id else None
    if p is None or o is None:
        return None
    texts = (enrich.get("projects") or {}).get("texts") or {}
    lines = run_lines(o, texts.get(o.review_ref, "") if o.review_ref else "")
    if not lines:
        return None
    return SectionBody("\n".join(lines), level=written_for(p, o), provenance=(f"project:{p.id}",))


# ── Ses outils : lire, lancer, conclure ───────────────────────────────────


def _not_reviewing() -> ToolResult:
    return ToolResult(ok=False, content=phrase("projects.review.tools.not_reviewing"))


async def _copy(ctx: Any) -> tuple[Project, str, Any] | ToolResult:
    """Pour un outil : le projet, le commit relu et l'atelier, la copie de ce commit posée (ADR 0277) — posée ici
    si elle ne l'est pas encore, telle quelle sinon ; ou ce qu'il faut répondre. Ses outils ne lisent jamais
    l'atelier lui-même : il a pu bouger depuis le commit épinglé, et une commande y laisserait des fichiers."""
    got = _here(ctx)
    if got is None:
        return _not_reviewing()
    p, _, sha = got
    port = ctx.ports.get("workshop")
    pose = getattr(port, "checkout", None)
    why = await pose(p.id, sha) if callable(pose) else UNREADABLE
    if why:
        reasons = family("projects.review.copy_none")
        return ToolResult(ok=False, content=phrase("projects.review.tools.no_copy",
                                                   why=reasons.get(why) or reasons[UNREADABLE]))
    return p, sha, port


@PROJECTS.tool("review_list", description=phrase("projects.review.tools.list"),
               label=phrase("projects.review.tools.list_label"), args=ListArgs, bundle=BUNDLE, episodes=EPISODES)
async def review_list(args: ListArgs, ctx: Any) -> Any:
    """Lister les fichiers du commit relu — une lecture, dans sa copie ; la vue d'un projet lu se lit comme en
    exécution (elle est déjà une copie en lecture seule)."""
    got = await _copy(ctx)
    if isinstance(got, ToolResult):
        return got
    p, sha, port = got
    if view_target(p, args.path) is not None:
        return await ws_list(args, ctx)
    try:
        files = await port.copy_tree(p.id, sha, args.path or ".")
    except (OutsideWorkshop, FileNotFoundError) as exc:
        return ToolResult(ok=False, content=phrase("projects.workshop.refused", error=exc))
    return "\n".join(files) if files else phrase("projects.workshop.empty")


@PROJECTS.tool("review_read", description=phrase("projects.review.tools.read"),
               label=phrase("projects.review.tools.read_label"), args=ReadArgs, bundle=BUNDLE, episodes=EPISODES)
async def review_read(args: ReadArgs, ctx: Any) -> Any:
    """Lire un fichier du commit relu — une lecture, dans sa copie."""
    got = await _copy(ctx)
    if isinstance(got, ToolResult):
        return got
    p, sha, port = got
    if view_target(p, args.path) is not None:
        return await ws_read(args, ctx)
    try:
        return await port.copy_read(p.id, sha, args.path)
    except (OutsideWorkshop, FileNotFoundError) as exc:
        return ToolResult(ok=False, content=phrase("projects.workshop.refused", error=exc))


@PROJECTS.tool("review_run", description=phrase("projects.review.tools.run"),
               label=phrase("projects.review.tools.run_label"), args=RunArgs, bundle=BUNDLE, episodes=EPISODES,
               max_calls_per_episode=8)
async def review_run(args: RunArgs, ctx: Any) -> Any:
    """Lancer une commande dans la copie du commit relu (ses tests, un programme), sans réseau, dans le temps de
    programmes qui reste : pour vérifier, pas pour changer. Ce qu'elle y laisse (des caches, un rapport de
    couverture, ``dist/``) reste dans la copie, effacée à la fin : rien n'entre dans l'atelier, ni dans un commit
    (ADR 0277)."""
    got = await _copy(ctx)
    if isinstance(got, ToolResult):
        return got
    p, sha, port = got
    left = program_time_left(ctx)
    if left < 2:
        return ToolResult(ok=False, content=phrase("projects.workshop.no_time"))
    result = await port.copy_run(p.id, sha, args.argv, timeout_s=min(float(args.timeout_s), left),
                                 views=await open_views(ctx, p, port))
    return ToolResult(ok=result.ok, content=describe(result))


async def tidy_copy(ev: Any, ports: Mapping[str, Any]) -> None:
    """Le ménage de la copie relue, après la fin d'une exécution impersonnelle d'un projet (ADR 0277) : quand
    aucune relecture de ce projet n'est en cours, sa copie de commit n'a plus lieu d'être — qu'elle ait conclu,
    échoué, ou fini sans verdict. Relu sur l'état courant, donc rejouable."""
    port, frame_of = ports.get("workshop"), ports.get("frame")
    pid = project_of(ev.data.target) if ev is not None else None
    drop = getattr(port, "discard", None)
    if pid is None or frame_of is None or not callable(drop):
        return
    s: ProjectsState = frame_of().state("projects")
    if not any(run.project == pid and run.purpose == "review" for run in s.running.values()):
        await drop(pid)


PROJECTS.effect(rt.EPISODE_ENDED, when=lambda d: d.kind == Kind.JOB and project_of(d.target) is not None)(tidy_copy)


class Finding(BaseModel):
    where: str = Field(min_length=1, max_length=WHERE_MAX, description=phrase("projects.review.tools.where"))
    what: str = Field(min_length=1, max_length=WHAT_MAX, description=phrase("projects.review.tools.what"))


class VerdictArgs(BaseModel):
    verdict: Literal["good", "findings"] = Field(description=phrase("projects.review.tools.verdict_arg"))
    findings: list[Finding] = Field(default_factory=list, max_length=FINDINGS_MAX,
                                    description=phrase("projects.review.tools.findings"))


def findings_text(found: list[Finding]) -> str:
    """Ses constats tels qu'ils se gardent et se citent : un par ligne, où puis quoi."""
    return "\n".join(f"- {' '.join(f.where.split())} : {' '.join(f.what.split())}" for f in found)


def _served(ctx: Any) -> str:
    """Le fournisseur de modèle qui sert la relecture (replis de rôle compris) : « qui a relu »."""
    serving = getattr(ctx.ports.get("llm"), "serving", None)
    return str(serving(str(Role.REVIEW)) or "")[:80] if callable(serving) else ""


@PROJECTS.tool("review_verdict", acts=True, description=phrase("projects.review.tools.verdict"),
               label=phrase("projects.review.tools.verdict_label"), args=VerdictArgs, bundle=BUNDLE,
               episodes=EPISODES, max_calls_per_episode=3)
async def review_verdict(args: VerdictArgs, ctx: Any) -> Any:
    """Le verdict d'une relecture (ADR 0276) : « bon », ou ses constats. Il se pose sur l'objectif pour le commit
    relu et conclut la boucle (``ToolResult.ends``). C'est le seul fait qu'une relecture écrit. Sur un projet au
    flux direct qui pousse de lui-même, un « bon » propose l'envoi de ce commit-là — s'il est encore celui de
    l'atelier."""
    got = _here(ctx)
    if got is None:
        return _not_reviewing()
    p, o, sha = got
    good = args.verdict == "good"
    if good and args.findings:
        return ToolResult(ok=False, content=phrase("projects.review.tools.good_with_findings"))
    if not good and not args.findings:
        return ToolResult(ok=False, content=phrase("projects.review.tools.no_findings", max=FINDINGS_MAX))
    if good:
        # sans diff lu, pas de « bon » (ADR 0277) : rien ne s'écrit, et une relecture qui s'arrête là compte sans
        # verdict — deux de suite rendent la main au propriétaire
        diff, why = await material(p, o, sha, ctx.ports.get("workshop"), 200)
        if diff is None:
            return ToolResult(ok=False, content=phrase("projects.review.tools.good_unread",
                                                       why=clipped(why or "?", 200)))
    said = "" if good else findings_text(args.findings)
    await ctx.emit(REVIEWED.draft(
        project=p.id, objective=o.id, sha=sha, good=good,
        findings=Content.of(said, level=written_for(p, o)) if said else None, by=_served(ctx), owner=p.owner,
        about=p.about, read_about=inherited_for(p, o)))
    if not good:
        return ToolResult(content=phrase("projects.review.tools.refused", sha=sha[:12]), ends=True)
    sent = ""
    if not by_pulls(p) and p.remote and p.auto_push:
        sent = await propose_push(ctx, p, phrase("projects.review.push_why", sha=sha[:12]), reviewed=sha)
    return ToolResult(content=phrase("projects.review.tools.good", sha=sha[:12]) + (
        phrase("projects.review.tools.pushed") if sent in ("proposed", "sent") else ""), ends=True)


__all__ = ["BUNDLE", "EPISODES", "asked", "material", "reviewing", "tidy_copy", "to_ask"]
