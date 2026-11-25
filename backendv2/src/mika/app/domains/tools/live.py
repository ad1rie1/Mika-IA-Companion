"""La part de ses outils venus d'ailleurs dans le direct (ADR 0308, 0310) : régler les paramètres du plugin ``mcp``
change ce que montre Paramètres, à toutes."""

from __future__ import annotations

from mika.app.domains.domain import LivePart
from mika.ports.changes import SETTINGS

LIVE = LivePart(params={"mcp": (SETTINGS,)})
