"""En ce moment : elle, telle qu'elle est à cet instant, sur une page dessinée à la main.

La console montre ce que chaque faculté déclare, une page par propriétaire. « Comment va-t-elle, et pourquoi ? »
traverse pourtant l'humeur, le corps, les besoins, l'attention, ses liens et ce qu'elle entreprend : cette page
les croise, lus aux faits (les mêmes lectures que son prompt, au même instant), au journal et aux séries de la
journée :

- son humeur en mots, ce que son prompt lui en dit, et le plan plaisir × éveil : où elle est, son repos, la trace
  de sa journée ;
- ses dernières 24 heures sur un seul axe : humeur, énergie, sommeil, besoins, ce qu'elle a fait ;
- son corps, ses besoins, ce qui lui trotte dans la tête ;
- les gens : qui est là, qui écrit, ce qu'elle ressent envers chacun, ce qui attend une réponse ;
- ce qu'elle entreprend, ce qui vient, et sa journée en un fil.

Réservée aux opérateurs, comme la console (elle montre tout, secrets compris). Elle se relit seule
(``handmade/live.js`` remplace le fragment) ; sans script, c'est une page complète. Chaque partie se lit à part : une
lecture qui échoue tait sa carte, jamais la page.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mika.app.handmade import (
    FAILED,
    MONTHS,
    WEEKDAYS,
    Look,
    affect_params,
    emotion,
    excerpt,
    person_card,
    presences,
    read_parts,
    said,
    span,
)
from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as needs_c
from mika.contracts import place as place_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.contracts import world as world_c
from mika.faculties.affect import prose
from mika.faculties.attention.inspect import ORIGIN_FR
from mika.faculties.body.inspect import SLEEP_FR
from mika.faculties.goals.inspect import KIND_FR as GOAL_KIND_FR
from mika.faculties.goals.inspect import STATUS_FR as GOAL_STATUS_FR
from mika.inspector import names
from mika.inspector.ui import PREFIX, UI
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.frame import Frame
from mika.kernel.inspect import money_fr, num_fr, pct_fr
from mika.runtime.boundary import Failed, call
from mika.vocab import affect as A
from mika.vocab import causes
from mika.vocab.circadian import PHASE_FR
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable

log = logging.getLogger("mika.console")

#: l'adresse de la page, et celle du fragment qu'elle relit
BASE = f"{PREFIX}/maintenant"
FRAGMENT = f"{PREFIX}/_maintenant"
#: la journée qu'elle montre, et ses mesures (une toutes les dix minutes)
WINDOW = DAY
POINTS = 144
#: au plus tant de pensées, de personnes, de buts, de moments à venir, de lignes du fil de sa journée
THOUGHTS_SHOWN = 4
PEOPLE_SHOWN = 8
GOALS_SHOWN = 5
UPCOMING_SHOWN = 4
FEED_SHOWN = 14
#: les épisodes relus pour sa journée (les plus récents)
EPISODES_READ = 400
#: deux réponses à la même personne à moins de tant l'une de l'autre : une seule conversation dans le fil
CONVERSATION_GAP = 30 * MINUTE
#: un vide ressenti (l'ennui, la solitude) se dit tant qu'il date de moins de tant
FELT_SHOWN = 3 * HOUR

#: les besoins : (clé, libellé, série)
NEEDS = ((needs_c.SOCIAL, "Compagnie", "needs.social"), (needs_c.EXPRESSION, "S'exprimer", "needs.expression"),
         (needs_c.CURIOSITY, "Apprendre", "needs.curiosite"))
FELT_FR = {needs_c.BORED: "de l'ennui", needs_c.LONELY: "de la solitude"}
PLACE_FR = {place_c.Place.CENTER: "au milieu de sa chambre", place_c.Place.WINDOW: "à la fenêtre",
            place_c.Place.DESK: "à son bureau", place_c.Place.BED: "sur son lit",
            place_c.Place.BOOKSHELF: "devant la bibliothèque", place_c.Place.DOOR: "près de la porte"}
#: ce qu'elle attend : avec quoi
AWAITED_FR = {"hopeful": "avec espoir", "anxious": "avec inquiétude"}
#: les repères du plan plaisir × éveil (leurs ancres), pour lire où elle est
LANDMARKS = (A.Emotion.EXCITED, A.Emotion.HAPPY, A.Emotion.RELIEVED, A.Emotion.BORED, A.Emotion.SAD,
             A.Emotion.ANXIOUS, A.Emotion.ANGRY)

# ── la géométrie des dessins ──
#: le plan plaisir × éveil (unités du viewBox : il garde ses proportions dans sa colonne)
PLANE = 300
PLANE_PAD = 28
#: les 24 heures s'étirent en largeur, jamais en hauteur : une largeur en unités, des hauteurs en pixels — un trait
#: garde son épaisseur, un texte sa taille (les textes et les points sont placés en pourcentages, hors de l'étirement)
LANES_W = 1000
#: (clé, libellé, hauteur) de chaque couloir des courbes ; ce qu'elle a fait suit à part, en points
LANES = (("mood", "Humeur", 64), ("energy", "Énergie", 40), ("sleep", "Sommeil", 16), ("needs", "Besoins", 46))
LANE_GAP = 12
LANES_TOP = 4
MOMENTS = "Ce qu'elle a fait"
MOMENTS_H = 26
#: des mesures qui commencent si tard dans la fenêtre : la page dit depuis quand
MEASURED_LATE = 2 * HOUR


# ── son humeur ──


def plane_xy(pleasure: float, arousal: float) -> tuple[float, float]:
    """Un point du plan plaisir (→) × éveil (↑), chacun dans [−1, 1], en coordonnées du dessin."""
    inner = PLANE - 2 * PLANE_PAD
    p, a = max(-1.0, min(1.0, pleasure)), max(-1.0, min(1.0, arousal))
    return round(PLANE_PAD + (p + 1) / 2 * inner, 1), round(PLANE_PAD + (1 - a) / 2 * inner, 1)


def trail(valence: Sequence[tuple[int, float]], arousal: Sequence[tuple[int, float]], parts: int = 5
          ) -> list[dict[str, Any]]:
    """Sa journée sur le plan : les mesures de valence et d'éveil prises au même instant, en ``parts`` tronçons
    du plus ancien (le plus pâle, ``step`` 1) au plus récent."""
    by = dict(arousal)
    points = [plane_xy(v, by[at]) for at, v in valence if at in by]
    if len(points) < 2:
        return []
    stride = max(1, -(-(len(points) - 1) // parts))
    return [{"d": "M" + " L".join(f"{x},{y}" for x, y in points[start:start + stride + 1]), "step": min(parts, i + 1)}
            for i, start in enumerate(range(0, len(points) - 1, stride))]


def mood(look: Look) -> dict[str, Any]:
    frame = look.frame
    m = frame.get(affect_c.MOOD)
    p = affect_params(frame)
    rest = A.distance(m.position, m.home) < p.rest_tolerance
    shown = p.background if rest else m.felt
    facets = [] if rest else [(e, w) for e, w in A.blend(m.position, top_k=3, home=m.home) if w > 0.02]
    total = sum(w for _, w in facets) or 1.0
    bar, x = [], 0.0
    for e, w in facets:
        width = 100 * w / total
        bar.append({"emotion": e.value, "word": A.FR[e], "x": round(x, 2), "w": round(width, 2),
                    "share": pct_fr(w / total)})
        x += width
    residue = ""
    if A.norm(m.fond) >= p.fond_said and m.fond_emotion not in (A.Emotion.NEUTRAL, shown):
        residue = f"un reste {A.partitive(m.fond_emotion)} de sa journée"
    because = None
    if m.cause == causes.TALK and m.cause_person:
        because = {"text": "depuis son échange avec", "who": look.who([m.cause_person])}
    overflow = m.overflow > p.overflow_floor
    home_x, home_y = plane_xy(m.home[0], m.home[1])
    now_x, now_y = plane_xy(m.position[0], m.position[1])
    return {
        "rest": rest, "emotion": shown.value, "word": A.FR[shown],
        "qualifier": "comme d'habitude" if rest else A.intensity_word(m.felt_intensity),
        "background": A.FR[p.background], "background_emotion": p.background.value,
        "line": prose.mood(m, p), "facets": bar, "residue": residue, "because": because,
        "overflow": overflow, "overflow_pct": pct_fr(m.overflow), "overflow_floor": pct_fr(p.overflow_floor),
        "esteem": pct_fr(frame.get(self_c.ESTEEM)),
        "plane": {
            "size": PLANE, "pad": PLANE_PAD, "mid": PLANE / 2, "far": PLANE - PLANE_PAD,
            "home": {"x": home_x, "y": home_y}, "now": {"x": now_x, "y": now_y},
            "trail": trail(look.series("affect.valence"), look.series("affect.eveil")),
            "landmarks": [{"word": A.FR[e], "emotion": e.value,
                           **dict(zip(("x", "y"), plane_xy(A.ANCHORS[e][0], A.ANCHORS[e][1]), strict=True))}
                          for e in LANDMARKS],
            "label": f"{A.FR[shown]} : plaisir {num_fr(m.position[0], 2, signed=True)}, "
                     f"éveil {num_fr(m.position[1], 2, signed=True)} ; son repos : plaisir "
                     f"{num_fr(m.home[0], 2, signed=True)}, éveil {num_fr(m.home[1], 2, signed=True)}",
        },
    }


# ── son corps ──


def body(look: Look) -> dict[str, Any]:
    frame = look.frame
    sleep = frame.get(body_c.SLEEP)
    awake = sleep is body_c.SleepPhase.AWAKE
    since = frame.get(body_c.AWAKE_SINCE) if awake else frame.get(body_c.ASLEEP_SINCE)
    energy = frame.get(body_c.ENERGY)
    place = frame.get(place_c.PLACE)
    where = "dans son lit" if place is place_c.Place.BED and not awake else PLACE_FR.get(place, str(place))
    doing = frame.get(world_c.DOING)
    activity = None
    if doing is not None:
        activity = {"label": doing.label, "since": span(look.now - doing.since),
                    "until": look.hm(doing.until) if doing.until else ""}
    night = frame.get(body_c.LAST_NIGHT)
    last_night = None
    if night is not None:
        notes = [f"réveillée {len(night.rousings)} fois"] if night.rousings else []
        notes += ["nuit courte"] if night.short else []
        notes += ["couchée tard"] if night.late else []
        last_night = {"slept": span(night.duration_us), "from": look.hm(night.start), "to": look.hm(night.end),
                      "notes": notes}
    else:  # le fait se tait (une nuit loin, ou tirée du sommeil) : son dernier sommeil fini, lu au journal
        done = [(a, b) for a, b in sleeps(look) if b < look.now]
        if done:
            a, b = done[-1]
            last_night = {"slept": span(b - a), "from": look.hm(a), "to": look.hm(b), "notes": []}
    return {
        "awake": awake, "state": "Éveillée" if awake else "Endormie", "depth": "" if awake else SLEEP_FR[sleep],
        "since": span(look.now - since) if since else "",
        "woken": frame.get(body_c.NIGHT_WAKING), "phase": PHASE_FR[frame.get(body_c.PHASE)],
        "energy": pct_fr(energy), "energy_w": round(100 * max(0.0, min(1.0, energy)), 1),
        "where": where, "where_since": span(look.now - frame.get(place_c.SINCE)) if frame.get(place_c.SINCE) else "",
        "activity": activity, "night": last_night,
    }


# ── ses besoins ──


def needs(look: Look) -> dict[str, Any]:
    r = look.frame.get(needs_c.NEEDS)
    values = {needs_c.SOCIAL: r.social, needs_c.EXPRESSION: r.expression, needs_c.CURIOSITY: r.curiosity}
    rows = []
    for key, label, series in NEEDS:
        value = values[key]
        trend = ""
        points = look.series(series)
        hour_ago = [v for at, v in points if at <= look.now - HOUR]
        if hour_ago:
            delta = value - hour_ago[-1]
            trend = "monte" if delta > 0.03 else "baisse" if delta < -0.03 else "stable"
        rows.append({"key": key, "label": label, "pct": pct_fr(value), "w": round(100 * max(0.0, min(1.0, value)), 1),
                     "dominant": key == r.dominant and value >= 0.05, "trend": trend})
    felt = None
    for e in reversed(look.recent([needs_c.FELT], 5)):
        if e.at >= look.now - FELT_SHOWN and e.data.feeling in FELT_FR:
            felt = {"what": FELT_FR[e.data.feeling], "how": A.intensity_word(e.data.intensity), "when": look.ago(e.at)}
            break
    return {
        "rows": rows, "felt": felt,
        "heard": look.ago(r.heard_at) if r.heard_at else "",
        "idle": span(look.now - r.idle_since) if r.idle_since and look.now - r.idle_since >= 10 * MINUTE else "",
    }


# ── dans sa tête ──


def _moments(frame: Frame) -> dict[int, Any]:
    """Les moments qu'elle voit venir ou qui approchent, par numéro et par fil."""
    out: dict[int, Any] = {}
    for key in (memory_c.AHEAD, memory_c.UPCOMING):
        for ev in frame.get(key) or ():
            out.setdefault(ev.id, ev)
            if ev.thread:
                out.setdefault(ev.thread, ev)
    return out


