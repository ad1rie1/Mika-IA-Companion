"""Elle › Pensées : ses onglets, chacun dans sa forme (ADR 0177).

Les trois premiers ont la même allure : une bande de chiffres quand la faculté en donne, puis des sous-onglets — ce qui se
passe maintenant, son historique (une page plus ancienne ouvre son sous-onglet), et comment ça marche.

- Pensées : ce qui lui trotte dans la tête, la plus forte d'abord — chacune de la couleur de son émotion, ce qu'il
  en reste en jauge, d'où elle est née, qui elle concerne ; puis toutes ses pensées, en fil ; et comment elles vivent.
- Ce qu'elle remarque : ce qui attend d'être remarqué, puis ce qu'elle a remarqué ces dernières minutes — la
  pertinence annoncée par la source et celle qu'elle a retenue sur une même barre (l'habituation se voit), l'émotion
  dosée ; puis tout ce qu'elle a remarqué ; et les règles.
- Attentes : ce qu'elle attend de qui, le temps écoulé vers l'échéance en jauge (échue : dit) ; puis les attentes
  closes, comblées ou déçues.
- Journal et rêves : son journal de la nuit en page de carnet, ce qu'elle en raconte à n'importe qui, sa journée en
  cours telle qu'elle pourra la dire demain ; puis ses nuits, une carte par nuit — son journal et ses rêves ensemble,
  ce dont elle s'est souvenue au réveil. Le fil « en bref » de la faculté redisait l'historique : il se tait.

Les données restent celles de la faculté de l'attention (ses blocs, ses curseurs au journal) ; celles de Journal et
rêves, celles de la faculté de soi (son onglet ``nuits`` : ses textes, son historique paginé au journal).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from markupsafe import Markup

from mika.app.handmade import date_fr
from mika.app.handmade.lists import listing
from mika.app.handmade.tabs import Got, Line, Tab, blank, gauge, instant, raw_lines, rest, subpanes, text
from mika.inspector.ui import env
from mika.kernel.inspect import Prose

STYLES = ("handmade/pensees.css",)
#: le curseur de leurs historiques au journal (``faculties/attention/inspect.py``)
CURSOR = "avant"


def _swatch(c: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return dict(c) if c and c.get("t") == "swatch" else None


def _first(got: Got, pane: str) -> str:
    """Le sous-onglet de l'historique en premier quand on le feuillette (son curseur est dans l'adresse)."""
    return pane if got.query.get(CURSOR) else ""


# ── Pensées ───────────────────────────────────────────────────────────────


def born_of(origin: str) -> str:
    """D'où est née une pensée, en une phrase : « née d'un échange », « née parce que personne ne lui écrit »."""
    if not origin or origin == "—":
        return ""
    if origin.startswith(("un ", "une ")):
        return f"née d’{origin}"
    return f"née parce qu’{origin}" if origin.startswith(("elle ", "il ")) else f"née parce que {origin}"


def _thought(line: Line) -> dict[str, Any]:
    strength = gauge(line.get("intensité"))
    return {"text": line["pensée"], "emotion": _swatch(line.get("couleur")), "strength": strength,
            "origin": born_of(line.text("née de")),
            "about": None if line.text("concerne") == "personne" else line.get("concerne"),
            "born": line.get("née"), "touched": None if blank(line.get("ravivée")) else line.get("ravivée"),
            "href": line.href, "detail": rest(line, ("née de", "ravivée")), "open": line.open,
            "faded": line.tone == "muted",
            "faint": strength is not None and strength["w"] < 10}


def _past_thought(line: Line) -> dict[str, Any]:
    return {"text": line["pensée"], "emotion": _swatch(line.get("couleur à la naissance")),
            "origin": born_of(line.text("née de")),
            "about": None if line.text("concerne") == "personne" else line.get("concerne"),
            "born": line.get("née"), "now": line.get("maintenant"), "alive": line.text("maintenant") == "vivante",
            "href": line.href, "detail": rest(line, ("couleur à la naissance", "née de")), "open": line.open}


def pensees(got: Got) -> Markup | None:
    """Pensées › Pensées : ce qui lui trotte dans la tête, toutes ses pensées, comment elles vivent."""
    live, history = got.table("Ce qui lui trotte dans la tête"), got.table("Toutes ses pensées")
    if live is None or history is None:
        return None
    thoughts = sorted((_thought(x) for x in got.lines("Ce qui lui trotte dans la tête")),
                      key=lambda x: -(x["strength"] or {"w": 0})["w"])
    panes = subpanes([{"id": "thoughts-now"}, {"id": "thoughts-history"}, {"id": "thoughts-rules"}],
                     _first(got, "thoughts-history"))
    return got.draw("handmade/pensees/pensees.html", band=got.stats(), live=live, thoughts=thoughts,
                    history=history, past=[_past_thought(x) for x in got.lines("Toutes ses pensées")],
                    rules=got.fields("Comment elles vivent"), panes=[p["id"] for p in panes])


# ── Ce qu'elle remarque ───────────────────────────────────────────────────


def _heard(line: Line) -> dict[str, Any]:
    announced, kept, weight = gauge(line.get("pertinence annoncée")), gauge(line.get("pertinence retenue")), gauge(
        line.get("poids (habituation)"))
    return {"when": line.get("quand"), "source": line["source"], "kind": line.text("sorte"), "announced": announced,
            "kept": kept, "weight": weight, "habituated": weight is not None and weight["w"] < 99.5,
            "emotion": _swatch(line.get("émotion dosée")),
            "detail": rest(line, ("pertinence annoncée", "poids (habituation)")), "open": line.open}


def _waiting(line: Line) -> dict[str, Any]:
    return {"when": line.get("signalé"), "source": line["source"], "kind": line.text("sorte"),
            "summary": line["résumé"],
            "announced": gauge(line.get("pertinence annoncée")),
            "kept": gauge(line.get("retenue si remarqué maintenant"))}


def _past_heard(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "source": line["source"], "kind": line.text("sorte"),
            "weight": gauge(line.get("poids (habituation)")), "emotion": _swatch(line.get("émotion dosée"))}


def remarque(got: Got) -> Markup | None:
    """Pensées › Ce qu'elle remarque : ce qui attend, ce qu'elle vient de remarquer, tout ce qu'elle a remarqué."""
    recent, history = got.table("Remarqué ces dernières minutes"), got.table("Tout ce qu'elle a remarqué")
    if recent is None or history is None:
        return None
    waiting = got.table("Signalé, pas encore remarqué")
    panes = subpanes([{"id": "noticed-now"}, {"id": "noticed-history"}, {"id": "noticed-rules"}],
                     _first(got, "noticed-history"))
    return got.draw("handmade/pensees/remarque.html", recent=recent,
                    heard=[_heard(x) for x in got.lines("Remarqué ces dernières minutes")], waiting=waiting,
                    queue=[_waiting(x) for x in got.lines("Signalé, pas encore remarqué")] if waiting else [],
                    history=history, past=[_past_heard(x) for x in got.lines("Tout ce qu'elle a remarqué")],
                    rules=got.fields("Comment elle remarque"), panes=[p["id"] for p in panes])


