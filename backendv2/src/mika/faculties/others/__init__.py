"""``others`` : ce qu'elle devine des autres — leur ton habituel et du moment,
la surprise quand ils s'en écartent, leurs délais de réponse, les heures où
ils répondent. Voir ``contracts/others.py``."""

from mika.faculties.others import inspect  # noqa: F401 — contributions
from mika.faculties.others.faculty import OTHERS, OthersParams, OthersState

__all__ = ["OTHERS", "OthersParams", "OthersState"]
