"""Décisions : pourquoi elle parle ou se tait. L'arbitre en direct, ses choix
passés (avec le détail de chaque ligne), ses épisodes, ses échéances."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector.pages.home import KINDS, OUTCOMES, outcome_badge
from mika.inspector.pages.tabs import TABS
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import (
    Badge,
    Chart,
    Column,
    Fields,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    When,
    read_params,
)
from mika.runtime.boundary import Failed, call

EPISODES_PAGE = 50


def _parts(parts: Any) -> str:
    return "\n".join(f"{owner} · {reason}  {value:+.2f}" for owner, reason, value in parts) or "—"


def waterfall(r: Any) -> Table:
    """Le score d'une ligne pas à pas : chaque preuve, chaque modulateur, l'attente,
    puis le seuil du type d'épisode — et le cumul à chaque étape."""
    steps: list[tuple[str, str, float]] = [("preuve", f"{owner} · {reason}", value) for owner, reason, value in r.parts]
    shifts = tuple(getattr(r, "shifts", ()) or ())
    if shifts:
        steps += [("modulateur", owner, value) for owner, value in shifts]
    elif r.shift:
        steps.append(("modulateur", "tous", r.shift))
    aging = getattr(r, "aging", 0.0)
    if aging:
        steps.append(("attente", "ce qu'a ajouté l'attente de la ligne", aging))
    threshold = getattr(r, "threshold", 0.0)
    if threshold:
        steps.append(("seuil", f"seuil de la sorte « {KINDS.get(r.kind, r.kind)} »", -threshold))
    total = 0.0
    rows = []
    for what, why, value in steps:
        total += value
        rows.append(Row((Badge(what, "info" if what == "preuve" else "muted"), why,
                         Text(f"{value:+.2f}", "num", "ok" if value > 0 else "danger" if value < 0 else ""),
                         Text(f"{total:+.2f}", "num"))))
    rows.append(Row((Badge("score", "ok" if r.score > 0 else "warn"), "log-odds finales",
                     "", Text(f"{r.score:+.2f}", "num", "ok" if r.score > 0 else "")), tone="muted"))
    if r.vetoes:
        rows.append(Row((Badge("veto", "danger"), ", ".join(f"{o} ({why})" for o, why in r.vetoes), "", "—"),
                        tone="danger"))
    drift = r.score - total
    caption = f"taux : {r.hazard * 3600:.3f} /h" + (f" · écart d'arrondi {drift:+.2f}" if abs(drift) > 0.05 else "")
    return Table((Column("étape", "fit"), "quoi", Column("apport", "num"), Column("cumul", "num")), tuple(rows),
                 title="Du signal au score", caption=caption)


def _row_detail(r: Any) -> list[Any]:
    return [waterfall(r)]


