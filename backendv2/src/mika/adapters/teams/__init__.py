"""Teams (ADR 0069) : ce que l'extension de navigateur pousse, ses brouillons et la file de ce qui repart (voir
``store``). Rien ici ne parle à Microsoft."""

from mika.adapters.teams.config import SIGNATURE, TeamsConfig
from mika.adapters.teams.store import TeamsStore

__all__ = ["SIGNATURE", "TeamsConfig", "TeamsStore"]
