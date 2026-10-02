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
pas comme une description de la commande.

**L'atelier n'a qu'un occupant à la fois** : une commande réseau ne s'approuve
pas pendant qu'une exécution y travaille ; sans accord requis, elle attend la
fin de l'exécution qui l'a demandée ; et aucune exécution ne part tant qu'une
commande, un envoi ou une récupération sont en route.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field, field_validator

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import NETWORK_QUEUED, NETWORKED, PROJECTS, Project, busy, params
from mika.faculties.projects.tools import (
    GONE,
    current,
    pending_push,
    pinned,
    propose_push,
    push_summary,
    wrap_up,
)
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.operate import Preview
from mika.ports.workshop import OutsideWorkshop, WorkshopFull, argv_lines, describe
from mika.vocab.episodes import PROJECT_KINDS, project_of, project_target

BUNDLE = "workshop"
RUNS = list(PROJECT_KINDS)
#: un argument de commande réseau, au plus (la commande se montre entière à qui l'approuve)
ARG_MAX = 2000
#: la clé où l'accord épingle l'aperçu lu (``runtime/decisions.py``)
SEEN_KEY = "_apercu"


def _atelier(ctx: Any) -> tuple[Any, Any] | str:
    got = current(ctx)
    if got is None:
        return GONE
    port = ctx.ports.get("workshop")
    if port is None:
        return "L'atelier n'est pas disponible ici."
    return got[0], port


PROJECTS.bundle(BUNDLE, "l'atelier d'un projet : lire, écrire, lancer des programmes isolés, son dépôt git")


class ListArgs(BaseModel):
    path: str = Field(default="", max_length=300, description="un dossier du projet (vide : tout le projet)")


class ReadArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300, description="le fichier à lire, relatif au dossier du projet")


class WriteArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=200_000)


class EditArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    old: str = Field(min_length=1, max_length=20_000, description="le fragment exact à remplacer (unique)")
    new: str = Field(max_length=20_000)


class RunArgs(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40, description="la commande et ses arguments, "
                                                                      "par exemple [\"python3\", \"test_x.py\"]")
    #: borné en plus par ce qui reste à l'exécution : un programme lent ne la fait jamais expirer
    timeout_s: int = Field(default=60, ge=1, le=300)


class NetworkArgs(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40, description="la commande et ses arguments (pip, npm, git, "
                                                                      "curl, wget, python…)")
    why: str = Field(min_length=1, max_length=400, description="pourquoi il faut le réseau, pour qui l'approuvera")

    @field_validator("argv")
    @classmethod
    def _bounded(cls, argv: list[str]) -> list[str]:
        if any(len(a) > ARG_MAX for a in argv):
            raise ValueError(f"un argument fait au plus {ARG_MAX} caractères")
        return argv


class PushArgs(BaseModel):
    why: str = Field(min_length=1, max_length=400, description="ce que contient cet envoi, pour qui l'approuvera")


