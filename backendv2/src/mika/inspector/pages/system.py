"""Système : santé, appels de modèle, chronologie, état et faits,
contributions, journal d'exploitation, simulations, toutes les vues."""

from __future__ import annotations

import json
import re
import secrets as _secrets
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.adapters.llm.config import ROLE_LABELS
from mika.contracts import runtime as rt
from mika.inspector import names
from mika.inspector.catalog import Panel
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.clock import DAY, US
from mika.kernel.facts import FactKey
from mika.kernel.inspect import (
    Badge,
    Chart,
    Code,
    Column,
    Disclosure,
    Fields,
    Nav,
    NavItem,
    Note,
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
    cursor_page,
    day_fr,
    describe_error,
    money_fr,
    num_fr,
    pct_fr,
    read_params,
)
from mika.runtime import health
from mika.runtime import operations as ops
from mika.runtime.boundary import Failed, call

STATE_TONES = {"ok": "ok", "degraded": "warn", "ko": "danger"}
STATES_FR = {"ok": "en forme", "degraded": "dégradé", "ko": "en panne"}
CHECKS_FR = {"journal": "journal", "slices": "tranches", "loops": "boucles", "projections": "projections",
             "processes": "processus", "outbox": "file de sortie", "llm": "modèles", "lanes": "voies",
             "config": "configuration lisible"}
#: les états d'une ligne de la file de sortie ; « seen » : un échec qu'un opérateur a vu et laissé
OUTBOX_LABELS = {"pending": "en attente", "done": "parti", "failed": "échoué", "orphan": "orphelin",
                 "seen": "vu, laissé"}
#: ce qui allume le badge « à traiter » de Sorties
OUTBOX_PROBLEMS = ("failed", "orphan")
#: les pages de Système qui lisent le journal ou une table, par page
PAGE = 50
REPORT_NAME = re.compile(r"^[\w.-]{1,120}\.(md|html|json|txt)$")
REPORT_MAX = 400_000


def _names(items: Any) -> str:
    return ", ".join(sorted(items)) or "—"


@TABS.tab("systeme.sante", title="Santé", group="Surveillance", badge=lambda ui: sum(
    1 for c in health.report(ui.kernel).checks if c.state != health.OK),
          description="Les contrôles de santé (ce que dit aussi /health), les projections et ce qui en est en "
                      "quarantaine, les vues lentes.")
