"""Les processus et les anomalies : leur lecture, et ce que la console y répare (ADR 0234) — une tranche corrompue
se reconstruit en ligne (``rebuildable`` dit laquelle), un processus en échec se réessaie tout de suite. Les gestes
eux-mêmes sont dans ``inspector/pages/system.py`` (``rebuild_post``, ``retry_post``)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mika.contracts import runtime as rt
from mika.inspector import names
from mika.kernel.inspect import (
    Badge,
    Column,
    Disclosure,
    Note,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    plural,
)
from mika.runtime.health import PROCESS_FAILURES_MAX


def process_blocks(ui: Any, query: Any) -> list[Any]:
    sched = ui.kernel.scheduler
    running = set(sched.running())
    failing = [s for s in sched.specs if sched.consecutive.get(s.name, 0) >= PROCESS_FAILURES_MAX]

    def state(name: str) -> Badge:
        consecutive = sched.consecutive.get(name, 0)
        if consecutive:
            return Badge(f"{plural(consecutive, 'échec', 'échecs')} d’affilée",
                         "danger" if consecutive >= PROCESS_FAILURES_MAX else "warn")
        if name in running:
            return Badge("en cours", "info")
        return Badge("en attente" if sched.runs.get(name, 0) else "pas encore exécuté", "muted")

    # Les problèmes restent visibles même lorsque la liste dépasse une page ; ensuite, l'ordre de l'ordonnanceur
    # (sa priorité : l'arbitre d'abord), le tri étant stable.
    specs = sorted(sched.specs, key=lambda s: (-sched.consecutive.get(s.name, 0), s.name not in running))
    rows = tuple(Row((ui.names.process(s.name), state(s.name), ui.names.faculty(s.owner),
                       names.process_lane(s.lane) or None,  # sans voie qui dise quelque chose : « — »
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


def tainted_said(tainted: Mapping[str, int]) -> str:
    """Ce que disent Anomalies et Diagnostic avancé d'une tranche corrompue : chacune et l'événement où son réducteur a
    levé, quand la reconstruction sert — une fois le réducteur corrigé : avec le même code, le rejeu lève au même
    événement et la tranche repasse corrompue (audit du 2026-11-05, C8-14) —, puis les deux façons de la faire : en
    ligne, par le geste « Reconstruire » de la console, le serveur relancé sur ce code (ADR 0234) ; ou serveur arrêté,
    par la commande exacte (``rebuild`` et leurs clés, ``app/cli/journal.py`` : elle tient le dossier de données)."""
    many = len(tainted) > 1
    return (("Tranches corrompues" if many else "Tranche corrompue") + " (un réducteur a levé) : "
            + ", ".join(f"{o} (au n° {s})" for o, s in tainted.items())
            + (". Leur état est figé jusqu'à leur reconstruction" if many else
               ". Son état est figé jusqu'à sa reconstruction")
            + " : corriger d'abord le réducteur — avec le même code, le rejeu lève au même événement et la tranche "
              "repasse corrompue —, puis, le serveur relancé sur ce code, « Reconstruire » dans la console (en "
              f"ligne, sans l'arrêter), ou, serveur arrêté, « mika rebuild {' '.join(tainted)} ».")


#: le tableau des tranches corrompues d'Anomalies, une ligne par faculté (la page dessinée y pose « Reconstruire »)
TAINTED_TITLE = "Tranches corrompues"


def rebuildable(kernel: Any, owner: str) -> bool:
    """Une tranche que la reconstruction en ligne rejoue (``Mind.rebuild``) : celle d'une faculté composée, pas
    volatile — une tranche volatile ne se rejoue pas, ni au démarrage ni à une reconstruction : le geste la laisserait
    corrompue en disant le contraire."""
    faculty = kernel.registry.faculties.get(owner)
    return faculty is not None and not getattr(faculty, "volatile", False)


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
        out.append(Note(tainted_said(tainted), "danger"))
        out.append(Table((Column("faculté", role="title"), Column("corrompue au", "fit"),
                          Column("faculté (clé)", detail=True)),
                         tuple(Row((ui.names.faculty(o), Ref("event", str(s), f"n° {s}"), Text(o, "mono")),
                                   href=Ref("event", str(s), ""), tone="danger") for o, s in tainted.items()),
                         title=TAINTED_TITLE, layout="list",
                         caption="Chacune et l'événement où son réducteur a levé. La reconstruction relit tout le "
                                 "journal ; elle ne sert qu'une fois le réducteur corrigé."))
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
