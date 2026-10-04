"""Où revenir après une écriture, sans faire confiance au POST.

``retour`` porte l'écran d'où l'on vient — c'est ce qui permet de résoudre
une revendication depuis la fiche d'une identité, ou d'approuver une action
depuis la fiche d'un projet, et d'y rester, filtres compris. Passé tel quel à
``redirect()``, c'est une redirection ouverte : un formulaire fabriqué
renvoie l'opérateur, déjà authentifié, sur un domaine tiers qui n'a plus
qu'à imiter l'écran de connexion.

Un seul contrôle pour tous les écrans. Il vivait dans ``views/social.py``
pendant que ``views/projects.py`` refaisait le ``redirect(back)`` brut à
quatre endroits : la seconde copie est celle qu'on oublie.
"""
from __future__ import annotations

from django.utils.http import url_has_allowed_host_and_scheme


def retour_sur(request, default: str, *, source: str = "POST", prefix: str = "") -> str:
    """L'URL de ``retour`` si elle reste sur ce site, sinon ``default``.

    Le contrôle est celui de Django (même hôte, schéma cohérent), pas une
    liste d'URL en dur : les onglets, filtres et numéros de page font partie
    de la valeur, et les énumérer serait à refaire à chaque écran ajouté.

    ``source="GET"`` sert aux fiches de lecture ; ``prefix`` peut restreindre
    leur retour à une section locale sans dupliquer le contrôle d'URL.
    """
    data = request.GET if source == "GET" else request.POST
    candidate = (data.get("retour") or "").strip()
    if prefix and not candidate.startswith(prefix):
        return default
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default
