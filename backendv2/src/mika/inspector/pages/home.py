"""L'accueil : ce qui demande ton attention, ses courbes du jour, ce qui se
passe en ce moment."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector.pages.tabs import TABS
from mika.kernel.clock import DAY
from mika.kernel.inspect import Badge, Chart, Column, Note, Ref, Row, Series, Stat, Stats, Table, Text, When
from mika.runtime import health

OUTCOMES = {"done": ("répondu", "ok"), "abstained": ("s'est tue", "muted"), "superseded": ("supplanté", "warn"),
            "timeout": ("trop long", "danger"), "failed": ("échec", "danger"), "preempted": ("interrompu", "warn"),
            "interrupted": ("interrompu", "warn"), "cancelled": ("annulé", "muted")}
KINDS = {"REPLY": "réponse", "INITIATIVE": "initiative", "STEP": "pas de travail", "MURMUR": "murmure",
         "JOURNAL": "journal", "DREAM": "rêve", "NARRATIVE": "récit"}


def outcome_badge(outcome: str) -> Badge:
    text, tone = OUTCOMES.get(outcome, (outcome, ""))
    return Badge(text, tone)


@TABS.tab("accueil.a_traiter", title="À traiter")
async def attention(ui: Any, request: Request) -> list[Any]:
    report = health.report(ui.kernel)
    out: list[Any] = []
    links = [(item["label"], item["badge"], item["href"]) for g in ui.nav("") for item in g["items"] if item["badge"]]
    if links:
        out.append(Stats(tuple(Stat(label, n, "à regarder", "warn", _local(href, label))
                               for label, n, href in links), title="À traiter"))
    problems = [c for c in report.checks if c.state != health.OK]
    for c in problems:
        out.append(Note(c.summary, "danger" if c.state == health.KO else "warn", title=f"Santé · {c.name}"))
    if not links and not problems:
        out.append(Note("Rien ne demande ton attention.", "ok", title="Tout va bien"))
    return out


def _local(href: str, text: str) -> Ref:
    """Un lien interne déjà construit (``/inspecteur/…``) : passé tel quel au rendu."""
    return Ref("local", href, text)


@TABS.tab("accueil.courbes", title="Sa journée")
async def curves(ui: Any, request: Request) -> list[Any]:
    sampler = ui.sampler
    now = ui.now()
    since = now - DAY
    if sampler is None:
        return [Note("Les courbes apparaîtront quand les mesures auront commencé.", "muted")]
    charts: list[Any] = []
    series = ui.kernel.registry.series
    groups: dict[tuple[float | None, float | None, str], list[Any]] = {}
    for key, spec in series.items():
        groups.setdefault((spec.lo, spec.hi, spec.unit), []).append((key, spec))
    for (lo, hi, unit), specs in groups.items():
        lines = []
        for i, (key, spec) in enumerate(specs[:4]):
            pts = tuple(sampler(key, since, now, 144))
            if pts:
                lines.append(Series(spec.label, pts, i + 1))
        if lines:
            y = (lo, hi) if lo is not None and hi is not None else None
            charts.append(Chart(tuple(lines), title=" · ".join(s.label for s in lines), unit=unit, y=y,
                                zero=0.0 if lo is not None and lo < 0 < (hi or 0) else None, since=since, until=now))
    return charts or [Note("Pas encore de mesure sur les dernières 24 heures.", "muted")]


@TABS.tab("accueil.maintenant", title="En ce moment")
async def now_tab(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    lanes = kernel.lanes
    waiting = {lane: lanes.pending(lane) for lane in lanes.capacities}
    running = kernel.scheduler.running()
    pending = len(frame.get(rt.PENDING_EFFECTS))
    stats = Stats((
        Stat("Journal", kernel.mind.head, f"{kernel.mind.root.slices['kernel'].boots} démarrage(s)"),
        Stat("En file", sum(waiting.values()), " · ".join(f"{k} {v}" for k, v in waiting.items()),
             "info" if sum(waiting.values()) else ""),
        Stat("Processus actifs", len(running), ", ".join(running)[:80] or "aucun"),
        Stat("À approuver", pending, "effets en attente", "warn" if pending else ""),
    ))
    ended = ui.inspection.context().events([rt.EPISODE_ENDED], 12)
    rows = tuple(Row((When(e.at), KINDS.get(e.data.kind, e.data.kind), e.data.target or "—",
                      outcome_badge(e.data.outcome), Text((e.data.detail or "")[:160], "muted")),
                     href=Ref("episode", e.correlation, "")) for e in ended)
    return [stats, Table((Column("quand", "fit"), "épisode", "vers", "issue", "détail"), rows,
                         title="Derniers épisodes", empty="aucun épisode encore")]
