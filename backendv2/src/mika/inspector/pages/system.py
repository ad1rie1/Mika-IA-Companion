"""Système : santé, appels de modèle, chronologie, état et faits,
contributions, journal d'exploitation, simulations, toutes les vues."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import quote

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector.pages.tabs import TABS
from mika.kernel.clock import DAY, US
from mika.kernel.facts import FactKey
from mika.kernel.inspect import (
    Badge,
    Chart,
    Code,
    Column,
    Disclosure,
    Fields,
    Note,
    Pager,
    Param,
    Prose,
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
from mika.runtime import health
from mika.runtime.boundary import Failed, call

STATE_TONES = {"ok": "ok", "degraded": "warn", "ko": "danger"}
REPORT_NAME = re.compile(r"^[\w.-]{1,120}\.(md|html|json|txt)$")
REPORT_MAX = 400_000


def _names(items: Any) -> str:
    return ", ".join(sorted(items)) or "—"


@TABS.tab("systeme.sante", title="Santé", badge=lambda ui: sum(
    1 for c in health.report(ui.kernel).checks if c.state != health.OK))
async def sante(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    report = health.report(kernel)
    checks = Table(("contrôle", "état", "résumé"), tuple(
        Row((c.name, Badge(c.state, STATE_TONES.get(c.state, "")), c.summary), tone=STATE_TONES.get(c.state, ""),
            detail=(Code("\n".join(c.detail)),) if c.detail else ()) for c in report.checks),
        title=f"État : {report.status} (phase {report.phase})")
    sched = kernel.scheduler
    running = set(sched.running())
    procs = Table(("processus", "faculté", "voie", Column("passages", "num"), Column("échecs", "num"),
                   Column("d'affilée", "num"), "dernier passage", "dernière erreur"), tuple(
        Row((s.name + (" · en cours" if s.name in running else ""), s.owner, s.lane, sched.runs.get(s.name, 0),
             sched.failures.get(s.name, 0), sched.consecutive.get(s.name, 0),
             When(sched.last_run(s.name) or 0) if sched.last_run(s.name) else "—",
             Text(sched.last_error.get(s.name, (0, ""))[1], "muted", clamp=160)),
            tone="danger" if sched.consecutive.get(s.name, 0) >= 3 else "") for s in sched.specs),
        title="Processus")
    lag = kernel.projections.lag()
    projs = Table(("projection", "niveau", Column("version", "num"), Column("retard", "num")), tuple(
        (p.name, str(p.tier), p.version, "dans la transaction" if str(p.tier).endswith("T0") else lag.get(p.name, 0))
        for p in sorted(kernel.registry.projectors.values(), key=lambda p: p.name)), title="Projections")
    blocks: list[Any] = [checks, procs, projs]
    if kernel.projections.quarantined:
        blocks.append(Table(("projection", "événement", "erreur"), tuple(
            (name, Ref("event", str(seq), str(seq)), Text(err, "muted", clamp=200))
            for name, seq, err in kernel.projections.quarantined[-50:]), title="Quarantaine"))
    slow = ui.inspection.slow()
    if slow:
        blocks.append(Table(("vue", Column("passages", "num"), Column("dernière (ms)", "num"),
                             Column("pire (ms)", "num")), tuple(
            (k, t.runs, t.last_us // 1000, t.max_us // 1000) for k, t in slow), title="Vues lentes"))
    blocks.append(Disclosure("Sonde publique (/health)", (Code(json.dumps(report.public(), indent=1)),)))
    return blocks


@TABS.tab("systeme.appels", title="Appels de modèle")
async def appels(ui: Any, request: Request) -> list[Any]:
    calls = ui.deps.calls
    now = ui.now()

    def day_of(at: int) -> str:
        return datetime.fromtimestamp(at / US, ui.tz).strftime("%Y-%m-%d")

    if calls is None:
        return [Note("Le registre des appels n'est pas branché : seuls les derniers appels en mémoire comptent.",
                     "muted")]
    days = calls.usage(now - 14 * DAY, by="day", day_of=day_of)
    roles = calls.usage(now - 7 * DAY, by="role")
    backends = calls.usage(now - 7 * DAY, by="backend")
    total_cost = sum(u.cost_usd for u in days)
    today = next((u for u in days if u.key == day_of(now)), None)
    out: list[Any] = [Stats((
        Stat("Aujourd'hui", today.calls if today else 0, f"{today.cost_usd:.3f} $" if today else "0 $"),
        Stat("14 jours", sum(u.calls for u in days), f"{total_cost:.2f} $"),
        Stat("Échecs (14 j)", sum(u.failures for u in days), "", "danger" if any(u.failures for u in days) else ""),
        Stat("Part du cache (7 j)", f"{_cache(roles):.0%}", "entrée lue depuis le cache"),
    ))]
    if days:
        stamp = {u.key: int(datetime.strptime(u.key, "%Y-%m-%d").replace(tzinfo=ui.tz).timestamp() * US)
                 for u in days}
        out.append(Chart((Series("coût", tuple((stamp[u.key], u.cost_usd) for u in days), 2),), kind="bars",
                         title="Coût par jour", unit="$"))

    def usage_table(rows: list[Any], label: str, title: str) -> Table:
        return Table((label, Column("appels", "num"), Column("échecs", "num"), Column("entrée", "num"),
                      Column("sortie", "num"), Column("cache lu", "num"), Column("part du cache", "num"),
                      Column("coût", "num"), Column("durée moy.", "num")), tuple(
            Row((u.key, u.calls, u.failures, u.input_tokens, u.output_tokens, u.cache_read, f"{u.cache_ratio:.0%}",
                 f"{u.cost_usd:.3f} $", f"{u.latency_avg_s:.1f} s"), tone="danger" if u.failures else "")
            for u in rows), title=title, empty="aucun appel")

    out += [usage_table(list(reversed(days)), "jour", "Par jour"), usage_table(roles, "rôle", "Par rôle (7 j)"),
            usage_table(backends, "fournisseur", "Par fournisseur (7 j)")]
    recent = calls.recent(100)
    out.append(Table((Column("quand", "fit"), "rôle", "fournisseur", "modèle", Column("attente", "num"),
                      Column("durée", "num"), Column("jetons", "num"), Column("coût", "num"), "issue"), tuple(
        Row((When(t.at), t.role, t.backend, Text(t.model, "mono"), f"{t.wait_us / 1e6:.1f} s",
             f"{t.latency_us / 1e6:.1f} s", f"{t.input_tokens} → {t.output_tokens}", f"{t.cost_usd:.4f} $",
             Badge(t.outcome, "ok" if t.outcome == "ok" else "danger")),
            href=Ref("episode", getattr(t, "correlation", "") or t.call_id.split("#")[0], "")) for t in recent),
        title="Derniers appels", empty="aucun appel"))
    return out


def _cache(rows: list[Any]) -> float:
    read = sum(u.cache_read for u in rows)
    total = sum(u.input_tokens + u.cache_read + u.cache_write for u in rows)
    return read / total if total else 0.0


TIMELINE_PARAMS = (Param("type", "type d'événement"), Param("correlation", "corrélation"))


@TABS.tab("systeme.chronologie", title="Chronologie")
async def chronologie(ui: Any, request: Request) -> Any:
    kernel = ui.kernel
    values, _ = read_params(TIMELINE_PARAMS, request.query_params)
    ctx = ui.inspection.context(request.query_params)
    before = ctx.int_param("avant", 0) or None
    kind = str(values["type"] or "")[:80]
    corr = str(values["correlation"] or "")[:160]
    clauses, params = [], []
    if kind:
        clauses.append("type LIKE ? ESCAPE '\\'")
        params.append(kind.replace("\\", "").replace("%", "").replace("_", "\\_") + "%")
    if corr:
        clauses.append("correlation=?")
        params.append(corr)
    if before:
        clauses.append("seq < ?")
        params.append(before)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    seqs = [int(r[0]) for r in kernel.mind.store.query_mind(
        f"SELECT seq FROM events {where} ORDER BY seq DESC LIMIT 100", tuple(params))]
    events = sorted((ui.decode(s) for s in kernel.mind.store.get_events(seqs)), key=lambda e: -e.seq)
    rows = tuple(Row((Ref("event", str(e.seq), str(e.seq)), When(e.at), Text(e.type.name, "mono"),
                      Ref("episode", e.correlation, e.correlation[:28]), Text(ui.show(e, 600), "mono", clamp=160)))
                 for e in events)
    pager = Pager(older=(("avant", str(events[-1].seq)),)) if len(events) == 100 else None
    return {"blocks": [Table((Column("seq", "fit"), Column("quand", "fit"), "type", "corrélation", "données"), rows,
                             title="Le journal", empty="Rien ne correspond.", pager=pager)],
            "filters": TIMELINE_PARAMS, "values": values}


@TABS.tab("systeme.etat", title="État et faits")
async def etat(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    root = kernel.mind.root
    rows = []
    for name, spec in sorted(kernel.registry.providers.items()):
        if isinstance(spec.key, FactKey):
            got = call(frame.get, spec.key, label=f"fait {name}")
            value = f"(erreur : {got.error!r})" if isinstance(got, Failed) else repr(got)
        else:
            value = "famille : dépend de son argument"
        rows.append((Text(name, "mono"), spec.owner, Text(getattr(spec.key, "doc", ""), "muted"),
                     Text(value[:600], "mono", clamp=200)))
    tainted = dict(root.tainted.items())
    out: list[Any] = []
    if tainted:
        out.append(Note("Tranches corrompues : " + ", ".join(f"{o} (seq {s})" for o, s in tainted.items()),
                        "danger"))
    out.append(Table(("fait", "fourni par", "sens", "valeur"), tuple(rows), title="Faits (lus maintenant)"))
    out.append(Disclosure("Tranches", tuple(
        Disclosure(f"{owner} · modifiée au seq {root.changed.get(owner, 0)}", (Code(repr(root.slices[owner])[:8000]),))
        for owner in root.slices)))
    return out


@TABS.tab("systeme.contributions", title="Contributions")
async def contributions(ui: Any, request: Request) -> list[Any]:
    reg = ui.kernel.registry
    readers: dict[str, set[str]] = defaultdict(set)
    for f in reg.faculties.values():
        for s in [*f.reducers, *f.facts, *f.sections, *f.enrichers, *f.proposers, *f.modulators, *f.processes,
                  *f.appraisals]:
            for r in getattr(s, "reads", ()):
                readers[r].add(f.name)
    out: list[Any] = [Note("Ce que chaque faculté apporte, lu dans le registre. Elles ne se connaissent pas : elles "
                           "lisent les faits et les événements publics des autres.", "muted")]
    for f in reg.faculties.values():
        own = set(f.events)
        pairs = [
            ("publie", _names(n for n, t in f.events.items() if t.public)),
            ("écoute", _names({t.name for s in f.reducers for t in s.types if t.name not in own}
                              | {f"forme {sh.__name__}" for s in f.reducers for sh in s.shapes})),
            ("fournit", "\n".join(f"{s.key.name} → {_names(readers.get(s.key.name, set()) - {f.name})}"
                                  for s in f.facts) or "—"),
            ("sections", "\n".join(f"{s.key} ({s.zone.value})" for s in f.sections) or "—"),
            ("preuves", "\n".join(", ".join(f"{r} [{lo:g} ; {hi:g}]" for r, (lo, hi) in s.reasons.items())
                                  for s in f.proposers) or "—"),
            ("processus", _names(s.name for s in f.processes)),
            ("outils", _names(s.name for s in f.tools)),
            ("capacités", _names(s.name for s in f.capabilities)),
            ("vues", _names(v.title for v in f.inspectors)),
            ("fiches", _names(s.label for s in f.subjects)),
            ("actions", _names(a.title for a in f.actions)),
        ]
        out.append(Disclosure(f"{f.name}", (Fields(tuple((k, Text(v, "mono") if "\n" in v else v)
                                                          for k, v in pairs)),)))
    return out


@TABS.tab("systeme.operations", title="Journal d'exploitation")
async def operations(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    before = ctx.int_param("avant", 0) or None
    done = ctx.events([rt.OPERATED], 100, before=before)
    tones = {"done": "ok", "refused": "warn", "superseded": "warn", "failed": "danger"}
    rows = tuple(Row((When(e.at), Text(e.data.action, "mono"), e.data.by, e.data.subject or "—",
                      Badge(e.data.outcome, tones.get(e.data.outcome, "")),
                      ", ".join(str(s) for s in e.data.seqs) or "—"), href=Ref("event", str(e.seq), ""))
                 for e in done)
    pager = Pager(older=(("avant", str(done[-1].seq)),)) if len(done) == 100 else None
    return [Table((Column("quand", "fit"), "action", "par", "sur", "issue", "événements"), rows,
                  title="Ce que les opérateurs ont fait", empty="Aucune action d'opérateur encore.", pager=pager)]


@TABS.tab("systeme.simulations", title="Simulations")
async def simulations(ui: Any, request: Request) -> list[Any]:
    folder = ui.deps.reports
    if folder is None or not folder.is_dir():
        return [Note("Aucun dossier de rapports (lance le serveur avec --reports DOSSIER, et "
                     "« mika sim run --report DOSSIER »).", "muted")]
    files = sorted((f for f in folder.rglob("*") if f.is_file() and REPORT_NAME.match(f.name)),
                   key=lambda f: f.stat().st_mtime, reverse=True)[:200]
    chosen = request.query_params.get("fichier", "")
    out: list[Any] = [Table(("fichier", "modifié"), tuple(
        (Ref("local", f"/inspecteur/systeme/simulations?fichier={_q(str(f.relative_to(folder)))}",
             str(f.relative_to(folder))), When(int(f.stat().st_mtime * US))) for f in files),
        title="Rapports", empty="aucun rapport")]
    if chosen:
        match = next((f for f in files if str(f.relative_to(folder)) == chosen), None)
        out.append(Prose(match.read_text(encoding="utf-8", errors="replace")[:REPORT_MAX], chosen) if match
                   else Note("Fichier inconnu.", "warn"))
    return out


def _q(text: str) -> str:
    return quote(text, safe="")


@TABS.tab("systeme.vues", title="Toutes les vues")
async def all_views(ui: Any, request: Request) -> list[Any]:
    rows = tuple((Ref.view(v.owner, v.name, v.title), v.owner, v.section or "—", v.subject or "—",
                  Badge("cachée", "muted") if v.hidden else "—") for v in ui.inspection.views())
    return [Table(("vue", "faculté", "destination", "fiche", ""), rows, title="Ce que chaque faculté montre d'elle")]