@TABS.tab("decisions.maintenant", title="Maintenant")
async def live(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    rows = kernel.arbiter.rows(kernel.mind.frame())
    policy = kernel.registry.arbitration
    table = Table(
        ("ligne", Column("preuves", hint="log-odds par faculté et raison"), Column("décalage", "num"),
         Column("seuil", "num"), Column("score", "num"), Column("taux /h", "num"), "vetos"),
        tuple(Row((f"{KINDS.get(r.kind, r.kind)} → {r.target}", Text(_parts(r.parts), "mono"), round(r.shift, 2),
                   round(getattr(r, "threshold", 0.0), 2), Text(f"{r.score:+.2f}", "num",
                                                                     "ok" if r.score > 0 else ""),
                   round(r.hazard * 3600, 3), Badge(", ".join(o for o, _ in r.vetoes), "danger") if r.vetoes else "—"),
                  tone="ok" if r.hazard > 0 and not r.vetoes else "", detail=tuple(_row_detail(r))) for r in rows),
        title="La table de l'arbitre, maintenant",
        empty="Aucune ligne : personne de présent et rien qui pousse à agir.",
        caption="Les preuves se cumulent par type d'épisode et cible ; un tirage à taux λ·σ(score) décide.")
    policy_fields = Fields(tuple((f"seuil · {KINDS.get(k, k)}", v) for k, v in sorted(policy.thresholds.items()))
                           + tuple((f"taux max · {KINDS.get(k, k)}", f"{v * 3600:.2f} /h")
                                   for k, v in sorted(policy.max_rates.items())), title="Politique")
    anomalies = list(getattr(kernel.arbiter, "anomalies", []))[-10:]
    return [table, policy_fields] + [Note(a, "warn") for a in anomalies]


@TABS.tab("decisions.selections", title="Ses choix")
async def selections(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    before = ctx.int_param("avant", 0) or None
    chosen = ctx.events(["kernel.selected"], 40, before=before)
    rows = []
    for e in chosen:
        d = e.data
        bound, total = getattr(d, "bound", 0.0), getattr(d, "total", 0.0)
        detail: list[Any] = []
        if bound and total:
            detail.append(Note(f"Tirage {d.draw:.3f} × borne {bound * 3600:.3f} /h = {d.draw * bound * 3600:.3f} /h, "
                               f"sous l'intensité totale Σλ = {total * 3600:.3f} /h : occurrence acceptée.", "info"))
        detail.append(Table(("ligne", Column("score", "num"), Column("taux /h", "num"), "preuves"), tuple(
            Row((f"{KINDS.get(r.kind, r.kind)} → {r.target}", round(r.score, 2), round(r.hazard * 3600, 3),
                 Text(_parts(r.parts), "mono")), tone="ok" if f"{r.kind}:{r.target}" in d.fired else "",
                detail=(waterfall(r),)) for r in d.rows),
            title="Les lignes au moment du choix"))
        rows.append(Row((When(e.at), ", ".join(d.fired) or "—", round(d.draw, 3),
                         Text(f"{total * 3600:.2f} / {bound * 3600:.2f}", "num") if bound else "—",
                         getattr(d, "candidates", 0) or len(d.rows)), href=Ref("event", str(e.seq), ""),
                        detail=tuple(detail)))
    pager = Pager(older=(("avant", str(chosen[-1].seq)),)) if len(chosen) == 40 else None
    return [Table((Column("quand", "fit"), "choisi", Column("tirage", "num"),
                   Column("Σλ / borne (/h)", "num", hint="l'intensité totale et la borne de l'amincissement"),
                   Column("lignes", "num")), tuple(rows),
                  title="Ses dernières initiatives décidées", empty="Elle n'a encore rien décidé d'elle-même.",
                  pager=pager)]


EPISODE_PARAMS = (
    Param("sorte", "sorte", "select", tuple(KINDS.items())),
    Param("issue", "issue", "select", tuple((k, v[0]) for k, v in OUTCOMES.items())),
    Param("cible", "vers", "search"),
)


@TABS.tab("decisions.episodes", title="Épisodes")
async def episodes(ui: Any, request: Request) -> Any:
    ctx = ui.inspection.context(request.query_params)
    values, notes = read_params(EPISODE_PARAMS, request.query_params)
    before = ctx.int_param("avant", 0) or None
    where = ("kind", values["sorte"]) if values["sorte"] else ("outcome", values["issue"]) if values["issue"] else \
        ("target", values["cible"]) if values["cible"] else None
    batch = ctx.events([rt.EPISODE_ENDED], 400 if where else EPISODES_PAGE, where=where, before=before)
    shown = [e for e in batch if (not values["issue"] or e.data.outcome == values["issue"])
             and (not values["cible"] or (e.data.target or "") == values["cible"])][:EPISODES_PAGE]
    rows = tuple(Row((When(e.at), KINDS.get(e.data.kind, e.data.kind), e.data.target or "—",
                      outcome_badge(e.data.outcome), Text((e.data.detail or e.data.guard or "")[:200], "muted")),
                     href=Ref("episode", e.correlation, ""),
                     tone="danger" if e.data.outcome in ("failed", "timeout") else "") for e in shown)
    pager = Pager(older=(("avant", str(batch[-1].seq)),)) if len(batch) >= EPISODES_PAGE and batch else None
    now = ui.now()
    recent = ctx.events([rt.EPISODE_ENDED], 1000)
    per_day: Counter[str] = Counter()
    stamps: dict[str, int] = {}
    for e in recent:
        if now - e.at > 14 * DAY:
            continue
        day = datetime.fromtimestamp(e.at / US, ui.tz).strftime("%Y-%m-%d")
        per_day[day] += 1
        stamps[day] = min(stamps.get(day, e.at), e.at)
    chart = Chart((Series("épisodes", tuple((stamps[d], float(n)) for d, n in sorted(per_day.items())), 1),),
                  kind="bars", title="Épisodes par jour (14 jours)", table=False, since=now - 14 * DAY,
                  until=now) if per_day else None
    counts = Counter(e.data.outcome for e in recent if now - e.at <= DAY)
    stats = Stats(tuple(Stat(OUTCOMES.get(k, (k, ""))[0], n, "dernières 24 h", OUTCOMES.get(k, ("", ""))[1])
                        for k, n in counts.most_common()))
    out: list[Any] = [Note(n, "warn") for n in notes]
    if counts:
        out.append(stats)
    if chart:
        out.append(chart)
    out.append(Table((Column("quand", "fit"), "épisode", "vers", "issue", "détail"), rows, title="Épisodes",
                     empty="Aucun épisode ne correspond." if where else "Aucun épisode encore.", pager=pager,
                     filters=("sorte", "issue", "cible")))
    return {"blocks": out, "filters": EPISODE_PARAMS, "values": values}


@TABS.tab("decisions.echeances", title="Échéances")
async def schedule(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    sched = kernel.scheduler
    frame = kernel.mind.frame()
    rows = []
    for spec in sched.specs:
        due: Any = call(sched.instances[spec.name].next_due, frame.root.slices.get(spec.owner), frame,
                        sched.last_run(spec.name), label=f"échéance de {spec.name}")
        nd = None if isinstance(due, Failed) else due
        failing = sched.consecutive.get(spec.name, 0)
        rows.append((nd if nd is not None else 1 << 62, Row((
            spec.name, spec.owner, spec.lane, When(nd) if nd else Text("rien de prévu", "muted"),
            When(sched.last_run(spec.name) or 0) if sched.last_run(spec.name) else "—",
            sched.runs.get(spec.name, 0), Badge(f"{failing} d'affilée", "danger") if failing else "—"),
            tone="danger" if failing >= 3 else "muted" if nd is None else "")))
    rows.sort(key=lambda x: x[0])
    running = set(sched.running())
    return [Stats((Stat("Processus", len(sched.specs)), Stat("En cours", len(running), ", ".join(sorted(running)))),),
            Table(("processus", "faculté", "voie", "prochaine fois", "dernière fois", Column("passages", "num"),
                   "échecs"), tuple(r for _, r in rows), title="Ce qui tournera, et quand")]