def mind(look: Look) -> dict[str, Any]:
    frame = look.frame
    thoughts = tuple(frame.get(attention_c.THOUGHTS) or ())[:THOUGHTS_SHOWN]
    anticipated = frame.get(attention_c.ANTICIPATION)
    moment = _moments(frame).get(anticipated.thread or anticipated.event) if anticipated is not None else None
    dream = frame.get(self_c.DREAM_RESIDUE)
    refs = [t.text_ref for t in thoughts] + [moment.text_ref if moment is not None else "",
                                              dream.text_ref if dream is not None else ""]
    texts = look.texts(refs)
    items = []
    for t in thoughts:
        e = emotion(t.emotion)
        items.append({"text": excerpt(texts.get(t.text_ref)), "emotion": e.value, "word": A.FR[e],
                      "pct": pct_fr(t.intensity), "w": round(100 * max(0.0, min(1.0, t.intensity)), 1),
                      "origin": ORIGIN_FR.get(t.origin, ""), "about": look.who(t.about), "born": look.ago(t.born_at)})
    awaited = None
    if anticipated is not None:
        awaited = {"how": AWAITED_FR.get(anticipated.emotion, A.FR[emotion(anticipated.emotion)]),
                   "emotion": emotion(anticipated.emotion).value,
                   "what": excerpt(texts.get(moment.text_ref), 160) if moment is not None else "un moment qui approche",
                   "when": look.day(anticipated.when) if anticipated.when else "", "about": look.who(anticipated.about)}
    woke_with = None
    if dream is not None:
        e = emotion(dream.emotion)
        woke_with = {"text": excerpt(texts.get(dream.text_ref), 280), "emotion": e.value, "word": A.FR[e],
                     "masked": dream.masked}
    return {"thoughts": items, "awaited": awaited, "dream": woke_with}


