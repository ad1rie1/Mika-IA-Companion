"""Activité › Projets : ses onglets, chacun dans sa forme (ADR 0177). « Créer un projet », l'action de la destination,
reste dans la barre de titre, à droite, sur chacun d'eux (``head_actions``).

- Ses projets : ses projets en chiffres (ce qui attend ton accord en tête quand il y en a), puis une entrée par
  projet, en deux colonnes sur un grand écran — son mode et son état, où il en est, ses objectifs en jauge, sa
  prochaine exécution et la dernière, pour qui ; le reste (priorité, plage, agenda, outils, dépôt, ce qui sort)
  replié. La bascule « Fiches / Tableau » et la pagination restent celles de la console.
- Exécutions : ce qui tourne en ce moment, puis le fil de ses exécutions jour par jour — le projet et l'objectif
  visé, le verdict et sa preuve, le compte rendu cité, le commit laissé dans l'atelier, l'épisode (prompt, outils,
  appels).
- Décisions techniques : rangées par projet, chacune comme une décision d'architecture — son numéro, la question,
  ce qui est choisi, pourquoi (en clair, c'est ce qui compte), qui l'a posée et quand ; une décision remplacée
  s'estompe.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, Tab, blank, gauge, instant, raw_lines, rest, text, tiles
from mika.app.handmade.tabs.decisions import by_day

STYLES = ("handmade/projets.css",)
#: les chiffres de la liste, dans l'ordre de la bande (ce qui attend ton accord passe devant quand il y en a)
FIGURES = ("Actifs", "En pause", "Objectifs", "Exécutions (24 h)", "Attendent ton accord", "Archivés")
#: ce que la liste replie dans le détail d'un projet, que la page montre déjà
SHOWN = ("priorité", "plage de travail", "agenda", "outils", "dépôt distant", "ce qui sort")


def _cell(c: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    return None if blank(c) else c


# ── Ses projets ───────────────────────────────────────────────────────────


def _project(line: Line) -> dict[str, Any]:
    state = line.get("état")
    return {"title": line["projet"], "href": line.href, "mode": line.get("mode"), "state": state,
            "waiting": line.tone == "warn", "archived": line.tone == "muted",
            "who": _cell(line.get("pour qui")), "goals": gauge(line.get("objectifs")),
            "goals_text": line.text("objectifs"), "next": _cell(line.get("prochaine exécution")),
            "last": _cell(line.get("dernière")), "where": _cell(line.get("où il en est")),
            "facts": [{"label": label, "value": line.get(label)} for label in SHOWN if not blank(line.get(label))],
            "detail": rest(line, SHOWN), "open": line.open}


def tous(got: Got) -> Markup | None:
    """Projets › Ses projets : ses chiffres, puis une entrée par projet."""
    t = got.table("Projets")
    if t is None:
        return None
    s = tiles(got.stats())
    waiting = s.get("Attendent ton accord")
    order = (("Attendent ton accord",) if waiting and text(waiting.get("value")) not in ("0", "") else ()) + FIGURES
    band = {"t": "stats", "title": "", "items": [s[label] for label in dict.fromkeys(order) if label in s]}
    return got.draw("handmade/projets/tous.html", t=t, band=band, items=[_project(x) for x in got.lines("Projets")],
                    notes=got.notes())


# ── Exécutions ────────────────────────────────────────────────────────────


def _run(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    at = instant(raw.get("quand"))
    commit = line.get("commit")
    return {"at": at, "when": line.get("quand"),
            "hm": got.ui.kernel.mind.frame().local(at).strftime("%H:%M") if at else "",
            "project": line["projet"], "objective": _cell(line.get("objectif")),
            "verdict": _cell(line.get("verdict")), "proof": _cell(line.get("preuve")),
            "summary": _cell(line.get("compte rendu")), "commit": _cell(commit), "href": line.href,
            "mode": line.text("mode"), "tools": "" if blank(line.get("outils utilisés")) else line.text("outils utilisés"),
            "episode": _cell(line.get("épisode")), "detail": rest(line, ("mode", "outils utilisés", "épisode")),
            "blocked": text(line.get("verdict")) == "bloqué"}


def executions(got: Got) -> Markup | None:
    """Projets › Exécutions : ce qui tourne, puis ses exécutions jour par jour."""
    t = got.table("Les exécutions")
    if t is None:
        return None
    items = [_run(got, x, r) for x, r in zip(got.lines("Les exécutions"), raw_lines(got, t), strict=False)]
    notes = got.notes()
    live = [n for n in notes if n.get("tone") == "info" and str(n.get("text") or "").startswith("En ce moment")]
    return got.draw("handmade/projets/executions.html", t=t, days=by_day(got, items), live=live,
                    notes=[n for n in notes if n not in live])


# ── Décisions techniques ──────────────────────────────────────────────────


def _decision(line: Line) -> dict[str, Any]:
    status = line.get("statut")
    return {"n": line.text("n°"), "question": line["la question"], "choice": _cell(line.get("ce qui est choisi")),
            "status": status, "live": text(status) == "en vigueur", "by": line.text("posée par"),
            "when": line.get("quand"), "why": _cell(line.get("pourquoi")), "href": line.href,
            "project": line["projet"]}


def decisions(got: Got) -> Markup | None:
    """Projets › Décisions techniques : rangées par projet, chacune avec ce qui est choisi et pourquoi."""
    t = got.table("Décisions techniques")
    if t is None:
        return None
    groups: list[dict[str, Any]] = []
    for d in (_decision(x) for x in got.lines("Décisions techniques")):
        name = text(d["project"])
        if not groups or groups[-1]["name"] != name:
            groups.append({"name": name, "href": d["href"], "items": []})
        groups[-1]["items"].append(d)
    return got.draw("handmade/projets/decisions.html", t=t, groups=groups, notes=got.notes())


TABS: dict[str, Any] = {
    "projets/tous": Tab(tous, *STYLES),
    "projets/toutes_executions": Tab(executions, *STYLES),
    "projets/toutes_decisions": Tab(decisions, *STYLES),
}
