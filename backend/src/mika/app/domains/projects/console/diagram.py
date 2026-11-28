"""Projet › Objectifs › Diagramme (ADR 0297), dessiné côté serveur : une ligne par objectif et par mission, et sous
chaque objectif, en retrait, une ligne par jalon ; les noms à gauche, les barres à droite, et dans le panneau ce qu'on a
choisi (un objectif, un jalon), avec ses gestes. Deux modes, comme sur l'écran Projets :

- **Avancement** : les barres partent du même bord — celle d'un objectif dit la part de ses jalons, couleur par
  couleur ; celle d'un jalon où il en est ; une mission montre ses passages en points. Au bout, un mot.
- **Dans le temps** : un axe en jours ou en semaines ; une barre va de quand elle s'y est mise à quand c'est atteint
  (jusqu'à aujourd'hui, le bout hachuré, si c'est en cours) ; un trait pour aujourd'hui ; une flèche d'un objectif à
  celui qui en dépend ; ce qui n'a pas commencé n'a pas de date : en fantôme, après aujourd'hui, dans l'ordre du plan.

**Ce qu'il lit** : ``faculties/projects/diagram.py`` — la source que lit aussi ``GET …/diagramme`` de l'API par
personne —, sur les départs de ses exécutions relus dans le journal. De vraies dates seulement. **Ce qu'il dessine** :
les positions (``_time``, le calcul de ``frontend/Web/src/screens/projets/diagram.ts`` porté ici) en pixels fixes — le
serveur ne mesure pas l'écran : la piste défile en largeur dans son cadre — et tout en SVG, sans un style en ligne.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from markupsafe import Markup

from mika.app.domains.projects.console.goals import milestone, refs, side
from mika.app.domains.projects.console.zones import (
    DONE,
    FAIL,
    OBJECTIVE_TONES,
    WAIT,
    WORK,
    YOU,
    Scene,
)
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import diagram
from mika.faculties.projects.faculty import milestone_at, objective_at
from mika.faculties.projects.inspect_common import FORGOTTEN
from mika.faculties.projects.inspect_milestones import STATE_FR
from mika.faculties.projects.inspect_words import OBJ_FR
from mika.inspector.ui import env
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import plural
from mika.vocab.episodes import project_target

#: les épisodes relus pour ses dates, au plus
EPISODES_READ = 1000
#: la hauteur d'une ligne d'objectif (ou de mission), d'une ligne de jalon, et de l'en-tête de l'axe
ROW_GOAL, ROW_MARK, HEAD = 46, 36, 42
#: ce qu'un jour mesure quand rien ne presse, et jusqu'où il se resserre ; ce qui suit aujourd'hui, au moins
DAY_WIDTH = {"jours": (124, 56), "semaines": (46, 14)}
TAIL = 150
#: la largeur de piste que le dessin vise (le serveur ne mesure pas l'écran) : au-delà, la piste défile
TRACK = 800
#: l'étendue de la barre d'avancement, en unités de son dessin
FULL = 1000
ORDER = (DONE, YOU, WORK, FAIL)
MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
MODES = (("avancement", "Avancement"), ("temps", "Dans le temps"))
ZOOMS = (("jours", "Jours"), ("semaines", "Semaines"))


def _mark_tone(m: diagram.Mark) -> str:
    """La couleur d'un jalon du diagramme : atteint, prêt (il attend qu'on le tranche), commencé, à venir."""
    return DONE if m.status == c.REACHED else YOU if m.ready else WORK if m.started_at else WAIT


def _mark_part(m: diagram.Mark) -> float:
    """La part faite d'un jalon : atteint ou prêt, entière ; commencé, selon ses exécutions (jamais entière)."""
    if m.status == c.REACHED or m.ready:
        return 1.0
    return min(0.9, 0.15 + 0.25 * max(1, m.runs)) if m.started_at else 0.0


