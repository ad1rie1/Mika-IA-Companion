"""La fiche d'un projet › Activité, calquée sur l'écran Projets (ADR 0290, 0297) : ses sous-onglets en adresses
(``?vue=``) — Fil, Exécutions, Carnet.

- **Fil** : ce qui s'est passé, jour par jour, le plus récent d'abord — ses exécutions, les commits qu'elles ont
  laissés, ses pull requests, ses tickets, les gestes des personnes —, lu du journal par la même fonction que l'API
  par personne (``faculties/projects/feed.py``) ; la console voit tout et nomme chacun. Ses filtres (une sorte, un
  objectif), sa pagination par curseur (``avant``) ; chaque ligne mène à ce qu'elle nomme. Le panneau : ses trente
  derniers jours en barres (dessinées côté serveur), son prochain passage, qui a fait quoi.
- **Exécutions** : la liste, jour par jour ; une exécution choisie (``execution=``) dans les trois zones — son compte
  rendu, ce qu'elle a fait pas à pas (sa trace : ``feed.steps``), son verdict et sa preuve, son commit, ce qu'elle a
  demandé ; et ce que seule la console a : **les onglets de son épisode** (prompt, outils, appels, décision), dessinés
  par la page d'un épisode (``episode_drawn.episode_panel``), un à la fois (``volet=``).
- **Carnet** : ses notes en cartes, ses consignes, ce qu'on en a fait, ce qui sort — les blocs de la vue ``carnet``
  de la faculté, lue seulement ici, chacun avec sa pagination.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from markupsafe import Markup

from mika.app.domains.projects.console.code import by_day_items
from mika.app.domains.projects.console.zones import DONE, FAIL, WAIT, WORK, YOU, Scene
from mika.app.handmade.tabs import Got, Line, anchored, lines, subpanes
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import feed, glance, tracker
from mika.faculties.projects.diagram import episode_sort
from mika.faculties.projects.faculty import objective_at
from mika.faculties.projects.inspect import (
    DECIDE_LABEL,
    EFFECTS_CURSOR,
    NOTES_CURSOR,
    OPERATIONS_CURSOR,
    window_words,
)
from mika.faculties.projects.inspect_common import FORGOTTEN
from mika.faculties.projects.inspect_words import OBJ_FR, VERDICT_FR
from mika.inspector.pages.episode_drawn import episode_panel
from mika.inspector.pages.journal import episode_head
from mika.inspector.pages.why import trace_of
from mika.inspector.ui import PREFIX, env
from mika.kernel.clock import DAY, US
from mika.runtime.boundary import Failed, call
from mika.vocab.episodes import outcome_words, project_target

TAB = "executions"
FIL, RUNS, NOTEBOOK = "", "executions", "carnet"
BAR = ((FIL, "Fil"), (RUNS, "Exécutions"), (NOTEBOOK, "Carnet"))
#: les lignes d'une page du fil, ses exécutions par page ; ce qu'une page lit du journal, par lots, au plus
PAGE, RUNS_PAGE, SCAN, SCAN_BATCHES = 20, 25, 200, 10
#: les jours comptés dans le panneau, et les lots lus au plus pour les compter (au-delà : un compte incomplet)
DAYS, COUNT_BATCHES = 30, 10
#: une sorte du fil → son icône
KIND_ICONS = {feed.RUN: "play", feed.COMMIT: "commit", feed.PULL: "pr", feed.TICKET: "ticket", feed.GESTURE: "user"}
#: un verdict → sa couleur ; une issue d'épisode qui a mal fini
VERDICT_TONES = {c.CONTINUE: WORK, c.DONE: DONE, c.BLOCKED: FAIL, c.WAIT: YOU}
FAILED = ("failed", "timeout")
#: les volets d'une exécution : les siens, puis les onglets de son épisode (la page d'un épisode les dessine)
EPISODE_PANES = (("", "Ce qu'elle a fait"), ("prompt", "Prompt"), ("outils", "Outils"), ("appels", "Appels"),
                 ("decision", "Décision"))
#: les volets du Carnet : (ancre, libellé, titre du bloc de la vue, son curseur de pagination)
NOTEBOOK_PANES = (("carnet-notes", "Ses notes", "Son carnet", NOTES_CURSOR),
                  ("carnet-consignes", "Consignes", "Consignes reçues", "avant"),
                  ("carnet-faits", "Ce qu'on en a fait", "Ce qu'on en a fait", OPERATIONS_CURSOR),
                  ("carnet-sorties", "Ce qui sort", "Ce qui sort de la machine", EFFECTS_CURSOR))


class _Look:
    """Ce que le fil demande à qui le lit (``feed.Look``) : la console voit tout et nomme chacun."""

    def __init__(self, sc: Scene) -> None:
        self.sc, self.store, self.her = sc, sc.ui.kernel.mind.store, sc.ui.her_name()
        self._tickets: dict[str, Any] = {}

    def who(self, author: str, by: str) -> dict[str, Any]:
        if author == c.BY_HOST:
            return {"author_kind": "host", "author": "chez l'hôte"}
        if c.asking_project(author):
            return {"author_kind": "project", "author": f"le projet n° {c.asking_project(author)}"}
        if author in (c.BY_SELF, "self") or (not by and author not in feed.PEOPLE):
            return {"author_kind": "self", "author": self.her}
        if not by:
            return {"author_kind": "other", "author": "une personne"}
        return {"author_kind": "person", "author": identity_c.person_name(self.sc.frame, by) or by}

    def heard(self, content: Any) -> str:
        return str(getattr(content, "ref", "") or "") if content is not None else ""

    def ticket(self, key: str) -> Any:
        if key not in self._tickets:
            self._tickets[key] = tracker.entry(self.store, self.sc.p.id, c.TICKETS, key)
        return self._tickets[key]

    def veiled(self, item: Any) -> bool:
        return False


def _journal(sc: Scene, types: Any, limit: int, **where: Any) -> list[Any]:
    mind = sc.ui.kernel.mind
    names = [getattr(t, "name", t) for t in types]
    return [mind.decode(x) for x in mind.store.latest(names, limit, **where)]


def _bar(sc: Scene, view: str, counts: Mapping[str, int | None]) -> list[dict[str, Any]]:
    return [{"label": label, "on": k == view, "count": counts.get(k), "href": sc.url(TAB, vue=k)} for k, label in BAR]


def activity_page(sc: Scene) -> Markup | None:
    """L'onglet Activité : sa barre (Fil, Exécutions, Carnet ; à son bout, son prochain passage), puis la sous-vue."""
    p = sc.p
    if p is None:
        return None
    view = sc.query.get("vue", "")
    view = view if view in (RUNS, NOTEBOOK) else FIL
    g = glance.of(p, sc.s, sc.frame)
    coming = sc.when(g.coming.at) if g.coming.at else ""
    context: dict[str, Any] = {"view": view, "bar": _bar(sc, view, {RUNS: p.runs}), "coming": coming,
                               "her": sc.ui.her_name()}
    builders = {FIL: feed_view, RUNS: runs_view, NOTEBOOK: notebook_view}
    context.update(builders[view](sc, g))
    return Markup(env.get_template("handmade/projets/activite.html").render(**context))


