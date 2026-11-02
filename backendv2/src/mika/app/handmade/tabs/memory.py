"""Elle › Mémoire : ses onglets, chacun dans sa forme (ADR 0177).

- Souvenirs : une entrée par souvenir, son texte d'abord — la couleur de l'émotion qu'il porte, à qui il se rapporte,
  ce qu'il en reste —, en deux colonnes sur un grand écran ; le détail (qui l'a confié, d'où il vient) replié.
- Croyances : la même liste, chaque croyance avec sa confiance en avant (un chiffre et sa jauge) et son origine
  (on le lui a dit, elle l'a vu, elle le déduit) ; une croyance remplacée s'estompe, celle qui la remplace le dit.
- Pièces reçues : une entrée par pièce — sa sorte en icône, son nom vers sa fiche, qui l'a envoyée, ce qu'elle y a
  lu, ce qui s'y relie, la télécharger.
- Place des pièces : la place de chacun en chiffres, puis une jauge par personne, de la plus chargée à la moins
  chargée.
- Promesses : celles qui l'engagent encore d'abord, leur échéance à gauche (en retard : dit) ; puis, côte à côte,
  celles qu'elle a tenues et celles qu'elle a abandonnées.
- La vie des autres : un agenda — ce qui dure en ce moment, ce qui vient (le plus proche d'abord), ce qui est passé
  et comment ça a tourné —, chaque moment avec sa date en pavé de calendrier.
- Voir venir : ses attentes par sorte d'annonce, sur une échelle de « toujours juste » à « pile ou face » ; et qui
  tient ce qu'il annonce, tenus et manqués sur une même barre.
- Consolidation : où en est la relecture, en une phrase et une bande de chiffres ; puis en sous-onglets les passages
  à reprendre (leur action sur leur ligne), ses relectures, les tris de la nuit et l'état détaillé.

Souvenirs, croyances, promesses et moments viennent de la même liste de la faculté (``memory``) : leurs filtres, leur
pagination et leur bascule « Tableau » restent les siens ; ce qui distingue chacun se lit dans ses colonnes, et pour
un moment, dans ce que la faculté sait de lui (une situation qui dure, comment il a tourné).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade import MONTHS, WEEKDAYS
from mika.app.handmade.lists import ORDINARY
from mika.app.handmade.nights import day_label
from mika.app.handmade.tabs import (
    Got,
    Line,
    Tab,
    blank,
    gauge,
    instant,
    number,
    pairs,
    raw_lines,
    rest,
    subpanes,
    text,
    tiles,
)
from mika.faculties.memory.inspect import ORIGIN_FR
from mika.inspector import render
from mika.inspector.ui import PREFIX
from mika.kernel.frame import Frame
from mika.kernel.inspect import Ref

STYLES = ("handmade/memoire.css",)


# ── Ce que partagent les onglets ──────────────────────────────────────────


def _item(line: Line, body: str, *quiet: str, shown: Iterable[str] = ()) -> dict[str, Any]:
    """Ce que partagent un souvenir, une croyance, une promesse et un moment : leur texte, les étiquettes qui disent
    quelque chose (l'état ordinaire se tait), leur numéro, leur origine, leur détail (``shown`` : les colonnes
    repliées que la page montre déjà)."""
    hush = ORDINARY | set(quiet)
    return {"text": line[body], "n": line.get("n°"), "href": line.href, "faded": line.tone == "muted",
            "tags": [b for b in (line.get("sensibilité"), line.get("statut"))
                     if not blank(b) and b["text"].casefold() not in hush],
            "detail": rest(line, shown), "open": line.open}


def _detail(line: Line) -> dict[str, dict[str, Any]]:
    """Les faits du détail d'un élément retenu (« Détail » : qui l'a confié, ce qu'il remplace…)."""
    return pairs(next((d for d in line.detail if d.get("t") == "fields" and d.get("title") == "Détail"), None))


def _empty_or_none(got: Got, template: str) -> Markup | None:
    """Une liste que la faculté n'a pas pu lire (sa table n'existe pas encore) : sa note, dans la forme de la page ;
    une liste qui manque sans rien dire (un titre changé) : ses blocs."""
    notes = got.notes()
    return got.draw(template, t=None, notes=notes) if notes else None


# ── Souvenirs ─────────────────────────────────────────────────────────────


def _memory(line: Line) -> dict[str, Any]:
    emotion = line.get("émotion")
    return {**_item(line, "souvenir", shown=("ce qu'il en reste", "émotion")), "about": line.get("concerne"),
            "born": line.get("né"), "emotion": emotion if emotion and emotion.get("t") == "swatch" else None,
            "left": gauge(line.get("ce qu'il en reste"))}


