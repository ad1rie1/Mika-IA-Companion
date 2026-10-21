"""Système, dessiné (ADR 0121) : les pages où l'opératrice cherche ce qui ne va pas.

Processus : ses processus de fond lus à l'ordonnanceur, comme l'onglet de la console — d'abord ce qui échoue, avec
sa dernière erreur en clair et son prochain essai ; puis tous les autres, une carte par faculté, une ligne chacun.
L'historique des échecs gardés au journal reste celui de la console (sa pagination à curseur).

Sorties : ses chiffres, ses états et ce qui est à traiter (ses boutons) restent à la console ; seule la liste des
effets se redessine, une ligne par effet — ce qu'il fait partir, son état, son événement.

Santé : le bilan lu au rapport de santé, comme l'onglet de la console — son verdict, puis ses dix contrôles en
tuiles, ce qui ne va pas d'abord, chacun avec son constat, son détail et la page de son diagnostic ; les projections
et la sonde publique en replis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade.lists import Roles, listing
from mika.inspector import names, render
from mika.inspector.pages import diagnostics
from mika.inspector.pages.system import OUTBOX_LABELS
from mika.inspector.ui import PREFIX, UI, env
from mika.kernel.inspect import Disclosure, Stats, Table
from mika.runtime import health as health_m
from mika.runtime.boundary import Failed, call

#: échecs d'affilée qui font une panne (comme la santé et l'onglet de la console)
FAILING = 3
#: l'ordre des états, du plus urgent au plus calme, et ce que chacun dit
STATES = (("ko", "en échec"), ("stumbling", "a trébuché"), ("held", "retenu"), ("running", "en cours"),
          ("ok", "passé"), ("never", "pas encore exécuté"))


def _state(sched: Any, name: str, running: set[str], now: int) -> str:
    consecutive = sched.consecutive.get(name, 0)
    if consecutive >= FAILING:
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


#: l'état ordinaire d'un effet (parti) : il se tait
OUTBOX_DONE = OUTBOX_LABELS["done"]
#: la liste des effets, en lignes : ce qu'il fait partir en titre, son état, son événement à droite
OUTBOX_ROLES = Roles(title="effet", badges=("état",), time="n°")


def outbox(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> tuple[Markup, list[Any]] | None:
    """Système › Sorties : la liste des effets, sous les chiffres et le panneau « à traiter » de la console."""
    table = next((b for b in blocks if isinstance(b, Table)), None)
    if table is None:
        return None
    section = {**listing(table, ui.env(), query, roles=OUTBOX_ROLES), "kind": "sorties",
               "link_label": "Voir l'événement"}
    for row in section["rows"]:  # parti du premier coup : l'ordinaire se tait, l'écart se voit
        row["badges"] = [b for b in row["badges"] if b.get("text") != OUTBOX_DONE]
        row["fields"] = [f for f in row["fields"] if not (f["label"] == "essais" and f["value"].get("text") == "1")]
        row["detail"] = []  # sa clé technique : l'info-bulle de son titre
    return Markup(env.get_template("handmade/shared/lists.html").render(
        counts=[], facts=[], sections=[section], notes=[])), [b for b in blocks if b is not table]


#: l'ordre des contrôles : ce qui est en panne, ce qui est dégradé, ce qui va
CHECK_ORDER = {health_m.KO: 0, health_m.DEGRADED: 1, health_m.OK: 2}
#: le titre du repli de la console qui redit les contrôles sans problème (ici, ses tuiles)
HEALTHY_FOLD = "Contrôles sans problème"


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
    technical = [b for b in blocks if isinstance(b, Disclosure) and b.title.split(" (")[0] != HEALTHY_FOLD]
    folds = drawn_blocks.page(ui, technical, query)
    return Markup(env.get_template("handmade/system/health.html").render(
        title=title, her=ui.her_name(), tone=diagnostics.TONES.get(report.status, "warn"), ready=report.ready,
        checks=checks,
        problems=len(problems), failed=sum(1 for c in problems if c["tone"] == "danger"),
        healthy=len(checks) - len(problems), snapshot=ui.when_long(ui.now()),
        folds=folds or ""))
