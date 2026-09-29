"""L'atelier d'un but : ses outils (lot ``workshop``, offerts aux pas des
projets seulement) et la seule capacité qui en sort.

Dans l'atelier, elle agit librement : lire, écrire, éditer, lancer un
programme isolé, relire ce qu'elle a changé. Ce qui **sort de la machine**
(une commande qui a besoin du réseau) ne part jamais d'un outil : elle le
propose (``effect.proposed``), et selon le projet il attend l'accord d'un
opérateur — qui le voit dans son panneau, avec le résumé qu'elle en a fait.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import runtime as rt
from mika.faculties.goals.faculty import GOALS
from mika.faculties.goals.tools import _goal
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.ports.workshop import OutsideWorkshop, describe
from mika.vocab.episodes import Kind, goal_of

BUNDLE = "workshop"
NETWORKED = "goals.networked"


def _atelier(ctx: Any) -> tuple[Any, Any] | str:
    g = _goal(ctx)
    if g is None:
        return "Ce but n'est plus en cours."
    port = ctx.ports.get("workshop")
    if port is None:
        return "L'atelier n'est pas disponible ici."
    return g, port


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
    timeout_s: int = Field(default=60, ge=1, le=600)


class NetworkArgs(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=40)
    why: str = Field(min_length=1, max_length=400, description="pourquoi il faut le réseau, pour qui l'approuvera")


@GOALS.tool("ws_list", description="Lister les fichiers du dossier du projet.", args=PathArgs, bundle=BUNDLE,
            episodes=[Kind.STEP])
async def ws_list(args: PathArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    g, port = got
    try:
        files = await port.tree(g.id, args.path)
    except OutsideWorkshop as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return "\n".join(files) if files else "(le dossier est vide)"


@GOALS.tool("ws_read", description="Lire un fichier du projet.", args=PathArgs, bundle=BUNDLE, episodes=[Kind.STEP])
async def ws_read(args: PathArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    g, port = got
    try:
        return await port.read(g.id, args.path)
    except (OutsideWorkshop, FileNotFoundError) as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")


@GOALS.tool("ws_write", description="Écrire (ou remplacer) un fichier du projet.", args=WriteArgs, bundle=BUNDLE,
            episodes=[Kind.STEP])
async def ws_write(args: WriteArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    g, port = got
    try:
        rel = await port.write(g.id, args.path, args.content)
    except OutsideWorkshop as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return f"Écrit : {rel} ({len(args.content)} caractères)."


@GOALS.tool("ws_edit", description="Remplacer un fragment exact (et unique) dans un fichier du projet.",
            args=EditArgs, bundle=BUNDLE, episodes=[Kind.STEP])
async def ws_edit(args: EditArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    g, port = got
    try:
        rel = await port.edit(g.id, args.path, args.old, args.new)
    except (OutsideWorkshop, FileNotFoundError, ValueError) as exc:
        return ToolResult(ok=False, content=f"Refusé : {exc}")
    return f"Modifié : {rel}."


@GOALS.tool("ws_run", description="Lancer une commande dans le dossier du projet (isolée, sans réseau).",
            args=RunArgs, bundle=BUNDLE, episodes=[Kind.STEP], max_calls_per_episode=6)
async def ws_run(args: RunArgs, ctx: Any) -> Any:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    g, port = got
    result = await port.run(g.id, args.argv, timeout_s=args.timeout_s)
    # une commande refusée ou en échec n'est pas du travail fait (elle reste une information)
    return ToolResult(ok=result.ok, content=describe(result))


@GOALS.tool("ws_diff", description="Relire ce qui a changé depuis le dernier pas.", args=PathArgs, bundle=BUNDLE,
            episodes=[Kind.STEP])
async def ws_diff(args: PathArgs, ctx: Any) -> str:
    got = _atelier(ctx)
    if isinstance(got, str):
        return got
    g, port = got
    diff = await port.diff(g.id)
    history = await port.log(g.id, 5)
    return (diff or "(rien de changé depuis le dernier pas)") + ("\n\nHistorique :\n" + history if history else "")


@GOALS.tool("ws_network", description="Proposer une commande qui a besoin du réseau (installer une dépendance, "
            "télécharger…). Elle ne part pas tout de suite : selon le projet, un opérateur doit l'approuver.",
            args=NetworkArgs, bundle=BUNDLE, episodes=[Kind.STEP], max_calls_per_episode=2)
async def ws_network(args: NetworkArgs, ctx: Any) -> str:
    g = _goal(ctx)
    if g is None:
        return "Ce but n'est plus en cours."
    summary = f"{args.why.strip()} — commande : {' '.join(args.argv)}"
    await ctx.emit(rt.EFFECT_PROPOSED.draft(
        capability=NETWORKED, owner=GOALS.name, args_json=json.dumps({"goal": g.id, "argv": args.argv}),
        summary=Content.of(summary[:600], level=0), approval=g.approval, context=f"goal:{g.id}"))
    if g.approval:
        return "Proposé : un opérateur doit l'approuver. Tu verras le résultat à un prochain pas."
    return "Lancé : tu verras le résultat à un prochain pas."


@GOALS.capability("networked", description="Lancer une commande avec le réseau dans l'atelier d'un but.")
async def networked(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("workshop")
    gid = goal_of(context)
    if port is None or gid is None or args.get("goal") != gid:
        return False, "atelier introuvable"
    argv = [str(a) for a in args.get("argv") or []]
    result = await port.run(gid, argv, network=True)
    return result.ok, describe(result, 3000)