def souvenirs(got: Got) -> Markup | None:
    """Mémoire › Souvenirs : une entrée par souvenir."""
    table = got.table("Ses souvenirs")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/souvenirs.html")
    return got.draw("handmade/memoire/souvenirs.html", t=table, items=[_memory(x) for x in got.lines("Ses souvenirs")],
                    notes=got.notes())


# ── Croyances ─────────────────────────────────────────────────────────────


def _origin(said: str) -> dict[str, str] | None:
    """« on le lui a dit (Adrien) » : sa sorte (``told``…), ses mots, qui."""
    for kind, words in ORIGIN_FR.items():
        if said.startswith(words):
            return {"kind": kind, "text": words, "who": said[len(words):].strip().removeprefix("(").removesuffix(")")}
    return None if said.strip() in ("", "—") else {"kind": "", "text": said, "who": ""}


def _belief(line: Line) -> dict[str, Any]:
    item = _item(line, "croyance", shown=("née",))
    replaced = line.text("statut").casefold().startswith("remplacée")
    return {**item, "trust": gauge(line.get("confiance")), "origin": _origin(line.text("origine")),
            "about": line.get("concerne"), "born": line.get("née"), "replaces": _detail(line).get("remplace"),
            "faded": item["faded"] or replaced}


def croyances(got: Got) -> Markup | None:
    """Mémoire › Croyances : chacune avec sa confiance et son origine."""
    table = got.table("Ses croyances")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/croyances.html")
    return got.draw("handmade/memoire/croyances.html", t=table, items=[_belief(x) for x in got.lines("Ses croyances")],
                    notes=got.notes())


# ── Promesses ─────────────────────────────────────────────────────────────

#: l'état d'une promesse, tel que la faculté l'écrit, et sa place dans la page
PROMISE_STATES = {"en cours": "open", "tenue": "kept", "abandonnée": "dropped"}


def _promise(line: Line, raw: Mapping[str, Any], now: int) -> dict[str, Any]:
    state = PROMISE_STATES.get(line.text("statut").casefold(), "open")
    due = instant(raw.get("échéance"))
    return {**_item(line, "promesse", *PROMISE_STATES, shown=("faite",)), "state": state, "to": line.get("à qui"),
            "due": line.get("échéance") if due else None, "late": state == "open" and 0 < due < now,
            "made": line.get("faite")}


def promesses(got: Got) -> Markup | None:
    """Mémoire › Promesses : celles qui l'engagent, puis celles qu'elle a tenues ou abandonnées."""
    table = got.table("Ses promesses")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/promesses.html")
    items = [_promise(x, r, got.env.now) for x, r in zip(got.lines("Ses promesses"), raw_lines(got, table),
                                                          strict=False)]
    groups = {state: [x for x in items if x["state"] == state] for state in PROMISE_STATES.values()}
    return got.draw("handmade/memoire/promesses.html", t=table, items=items, groups=groups, notes=got.notes())


# ── La vie des autres ─────────────────────────────────────────────────────

WEEKDAYS_SHORT = tuple(d[:3] + "." for d in WEEKDAYS)


