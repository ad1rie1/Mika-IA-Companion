"""L'atelier d'un projet : ses outils (lot ``workshop``) et ce qui en sort.

Dans l'atelier, elle agit librement : lire, écrire, éditer, lancer un
programme isolé, relire ce qu'elle a changé. Ce qui **sort de la machine**
(une commande qui a besoin du réseau, un envoi au dépôt distant) ne part jamais
d'un outil : elle le propose (``effect.proposed``), et selon le projet il
attend l'accord d'un opérateur. Pousser et récupérer sont aussi des
**capacités** que l'opérateur déclenche depuis la console (exécutées tout de
suite : c'est lui qui les demande).

**Ce qu'on approuve est ce qui partira** : une commande réseau se montre
entière et exacte, un argument par ligne, avec l'état de l'atelier (son commit,
ce qui n'est pas enregistré) ; l'accord épingle cet aperçu, et si l'atelier a
changé entre-temps, rien ne part. Ses raisons sont montrées comme **ses mots**,
pas comme une description de la commande. Un envoi au dépôt distant se montre
de même : le dépôt, la branche, le commit épinglé et les enregistrements qui
partiront (relus dans l'atelier, face à ce que l'hôte dit du distant) ; une
récupération, ce qui arrivera.

**Un projet qui passe par des pull requests** (ADR 0274) ne pousse jamais sa
branche de base : ``project_push`` et l'envoi demandé depuis la console poussent
la branche de travail où l'atelier se trouve, la capacité ``projects.push``
refuse la base, et rien ici ne fusionne. Récupérer n'avance que la base.
Quand la base a avancé et que la branche de travail ne s'y accorde plus (l'hôte
dit sa pull request impossible à fusionner), ``ws_take_base`` ramène la base
**dans la branche de travail** (ADR 0280) : les conflits restent dans les
fichiers, nommés, elle les résout et son compte rendu enregistre. La base
elle-même n'est jamais écrite.

**L'atelier n'a qu'un occupant à la fois** : une commande réseau ne s'approuve
pas pendant qu'une exécution y travaille ; sans accord requis, elle attend la
fin de l'exécution qui l'a demandée ; et aucune exécution ne part tant qu'une
commande, un envoi ou une récupération sont en route.

**Ce qu'un projet lit des fichiers d'un autre** (ADR 0260) est une vue de son
atelier : son dernier commit, sous ``liens/<n>/``. ``ws_list`` et ``ws_read`` la
lisent, ``ws_run`` la monte en lecture seule pour ses programmes, ``ws_write``
et ``ws_edit`` la refusent : un projet n'écrit jamais dans un autre. Le droit se
relit **à chaque appel** dans les lignes d'accès du projet lu (``links.views``) :
retiré, la lecture s'arrête à l'appel suivant et la vue est supprimée. Un lien
retiré ou suspendu, un projet archivé, un « pour qui » changé font le même
ménage après le commit (``tidy_views``), sans attendre que le lecteur retravaille ;
et ce ménage se rejoue au démarrage puis à intervalle régulier (``projects.views``,
ADR 0262) : un droit repris hors des événements des projets — une personne qui
n'est plus proche, un tableau de canal changé — ne laisse pas de vue non plus.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator

from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.faculties.projects import links
from mika.faculties.projects.capability_common import effect_project, hosted_remote, pin_of, project_refusal
from mika.faculties.projects.faculty import (
    ACCESS_SET,
    ARCHIVED,
    BASE_REQUEST,
    LINKS_SET,
    NETWORK_QUEUED,
    NETWORKED_CAPABILITY,
    PROJECTS,
    PULL_CAPABILITY,
    PUSH_CAPABILITY,
    REFRAMED,
    Project,
    ProjectsState,
    branch_of,
    busy,
    by_pulls,
    params,
    subjects_of,
    written,
)
from mika.faculties.projects.inspect_pulls import BASE_KEPT, BASE_PULL
from mika.faculties.projects.inspect_reviews import review_line
from mika.faculties.projects.remote import pending_push, pinned, propose_push, push_branch, push_summary
from mika.faculties.projects.tool_common import gone_reply, running_project
from mika.faculties.projects.tools import CONFLICTS_SHOWN, TAKE_BASE
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp, ToolResult
from mika.kernel.inspect import plural
from mika.kernel.operate import Preview
from mika.ports.workshop import (
    UNREADABLE,
    VIEWS_DIR,
    Commit,
    OutsideWorkshop,
    View,
    WorkshopFull,
    argv_lines,
    describe,
    view_entry,
    view_place,
    viewed,
)
from mika.vocab.episodes import PROJECT_KINDS, project_of, project_target
from mika.vocab.phrasebook import family, phrase

BUNDLE = "workshop"
RUNS = list(PROJECT_KINDS)
#: un argument de commande réseau, au plus (la commande se montre entière à qui l'approuve)
ARG_MAX = 2000
#: la clé où l'accord épingle l'aperçu lu (``runtime/decisions.py``)
SEEN_KEY = "_apercu"


def _atelier(ctx: Any) -> tuple[Any, Any] | str:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    port = ctx.ports.get("workshop")
    if port is None:
        return phrase("projects.workshop.unavailable")
    return got[0], port


PROJECTS.bundle(BUNDLE, phrase("projects.workshop.bundle"))


# ── La vue de l'atelier d'un projet lu (ADR 0260) ─────────────────────────


def view_target(p: Project, path: str) -> tuple[int, str] | None:
    """Ce chemin vise-t-il la vue d'un projet que ``p`` lit (``liens/<n>/…``) ? Son numéro et le reste du chemin.
    Un lien suspendu garde sa place : ``liens/<n>/`` reste la vue, fermée, pas un dossier de l'atelier."""
    got = viewed(path)
    return got if got is not None and got[0] in p.reads else None


