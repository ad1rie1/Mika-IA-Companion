"""``others`` : ce qu'elle devine des autres — leur ton habituel et du moment,
la surprise quand ils s'en écartent, leurs délais de réponse, les heures où
ils répondent. Voir ``contracts/others.py``.

Ses modules à contributions, importés ici pour qu'elles s'inscrivent : ce qu'elle
en apprend (``faculty``), ses initiatives selon ce que l'expérience lui a appris
(``initiative``), ce qu'elle en met dans le prompt (``prompt``) et ce qu'elle en
montre à la console (``inspect``)."""

from mika.faculties.others import initiative, inspect, prompt  # noqa: F401 — contributions
from mika.faculties.others.faculty import OTHERS, OthersParams, OthersState

__all__ = ["OTHERS", "OthersParams", "OthersState"]