# ── Le fil ────────────────────────────────────────────────────────────────


def _go(sc: Scene, x: Mapping[str, Any], e: Any) -> str:
    """Où mène une ligne du fil : ce qu'elle nomme."""
    name = feed.name_of(e)
    if x["kind"] == feed.RUN and x["run"]:
        return sc.url(TAB, vue=RUNS, execution=x["run"])
    if x["kind"] == feed.COMMIT and x["sha"]:
        return sc.url("git", vue="commits", sha=x["sha"])
    if x["pull"]:
        return sc.url("git", vue="pulls", pr=x["pull"])
    if x["kind"] == feed.PULL and x["sha"]:
        return sc.url("git", vue="ci", sha=x["sha"])
    if x["ticket"]:
        return sc.url("tickets", element=f"#{x['ticket']}")
    if name in feed.DECISION_FACTS:
        return sc.url("documentation", vue="decisions", statut="toutes", decision=getattr(e.data, "decision", 0))
    if name == "amended":
        return sc.url(TAB, "carnet-consignes", vue=NOTEBOOK)
    if name == "deposited":
        return sc.url("git")
    if name == "links_set":
        return sc.url("liens")
    if name == "reframed":
        return sc.url("comportement")
    if x["objective"]:
        return sc.url("objectifs", objectif=x["objective"])
    return ""