async def open_views(ctx: Any, p: Project, port: Any) -> tuple[int, ...]:
    """Les projets dont la vue est ouverte à ``p`` **maintenant** : le droit se relit à chaque appel, dans les lignes
    d'accès de chaque projet lu. Une vue qu'il n'a plus le droit de lire est supprimée ici, avant de répondre."""
    if not p.reads:
        return ()
    granted = links.views(ctx.frame.state("projects"), p, links.world_of(ctx.frame))
    await port.drop_views(p.id, keep=granted)
    return granted


def no_view_words(why: str) -> str:
    """Pourquoi un projet lu n'a pas de vue, en mots (``View.why``)."""
    reasons = family("projects.links.view.none")
    return reasons.get(why) or reasons[UNREADABLE]


async def _view(ctx: Any, p: Project, port: Any, target: int) -> View | ToolResult:
    """La vue du projet ``target``, si elle est ouverte à ``p`` et posée ; sinon ce qu'il faut répondre."""
    if target not in await open_views(ctx, p, port):
        return ToolResult(ok=False, content=phrase("projects.workshop.view_closed", id=target))
    view = await port.view(p.id, target)
    if not view.sha:
        return ToolResult(ok=False, content=phrase("projects.workshop.view_none", id=target,
                                                   why=no_view_words(view.why)))
    return view


def _read_only(target: int) -> ToolResult:
    """Ce que ``ws_write`` et ``ws_edit`` répondent pour un chemin d'une vue, ouverte ou non : elle ne s'écrit pas."""
    return ToolResult(ok=False, content=phrase("projects.workshop.view_read_only", path=view_place(target) + "/",
                                               id=target))


async def _view_entries(ctx: Any, p: Project, port: Any) -> list[str]:
    """Une ligne par vue ouverte et posée : ce que ``ws_list`` ajoute à la racine de l'atelier, et sous ``liens``."""
    out = []
    for target in await open_views(ctx, p, port):
        if (await port.view(p.id, target)).sha:
            out.append(phrase("projects.workshop.view_entry", path=view_place(target) + "/", id=target))
    return out


async def tidy_views(ev: Any, ports: Mapping[str, Any]) -> None:
    """Le ménage des vues, après le commit : chaque projet ne garde que celles que ses liens et les lignes d'accès
    des projets lus lui donnent maintenant — aucune s'il est archivé. Relu sur l'état courant, donc rejouable : un
    lien retiré ou suspendu, un droit repris, un projet archivé, un « pour qui » changé ne laissent pas de vue
    derrière eux, même si le lecteur ne retravaille jamais."""
    port, frame_of = ports.get("workshop"), ports.get("frame")
    if port is None or frame_of is None:
        return
    frame = frame_of()
    s: ProjectsState = frame.state("projects")
    world = links.world_of(frame)
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        await port.drop_views(p.id, keep=links.views(s, p, world))


PROJECTS.effect(LINKS_SET)(tidy_views)
PROJECTS.effect(ACCESS_SET)(tidy_views)
PROJECTS.effect(ARCHIVED)(tidy_views)
PROJECTS.effect(REFRAMED, when=lambda d: d.set_owner)(tidy_views)

#: le ménage des vues se rejoue à cet intervalle (ADR 0262)
VIEWS_SWEEP_US = 15 * MINUTE