# ── les gens ──


def people(look: Look) -> dict[str, Any]:
    frame = look.frame
    online = presences(look)
    circle = [p for p in (frame.get(social_c.CIRCLE) or ()) if is_identifiable(p)]
    rows = []
    for person in dict.fromkeys([*online, *circle]):
        got = call(person_card, look, person, online.get(person), label=f"personne {person}")
        if not isinstance(got, Failed):
            rows.append(got)
    rows.sort(key=lambda r: (not r["composing"], not r["online"], -r["last_in"]))
    return {"rows": rows[:PEOPLE_SHOWN], "more": max(0, len(rows) - PEOPLE_SHOWN), "online": len(online)}


# ── ce qu'elle entreprend ──


def pursuits(look: Look) -> dict[str, Any]:
    frame, now = look.frame, look.now
    live = list(frame.get(goals_c.LIVE) or ())[::-1][:GOALS_SHOWN]
    upcoming = list(frame.get(memory_c.UPCOMING) or ())[:UPCOMING_SHOWN]
    texts = look.texts([g.title_ref for g in live] + [ev.text_ref for ev in upcoming])
    goals = []
    for g in live:
        if g.tasks_total:
            done, total, unit = g.tasks_done, g.tasks_total, "tâches"
        else:
            done, total, unit = g.steps, g.max_steps, "séances"
        nxt = g.next_step_at or g.due or g.waiting_until
        goals.append({
            "title": excerpt(texts.get(g.title_ref), 120) if g.title_ref else "(sans titre)",
            "kind": "rêverie" if g.musing else GOAL_KIND_FR.get(g.kind, g.kind),
            "status": GOAL_STATUS_FR.get(g.status, g.status), "waiting": g.status == goals_c.WAITING,
            "progress": f"{done} / {total} {unit}" if total else "",
            "w": round(100 * min(1.0, done / total), 1) if total else 0.0,
            "next": (f"prochaine séance {look.day(nxt)}" if nxt > now else "") if nxt else "",
            "blocked": g.tasks_blocked, "href": f"{PREFIX}/fiche/goal/{g.id}",
        })
    agency = frame.get(agency_c.AGENCY)
    holding = agency.refractory_until > now
    coming = [{"text": excerpt(texts.get(ev.text_ref), 140), "when": look.day(ev.when, all_day=ev.all_day),
               "about": look.who(ev.about), "ongoing": ev.ongoing, "world": ev.scope == memory_c.WORLD}
              for ev in upcoming]
    return {
        "goals": goals, "upcoming": coming,
        "initiatives": agency.initiatives_today,
        "last_initiative": look.ago(agency.last_initiative_at) if agency.last_initiative_at else "",
        "holding": look.hm(agency.refractory_until) if holding else "",
    }


