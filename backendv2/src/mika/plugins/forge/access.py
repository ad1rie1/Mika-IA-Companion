"""Les outils de ses apps et leurs accès (ADR 0133, 0134) : ``<app>_<outil>`` et ``<app>_pages``.

Chaque app s'annonce (un lot ``forge_apps.<app>``) et chacune de ses actions devient un vrai outil, en main
(``_app_tools``, ADR 0104) ; ``<app>_pages`` lit une de ses vues. Ils sont offerts selon la ligne d'accès qui les
concerne (``app_lines``, ``app_level``) : celle de son projet, sa colonne « lecture » pour un outil qui le déclare
(``lit``), « action » sinon ; une app sans projet a ses propres lignes, nées de son minimum vital (``APP_VITAL`` : toi
et elle seule). Seule, l'outil appelle l'app ; sur accord, l'appel est proposé (``calls.ask``) ; ce qu'il rend porte ce
qu'elle en garde (``vocab.access.KEEP_FLOORS``, ADR 0128). Une app qui a des secrets ne sert en conversation que
promue. ``resource_allowance`` redit à la personne la ligne d'une case d'app (ADR 0219) ; ``app_tool_names`` dit ce
qu'une ligne d'un projet peut cocher.

La source d'outils s'inscrit sur ``FORGE`` à l'import du module, que le paquet fait en fin de fichier. Il lit du paquet
l'état, les tours et les aides partagées, et ``calls.py`` pour demander un accord.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import projects as projects_c
from mika.kernel.faculty import ToolResult, ToolSpec
from mika.kernel.frame import Frame
from mika.plugins.forge import (
    APPS_BUNDLE,
    FORGE,
    App,
    bad_args,
    calls,
    caretaker,
    concerns,
    forge_port,
    has_secrets,
    outcomes,
    params,
    sifting_app,
    stopped,
    timeout_of,
    trusted,
)
from mika.plugins.forge.views import (
    VIEW_MAX_BYTES,
    VIEW_TIMEOUT_S,
    decode_view,
    failure_note,
    is_invalid,
    view_params,
)
from mika.ports.forge_args import args_schema, check_args
from mika.vocab.access import ALONE, CLOSED_TOOLS, INTERNAL, KEEP_FLOORS, NO, OWNER, SELF, ToolRule
from mika.vocab.episodes import WORKING, Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.rights import closeness_of, rights_of, tool_allowance

# ── Les outils de ses apps et leurs accès ─────────────────────────────────


class AppToolArgs(BaseModel):
    """Les arguments d'un outil d'app, tels que le modèle les donne : son schéma est celui que l'app déclare
    (``args_schema``), et l'hôte les vérifie (``check_args``) avant de les lui passer (ADR 0105)."""

    model_config = ConfigDict(extra="allow")


class PagesArgs(BaseModel):
    view: str = Field(default="", max_length=24, description=phrase("forge.tools.pages.view"))
    params: dict[str, Any] = Field(default_factory=dict, description=phrase("forge.tools.pages.params"))


#: où ses apps servent : en conversation, en initiative (devant sa propriétaire), quand elle travaille, et quand elle
#: lit la file de signaux d'une app (une tâche, ADR 0105)
APP_EPISODES = frozenset({Kind.REPLY, Kind.INITIATIVE, Kind.TASK, *WORKING})


#: le minimum vital d'une app sans projet, tant qu'on ne l'a pas réglée (ADR 0134) : à toi, et elle seule, sans
#: demander, ce qu'elle rend gardé comme un souvenir ; personne d'autre
APP_VITAL = (ToolRule(who=(OWNER,), read=ALONE, act=ALONE, keep="perso"),
             ToolRule(who=(SELF,), canal=(INTERNAL,), read=ALONE, act=ALONE, keep="perso"))


def app_lines(frame: Frame, app: App | None) -> tuple[tuple[Any, ...], Any]:
    """Les lignes d'accès qui valent pour une app (ADR 0133, 0134) : celles de son projet ; sans projet, les siennes
    (ou son minimum vital) ; son projet archivé ou disparu, personne."""
    if app is None:
        return (), projects_c.CLOSED
    if not app.project:
        return (tuple(app.access), app.default_access) if app.access is not None else (APP_VITAL, CLOSED_TOOLS)
    view = next((v for v in frame.get(projects_c.LIVE) if v.id == app.project), None)
    return (view.access, view.default_access) if view is not None else ((), projects_c.CLOSED)


def _allowance(frame: Frame, app: App | None, tool: str, acts: bool, audience: Any, kind: str) -> Any:
    """La ligne de son projet (ou la sienne) qui décide de cet outil d'app (``tool`` : ``<app>_<outil>``) devant qui
    est en face, à ce moment : sa colonne « lecture » ou « action », serrée par le canal et le plafond (ADR 0134)."""
    rows, default = app_lines(frame, app)
    return tool_allowance(rows, default, audience, kind, acts, rights_of(frame.env),
                          lambda a: not a.tools or tool in a.tools, close=closeness_of(frame.env, frame), outside=True)