async def sante(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    report = health.report(kernel)
    checks = Table(("contrôle", "état", "résumé"), tuple(
        Row((CHECKS_FR.get(c.name, c.name), Badge(STATES_FR.get(c.state, c.state), STATE_TONES.get(c.state, "")),
             c.summary), tone=STATE_TONES.get(c.state, ""),
            detail=(Code("\n".join(c.detail)),) if c.detail else ()) for c in report.checks),
        title=f"État : {STATES_FR.get(report.status, report.status)} (phase {report.phase})")
    lag = kernel.projections.lag()
    projs = Table(("projection", "niveau", Column("version", "num"), Column("retard", "num")), tuple(
        (p.name, str(p.tier), p.version, "dans la transaction" if str(p.tier).endswith("T0") else lag.get(p.name, 0))
        for p in sorted(kernel.registry.projectors.values(), key=lambda p: p.name)), title="Projections")
    blocks: list[Any] = [checks, projs]
    if kernel.projections.quarantined:
        blocks.append(Table(("projection", "événement", "erreur"), tuple(
            (name, Ref("event", str(seq), str(seq)), Text(err, "muted", clamp=200))
            for name, seq, err in reversed(kernel.projections.quarantined)), title="Quarantaine"))
    slow = ui.inspection.slow()
    if slow:
        blocks.append(Table(("vue", Column("passages", "num"), Column("dernière (ms)", "num"),
                             Column("pire (ms)", "num")), tuple(
            (k, t.runs, t.last_us // 1000, t.max_us // 1000) for k, t in slow), title="Vues lentes"))
    blocks.append(Disclosure("Sonde publique (/health)", (Code(json.dumps(report.public(), indent=1)),)))
    return blocks


@TABS.tab("systeme.appels", title="Coûts et appels", group="Surveillance",
          description="Chaque appel de modèle : combien, par qui, pour combien, combien de temps, avec quelle part "
                      "de cache (30 jours gardés).")
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
        Stat("Aujourd'hui", today.calls if today else 0, money_fr(today.cost_usd) if today else money_fr(0.0)),
        Stat("14 jours", sum(u.calls for u in days), money_fr(total_cost)),
        Stat("Échecs (14 j)", sum(u.failures for u in days), "", "danger" if any(u.failures for u in days) else ""),
        Stat("Part du cache (7 j)", pct_fr(_cache(roles)), "entrée lue depuis le cache"),
    ))]
    stamp = {u.key: int(datetime.strptime(u.key, "%Y-%m-%d").replace(tzinfo=ui.tz).timestamp() * US)
             for u in days}
    if days:
        out.append(Chart((Series("coût", tuple((stamp[u.key], u.cost_usd) for u in days), 2),), kind="bars",
                         title="Coût par jour", unit="$"))

    def day_label(key: str) -> str:
        d = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=ui.tz)
        return day_fr(d.year, d.month, d.day, d.weekday())

    def usage_table(rows: list[Any], label: str, title: str, show: Any = str) -> Table:
        return Table((label, Column("appels", "num"), Column("échecs", "num"), Column("entrée", "num", detail=True),
                      Column("sortie", "num", detail=True), Column("cache lu", "num", detail=True),
                      Column("part du cache", "num", detail=True), Column("coût", "num"), Column("durée moy.", "num")),
                     tuple(Row((show(u.key), u.calls, u.failures, num_fr(u.input_tokens), num_fr(u.output_tokens),
                                num_fr(u.cache_read), pct_fr(u.cache_ratio), money_fr(u.cost_usd),
                                f"{num_fr(u.latency_avg_s, 1)} s"), tone="danger" if u.failures else "")
                           for u in rows), title=title, empty="aucun appel")

    models = calls.usage(now - 7 * DAY, by="model")
    breakdown = [usage_table(list(reversed(days)), "jour", "Par jour", day_label),
                 usage_table(roles, "rôle", "Par rôle (7 j)", names.role),
                 usage_table(backends, "fournisseur", "Par fournisseur (7 j)"),
                 usage_table(models, "fournisseur · modèle", "Par modèle (7 j)")]
    ctx = ui.inspection.context(request.query_params)
    pager = ctx.pager("page", size=PAGE, total=calls.count())
    recent = calls.recent(pager.size, offset=pager.offset)
    corr_of = {id(t): getattr(t, "correlation", "") or t.call_id.split("#")[0] for t in recent}
    episodes = _episode_correlations(ui, set(corr_of.values()))
    out.append(Table((Column("quand", "fit"), "rôle", "fournisseur", Column("modèle", detail=True),
                      Column("attente", "num", detail=True), Column("durée", "num"), Column("jetons", "num", detail=True),
                      Column("coût", "num"), "issue"), tuple(
        Row((When(t.at), names.role(t.role), t.backend, Text(t.model, "mono"), f"{num_fr(t.wait_us / 1e6, 1)} s",
             f"{num_fr(t.latency_us / 1e6, 1)} s", f"{num_fr(t.input_tokens)} → {num_fr(t.output_tokens)}",
             money_fr(t.cost_usd),
             Badge("réussi" if t.outcome == "ok" else names.detail(t.outcome), "ok" if t.outcome == "ok" else "danger")),
            href=Ref("episode", corr_of[id(t)], "") if corr_of[id(t)] in episodes else None) for t in recent),
        title="Tous les appels, du plus récent", empty="aucun appel", pager=pager))
    out.append(Disclosure("Répartition des appels et des coûts", tuple(breakdown)))
    return out


def _cache(rows: list[Any]) -> float:
    read = sum(u.cache_read for u in rows)
    total = sum(u.input_tokens + u.cache_read + u.cache_write for u in rows)
    return read / total if total else 0.0


TIMELINE_PARAMS = (Param("type", "type d'événement", placeholder="memory., episode.utterance…"),
                   Param("correlation", "corrélation", placeholder="un épisode, une action"))


@TABS.tab("systeme.chronologie", title="Chronologie", group="Journaux",
          description="Le journal d'événements, du plus récent : tout ce qui lui est arrivé, filtrable par type ou "
                      "par épisode.")
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
        f"SELECT seq FROM events {where} ORDER BY seq DESC LIMIT {CHRONOLOGY_PAGE + 1}", tuple(params))]
    found = sorted((ui.decode(s) for s in kernel.mind.store.get_events(seqs)), key=lambda e: -e.seq)
    events, pager = cursor_page(found, CHRONOLOGY_PAGE, current=before or 0)
    episodes = _episode_correlations(ui, {e.correlation for e in events})
    rows = tuple(Row((When(e.at), Text(ui.names.event(e.type.name), hint=e.type.name),
                      _correlation_cell(e.correlation, episodes),
                      Ref("event", str(e.seq), f"n° {e.seq}"), Text(e.type.name, "mono"),
                      Text(e.correlation, "mono")),
                     href=Ref("event", str(e.seq), ""), detail=(Code(ui.show(e, 4000), "Données"),))
                 for e in events)
    notes = [Note(f"Les événements de « {corr[:80]} » : ce n'est pas un épisode (une action d'opérateur, un effet, "
                  "un processus).", "info")] if corr and corr not in episodes and events else []
    return {"blocks": [*notes, Table((Column("quand", "fit"), "ce qui s'est passé", "lié à",
                                      Column("événement", detail=True), Column("type", detail=True),
                                      Column("corrélation", detail=True)), rows,
                                     title="Le journal", empty="Rien ne correspond.", pager=pager)],
            "filters": TIMELINE_PARAMS, "values": values}