# ── ses dernières 24 heures ──


def _runs(points: Sequence[tuple[int, float]]) -> list[list[tuple[int, float]]]:
    """Une ligne par suite de mesures : un trou (plus de trois fois l'écart habituel) la coupe."""
    if len(points) < 2:
        return [list(points)] if points else []
    limit = 3 * median(b[0] - a[0] for a, b in zip(points, points[1:], strict=False))
    out, cur = [], [points[0]]
    for prev, pt in zip(points, points[1:], strict=False):
        if pt[0] - prev[0] > limit:
            out.append(cur)
            cur = []
        cur.append(pt)
    out.append(cur)
    return out


@dataclass(frozen=True, slots=True)
class Axis:
    since: int
    until: int

    def part(self, at: int) -> float:
        """La part de la fenêtre écoulée à cet instant, dans [0, 1]."""
        return (min(max(at, self.since), self.until) - self.since) / max(1, self.until - self.since)

    def x(self, at: int) -> float:
        """En unités du dessin étiré (0 à ``LANES_W``)."""
        return round(self.part(at) * LANES_W, 2)

    def pct(self, at: int) -> float:
        """En pourcentage de la largeur : ce qui ne s'étire pas (un texte, un point)."""
        return round(self.part(at) * 100, 3)


def _line(axis: Axis, points: Sequence[tuple[int, float]], y: Callable[[float], float]) -> str:
    return " ".join("M" + " L".join(f"{axis.x(at)},{round(y(v), 1)}" for at, v in run)
                    for run in _runs(points) if len(run) >= 2)


