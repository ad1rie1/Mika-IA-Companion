"""Elle › Pensées (Journal et rêves : ``nights.py``) : ses onglets, chacun dans sa forme (ADR 0177).

Les trois ont la même allure : une bande de chiffres quand la faculté en donne, puis des sous-onglets — ce qui se
passe maintenant, son historique (une page plus ancienne ouvre son sous-onglet), et comment ça marche.

- Pensées : ce qui lui trotte dans la tête, la plus forte d'abord — chacune de la couleur de son émotion, ce qu'il
  en reste en jauge, d'où elle est née, qui elle concerne ; puis toutes ses pensées, en fil ; et comment elles vivent.
- Ce qu'elle remarque : ce qui attend d'être remarqué, puis ce qu'elle a remarqué ces dernières minutes — la
  pertinence annoncée par la source et celle qu'elle a retenue sur une même barre (l'habituation se voit), l'émotion
  dosée ; puis tout ce qu'elle a remarqué ; et les règles.
- Attentes : ce qu'elle attend de qui, le temps écoulé vers l'échéance en jauge (échue : dit) ; puis les attentes
  closes, comblées ou déçues.

Les données restent celles de la faculté de l'attention (ses blocs, ses curseurs au journal).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, Tab, blank, gauge, instant, raw_lines, rest, subpanes, text

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


TABS: dict[str, Any] = {
    "pensees/pensees": Tab(pensees, *STYLES),
    "pensees/remarque": Tab(remarque, *STYLES),
    "pensees/attentes": Tab(attentes, *STYLES),
}
