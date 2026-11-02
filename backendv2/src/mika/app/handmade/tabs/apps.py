"""Outils › Apps forgées : ses onglets, chacun dans sa forme (ADR 0177).

- Apps forgées : ses apps en tuiles, comme un lanceur — leur titre vers leur fiche, leur nom, leur état (une app
  cassée dit pourquoi, en rouge), promue ou non, leur version et leur agenda, leur dernier tour, ce qu'elles lui ont
  signalé. La recherche, la pagination et la bascule « Tableau » restent celles de la vue.

Seules les vues propres d'une app (sur sa fiche) gardent le rendu de la console (``plain_owners``) : la liste, elle,
se dessine. Elle se lit dans les blocs de la vue de la Forge (``plugins/forge/console.py``), qui reste la source.
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, Tab, blank, text
from mika.app.handmade.tabs.senses import state

STYLES = ("handmade/apps.css",)
#: l'agenda d'une app, en mots
SCHEDULES = {"manual": "à la demande", "": "à la demande"}


def _app(line: Line) -> dict[str, Any]:
    status = line.get("état") or {}
    said = text(status)
    broken = said.startswith("cassée")
    reason = said.split(" : ", 1)[1] if broken and " : " in said else ""
    last = line.text("dernier tour")
    rule = line.text("agenda")
    signals = line.text("signaux")
    return {"name": text(line.get("app")), "href": line.href or (line.get("app") or {}).get("href") or "",
            "title": line.text("titre") or text(line.get("app")),
            "status": {**status, "text": "cassée"} if broken else status, "reason": reason,
            "promoted": line.text("promue") == "oui", "version": line.text("version"),
            "schedule": SCHEDULES.get(rule, rule), "last": "" if blank(line.get("dernier tour")) else last,
            "last_failed": last.startswith("échec"), "never": last == "jamais",
            "signals": "" if signals in ("", "0", "—") else signals, "tone": status.get("tone") or ""}


def apps(got: Got) -> Markup | None:
    """Apps forgées : ses apps en tuiles."""
    table = got.table("Ses apps")
    if table is None:
        return None
    items = [_app(x) for x in got.lines("Ses apps")]
    return got.draw("handmade/apps/apps.html", state=state(got), t=table, items=items,
                    broken=sum(1 for x in items if x["tone"] == "danger"))


TABS: dict[str, Any] = {
    "apps/apps": Tab(apps, *STYLES),
}