# ── Attentes ──────────────────────────────────────────────────────────────


def _expectation(line: Line, raw: Mapping[str, Any], now: int) -> dict[str, Any]:
    since, due = instant(raw.get("depuis")), instant(raw.get("échéance"))
    state = line.get("état") or {}
    late = bool(due) and due <= now
    return {"what": line.text("elle attend"), "who": line.get("de"), "since": line.get("depuis"),
            "due": line.get("échéance") if due else None, "state": state,
            "progress": round(100 * min(1.0, max(0.0, (now - since) / (due - since))), 1) if due > since > 0 else None,
            "late": late, "tone": state.get("tone") or ""}


def _closed(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "what": line.text("elle attendait"), "who": line.get("de"),
            "since": line.get("depuis"), "outcome": line.get("issue"), "event": line.get("événement"),
            "met": text(line.get("issue")) == "comblée"}


def attentes(got: Got) -> Markup | None:
    """Pensées › Attentes : ce qu'elle attend, puis les attentes closes."""
    open_, closed = got.table("Ce qu'elle attend"), got.table("Attentes closes")
    if open_ is None or closed is None:
        return None
    waits = [_expectation(x, r, got.env.now) for x, r in zip(got.lines("Ce qu'elle attend"), raw_lines(got, open_),
                                                             strict=False)]
    panes = subpanes([{"id": "waits-now"}, {"id": "waits-closed"}], _first(got, "waits-closed"))
    return got.draw("handmade/pensees/attentes.html", band=got.stats(), open=open_, waits=waits, closed=closed,
                    done=[_closed(x) for x in got.lines("Attentes closes")], panes=[p["id"] for p in panes])