@PROJECTS.process("projects.views", wake_on=[LINKS_SET], catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=70,
                  reads=[identity_c.IS_OWNER])
class Views:
    """Le ménage des vues, rejoué au démarrage puis à intervalle régulier (ADR 0262). Les effets ci-dessus suivent
    ce qui change dans les projets ; un droit se reprend aussi sans qu'aucun de leurs événements ne le dise — une
    personne qui n'est plus proche (la source « tes proches » d'une ligne), un tableau de canal réglé autrement
    (la porte « elle seule ») —, et la vue restait sur le disque tant que le lecteur ne retravaillait pas. Il ne
    tourne que tant qu'un projet en lit un autre, n'écrit rien au journal, et refait ce que ferait un effet rejoué :
    chaque projet ne garde que les vues que ses liens et les lignes des projets lus lui donnent maintenant."""

    def next_due(self, s: ProjectsState, frame: Any, last_run: int | None) -> int | None:
        if not any(p.reads for p in s.projects.values()):
            return None
        return frame.now if last_run is None else last_run + VIEWS_SWEEP_US

    async def run(self, ctx: Any) -> None:
        await tidy_views(None, {**ctx.ports, "frame": lambda: ctx.frame})


class ListArgs(BaseModel):
    path: str = Field(default="", max_length=300, description=phrase("projects.workshop.list_path"))


class ReadArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300, description=phrase("projects.workshop.read_path"))


class WriteArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=200_000)


class EditArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    old: str = Field(min_length=1, max_length=20_000, description=phrase("projects.workshop.edit_old"))
    new: str = Field(max_length=20_000)


class RunArgs(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40, description=phrase("projects.workshop.run_argv"))
    #: borné en plus par ce qui reste à l'exécution : un programme lent ne la fait jamais expirer
    timeout_s: int = Field(default=60, ge=1, le=300)


class NetworkArgs(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40, description=phrase("projects.workshop.network_argv"))
    why: str = Field(min_length=1, max_length=400, description=phrase("projects.workshop.network_why"))

    @field_validator("argv")
    @classmethod
    def _bounded(cls, argv: list[str]) -> list[str]:
        if any(len(a) > ARG_MAX for a in argv):
            raise ValueError(f"un argument fait au plus {ARG_MAX} caractères")
        return argv


class BaseArgs(BaseModel):
    pass


class PushArgs(BaseModel):
    why: str = Field(min_length=1, max_length=400, description=phrase("projects.workshop.push_why"))


