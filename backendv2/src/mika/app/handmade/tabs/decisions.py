"""Activité › Décisions : ses onglets, chacun dans sa forme (ADR 0177) ; En cours est dessiné à part (``running.py``).

Ces pages répondent à « pourquoi parle-t-elle, ou se tait-elle ? ». Une ligne de l'arbitre (une sorte d'épisode envers
quelqu'un) s'y lit partout de la même façon : ce qui pousse et ce qui retient sur une même barre, de part et d'autre
de l'équilibre (le vert passe le milieu : ce qui pousse l'emporte), ce qui l'en empêche (un veto), et ce qui en sort
— combien de fois par heure, en moyenne dans combien de temps ; le calcul pas à pas, replié.

- Table de l'arbitre : d'abord une phrase (elle agirait en moyenne dans…, ou rien ne la fera agir), puis une entrée
  par ligne, la plus probable d'abord ; les règles du jeu (le seuil et le rythme maximal de chaque sorte) en bas.
- Que ferait-elle ? : sans personne, les personnes dont une ligne existe, en puces ; pour une personne, son verdict
  en grand, ses lignes, et ce qui vise « n'importe qui de présent », replié.
- Initiatives : son budget du jour en cases (une case par initiative permise), sa période de recul, ce qu'elle a dit
  d'elle-même (répondu ou non, au premier coup d'œil) ; ses règles et les initiatives comptées sur le côté.
- Ses choix : une entrée par initiative décidée — ce qu'elle a choisi, le tirage, et la roue des lignes en lice
  (chacune à proportion de son taux, la choisie en couleur) ; leurs comptes, repliés.
- Épisodes : ses dernières 24 heures par issue et ses quatorze jours en barres, puis le fil des épisodes jour par jour
  (l'heure, la sorte, vers qui, l'issue, le détail), vers chaque épisode.
- Échéances : ce qui tournera, rangé par horizon (dans l'heure, aujourd'hui, plus tard, rien de prévu) ; ce qui
  échoue d'affilée, en tête.

Tout se lit dans la vue de la console (``inspector/pages/decisions.py``), jamais à l'arbitre ni au journal : chaque
ligne porte son calcul pas à pas (« Du signal au score » : chaque preuve, chaque modulation, le seuil, chaque veto,
avec son apport) et, repliés, sa sorte, sa cible et le rythme maximal de la sorte ; les barres en sont tirées. Ses
listes, leurs filtres, leur pagination et leur bascule « Tableau » restent ceux de la console.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import date_fr
from mika.app.handmade.tabs import Got, Line, Tab, blank, instant, lines, pairs, raw_lines, rest, text, tiles
from mika.inspector.ui import PREFIX
from mika.kernel.arbitration import sigmoid
from mika.kernel.clock import DAY, HOUR
from mika.kernel.inspect import Chart, num_fr

STYLES = ("handmade/decisions.css",)
#: entre deux segments de la barre d'une ligne, un jour (en centièmes de sa largeur)
GAP = 0.6


# ── Les mots des nombres ──────────────────────────────────────────────────


def _signed(value: float) -> str:
    return num_fr(value, 2, signed=True)


def _per_hour(per_second: float) -> str:
    """Un taux de l'arbitre (par seconde) en « fois par heure » : deux décimales sous 1, une sous 10, aucune
    au-delà (« 0,52 », « 3,6 », « 360 »)."""
    n = per_second * 3600
    return num_fr(n, 2 if n < 1 else 1 if n < 10 else 0)


def _delay(seconds: float) -> str:
    """Un temps d'attente moyen, dit simplement."""
    if not math.isfinite(seconds):
        return "un temps indéfini"
    if seconds < 90:
        return f"{num_fr(seconds, 0)} s"
    if seconds < 5400:
        return f"{num_fr(seconds / 60, 0)} min"
    if seconds < 2 * 86_400:
        return f"{num_fr(seconds / 3600, 1)} h"
    return f"{num_fr(seconds / 86_400, 1)} jours"


# ── Une ligne de l'arbitre, lisible ───────────────────────────────────────

#: le titre du calcul pas à pas qu'une ligne de la vue porte dans son détail (``inspector/pages/decisions.py``)
WATERFALL = "Du signal au score"
#: les étapes du calcul qui ajoutent ou retirent au score (le score final et les vetos n'en sont pas)
STEPS = ("preuve", "modulation", "attente", "seuil")


