"""Lecture des processus et anomalies, sans intervenir dans leur exécution."""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import runtime as rt
from mika.inspector import names
from mika.kernel.inspect import Badge, Column, Disclosure, Note, Ref, Row, Stat, Stats, Table, Text, When
from mika.runtime.health import PROCESS_FAILURES_MAX


def process_blocks(ui: Any, query: Any) -> list[Any]:
    sched = ui.kernel.scheduler
    running = set(sched.running())
    failing = [s for s in sched.specs if sched.consecutive.get(s.name, 0) >= PROCESS_FAILURES_MAX]

    def state(name: str) -> Badge:
        consecutive = sched.consecutive.get(name, 0)
        if consecutive:
            return Badge(f"{consecutive} échec(s) d’affilée", "danger" if consecutive >= PROCESS_FAILURES_MAX else "warn")
        if name in running:
            return Badge("en cours", "info")
        return Badge("en attente" if sched.runs.get(name, 0) else "pas encore exécuté", "muted")

    # Les problèmes restent visibles même lorsque la liste dépasse une page ; ensuite, l'ordre de l'ordonnanceur
    # (sa priorité : l'arbitre d'abord), le tri étant stable.
    specs = sorted(sched.specs, key=lambda s: (-sched.consecutive.get(s.name, 0), s.name not in running))
    rows = tuple(Row((ui.names.process(s.name), state(s.name), ui.names.faculty(s.owner), names.lane(s.lane),
                       sched.runs.get(s.name, 0), sched.failures.get(s.name, 0),
                       When(sched.last_run(s.name)) if sched.last_run(s.name) else "—",
                       Text(names.detail(sched.last_error.get(s.name, (0, ""))[1]) or "—", clamp=240),
                       Text(s.name, "mono")),
                      tone="danger" if sched.consecutive.get(s.name, 0) >= PROCESS_FAILURES_MAX else
                           "warn" if sched.consecutive.get(s.name, 0) else "") for s in specs)
    procs = Table((Column("processus", role="title"), Column("état", role="badge"), "faculté",
                   Column("voie", detail=True), Column("passages", "num"), Column("échecs", "num"),
                   "dernier passage", Column("dernière erreur", detail=True), Column("nom technique", detail=True)), rows,
                  title="Depuis le démarrage", layout="list",
                  caption="Les processus en échec précèdent ceux en cours, puis ceux en attente. Ces compteurs "
                          "repartent de zéro au démarrage. Le détail conserve la dernière erreur connue, même "
                          "si le processus a repris ; les échecs journalisés restent dans l’historique.")
    ctx = ui.inspection.context(query)
    failed, pager = ctx.older([rt.PROCESS_FAILED], 50)
    history = Table((Column("quand", "fit"), Column("processus", role="title"), Column("erreur", role="body")), tuple(
        Row((When(e.at), Text(ui.names.process(e.data.process), hint=e.data.process),
             Text(names.detail(e.data.error), clamp=240)), href=Ref("event", str(e.seq), "")) for e in failed),
        title="Échecs gardés au journal", empty="Aucun échec de processus au journal.", pager=pager,
        layout="list", link_label="Ouvrir l’événement")
    return [Stats((Stat("Processus", len(sched.specs)),
                   Stat("En cours", len(running), ", ".join(ui.names.process(n) for n in sorted(running))[:90]),
                   Stat("Échecs répétés", len(failing), "3 passages consécutifs ou plus",
                        "danger" if failing else ""),
                   Stat("Échecs depuis le démarrage", sum(sched.failures.values()), "",
                        "warn" if any(sched.failures.values()) else ""))), procs,
            Disclosure("Historique des échecs", (history,), open=bool(query.get("avant")))]


def anomaly_blocks(ui: Any) -> list[Any]:
    mind = ui.kernel.mind
    items = list(reversed(list(getattr(mind, "anomalies", ()) or ())))
    arbiter = list(reversed(list(getattr(ui.kernel.arbiter, "anomalies", ()) or ())))
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
    if not (items or arbiter or tainted):
        out.append(Note("Aucune anomalie enregistrée depuis le démarrage. Les traces du journal ci-dessous "
                        "décrivent aussi des opérations normales, comme un oubli ou une reconstruction.", "ok"))
    for title, values in (("Évaluations et réductions qui ont échoué", items), ("Anomalies de l'arbitre", arbiter)):
        if values:
            out.append(Table((Column("anomalie", role="body"),),
                             tuple(Row((Text(str(a), "mono", clamp=500),), tone="warn") for a in values),
                             title=title, layout="list"))
    out.append(Disclosure("Traces du journal", (Table((Column("quand", "fit"), Column("sorte", role="title"),
                                                       Column("détail", role="body")), tuple(
        (When(t.at), Badge(t.kind, "muted"), Text(json.dumps(t.detail, ensure_ascii=False, default=str), "mono", clamp=240))
        for t in traces), title="Traces du journal", empty="Aucune trace depuis le démarrage.", layout="list"),)))
    return out
