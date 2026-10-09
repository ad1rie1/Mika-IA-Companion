"""Lecture de la santé : problèmes d'abord, contrôles et détails techniques ensuite."""

from __future__ import annotations

import json
from typing import Any

from mika.inspector.catalog import Panel
from mika.kernel.inspect import Badge, Code, Column, Disclosure, Ref, Row, Table, Text
from mika.runtime import health

STATES = {"ok": "En forme", "degraded": "Dégradé", "ko": "En panne"}
TONES = {"ok": "ok", "degraded": "warn", "ko": "danger"}
CHECKS = {"journal": "Journal d’événements", "slices": "État des facultés", "loops": "Boucles de fonctionnement",
          "projections": "Projections", "processes": "Processus de fond", "outbox": "File de sortie",
          "llm": "Modèles", "lanes": "Files d’attente", "config": "Configuration lisible", "ports": "Branchements"}
DESTINATIONS = {"journal": "systeme/chronologie", "slices": "systeme/etat", "loops": "systeme/processus",
                "processes": "systeme/processus", "outbox": "systeme/sorties", "llm": "systeme/passerelle",
                "lanes": "decisions/en_cours", "config": "reglages/apercu", "ports": "reglages/apercu"}
#: le titre de la page hors marche ; arrêtée, elle est nommée par sa persona (ADR 0070)
PHASES = {"starting": "Démarrage en cours", "stopping": "Arrêt en cours", "stopped": "{her} est arrêtée"}


def health_page(ui: Any) -> dict[str, Any]:
    kernel = ui.kernel
    report = health.report(kernel)
    problems = sorted((c for c in report.checks if c.state != health.OK), key=lambda c: c.state != health.KO)
    healthy = [c for c in report.checks if c.state == health.OK]

    def checks(items, title: str, layout: str) -> Table:
        return Table((Column("Contrôle", role="title"), Column("État", role="badge"), Column("Constat", role="body")), tuple(
            Row((CHECKS.get(c.name, c.name), Badge(STATES.get(c.state, c.state), TONES.get(c.state, "warn")), c.summary),
                tone=TONES.get(c.state, "warn"),
                href=Ref("local", "/inspecteur/" + DESTINATIONS[c.name], "") if c.name in DESTINATIONS else None,
                detail=(Code("\n".join(c.detail), "Détail du contrôle"),) if c.detail else ()) for c in items),
            title=title, layout=layout, link_label="Ouvrir le diagnostic")

    blocks: list[Any] = []
    if problems:
        blocks.append(checks(problems, "Points à examiner", "cards"))
    if healthy:
        blocks.append(Disclosure(f"Contrôles sans problème ({len(healthy)})", (
            checks(healthy, "Contrôles sans problème", "list"),), open=not problems))
    lag = kernel.projections.lag()
    technical: list[Any] = [Table(("Projection", "Niveau", Column("Version", "num"), Column("Retard", "num")), tuple(
        (p.name, str(p.tier), p.version, "dans la transaction" if str(p.tier).endswith("T0") else lag.get(p.name, 0))
        for p in sorted(kernel.registry.projectors.values(), key=lambda p: p.name)), title="Projections")]
    if kernel.projections.quarantined:
        technical.append(Table(("Projection", "Événement", "Erreur"), tuple(
            (name, Ref("event", str(seq), str(seq)), Text(err, "muted", clamp=200))
            for name, seq, err in reversed(kernel.projections.quarantined)), title="Quarantaine"))
    slow = ui.inspection.slow()
    if slow:
        technical.append(Table(("Vue", Column("Passages", "num"), Column("Dernière (ms)", "num"), Column("Pire (ms)", "num")),
            tuple((k, t.runs, t.last_us // 1000, t.max_us // 1000) for k, t in slow), title="Vues lentes"))
    blocks.append(Disclosure("Projections et performances", tuple(technical), open=bool(kernel.projections.quarantined)))
    blocks.append(Disclosure("Sonde publique (/health)", (Code(json.dumps(report.public(), indent=1)),)))
    title = {health.OK: "Tous les contrôles sont au vert", health.DEGRADED: "Le fonctionnement est dégradé",
             health.KO: "Une panne demande ton attention"}.get(report.status) or PHASES.get(report.phase, report.phase).replace("{her}", ui.her_name())
    return {"blocks": blocks, "panel": Panel("health_summary.html", {
        "health_title": title, "health_tone": TONES.get(report.status, "warn"),
        "health_ready": report.ready, "health_checked": len(report.checks), "health_healthy": len(healthy),
        "health_failed": sum(c.state == health.KO for c in problems), "health_problems": len(problems),
        "health_snapshot": ui.when_long(ui.now()),
    })}