def _value(said: str) -> float | None:
    """Un nombre que la console a écrit à la française (« −0,35 », « +1,20 », « 12 345 ») ; rien s'il n'y en a pas."""
    clean = said.replace("\u2212", "-").replace("\u202f", "").replace("\u00a0", "").replace(" ", "")
    try:
        return float(clean.replace(",", ".").removeprefix("+"))
    except ValueError:
        return None


def _item(label: str, value: float, cls: str, hint: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "text": _signed(value), "cls": cls, "hint": hint}


def _waterfall(line: Line) -> list[dict[str, Any]]:
    """Le calcul pas à pas qu'une ligne porte dans son détail : chaque étape, ce qu'elle dit, son apport."""
    table = next((d for d in line.detail if d.get("t") == "table" and d.get("title") == WATERFALL), None)
    out = []
    for step in lines(table):
        quoi = step.get("quoi") or {}
        out.append({"what": step.text("étape"), "label": text(quoi), "hint": str(quoi.get("hint") or ""),
                    "value": _value(step.text("apport")), "total": step.text("cumul")})
    return out


def arbiter_line(line: Line, *, chosen: bool = False) -> dict[str, Any]:
    """Une ligne de l'arbitre telle que la vue la dit (sa table et son calcul pas à pas) : ce qui pousse, ce qui
    retient, la barre qui les met face à face, ce qui l'en empêche, ce qui en sort."""
    steps = _waterfall(line)
    pushes: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    idle: list[str] = []
    for st in steps:
        value = st["value"]
        if st["what"] not in STEPS or value is None:
            continue
        if st["what"] == "modulation" and st["hint"]:  # le réglage d'une faculté (sa clé au survol)
            st = {**st, "label": f"réglage · {st['label']}"}
        elif st["what"] == "attente":
            st = {**st, "label": "l'attente de la ligne"}
        if st["what"] == "seuil":  # la sorte est déjà dans le titre de la ligne
            holds.append(_item("le seuil de cette sorte d'épisode", value, "limit"))
        elif value > 0:
            pushes.append(_item(st["label"], value, "push", st["hint"]))
        elif value < 0:
            holds.append(_item(st["label"], value, "hold", st["hint"]))
        else:
            idle.append(st["label"])
    push = sum(x["value"] for x in pushes)
    hold = -sum(x["value"] for x in holds)
    whole = push + hold
    segments, x = [], 0.0
    for item in [*pushes, *holds]:
        w = 100 * abs(item["value"]) / whole if whole else 0.0
        segments.append({"x": round(x, 2), "w": round(max(0.0, w - GAP), 2), "cls": item["cls"]})
        x += w
    vetoes = [st["label"] for st in steps if st["what"] == "veto"]
    score = _value(line.text("score")) or 0.0
    per_hour = _value(line.text("fois / h")) or 0.0
    hazard = per_hour / 3600
    top = line.text("au plus (fois / h)")
    if vetoes:
        state, tag, tone = "blocked", "bloquée", "danger"
    elif hazard > 0 and score >= 0:
        state, tag, tone = "likely", "l'emporte", "ok"
    elif hazard > 0:
        state, tag, tone = "under", "sous le seuil", ""
    else:
        state, tag, tone = "still", "à l'arrêt", ""
    return {
        "label": line.text("ligne"), "kind": line.text("sorte"), "who": None if blank(line.get("vers")) else line["vers"],
        "state": state, "tag": tag, "tone": tone, "chosen": chosen,
        "pushes": pushes, "holds": holds, "idle": idle, "vetoes": vetoes, "segments": segments,
        "push": num_fr(push, 2), "hold": num_fr(hold, 2), "score": _signed(score), "gap": num_fr(abs(score), 2),
        "rate": _per_hour(hazard), "top": top if top not in ("", "—") else "",
        "share": round(100 * sigmoid(score), 1) if top and not vetoes else None,
        "wait": _delay(1 / hazard) if hazard > 0 else "",
        "steps": [{"what": st["what"], "label": st["label"], "text": _signed(st["value"]), "total": st["total"],
                   "tone": "ok" if st["value"] > 0 else "danger" if st["value"] < 0 else ""}
                  for st in steps if st["what"] in STEPS and st["value"] is not None],
        "hazard": hazard,
    }


