"""Connexions extérieures › Réveils par API : ses onglets, chacun dans sa forme (ADR 0177).

- Réveils par API : ses réveils en tuiles — à quoi chacun sert, s'il est actif, s'il a sa clé, ce qui attend, son
  dernier appel ; puis ses derniers appels en fil, chacun avec ce qu'il apportait (une donnée venue d'ailleurs), où il
  en est, l'épisode qui l'a traité, et son détail replié. « Déclarer un réveil » est l'action de la page (barre de
  titre) ; ses réglages sont derrière la roue de la destination, qui ferme la barre (Réveils par API › Paramètres,
  ADR 0206).

Tout se lit dans les blocs de la vue du plugin (``plugins/wakeup/console.py``), qui reste la source pour la console en
MCP et le repli.
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, Tab, blank, number, pairs
from mika.app.handmade.tabs.senses import HEAD, state

STYLES = ("handmade/senses.css", "handmade/reveils.css")


def _endpoint(line: Line) -> dict[str, Any]:
    waiting = int(number(line.get("en attente")) or 0)
    last = line.get("dernier appel")
    return {"name": line["réveil"], "href": line.href, "label": "" if blank(line.get("à quoi il sert"))
            else line.text("à quoi il sert"), "state": line.get("état"), "key": line.get("clé"),
            "on": (line.get("état") or {}).get("tone") == "ok", "keyless": (line.get("clé") or {}).get("tone") == "warn",
            "waiting": waiting, "last": last if (last or {}).get("t") == "when" else None}


#: le compte rendu d'un appel, tel que la vue le titre
REPORT = "Son compte rendu"


def _call(line: Line) -> dict[str, Any]:
    """Un appel : ce qu'il apportait, où il en est, pourquoi il attend et son compte rendu en clair ; le reste de son
    détail (ce qu'il apportait en entier, ses faits, l'annuler) replié."""
    episode = line.get("épisode")
    why = next((d for d in line.detail if d.get("t") == "note"), None)
    report = next((d for d in line.detail if d.get("t") == "prose" and d.get("title") == REPORT), None)
    return {"when": line.get("reçu"), "endpoint": line.get("réveil"), "state": line.get("état"),
            "text": line["ce qu'il apportait"], "episode": episode if (episode or {}).get("t") == "link" else None,
            "failed": line.tone == "danger", "why": why["text"] if why else "",
            "report": str(report.get("text") or "") if report else "",
            "detail": [d for d in line.detail if d is not why and d is not report], "open": line.open}


def reveils(got: Got) -> tuple[Markup, list[Any], Markup] | None:
    """Réveils par API : ses réveils en tuiles, puis leurs derniers appels."""
    links, calls = pairs(got.fields()), got.table("Les ")
    if calls is None:
        return None
    endpoints = got.table("Réveils")
    # l'action de la page ; ses réglages sont derrière la roue de la destination (ADR 0206), pas un bouton de plus
    add = links.get("nouveau réveil") or {}
    head = got.draw(HEAD, primary=[("Déclarer un réveil", add["href"])] if add.get("href") else [])
    items = [_endpoint(x) for x in got.lines("Réveils")]
    html = got.draw("handmade/reveils/reveils.html", state=state(got), endpoints=endpoints, items=items,
                    waiting=sum(x["waiting"] for x in items), add=add.get("href") or "", calls=calls,
                    call_items=[_call(x) for x in got.lines("Les ")], name=str(got.query.get("reveil") or ""))
    return html, [], head


TABS: dict[str, Any] = {
    "reveils/reveils": Tab(reveils, *STYLES),
}