def _area(axis: Axis, points: Sequence[tuple[int, float]], y: Callable[[float], float], base: float) -> str:
    out = []
    for run in _runs(points):
        if len(run) < 2:
            continue
        top = " L".join(f"{axis.x(at)},{round(y(v), 1)}" for at, v in run)
        out.append(f"M{axis.x(run[0][0])},{base} L{top} L{axis.x(run[-1][0])},{base} Z")
    return " ".join(out)


def sleeps(look: Look) -> list[tuple[int, int]]:
    """Ses sommeils dans la fenêtre : (endormie, réveillée), d'après le journal ; le dernier dure encore si elle
    dort."""
    got = call(look.events, [body_c.FELL_ASLEEP, body_c.WOKE], 60, label="journal")
    events = sorted([] if isinstance(got, Failed) else got, key=lambda e: e.data.at)
    out: list[tuple[int, int]] = []
    start: int | None = None
    for e in events:
        if e.type.name == body_c.FELL_ASLEEP.name:
            start = e.data.at
        elif start is not None:
            out.append((start, e.data.at))
            start = None
        elif e.data.at >= look.since:  # réveillée sans endormissement lu : elle dormait au début de la fenêtre
            out.append((look.since, e.data.at))
    asleep = look.frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE
    if asleep:
        out.append((start if start is not None else look.since, look.now))
    return [(max(a, look.since), b) for a, b in out if b > look.since]


def _target(look: Look, e: Any) -> str:
    return look.ui.names.who(e.data.target) if e.data.target else ""


