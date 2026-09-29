"""``goals`` : ce qu'elle a entrepris — rappels, explorations, projets.
Voir ``contracts/goals.py``."""

from mika.faculties.goals import atelier, prompt, tend, tools, work  # noqa: F401 — contributions
from mika.faculties.goals.faculty import GOALS, GoalsParams, GoalsState
from mika.faculties.goals.prompt import step_brief

__all__ = ["GOALS", "GoalsParams", "GoalsState", "step_brief"]
