"""La file de signaux d'une app (ADR 0105) : une tâche pour en lire un lot, et son verdict.

Ce qu'une app lui signale entre dans sa file (``c.QUEUED``, réduit par le paquet). Quand une file attend, une tâche
en lit un lot, autant que l'app le déclare, avec la consigne de l'app, sous son quota du jour plafonné par un réglage
(``_triage``, ``calls_today``) : une lecture à la fois par app. Le lot, ce qu'elle a déjà dit de cette app et les
consignes de son projet sont cités (sections « app_signals » et « app_consignes »). Son verdict
(``forge_signals_done``) dit ce qu'elle dira (une trouvaille, que ``prompt.py`` lui fait dire), ce qu'elle garde en
tête (une pensée), ou rien ; le lot quitte la file. ``told_to`` : à qui elle dirait ce qu'une app trouve.

Ces contributions s'inscrivent sur ``FORGE`` à l'import du module, que ``prompt.py`` fait entre ses trouvailles et sa
section « apps », à la place qu'elles avaient dans l'ancien fichier unique : ``forge_signals_done`` reste inscrit
avant les outils ``forge_*``. Il lit du paquet l'état, les tours et les aides partagées, et rien de ``prompt.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import forge as c
from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult, Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.forge import (
    APPS_BUNDLE,
    FORGE,
    App,
    ForgeState,
    Queued,
    concerns,
    params,
    rules_of,
    sifting_app,
    signal_draft,
)
from mika.vocab.days import ago_words
from mika.vocab.episodes import Kind, task_target
from mika.vocab.phrasebook import phrase

# ── Lire la file de signaux d'une app : une tâche, un verdict (ADR 0105) ──

TRIAGE_BUNDLE = "forge_signals"
FORGE.bundle(TRIAGE_BUNDLE, phrase("forge.triage.bundle"))


def told_to(frame: Frame, app: App) -> tuple[tuple[str, ...], int]:
    """À qui elle dirait ce qu'une app trouve : la personne de son projet (à son niveau), sinon qui s'occupe d'elle."""
    about, level = concerns(frame, app)
    if about:
        return about, level
    owners = frame.get(identity_c.OWNERS)
    return (tuple(owners[:1]), 0) if owners else ((), 0)


def _who(frame: Frame, about: tuple[str, ...]) -> str:
    return identity_c.keeper_name(frame, about[0] if about else "", quoted=True)


def calls_today(app: App, now: int) -> int:
    return sum(1 for t in app.calls_at if now - t < DAY)


@FORGE.propose(kinds=[Kind.TASK], reasons={c.TRIAGE: (0.0, 12.0)},
               reads=[projects_c.LIVE, identity_c.OWNERS, identity_c.IDENTITY])
def _triage(s: ForgeState, frame: Frame) -> list[Candidate]:
    """Une app dont la file attend : une tâche pour lire un lot (autant que l'app le déclare), avec la consigne de
    l'app, sous son quota du jour (plafonné par un réglage) — une lecture à la fois par app."""
    p = params(frame.env.params_of("forge", frame.root))
    reading = {app for app, _, _ in s.sifting.values()}
    out = []
    for name, app in sorted(s.apps.items()):
        if not app.queue or not app.enabled or app.broken or app.held or name in reading:
            continue
        r = rules_of(app)
        if calls_today(app, frame.now) >= min(r.quota, p.signal_calls_max):
            continue
        about, _ = told_to(frame, app)
        brief = phrase("forge.triage.brief", app=app.title, count=min(len(app.queue), r.per_call),
                       who=_who(frame, about))
        if r.instructions:
            brief += " " + phrase("forge.triage.instructions", instructions=r.instructions)
        out.append(Candidate(Kind.TASK, task_target("forge", name), c.TRIAGE, p.triage_evidence,
                             resources=frozenset({f"forge-triage:{name}"}),
                             args=FrozenDict({"bundles": f"{TRIAGE_BUNDLE},{APPS_BUNDLE}.{name},memory,mcp.web",
                                              "brief:forge": brief})))
    return out


def _batch(s: ForgeState, frame: Frame) -> tuple[str, App | None, tuple[Queued, ...]]:
    """L'app et le lot que lit la tâche en cours."""
    ep = frame.episode
    name = sifting_app(ep.target) if ep is not None and ep.kind == Kind.TASK else ""
    app = s.apps.get(name) if name else None
    if app is None:
        return name, None, ()
    sift = s.sifting.get(ep.id) if ep is not None else None
    if sift is not None:
        wanted = set(sift[1])
        return name, app, tuple(q for q in app.queue if q.seq in wanted)
    return name, app, app.queue[:rules_of(app).per_call]


def _app_project(frame: Frame, app: App | None) -> Any:
    """La vue du projet d'une app (vide : une app sans projet, ou un projet qui n'est plus en vie)."""
    if app is None or not app.project:
        return None
    return next((v for v in frame.get(projects_c.LIVE) if v.id == app.project), None)