#: la chronologie, par page
CHRONOLOGY_PAGE = 100


def _episode_correlations(ui: Any, correlations: set[str]) -> set[str]:
    """Parmi ces corrélations, celles d'un épisode (un début ou une fin au journal)."""
    corrs = sorted(c for c in correlations if c)[:500]
    if not corrs:
        return set()
    marks = ",".join("?" * len(corrs))
    rows = ui.kernel.mind.store.query_mind(
        f"SELECT DISTINCT correlation FROM events WHERE type IN (?, ?) AND correlation IN ({marks})",
        (rt.EPISODE_STARTED.name, rt.EPISODE_ENDED.name, *corrs))
    return {str(r[0]) for r in rows}


def _correlation_cell(corr: str, episodes: set[str]) -> Any:
    """Un épisode mène à sa page ; le reste (une action d'opérateur, un effet) à ses événements."""
    if corr in episodes:
        return Ref("episode", corr, "un épisode")
    if corr.startswith("opérateur:"):
        label = "une action d'opérateur"
    elif corr.startswith("effet:"):
        label = "un effet"
    else:
        label = "les événements liés"
    return Ref("local", "/inspecteur/systeme/chronologie", label, (("correlation", corr),))


@TABS.tab("systeme.etat", title="État et faits", group="Anatomie",
          description="Les faits que les facultés se partagent, lus maintenant, et l'état brut de chaque tranche.")
async def etat(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    root = kernel.mind.root
    rows = []
    for name, spec in sorted(kernel.registry.providers.items()):
        if isinstance(spec.key, FactKey):
            got = call(frame.get, spec.key, label=f"fait {name}")
            value = f"(erreur : {describe_error(got.error)})" if isinstance(got, Failed) else repr(got)
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


@TABS.tab("systeme.contributions", title="Contributions", group="Anatomie",
          description="Ce que chaque faculté apporte, lu dans le registre : événements, faits, sections, preuves, "
                      "processus, outils, vues.")
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
            ("preuves", "\n".join(", ".join(f"{r} [{num_fr(lo)} ; {num_fr(hi)}]" for r, (lo, hi) in s.reasons.items())
                                  for s in f.proposers) or "—"),
            ("processus", _names(s.name for s in f.processes)),
            ("outils", _names(s.name for s in f.tools)),
            ("capacités", _names(s.name for s in f.capabilities)),
            ("vues", _names(v.title for v in f.inspectors)),
            ("fiches", _names(s.label for s in f.subjects)),
            ("actions", _names(a.title for a in f.actions)),
        ]
        label = ui.names.faculty(f.name)
        out.append(Disclosure(label if label == f.name else f"{label} ({f.name})", (Fields(tuple((k, Text(v, "mono") if "\n" in v else v)
                                                          for k, v in pairs)),)))
    return out


@TABS.tab("systeme.operations", title="Opérations", group="Journaux",
          description="Ce que les opérateurs ont fait depuis la console : l'action, qui, sur quoi, l'issue (jamais "
                      "un contenu).")
