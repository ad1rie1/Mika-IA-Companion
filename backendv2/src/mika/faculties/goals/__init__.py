"""``goals`` : ce qu'elle se propose de faire ensuite — rappels et explorations (les projets : ``projects``).
Voir ``contracts/goals.py``."""

from mika.faculties.goals import (  # noqa: F401 — contributions
    actions,
    inspect,
    prompt,
    tend,
    tools,
    work,
)
from mika.faculties.goals.faculty import GOALS, GoalsParams, GoalsState
from mika.faculties.goals.prompt import step_brief

__all__ = ["GOALS", "GoalsParams", "GoalsState", "step_brief"]