def app_level(frame: Frame, name: str, tool: str, reads: bool, audience: Any, kind: str) -> tuple[str, str]:
    """Ce qu'elle fait de cet outil d'app devant qui est en face, à ce moment, et ce qu'elle en garde (``_allowance``) ;
    ``non`` sans personne."""
    got = _allowance(frame, frame.state("forge").apps.get(name), tool, not reads, audience, kind)
    return (got.level, got.keep) if got is not None else (NO, "rien")


def resource_allowance(frame: Frame, resource: str, tool: str, acts: bool, audience: Any, kind: str) -> Any:
    """La lecture même d'une case d'app, pour qu'on redise sa ligne à la personne (ADR 0219) : ``resource`` est celle
    de ses droits (``forge:<app>``, ou ``project:<n>`` pour une app d'un projet, qui suit les lignes du projet) ;
    ``None`` sans app ni ligne."""
    sort, _, key = resource.partition(":")
    apps = frame.state("forge").apps
    app = apps.get(key) if sort == "forge" else \
        next((a for a in apps.values() if str(a.project) == key), None) if sort == "project" else None
    return _allowance(frame, app, tool, acts, audience, kind) if app is not None else None


def app_tool_names(frame: Frame, ports: Mapping[str, Any], project: int) -> list[tuple[str, str]]:
    """Les outils des apps d'un projet, tels qu'elle les nomme (``<app>_<outil>``, ``<app>_pages``), et ce qu'ils
    font (« lit », « agit ») : ce qu'une ligne d'accès de ce projet peut cocher."""
    port = ports.get("forge")
    out: list[tuple[str, str]] = []
    for name, app in sorted(frame.state("forge").apps.items()):
        info = port.info(name) if port is not None and app.project == project else None
        if info is None:
            continue
        out += [(f"{name}_{t.name}", "lit" if t.reads else "agit") for t in info.tools]
        if info.views:
            out.append((f"{name}_pages", "lit"))
    return out


def _app_gate(name: str, tool: str, reads: bool) -> Any:
    def allowed(audience: Any, kind: str, frame: Any = None) -> bool:
        """Seulement là où les lignes d'accès de son projet l'ouvrent, devant cette personne, à ce moment (ADR 0133).

        Jamais dans un salon, avec une inconnue, ni sans ce qu'elle vit (une console qui juge hors de sa vie)."""
        return frame is not None and app_level(frame, name, tool, reads, audience, kind)[0] != NO

    return allowed


def _usable(ctx: Any, name: str, port: Any, tool: str, reads: bool) -> tuple[App | None, str, str, str]:
    """L'app, pourquoi elle ne sert pas ici (vide : elle sert), ce qu'elle en fait (``seule``, ``carte``, ``toi``) et
    ce qu'elle en garde : ses lignes d'accès (ADR 0133, 0134) ; en conversation, une app qui a des secrets seulement
    si un opérateur l'a promue (ADR 0104)."""
    app = ctx.frame.state("forge").apps.get(name)
    if port is None or app is None:
        return None, phrase("forge.tools.call.unavailable"), NO, "rien"
    if app.held or not app.enabled or app.broken:
        return app, phrase("forge.tools.call.stopped", why=stopped(app)), NO, "rien"
    ep = ctx.frame.episode
    level, keep = app_level(ctx.frame, name, tool, reads, ctx.frame.audience, ep.kind if ep is not None else "")
    if level == NO:
        # une app peut sortir ce qu'on lui passe vers le réseau : seulement pour qui ses lignes d'accès le permettent
        return app, phrase("forge.tools.call.not_here", who=caretaker(ctx.frame)), NO, "rien"
    working = ep is not None and (ep.kind in WORKING or (ep.kind == Kind.TASK and bool(sifting_app(ep.target))))
    if not working and not app.promoted and has_secrets(ctx.ports, port.info(name)):
        return app, phrase("forge.tools.call.secrets"), NO, "rien"
    return app, "", level, keep


