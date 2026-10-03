"""Le tableau de bord : ce qui attend ton attention, son état en ce moment, sa
journée en courbes, et ce qu'elle a fait aujourd'hui."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector import names
from mika.inspector.names import KINDS, OUTCOMES
from mika.inspector.pages.system import backup_state
from mika.inspector.pages.tabs import TABS
from mika.kernel.clock import DAY, MINUTE, US
from mika.kernel.forms import show_duration
from mika.kernel.inspect import (
    Badge,
    Chart,
    Column,
    Disclosure,
    Grid,
    Note,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    When,
    money_fr,
)
from mika.runtime import health
from mika.vocab.episodes import Kind

__all__ = ["KINDS", "OUTCOMES", "outcome_badge"]

#: les derniers épisodes, par page
EPISODES_PAGE = 20
#: une courbe mêle au plus tant de séries (au-delà : une autre courbe, jamais une série perdue)
SERIES_PER_CHART = 4


def outcome_badge(outcome: str, kind: str | None = None) -> Badge:
    text, tone = names.outcome(outcome, kind)
    return Badge(text, tone)


def episode_row(ui: Any, e: Any) -> Row:
    """Une ligne d'épisode terminé (tableau de bord, Décisions › Épisodes) : quand, quoi, vers qui (un
    nom), l'issue, le détail en mots — la ligne mène à l'épisode."""
    return Row((When(e.at), names.kind(e.data.kind), ui.names.who_cell(e.data.target),
                outcome_badge(e.data.outcome, e.data.kind),
                Text(names.detail(e.data.detail or e.data.guard or "")[:200], "muted")),
               href=Ref("episode", e.correlation, ""),
               tone="danger" if e.data.outcome in ("failed", "timeout") else "")


def _local(href: str, text: str) -> Ref:
    """Un lien interne déjà construit (``/inspecteur/…``) : passé tel quel au rendu."""
    return Ref("local", href, text)


#: les épisodes (Décisions › Épisodes)
EPISODES_HREF = "/inspecteur/decisions/episodes"
#: les réponses relues pour savoir si elles échouent (les plus récentes d'abord)
REPLIES_SCANNED = 200
_REPLY = str(Kind.REPLY)


def failed_replies(ui: Any, ctx: Any) -> tuple[int, int, str] | None:
    """Ses réponses échouent : combien d'affilée depuis la dernière qui a abouti (dans les dernières 24 h), depuis
    quand, et pourquoi la plus récente a échoué, en mots. ``None`` : la dernière réponse a abouti (ou elle s'est
    tue), ou aucune en 24 h. Une configuration juste avec un fournisseur injoignable ne se voyait qu'au fil des
    « Derniers épisodes »."""
    now = ui.now()
    count, since, why = 0, 0, ""
    for e in ctx.events([rt.EPISODE_ENDED], REPLIES_SCANNED, where=("kind", _REPLY)):
        if now - e.at > DAY or e.data.outcome not in ("failed", "timeout"):
            break
        count, since = count + 1, e.at
        why = why or names.detail(e.data.detail or e.data.outcome)
    return (count, since, why or "échec") if count else None


def render_ago(us: int) -> str:
    """Une durée passée, à la minute (« 12 min », « 3 h 5 min ») — « moins d'une minute » en dessous."""
    if us < MINUTE:
        return "moins d'une minute"
    return show_duration(us - us % MINUTE)


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
        cards.insert(0, Stat("Modèles", "aucun", "rien ne sert « répondre » : chaque tour échoue — déclare un "
                             "fournisseur", "danger", _local("/inspecteur/reglages/fournisseurs", "Modèles")))
    else:
        failed = failed_replies(ui, ui.inspection.context(request.query_params))
        if failed is not None:
            count, since, why = failed
            cards.insert(0, Stat("Réponses en échec", count, f"depuis {render_ago(ui.now() - since)} — {why}"[:90],
                                 "danger", _local(f"{EPISODES_HREF}?sorte=reply", "Réponses en échec")))
    sched = ui.kernel.scheduler
    failing = [ui.names.process(s.name) for s in sched.specs if sched.consecutive.get(s.name, 0) >= 3]
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
             ", ".join(names.kind(o.kind) for o in open_.values())[:80] or "aucun travail en cours"),
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
    cards = [Stat("Épisodes", len(day), " · ".join(f"{names.kind(k)} {n}" for k, n in by_kind.most_common(4))
                  or "aucun")]
    for outcome, n in by_outcome.most_common():
        text, tone = names.outcome(outcome)
        cards.append(Stat(text.capitalize(), n, "depuis minuit", tone if tone in ("warn", "danger") else ""))
    calls = ui.deps.calls
    if calls is not None:
        spent = calls.usage(midnight, by="role")
        cost = sum(u.cost_usd for u in spent)
        failed = sum(u.failures for u in spent)
        cards.append(Stat("Appels de modèle", sum(u.calls for u in spent), f"{money_fr(cost)} · {failed} échec(s)",
                          "danger" if failed else "", _local("/inspecteur/systeme/appels", "coûts")))
    ended, pager = ctx.older([rt.EPISODE_ENDED], EPISODES_PAGE)
    rows = tuple(episode_row(ui, e) for e in ended)
    scope = [Note("Ces indicateurs portent sur les 1 000 derniers épisodes : la journée peut en contenir davantage.",
                  "info")] if len(day) == 1000 else []
    return [Stats(tuple(cards)), *scope,
            Table((Column("quand", "fit"), "épisode", "vers", "issue", "détail"), rows, title="Derniers épisodes",
                  empty="aucun épisode encore", pager=pager)]
