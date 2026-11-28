"""Lecture de la santé : problèmes d'abord, contrôles et détails techniques ensuite.

La page tient les dix contrôles du rapport de santé (``runtime/health.py``, ceux que publie ``/health``), puis deux
tuiles de la console qui n'en sont pas (``console_tiles``) : les sauvegardes et les anomalies depuis le démarrage. La
sonde publique ne les voit jamais. La page dessinée (``app/handmade/tabs/system.py::health``) lit ces blocs, la
console en MCP aussi (ADR 0177) : leurs titres sont ici, nommés une fois.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mika.inspector.catalog import Panel
from mika.inspector.render import PREFIX
from mika.kernel.faculty import Tier
from mika.kernel.inspect import Badge, Code, Column, Disclosure, Ref, Row, Table, Text, plural
from mika.runtime import health

STATES = {"ok": "En forme", "degraded": "Dégradé", "ko": "En panne"}
TONES = {"ok": "ok", "degraded": "warn", "ko": "danger"}
CHECKS = {"journal": "Journal d’événements", "slices": "État des facultés", "loops": "Boucles de fonctionnement",
          "projections": "Projections", "processes": "Processus de fond", "outbox": "File de sortie",
          "llm": "Modèles", "lanes": "Files d’attente", "config": "Configuration lisible", "ports": "Branchements"}
#: la page où regarder ce qu'un contrôle dit (la santé, et l'accueil, qui y mène chaque contrôle qui ne va pas) : celle
#: qui montre ce que son constat dit — le journal, son dernier instantané sur Stockage et sauvegardes. Un contrôle
#: qu'aucune page ne montre mieux que sa tuile n'y est pas (les boucles du noyau : son constat dit le geste) : il mène
#: à la santé générale (``check_href``)
DESTINATIONS = {"journal": "systeme/stockage", "slices": "systeme/etat", "processes": "systeme/processus",
                "outbox": "systeme/sorties", "llm": "systeme/passerelle", "lanes": "decisions/en_cours",
                "config": "reglages/apercu", "ports": "reglages/apercu"}
#: les contrôles qu'une page montre sous un autre nom que le leur (Stockage et sauvegardes dit les événements du
#: journal et son dernier instantané) : l'accueil dit leur nom devant leur constat, comme pour un contrôle qui mène
#: à la santé générale. La file de sortie, les processus, les réglages (configuration, branchements) se lisent sur
#: une page qui dit déjà leur sujet
UNNAMED_BY_PAGE = frozenset({"journal"})
#: les sauvegardes : leur carte, sur Stockage et sauvegardes (son ancre, ``handmade/systeme/stockage.html``) — une
#: autre adresse que le haut de la page, où mène le journal : l'accueil, qui garde une ligne par adresse
#: (``app/handmade/home.py::_merged``), ne fond jamais une sauvegarde à faire dans un journal en retard
BACKUPS_PAGE = "systeme/stockage#sys-store-saves"
#: la page des contrôles eux-mêmes (Système › Santé générale) : celle d'un contrôle sans page à lui
HEALTH = "systeme/sante"
#: le titre de la page hors marche ; arrêtée, elle est nommée par sa persona (ADR 0070)
PHASES = {"starting": "Démarrage en cours", "stopping": "Arrêt en cours", "stopped": "{her} est arrêtée"}
#: les titres des blocs de la page, que la page dessinée lit (un titre changé ici l'y suit)
PROBLEMS_TITLE, HEALTHY_TITLE = "Points à examiner", "Contrôles sans problème"
PROJECTIONS_TITLE, QUARANTINE_TITLE, SLOW_TITLE = "Projections", "Quarantaine", "Vues lentes"
TECHNICAL_FOLD, PROBE_FOLD = "Projections et performances", "Sonde publique (/health)"
#: le niveau d'une projection, en mots
TIERS = {Tier.T0: "dans la transaction", Tier.T1: "différée", Tier.T2: "différée, calcul lourd"}
#: l'état d'une tuile des sauvegardes, par le ton de ``backup_state`` (``inspector/pages/system.py``) : son état de
#: contrôle et ses mots
BACKUP_STATES = {"ok": (health.OK, "À jour"), "warn": (health.DEGRADED, "À faire"), "danger": (health.KO, "En échec")}


@dataclass(frozen=True, slots=True)
class Tile:
    """Une tuile de la santé : un contrôle du rapport, ou un point que la console y ajoute (``console_tiles``).
    ``state`` : ``ok``, ``degraded`` ou ``ko`` ; ``said`` : ses mots ; ``page`` : la page de son diagnostic, sans
    préfixe (vide : aucune)."""

    key: str
    name: str
    state: str
    said: str
    summary: str
    page: str = ""
    detail: tuple[str, ...] = ()


def check_href(name: str) -> str:
    """L'adresse de la page où regarder ce que dit un contrôle (``DESTINATIONS``), la santé générale à défaut."""
    return f"{PREFIX}/" + DESTINATIONS.get(name, HEALTH)