def _moment(frame: Frame, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Un moment, tel que la vue le dit — lu dans l'archive de la faculté : une situation qui dure encore, comment il
    a tourné, s'il se fête, même passé depuis longtemps."""
    at = instant(raw.get("quand"))
    ongoing = line.text("situation") == "dure encore"
    item = _item(line, "moment", "à suivre", "personnel")
    tags = [line["issue"]] if not blank(line.get("issue")) else []
    if not blank(line.get("chaque année")):
        tags.append({"text": "revient chaque année", "tone": "info"})
    if not blank(line.get("se fête")):
        tags.append(line["se fête"])
    if line.text("situation") == "finie":
        tags.append(line["situation"])
    date = frame.local(at) if at else None
    return {**item, "tags": tags + list(item["tags"]), "who": line.get("de qui"), "when": line.get("quand"),
            "at": at, "place": "current" if ongoing else "ahead" if at >= frame.now else "past",
            "day": {"d": date.day, "m": MONTHS[date.month - 1], "w": WEEKDAYS_SHORT[date.weekday()]} if date else None,
            "noted": line.get("noté"), "faded": item["faded"] or line.text("statut").casefold().startswith("remplacé")}


def moments(got: Got) -> Markup | None:
    """Mémoire › La vie des autres : ce qui dure, ce qui vient, ce qui est passé — chaque moment à sa date."""
    table = got.table("Ce qui se passe dans la vie des autres")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/moments.html")
    frame = got.ui.kernel.mind.frame()
    items = [_moment(frame, x, r) for x, r in zip(got.lines("Ce qui se passe dans la vie des autres"),
                                                       raw_lines(got, table), strict=False)]
    groups = [
        ("current", "En ce moment", "ce qui dure dans leur vie, depuis le jour où ça a commencé",
         sorted((x for x in items if x["place"] == "current"), key=lambda x: -x["at"])),
        ("ahead", "À venir", "le plus proche d'abord : elle y pense quand c'est proche",
         sorted((x for x in items if x["place"] == "ahead"), key=lambda x: x["at"])),
        ("past", "Passés", "elle en demande des nouvelles après",
         sorted((x for x in items if x["place"] == "past"), key=lambda x: -x["at"])),
    ]
    return got.draw("handmade/memoire/moments.html", t=table, items=items,
                    groups=[{"id": g, "title": title, "lede": lede, "items": xs}
                            for g, title, lede, xs in groups if xs],
                    notes=got.notes())


# ── Pièces reçues, place des pièces ──────────────────────────────────────

#: la sorte d'une pièce, telle que la faculté l'écrit, et son icône
PIECE_KINDS = {"photo": "image", "vocal": "audio", "document": "file"}


def _piece(line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    state = line.get("état")
    href = raw.get("nom")
    tied = int(number(line.get("liens")) or 0)
    links = render.href(Ref(href.kind, href.key, "", (("onglet", "liens"),))) if isinstance(href, Ref) else ""
    return {"name": line["nom"], "from": line.get("de"), "kind": PIECE_KINDS.get(line.text("sorte"), "file"),
            "sort": line.text("sorte"), "size": line.text("taille"), "at": line.get("reçue"),
            "seen": None if blank(line.get("ce qu'elle y a lu")) else line.get("ce qu'elle y a lu"),
            "state": None if blank(state) or text(state) == "gardée" else state,
            "gone": text(state).startswith("retirée"), "unread": text(state) == "gardée, pas lue",
            "tied": tied, "links": links if tied else "",
            "download": line.get("télécharger") if (line.get("télécharger") or {}).get("t") == "link" else None}


def recues(got: Got) -> Markup | None:
    """Mémoire › Pièces reçues : une entrée par pièce, ce qu'elle y a lu en avant."""
    table = got.table("Pièces reçues")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/recues.html")
    items = [_piece(x, r) for x, r in zip(got.lines("Pièces reçues"), raw_lines(got, table), strict=False)]
    return got.draw("handmade/memoire/recues.html", t=table, items=items, notes=got.notes())


def place(got: Got) -> Markup | None:
    """Mémoire › Place des pièces : la place de chacun, une jauge par personne."""
    table, facts = got.table("Par personne"), got.fields("Place")
    if table is None or facts is None:
        return _empty_or_none(got, "handmade/memoire/place.html")
    f = pairs(facts)
    people = [{"who": x["personne"], "href": x.href, "n": x.text("pièces"), "used": x.text("occupé"),
               "share": gauge(x.get("de sa place"))} for x in got.lines("Par personne")]
    band = {"t": "stats", "title": "", "items": [
        {"label": "Place de chacun", "value": f.get("place par personne") or {"t": "text", "text": "—"},
         "sub": "tous ses moyens de communication réunis"},
        {"label": "En tout", "value": f.get("en tout") or {"t": "text", "text": "—"},
         "sub": f"pour {text(f.get('personnes'))} personne(s)" if number(f.get("personnes")) else "rien de gardé"}]}
    return got.draw("handmade/memoire/place.html", t=table, band=band, budget=text(f.get("place par personne")),
                    people=people, notes=got.notes())


# ── Voir venir ────────────────────────────────────────────────────────────

#: l'écart quadratique moyen (Brier) d'une attente : 0, toujours juste ; 0,25, comme à pile ou face ; l'échelle
#: montrée va jusqu'à 0,5
BRIER_SCALE = 0.5
COIN = 0.25


def _calibration(line: Line) -> dict[str, Any]:
    brier = number(line.get("écart moyen (Brier)"))
    tone = "" if brier is None else "ok" if brier < 0.1 else "warn" if brier < COIN else "danger"
    return {"nature": line.text("sorte d'annonce"), "seen": line.text("constatés"),
            "brier": line.text("écart moyen (Brier)"),
            "x": None if brier is None else round(100 * min(brier, BRIER_SCALE) / BRIER_SCALE, 1), "tone": tone,
            "verdict": line.get("ce qu'elle en fait")}


def _teller(line: Line) -> dict[str, Any]:
    kept, missed = int(number(line.get("tenus")) or 0), int(number(line.get("reportés ou annulés")) or 0)
    total = kept + missed
    return {"who": line.text("qui annonce"), "kept": kept, "missed": missed,
            "split": round(100 * kept / total, 1) if total else 0.0,
            "worth": gauge(line.get("ce que vaut son annonce"))}


def voir_venir(got: Got) -> Markup | None:
    """Mémoire › Voir venir : ses attentes sur une échelle, et qui tient ce qu'il annonce."""
    expected, tellers = got.table("Ce qu'elle attendait"), got.table("Ce qu'elle apprend de qui annonce")
    if expected is None or tellers is None:
        return None
    return got.draw("handmade/memoire/voir_venir.html", expected=expected, tellers=tellers,
                    natures=[_calibration(x) for x in got.lines("Ce qu'elle attendait")],
                    people=[_teller(x) for x in got.lines("Ce qu'elle apprend de qui annonce")],
                    coin=round(100 * COIN / BRIER_SCALE, 1))


# ── Consolidation ─────────────────────────────────────────────────────────

#: les chiffres de « Ce qu'elle garde », et l'onglet où ils mènent
KEPT_TABS = {"Souvenirs": "souvenirs", "Croyances": "croyances", "Promesses en cours": "promesses"}
#: les curseurs de ses listes au journal (``faculties/memory/inspect.py``) : leur sous-onglet
CURSORS = (("avant", "consol-runs"), ("avant_nuits", "consol-nights"), ("reprises", "consol-queue"))


def _passage(line: Line) -> dict[str, Any]:
    acts = [d for d in line.rest if d.get("t") == "action"]
    return {"title": line["passage"], "state": line.get("état"), "cause": line.get("cause"),
            "since": line.get("depuis"),
            "tries": line.text("essais"), "next": line.get("prochaine reprise"), "acts": acts,
            "detail": [d for d in line.rest if d.get("t") != "action"], "open": line.open}


def _run(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "upto": line.get("relu jusqu'au"), "kept": line.text("retenus"),
            "outcome": line.get("issue"), "model": line.text("modèle"), "href": line.href,
            "failed": line.tone == "danger"}


def _night(line: Line) -> dict[str, Any]:
    return {"night": day_label(line.text("nuit")), "merges": line.text("fusions"), "pairs": line.get("fondu → gardé"),
            "when": line.get("quand"), "href": line.href, "detail": line.rest}


def consolidation(got: Got) -> Markup | None:
    """Mémoire › Consolidation : où en est la relecture, puis ses sous-onglets."""
    rereading, runs, nights = got.fields("La relecture"), got.table("Les dernières relectures"), got.table(
        "Les tris de la nuit")
    if rereading is None or runs is None or nights is None:
        return None
    f = pairs(rereading)
    queue = got.table("Passages à reprendre")
    kept = tiles(got.stats("Ce qu'elle garde"))
    band = [{**s, "href": f"{PREFIX}/memoire/{KEPT_TABS[label]}"} for label, s in kept.items() if label in KEPT_TABS]
    waiting = text(f.get("messages pas encore relus")) or "0"
    band.append({"label": "Pas encore relus", "value": {"t": "text", "text": waiting, "kind": "num"},
                 "sub": "messages en attente",
                 "tone": ""})
    if queue is not None:
        band.append({"label": "À reprendre", "value": {"t": "text", "text": str(queue["count"] or 0), "kind": "num"},
                     "sub": "passages que la relecture n'a pas pu traiter", "tone": "warn" if queue["count"] else "",
                     "href": "#consol-queue"})
    first = next((pane for param, pane in CURSORS if got.query.get(param)), "")
    panes = subpanes([{"id": "consol-queue"}, {"id": "consol-runs"}, {"id": "consol-nights"}, {"id": "consol-state"}],
                     first)
    return got.draw("handmade/memoire/consolidation.html", f=f, band={"t": "stats", "title": "", "items": band},
                    rereading=rereading, queue=queue, passages=[_passage(x) for x in got.lines("Passages à reprendre")],
                    runs=runs, run_items=[_run(x) for x in got.lines("Les dernières relectures")],
                    nights=nights, night_items=[_night(x) for x in got.lines("Les tris de la nuit")],
                    panes=[p["id"] for p in panes], notes=got.notes())


TABS: dict[str, Any] = {
    "memoire/souvenirs": Tab(souvenirs, *STYLES),
    "memoire/croyances": Tab(croyances, *STYLES),
    "memoire/recues": Tab(recues, *STYLES),
    "memoire/place": Tab(place, *STYLES),
    "memoire/promesses": Tab(promesses, *STYLES),
    "memoire/moments": Tab(moments, *STYLES),
    "memoire/voir-venir": Tab(voir_venir, *STYLES),
    "memoire/consolidation": Tab(consolidation, *STYLES),
}
