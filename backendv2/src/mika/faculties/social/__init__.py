"""``social`` : les liens — saluer, le rythme de chaque relation, la
proximité, ce qu'elle pense de chacun, le manque, le réconfort, la retenue.

Voir ``contracts/social.py`` pour ce que les autres peuvent lire.
"""

from mika.faculties.social import initiative, profile, sections  # noqa: F401 — contributions
from mika.faculties.social.faculty import SOCIAL, SocialParams, SocialState

__all__ = ["SOCIAL", "SocialParams", "SocialState"]