def console_tiles(ui: Any, backups: tuple[str, str]) -> list[Tile]:
    """Ce que la santé générale montre en plus des contrôles, comme l'accueil : les sauvegardes (``backups`` : le ton
    et la phrase de ``backup_state`` ; aucune tuile quand rien ne les note) et les anomalies depuis le démarrage — ce
    qui a échoué sans corrompre dans ses évaluations, ses réductions et à l'arbitre. Jamais dans ``health.report`` :
    la sonde publique ``/health`` ne publie que ses contrôles."""
    out: list[Tile] = []
    tone, said = backups
    if tone in BACKUP_STATES:
        state, words = BACKUP_STATES[tone]
        out.append(Tile("backups", "Sauvegardes", state, words, said, BACKUPS_PAGE))
    failed = len(getattr(ui.kernel.mind, "anomalies", ()) or ())
    arbiter = len(getattr(ui.kernel.arbiter, "anomalies", ()) or ())
    parts = [*([plural(failed, "évaluation ou réduction échouée", "évaluations ou réductions échouées")] if failed
               else []),
             *([plural(arbiter, "anomalie de l’arbitre", "anomalies de l’arbitre")] if arbiter else [])]
    out.append(Tile("anomalies", "Anomalies depuis le démarrage", health.DEGRADED if parts else health.OK,
                    "À examiner" if parts else "Aucune",
                    " ; ".join(parts) or "aucune évaluation, réduction ni décision de l’arbitre n’a échoué",
                    "systeme/anomalies"))
    return out


def verdict(status: str, states: Sequence[str], her: str) -> tuple[str, str]:
    """Le titre du bilan et son ton. ``status`` : celui du rapport (son état, ou sa phase hors marche) ; ``states`` :
    l'état de chaque tuile, celles de la console comprises, qui l'aggravent sans jamais l'adoucir — une sauvegarde à
    faire n'est pas un fonctionnement dégradé, mais un point qui demande ton attention."""
    if status not in TONES:
        return PHASES.get(status, status).replace("{her}", her), "warn"
    if health.KO in (status, *states):
        return "Une panne demande ton attention", "danger"
    if status == health.DEGRADED:
        return "Le fonctionnement est dégradé", "warn"
    problems = sum(1 for s in states if s != health.OK)
    if problems:
        return f"{plural(problems, 'point demande', 'points demandent')} ton attention", "warn"
    return "Tous les contrôles sont au vert", "ok"


def all_clear(points: int) -> str:
    """Ce que dit le bilan quand rien ne va mal : combien de points il a vérifiés — les contrôles et les tuiles de la
    console, que ses compteurs comptent aussi (« sans problème ») ; ces tuiles ne sont pas des contrôles."""
    said = "le seul point vérifié" if points == 1 else "les " + plural(points, "point vérifié", "points vérifiés")
    return f"Aucun problème sur {said}."


