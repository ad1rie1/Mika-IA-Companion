"""``projects`` : ses projets, des boîtes noires qu'on pilote (ADR 0031).
Voir ``contracts/projects.py``."""

from mika.faculties.projects import (  # noqa: F401 — contributions
    access,
    actions,
    atelier,
    console_access,
    inspect,
    prompt,
    tend,
    tools,
    work,
)
from mika.faculties.projects.faculty import PROJECTS, ProjectsParams, ProjectsState
from mika.faculties.projects.prompt import job_brief, work_brief

__all__ = ["PROJECTS", "ProjectsParams", "ProjectsState", "job_brief", "work_brief"]
