"""Système, dessiné (ADR 0121) : les pages où l'opératrice cherche ce qui ne va pas.

Processus : ses processus de fond lus à l'ordonnanceur, comme l'onglet de la console — d'abord ce qui échoue, avec
sa dernière erreur en clair et son prochain essai ; puis tous les autres, une carte par faculté, une ligne chacun.
L'historique des échecs gardés au journal reste celui de la console (sa pagination à curseur).

Sorties : le parcours d'un effet et où en sont les départs, ce qui est à traiter (relancer, marquer comme vu), ce
qui part, par sorte, et les derniers départs, une ligne par effet — ce qu'il fait partir, son état, son événement.
Elle dit tout ce que disait le panneau de la console (``panel=False``), qui ne revient qu'au repli.

Santé : le bilan lu au rapport de santé, comme l'onglet de la console — son verdict, puis ses dix contrôles en
tuiles, ce qui ne va pas d'abord, chacun avec son constat, son détail et la page de son diagnostic ; les projections
et la sonde publique en replis.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup
from sqlalchemy import func, select

from mika.app.handmade import blocks as drawn_blocks
from mika.inspector import names, render
from mika.inspector.pages import diagnostics
from mika.inspector.pages.system import (
    OUTBOX_GUIDANCE,
    OUTBOX_LABELS,
    OUTBOX_PROBLEMS,
    OUTBOX_SEEN_ONLY,
    OUTBOX_TONES,
)
from mika.inspector.ui import PREFIX, UI, env
from mika.kernel.faculty import Tier
from mika.kernel.inspect import Disclosure, Pager, Stats, Table
from mika.ports.journal import JournalOutbox
from mika.runtime import health as health_m
from mika.runtime.boundary import Failed, call
from mika.runtime.effects import MAX_ATTEMPTS, RETRY_BASE_S, RETRY_MAX_S, STALE_AFTER_S
from mika.runtime.inspection import SLOW_US

#: l'ordre des états, du plus urgent au plus calme, et ce que chacun dit
STATES = (("ko", "en échec"), ("stumbling", "a trébuché"), ("held", "retenu"), ("running", "en cours"),
          ("ok", "passé"), ("never", "pas encore exécuté"))


def _state(sched: Any, name: str, running: set[str], now: int) -> str:
    consecutive = sched.consecutive.get(name, 0)
    if consecutive >= health_m.PROCESS_FAILURES_MAX:
        return "ko"
    if consecutive:
        return "stumbling"
    if sched.storms.get(name) and sched.not_before.get(name, 0) > now:
        return "held"
    if name in running:
        return "running"
    return "ok" if sched.runs.get(name, 0) else "never"


def processes(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> tuple[Markup, list[Any]] | None:
    """Système › Processus : ce qui échoue d'abord, puis une carte par faculté ; l'historique à la console."""
    table = next((b for b in blocks if isinstance(b, Table)), None)
    if table is None:
        return None
    sched, now = ui.kernel.scheduler, ui.now()
    frame = ui.kernel.mind.frame()
    running = set(sched.running())
    rows = []
    for spec in sched.specs:
        due = call(sched.instances[spec.name].next_due, frame.root.slices.get(spec.owner), frame,
                   sched.last_run(spec.name), label=f"échéance de {spec.name}")
        nd = None if isinstance(due, Failed) else due
        floor = sched.not_before.get(spec.name, 0)
        if nd is not None and floor > nd:
            nd = floor
        last = sched.last_run(spec.name)
        error_at, error = sched.last_error.get(spec.name, (0, ""))
        state = _state(sched, spec.name, running, now)
        rows.append({
            "name": ui.names.process(spec.name), "tech": spec.name, "state": state,
            "faculty": ui.names.faculty(spec.owner), "lane": names.lane(spec.lane),
            "runs": sched.runs.get(spec.name, 0), "failures": sched.failures.get(spec.name, 0),
            "consecutive": sched.consecutive.get(spec.name, 0),
            "last": render.relative(last, now) if last else "jamais",
            "next": "en cours" if spec.name in running else
            render.relative(nd, now) if nd is not None and nd > now else "dès que possible" if nd is not None
            else "à un événement" if spec.wake_on else "rien de prévu",
            "error": names.detail(error) if error else "",
            "error_at": render.relative(error_at, now) if error_at else "",
        })
    order = {key: i for i, (key, _) in enumerate(STATES)}
    said = dict(STATES)
    for r in rows:
        r["said"] = said[r["state"]]
    trouble = sorted((r for r in rows if r["state"] in ("ko", "stumbling", "held")),
                     key=lambda r: (order[r["state"]], -r["consecutive"], r["name"]))
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["faculty"], []).append(r)
    faculties = [{"name": name, "rows": sorted(items, key=lambda r: (order[r["state"]], r["name"].casefold())),
                  "trouble": sum(1 for r in items if r["state"] in ("ko", "stumbling", "held"))}
                 for name, items in by.items()]
    faculties.sort(key=lambda f: (not f["trouble"], f["name"].casefold()))
    counts = [{"key": key, "label": label, "count": sum(1 for r in rows if r["state"] == key)} for key, label in STATES]
    total = len(rows) or 1
    left = 0.0
    for c in counts:
        c["x"], c["w"] = f"{100 * left / total:.3f}%", f"{100 * c['count'] / total:.3f}%"
        left += c["count"]
    got = render.block(table, ui.env(), query)
    as_table = "?" + urlencode({**query, f"vue_{got['id']}": "table"})
    rest = [b for b in blocks if b is not table and not isinstance(b, Stats)]
    return Markup(env.get_template("handmade/system/processes.html").render(
        total=len(rows), counts=[c for c in counts if c["count"]], trouble=trouble, faculties=faculties,
        failures=sum(r["failures"] for r in rows), as_table=as_table)), rest


#: chaque sorte d'effet en mots (la console n'a que « propriétaire:type ») : sa famille, son nom, ce que c'est
KINDS: dict[str, tuple[str, str, str]] = {
    "expression:episode.utterance": ("dit", "Ses messages",
                                     "ce qu'elle répond ou lance, livré aux écrans et au téléphone de la personne"),
    "runtime:episode.ended": ("dit", "Une réponse qui ne viendra pas",
                              "les écrans apprennent qu'aucune réponse ne viendra (une panne, un silence choisi)"),
    "body:body.fell_asleep": ("montre", "Elle s'endort", "ses écrans la montrent se coucher"),
    "body:body.woke": ("montre", "Elle se réveille", "ses écrans la montrent se lever"),
    "body:body.roused": ("montre", "On la réveille", "un réveil par API la tire du sommeil"),
    "world:world.intended": ("montre", "Un geste commence", "dans son monde : elle va quelque part, prend un objet"),
    "world:episode.started": ("montre", "Elle se met au travail", "son monde la montre occupée pendant qu'elle travaille"),
    "world:world.ended": ("montre", "Un geste s'achève", "son monde montre comment il a fini"),
    "world:world.changed": ("montre", "Ce qui l'occupe change", "ses écrans redessinent son monde"),
    "world:world.authored": ("montre", "Son monde, réécrit", "une opératrice l'a édité : les écrans le redessinent"),
    "runtime:effect.proposed": ("agit", "Une action, tout de suite",
                                "une action qui ne demande pas d'accord : elle part dès qu'elle est décidée"),
    "runtime:effect.resolved": ("agit", "Une action que tu as autorisée",
                                "elle part après ton accord : un mail, une réponse Teams, un git push…"),
    "email:effect.executed": ("agit", "Un mail parti", "elle apprend qu'il est parti, retouché ou non"),
    "teams:teams.settled": ("agit", "Une réponse Teams partie", "elle apprend qu'elle est partie, retouchée ou non"),
    "mcp:effect.executed": ("agit", "Ce qu'un service a rendu", "le résultat d'un appel à un service branché"),
    "forge:effect.executed": ("agit", "Une app installée", "une version de ses apps forgées, après ton accord"),
    "forge:effect.resolved": ("agit", "Une version d'app refusée", "mise de côté puis refusée : elle ne traîne plus"),
    "shares:shares.expired": ("range", "Un fichier envoyé expire", "ses octets sont effacés"),
    "attachments:attachments.expired": ("range", "Une pièce reçue expire", "ses octets sont effacés"),
}
#: les familles, dans l'ordre de la page
FAMILIES = (("dit", "Ce qu'elle dit"), ("montre", "Ce que montrent ses écrans"), ("agit", "Ce qu'elle fait au dehors"),
            ("range", "Le ménage"), ("autre", "Le reste"))
#: ce que devient chaque état dans la page : en route, à traiter, parti, vu
ROUTE, STUCK = ("pending", "running"), OUTBOX_PROBLEMS
#: des départs par page, des effets à traiter montrés avec leurs boutons
RECENT_PAGE, STUCK_SHOWN = 20, 8
#: les parts d'une barre, en mots
SEGMENTS = {"done": "parti", "route": "en route", "stuck": "à traiter", "seen": "vu, laissé"}


def _kind(ui: UI, effect: str) -> tuple[str, str, str]:
    owner, _, type_name = effect.partition(":")
    return KINDS.get(effect) or ("autre", ui.names.event(type_name or owner), effect)


def _capability(ui: UI, ev: Any) -> str:
    """L'action qu'une proposition fait partir (« email.send » : son nom), lue dans son événement."""
    try:
        data = json.loads(ev.data)
    except (TypeError, ValueError):
        return ""
    name = data.get("capability") if isinstance(data, dict) else None
    return ui.names.capability(name) if isinstance(name, str) and name else ""


def _segments(by: Mapping[str, int]) -> list[dict[str, Any]]:
    """Une barre empilée, de gauche à droite : parti, en route, à traiter, vu (en % du total)."""
    parts = (("done", by.get("done", 0)), ("route", sum(by.get(s, 0) for s in ROUTE)),
             ("stuck", sum(by.get(s, 0) for s in STUCK)), ("seen", by.get("seen", 0)))
    total = sum(n for _k, n in parts) or 1
    out, left = [], 0.0
    for key, n in parts:
        if n:
            out.append({"key": key, "x": round(100 * left / total, 2), "w": round(100 * n / total, 2), "n": n})
            left += n
    return out


def outbox(ui: UI, blocks: Sequence[Any], query: Mapping[str, str], forms: Mapping[str, Any]) -> Markup:
    """Système › File de sortie, dessinée : à quoi elle sert et où en est ce qui part (une ligne qui va du journal au
    départ), ce qui est à traiter (avec ses boutons), ce qui part par sorte, les derniers départs."""
    store, now = ui.kernel.mind.store, ui.now()
    o = JournalOutbox
    grouped = store.query_mind(select(o.effect, o.status, func.count(), func.max(o.seq)).group_by(o.effect, o.status))
    counts: dict[str, int] = {}
    kinds: dict[str, dict[str, Any]] = {}
    for effect, status, n, last in grouped:
        counts[status] = counts.get(status, 0) + int(n)
        k = kinds.setdefault(effect, {"by": {}, "last": 0})
        k["by"][status] = int(n)
        k["last"] = max(k["last"], int(last or 0))
    asked = str(query.get("etat", ""))[:40]
    status = asked if asked in OUTBOX_LABELS or asked in counts else ""
    where = (o.status == status,) if status else ()
    total = int(store.query_mind(select(func.count()).select_from(o).where(*where))[0][0])
    try:
        number = max(1, int(query.get("page", "1") or 1))
    except ValueError:
        number = 1
    number = min(number, max(1, -(-total // RECENT_PAGE)))
    recent = store.query_mind(select(o.key, o.seq, o.effect, o.status, o.attempts, o.last_error).where(*where)
                              .order_by(o.seq.desc(), o.key).limit(RECENT_PAGE).offset((number - 1) * RECENT_PAGE))
    stuck_total = sum(counts.get(s, 0) for s in STUCK)
    # « à traiter » suit le filtre : un état à traiter, lui seul ; un autre état, rien ; aucun, tous
    chosen = (status,) if status in STUCK else STUCK if not status else ()
    chosen_total = sum(counts.get(s, 0) for s in chosen)
    try:
        cards = max(1, int(query.get("page_problemes", "1") or 1))
    except ValueError:
        cards = 1
    cards = min(cards, max(1, -(-chosen_total // STUCK_SHOWN)))
    stuck = store.query_mind(select(o.key, o.seq, o.effect, o.status, o.last_error).where(o.status.in_(chosen))
                             .order_by(o.seq.desc(), o.key).limit(STUCK_SHOWN)
                             .offset((cards - 1) * STUCK_SHOWN)) if chosen_total else []
    seqs = {r[1] for r in recent} | {r[1] for r in stuck} | {k["last"] for k in kinds.values() if k["last"]}
    events = {ev.seq: ev for ev in store.get_events(seqs)} if seqs else {}

    def when(seq: int) -> str:
        ev = events.get(seq)
        return render.relative(ev.at, now) if ev is not None else ""

    def named(seq: int, effect: str) -> str:
        name = _kind(ui, effect)[1]
        action = _capability(ui, events[seq]) if seq in events and effect.startswith("runtime:effect.") else ""
        return f"{name} : {action}" if action else name

    query_kept = {k: v for k, v in query.items() if k != "flash"}
    back = f"{PREFIX}/systeme/sorties" + (f"?{urlencode(query_kept)}" if query_kept else "")
    families = []
    for key, title in FAMILIES:
        rows = []
        for effect, k in sorted(kinds.items(), key=lambda e: -sum(e[1]["by"].values())):
            fam, name, what = _kind(ui, effect)
            if fam != key:
                continue
            segments = _segments(k["by"])
            rows.append({"name": name, "what": what, "total": sum(k["by"].values()),
                         "stuck": sum(k["by"].get(s, 0) for s in STUCK), "segments": segments,
                         "bar": ", ".join(f"{SEGMENTS[g['key']]} {g['n']}" for g in segments), "last": when(k["last"])})
        if rows:
            families.append({"title": title, "rows": rows})
    page = Pager(number=number, size=RECENT_PAGE, total=total)
    stuck_tone = "danger" if counts.get("failed") or counts.get("orphan") else "warn" if stuck_total else "ok"
    return Markup(env.get_template("handmade/system/sorties.html").render(
        tone=stuck_tone, stuck_total=stuck_total, route=sum(counts.get(s, 0) for s in ROUTE),
        done=counts.get("done", 0), seen=counts.get("seen", 0),
        attempts=MAX_ATTEMPTS, base_s=int(RETRY_BASE_S), max_min=int(RETRY_MAX_S // 60),
        stale_min=int(STALE_AFTER_S // 60), csrf=getattr(forms, "csrf", ""), back=back,
        unknown=bool(asked and not status), chosen_total=chosen_total,
        stuck_pager=render._pager(Pager(param="page_problemes", number=cards, size=STUCK_SHOWN, total=chosen_total),
                                  query),
        stuck=[{"key": key, "seq": seq, "name": named(seq, effect), "when": when(seq),
                "state": OUTBOX_LABELS.get(st, st).capitalize(), "tone": OUTBOX_TONES.get(st, "warn"),
                "hint": OUTBOX_GUIDANCE[st],
                "error": names.detail(err) if err else "", "retry": st not in OUTBOX_SEEN_ONLY}
               for key, seq, effect, st, err in stuck],
        families=families,
        chips=[{"label": "tout", "href": f"{PREFIX}/systeme/sorties", "n": sum(counts.values()), "on": not status}] +
              [{"label": OUTBOX_LABELS.get(k, k), "href": f"{PREFIX}/systeme/sorties?" + urlencode({"etat": k}),
                "n": n, "on": k == status, "tone": OUTBOX_TONES.get(k, "")} for k, n in sorted(counts.items())],
        recent=[{"seq": seq, "name": named(seq, effect), "when": when(seq),
                 "state": OUTBOX_LABELS.get(st, st).capitalize(),
                 "tone": OUTBOX_TONES.get(st, ""), "plain": st == "done", "attempts": attempts,
                 "error": names.detail(err) if err else "", "tech": effect}
                for _key, seq, effect, st, attempts, err in recent],
        pager=render._pager(page, query), filtered=OUTBOX_LABELS.get(status, status)))


#: l'ordre des contrôles : ce qui est en panne, ce qui est dégradé, ce qui va
CHECK_ORDER = {health_m.KO: 0, health_m.DEGRADED: 1, health_m.OK: 2}
#: le titre du repli de la console qui redit les contrôles sans problème (ici, ses tuiles)
HEALTHY_FOLD = "Contrôles sans problème"
#: le repli technique de la santé (``inspector/pages/diagnostics.py``) que la page dessine elle-même
PROJECTIONS_FOLD = "Projections et performances"
#: ce que tient chaque projection, en mots (la console n'a que leur nom technique, montré à côté)
PROJECTIONS = {
    "memory_chunks": "Sa mémoire, découpée pour la recherche",
    "memory_extraction_queue": "Ce que sa mémoire doit encore relire",
    "memory_items": "Ses souvenirs et ses croyances",
    "memory_life": "Ce qu'elle sait de la vie des autres",
    "memory_readings": "Ses lectures",
    "memory_told": "Qui a entendu quoi",
    "received_files": "Les pièces qu'on lui envoie",
    "shared_files": "Les fichiers qu'elle envoie",
    "social_relations": "Ses relations",
    "thread": "Le fil des conversations",
}
#: le niveau d'une projection, en mots
TIERS = {Tier.T0: "dans la transaction", Tier.T1: "différée", Tier.T2: "différée, calcul lourd"}


def health(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup:
    """Système › Santé : le verdict, les dix contrôles en tuiles, les replis techniques de la console."""
    report = health_m.report(ui.kernel)
    checks = [{"name": diagnostics.CHECKS.get(c.name, c.name), "key": c.name,
               "state": diagnostics.STATES.get(c.state, c.state), "tone": diagnostics.TONES.get(c.state, "warn"),
               "summary": c.summary, "detail": "\n".join(c.detail),
               "href": f"{PREFIX}/{diagnostics.DESTINATIONS[c.name]}" if c.name in diagnostics.DESTINATIONS else ""}
              for c in sorted(report.checks, key=lambda c: CHECK_ORDER.get(c.state, 1))]
    problems = [c for c in checks if c["tone"] != "ok"]
    title = {health_m.OK: "Tous les contrôles sont au vert", health_m.DEGRADED: "Le fonctionnement est dégradé",
             health_m.KO: "Une panne demande ton attention"}.get(report.status) or \
        diagnostics.PHASES.get(report.phase, report.phase).replace("{her}", ui.her_name())
    for c in checks:
        if c["key"] == "projections":
            c["href"] = "#sys-projections"  # dessinées plus bas, sur la page même
    technical = [b for b in blocks if isinstance(b, Disclosure)
                 and b.title.split(" (")[0] not in (HEALTHY_FOLD, PROJECTIONS_FOLD)]
    folds = drawn_blocks.page(ui, technical, query)
    return Markup(env.get_template("handmade/system/health.html").render(
        title=title, her=ui.her_name(), tone=diagnostics.TONES.get(report.status, "warn"), ready=report.ready,
        checks=checks,
        problems=len(problems), failed=sum(1 for c in problems if c["tone"] == "danger"),
        healthy=len(checks) - len(problems), snapshot=ui.when_long(ui.now()),
        proj=projections(ui), folds=folds or ""))


def _arc(share: float) -> str:
    """L'arc rempli d'une jauge en demi-cercle (centre 60,60, rayon 50), de 0 à 1 ; vide : rien à tracer."""
    share = max(0.0, min(1.0, share))
    if share <= 0:
        return ""
    angle = math.pi * (1 - share)
    return f"M10,60 A50,50 0 0 1 {60 + 50 * math.cos(angle):.1f},{60 - 50 * math.sin(angle):.1f}"


def projections(ui: UI) -> dict[str, Any]:
    """Ses projections : combien sont à jour (une jauge), où chacune en est du journal, ce qui est en quarantaine,
    et les vues lentes de la console."""
    kernel = ui.kernel
    head = kernel.mind.head
    lag = kernel.projections.lag()
    stuck = Counter(name for name, _seq, _err in kernel.projections.quarantined)
    rows = []
    for p in sorted(kernel.registry.projectors.values(), key=lambda p: PROJECTIONS.get(p.name, p.name)):
        behind = max(0, lag.get(p.name, 0)) if p.tier is not Tier.T0 else 0
        held = stuck[p.name]
        rows.append({
            "name": PROJECTIONS.get(p.name, p.name), "tech": p.name, "version": p.version,
            "faculty": ui.names.faculty(p.owner), "tier": TIERS.get(p.tier, str(p.tier)), "behind": behind,
            "share": 100.0 if not behind or head <= 0 else round(100 * max(0, head - behind) / head, 1),
            "tone": "danger" if held else "warn" if behind else "ok",
            "state": f"{held} en quarantaine" if held else
            f"{behind} événement{'s' if behind > 1 else ''} de retard" if behind else "à jour"})
    up = sum(1 for r in rows if r["tone"] == "ok")
    slow = ui.inspection.slow()
    worst = max((t.max_us for _k, t in slow), default=0)
    return {
        "rows": rows, "up": up, "total": len(rows), "head": head, "arc": _arc(up / len(rows) if rows else 1.0),
        "behind": sum(r["behind"] for r in rows), "deferred": sum(1 for r in rows if r["tier"] != TIERS[Tier.T0]),
        "tone": "danger" if stuck else "warn" if up < len(rows) else "ok",
        "quarantine": [{"name": PROJECTIONS.get(n, n), "tech": n, "seq": seq, "href": f"{PREFIX}/evenement/{seq}",
                        "error": err[:300]} for n, seq, err in reversed(kernel.projections.quarantined)],
        "views": [{"name": k, "runs": t.runs, "last": t.last_us // 1000, "worst": t.max_us // 1000,
                   "share": round(100 * t.max_us / worst, 1) if worst else 0.0,
                   "last_share": round(100 * t.last_us / worst, 1) if worst else 0.0} for k, t in slow],
        "slow_ms": SLOW_US // 1000}