@PROJECTS.tool("ws_list", description="Lister les fichiers du projet (ou d'un de ses dossiers), les plus proches de "
               "la racine d'abord.", args=ListArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_list(args: ListArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    try:
        files = await port.tree(p.id, args.path or ".")
    except OutsideWorkshop as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return wrap_up(ctx, "\n".join(files) if files else "(le dossier est vide)")


@PROJECTS.tool("ws_read", description="Lire un fichier du projet.", args=ReadArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_read(args: ReadArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    try:
        return wrap_up(ctx, await port.read(p.id, args.path))
    except (OutsideWorkshop, FileNotFoundError) as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")


@PROJECTS.tool("ws_write", description="Écrire (ou remplacer) un fichier du projet.", args=WriteArgs, bundle=BUNDLE,
               episodes=RUNS)
async def ws_write(args: WriteArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    try:
        rel = await port.write(p.id, args.path, args.content)
    except (OutsideWorkshop, WorkshopFull) as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return wrap_up(ctx, f"Écrit : {rel} ({len(args.content)} caractères).")


@PROJECTS.tool("ws_edit", description="Remplacer un fragment exact (et unique) dans un fichier du projet.",
               args=EditArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_edit(args: EditArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    try:
        rel = await port.edit(p.id, args.path, args.old, args.new)
    except (OutsideWorkshop, FileNotFoundError, ValueError) as exc:  # WorkshopFull est une ValueError
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return wrap_up(ctx, f"Modifié : {rel}.")


def program_time_left(ctx: Any) -> float:
    """Ce qui reste aux programmes de cette exécution (secondes) : ils doivent avoir fini un peu après son début,
    bien avant son délai — un programme lent s'arrête en « délai dépassé », que le modèle lit et qui lui laisse
    le temps de conclure."""
    pm = params(ctx.frame.env.params_of("projects", ctx.frame.root))
    run = ctx.frame.state("projects").running.get(ctx.episode_id)
    if run is None or not run.started:
        return pm.run_programs_us / 1_000_000
    return max(0.0, (run.started + pm.run_programs_us - ctx.frame.now) / 1_000_000)


@PROJECTS.tool("ws_run", description="Lancer une commande dans le dossier du projet (isolée, sans réseau). Le temps "
               "des programmes d'une exécution est compté : garde de quoi conclure.",
               args=RunArgs, bundle=BUNDLE, episodes=RUNS, max_calls_per_episode=8)
async def ws_run(args: RunArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    left = program_time_left(ctx)
    if left < 2:
        return ToolResult(ok=False, content="Plus le temps de lancer un programme dans cette exécution : conclus "
                                            "par report_run (« continue », tu reprendras à la prochaine).")
    result = await port.run(p.id, args.argv, timeout_s=min(float(args.timeout_s), left))
    # une commande refusée ou en échec n'est pas du travail fait (elle reste une information)
    return wrap_up(ctx, ToolResult(ok=result.ok, content=describe(result)))


@PROJECTS.tool("ws_diff", description="Relire ce qui a changé depuis le dernier enregistrement, et l'historique.",
               args=ListArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_diff(args: ListArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    diff = await port.diff(p.id)
    history = await port.log(p.id, 8)
    return wrap_up(ctx, (diff or "(rien de changé depuis le dernier enregistrement)")
                   + ("\n\nHistorique :\n" + history if history else ""))


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
        if v.capability != NETWORKED or project_of(v.context) != p.id:
            continue
        try:
            if [str(a) for a in json.loads(state.awaiting.get(v.proposal, "{}")).get("argv") or []] == wanted:
                return True
        except (ValueError, AttributeError):
            continue
    return False


@PROJECTS.tool("ws_network", description="Proposer une commande qui a besoin du réseau (installer une dépendance, "
               "télécharger…). Elle ne part pas tout de suite : selon le projet, un opérateur doit l'approuver, sinon "
               "elle part à la fin de cette exécution.", args=NetworkArgs, bundle=BUNDLE, episodes=RUNS,
               max_calls_per_episode=2)
async def ws_network(args: NetworkArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return GONE
    p, _ = got
    about = tuple(x for x in (p.owner, *p.about) if x)
    if _already(ctx.frame, p, args.argv):  # la même commande ne s'empile pas : elle attend déjà
        return wrap_up(ctx, ToolResult(ok=False, content="Cette commande attend déjà (un accord, ou la fin de "
                                                         "l'exécution) : inutile de la redemander."))
    if not p.approval:  # sans accord : elle partira quand cette exécution aura fini (l'atelier est à elle d'ici là)
        await ctx.emit(NETWORK_QUEUED.draft(project=p.id, argv=tuple(args.argv),
                                            why=Content.of(args.why.strip(), level=p.sensitivity),
                                            owner=p.owner, about=p.about))
        return wrap_up(ctx, "Noté : elle partira à la fin de cette exécution ; tu verras son résultat à la "
                            "suivante.")
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=NETWORKED, owner=PROJECTS.name, args_json=json.dumps({"project": p.id, "argv": args.argv}),
        summary=Content.of(network_summary(p, args.argv, args.why), level=p.sensitivity), approval=True,
        context=project_target(p.id), about=about))
    return wrap_up(ctx, "Proposé : un opérateur doit l'approuver. Tu verras le résultat à une prochaine exécution.")


@PROJECTS.tool("project_push", description="Proposer d'envoyer ce qui est enregistré dans l'atelier vers le dépôt "
               "distant du projet. Selon le projet, un opérateur doit l'approuver.", args=PushArgs, bundle=BUNDLE,
               episodes=RUNS, max_calls_per_episode=1)
async def project_push(args: PushArgs, ctx: Any) -> Any:
    got = current(ctx)
    if got is None:
        return GONE
    p, _ = got
    if not p.remote:
        return ToolResult(ok=False, content="Ce projet n'a pas de dépôt distant (un opérateur le règle).")
    done = await propose_push(ctx, p, args.why.strip())
    if done == "nothing":
        return ToolResult(ok=False, content="Rien à envoyer : l'atelier n'a encore aucun enregistrement.")
    if done == "pending":
        return ToolResult(ok=False, content="Un envoi attend déjà l'accord d'un opérateur : celui-ci suivra.")
    return "Envoi proposé : un opérateur doit l'approuver." if p.approval else "Envoi lancé."


def _project_of(args: Mapping[str, Any], context: str) -> int | None:
    pid = project_of(context)
    return pid if pid is not None and args.get("project") == pid else None


def _gone(ports: Mapping[str, Any], pid: int) -> str:
    """Pourquoi un effet ne s'exécute plus pour ce projet (vide : il peut) : archivé, il ne sort plus rien,
    même approuvé avant."""
    frame = ports["frame"]() if "frame" in ports else None
    p = frame.state("projects").projects.get(pid) if frame is not None else None
    if frame is not None and p is None:
        return "refusé : ce projet n'existe plus"
    if p is not None and p.status == c.ARCHIVED:
        return "refusé : ce projet est archivé"
    return ""


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
            + (f", avec {len(dirty)} fichier(s) non enregistré(s) : {shown}" if dirty else "") + ".")
    blocked = _gone(ports, pid).removeprefix("refusé : ")
    if not blocked and _busy(ports, pid):
        blocked = "une exécution travaille dans l'atelier : décide quand elle aura fini"
    return Preview(text, _digest(argv, head, dirty), blocked)


@PROJECTS.capability("networked", description="Lancer une commande avec le réseau dans l'atelier d'un projet.",
                     preview=networked_preview)
async def networked(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    pid = _project_of(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := _gone(ports, pid):
        return False, why
    if _busy(ports, pid):
        return False, "refusé : une exécution travaille dans l'atelier"
    argv = [str(a) for a in args.get("argv") or []]
    seen = str(args.get(SEEN_KEY) or "")
    if seen and seen != _digest(argv, *await _workshop_state(port, pid)):
        return False, "refusé : l'atelier a changé depuis l'accord (rien n'est lancé ; qu'elle le redemande)"
    result = await port.run(pid, argv, network=True)
    return result.ok, describe(result, 3000)


@PROJECTS.capability("push", description="Envoyer l'atelier d'un projet vers son dépôt distant (git push).")
async def push(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    pid = _project_of(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := _gone(ports, pid):
        return False, why
    result = await port.push(pid, str(args.get("url") or ""), str(args.get("branch") or "main"),
                             str(args.get("sha") or ""))
    return result.ok, describe(result, 3000)


@PROJECTS.capability("pull", description="Récupérer l'histoire du dépôt distant dans l'atelier (en ligne droite).")
async def pull(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    pid = _project_of(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := _gone(ports, pid):
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
        summary = push_summary(p, sha, title, "demandé depuis la console") if sha else \
            f"Pousser vers {p.remote} — demandé depuis la console (l'atelier n'a encore rien enregistré)"
    else:
        summary = f"Récupérer dans l'atelier {p.remote} (branche {p.branch}) — demandé depuis la console"
    return rt.EFFECT_PROPOSED.draft(
        capability=f"{c.OWNER}.{what}", owner=PROJECTS.name, context=project_target(p.id), approval=False,
        args_json=json.dumps(args), summary=Content.of(summary[:600], level=0),
        about=tuple(x for x in (p.owner, *p.about) if x), dedupe_key=f"distant:{p.id}:{request}")


def network_proposal(p: Project, request: int, argv: tuple[str, ...], why: str) -> Any:
    """Sa commande réseau mise en file (un projet sans accord requis), proposée maintenant que l'exécution qui
    l'a demandée a fini."""
    return rt.EFFECT_PROPOSED.draft(
        capability=NETWORKED, owner=PROJECTS.name, context=project_target(p.id), approval=False,
        args_json=json.dumps({"project": p.id, "argv": list(argv), "request": request}),
        summary=Content.of(network_summary(p, argv, why or "(sans raison donnée)"), level=p.sensitivity),
        about=tuple(x for x in (p.owner, *p.about) if x), dedupe_key=f"reseau:{p.id}:{request}")


__all__ = ["network_proposal", "network_summary", "pending_push", "remote_proposal"]