def lanes(look: Look, episodes: Sequence[Any], thoughts: Sequence[Any]) -> dict[str, Any]:
    axis = Axis(look.since, look.now)
    tops: dict[str, tuple[float, float]] = {}
    y = LANES_TOP
    for key, _label, height in LANES:
        tops[key] = (y, y + height)
        y += height + LANE_GAP
    plot_h = y - LANE_GAP + LANES_TOP

    def scale(key: str, lo: float, hi: float) -> Callable[[float], float]:
        top, bottom = tops[key]
        return lambda v: bottom - (min(max(v, lo), hi) - lo) / (hi - lo) * (bottom - top)

    valence = look.series("affect.valence")
    energy = look.series("body.energie")
    mood_y = scale("mood", -1.0, 1.0)
    energy_y = scale("energy", 0.0, 1.0)
    needs_y = scale("needs", 0.0, 1.0)
    zero = round(mood_y(0.0), 1)
    rows = [{"key": key, "label": label, "top": tops[key][0], "bottom": tops[key][1],
             "mid": round((tops[key][0] + tops[key][1]) / 2, 1)} for key, label, _h in LANES]
    needs_lines = [{"key": key, "label": label, "d": _line(axis, look.series(series), needs_y)}
                   for key, label, series in NEEDS]
    sleep_top, sleep_bottom = tops["sleep"]
    asleep = [{"x": axis.x(a), "w": round(max(1.5, axis.x(b) - axis.x(a)), 2),
               "title": f"endormie de {look.hm(a)} à {look.hm(b) if b < look.now else 'maintenant'}"}
              for a, b in sleeps(look)]
    marks = []
    for e in episodes:
        kind = str(e.data.kind)
        if kind not in (Kind.REPLY, Kind.INITIATIVE, Kind.MURMUR):
            continue
        failed = e.data.outcome in FAILED
        outcome, _tone = names.outcome(e.data.outcome, kind)
        who = _target(look, e)
        marks.append({"pct": axis.pct(e.at), "kind": "failed" if failed else kind.lower(),
                      "r": 4.5 if kind == Kind.INITIATIVE else 3.5,
                      "href": f"{PREFIX}/episode/{quote(e.correlation, safe='')}",
                      "title": f"{look.hm(e.at)} · {names.kind(kind)}{' à ' + who if who else ''} · {outcome}"})
    for e in thoughts:
        marks.append({"pct": axis.pct(e.at), "kind": "thought", "r": 3.5, "href": f"{PREFIX}/pensees",
                      "title": f"{look.hm(e.at)} · une pensée : {excerpt(said(e.data.text), 90)}"})
    # l'heure, toutes les trois heures (minuit nommé par son jour) ; près d'un bord, le texte ne déborde pas
    ticks = []
    local = look.frame.local(look.since).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while int(local.timestamp() * US) < look.now:
        if local.hour % 3 == 0:
            at = int(local.timestamp() * US)
            pct = axis.pct(at)
            ticks.append({"x": axis.x(at), "pct": pct, "midnight": local.hour == 0,
                          "label": WEEKDAYS[local.weekday()] if local.hour == 0 else f"{local.hour} h",
                          "anchor": "start" if pct < 3 else "end" if pct > 97 else "middle"})
        local += timedelta(hours=1)
    # une colonne par mesure : ce que valaient l'humeur, l'énergie et les besoins à cet instant (au survol)
    stamps = sorted({at for at, _ in valence} | {at for at, _ in energy})
    by = {"humeur": dict(valence), "énergie": dict(energy),
          **{label.lower(): dict(look.series(series)) for _k, label, series in NEEDS}}
    columns = []
    for i, at in enumerate(stamps):
        lo = (axis.x(stamps[i - 1]) + axis.x(at)) / 2 if i else 0.0
        hi = (axis.x(at) + axis.x(stamps[i + 1])) / 2 if i + 1 < len(stamps) else LANES_W
        values = [f"{name} {num_fr(d[at], 2, signed=True) if name == 'humeur' else pct_fr(d[at])}"
                  for name, d in by.items() if at in d]
        columns.append({"x": round(lo, 2), "w": round(max(0.5, hi - lo), 2),
                        "title": f"{look.hm(at)} — " + " · ".join(values)})
    late = f"mesurées depuis {look.hm(stamps[0])} seulement — une mesure toutes les dix minutes, quand elle tourne" \
        if stamps and stamps[0] > look.since + MEASURED_LATE else ""
    return {
        "w": LANES_W, "plot_h": plot_h, "rows": rows, "measured": bool(stamps), "late": late, "zero": zero,
        "mood_top": tops["mood"][0], "mood_bottom": tops["mood"][1],
        "mood_area": _area(axis, valence, mood_y, zero), "mood_line": _line(axis, valence, mood_y),
        "energy_area": _area(axis, energy, energy_y, tops["energy"][1]), "energy_line": _line(axis, energy, energy_y),
        "needs": needs_lines, "sleep": {"top": sleep_top, "h": sleep_bottom - sleep_top, "bands": asleep},
        "moments": MOMENTS, "moments_h": MOMENTS_H, "marks": marks, "ticks": ticks, "columns": columns,
        "labels_h": plot_h + LANE_GAP + MOMENTS_H, "moments_mid": plot_h + LANE_GAP + MOMENTS_H / 2,
    }


