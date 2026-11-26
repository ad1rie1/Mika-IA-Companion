"""``memory`` : ce qu'elle garde de ce qu'elle vit.

Ses modules à contributions, importés ici pour qu'elles s'inscrivent :

- la consolidation : le modèle dit ce qu'elle retient d'une fenêtre (``consolidation``), et relit de même ce qu'on
  lui montre d'un téléphone (``relayed``, ADR 0120) ;
- l'index des vecteurs, un cache (``index``) ;
- le rappel filtré par la divulgation (``recall``), ses sections (``recall_sections``) et le récit sans nom
  (``veiled``, ADR 0091) ;
- la vie des autres et ses promesses (``life``), et l'archive des situations et des dates durables (``archive``) ;
- la nuit : réfléchir, trier, joindre (``night``), et relire ce qu'elle a lu (``reread``, ADR 0085) ;
- ses mensonges (``lies``, ADR 0076) et les sujets délicats (``delicate``, ADR 0099) ;
- ses projections (``projections``), ses outils (``tools``), ses vues de la console (``inspect``) et ce que
  l'opératrice y corrige (``actions``, ADR 0230).

Voir ``contracts/memory.py`` pour ce que les autres peuvent lire.
"""

from mika.faculties.memory import (  # noqa: F401 — contributions
    actions,
    archive,
    consolidation,
    delicate,
    index,
    inspect,
    lies,
    life,
    night,
    projections,
    recall,
    recall_sections,
    relayed,
    reread,
    tools,
    veiled,
)
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState

__all__ = ["MEMORY", "MemoryParams", "MemoryState"]