def health_page(ui: Any, backups: tuple[str, str] = ("", "")) -> dict[str, Any]:
    """Système › Santé générale : ses tuiles (les contrôles du rapport, puis celles de la console, ``console_tiles``)
    — en cartes ce qui ne va pas, en panne d'abord ; replié, ce qui va —, ses projections et la sonde publique.
    ``backups`` : l'état des sauvegardes (``backup_state``), que ``sante`` lui passe (``inspector/pages/system.py``
    importe ce module). Le rapport se calcule une fois."""
    kernel = ui.kernel
    report = health.report(kernel)
    tiles = [Tile(c.name, CHECKS.get(c.name, c.name), c.state, STATES.get(c.state, c.state), c.summary,
                  DESTINATIONS.get(c.name, ""), c.detail) for c in report.checks]
    if report.ready:
        tiles += console_tiles(ui, backups)
    # ce qui est en panne d'abord ; à état égal, les contrôles avant les tuiles de la console (le tri est stable)
    problems = sorted((t for t in tiles if t.state != health.OK), key=lambda t: t.state != health.KO)
    healthy = [t for t in tiles if t.state == health.OK]

    def listed(items: Sequence[Tile], title: str, layout: str) -> Table:
        # la clé de chaque tuile, repliée : la page dessinée en a besoin (l'ancre des projections)
        return Table((Column("Contrôle", role="title"), Column("État", role="badge"), Column("Constat", role="body"),
                      Column("clé", detail=True)), tuple(
            Row((t.name, Badge(t.said, TONES.get(t.state, "warn"), key=t.state), t.summary, Text(t.key, "mono")),
                tone=TONES.get(t.state, "warn"),
                href=Ref("local", f"{PREFIX}/" + t.page, "") if t.page else None,
                detail=(Code("\n".join(t.detail), "Détail du contrôle"),) if t.detail else ()) for t in items),
            title=title, layout=layout, link_label="Ouvrir le diagnostic")

    blocks: list[Any] = []
    if problems:
        blocks.append(listed(problems, PROBLEMS_TITLE, "cards"))
    if healthy:
        blocks.append(Disclosure(f"{HEALTHY_TITLE} ({len(healthy)})", (
            listed(healthy, HEALTHY_TITLE, "list"),), open=not problems))
    lag = kernel.projections.lag()
    technical: list[Any] = [Table(("Projection", "Faculté", "Niveau", Column("Version", "num"), Column("Retard", "num")),
        tuple((p.name, ui.names.faculty(p.owner), TIERS.get(p.tier, str(p.tier)), p.version,
               "—" if p.tier is Tier.T0 else lag.get(p.name, 0))
              for p in sorted(kernel.registry.projectors.values(), key=lambda p: p.name)), title=PROJECTIONS_TITLE)]
    if kernel.projections.quarantined:
        technical.append(Table(("Projection", "Événement", "Erreur"), tuple(
            (name, Ref("event", str(seq), str(seq)), Text(err, "muted", clamp=200))
            for name, seq, err in reversed(kernel.projections.quarantined)), title=QUARANTINE_TITLE))
    slow = ui.inspection.slow()
    if slow:
        technical.append(Table(("Vue", Column("Passages", "num"), Column("Dernière (ms)", "num"), Column("Pire (ms)", "num")),
            tuple((k, t.runs, t.last_us // 1000, t.max_us // 1000) for k, t in slow), title=SLOW_TITLE))
    blocks.append(Disclosure(TECHNICAL_FOLD, tuple(technical), open=bool(kernel.projections.quarantined)))
    blocks.append(Disclosure(PROBE_FOLD, (Code(json.dumps(report.public(), indent=1)),)))
    title, tone = verdict(report.status, [t.state for t in tiles], ui.her_name())
    return {"blocks": blocks, "panel": Panel("health_summary.html", {
        "health_title": title, "health_tone": tone,
        "health_ready": report.ready, "health_all_clear": all_clear(len(tiles)), "health_healthy": len(healthy),
        "health_failed": sum(t.state == health.KO for t in problems), "health_problems": len(problems),
        "health_snapshot": ui.when_long(ui.now()),
    })}