async def operations(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    done, pager = ctx.older([rt.OPERATED], OPERATIONS_PAGE)
    rows = tuple(operation_row(ui, e) for e in done)
    return [Table((Column("quand", "fit"), "action", "par", "sur", "issue", Column("action (clé)", detail=True),
                   Column("événements", detail=True)), rows,
                  title="Ce que les opérateurs ont fait", empty="Aucune action d'opérateur encore.", pager=pager)]


#: les opérations, par page
OPERATIONS_PAGE = 100


def operation_row(ui: Any, e: Any) -> Row:
    """Une action d'opérateur : son titre, qui (un nom), sur quoi (un nom), l'issue en mots ; les clés au
    détail."""
    label, tone = names.OPERATED.get(e.data.outcome, (e.data.outcome, ""))
    subject, kind = e.data.subject or "", e.data.subject_kind or ""
    on: Any = "—"
    spec = ui.inspection.subject(kind) if kind else None
    if subject and kind in ("person", "handle"):
        on = ui.names.who_cell(subject)
    elif subject and spec is not None:
        on = Ref.subject(kind, subject, f"{spec.label} {subject}")
    elif subject:
        on = Text(subject, hint=kind)
    return Row((When(e.at), ui.names.action(e.data.action), ui.names.who(e.data.by), on, Badge(label, tone),
                Text(e.data.action, "mono"), ", ".join(str(s) for s in e.data.seqs) or "—"),
               href=Ref("event", str(e.seq), ""))


@TABS.tab("systeme.simulations", title="Simulations", group="Outils",
          description="Les rapports de simulation (« mika sim run --report »).")
async def simulations(ui: Any, request: Request) -> list[Any]:
    folder = ui.deps.reports
    if folder is None or not folder.is_dir():
        return [Note("Aucun dossier de rapports (lance le serveur avec --reports DOSSIER, et "
                     "« mika sim run --report DOSSIER »).", "muted")]
    files = sorted((f for f in folder.rglob("*") if f.is_file() and REPORT_NAME.match(f.name)),
                   key=lambda f: f.stat().st_mtime, reverse=True)
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


@TABS.tab("systeme.vues", title="Toutes les vues", group="Anatomie",
          description="Chaque vue que les facultés déclarent, et où elle est rangée.")
async def all_views(ui: Any, request: Request) -> list[Any]:
    rows = tuple((Ref.view(v.owner, v.name, v.title), Text(ui.names.faculty(v.owner), hint=v.owner),
                  v.section or "—", v.subject or "—",
                  Badge("cachée", "muted") if v.hidden else "—") for v in ui.inspection.views())
    return [Table(("vue", "faculté", "destination", "fiche", ""), rows, title="Ce que chaque faculté montre d'elle")]


@TABS.tab("systeme.processus", title="Processus", group="Surveillance",
          badge=lambda ui: sum(1 for s in ui.kernel.scheduler.specs if ui.kernel.scheduler.consecutive.get(s.name, 0) >= 3),
          description="Ses processus de fond (relire la mémoire, dormir, relever le courrier…) : combien de passages, "
                      "d'échecs, la dernière erreur — et les échecs gardés au journal, qui survivent au redémarrage.")
async def processus(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    sched = kernel.scheduler
    running = set(sched.running())
    failing = [s for s in sched.specs if sched.consecutive.get(s.name, 0) >= 3]
    procs = Table(("processus", "faculté", "voie", Column("passages", "num"), Column("échecs", "num"),
                   Column("d'affilée", "num"), "dernier passage", "dernière erreur", Column("nom technique", detail=True)),
                  tuple(
        Row((ui.names.process(s.name) + (" · en cours" if s.name in running else ""), ui.names.faculty(s.owner),
             names.lane(s.lane), sched.runs.get(s.name, 0),
             sched.failures.get(s.name, 0), sched.consecutive.get(s.name, 0),
             When(sched.last_run(s.name) or 0) if sched.last_run(s.name) else "—",
             Text(names.detail(sched.last_error.get(s.name, (0, ""))[1]), "muted", clamp=160),
             Text(s.name, "mono")),
            tone="danger" if sched.consecutive.get(s.name, 0) >= 3 else "") for s in sched.specs),
        title="Depuis le démarrage", caption="Ces compteurs repartent de zéro à chaque démarrage ; les échecs "
                                             "gardés au journal sont dessous.")
    ctx = ui.inspection.context(request.query_params)
    failed, pager = ctx.older([rt.PROCESS_FAILED], PAGE)
    history = Table((Column("quand", "fit"), "processus", "erreur"), tuple(
        Row((When(e.at), Text(ui.names.process(e.data.process), hint=e.data.process),
             Text(names.detail(e.data.error), "muted", clamp=240)),
            href=Ref("event", str(e.seq), "")) for e in failed), title="Échecs gardés au journal",
        empty="Aucun échec de processus au journal.", pager=pager)
    return [Stats((Stat("Processus", len(sched.specs)),
                   Stat("En cours", len(running), ", ".join(ui.names.process(n) for n in sorted(running))[:90]),
                   Stat("En échec d'affilée", len(failing), ", ".join(ui.names.process(s.name) for s in failing)[:90],
                        "danger" if failing else ""),
                   Stat("Échecs depuis le démarrage", sum(sched.failures.values()), "",
                        "warn" if any(sched.failures.values()) else ""))), procs, history]


@TABS.tab("systeme.anomalies", title="Anomalies", group="Surveillance",
          badge=lambda ui: len(getattr(ui.kernel.mind, "anomalies", ()) or ()),
          description="Ce qui s'est mal passé sans tout arrêter : une évaluation, une réduction, un choix de l'arbitre ; et "
                      "les traces du journal (épisode supplanté, oubli, reconstruction). En mémoire depuis le "
                      "démarrage.")
async def anomalies(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    mind = kernel.mind
    items = list(reversed(list(getattr(mind, "anomalies", ()) or ())))
    arbiter = list(reversed(list(getattr(kernel.arbiter, "anomalies", ()) or ())))
    traces = list(reversed(list(getattr(mind, "traces", ()) or ())))
    tainted = dict(mind.root.tainted.items())
    out: list[Any] = [Stats((
        Stat("Évaluations et réductions", len(items), "échouées sans corrompre", "warn" if items else ""),
        Stat("Arbitre", len(arbiter), "anomalies de l'arbitre", "warn" if arbiter else ""),
        Stat("Traces du journal", len(traces), "supplanté, oubli, reconstruction"),
        Stat("Tranches corrompues", len(tainted), ", ".join(tainted) or "aucune", "danger" if tainted else ""),
    ))]
    if tainted:
        out.append(Note("Tranches corrompues (leur réducteur a levé) : " + ", ".join(
            f"{o} (au seq {s})" for o, s in tainted.items()) + ". Leur état est figé jusqu'à reconstruction "
            "(« mika rebuild »).", "danger"))
    out.append(Table(("anomalie",), tuple((Text(a, "mono", clamp=300),) for a in items),
                     title="Évaluations et réductions qui ont échoué", empty="Aucune."))
    out.append(Table(("anomalie",), tuple((Text(str(a), "mono", clamp=300),) for a in arbiter),
                     title="Anomalies de l'arbitre", empty="Aucune."))
    out.append(Table((Column("quand", "fit"), Column("sorte", "fit"), "détail"), tuple(
        (When(t.at), Badge(t.kind, "muted"), Text(json.dumps(t.detail, ensure_ascii=False, default=str), "mono",
                                                   clamp=240)) for t in traces),
        title="Traces du journal", empty="Aucune."))
    return out


@TABS.tab("systeme.sorties", title="Sorties", group="Surveillance",
          badge=lambda ui: _outbox_problems(ui),
          description="La file de sortie : chaque effet visible (une réponse livrée, un mail envoyé) part après son "
                      "écriture au journal. Ce qui attend, ce qui n'a pas pu partir, ce qui n'a trouvé personne pour "
                      "l'exécuter.")
async def sorties(ui: Any, request: Request) -> Any:
    store = ui.kernel.mind.store
    counts = dict(store.query_mind("SELECT status, COUNT(*) FROM outbox GROUP BY status"))
    ctx = ui.inspection.context(request.query_params)
    status = request.query_params.get("etat", "")
    labels = OUTBOX_LABELS
    invalid = bool(status and status not in labels)
    if invalid:
        status = ""
    where, args = ("WHERE status=?", (status,)) if status else ("", ())
    total = int(store.query_mind(f"SELECT COUNT(*) FROM outbox {where}", args)[0][0])
    pager = ctx.pager("page", size=PAGE, total=total)
    rows = store.query_mind(f"SELECT key, seq, effect, status, attempts, last_error FROM outbox {where} "
                            f"ORDER BY seq DESC LIMIT ? OFFSET ?", (*args, pager.size, pager.offset))
    tones = {"pending": "info", "done": "ok", "failed": "danger", "orphan": "warn", "seen": "muted"}
    chips = tuple(NavItem(f"{labels.get(k, k)}", Ref("local", "/inspecteur/systeme/sorties", k, (("etat", k),)),
                          count=n, active=k == status, tone=tones.get(k, "")) for k, n in sorted(counts.items()))
    back = request.url.path + (f"?{urlencode(_without(request.query_params, 'flash'))}"
                               if _without(request.query_params, "flash") else "")
    marks = ",".join("?" * len(OUTBOX_PROBLEMS))
    problems = [{"key": key, "seq": seq, "label": _effect_label(ui, effect), "status": labels.get(st, st),
                 "error": names.detail(err) if err else ""}
                for key, seq, effect, st, err in store.query_mind(
                    f"SELECT key, seq, effect, status, last_error FROM outbox WHERE status IN ({marks}) "
                    f"ORDER BY seq DESC LIMIT {OUTBOX_PROBLEMS_SHOWN}", OUTBOX_PROBLEMS)]
    panel = Panel("outbox.html", {"problems": problems, "back": back,
                                  "more": max(0, _outbox_problems(ui) - len(problems)), "panel_after": True})
    return {"panel": panel, "blocks": [
        *([Note("État inconnu : affichage de tous les effets.", "warn")] if invalid else []),
        Stats(tuple(Stat(labels.get(k, k).capitalize(), n, "", tones.get(k, "") if k not in ("done", "seen") else "")
                    for k, n in sorted(counts.items())) or (Stat("File", 0, "vide"),)),
        Nav((NavItem("tout", Ref("local", "/inspecteur/systeme/sorties", "tout"), count=sum(counts.values()),
                     active=not status), *chips), title="État"),
        Table((Column("n°", "fit", hint="l'événement qui l'a fait partir"), "effet", "état", Column("essais", "num"),
               "dernière erreur", Column("effet (clé)", detail=True)), tuple(
            Row((Ref("event", str(seq), f"n° {seq}"), Text(_effect_label(ui, effect), hint=effect),
                 Badge(labels.get(st, st), tones.get(st, "")), attempts,
                 Text(names.detail(err) if err else "—", "muted", clamp=200), Text(effect, "mono")),
                href=Ref("event", str(seq), ""), tone={"failed": "danger", "orphan": "warn"}.get(st, ""))
            for _key, seq, effect, st, attempts, err in rows),
            title="Effets", empty="Aucun effet.", pager=pager,
            caption="Orphelin : aucun exécuteur n'était déclaré pour cet effet quand il est parti — il n'a rien fait. "
                    "Un effet échoué ou orphelin se relance (un essai de plus) ou se marque comme vu : le badge "
                    "« à traiter » s'éteint, la ligne reste."),
    ]}


#: les effets en échec montrés avec leurs boutons (les plus récents)
OUTBOX_PROBLEMS_SHOWN = 50


def _without(query: Any, *keys: str) -> dict[str, str]:
    return {k: v for k, v in query.items() if k not in keys}


def _effect_label(ui: Any, effect: str) -> str:
    """Un effet (« runtime:episode.utterance ») : ce qu'il fait partir."""
    owner, _, type_name = effect.partition(":")
    return {"episode.utterance": "une parole à livrer"}.get(type_name, ui.names.event(type_name or owner))


def _outbox_problems(ui: Any) -> int:
    marks = ",".join("?" * len(OUTBOX_PROBLEMS))
    rows = ui.kernel.mind.store.query_mind(f"SELECT COUNT(*) FROM outbox WHERE status IN ({marks})", OUTBOX_PROBLEMS)
    return int(rows[0][0]) if rows else 0


async def outbox_post(ui: Any, request: Request) -> Response:
    """Relancer un effet échoué ou orphelin (un essai de plus, tout de suite), ou le marquer comme vu (il
    n'allume plus « à traiter ») — audité, jamais sur un effet qui n'est pas en échec."""
    data = await ui.form(request)
    account = ui.operator(request)
    back = str((data or {}).get("_retour", "")) or f"{PREFIX}/systeme/sorties"
    if not back.startswith(PREFIX + "/") or "//" in back or "\\" in back:
        back = f"{PREFIX}/systeme/sorties"
    token = _secrets.token_urlsafe(9)
    if data is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    else:
        key, what = str(data.get("cle", ""))[:300], str(data.get("faire", ""))
        store = ui.kernel.mind.store
        found = store.query_mind("SELECT status, last_error FROM outbox WHERE key=?", (key,))
        if not found or found[0][0] not in OUTBOX_PROBLEMS or what not in ("relancer", "vu"):
            ui.flash(token, "warn", "Rien à faire : cet effet n'est plus en échec (déjà relancé ou vu ?).")
        else:
            error = found[0][1]
            if what == "relancer":
                await store.mark_outbox(key, "pending", error)
                ui.kernel.effects.wake()
                ui.flash(token, "ok", "Relancé : l'effet repart pour un essai.")
            else:
                await store.mark_outbox(key, "seen", error)
                ui.flash(token, "ok", "Marqué comme vu : il n'est plus « à traiter ».")
            await ops.audit(ui.kernel, f"console.sorties.{what}", by=account.handle, subject_kind="effet",
                            subject=key)
    sep = "&" if "?" in back else "?"
    return secure(RedirectResponse(f"{back}{sep}flash={token}", status_code=303))


@TABS.tab("systeme.passerelle", title="Modèles en service", group="Surveillance",
          description="La passerelle des modèles telle qu'elle tourne : pour chaque fournisseur, ses créneaux "
                      "(occupés, en attente), son repli, son quota ; pour chaque rôle, qui le sert vraiment.")
async def passerelle(ui: Any, request: Request) -> list[Any]:
    gateway = ui.kernel.deps.gateway
    status = list(getattr(gateway, "status", lambda: [])() or [])
    resolution = dict(getattr(gateway, "resolution", lambda: {})() or {})
    if not getattr(gateway, "configured", gateway is not None):
        return [Note("Aucun modèle n'est configuré : chaque tour échoue proprement. Déclare un fournisseur dans "
                     "Configuration › Intelligence › Fournisseurs.", "danger")]
    rows = []
    for b in status:
        quota = (b.get("extra") or {}).get("quota") or {}
        quota_text = " · ".join(f"{k} {pct_fr(v)}" for k, v in quota.items()) if quota else "—"
        rows.append(Row((Text(b["name"], "mono"), Text(f"{b['busy']} / {b['slots']}", "num"), b["waiting"],
                         Badge("oui", "info") if b["preempt"] else Text("non", "muted"),
                         Text(b["fallback"] or "—", "mono" if b["fallback"] else "muted"), quota_text),
                        tone="warn" if b["waiting"] else ""))
    unserved = [r for r, name in resolution.items() if not name]
    return [
        Stats((Stat("Fournisseurs", len(status)), Stat("Créneaux occupés", sum(b["busy"] for b in status),
                                                       f"sur {sum(b['slots'] for b in status)}"),
               Stat("En attente d'un créneau", sum(b["waiting"] for b in status), "",
                    "warn" if any(b["waiting"] for b in status) else ""),
               Stat("Rôles sans fournisseur", len(unserved), ", ".join(names.role(r) for r in unserved) or "aucun",
                    "danger" if unserved else ""))),
        Table(("fournisseur", Column("créneaux", "num"), Column("en attente", "num"), "préempte", "repli",
               "quota d'abonnement"), tuple(rows), title="Fournisseurs",
              caption="Un fournisseur à un seul créneau préempte : une réponse interrompt un travail de fond."),
        Table(("rôle", Column("nom technique", "fit"), "servi par"), tuple(
            Row((ROLE_LABELS.get(r, r), Text(r, "mono"), Text(n or "aucun : chaque appel échoue",
                                                             "mono" if n else "muted")), tone="" if n else "danger")
            for r, n in resolution.items()), title="Qui sert quoi, en vrai",
            caption="Replis compris : un rôle sans fournisseur retombe sur un autre rôle (murmurer → répondre). "
                    "Se règle dans Configuration › Intelligence › Qui sert quoi."),
    ]


@TABS.tab("systeme.stockage", title="Stockage", group="Surveillance",
          description="Ses bases (sa vie dans mind.db, les projections jetables dans views.db), le dernier instantané "
                      "et ce que garde le journal. Les sauvegardes se font par « mika backup ».")
async def stockage(ui: Any, request: Request) -> list[Any]:
    store = ui.kernel.mind.store
    mind = ui.kernel.mind

    def size(query: Any) -> int:
        try:
            pages = query("PRAGMA page_count")[0][0]
            page = query("PRAGMA page_size")[0][0]
            return int(pages) * int(page)
        except (IndexError, TypeError, ValueError):
            return 0

    tables = {r[0] for r in store.query_mind("SELECT name FROM sqlite_master WHERE type='table'")}

    def count(table: str) -> int:
        if table not in tables:
            return 0
        rows = store.query_mind(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 — un nom de table de cette liste
        return int(rows[0][0]) if rows else 0

    snap = store.latest_snapshot()
    mind_size, views_size = size(store.query_mind), size(store.query_views)
    boots = mind.root.slices["kernel"].boots
    return [
        Stats((Stat("mind.db", _bytes(mind_size), "sa vie : à sauvegarder"),
               Stat("views.db", _bytes(views_size), "reconstruisible"),
               Stat("Événements", mind.head, f"{boots} démarrage(s)"),
               Stat("Dernier instantané", f"seq {snap.seq}" if snap else "aucun",
                    ui.when_long(snap.at) if snap else "le démarrage rejoue tout"))),
        Table(("table", Column("lignes", "num"), "ce qu'elle garde"), (
            ("events", count("events"), "le journal : tout ce qui lui est arrivé"),
            ("content", count("content"), "les textes libres, effaçables par l'oubli"),
            ("snapshots", count("snapshots"), "les instantanés (démarrage rapide)"),
            ("outbox", count("outbox"), "la file de sortie"),
            ("settings", count("settings"), "les réglages d'exploitation"),
        ), title="Ce que garde mind.db"),
        *backup_blocks(ui),
        Note("Sauvegarder : « mika --data DOSSIER backup ARCHIVES --keep 14 » (sans risque serveur en marche) ; "
             "vérifier : « mika --data DOSSIER verify ARCHIVE » ; restaurer (serveur arrêté) : « mika restore "
             "ARCHIVE ». Chaque sauvegarde et chaque vérification se notent ici.", "muted"),
    ]


#: au-delà, une sauvegarde est « ancienne » (le tableau de bord le signale)
BACKUP_LATE_DAYS = 2


def backup_state(ui: Any) -> tuple[str, str]:
    """(ton, phrase) : l'état des sauvegardes, pour le tableau de bord et la page Stockage."""
    fn = ui.deps.backups
    if fn is None:
        return "", ""
    got = fn() or {}
    last = got.get("sauvegarde") or {}
    if not last:
        return "warn", "aucune sauvegarde notée : « mika backup »"
    age = (ui.now() - int(last.get("at") or 0)) / DAY
    check = got.get("verification") or {}
    if check and not check.get("ok"):
        return "danger", f"la dernière vérification a échoué : {check.get('erreur', '?')}"[:160]
    if age > BACKUP_LATE_DAYS:
        return "warn", f"la dernière date de {age:.0f} jours"
    return "ok", f"il y a {age * 24:.0f} h"


def backup_blocks(ui: Any) -> list[Any]:
    fn = ui.deps.backups
    if fn is None:
        return []
    got = fn() or {}
    last, check, archives = got.get("sauvegarde") or {}, got.get("verification") or {}, got.get("archives") or []
    head = ui.kernel.mind.head
    tone, text = backup_state(ui)
    since = head - int(last.get("tete") or 0) if last else 0
    out: list[Any] = [Stats((
        Stat("Dernière sauvegarde", When(int(last["at"])) if last else "jamais", text, tone),
        Stat("Depuis", f"{since} événement(s)" if last else "—", "écrits depuis, pas encore sauvegardés",
             "warn" if last and since > 0 and tone == "warn" else ""),
        Stat("Dernière vérification", When(int(check["at"])) if check else "jamais",
             ("réussie" if check.get("ok") else f"échec : {check.get('erreur', '?')}")[:120] if check else
             "« mika verify ARCHIVE » rejoue une archive sans rien toucher",
             "" if not check else "ok" if check.get("ok") else "danger"),
        Stat("Archives gardées", len(archives), _bytes(sum(int(a.get("octets") or 0) for a in archives))
             + (f" · {last.get('dossier')}" if last else "")),
    ), title="Sauvegardes")]
    if last:
        out.append(Fields((("archive", Text(str(last.get("archive", "—")), "mono")), ("fichiers", last.get("fichiers")),
                           ("taille", _bytes(int(last.get("octets") or 0))), ("tête du journal", last.get("tete")),
                           ("en garde", f"les {last['garde']} plus récentes" if last.get("garde") else "toutes"),
                           ("remarques", "; ".join(last.get("remarques") or []) or "—")),
                          title="La dernière sauvegarde", columns=2))
    if archives:
        out.append(Table((Column("archive"), Column("taille", "num"), Column("écrite", "fit")), tuple(
            (Text(a["nom"], "mono"), _bytes(int(a.get("octets") or 0)), When(int(a.get("at") or 0)))
            for a in archives), title=f"Archives ({len(archives)})"))
    return out


def _bytes(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)
