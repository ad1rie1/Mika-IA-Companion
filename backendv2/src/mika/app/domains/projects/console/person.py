"""La part des projets dans la fiche d'une personne (ADR 0310) : l'onglet Projets — ceux qui la regardent, menés pour
elle, qui la concernent ou qui lisent un projet qui la concerne (``faculties/projects/inspect.py::of_person``), en
liste — et son compte dans la barre."""

from __future__ import annotations

from mika.app.domains.domain import PersonPart
from mika.app.handmade import Look
from mika.app.handmade.lists import Roles, drawn
from mika.app.handmade.person.common import Who, _slice
from mika.faculties.projects.inspect import of_person as projects_of


def count(look: Look, who: Who) -> int:
    """Le compte de l'onglet Projets (``PersonOverview.counts``) : les projets qui la regardent."""
    projects = _slice(look, "projects")
    handles = sorted({who.person, *who.handles})
    return len(projects_of(projects, handles)) if projects is not None else 0


#: sa part de la fiche d'une personne (ADR 0310)
PERSON_PART = PersonPart(
    tabs={"projets": drawn(Roles(title="projet", badges=("mode", "état"), time="ouvert"), "projets")},
    counts={"projets": count})