def _said(look: Look, e: Any) -> tuple[str, str]:
    """Une fin d'épisode, en mots : (ce qu'elle a fait, le ton)."""
    kind, outcome = str(e.data.kind), str(e.data.outcome)
    who = _target(look, e)
    to = f" à {who}" if who else ""
    if outcome in FAILED:
        return f"{names.kind(kind).capitalize()}{to} : {names.detail(e.data.detail or outcome) or 'échec'}", "danger"
    if kind == Kind.REPLY:
        return (f"A répondu{to}", "") if outcome == "done" else (f"S'est tue{' devant ' + who if who else ''}", "muted")
    if kind == Kind.INITIATIVE:
        return (f"A écrit d'elle-même{to}", "accent") if outcome == "done" else \
            (f"S'est retenue d'écrire{to}", "muted")
    if kind == Kind.MURMUR:
        return "A murmuré", ""
    if kind == Kind.JOURNAL:
        return "A écrit son journal", ""
    if kind == Kind.DREAM:
        return "A rêvé", ""
    if kind == Kind.NARRATIVE:
        return "A repris le récit de qui elle devient", ""
    text, tone = names.outcome(outcome, kind)
    return f"{names.kind(kind).capitalize()}{' pour ' + who if who else ''} · {text}", tone if tone == "warn" else ""


def feed(look: Look, episodes: Sequence[Any], thoughts: Sequence[Any]) -> list[dict[str, Any]]:
    """Sa journée en un fil, du plus récent au plus ancien : ses paroles (une conversation en une ligne), ses
    pensées, son sommeil, ses manques et ses retrouvailles, ce qu'elle a mené à bout."""
    entries: list[dict[str, Any]] = []
    for e in episodes:
        if str(e.data.outcome) in ("superseded", "preempted", "cancelled"):
            continue
        text, tone = _said(look, e)
        last = entries[-1] if entries else None
        same = (last is not None and last.get("conversation") == (e.data.kind, e.data.target, e.data.outcome)
                and e.at - last["at"] <= CONVERSATION_GAP and str(e.data.kind) == Kind.REPLY and tone == "")
        if same:
            last["count"] += 1
            last["at"] = e.at
            last["text"] = f"A répondu {last['count']} fois{' à ' + _target(look, e) if e.data.target else ''}"
            last["href"] = f"{PREFIX}/episode/{quote(e.correlation, safe='')}"
            continue
        entries.append({"at": e.at, "start": e.at, "text": text, "tone": tone, "count": 1, "kind": "episode",
                        "conversation": (e.data.kind, e.data.target, e.data.outcome),
                        "href": f"{PREFIX}/episode/{quote(e.correlation, safe='')}"})
    for e in thoughts:
        entries.append({"at": e.at, "text": "Une pensée lui vient", "quote": excerpt(said(e.data.text), 140),
                        "tone": "thought", "kind": "thought", "href": f"{PREFIX}/pensees"})
    others = look.recent([body_c.WOKE, body_c.FELL_ASLEEP, body_c.ROUSED, needs_c.FELT, needs_c.REUNITED,
                          goals_c.GOAL_CLOSED], 80)
    for e in others:
        if e.type.name == body_c.WOKE.name:
            entries.append({"at": e.at, "text": "S'est réveillée", "tone": "sleep", "kind": "body"})
        elif e.type.name == body_c.FELL_ASLEEP.name:
            entries.append({"at": e.at, "text": "S'est endormie", "tone": "sleep", "kind": "body"})
        elif e.type.name == body_c.ROUSED.name:
            who = look.name(e.data.person) if e.data.person else ""
            entries.append({"at": e.at, "text": f"Tirée du sommeil{' par ' + who if who else ''}", "tone": "sleep",
                            "kind": "body"})
        elif e.type.name == needs_c.FELT.name and e.data.feeling in FELT_FR:
            entries.append({"at": e.at, "text": f"Ressent {FELT_FR[e.data.feeling]}", "tone": "muted", "kind": "need"})
        elif e.type.name == needs_c.REUNITED.name:
            entries.append({"at": e.at, "text": f"Retrouve {look.name(e.data.person)} : ça lui fait du bien",
                            "tone": "accent", "kind": "need", "href": look.href(e.data.person)})
        elif e.type.name == goals_c.GOAL_CLOSED.name:
            status = GOAL_STATUS_FR.get(e.data.status, e.data.status)
            entries.append({"at": e.at, "text": f"But {status}", "quote": excerpt(said(e.data.title), 120),
                            "tone": "ok" if e.data.status == goals_c.ACHIEVED else "muted", "kind": "goal",
                            "href": f"{PREFIX}/fiche/goal/{e.data.goal}"})
    entries.sort(key=lambda x: x["at"], reverse=True)
    out = []
    for x in entries[:FEED_SHOWN]:
        start = x.get("start", x["at"])
        first, last = look.hm(start), look.hm(x["at"])
        x["time"] = first if first == last else f"{first}–{last}"
        out.append(x)
    return out