@PROJECTS.tool("ws_list", description=phrase("projects.workshop.list"), label=phrase("projects.workshop.list_label"), args=ListArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_list(args: ListArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    seen = view_target(p, args.path)
    try:
        if seen is not None:  # la vue d'un projet lu : son dernier commit, si le droit tient encore
            view = await _view(ctx, p, port, seen[0])
            if isinstance(view, ToolResult):
                return view
            # les noms des fichiers d'un autre projet : des données, sans caractère de contrôle, coupées (ADR 0262)
            files = [view_entry(f) for f in await port.view_tree(p.id, *seen)]
        else:
            files = await port.tree(p.id, args.path or ".")
            if p.reads and args.path.strip().strip("/") in ("", ".", VIEWS_DIR):
                files = [*files, *await _view_entries(ctx, p, port)]
    except (OutsideWorkshop, FileNotFoundError) as exc:
        return ToolResult(ok=False, content=phrase("projects.workshop.refused", error=exc))
    return "\n".join(files) if files else phrase("projects.workshop.empty")


@PROJECTS.tool("ws_read", description=phrase("projects.workshop.read"), label=phrase("projects.workshop.read_label"), args=ReadArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_read(args: ReadArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    seen = view_target(p, args.path)
    try:
        if seen is None:
            return await port.read(p.id, args.path)
        view = await _view(ctx, p, port, seen[0])
        return view if isinstance(view, ToolResult) else await port.view_read(p.id, *seen)
    except (OutsideWorkshop, FileNotFoundError) as exc:
        return ToolResult(ok=False, content=phrase("projects.workshop.refused", error=exc))


@PROJECTS.tool("ws_write", acts=True, description=phrase("projects.workshop.write"),
               label=phrase("projects.workshop.write_label"), args=WriteArgs, bundle=BUNDLE,
               episodes=RUNS)
async def ws_write(args: WriteArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    if (seen := view_target(p, args.path)) is not None:  # un projet n'écrit jamais dans un autre
        return _read_only(seen[0])
    try:
        rel = await port.write(p.id, args.path, args.content)
    except (OutsideWorkshop, WorkshopFull) as exc:
        return ToolResult(ok=False, content=phrase("projects.workshop.refused", error=exc))
    return phrase("projects.workshop.written", path=rel, size=len(args.content))


@PROJECTS.tool("ws_edit", acts=True, description=phrase("projects.workshop.edit"), label=phrase("projects.workshop.edit_label"), args=EditArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_edit(args: EditArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    if (seen := view_target(p, args.path)) is not None:
        return _read_only(seen[0])
    try:
        rel = await port.edit(p.id, args.path, args.old, args.new)
    except (OutsideWorkshop, FileNotFoundError, ValueError) as exc:  # WorkshopFull est une ValueError
        return ToolResult(ok=False, content=phrase("projects.workshop.refused", error=exc))
    return phrase("projects.workshop.edited", path=rel)


def program_time_left(ctx: Any) -> float:
    """Ce qui reste aux programmes de cette exécution (secondes) : ils doivent avoir fini un peu après son début,
    bien avant son délai — un programme lent s'arrête en « délai dépassé », que le modèle lit et qui lui laisse
    le temps de conclure."""
    pm = params(ctx.frame.env.params_of("projects", ctx.frame.root))
    run = ctx.frame.state("projects").running.get(ctx.episode_id)
    if run is None or not run.started:
        return pm.run_programs_us / 1_000_000
    return max(0.0, (run.started + pm.run_programs_us - ctx.frame.now) / 1_000_000)


@PROJECTS.tool("ws_run", acts=True, description=phrase("projects.workshop.run"), label=phrase("projects.workshop.run_label"), args=RunArgs, bundle=BUNDLE, episodes=RUNS, max_calls_per_episode=8)
async def ws_run(args: RunArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    left = program_time_left(ctx)
    if left < 2:
        return ToolResult(ok=False, content=phrase("projects.workshop.no_time"))
    # ses programmes lisent les vues qui lui sont ouvertes maintenant, là où ses outils les disent
    result = await port.run(p.id, args.argv, timeout_s=min(float(args.timeout_s), left),
                            views=await open_views(ctx, p, port))
    # une commande refusée ou en échec n'est pas du travail fait (elle reste une information)
    return ToolResult(ok=result.ok, content=describe(result))


@PROJECTS.tool(TAKE_BASE, acts=True, description=phrase("projects.workshop.take_base"),
               label=phrase("projects.workshop.take_base_label"), args=BaseArgs, bundle=BUNDLE, episodes=RUNS,
               max_calls_per_episode=3)
async def ws_take_base(args: BaseArgs, ctx: Any) -> Any:
    """Ramener la base dans la branche de travail de l'objectif visé (ADR 0280) : la sortie d'une pull request que
    l'hôte dit impossible à fusionner. C'est l'adaptateur de l'atelier qui le fait, hors de la cage — là où elle
    lance ses commandes, le dépôt ne s'écrit pas. Les conflits restent dans les fichiers, nommés ; elle les résout,
    et son compte rendu enregistre. Rien n'est écrit sur la base, rien ne part chez l'hôte."""
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    if not by_pulls(p):
        return ToolResult(ok=False, content=phrase("projects.workshop.take_base_direct"))
    found = running_project(ctx)
    joined = await port.take_base(p.id, branch_of(found[1] if found is not None else None),
                                  stow=phrase("projects.commit.stowed"))
    if not joined.branch:
        return ToolResult(ok=False, content=phrase("projects.workshop.take_base_refused", why=joined.why or "?"))
    stowed = phrase("projects.workshop.take_base_stowed", sha=joined.stowed[:12]) if joined.stowed else ""
    if joined.already:
        o = found[1] if found is not None else None
        if o is not None and o.pull_conflicts:
            # l'hôte la dit en conflit, mais l'atelier n'a pas encore ce que la base a reçu là-bas : la récupération
            # est demandée dès que l'hôte l'a dit, et passe quand l'atelier est libre — elle reprendra ensuite
            return ToolResult(ok=False, content=phrase("projects.workshop.take_base_stale", branch=joined.branch,
                                                       base=joined.base[:12]))
        return phrase("projects.workshop.take_base_already", branch=joined.branch, base=joined.base[:12])
    if joined.conflicts:
        files = ", ".join(joined.conflicts[:CONFLICTS_SHOWN]) + (" …" if len(joined.conflicts) > CONFLICTS_SHOWN else "")
        return phrase("projects.workshop.take_base_conflicts", branch=joined.branch, base=joined.base[:12],
                      files=files) + stowed
    return phrase("projects.workshop.take_base_clean", branch=joined.branch, base=joined.base[:12]) + stowed


@PROJECTS.tool("ws_diff", description=phrase("projects.workshop.diff"), label=phrase("projects.workshop.diff_label"), args=ListArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_diff(args: ListArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    diff = await port.diff(p.id)
    history = await port.log(p.id, 8)
    return (diff or phrase("projects.workshop.unchanged")) \
        + ("\n\n" + phrase("projects.workshop.history") + "\n" + history if history else "")


def network_summary(p: Project, argv: list[str] | tuple[str, ...], why: str) -> str:
    """Ce qu'on montre de sa demande : la commande entière, un argument par ligne, puis **ses mots** — jamais une
    description qu'on pourrait confondre avec la commande."""
    return (f"Commande avec le réseau (Internet seulement), dans l'atelier du projet n° {p.id}.\n"
            f"La commande, entière, un argument par ligne :\n{argv_lines(argv)}\n"
            f"Ses mots, pour expliquer : « {why.strip()} »")


def _already(frame: Any, p: Project, argv: list[str]) -> bool:
    """La même commande réseau attend-elle déjà, pour ce projet (en file, ou un accord) ?"""
    wanted = [str(a) for a in argv]
    if any(list(queued) == wanted for _, queued, _ in p.network):
        return True
    state = frame.state("projects")
    for v in frame.get(rt.PENDING_EFFECTS):
        if v.capability != NETWORKED_CAPABILITY or project_of(v.context) != p.id:
            continue
        try:
            if [str(a) for a in json.loads(state.awaiting.get(v.proposal, "{}")).get("argv") or []] == wanted:
                return True
        except (ValueError, AttributeError):
            continue
    return False


@PROJECTS.tool("ws_network", acts=True, description=phrase("projects.workshop.network"),
               label=phrase("projects.workshop.network_label"), args=NetworkArgs, bundle=BUNDLE,
               episodes=RUNS,
               max_calls_per_episode=2)
async def ws_network(args: NetworkArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    # ses mots et sa commande sont ce qu'elle écrit pendant une exécution : au niveau de ce qu'elle y lit, celui des
    # projets que le sien lit compris (``written``, ADR 0262) — pas au seul niveau de son cadre
    level = written(p)
    if _already(ctx.frame, p, args.argv):  # la même commande ne s'empile pas : elle attend déjà
        return ToolResult(ok=False, content=phrase("projects.workshop.already"))
    if not p.approval:  # sans accord : elle partira quand cette exécution aura fini (l'atelier est à elle d'ici là)
        await ctx.emit(NETWORK_QUEUED.draft(project=p.id, argv=tuple(args.argv),
                                            why=Content.of(args.why.strip(), level=level),
                                            owner=p.owner, about=p.about, read_about=p.read_about))
        return phrase("projects.workshop.queued")
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=NETWORKED_CAPABILITY, owner=PROJECTS.name,
        args_json=json.dumps({"project": p.id, "argv": args.argv}),
        summary=Content.of(network_summary(p, args.argv, args.why), level=level), approval=True,
        context=project_target(p.id), about=subjects_of(p)))
    return phrase("projects.workshop.proposed")


@PROJECTS.tool("project_push", acts=True, description=phrase("projects.workshop.push"),
               label=phrase("projects.workshop.push_label"), args=PushArgs, bundle=BUNDLE,
               episodes=RUNS, max_calls_per_episode=1)
async def project_push(args: PushArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    if not p.remote:
        return ToolResult(ok=False, content=phrase("projects.workshop.no_remote"))
    done = await propose_push(ctx, p, args.why.strip())
    if done == "nothing":
        return ToolResult(ok=False, content=phrase("projects.workshop.nothing"))
    if done == "pending":
        return ToolResult(ok=False, content=phrase("projects.workshop.push_pending"))
    if done == "base":  # un projet qui passe par des pull requests : sa base ne se pousse pas (ADR 0274)
        return ToolResult(ok=False, content=phrase("projects.workshop.push_base"))
    if done == "unreviewed":  # rien ne sort d'elle-même sans verdict favorable pour ce commit (ADR 0276)
        return ToolResult(ok=False, content=phrase("projects.workshop.push_unreviewed"))
    return phrase("projects.workshop.push_proposed") if p.approval else phrase("projects.workshop.push_sent")


#: pourquoi une demande qui occuperait l'atelier ne s'approuve pas maintenant
BUSY = "une exécution travaille dans l'atelier : décide quand elle aura fini"


def _busy(ports: Mapping[str, Any], pid: int) -> bool:
    frame = ports["frame"]() if "frame" in ports else None
    return frame is not None and busy(frame.state("projects"), pid)


async def _workshop_state(port: Any, pid: int) -> tuple[str, list[str]]:
    """Le commit courant de l'atelier, et ce qui n'y est pas enregistré."""
    if not port.exists(pid):
        return "", []
    return await port.head(pid), sorted(await port.pending(pid))


def _digest(argv: list[str], head: str, dirty: list[str]) -> str:
    raw = json.dumps({"argv": argv, "head": head, "dirty": dirty}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def networked_preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui partirait : la commande, un argument par ligne, et l'atelier où elle tournerait (son
    commit, ce qui n'est pas enregistré). Le condensé épingle les trois."""
    port = ports.get("workshop")
    pid = args.get("project")
    if port is None or not isinstance(pid, int):
        return None
    argv = [str(a) for a in args.get("argv") or []]
    head, dirty = await _workshop_state(port, pid)
    shown = ", ".join(dirty[:20]) + (" …" if len(dirty) > 20 else "")
    text = (f"La commande, entière, un argument par ligne :\n{argv_lines(argv)}\n\n"
            f"Elle tournerait dans l'atelier du projet n° {pid}, avec Internet seulement (ni la machine, ni le "
            f"réseau local), au commit {head[:12] or '(aucun)'}"
            + (f", avec {plural(len(dirty), 'fichier non enregistré', 'fichiers non enregistrés')} : {shown}"
               if dirty else "") + ".")
    blocked = project_refusal(ports, pid).removeprefix("refusé : ")
    if not blocked and _busy(ports, pid):
        blocked = BUSY
    return Preview(text, _digest(argv, head, dirty), blocked)


@PROJECTS.capability(NETWORKED_CAPABILITY,
                     description="Lancer une commande avec le réseau dans l'atelier d'un projet.",
                     preview=networked_preview)
async def networked(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    pid = effect_project(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := project_refusal(ports, pid):
        return False, why
    if _busy(ports, pid):
        return False, "refusé : une exécution travaille dans l'atelier"
    argv = [str(a) for a in args.get("argv") or []]
    seen = str(args.get(SEEN_KEY) or "")
    if seen and seen != _digest(argv, *await _workshop_state(port, pid)):
        return False, "refusé : l'atelier a changé depuis l'accord (rien n'est lancé ; qu'elle le redemande)"
    result = await port.run(pid, argv, network=True)
    return result.ok, describe(result, 3000)


#: les enregistrements de l'atelier relus pour dire ce qui partira (ou arrivera), et ceux qu'un aperçu montre, au plus
REMOTE_WINDOW, REMOTE_SHOWN = 200, 20
#: ce que l'aperçu d'un envoi ou d'une récupération dit (la console de l'opératrice, pas elle)
REMOTE = {
    "push": "Pousser le commit {sha}{title} vers {url}, branche {branch}.",
    "pull": "Récupérer dans l'atelier {url}, branche {branch}, en ligne droite.",
    "unread": "Le dépôt distant ne se lit pas d'ici : on ne sait pas ce qu'il a déjà.",
    "last": "Les derniers enregistrements jusqu'à ce commit :",
    "missing": "Ce commit n'est pas parmi les derniers enregistrements de l'atelier.",
    "new_branch": "La branche « {branch} » n'existe pas encore sur le dépôt distant : elle recevra toute l'histoire "
                  "jusqu'à ce commit :",
    "leaving": "Ce qui partira, les enregistrements que le dépôt distant n'a pas (le plus récent d'abord) :",
    "pushed": "Le dépôt distant a déjà ce commit : rien de nouveau ne partira.",
    "diverged": "Le bout de la branche distante ({head}) n'est pas dans l'histoire de ce commit : l'envoi sera "
                "refusé s'il ne va pas en ligne droite.",
    "coming": "Ce qui arrivera, les enregistrements que l'atelier n'a pas (le plus récent d'abord) :",
    "pulled": "L'atelier a déjà le bout de la branche distante : rien de nouveau n'arrivera.",
    "none": "(aucun dépôt distant)",
    "no_remote": "aucun dépôt distant n'est réglé",
}


def _place(sha: str, commits: Sequence[Commit]) -> int | None:
    """La place d'un commit dans une histoire relue, du plus récent (son identifiant entier ou abrégé) ; ``None`` :
    il n'y est pas."""
    return next((i for i, k in enumerate(commits) if sha and k.sha and (sha.startswith(k.sha) or
                                                                        k.sha.startswith(sha))), None)


def commits_listed(said: str, commits: Sequence[Commit]) -> str:
    """Ce qu'un aperçu dit, puis des enregistrements, un par ligne (« 1a2b3c4 son titre »), les premiers seulement."""
    lines = [f"- {k.sha[:7]} {k.title}" for k in commits[:REMOTE_SHOWN]]
    if len(commits) > REMOTE_SHOWN:
        lines.append(f"- … et {len(commits) - REMOTE_SHOWN} de plus")
    return "\n".join([said, *lines])


def _remote_blocked(ports: Mapping[str, Any], pid: int, url: str) -> str:
    """Pourquoi un envoi ou une récupération ne peut pas partir (vide : il peut)."""
    return project_refusal(ports, pid).removeprefix("refusé : ") or ("" if url else REMOTE["no_remote"])


def base_kept(ports: Mapping[str, Any], pid: int, branch: str) -> str:
    """Pourquoi cet envoi ne part pas (vide : il peut) : il vise la branche de base d'un projet qui passe par des
    pull requests. Aucune capacité ne pousse sur elle : elle n'avance que par ce qui est accepté chez l'hôte."""
    frame = ports["frame"]() if "frame" in ports else None
    p = frame.state("projects").projects.get(pid) if frame is not None else None
    return BASE_KEPT.format(branch=branch) if p is not None and by_pulls(p) and branch == p.branch else ""


async def push_preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui partirait : le dépôt distant, sa branche, le commit épinglé, et les enregistrements que le
    distant n'a pas encore — relus dans l'atelier jusqu'au bout de la branche distante, tel que l'hôte le dit. Le
    condensé épingle le tout : si le distant a bougé depuis la lecture, l'accord se relit."""
    port = ports.get("workshop")
    pid = args.get("project")
    if port is None or not isinstance(pid, int):
        return None
    url, sha, branch = str(args.get("url") or ""), str(args.get("sha") or ""), str(args.get("branch") or "main")
    local = await port.commits(pid, REMOTE_WINDOW) if port.exists(pid) else []
    at = _place(sha, local) if sha else 0
    upto = local[at:] if at is not None else []
    hosted = await hosted_remote(ports, url, branch) if upto else None
    leaving: list[Commit] = []
    if not upto:
        said = REMOTE["missing"]
    elif hosted is None:
        said = commits_listed(f"{REMOTE['unread']}\n{REMOTE['last']}", upto)
    elif not hosted.head:  # la branche n'existe pas encore là-bas : toute l'histoire part
        leaving = upto
        said = commits_listed(REMOTE["new_branch"].format(branch=branch), leaving)
    elif (end := _place(hosted.head, upto)) is not None:
        leaving = upto[:end]
        said = commits_listed(REMOTE["leaving"], leaving) if leaving else REMOTE["pushed"]
    else:
        said = commits_listed(f"{REMOTE['diverged'].format(head=hosted.head[:7])}\n{REMOTE['last']}", upto)
    head = REMOTE["push"].format(sha=(sha or (upto[0].sha if upto else ""))[:12],
                                 title=f" (« {upto[0].title} »)" if upto else "", url=url or REMOTE["none"],
                                 branch=branch)
    # ce qu'une relecture indépendante a dit de ce commit-là (ADR 0276), quand le projet en demande une — pour une
    # branche de travail aussi (ADR 0277) : un envoi que l'opérateur demande part sans verdict, et l'aperçu le dit
    frame = ports["frame"]() if "frame" in ports else None
    project = frame.state("projects").projects.get(pid) if frame is not None else None
    judged = review_line(project, None, sha) if project is not None else ""
    if judged:
        said = f"{judged}\n\n{said}"
    return Preview(f"{head}\n\n{said}", pin_of(url=url, branch=branch, sha=sha, remote=hosted.head if hosted else None,
                                             leaving=[k.sha for k in leaving]),
                   _remote_blocked(ports, pid, url) or base_kept(ports, pid, branch))


async def pull_preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui arriverait : le dépôt distant, sa branche, et les enregistrements que l'atelier n'a pas encore
    (les derniers que l'hôte montre, jusqu'au premier que l'atelier connaît). Le condensé épingle l'atelier et le
    distant tels qu'on les a lus ; une exécution qui travaille dans l'atelier bloque, comme pour la capacité."""
    port = ports.get("workshop")
    pid = args.get("project")
    if port is None or not isinstance(pid, int):
        return None
    url, branch = str(args.get("url") or ""), str(args.get("branch") or "main")
    local = await port.commits(pid, REMOTE_WINDOW) if port.exists(pid) else []
    hosted = await hosted_remote(ports, url, branch)
    coming = [] if hosted is None else \
        list(itertools.takewhile(lambda k: _place(k.sha, local) is None, hosted.commits))
    said = REMOTE["unread"] if hosted is None else commits_listed(REMOTE["coming"], coming) if coming else REMOTE["pulled"]
    blocked = _remote_blocked(ports, pid, url) or (BUSY if _busy(ports, pid) else "")
    return Preview(f"{REMOTE['pull'].format(url=url or REMOTE['none'], branch=branch)}\n\n{said}",
                   pin_of(url=url, branch=branch, head=local[0].sha if local else "",
                        remote=hosted.head if hosted else None), blocked)


@PROJECTS.capability(PUSH_CAPABILITY,
                     description="Envoyer l'atelier d'un projet vers son dépôt distant (git push).",
                     preview=push_preview)
async def push(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    pid = effect_project(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := project_refusal(ports, pid):
        return False, why
    branch = str(args.get("branch") or "main")
    if kept := base_kept(ports, pid, branch):
        return False, f"refusé : {kept}"
    result = await port.push(pid, str(args.get("url") or ""), branch, str(args.get("sha") or ""))
    return result.ok, describe(result, 3000)


@PROJECTS.capability(PULL_CAPABILITY,
                     description="Récupérer l'histoire du dépôt distant dans l'atelier (en ligne droite).",
                     preview=pull_preview)
async def pull(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    pid = effect_project(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := project_refusal(ports, pid):
        return False, why
    if _busy(ports, pid):
        return False, "refusé : une exécution travaille dans l'atelier — récupère quand elle a fini"
    result = await port.pull(pid, str(args.get("url") or ""), str(args.get("branch") or "main"))
    return result.ok, describe(result, 3000)


async def remote_proposal(p: Any, what: str, request: int, port: Any) -> Any:
    """La proposition d'un envoi ou d'une récupération demandés par l'opérateur : sans accord (c'est lui),
    l'envoi épinglé sur le commit courant."""
    args: dict[str, Any] = {"project": p.id, "url": p.remote, "branch": p.branch, "request": request}
    if what == "push":
        sha, title = await pinned(port, p.id)
        args["sha"] = sha
        # un projet qui passe par des pull requests pousse la branche de travail où l'atelier se trouve ; sur sa base,
        # l'envoi garde la base pour cible et la capacité le refuse en le disant (ADR 0274)
        args["branch"] = await push_branch(port, p) or p.branch
        summary = push_summary(p, sha, title, "demandé depuis la console", args["branch"]) if sha else \
            f"Pousser vers {p.remote} — demandé depuis la console (l'atelier n'a encore rien enregistré)"
    elif what == BASE_REQUEST:  # sa pull request vient d'être fusionnée : la base se récupère (ADR 0274)
        summary = BASE_PULL.format(url=p.remote, branch=p.branch)
    else:
        summary = f"Récupérer dans l'atelier {p.remote} (branche {p.branch}) — demandé depuis la console"
    capability = PUSH_CAPABILITY if what == "push" else PULL_CAPABILITY
    return rt.EFFECT_PROPOSED.draft(
        capability=capability, owner=PROJECTS.name, context=project_target(p.id), approval=False,
        args_json=json.dumps(args), summary=Content.of(summary[:600], level=0),
        about=subjects_of(p), dedupe_key=f"distant:{p.id}:{request}")


def network_proposal(p: Project, request: int, argv: tuple[str, ...], why: str) -> Any:
    """Sa commande réseau mise en file (un projet sans accord requis), proposée maintenant que l'exécution qui
    l'a demandée a fini — avec l'accord si l'opératrice l'a exigé depuis : le réglage du projet est relu ici."""
    return rt.EFFECT_PROPOSED.draft(
        capability=NETWORKED_CAPABILITY, owner=PROJECTS.name, context=project_target(p.id), approval=p.approval,
        args_json=json.dumps({"project": p.id, "argv": list(argv), "request": request}),
        summary=Content.of(network_summary(p, argv, why or "(sans raison donnée)"), level=written(p)),
        about=subjects_of(p), dedupe_key=f"reseau:{p.id}:{request}")


__all__ = ["network_proposal", "network_summary", "no_view_words", "pending_push", "remote_proposal", "tidy_views"]
