"""Activité › Projets : ses onglets, chacun dans sa forme (ADR 0177). « Créer un projet », l'action de la destination,
reste dans la barre de titre, à droite, sur chacun d'eux (``head_actions``).

- Ses projets, la page d'ensemble (ADR 0281) : « À faire » en tête — ce qui t'attend dans tous ses projets, dans
  l'ordre où s'en occuper, chaque ligne nommant son projet et menant là où elle se règle —, ses projets en chiffres
  (ce qui t'attend en tête quand il y en a), puis une liste, une rangée par projet sous des colonnes nommées — son
  nom et où il en est (une ligne), son mode et son état, combien de choses t'y attendent, ses objectifs en jauge, sa
  prochaine exécution et la dernière, pour qui ; le reste (priorité, plage, agenda, outils, dépôt, ce qui sort)
  replié sous la rangée ; enfin les liens entre projets : qui lit qui, ce que le lien donne, les demandes en cours.
  La bascule « Fiches / Tableau » et la pagination restent celles de la console.
- Exécutions : ce qui tourne en ce moment, puis le fil de ses exécutions jour par jour — le projet et l'objectif
  visé, le verdict et sa preuve, le compte rendu cité, le commit laissé dans l'atelier, l'épisode (prompt, outils,
  appels). Une exécution se met en forme par ``run``, que l'onglet Exécutions de la fiche d'un projet partage
  (``subject.py``), comme le fil de ``handmade/projets/_runs.html``.
- Décisions techniques : rangées par projet, chacune comme une décision d'architecture — son numéro, la question,
  ce qui est choisi, pourquoi (en clair, c'est ce qui compte), qui l'a posée et quand ; une décision remplacée
  s'estompe.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import (
    Got,
    Line,
    Tab,
    blank,
    gauge,
    instant,
    lines,
    raw_lines,
    rest,
    text,
    tiles,
)
from mika.app.handmade.tabs.decisions import by_day

STYLES = ("handmade/projets.css",)
#: le chiffre de ce qui attend quelqu'un, et les tables que la page d'ensemble pose autour de la liste (les titres
#: de la vue : ``projects.inspect_todo.EVERYWHERE_TITLE``, ``projects.inspect.LINKED_TITLE``)
WAITING, TODO_TITLE, LINKED_TITLE = "T'attendent", "À faire", "Dépendances entre projets"
#: les chiffres de la liste, dans l'ordre de la bande (ce qui attend ton accord passe devant quand il y en a)
FIGURES = ("Actifs", "En pause", "Objectifs", "Exécutions (24 h)", WAITING, "Archivés")
#: ce que la liste replie dans le détail d'un projet, que la page montre déjà
SHOWN = ("priorité", "plage de travail", "agenda", "outils", "dépôt distant", "ce qui sort")


def _cell(c: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    return None if blank(c) else c


# ── Ses projets ───────────────────────────────────────────────────────────


def _project(line: Line) -> dict[str, Any]:
    state, where = line.get("état"), line.get("où il en est")
    return {"title": line["projet"], "href": line.href, "mode": line.get("mode"), "state": state,
            "waiting": line.tone == "warn", "archived": line.tone == "muted",
            "awaits": _cell(line.get("t'attend")),
            "who": _cell(line.get("pour qui")), "goals": gauge(line.get("objectifs")),
            "goals_text": line.text("objectifs"), "next": _cell(line.get("prochaine exécution")),
            "last": _cell(line.get("dernière")), "where": "" if blank(where) else text(where),
            "facts": [{"label": label, "value": line.get(label)} for label in SHOWN if not blank(line.get(label))],
            "detail": rest(line, SHOWN), "open": line.open}


def tous(got: Got) -> Markup | None:
    """Projets › Ses projets : ses chiffres, puis une rangée par projet."""
    t = got.table("Projets")
    if t is None:
        return None
    s = tiles(got.stats())
    waiting = s.get(WAITING)
    order = ((WAITING,) if waiting and text(waiting.get("value")) not in ("0", "") else ()) + FIGURES
    band = {"t": "stats", "title": "", "items": [s[label] for label in dict.fromkeys(order) if label in s]}
    todo = got.table(TODO_TITLE)
    linked = got.table(LINKED_TITLE)
    # les liens entre projets, une ligne chacun (une table à quatre colonnes s'écrase sur un écran étroit)
    links = [{"reader": x.get("le projet"), "target": x.get("lit"), "gives": x.text("ce qu'il en reçoit"),
              "off": x.tone == "muted", "asks": _cell(x.get("ses demandes"))} for x in lines(linked)]
    return got.draw("handmade/projets/tous.html", t=t, band=band, items=[_project(x) for x in got.lines("Projets")],
                    notes=got.notes(), waiting=_waiting(todo), links=links,
                    links_help=(linked or {}).get("caption", ""))


def _waiting(t: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """« À faire » : une ligne par attente, avec son projet (``handmade/projets/_todo.html``)."""
    if t is None:
        return None
    # combien attendent : une ligne peut en résumer plusieurs (les éléments d'une liste) — le titre de la table le
    # dit alors ; sinon c'est le nombre de ses lignes, que la console a ôté du titre
    counted = re.search(r"\((\d+)\)$", str(t.get("title") or ""))
    return {"empty": t.get("empty", ""), "caption": t.get("caption", ""),
            "count": int(counted.group(1)) if counted else int(t.get("count") or 0),
            "items": [{"kind": x.get("quoi"), "text": x.text("de quoi il s'agit"), "since": x.get("depuis"),
                       "who": x.get("attend"), "go": x.get("le geste"), "project": x.get("projet")}
                      for x in lines(t)]}


# ── Exécutions ────────────────────────────────────────────────────────────


#: les onglets de son épisode qu'une exécution lie un à un, quand sa vue les donne (la fiche d'un projet : ses colonnes
#: repliées « prompt », « outils », « appels », « décision »)
EPISODE_TABS = ("prompt", "outils", "appels", "décision")
#: ce qu'une exécution dit sur sa ligne, que son détail ne redit pas
RUN_SHOWN = ("mode", "outils utilisés", "épisode", *EPISODE_TABS)


def run(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Une exécution, pour le fil de Projets › Exécutions et pour l'onglet Exécutions de la fiche d'un projet
    (``handmade/projets/_runs.html``) : ce que sa ligne dit, par le libellé de ses colonnes — le projet (absent sur
    la fiche : c'est lui), l'issue et la durée (sur la fiche), les onglets de son épisode quand la vue les donne."""
    at = instant(raw.get("quand"))
    return {"at": at, "when": line.get("quand"),
            "hm": got.ui.kernel.mind.frame().local(at).strftime("%H:%M") if at else "",
            "project": _cell(line.get("projet")), "objective": _cell(line.get("objectif")),
            "issue": _cell(line.get("issue")), "verdict": _cell(line.get("verdict")), "proof": _cell(line.get("preuve")),
            "summary": _cell(line.get("compte rendu")), "commit": _cell(line.get("commit")),
            "duration": _cell(line.get("durée")), "href": line.href,
            "mode": line.text("mode"), "tools": "" if blank(line.get("outils utilisés")) else line.text("outils utilisés"),
            "episode": _cell(line.get("épisode")),
            "links": [x for label in EPISODE_TABS if (x := _cell(line.get(label))) is not None],
            "detail": rest(line, RUN_SHOWN),
            "blocked": text(line.get("verdict")) == "bloqué" or line.tone == "danger"}


def executions(got: Got) -> Markup | None:
    """Projets › Exécutions : ce qui tourne, puis ses exécutions jour par jour."""
    t = got.table("Les exécutions")
    if t is None:
        return None
    items = [run(got, x, r) for x, r in zip(got.lines("Les exécutions"), raw_lines(got, t), strict=False)]
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
