"""Les décisions techniques d'un projet : ce qu'il a tranché, et pourquoi.

Une décision se prend pendant une exécution (l'outil ``project_decide``) ou depuis la console (l'action
``projects.decision_ajouter``) ; sa forme (``Decision``) est dans ``faculty.py``. Ici, **sa révision**
(``projects.decision_revised``, ADR 0290) : ses textes changent — son titre, ce qui est choisi, son contexte, ses
options, sa raison —, son numéro, son statut et ce qu'elle remplace restent. Une décision remplacée ne se révise pas :
c'est celle qui la remplace qu'on change. L'action qui la pose, ``projects.decision_modifier``, est dans
``actions.py``.

Les faits de sa naissance et de son statut (``projects.decided``, ``projects.decision_changed``) et leurs réducteurs
sont encore dans ``faculty.py`` (ADR 0313).
"""

from __future__ import annotations

from dataclasses import replace

from mika.contracts import projects as c
from mika.faculties.projects.faculty import INHERITED, PROJECTS, ProjectsState, decision_at
from mika.kernel.events import Content, Payload

#: les textes facultatifs d'une décision, qu'une révision peut vider
OPTIONAL = ("context", "options", "reason")


class DecisionRevised(Payload):
    """Les textes d'une décision technique changent (``None`` : inchangé ; ``cleared`` : ceux qu'on vide, parmi
    ``OPTIONAL``). Son numéro, son statut et ce qu'elle remplace restent."""

    project: int
    decision: int
    title: Content | None = None
    choice: Content | None = None
    context: Content | None = None
    options: Content | None = None
    reason: Content | None = None
    cleared: tuple[str, ...] = ()
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


DECISION_REVISED = PROJECTS.event("decision_revised", DecisionRevised,
                                  content=("title", "choice", "context", "options", "reason"),
                                  subjects=("owner", "about", "by", INHERITED))


@PROJECTS.reducer(DECISION_REVISED)
def _decision_revised(s: ProjectsState, e, cx) -> ProjectsState:
    """Une décision remplacée ne se révise pas : c'est celle qui la remplace qu'on change."""
    d = e.data
    p = s.projects.get(d.project)
    x = decision_at(p, d.decision) if p is not None else None
    if p is None or x is None or x.status == c.SUPERSEDED:
        return s

    def ref(name: str, old: str) -> str:
        new = getattr(d, name)
        if new is not None and new.ref:
            return new.ref
        return "" if name in d.cleared and name in OPTIONAL else old

    new = replace(x, title_ref=ref("title", x.title_ref), choice_ref=ref("choice", x.choice_ref),
                  context_ref=ref("context", x.context_ref), options_ref=ref("options", x.options_ref),
                  reason_ref=ref("reason", x.reason_ref))
    if new == x:
        return s
    return replace(s, projects=s.projects.set(p.id, replace(
        p, decisions=tuple(new if y.id == x.id else y for y in p.decisions))))


__all__ = ["DECISION_REVISED"]
