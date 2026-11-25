"""Ce qui vient d'ailleurs (ADR 0192, 0219, 0310) : les services MCP, les apps de la Forge — des ressources dont les
outils ne sont pas à une famille d'elle, et dont la ligne est celle que leur faculté déclare (``RightsSpec.grants``).

Chaque sorte est à un domaine, qui dit dans sa part (``OutsidePart`` : l'``outside.py`` de son dossier) la famille de
ses outils, l'outil et la ressource d'une de ses lignes, la lecture même de sa ligne, le nom d'une de ses ressources et
à quoi elle sert, sa ligne dans Réglages › Droits ; ce module garde l'ordre des sortes (``OUTSIDE``) et réunit les
parts, sans en connaître aucune. Les lisent : la matrice de l'écran Outils (``app/me/rights.py``) et Réglages › Droits
(``app/handmade/rights.py``).
"""

from __future__ import annotations

import functools

from mika.app.domains import DOMAINS, OutsidePart, part

#: les sortes venues d'ailleurs, dans l'ordre des groupes de l'écran Outils : la sorte de leurs droits (la fin de la clé
#: de leur ``RightsSpec``), que la part d'un domaine dit (``OutsidePart.sort``)
OUTSIDE = ("services", "apps")


@functools.cache
def parts() -> dict[str, OutsidePart]:
    """La part de chaque sorte, dans l'ordre de ``OUTSIDE``. Lue à la demande, une fois, comme les autres parts ;
    chaque sorte de ``OUTSIDE`` a sa part, dite une fois."""
    found = [part(d.outside, "OUTSIDE") for d in DOMAINS if d.outside is not None]
    by_sort = {p.sort: p for p in found}
    if set(by_sort) != set(OUTSIDE) or len(by_sort) != len(found):
        raise ValueError("Ce qui vient d'ailleurs : chaque sorte a sa part, dite une fois, et sa place dans OUTSIDE — "
                         f"{sorted(set(OUTSIDE) ^ set(by_sort))}")
    return {sort: by_sort[sort] for sort in OUTSIDE}
