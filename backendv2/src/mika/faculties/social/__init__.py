"""``social`` : les liens — saluer, le rythme de chaque relation, la
proximité, ce qu'elle pense de chacun, le manque, le réconfort, la retenue.

Voir ``contracts/social.py`` pour ce que les autres peuvent lire.
"""

from mika.faculties.social import (  # noqa: F401 — contributions
    actions,
    initiative,
    inspect,
    profile,
    sections,
)
from mika.faculties.social.faculty import SOCIAL, SocialParams, SocialState

__all__ = ["SOCIAL", "SocialParams", "SocialState"]
