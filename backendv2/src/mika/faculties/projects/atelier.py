"""L'atelier d'un projet : ses outils (lot ``workshop``) et ce qui en sort.

Dans l'atelier, elle agit librement : lire, écrire, éditer, lancer un
programme isolé, relire ce qu'elle a changé. Ce qui **sort de la machine**
(une commande qui a besoin du réseau, un envoi au dépôt distant) ne part jamais
d'un outil : elle le propose (``effect.proposed``), et selon le projet il
attend l'accord d'un opérateur. Pousser et récupérer sont aussi des
**capacités** que l'opérateur déclenche depuis la console (exécutées tout de
suite : c'est lui qui les demande).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import NETWORKED, PROJECTS, busy
from mika.faculties.projects.tools import GONE, current, pinned, propose_push, push_summary
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.ports.workshop import OutsideWorkshop, describe
from mika.vocab.episodes import PROJECT_KINDS, project_of, project_target

BUNDLE = "workshop"
RUNS = list(PROJECT_KINDS)


def _atelier(ctx: Any) -> tuple[Any, Any] | str:
    got = current(ctx)
    if got is None:
        return GONE
    port = ctx.ports.get("workshop")
    if port is None:
        return "L'atelier n'est pas disponible ici."
    return got[0], port


PROJECTS.bundle(BUNDLE, "l'atelier d'un projet : lire, écrire, lancer des programmes isolés, son dépôt git")


class PathArgs(BaseModel):
    path: str = Field(default=".", max_length=300, description="chemin relatif au dossier du projet")


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
    #: bien en deçà du délai d'une exécution (10 min) : un programme long ne doit pas la faire expirer
    timeout_s: int = Field(default=60, ge=1, le=300)


class NetworkArgs(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40)
    why: str = Field(min_length=1, max_length=400, description="pourquoi il faut le réseau, pour qui l'approuvera")


class PushArgs(BaseModel):
    why: str = Field(min_length=1, max_length=400, description="ce que contient cet envoi, pour qui l'approuvera")


@PROJECTS.tool("ws_list", description="Lister les fichiers du dossier du projet.", args=PathArgs, bundle=BUNDLE,
               episodes=RUNS)
async def ws_list(args: PathArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    try:
        files = await port.tree(p.id, args.path)
    except OutsideWorkshop as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return "\n".join(files) if files else "(le dossier est vide)"


@PROJECTS.tool("ws_read", description="Lire un fichier du projet.", args=PathArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_read(args: PathArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    try:
        return await port.read(p.id, args.path)
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
    except OutsideWorkshop as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return f"Écrit : {rel} ({len(args.content)} caractères)."


@PROJECTS.tool("ws_edit", description="Remplacer un fragment exact (et unique) dans un fichier du projet.",
               args=EditArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_edit(args: EditArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    try:
        rel = await port.edit(p.id, args.path, args.old, args.new)
    except (OutsideWorkshop, FileNotFoundError, ValueError) as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return f"Modifié : {rel}."


@PROJECTS.tool("ws_run", description="Lancer une commande dans le dossier du projet (isolée, sans réseau).",
               args=RunArgs, bundle=BUNDLE, episodes=RUNS, max_calls_per_episode=8)
async def ws_run(args: RunArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    result = await port.run(p.id, args.argv, timeout_s=args.timeout_s)
    # une commande refusée ou en échec n'est pas du travail fait (elle reste une information)
    return ToolResult(ok=result.ok, content=describe(result))


@PROJECTS.tool("ws_diff", description="Relire ce qui a changé depuis le dernier enregistrement, et l'historique.",
               args=PathArgs, bundle=BUNDLE, episodes=RUNS)
async def ws_diff(args: PathArgs, ctx: Any) -> str:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    p, port = got
    diff = await port.diff(p.id)
    history = await port.log(p.id, 8)
    return (diff or "(rien de changé depuis le dernier enregistrement)") + \
        ("\n\nHistorique :\n" + history if history else "")


@PROJECTS.tool("ws_network", description="Proposer une commande qui a besoin du réseau (installer une dépendance, "
               "télécharger…). Elle ne part pas tout de suite : selon le projet, un opérateur doit l'approuver.",
               args=NetworkArgs, bundle=BUNDLE, episodes=RUNS, max_calls_per_episode=2)
async def ws_network(args: NetworkArgs, ctx: Any) -> str:
    got = current(ctx)
    if got is None:
        return GONE
    p, _ = got
    summary = f"{args.why.strip()} — commande : {' '.join(args.argv)}"
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=NETWORKED, owner=PROJECTS.name, args_json=json.dumps({"project": p.id, "argv": args.argv}),
        summary=Content.of(summary[:600], level=0), approval=p.approval, context=project_target(p.id),
        about=tuple(x for x in (p.owner, *p.about) if x)))
    if p.approval:
        return "Proposé : un opérateur doit l'approuver. Tu verras le résultat à une prochaine exécution."
    return "Lancé : tu verras le résultat à une prochaine exécution."


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
    if not await propose_push(ctx, p, args.why.strip()):
        return ToolResult(ok=False, content="Rien à envoyer : l'atelier n'a encore aucun enregistrement.")
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


@PROJECTS.capability("networked", description="Lancer une commande avec le réseau dans l'atelier d'un projet.")
async def networked(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    pid = _project_of(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := _gone(ports, pid):
        return False, why
    argv = [str(a) for a in args.get("argv") or []]
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
    frame = ports["frame"]() if "frame" in ports else None
    if frame is not None and busy(frame.state("projects"), pid):
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
