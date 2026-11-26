"""Les comptes d'un canal (ADR 0185, 0186, 0207, 0310) : les boîtes, les comptes Teams.

Chaque canal qui a des comptes est à un domaine, qui dit dans sa part (``AccountsPart`` : l'``accounts.py`` de son
dossier) les comptes d'une personne, à qui est un compte, comment part ce qu'elle y prépare (ses brouillons, le geste
qui le règle) et comment la console les montre ; ce module garde l'ordre des canaux (``CHANNELS``) et réunit les
parts, sans en connaître aucune. Les lisent : la règle d'envoi d'un compte (``app/me/settings.py::rules_save``), la
matrice de l'écran Outils (« Tes comptes », ``app/me/rights.py``), l'onglet Comptes de la fiche d'une personne
(``app/handmade/person/``) et les instances de canal des tableaux de droits (``app/handmade/access.py``).
"""

from __future__ import annotations

import functools

from mika.app.domains import DOMAINS, AccountsPart, part
from mika.vocab.access import MAIL, TEAMS

#: les canaux qui ont des comptes, dans l'ordre où leurs comptes se lisent — la matrice, l'onglet Comptes (le premier
#: y porte les autres) : un canal par domaine, que sa part dit (``AccountsPart.canal``)
CHANNELS = (MAIL, TEAMS)


@functools.cache
def parts() -> dict[str, AccountsPart]:
    """La part de chaque canal, dans l'ordre de ``CHANNELS``. Lue à la demande, une fois : la part d'un domaine importe
    son module de l'API par personne, qui importe ce paquet. Chaque canal de ``CHANNELS`` a sa part, dite une fois."""
    found = [part(d.accounts, "ACCOUNTS") for d in DOMAINS if d.accounts is not None]
    by_canal = {p.canal: p for p in found}
    if set(by_canal) != set(CHANNELS) or len(by_canal) != len(found):
        raise ValueError("Comptes : chaque canal a sa part, dite une fois, et sa place dans CHANNELS — "
                         f"{sorted(set(CHANNELS) ^ set(by_canal))}")
    return {canal: by_canal[canal] for canal in CHANNELS}