def app_tool(name: str, tool: str) -> Any:
    """Le gestionnaire d'un outil que déclare une app : son code, dans son bac à sable ; ce qu'il signale ou émet
    vit comme le reste de sa vie (jamais compté contre elle)."""

    async def handler(args: AppToolArgs, ctx: Any) -> ToolResult:
        port = forge_port(ctx)
        info = port.info(name) if port is not None else None
        spec = next((t for t in info.tools if t.name == tool), None) if info is not None else None
        app, why, level, keep = _usable(ctx, name, port, f"{name}_{tool}", bool(spec is not None and spec.reads))
        if why or app is None:
            return ToolResult(ok=False, content=why)
        if spec is None:
            return ToolResult(ok=False, content=phrase("forge.tools.call.no_tool"))
        values, errors = check_args(spec.args, args.model_dump())  # l'hôte vérifie avant l'app (ADR 0105)
        if errors:
            return ToolResult(ok=False, content=bad_args(spec, errors))
        if level != ALONE:  # sur accord (ADR 0133) : rien ne part avant le oui
            return await calls.ask(ctx, app, name, f"{name}_{tool}", f"tool_{tool}", values, level, keep)
        frame: Frame = ctx.frame
        r = await port.call(name, f"tool_{tool}", values,
                            timeout_s=timeout_of(info, f"tool_{tool}", params(frame.env.params_of("forge",
                                                                                                  frame.root))),
                            secrets=trusted(app))
        drafts = outcomes(name, app, [r], frame.now, params(frame.env.params_of("forge", frame.root)), breaker=False,
                          concern=concerns(frame, app))
        if drafts:
            await ctx.emit(*drafts)
        if not r.ok:
            return ToolResult(ok=False, content=phrase("forge.tools.call.failed", error=r.error[:500]))
        return ToolResult(content=phrase("forge.tools.call.result",
                                         value=json.dumps(r.value, ensure_ascii=False, default=str)[:3000]),
                          floor=KEEP_FLOORS.get(keep, 0), unkept=keep == "rien")

    return handler


def app_pages(name: str) -> Any:
    """Lire une page d'une app (une de ses vues) : une lecture, jamais journalisée, jamais comptée par le
    disjoncteur — ce qu'elle a trouvé, à dire à qui le demande (ADR 0104)."""

    async def handler(args: PagesArgs, ctx: Any) -> ToolResult:
        port = forge_port(ctx)
        app, why, level, keep = _usable(ctx, name, port, f"{name}_pages", True)
        if why or app is None:
            return ToolResult(ok=False, content=why)
        info = port.info(name)
        views = info.views if info is not None else ()
        spec = next((v for v in views if v.key == args.view), views[0] if views and not args.view else None)
        if info is None or spec is None:
            return ToolResult(ok=False, content=phrase("forge.tools.pages.unknown",
                                                       views=", ".join(v.key for v in views)))
        values, notes = view_params(spec, {k: str(v).lower() if isinstance(v, bool) else str(v)
                                          for k, v in args.params.items()})
        if level != ALONE:  # sur accord (ADR 0133) : rien ne se lit avant le oui
            return await calls.ask(ctx, app, name, f"{name}_pages", spec.function, values, level, keep)
        r = await port.call(name, spec.function, values, timeout_s=VIEW_TIMEOUT_S, max_result=VIEW_MAX_BYTES,
                            secrets=trusted(app))
        if not r.ok:
            return ToolResult(ok=False, content=failure_note(spec.label, r).text, proof=False)
        blocks = decode_view(r.value, name, info, spec)
        if is_invalid(blocks):
            return ToolResult(ok=False, content=blocks[0].text, proof=False)
        said = "".join(f"\n{n}" for n in notes)
        return ToolResult(content=phrase("forge.tools.pages.result", title=spec.label,
                                         value=json.dumps(r.value, ensure_ascii=False, default=str)[:3000]) + said,
                          proof=False, floor=KEEP_FLOORS.get(keep, 0), unkept=keep == "rien")

    return handler


@FORGE.tool_source(APPS_BUNDLE)
def _app_tools(ports: Mapping[str, Any]) -> tuple[list[ToolSpec], dict[str, str]]:
    """Chaque app s'annonce (un lot ``forge_apps.<app>``, décrit par son titre) et chacune de ses actions devient un
    vrai outil — ``<app>_<outil>``, et ``<app>_pages`` pour lire ses pages — en main : ce sont ses mains à elle, peu
    nombreuses (ADR 0104). Recalculé quand l'hôte change (une app écrite, installée, effacée)."""
    port = ports.get("forge")
    if port is None:
        return [], {}
    tools: list[ToolSpec] = []
    bundles: dict[str, str] = {}
    for info in port.apps():
        if info.error:
            continue
        bundle = f"{APPS_BUNDLE}.{info.name}"
        bundles[bundle] = phrase("forge.apps.bundle", title=info.title, description=info.description[:200])
        for t in info.tools:
            tools.append(ToolSpec(
                FORGE.name, f"{info.name}_{t.name}", phrase("forge.apps.tool", title=info.title,
                                                            description=t.description[:300]),
                AppToolArgs, app_tool(info.name, t.name), bundle, APP_EPISODES, max_calls_per_episode=3,
                fits=_app_gate(info.name, f"{info.name}_{t.name}", t.reads), rule=phrase("forge.apps.rule"),
                schema=args_schema(t.args), in_hand=True))
        if info.views:
            tools.append(ToolSpec(
                FORGE.name, f"{info.name}_pages", phrase("forge.apps.pages", title=info.title,
                                                         views=", ".join(v.key for v in info.views)),
                PagesArgs, app_pages(info.name), bundle, APP_EPISODES, max_calls_per_episode=4,
                fits=_app_gate(info.name, f"{info.name}_pages", True), rule=phrase("forge.apps.rule"), in_hand=True))
    return tools, bundles
