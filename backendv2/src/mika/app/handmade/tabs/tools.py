"""Outils › Prêter à un agent (Ce qu'elle peut faire, Venus d'ailleurs : ``handmade/tools.py``) : ses onglets, chacun
dans sa forme (ADR 0177).

- Prêter à un agent : la page est son panneau, déjà dessiné (``handmade/outils/expose.html`` : la console en lecture,
  ses points de prêt, le relais du moteur Claude Code) ; la vue n'a pas de blocs. L'onglet garde ce panneau, charge sa
  feuille (``handmade/tools.css``) et pose sa marque, rien de plus.
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Tab


def expose(got: Got) -> Markup:
    """Prêter à un agent : le panneau dit tout ; la marque de l'onglet, vide."""
    return got.draw("handmade/outils/preter.html")


TABS: dict[str, Any] = {
    "outils/expose": Tab(expose, "handmade/tools.css"),
}