# ── Journal et rêves ──────────────────────────────────────────────────────

#: les textes de l'onglet, reconnus au début de leur titre : (le début, sa place dans la page)
TEXTS = (("Journal du ", "journal"), ("Ce qu'elle en raconte", "told"), ("Sa journée en cours", "today"))
#: ce que dit la colonne « souvenu au réveil » d'un rêve
REMEMBERED = {"oui": "souvenu au réveil", "non": "oublié au réveil"}
#: ce que dit la colonne « concerne » quand une nuit ne concerne personne : il se tait
NOBODY = "personne"


def day_label(iso: str) -> str:
    """« 2026-10-20 » : « lundi 20 oct. » (tel quel s'il n'est pas une date)."""
    try:
        d = date.fromisoformat(iso.strip())
    except ValueError:
        return iso
    return date_fr(d)


def _day_in(title: str) -> str:
    """La journée nommée dans un titre de la faculté : « Journal du 2026-10-20, en entier », « … (2026-10-21) »."""
    for part in title.replace("(", " ").replace(")", " ").replace(",", " ").split():
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    return ""


def nights(got: Got) -> Markup | None:
    """Journal et rêves : le journal, ce qu'elle en raconte, sa journée en cours, puis une carte par nuit."""
    table = got.raw_table()
    if table is None:
        return None
    texts: dict[str, dict[str, str]] = {}
    for b in got.raw:
        if isinstance(b, Prose):
            known = next((place for start, place in TEXTS if b.title.startswith(start)), None)
            if known is None:
                return None  # un texte qu'elle ne connaît pas : les blocs de la faculté
            texts[known] = {"text": b.text, "day": day_label(_day_in(b.title))}
    history = listing(table, got.env, got.query)
    # l'historique suit l'ordre d'écriture (un rêve s'écrit à part de son journal) : une carte par nuit, la plus
    # récente d'abord, son journal puis ses rêves
    by_night: dict[str, list[dict[str, Any]]] = {}
    for row in history["rows"]:
        fields = {f["label"]: f["value"] for f in row["fields"]}
        kind = (row["badges"] or [{}])[0]
        remembered = text(fields.get("souvenu au réveil")).casefold()
        about = fields.get("concerne")
        by_night.setdefault(text(fields.get("nuit")), []).append({
            "kind": kind, "journal": text(kind).casefold() == "journal",
            "text": (row["body"] or [{}])[0].get("value"),
            "about": about if text(about) not in ("", NOBODY) else None,
            "remembered": REMEMBERED.get(remembered, ""), "awake": remembered == "oui",
            "detail": row.get("detail") or [],
        })
    groups = [{"label": day_label(night), "entries": sorted(entries, key=lambda e: not e["journal"])}
              for night, entries in sorted(by_night.items(), reverse=True)]
    return Markup(env.get_template("handmade/pensees/nuits.html").render(
        journal=texts.get("journal"), told=texts.get("told"), today=texts.get("today"), groups=groups,
        history=history, forms={}))


TABS: dict[str, Any] = {
    "pensees/pensees": Tab(pensees, *STYLES),
    "pensees/remarque": Tab(remarque, *STYLES),
    "pensees/attentes": Tab(attentes, *STYLES),
    "pensees/nuits": Tab(nights, "handmade/nights.css"),
}