def _counted(sc: Scene, look: _Look) -> dict[str, Any]:
    """Ses trente derniers jours, sorte par sorte, et qui a fait quoi (lus au plus ``COUNT_BATCHES`` lots)."""
    today = sc.frame.local().date()
    since = sc.now - (DAYS + 1) * DAY
    days = [today - timedelta(days=n) for n in range(DAYS - 1, -1, -1)]
    counts = {day: dict.fromkeys(feed.KINDS, 0) for day in days}
    by: dict[str, int] = {}
    cursor, cut = None, False
    for _ in range(COUNT_BATCHES):
        batch = _journal(sc, feed.ALL, SCAN, where=("project", sc.p.id), before=cursor)
        for e in batch:
            cursor = e.seq
            if e.at < since:
                break
            day = sc.frame.local(e.at).date()
            for x in feed.entries(look, e) if day in counts else ():
                counts[day][x["kind"]] += 1
                by[x["author"]] = by.get(x["author"], 0) + 1
        else:
            if len(batch) == SCAN:
                continue
        break
    else:
        cut = True
    top = max([1] + [sum(row.values()) for row in counts.values()])
    bars = []
    for i, day in enumerate(days):
        y = 100
        parts = []
        for k in feed.KINDS:
            h = round(96 * counts[day][k] / top, 1)
            if h:
                y -= h
                parts.append({"kind": k, "y": round(y, 1), "h": h})
        bars.append({"x": i * 10 + 1.5, "parts": parts, "total": sum(counts[day].values()),
                     "day": f"{day.day}/{day.month}"})
    totals = {k: sum(row[k] for row in counts.values()) for k in feed.KINDS}
    return {"bars": bars, "total": sum(totals.values()), "cut": cut,
            "legend": [{"kind": k, "label": feed.KIND_WORDS[k], "count": totals[k]} for k in feed.KINDS],
            # le premier repère commence avec sa barre (centré sur elle, il sortirait du dessin à gauche)
            "ticks": [{"x": i * 10 + 5 if i else 1.5, "label": f"{d.day}/{d.month}", "first": not i}
                      for i, d in enumerate(days) if i % 7 == 0],
            "by": sorted(({"who": who, "count": n} for who, n in by.items()), key=lambda x: -x["count"])}