def _policy(fields: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Le seuil et le rythme maximal de chaque sorte d'épisode, tels que la vue les dit (« seuil · initiative »)."""
    kinds: dict[str, dict[str, str]] = {}
    for label, cell in pairs(fields).items():
        what, _, kind = label.partition(" · ")
        said = text(cell)
        if what == "seuil":
            kinds.setdefault(kind, {})["threshold"] = said.split(" (", 1)[0]
        elif what == "taux max":
            kinds.setdefault(kind, {})["top"] = said.removesuffix(" fois / h")
    return [{"kind": k.capitalize(), "threshold": v.get("threshold", "—"), "top": v.get("top", "—")}
            for k, v in sorted(kinds.items())]


# ── Table de l'arbitre ────────────────────────────────────────────────────


def _outlook(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Ce que la table dit d'un coup : quand elle agirait, et sur quelle ligne ; ou pourquoi rien."""
    live = [x for x in items if x["hazard"] > 0 and not x["vetoes"]]
    total = sum(x["hazard"] for x in live)
    top = max(live, key=lambda x: x["hazard"], default=None)
    return {"lines": len(items), "blocked": sum(1 for x in items if x["vetoes"]), "live": len(live),
            "wait": _delay(1 / total) if total else "", "rate": _per_hour(total), "top": top["label"] if top else "",
            "share": round(100 * top["hazard"] / total) if top and total else 0}


def maintenant(got: Got) -> Markup | None:
    """Décisions › Table de l'arbitre : une phrase, puis chaque ligne, ce qui pousse face à ce qui retient."""
    t = got.table("La table de l'arbitre")
    if t is None:
        return None
    items = [arbiter_line(x) for x in got.lines("La table de l'arbitre")]
    outlook = _outlook(items)
    order = {"likely": 0, "under": 1, "still": 2, "blocked": 3}
    items.sort(key=lambda x: (order.get(x["state"], 4), -x["hazard"]))
    return got.draw("handmade/decisions/maintenant.html", t=t, items=items, outlook=outlook,
                    kinds=_policy(got.fields("Politique")), notes=got.notes())


# ── Que ferait-elle ? ─────────────────────────────────────────────────────


def envers(got: Got) -> Markup | None:
    """Décisions › Que ferait-elle ? : choisir une personne ; pour elle, son verdict en grand, puis ses lignes."""
    notes = got.notes()
    verdict = next((n for n in notes if str(n.get("title") or "").startswith("Envers ")), None)
    mine, shared = got.table("Ses lignes envers"), got.table("Lignes sans cible précise")
    if verdict is not None and mine is None:
        return None
    people = [{"name": x["personne"]["text"], "href": x["personne"].get("href", "")}
              for x in got.lines("Personnes dont une ligne existe")]
    return got.draw("handmade/decisions/envers.html", verdict=verdict, people=people,
                    notes=[n for n in notes if n is not verdict], mine=mine, shared=shared,
                    items=[arbiter_line(x) for x in got.lines("Ses lignes envers")] if mine is not None else [],
                    others=[arbiter_line(x) for x in got.lines("Lignes sans cible précise")] if shared is not None
                    else [])


# ── Initiatives ───────────────────────────────────────────────────────────


def _budget(c: Mapping[str, Any] | None) -> dict[str, Any]:
    """« 2 / 5 » : ses initiatives du jour en cases (au plus douze cases ; au-delà, le chiffre seul)."""
    said = text(c)
    try:
        done, cap = (int(part.strip()) for part in said.split("/", 1))
    except ValueError:
        return {"text": said, "slots": []}
    return {"text": said, "done": done, "cap": cap,
            "slots": [i < done for i in range(cap)] if 0 < cap <= 12 else []}


def _counted(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "today": line.text("aujourd'hui") == "oui"}


def initiatives(got: Got) -> Markup | None:
    """Décisions › Initiatives : son budget du jour, ce qu'elle a dit d'elle-même, ses règles."""
    budget, said = got.stats("Son budget"), got.timeline("Ce qu'elle a dit")
    if budget is None or said is None:
        return None
    b = tiles(budget)
    entries = said["entries"]
    answered = sum(1 for e in entries if e.get("tone") == "ok")
    waiting = sum(1 for e in entries if e.get("tone") == "warn")
    counted = got.table("Initiatives comptées")
    return got.draw("handmade/decisions/initiatives.html", b=b, today=_budget((b.get("aujourd'hui") or {}).get("value")),
                    said=said, entries=entries, answered=answered, waiting=waiting,
                    detail=pairs(got.fields("En détail")), counted=counted,
                    counted_items=[_counted(x) for x in got.lines("Initiatives comptées")])


# ── Ses choix ─────────────────────────────────────────────────────────────

#: le titre des lignes au moment d'un choix, dans le détail de ce choix (``inspector/pages/decisions.py``)
AT_CHOICE = "Les lignes au moment du choix"


def _choice(line: Line) -> dict[str, Any]:
    """Un choix de l'arbitre, tel que la vue le dit : le tirage (sa note), puis les lignes au moment du choix — la
    choisie est celle que la vue marque."""
    table = next((d for d in line.detail if d.get("t") == "table" and d.get("title") == AT_CHOICE), None)
    rows = [arbiter_line(x, chosen=x.tone == "ok") for x in lines(table)]
    alive = [x for x in rows if x["hazard"] > 0 and x["state"] != "blocked"]
    total = sum(x["hazard"] for x in alive)
    wheel, at = [], 0.0
    for x in sorted(alive, key=lambda x: (not x["chosen"], -x["hazard"])):
        w = 100 * x["hazard"] / total if total else 0.0
        wheel.append({"x": round(at, 2), "w": round(max(0.0, w - GAP), 2), "chosen": x["chosen"],
                      "label": x["label"], "share": f"{num_fr(w, 0)} %", "rate": x["rate"]})
        at += w
    note = next((d for d in line.rest if d.get("t") == "note"), None)
    return {"when": line.get("quand"), "href": line.href, "chosen": [x for x in rows if x["chosen"]],
            "draw": line.text("tirage"), "rates": line.text("Σ taux / borne (fois / h)"),
            "count": line.text("lignes"), "note": note, "wheel": wheel, "rows": rows,
            "blocked": [x for x in rows if x["state"] == "blocked"], "open": line.open}


def selections(got: Got) -> Markup | None:
    """Décisions › Ses choix : chaque initiative décidée, le tirage, la roue des lignes en lice."""
    t = got.table("Ses dernières initiatives décidées")
    if t is None:
        return None
    return got.draw("handmade/decisions/selections.html", t=t,
                    items=[_choice(x) for x in got.lines("Ses dernières initiatives décidées")])


# ── Épisodes ──────────────────────────────────────────────────────────────


def day_name(got: Got, at: int) -> str:
    frame = got.ui.kernel.mind.frame()
    day, today = frame.local(at).date(), frame.local(got.env.now).date()
    gap = (today - day).days
    return "Aujourd'hui" if gap == 0 else "Hier" if gap == 1 else date_fr(day).capitalize()


def by_day(got: Got, items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Des éléments datés (``at``), groupés par jour local, dans leur ordre."""
    days: list[dict[str, Any]] = []
    for x in items:
        name = day_name(got, x["at"]) if x["at"] else "Sans date"
        if not days or days[-1]["name"] != name:
            days.append({"name": name, "items": []})
        days[-1]["items"].append(x)
    return days


def _raw_chart(items: Sequence[Any]) -> Chart | None:
    for b in items:
        if isinstance(b, Chart):
            return b
        found = _raw_chart(getattr(b, "items", None) or ())
        if found is not None:
            return found
    return None


def _bars(got: Got) -> dict[str, Any] | None:
    """Ses épisodes par jour sur quatorze jours, en barres (le plus haut fait toute la hauteur)."""
    chart = _raw_chart(got.raw)
    if chart is None or not chart.series or not chart.series[0].points:
        return None
    frame = got.ui.kernel.mind.frame()
    today = frame.local(got.env.now).date()
    per_day = {frame.local(at).date(): v for at, v in chart.series[0].points}
    top = max(per_day.values()) or 1.0
    bars = []
    days = [frame.local(got.env.now - (13 - i) * DAY).date() for i in range(14)]
    for i, day in enumerate(days):
        n = per_day.get(day, 0.0)
        h = round(36 * n / top, 2)
        bars.append({"x": i * 10 + 1, "y": round(40 - h, 2), "h": h, "n": int(n), "day": date_fr(day),
                     "today": day == today})
    return {"bars": bars, "top": int(top)}


def _episode(line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    outcome = line.get("Issue")
    return {"at": instant(raw.get("Quand")), "when": line.get("Quand"), "kind": line.text("Épisode"),
            "who": None if blank(line.get("Vers")) or (line.get("Vers") or {}).get("kind") == "muted"
            else line.get("Vers"),
            "outcome": outcome if outcome and outcome.get("t") == "badge" else None,
            "detail": "" if blank(line.get("Détail")) else line.text("Détail"), "href": line.href,
            "failed": line.tone == "danger"}


def episodes(got: Got) -> Markup | None:
    """Décisions › Épisodes : ses dernières 24 heures, ses quatorze jours, puis le fil jour par jour."""
    t = got.table("Épisodes")
    if t is None:
        return None
    frame = got.ui.kernel.mind.frame()
    items = [_episode(x, r) for x, r in zip(got.lines("Épisodes"), raw_lines(got, t), strict=False)]
    for x in items:
        x["hm"] = frame.local(x["at"]).strftime("%H:%M") if x["at"] else ""
    counts = got.stats()
    activity = got.disclosure("Activité correspondant")
    return got.draw("handmade/decisions/episodes.html", t=t, days=by_day(got, items),
                    counts=(counts or {}).get("items", []), bars=_bars(got) if activity else None,
                    notes=[n for n in got.notes() if not (activity and n in activity.get("items", []))],
                    sampled=[n for n in (activity or {}).get("items", []) if n.get("t") == "note"])


# ── Échéances ─────────────────────────────────────────────────────────────

#: les horizons d'une échéance : (clé, titre, ce qu'il couvre)
HORIZONS = (("soon", "Dans l'heure", "ce qui tourne bientôt"), ("today", "Plus tard aujourd'hui", ""),
            ("later", "Plus tard", ""), ("never", "Rien de prévu", "ils attendent un événement, ou sont arrêtés"))


def _due(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    at = instant(raw.get("prochaine fois"))
    now = got.env.now
    frame = got.ui.kernel.mind.frame()
    if not at:
        horizon = "never"
    elif at - now < HOUR:
        horizon = "soon"
    elif frame.local(at).date() == frame.local(now).date():
        horizon = "today"
    else:
        horizon = "later"
    failing = line.get("échecs")
    return {"name": line["processus"], "faculty": line.text("faculté"), "lane": line.text("voie"),
            "next": line.get("prochaine fois") if at else None, "at": at,
            "hm": frame.local(at).strftime("%H:%M") if at and horizon in ("soon", "today") else "",
            "last": None if blank(line.get("dernière fois")) else line.get("dernière fois"),
            "runs": line.text("passages"), "horizon": horizon,
            "failing": failing if failing and failing.get("t") == "badge" else None,
            "danger": line.tone == "danger", "detail": rest(line, ("nom technique",)),
            "key": line.text("nom technique")}


def echeances(got: Got) -> Markup | None:
    """Décisions › Échéances : ce qui tournera, par horizon ; ce qui échoue d'affilée, en tête."""
    t = got.table("Ce qui tournera")
    if t is None:
        return None
    s = tiles(got.stats())
    items = [_due(got, x, r) for x, r in zip(got.lines("Ce qui tournera"), raw_lines(got, t), strict=False)]
    groups = [{"id": key, "title": title, "lede": lede, "items": [x for x in items if x["horizon"] == key]}
              for key, title, lede in HORIZONS]
    return got.draw("handmade/decisions/echeances.html", t=t, total=text((s.get("Processus") or {}).get("value")),
                    running=s.get("En cours"), groups=[g for g in groups if g["items"]],
                    failing=[x for x in items if x["danger"]], processes=f"{PREFIX}/systeme/processus")


TABS: dict[str, Any] = {
    "decisions/maintenant": Tab(maintenant, *STYLES),
    "decisions/envers": Tab(envers, *STYLES),
    "decisions/initiatives": Tab(initiatives, *STYLES),
    "decisions/selections": Tab(selections, *STYLES),
    "decisions/episodes": Tab(episodes, *STYLES),
    "decisions/echeances": Tab(echeances, *STYLES),
}