def _segments(o: diagram.Row) -> list[dict[str, Any]]:
    """La barre d'un objectif : la somme de ses jalons, couleur par couleur ; sans jalon, son état seul."""
    if not o.marks:
        part = [(DONE, 1.0)] if o.status == c.DONE else [(FAIL, 0.5 if o.runs else 0.15)] if o.status == c.BLOCKED \
            else [(WORK, 0.5)] if o.runs else []
    else:
        sums: dict[str, float] = {}
        for m in o.marks:
            sums[_mark_tone(m)] = sums.get(_mark_tone(m), 0.0) + _mark_part(m) / len(o.marks)
        part = [(t, sums[t]) for t in ORDER if sums.get(t, 0) > 0]
    out, at = [], 0
    for tone, share in part:
        width = round(share * FULL)
        out.append({"tone": tone, "x": at, "w": width})
        at += width
    return out


def _runs_word(n: int) -> str:
    return plural(max(1, n), "exécution", "exécutions")


def _mark_word(sc: Scene, m: diagram.Mark) -> str:
    if m.status == c.REACHED:
        return f"atteint le {sc.day(m.reached_at)}" if m.reached_at else STATE_FR[c.REACHED]
    if m.ready:
        return "attend sa validation"
    return _runs_word(m.runs) if m.started_at else STATE_FR.get(m.status, m.status)


def _goal_word(sc: Scene, o: diagram.Row) -> str:
    label = OBJ_FR.get(o.status, o.status)
    base = f"{o.reached} / {plural(len(o.marks), 'jalon atteint', 'jalons atteints')}" if o.marks else \
        f"{label} le {sc.day(o.closed_at)}" if o.status == c.DONE and o.closed_at else label
    return base + (f" · {_runs_word(o.runs)}" if o.runs else "")


def _lines(found: tuple[diagram.Row, ...]) -> list[dict[str, Any]]:
    """Ses lignes : les objectifs dans l'ordre du plan, chacun suivi de ses jalons, puis les missions."""
    out: list[dict[str, Any]] = []
    y = 0
    for o in (x for x in found if x.kind != c.CONSTANT):
        out.append({"sort": "goal", "o": o, "m": None, "y": y, "h": ROW_GOAL})
        y += ROW_GOAL
        for m in o.marks:
            out.append({"sort": "mark", "o": o, "m": m, "y": y, "h": ROW_MARK})
            y += ROW_MARK
    for o in (x for x in found if x.kind == c.CONSTANT):
        out.append({"sort": "mission", "o": o, "m": None, "y": y, "h": ROW_GOAL})
        y += ROW_GOAL
    return out


def _days_back(sc: Scene, found: tuple[diagram.Row, ...], zoom: str) -> int:
    """Combien de jours l'axe compte avant aujourd'hui : de la première date à ce matin."""
    dated = [x for o in found for x in (o.added_at, o.started_at, *o.passes) if x > 0]
    first = min(dated, default=sc.now)
    span = max(0, (sc.local(sc.now).date() - sc.local(first).date()).days)
    return max(13 if zoom == "semaines" else 2, span + (1 if zoom == "semaines" else 0))


def pick_zoom(sc: Scene, found: tuple[diagram.Row, ...]) -> str:
    """L'échelle quand l'adresse n'en dit rien : en jours si la première date et aujourd'hui tiennent ensemble dans
    la piste (resserrée au besoin), sinon en semaines."""
    return "jours" if (_days_back(sc, found, "jours") + 1) * DAY_WIDTH["jours"][1] + TAIL <= TRACK else "semaines"