def feed_view(sc: Scene, g: Any) -> dict[str, Any]:
    p = sc.p
    kind = sc.query.get("sorte", "")
    kind = kind if kind in feed.KINDS else ""
    raw = sc.query.get("objectif", "")
    objective = int(raw) if raw.isdecimal() else 0
    before = sc.query.get("avant", "")
    cursor: int | None = int(before) if before.isdecimal() else None
    look = _Look(sc)
    found: list[tuple[dict[str, Any], Any]] = []
    more = True
    for _ in range(SCAN_BATCHES):
        batch = _journal(sc, feed.READS.get(kind, feed.ALL), SCAN, where=("project", p.id), before=cursor)
        for e in batch:
            if len(found) >= PAGE:
                break
            cursor = e.seq
            found += [(x, e) for x in feed.entries(look, e) if (not kind or x["kind"] == kind)
                      and feed.kept(x, objective, 0, frozenset())]
        else:
            if len(batch) < SCAN:
                more = False
                break
            continue
        break
    texts = sc.texts(x["text_ref"] for x, _ in found)
    goals = sc.texts(o.text_ref for o in p.objectives)
    items = []
    for x, e in found:
        text = feed.clip(texts.get(x["text_ref"], ""), 300) if x["text_ref"] else ""
        title = (text or "Compte rendu oublié") if x["kind"] == feed.RUN else x["title"]
        o = objective_at(p, x["objective"]) if x["objective"] else None
        items.append({
            **x, "title": title, "sub": "" if x["kind"] == feed.RUN else text or x["sub"], "at": e.at,
            "time": sc.local(e.at).strftime("%H:%M"), "icon": KIND_ICONS[x["kind"]], "href": _go(sc, x, e),
            "tone": VERDICT_TONES.get(x["verdict"], WORK) if x["kind"] == feed.RUN else
            FAIL if x["verdict"] == "failed" else DONE if x["verdict"] == "passed" else "",
            "goal": f"objectif n° {o.id}" if o is not None else "", "goal_title": goals.get(o.text_ref, "") if o else "",
            "her": x["author_kind"] == "self"})
    target = objective_at(p, g.coming.objective) if g.coming.objective else None
    keep = {"vue": FIL, "objectif": objective or "", "sorte": kind}
    filters = [{"label": "Tout", "on": not kind, "href": sc.url(TAB, objectif=objective or "")}] + \
        [{"label": feed.KIND_WORDS[k], "on": k == kind, "href": sc.url(TAB, sorte=k, objectif=objective or "")}
         for k in feed.KINDS]
    goals_menu = [{"label": "Tous les objectifs", "on": not objective, "href": sc.url(TAB, sorte=kind)}] + \
        [{"label": f"n° {o.id} — {feed.clip(goals.get(o.text_ref, FORGOTTEN), 60)}", "on": o.id == objective,
          "href": sc.url(TAB, sorte=kind, objectif=o.id)} for o in p.objectives if o.status != c.DROPPED]
    return {"days": by_day_items(sc, items), "filters": filters, "goals": goals_menu,
            "goal_on": next((x["label"] for x in goals_menu if x["on"]), "Tous les objectifs"),
            "older": sc.url(TAB, **keep, avant=cursor) if more and found and cursor else "",
            "newest": sc.url(TAB, **keep) if before else "",
            # ses trente jours ne se relisent qu'en tête du fil : une page plus ancienne ne relit pas le journal une
            # seconde fois pour redire le même panneau
            "chart": None if before else _counted(sc, look),
            "next": {"when": sc.when(g.coming.at) if g.coming.at else "",
                     "about": goals.get(target.text_ref, "") if target is not None else "",
                     "rhythm": f"{g.schedule} · {window_words(p)}"}}


# ── Ses exécutions ────────────────────────────────────────────────────────