@FORGE.enricher("signals", episodes=[Kind.TASK], deadline_ms=1000)
async def _signal_texts(s: ForgeState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Les textes du lot, de ce qu'elle a dit de cette app la dernière fois, et des consignes de son projet."""
    store = ports.get("store")
    name, app, batch = _batch(s, frame)
    refs = [q.summary_ref for q in batch if q.summary_ref]
    last = s.news.get(name) if name else None
    if last is not None and last.summary_ref:
        refs.append(last.summary_ref)
    refs += [ref for ref, _at, _level in (s.said.get(name, ()) if name else ()) if ref]
    project = _app_project(frame, app)
    if project is not None:
        refs += [r for r in project.instructions if r]
    return {"texts": store.content(refs)} if store is not None and refs else None


@FORGE.section("app_signals", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=95,
               title=phrase("forge.triage.title"), untrusted=True)
def _signals_section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que l'app a mis dans sa file, le lot qu'elle lit : cité — ce sont des données venues d'ailleurs (un titre
    d'article peut dire n'importe quoi), jamais des consignes. Et ce qu'elle a déjà dit de cette app : un signal
    peut revenir (un flux republie, une base repart de zéro) — on ne redit pas la même nouvelle (sonde du
    2026-10-13 : les mêmes quatre articles redits une heure et demie après)."""
    name, app, batch = _batch(s, frame)
    if app is None or not batch:
        return None
    texts = (enrich.get("signals") or {}).get("texts") or {}
    lines = [phrase("forge.triage.line", n=i, ago=ago_words(frame.now - q.at),
                    pertinence=f"{q.pertinence:.1f}".replace(".", ","), text=texts.get(q.summary_ref, "…"))
             for i, q in enumerate(batch, start=1)]
    rest = len(app.queue) - len(batch)
    if rest > 0:
        lines.append(phrase("forge.triage.rest", count=rest))
    if app.dropped:
        lines.append(phrase("forge.triage.dropped", count=app.dropped))
    levels = [q.level for q in batch]
    for ref, at, level in s.said.get(name, ()):
        if texts.get(ref):
            lines.append(phrase("forge.triage.told", ago=ago_words(frame.now - at), text=texts[ref]))
            levels.append(level)
    last = s.news.get(name)
    if last is not None and not last.told and texts.get(last.summary_ref):
        lines.append(phrase("forge.triage.pending", ago=ago_words(frame.now - last.at), text=texts[last.summary_ref]))
        levels.append(last.level)
    return SectionBody("\n".join(lines), level=max(levels))


@FORGE.section("app_consignes", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=94,
               title=phrase("forge.triage.consignes_title"), reads=[projects_c.LIVE])
def _consignes_section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Les dernières consignes du projet de l'app dont elle lit la file : ce que qui suit le projet a demandé vaut
    aussi pour ce qu'elle en dit (« écarte les articles hors sujet », sonde du 2026-10-13)."""
    _, app, batch = _batch(s, frame)
    project = _app_project(frame, app) if batch else None
    texts = (enrich.get("signals") or {}).get("texts") or {}
    said = [texts[r] for r in (project.instructions if project is not None else ()) if texts.get(r)]
    if not said:
        return None
    return SectionBody(phrase("forge.triage.consignes") + "\n" + "\n".join(f"- {t}" for t in said),
                       level=project.written, provenance=(f"project:{project.id}",))


class SignalsDoneArgs(BaseModel):
    tell: str = Field(default="", max_length=1500, description=phrase("forge.triage.tell"))
    keep: str = Field(default="", max_length=500, description=phrase("forge.triage.keep"))
    urgent: bool = Field(default=False, description=phrase("forge.triage.urgent"))


@FORGE.tool("forge_signals_done", acts=True, description=phrase("forge.triage.description"),
            label=phrase("forge.triage.label"), args=SignalsDoneArgs,
            bundle=TRIAGE_BUNDLE, episodes=[Kind.TASK], max_calls_per_episode=1, ends_loop=True)
async def forge_signals_done(args: SignalsDoneArgs, ctx: Any) -> Any:
    """Son verdict sur le lot lu : ce qu'elle dira (une trouvaille à dire, de son initiative ou à la prochaine
    occasion), ce qu'elle garde en tête (une pensée), ou rien — le lot quitte la file."""
    s: ForgeState = ctx.frame.state("forge")
    name, app, batch = _batch(s, ctx.frame)
    if app is None:
        return ToolResult(ok=False, content=phrase("forge.triage.nothing"))
    about, level = told_to(ctx.frame, app)
    level = max([level, *(q.level for q in batch)])
    tell, keep = args.tell.strip(), args.keep.strip()
    drafts: list[Any] = [c.JUDGED.draft(app=name, seqs=tuple(q.seq for q in batch),
                                        tell=Content.of(tell, level=level) if tell and about else None,
                                        keep=Content.of(keep, level=level) if keep else None, about=about,
                                        sensitivity=level, urgent=bool(args.urgent and tell and about))]
    if keep:  # ce qu'elle garde en tête : une pensée, comme un signal qui lui reste
        strongest = max(batch, key=lambda q: q.pertinence) if batch else None
        drafts.append(signal_draft(name, phrase("forge.signal.kept", app=app.title, kept=keep), 0.6,
                                   strongest.emotion if strongest is not None else "", about=about,
                                   sensitivity=level))
    await ctx.emit(*drafts)
    if tell and about:
        return ToolResult(content=phrase("forge.triage.done_tell", who=_who(ctx.frame, about)), proof=False)
    if keep:
        return ToolResult(content=phrase("forge.triage.done_quiet"), proof=False)
    return ToolResult(content=phrase("forge.triage.done_nothing"), proof=False)
