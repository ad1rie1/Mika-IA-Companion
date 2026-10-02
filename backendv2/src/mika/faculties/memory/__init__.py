"""``memory`` : ce qu'elle garde de ce qu'elle vit.

Consolidation (le modèle dit ce qu'elle retient d'une fenêtre), index des
vecteurs (un cache), rappel filtré par la divulgation, outils. Voir
``contracts/memory.py`` pour ce que les autres peuvent lire.
"""

from mika.faculties.memory import (  # noqa: F401 — contributions
    consolidation,
    inspect,
    life,
    night,
    projections,
    recall,
    tools,
)
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState

__all__ = ["MEMORY", "MemoryParams", "MemoryState"]