def _runs(sc: Scene, started: list[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    corrs = [e.correlation for e in started]
    if not corrs:
        return {}, {}
    ended = {e.correlation: e for e in _journal(sc, [rt.EPISODE_ENDED], len(corrs) + 1, correlations=corrs)}
    reports = {e.correlation: e for e in _journal(sc, [c.RUN_REPORTED], len(corrs) + 1, correlations=corrs)}
    return ended, reports


def _run(sc: Scene, e: Any, end: Any, report: Any, goals: Mapping[str, str],
         keep: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """Une exécution de la liste ; ``keep`` : ce que son lien garde de l'adresse (sa page, ``avant``)."""
    found = episode_sort(sc.p, e.data.subject)
    if found is None:
        return None
    sort, oid = found
    d = report.data if report is not None else None
    outcome = str(end.data.outcome) if end is not None else ""
    o = objective_at(sc.p, d.objective if d is not None and d.objective else oid) if (d or oid) else None
    seconds = max(1, (end.at - e.at) // US) if end is not None else 0
    verdict = d.verdict if d is not None else ""
    return {
        "id": e.correlation, "at": e.at, "sort": feed.SORT_WORDS[sort], "sort_key": sort,
        "objective": {"n": o.id, "text": goals.get(o.text_ref, FORGOTTEN), "state": OBJ_FR.get(o.status, o.status),
                      "tone": WORK if o.status == c.OPEN else DONE if o.status == c.DONE else
                      FAIL if o.status == c.BLOCKED else WAIT, "href": sc.url("objectifs", objectif=o.id)}
        if o is not None else None,
        "title": goals.get(o.text_ref, FORGOTTEN) if o is not None else "Cadrage" if sort == "frame" else "Exécution",
        "running": end is None, "outcome": outcome,
        "outcome_label": outcome_words(outcome, e.data.kind)[0] if outcome else "en cours",
        "failed": outcome in FAILED, "verdict": VERDICT_FR.get(verdict, verdict),
        # sa couleur est celle de son verdict, comme l'écran ; une exécution qui a mal fini après son compte rendu
        # (un délai dépassé) garde son verdict, et son issue se dit à côté (« failed »)
        "tone": VERDICT_TONES[verdict] if verdict in VERDICT_TONES else FAIL if outcome in FAILED else
        WORK if end is None else WAIT,
        "proven": bool(d.proven) if d is not None else False, "commit": d.commit[:40] if d is not None else "",
        "branch": d.branch if d is not None else "", "time": sc.local(e.at).strftime("%H:%M"),
        "took": _took(seconds), "when": sc.when(e.at), "ago": sc.ago(e.at),
        "summary_ref": d.summary.ref if d is not None and d.summary is not None else "",
        "need_ref": d.need.ref if d is not None and d.need is not None else "",
        "tools": list(d.tools) if d is not None and d.tools else [],
        "href": sc.url(TAB, vue=RUNS, execution=e.correlation, **(keep or {}))}


def _took(seconds: int) -> str:
    if not seconds:
        return ""
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min" if seconds < 3600 else \
        f"{seconds // 3600} h {seconds % 3600 // 60:02d}"


def runs_view(sc: Scene, g: Any) -> dict[str, Any]:
    p = sc.p
    before = sc.query.get("avant", "")
    before = before if before.isdecimal() else ""
    keep = {"avant": before} if before else {}  # choisir une exécution garde sa page dans la liste
    started = _journal(sc, [rt.EPISODE_STARTED], RUNS_PAGE + 1, where=("target", project_target(p.id)),
                       before=int(before) if before else None)
    page = started[:RUNS_PAGE]
    wanted = sc.query.get("execution", "")
    if wanted and wanted not in {e.correlation for e in page}:  # une exécution d'une autre page : lue à part
        page_wanted = [e for e in _journal(sc, [rt.EPISODE_STARTED], 2, correlations=[wanted])
                       if e.data.target == project_target(p.id)]
    else:
        page_wanted = []
    ended, reports = _runs(sc, page + page_wanted)
    goals = sc.texts(o.text_ref for o in p.objectives)
    items = [x for e in page if (x := _run(sc, e, ended.get(e.correlation), reports.get(e.correlation), goals, keep))]
    chosen_id = wanted or (items[0]["id"] if items else "")
    chosen = next((x for x in items if x["id"] == chosen_id), None)
    if chosen is None and page_wanted:
        e = page_wanted[0]
        chosen = _run(sc, e, ended.get(e.correlation), reports.get(e.correlation), goals, keep)
    for x in items:
        x["on"] = chosen is not None and x["id"] == chosen["id"]
    out: dict[str, Any] = {
        "days": by_day_items(sc, items), "total": p.runs, "lire": bool(wanted), "run": None,
        "older": sc.url(TAB, vue=RUNS, avant=page[-1].seq) if len(started) > RUNS_PAGE else "",
        "newest": sc.url(TAB, vue=RUNS) if before else "", "home": sc.url(TAB, vue=RUNS),
        "missing": wanted if wanted and chosen is None else ""}
    if chosen is None:
        return out
    run = dict(chosen)
    said = sc.texts([run["summary_ref"], run["need_ref"]])
    run["summary"] = said.get(run["summary_ref"], "") if run["summary_ref"] else ""
    run["need"] = said.get(run["need_ref"], "") if run["need_ref"] else ""
    kept, steps, cut = feed.steps(trace_of(sc.ui, run["id"]), sc.ui.kernel.registry.tools, lambda args: True)
    run.update(steps_kept=kept, steps=steps, steps_cut=cut, commit_href=sc.url("git", vue="commits",
                                                                              sha=run["commit"]) if run["commit"]
               else "", episode_href=f"{PREFIX}/episode/{run['id']}")
    pane = sc.query.get("volet", "")
    pane = pane if pane in dict(EPISODE_PANES) else ""
    run["panes"] = [{"key": k, "label": label, "on": k == pane,
                     "href": sc.url(TAB, vue=RUNS, execution=run["id"], volet=k, **keep)} for k, label in EPISODE_PANES]
    run["pane"] = pane
    run["episode"] = _episode(sc, run["id"], pane) if pane else None
    out["run"] = run
    return out


def _episode(sc: Scene, corr: str, slug: str) -> Markup | None:
    """Un onglet de son épisode, dessiné par la page d'un épisode (la console seule l'a) ; rien s'il ne se lit pas."""
    info = episode_head(sc.ui, corr)
    if info is None:
        return None
    panel = call(episode_panel, sc.ui, corr, slug, info, dict(sc.query), sc.ui.env(), label="épisode d'une exécution")
    if panel is None or isinstance(panel, Failed):
        return None
    shown = call(lambda: Markup(env.get_template(panel.template).render(**panel.context)),
                 label="épisode d'une exécution, dessiné")
    return None if isinstance(shown, Failed) else shown


# ── Son carnet ────────────────────────────────────────────────────────────


def _request(line: Line) -> dict[str, Any]:
    """Ce qu'il a voulu faire sortir de la machine : quand, quoi, s'il fallait ton accord, où il en est ; la commande
    exacte et le lien vers la file quand il attend (la fiche ne décide pas sur place, ADR 0177)."""
    told = [d for d in line.rest if d.get("t") == "code"]
    decide = next((p["value"] for d in line.rest if d.get("t") == "fields" for p in d["pairs"]
                   if p["label"] == DECIDE_LABEL and p["value"].get("t") == "link"), None)
    return {"when": line.get("quand"), "what": line.text("ce qu'il voulait faire sortir"),
            "approval": line.text("accord"), "state": line.get("état"), "waiting": line.tone == "warn",
            "decide": decide, "codes": told}


def notebook_view(sc: Scene, g: Any) -> dict[str, Any]:
    """Le Carnet : la vue ``carnet`` de la faculté, lue ici seulement — ses notes en cartes, ses consignes, ce qu'on
    en a fait, ce qui sort —, chacune avec sa pagination ; celle qu'on feuillette s'ouvre."""
    tab = next((t for t in sc.ui.subject_tabs("project", sc.key) if t.name == "carnet"), None)
    if tab is None:
        return {"lists": None}
    got = Got(sc.ui, list(sc.ui.inspection.run(tab, sc.query, sc.ui.when_long, subject=sc.key)), sc.query, {})
    lists = {pane: got.first("table" if pane == "carnet-sorties" else "timeline", title)
             for pane, _, title, _ in NOTEBOOK_PANES}
    if any(x is None for x in lists.values()):
        return {"lists": None, "notes": got.notes()}
    for pane, x in lists.items():
        anchored(x, pane)
    browsed = next((pane for pane, _, _, cursor in NOTEBOOK_PANES if sc.query.get(cursor)), "")
    requests = [_request(x) for x in lines(lists["carnet-sorties"])]
    panes = [{"id": pane, "label": label, "warn": pane == "carnet-sorties" and any(r["waiting"] for r in requests)}
             for pane, label, _, _ in NOTEBOOK_PANES]
    order = [x["id"] for x in subpanes([{"id": x["id"]} for x in panes], browsed)]
    return {"lists": lists, "panes": panes, "order": order, "requests": requests, "notes": got.notes()}
