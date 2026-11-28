"""Les décisions techniques d'un projet : ce qu'il a tranché, et pourquoi.

Une décision se prend pendant une exécution (l'outil ``project_decide``) ou depuis la console (l'action
``projects.decision_ajouter``) ; sa forme (``Decision``), ``decision_at`` et ``DECISIONS_KEPT`` sont dans
``faculty.py``. Ici, ses faits et leurs réducteurs (ADR 0313) :

- **sa naissance et son statut** (``projects.decided``, ``projects.decision_changed``) : une décision qui en remplace
  une autre en vigueur la dit remplacée ; ``DECISIONS_KEPT`` en vigueur au plus, et la plus ancienne qui ne l'est
  plus tombe quand la place manque ;
- **sa révision** (``projects.decision_revised``, ADR 0290) : ses textes changent — son titre, ce qui est choisi, son
  contexte, ses options, sa raison —, son numéro, son statut et ce qu'elle remplace restent. Une décision remplacée ne
  se révise pas : c'est celle qui la remplace qu'on change. L'action qui la pose, ``projects.decision_modifier``, est
  dans ``actions.py``.
"""

from __future__ import annotations

from dataclasses import replace

from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    DECISIONS_KEPT,
    INHERITED,
    PROJECTS,
    Decision,
    ProjectsState,
    decision_at,
    with_project,
)
from mika.kernel.events import Content, Payload

#: les textes facultatifs d'une décision, qu'une révision peut vider
OPTIONAL = ("context", "options", "reason")


# ── Sa naissance et son statut ────────────────────────────────────────────


class Decided(Payload):
    """Une décision technique (la sienne pendant une exécution, ou celle d'un opérateur)."""

    project: int
    decision: int
    title: Content
    choice: Content
    context: Content | None = None
    options: Content | None = None
    reason: Content | None = None
    #: la décision qu'elle remplace (0 : aucune)
    replaces: int = 0
    objective: int = 0
    author: str = "self"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class DecisionChanged(Payload):
    project: int
    decision: int
    status: str
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


DECIDED = PROJECTS.event("decided", Decided, content=("title", "choice", "context", "options", "reason"),
                         subjects=("owner", "about", "by", INHERITED))
DECISION_CHANGED = PROJECTS.event("decision_changed", DecisionChanged, subjects=("owner", "about"))


@PROJECTS.reducer(DECIDED)
def _decided(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not d.title.ref or not d.choice.ref:
        return s
    did = d.decision if d.decision > p.decision_seq and decision_at(p, d.decision) is None else \
        max([p.decision_seq, *(x.id for x in p.decisions)]) + 1  # le numéro déjà pris : le suivant
    replaced = decision_at(p, d.replaces) if d.replaces else None
    decision = Decision(
        id=did, title_ref=d.title.ref, choice_ref=d.choice.ref,
        context_ref=d.context.ref or "" if d.context is not None else "",
        options_ref=d.options.ref or "" if d.options is not None else "",
        reason_ref=d.reason.ref or "" if d.reason is not None else "", author=d.author, at=e.at,
        replaces=d.replaces if replaced is not None and replaced.status == c.IN_FORCE else 0, objective=d.objective)
    decisions = tuple(replace(x, status=c.SUPERSEDED, replaced_by=did) if x.id == decision.replaces else x
                      for x in p.decisions)
    if sum(1 for x in decisions if x.status == c.IN_FORCE) >= DECISIONS_KEPT:
        return s  # trop de décisions en vigueur : qu'on en retire avant d'en prendre d'autres
    decisions = (*decisions, decision)
    while len(decisions) > DECISIONS_KEPT:  # la place manque : la plus ancienne qui n'est plus en vigueur tombe
        oldest = next(x for x in decisions if x.status != c.IN_FORCE)
        decisions = tuple(x for x in decisions if x is not oldest)
    return with_project(s, replace(p, decisions=decisions, decision_seq=max(p.decision_seq, did)))


@PROJECTS.reducer(DECISION_CHANGED)
def _decision_changed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    x = decision_at(p, d.decision) if p is not None else None
    if p is None or x is None or d.status not in c.DECISION_STATUSES:
        return s
    new = replace(x, status=d.status, replaced_by=x.replaced_by if d.status == c.SUPERSEDED else 0)
    return with_project(s, replace(p, decisions=tuple(new if y.id == x.id else y for y in p.decisions)))


# ── Sa révision ───────────────────────────────────────────────────────────


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


__all__ = ["DECIDED", "DECISION_CHANGED", "DECISION_REVISED"]