def today(look: Look, episodes: Sequence[Any], thoughts: Sequence[Any]) -> list[dict[str, Any]]:
    """Depuis minuit : ce qu'elle a dit, tu, pensé, raté, et ce que ses modèles ont coûté."""
    local = look.frame.local(look.now)
    midnight = int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * US)
    ended = [(str(e.data.kind), str(e.data.outcome)) for e in episodes if e.at >= midnight]
    replies = sum(1 for k, o in ended if k == Kind.REPLY and o == "done")
    initiatives = sum(1 for k, o in ended if k == Kind.INITIATIVE and o == "done")
    silences = sum(1 for _k, o in ended if o == "abstained")
    failures = sum(1 for _k, o in ended if o in FAILED)
    out = [{"label": "réponses", "value": replies},
           {"label": "initiatives", "value": initiatives},
           {"label": "silences choisis", "value": silences},
           {"label": "pensées nées", "value": sum(1 for e in thoughts if e.at >= midnight)},
           {"label": "échecs", "value": failures, "tone": "danger" if failures else "",
            "href": f"{PREFIX}/decisions/episodes?issue=failed" if failures else ""}]
    calls = look.ui.deps.calls
    if calls is not None:
        used = call(calls.usage, midnight, label="appels du jour")
        if not isinstance(used, Failed):
            out.append({"label": "appels de modèle", "value": sum(u.calls for u in used),
                        "sub": money_fr(sum(u.cost_usd for u in used)), "href": f"{PREFIX}/systeme/appels"})
    return out


def day(look: Look) -> dict[str, Any]:
    episodes = look.recent([rt.EPISODE_ENDED], EPISODES_READ)
    thoughts = look.recent([attention_c.THOUGHT_BORN], 60)
    return {"lanes": lanes(look, episodes, thoughts), "feed": feed(look, episodes, thoughts),
            "today": today(look, episodes, thoughts)}


# ── la page ──

#: chaque partie de la page, lue à part
PARTS: tuple[tuple[str, Callable[[Look], dict[str, Any]]], ...] = (
    ("mood", mood), ("day", day), ("body", body), ("needs", needs), ("mind", mind), ("people", people),
    ("pursuits", pursuits))


class NowPage:
    """La page « En ce moment » et son fragment, dans le cadre de la console (son menu, ses vitaux)."""

    def __init__(self, ui: UI) -> None:
        self.ui = ui

    def snapshot(self) -> dict[str, Any]:
        """Tout ce que montre la page ; une partie dont la lecture a échoué vaut ``None`` (sa carte le dit)."""
        look = Look.of(self.ui, WINDOW)
        local = look.frame.local(look.now)
        return {"her": self.ui.her_name(), "at": look.hm(look.now), "stamp": local.strftime("%H:%M:%S"),
                "today": f"{WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}",
                **read_parts(look, PARTS, "en ce moment")}

    async def page(self, request: Request) -> Response:
        snap = self.snapshot()
        return self.ui.page(request, "handmade/now/page.html", f"{snap['her']}, en ce moment", now=snap,
                            fragment=FRAGMENT)

    async def fragment(self, request: Request) -> Response:
        return self.ui.fragment("handmade/now/body.html", now=self.snapshot())

    def routes(self) -> list[Route]:
        return [Route(BASE, self.ui.guarded(self.page), methods=["GET"]),
                Route(FRAGMENT, self.ui.guarded(self.fragment), methods=["GET"])]
