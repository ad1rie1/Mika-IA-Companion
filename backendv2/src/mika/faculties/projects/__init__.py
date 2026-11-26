"""``projects`` : ses projets, des boîtes noires qu'on pilote (ADR 0031).
Voir ``contracts/projects.py``."""

from mika.faculties.projects import (  # noqa: F401 — contributions
    access,
    actions,
    asks_tools,
    atelier,
    decisions,
    docs,
    docs_tools,
    framing_tools,
    inspect,
    inspect_access,
    inspect_docs,
    inspect_files,
    inspect_git,
    inspect_merge,
    inspect_milestones,
    inspect_tracker,
    issues,
    merge,
    milestones,
    prompt,
    pulls,
    reaching,
    review,
    steer,
    tend,
    tools,
    tracker,
    tracker_tools,
    triage,
    work,
)
from mika.faculties.projects.faculty import PROJECTS, ProjectsParams, ProjectsState
from mika.faculties.projects.prompt import job_brief, work_brief

__all__ = ["PROJECTS", "ProjectsParams", "ProjectsState", "job_brief", "work_brief"]
