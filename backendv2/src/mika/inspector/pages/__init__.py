"""Les pages de la console : les onglets qu'elle fournit elle-même (tableau de
bord, décisions, approbations, configuration, système) et ses routes."""

from mika.inspector.pages import (  # noqa: F401 — enregistrement
    accounts,
    approvals,
    canals,
    decisions,
    families,
    home,
    reglages,
    rights,
    settings_directory,
    system,
    tools,
)
from mika.inspector.pages.tabs import TABS

__all__ = ["TABS"]