def _time(sc: Scene, found: tuple[diagram.Row, ...], lines: list[dict[str, Any]], zoom: str) -> dict[str, Any]:
    """Les positions du diagramme dans le temps, en pixels : l'axe, la barre et le mot de chaque ligne, les
    fantômes de ce qui n'a pas commencé, les flèches."""
    back = _days_back(sc, found, zoom)
    midnight = sc.local(sc.now).replace(hour=0, minute=0, second=0, microsecond=0)
    origin = int((midnight - timedelta(days=back)).timestamp() * US)
    goals = [r for r in lines if r["sort"] == "goal"]
    gap = 8

    def ghosts(day: float) -> dict[str, Any]:
        """Ce qui n'a pas commencé, à la suite d'aujourd'hui (ou de l'objectif dont il dépend), sans date."""
        today = round((sc.now - origin) / DAY * day)
        width = max(74, round(day * 0.8))
        goal: dict[int, tuple[int, int]] = {}
        mark: dict[tuple[int, int], int] = {}
        end = today + TAIL
        for r in goals:
            o = r["o"]
            cur = today + 34
            before = goal.get(o.after) if o.after else None
            if before:
                cur = max(cur, before[1] + 18)
            waiting = [m for m in o.marks if not m.started_at and m.status != c.REACHED]
            if not waiting and (o.started_at or o.status == c.DONE):
                continue
            x0 = cur
            for m in waiting:
                mark[(o.id, m.id)] = cur
                cur += width + gap
            goal[o.id] = (x0, cur - gap if waiting else cur + width)
            end = max(end, goal[o.id][1] + 40)
        return {"today": today, "end": end, "width": width, "goal": goal, "mark": mark}

    natural, least = DAY_WIDTH[zoom]
    day: float = natural
    g = ghosts(day)
    for _ in range(5):  # resserré — du passé seulement — jusqu'à ce que la première date et la suite tiennent
        if g["end"] <= TRACK or day <= least:
            break
        past = (sc.now - origin) / DAY
        day = max(least, min(day - 1, (TRACK - (g["end"] - g["today"])) // past))
        g = ghosts(day)

    def x(at: int) -> int:
        return round((at - origin) / DAY * day)

    def span(cls: str, a: int, b: int) -> dict[str, Any]:
        return {"cls": cls, "x": a, "w": max(10, b - a)}

    today = g["today"]
    tracks = []
    for r in lines:
        o, m = r["o"], r["m"]
        if r["sort"] == "mission":
            tracks.append({"bars": [], "line": today, "label": today + 14, "you": False,
                           "passes": [x(at) for at in o.passes if at >= origin],
                           "word": plural(o.runs, "passage", "passages")})
            continue
        if m is not None:
            tone = _mark_tone(m)
            if not m.started_at and m.status != c.REACHED:
                gx = g["mark"].get((o.id, m.id), today + 34)
                tracks.append({"bars": [span("fantome", gx, gx + g["width"])], "label": -1, "word": "", "you": False})
                continue
            a = x(m.started_at or m.reached_at)
            b = x((m.reached_at or sc.now) if m.status == c.REACHED else sc.now)
            bars = [span(WORK, a, x(m.ready_at)), span(f"{YOU} hache", x(m.ready_at), b)] if m.ready and m.ready_at \
                else [span(tone if m.status == c.REACHED else f"{tone} encours", a, b)]
            tracks.append({"bars": bars, "label": max(b, a + 10) + 10, "word": _mark_word(sc, m), "you": m.ready})
            continue
        tone = OBJECTIVE_TONES.get(o.status, WORK)
        ghost = g["goal"].get(o.id)
        bars, label = [], -1
        if o.started_at:
            running = o.status != c.DONE
            stop = x(sc.now if running else o.closed_at or o.last_run or sc.now)
            bars.append(span(f"obj {tone}{' encours' if running else ''}", x(o.started_at), stop))
            if ghost is None:  # une flèche part de cette barre vers l'objectif qui en dépend : son mot lui laisse la place
                label = max(stop, x(o.started_at) + 10) + (24 if any(q["o"].after == o.id for q in goals) else 10)
        if ghost is not None:
            bars.append(span("obj fantome", ghost[0], ghost[1]))
        word = f"{OBJ_FR.get(o.status, o.status)} le {sc.day(o.closed_at)}" if o.status == c.DONE and o.closed_at else ""
        tracks.append({"bars": bars, "label": label, "word": word, "you": False})

    arrows = []
    for r in goals:  # d'un objectif à celui qui en dépend
        o = r["o"]
        source = next((q for q in goals if q["o"].id == o.after), None) if o.after else None
        if source is None:
            continue
        gd, ga, so = g["goal"].get(source["o"].id), g["goal"].get(o.id), source["o"]
        x1 = gd[1] if gd else x((so.closed_at or sc.now) if so.status == c.DONE else sc.now) if so.started_at else 0
        x2 = ga[0] if ga else x(o.started_at or sc.now)
        y1, y2 = HEAD + source["y"] + ROW_GOAL // 2, HEAD + r["y"] + ROW_GOAL // 2
        if x2 >= x1 + 16:  # en équerre vers la droite
            arrows.append({"line": f"M{x1 + 2} {y1} h8 V{y2} H{x2 - 7}", "head": f"M{x2 - 9} {y2 - 4} l6 4 l-6 4"})
        else:  # la cible est avant la source : en la contournant
            arrows.append({"line": f"M{x1 + 2} {y1} h10 V{y2 - ROW_GOAL // 2 + 3} H{x2 - 12} V{y2} H{x2 - 4}",
                           "head": f"M{x2 - 8} {y2 - 4} l6 4 l-6 4"})

    days = []
    for i in range(back + 1):
        d = (midnight - timedelta(days=back - i)).date()
        named = i in (0, back) or day >= 84 or not i % 2
        days.append({"x": round(i * day), "n": d.day, "today": i == back, "weekend": d.weekday() >= 5,
                     "monday": d.weekday() == 0, "month": MONTHS[d.month - 1] if d.day == 1 or i == 0 else "",
                     "week": f"sem. du {d.day} {MONTHS[d.month - 1]}", "named": named})
    return {"day": round(day), "width": max(g["end"], TRACK), "today": today, "days": days, "tracks": tracks,
            "arrows": arrows}


def _row(sc: Scene, r: dict[str, Any], said: dict[str, str], keep: dict[str, Any], chosen: tuple[int, int]
         ) -> dict[str, Any]:
    """Une ligne : son nom, où elle mène, et sa barre d'avancement."""
    o, m = r["o"], r["m"]
    out = {"sort": r["sort"], "y": r["y"], "h": r["h"], "n": o.id,
           "href": sc.url("objectifs", objectif=o.id, jalon=m.id if m else "", **keep),
           "on": (o.id, m.id if m else 0) == chosen}
    if m is not None:
        part = _mark_part(m)
        return {**out, "text": said.get(m.text_ref, FORGOTTEN), "tone": _mark_tone(m), "ready": m.ready,
                "bar": [{"tone": _mark_tone(m), "x": 0, "w": round(part * FULL)}] if part else [],
                "word": _mark_word(sc, m)}
    label = OBJ_FR.get(o.status, o.status)
    if r["sort"] == "mission":
        last = f" · le dernier {sc.ago(o.last_run)}" if o.last_run else ""
        return {**out, "text": said.get(o.text_ref, FORGOTTEN), "tone": WORK if o.status == c.OPEN else WAIT,
                "sub": f"mission · {label}", "dots": min(12, len(o.passes) or min(12, o.runs)),
                "word": plural(o.runs, "passage", "passages") + last, "ready": False}
    return {**out, "text": said.get(o.text_ref, FORGOTTEN), "tone": OBJECTIVE_TONES.get(o.status, WORK),
            "sub": f"n° {o.id} · {label}", "bar": _segments(o), "word": _goal_word(sc, o), "ready": False}


def _panel(sc: Scene, found: tuple[diagram.Row, ...], o: Any, mark: Any, keep: dict[str, Any], back: str
           ) -> dict[str, Any] | None:
    """Ce qu'on a choisi, dans le panneau : un objectif ou une mission (son panneau de l'onglet, et de quoi l'ouvrir),
    ou un jalon (comment on le vérifie, ses dates, ses gestes)."""
    if o is None:
        return None
    said = sc.texts(refs(sc, o))
    row = next((x for x in found if x.id == o.id), None)
    mission = o.kind == c.CONSTANT
    tone = (WORK if o.status == c.OPEN else WAIT) if mission else OBJECTIVE_TONES.get(o.status, WAIT)
    head = {"title": said.get(o.text_ref, FORGOTTEN), "sub": "mission" if mission else f"objectif n° {o.id}",
            "tone": tone, "state": OBJ_FR.get(o.status, o.status), "icon": "refresh" if mission else "target",
            "open": sc.url("objectifs", objectif=o.id), "href": sc.url("objectifs", objectif=o.id, **keep)}
    if mark is not None:
        dated = next((x for x in (row.marks if row else ()) if x.id == mark.id), None)
        shown_ = milestone(sc, o, mark, said, back)
        times = []
        if dated is not None:
            times.append(("Elle s'y est mise", f"le {sc.day(dated.started_at)} à {sc.local(dated.started_at):%H:%M}"
                          if dated.started_at else "pas encore : sans date"))
            if mark.status == c.REACHED and mark.reached_at:
                times.append(("Atteint", f"le {sc.day(mark.reached_at)} à {sc.local(mark.reached_at):%H:%M}"))
            elif dated.ready and mark.ready_at:
                times.append(("Prêt depuis", sc.ago(mark.ready_at)))
            if dated.started_at:
                times.append(("Elle y a passé", _runs_word(dated.runs)))
        return {"sort": "mark", "goal": head, "m": shown_, "times": times,
                "edit": sc.url("objectifs", "obj-jalon-modifier", objectif=o.id, jalon=mark.id)
                if mark.status == c.OPEN else ""}
    before = next((x for x in found if x.id == o.after), None) if not mission and o.after else None
    return {"sort": "goal", "goal": head, "side": side(sc, o, said, back),
            "edit": sc.url("objectifs", "obj-modifier", objectif=o.id),
            "add": sc.url("objectifs", "obj-jalon", objectif=o.id)
            if not mission and o.status in (c.OPEN, c.BLOCKED) and len(row.marks if row else ()) < c.MILESTONES_MAX
            else "",
            "before": {"title": sc.texts([before.text_ref]).get(before.text_ref, FORGOTTEN), "n": before.id,
                       "tone": OBJECTIVE_TONES.get(before.status, WAIT), "state": OBJ_FR.get(before.status, ""),
                       "href": sc.url("objectifs", objectif=before.id, **keep)} if before is not None else None}


def diagram_view(sc: Scene) -> Markup | None:
    """L'onglet Objectifs en diagramme (``?vue=diagramme`` ; ``mode`` : avancement ou temps ; ``echelle`` : jours ou
    semaines ; ``objectif``, ``jalon`` : ce qu'on a choisi)."""
    p = sc.p
    if p is None:
        return None
    mind = sc.ui.kernel.mind
    started = [mind.decode(x) for x in mind.store.latest([rt.EPISODE_STARTED.name], EPISODES_READ,
                                                         where=("target", project_target(p.id)))]
    found = diagram.rows(p, diagram.starts_of(p, started))
    mode = "temps" if sc.query.get("mode") == "temps" else "avancement"
    asked = sc.query.get("echelle")
    zoom = asked if asked in dict(ZOOMS) else pick_zoom(sc, found)
    keep = {"vue": "diagramme", "mode": mode if mode == "temps" else "",
            "echelle": asked if asked in dict(ZOOMS) else ""}
    o = objective_at(p, sc.query.get("objectif"))
    if o is None or o.status == c.DROPPED:
        first = next((x for x in found if x.kind != c.CONSTANT and x.status != c.DONE), found[0] if found else None)
        o = objective_at(p, first.id) if first is not None else None
    mark = milestone_at(o, sc.query.get("jalon")) if o is not None and o.kind == c.ONCE else None
    if mark is not None and mark.status == c.DROPPED:
        mark = None
    lines = _lines(found)
    said = sc.texts([ref for x in found for ref in (x.text_ref, *(m.text_ref for m in x.marks))])
    chosen = (o.id if o else 0, mark.id if mark else 0)
    back = sc.url("objectifs", objectif=o.id if o else "", jalon=mark.id if mark else "", **keep)
    rows = [_row(sc, r, said, keep, chosen) for r in lines]
    add = sc.form("objectif_ajouter", sc.url("objectifs"))
    here = {"objectif": o.id if o and sc.query.get("objectif") else "",
            "jalon": mark.id if mark and sc.query.get("jalon") else ""}
    return Markup(env.get_template("handmade/projets/diagramme.html").render(
        rows=rows, height=sum(r["h"] for r in lines), head=HEAD, full=FULL, mode=mode, zoom=zoom,
        time=_time(sc, found, lines, zoom) if mode == "temps" and lines else None,
        cut=len(started) >= EPISODES_READ, panel=_panel(sc, found, o, mark, keep, back),
        lire=bool(sc.query.get("objectif")), can_add=add is not None,
        modes=[{"text": label, "on": code == mode, "href": sc.url("objectifs", **{**keep, **here, "mode": code if
                                                                                    code == "temps" else ""})}
               for code, label in MODES],
        zooms=[{"text": label, "on": code == zoom, "href": sc.url("objectifs", **{**keep, **here, "echelle": code})}
               for code, label in ZOOMS],
        links={"liste": sc.url("objectifs"), "diagramme": sc.url("objectifs", vue="diagramme"),
               "ajouter": sc.url("objectifs", ajouter=1), "back": sc.url("objectifs", **keep)}))
