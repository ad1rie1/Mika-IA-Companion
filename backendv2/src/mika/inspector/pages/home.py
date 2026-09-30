"""Le tableau de bord : ce qui attend ton attention, son état en ce moment, sa
journée en courbes, et ce qu'elle a fait aujourd'hui."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector.pages.system import backup_state
from mika.inspector.pages.tabs import TABS
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import (
    Badge,
    Chart,
    Column,
    Disclosure,
    Grid,
    Note,
    Pager,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    When,
)
from mika.runtime import health

OUTCOMES = {"done": ("répondu", "ok"), "abstained": ("s'est tue", "muted"), "superseded": ("supplanté", "warn"),
            "timeout": ("trop long", "danger"), "failed": ("échec", "danger"), "preempted": ("interrompu", "warn"),
            "interrupted": ("interrompu", "warn"), "cancelled": ("annulé", "muted")}
KINDS = {"REPLY": "réponse", "INITIATIVE": "initiative", "STEP": "pas de travail", "MURMUR": "murmure",
         "JOURNAL": "journal", "DREAM": "rêve", "NARRATIVE": "récit"}
#: les derniers épisodes, par page
EPISODES_PAGE = 20
#: une courbe mêle au plus tant de séries (au-delà : une autre courbe, jamais une série perdue)
SERIES_PER_CHART = 4


def outcome_badge(outcome: str) -> Badge:
    text, tone = OUTCOMES.get(outcome, (outcome, ""))
    return Badge(text, tone)


def _local(href: str, text: str) -> Ref:
    """Un lien interne déjà construit (``/inspecteur/…``) : passé tel quel au rendu."""
    return Ref("local", href, text)


@TABS.tab("accueil.a_traiter", title="À traiter",
          description="Chaque cadre mène à la page où décider. Vide : rien n'attend.")
async def attention(ui: Any, request: Request) -> list[Any]:
    report = health.report(ui.kernel)
    out: list[Any] = []
    items = ui.attention_items()
    gateway = ui.kernel.deps.gateway
    cards = [Stat(i["label"], i["count"], i["hint"] or "à regarder", "warn", _local(i["href"], i["label"]))
             for i in items]
    if not getattr(gateway, "configured", gateway is not None):
        cards.insert(0, Stat("Modèles", "aucun", "chaque tour échoue : déclare un fournisseur", "danger",
                             _local("/inspecteur/reglages/fournisseurs", "Modèles")))
    sched = ui.kernel.scheduler
    failing = [s.name for s in sched.specs if sched.consecutive.get(s.name, 0) >= 3]
    if failing:
        cards.append(Stat("Processus en échec", len(failing), ", ".join(failing)[:90], "danger",
                          _local("/inspecteur/systeme/processus", "Processus")))
    anomalies = len(getattr(ui.kernel.mind, "anomalies", ()) or ())
    if anomalies:
        cards.append(Stat("Anomalies", anomalies, "évaluations ou réductions qui ont échoué", "warn",
                          _local("/inspecteur/systeme/anomalies", "Anomalies")))
    tone, text = backup_state(ui)
    if tone in ("warn", "danger"):
        cards.append(Stat("Sauvegarde", "à faire" if tone == "warn" else "en échec", text, tone,
                          _local("/inspecteur/systeme/stockage", "Stockage")))
    if cards:
        out.append(Stats(tuple(cards)))
    for c in report.checks:
        if c.state != health.OK:
            out.append(Note(c.summary, "danger" if c.state == health.KO else "warn", title=f"Santé · {c.name}"))
    if not cards and len(out) == 0:
        out.append(Note("Rien ne demande ton attention.", "ok", title="Tout va bien"))
    return out


@TABS.tab("accueil.maintenant", title="En ce moment",
          description="Son état, ce qui tourne et ce qui attend, tels qu'ils sont à cet instant.")
async def now_tab(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    cards = []
    for spec, v in ui.inspection.vitals():
        cards.append(Stat(spec.label, v.text, v.hint[:90] if v.hint else "", v.tone or "",
                          v.href if v.href else None))
    lanes = kernel.lanes
    waiting = {lane: lanes.pending(lane) for lane in lanes.capacities}
    open_ = frame.state("runtime").open
    cards += [
        Stat("Épisodes en cours", len(open_), f"{sum(waiting.values())} en attente · " + (
             ", ".join(KINDS.get(o.kind, o.kind) for o in open_.values())[:80] or "aucun travail en cours"),
             "info" if open_ else "", _local("/inspecteur/decisions/en_cours", "en cours")),
    ]
    return [Stats(tuple(cards))]


@TABS.tab("accueil.courbes", title="Sa journée",
          description="Les dernières 24 heures, une échelle par courbe.")
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
        for start in range(0, len(specs), SERIES_PER_CHART):
            lines = []
            for i, (key, spec) in enumerate(specs[start:start + SERIES_PER_CHART]):
                pts = tuple(sampler(key, since, now, 144))
                if pts:
                    lines.append(Series(spec.label, pts, i + 1))
            if lines:
                y = (lo, hi) if lo is not None and hi is not None else None
                charts.append(Chart(tuple(lines), title=" · ".join(s.label for s in lines), unit=unit, y=y,
                                    zero=0.0 if lo is not None and lo < 0 < (hi or 0) else None, since=since,
                                    until=now))
    return [Disclosure("Consulter les courbes", (Grid(tuple(charts)),))] if charts else [
        Note("Pas encore de mesure sur les dernières 24 heures.", "muted")]


@TABS.tab("accueil.aujourdhui", title="Aujourd'hui",
          description="Ce qu'elle a fait depuis minuit, ce que ça a coûté, et ses derniers épisodes.")
async def today(ui: Any, request: Request) -> list[Any]:
    now = ui.now()
    local = datetime.fromtimestamp(now / US, ui.tz)
    midnight = int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * US)
    ctx = ui.inspection.context(request.query_params)
    day = [e for e in ctx.events([rt.EPISODE_ENDED], 1000) if e.at >= midnight]
    by_outcome = Counter(e.data.outcome for e in day)
    by_kind = Counter(e.data.kind for e in day)
    cards = [Stat("Épisodes", len(day), " · ".join(f"{KINDS.get(k, k)} {n}" for k, n in by_kind.most_common(4))
                  or "aucun")]
    for outcome, n in by_outcome.most_common():
        text, tone = OUTCOMES.get(outcome, (outcome, ""))
        cards.append(Stat(text.capitalize(), n, "depuis minuit", tone if tone in ("warn", "danger") else ""))
    calls = ui.deps.calls
    if calls is not None:
        spent = calls.usage(midnight, by="role")
        cost = sum(u.cost_usd for u in spent)
        failed = sum(u.failures for u in spent)
        cards.append(Stat("Appels de modèle", sum(u.calls for u in spent), f"{cost:.3f} $ · {failed} échec(s)",
                          "danger" if failed else "", _local("/inspecteur/systeme/appels", "coûts")))
    before = ctx.int_param("avant", 0) or None
    ended = ctx.events([rt.EPISODE_ENDED], EPISODES_PAGE, before=before)
    rows = tuple(Row((When(e.at), KINDS.get(e.data.kind, e.data.kind), e.data.target or "—",
                      outcome_badge(e.data.outcome), Text((e.data.detail or "")[:160], "muted")),
                     href=Ref("episode", e.correlation, ""),
                     tone="danger" if e.data.outcome in ("failed", "timeout") else "") for e in ended)
    pager = Pager(older=(("avant", str(ended[-1].seq)),)) if len(ended) == EPISODES_PAGE else Pager()
    scope = [Note("Ces indicateurs portent sur les 1 000 derniers épisodes : la journée peut en contenir davantage.",
                  "info")] if len(day) == 1000 else []
    return [Stats(tuple(cards)), *scope,
            Table((Column("quand", "fit"), "épisode", "vers", "issue", "détail"), rows, title="Derniers épisodes",
                  empty="aucun épisode encore", pager=pager)]
