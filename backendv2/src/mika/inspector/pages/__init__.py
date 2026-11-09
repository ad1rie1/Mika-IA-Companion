"""Les pages de la console : les onglets qu'elle fournit elle-même (Accueil, À valider,
Réglages, Système) et ses routes."""

from mika.inspector.pages import (  # noqa: F401 — enregistrement
    accounts,
    approvals,
    canals,
    decisions,
    families,
    home,
    params,
    rights,
    settings_directory,
    system,
    tools,
)
from mika.inspector.pages.tabs import TABS

__all__ = ["TABS"]
