"""Les pages de la console : les onglets qu'elle fournit elle-même (tableau de
bord, décisions, approbations, configuration, système) et ses routes."""

from mika.inspector.pages import (  # noqa: F401 — enregistrement
    accounts,
    approvals,
    decisions,
    home,
    reglages,
    system,
)
from mika.inspector.pages.tabs import TABS

__all__ = ["TABS"]
