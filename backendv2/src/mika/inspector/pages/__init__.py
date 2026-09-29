"""Les pages de la console : les onglets qu'elle fournit elle-même (accueil,
décisions, approbations, réglages, système) et ses routes."""

from mika.inspector.pages import approvals, decisions, home, reglages, system  # noqa: F401 — enregistrement
from mika.inspector.pages.tabs import TABS

__all__ = ["TABS"]
