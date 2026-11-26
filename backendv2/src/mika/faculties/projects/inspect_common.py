"""Ce que partagent les vues et les actions de console des projets (``inspect*.py``, ``actions.py``).

Les gardes et les cibles d'un geste : la garde « projet inchangé » (``unchanged`` — les gestes de conversation,
``steer.py``, ``tracker.py`` et ``reaching.py``, la posent aussi), les états où un projet se pilote (``LIVE``), le
projet et l'objectif qu'un geste vise (``target_project``, ``target_objective``), la personne qui agit
(``operator_person``). Les petits outils des vues : le projet dont une vue est la fiche (``subject_project``), les
textes gardés (``stored_texts``, ``stored_text``, ``FORGOTTEN``), un texte coupé (``cut_noted``), un dépôt distant
(``host_of``, ``remote_ref``), où en est un effet (``effect_state``).

Ce qui dit si une action peut être offerte (``can_edit``, ``can_run``…) reste à côté de son geste, dans
``actions.py``."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import (
    Objective,
    Project,
    ProjectsState,
    by_pulls,
    objective_at,
    project_at,
)
from mika.kernel.events import Event
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.inspect import Badge, InspectContext, Note, Ref
from mika.kernel.operate import ActionContext, Refused


def unchanged(project: int, wanted: tuple[str, ...]) -> Guard:
    """Un geste ne vaut que si le projet est toujours dans cet état (un opérateur a pu le mettre en pause ou
    l'archiver entre-temps)."""
    return Guard("projet inchangé", predicate=lambda view, k=project: view.get(c.STATUS(k)) in wanted)


LIVE = (c.ACTIVE, c.PAUSED)


def target_project(s: ProjectsState, ctx: ActionContext) -> Project:
    p = project_at(s, ctx.subject)
    if p is None:
        raise Refused(f"Aucun projet « {ctx.subject} ».")
    return p


def target_objective(p: Project, raw: str) -> Objective:
    o = objective_at(p, raw)
    if o is None:
        raise Refused(f"Aucun objectif n° {raw[:12]} dans ce projet.")
    return o


def operator_person(frame: Frame, ctx: ActionContext) -> str:
    """La personne de l'opérateur qui agit (vide : inconnue)."""
    return (frame.get(identity_c.PERSON(ctx.by)) or "") if ctx.by else ""


def subject_project(s: ProjectsState, ctx: InspectContext) -> Project | Note:
    if not ctx.subject:
        return Note("Cette vue se lit sur la fiche d'un projet (Projets → un projet).", tone="muted")
    p = project_at(s, ctx.subject)
    if p is None:
        return Note(f"Aucun projet « {ctx.subject} ».", tone="warn")
    return p


FORGOTTEN = "(oublié)"


def stored_texts(ctx: InspectContext, refs: Iterable[str]) -> Mapping[str, str]:
    wanted = sorted({r for r in refs if r})
    if not wanted or ctx.store is None:
        return {}
    return ctx.store.content(wanted)


def stored_text(texts: Mapping[str, str], ref: str, empty: str = "—") -> str:
    if not ref:
        return empty
    got = texts.get(ref)
    return got if got is not None else FORGOTTEN


def cut_noted(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"\n[… coupé à {n} caractères …]"


def host_of(url: str) -> str:
    return urlsplit(url).hostname or url if url else ""


def remote_ref(p: Project) -> Ref | str:
    if not p.remote:
        return "aucun"
    shown = re.sub(r"\.git$", "", p.remote.split("://", 1)[-1])
    # son flux, quand il passe par des pull requests (ADR 0274) : la branche nommée ne reçoit que ce qui est accepté
    return Ref.url(re.sub(r"\.git$", "", p.remote), f"{shown} ({p.branch}{', par pull request' if by_pulls(p) else ''})")


def effect_state(proposal: Event[Any], pending: bool, outcomes: Sequence[Event[Any]]) -> tuple[Badge, str]:
    if pending:
        return Badge("attend ton accord", "warn"), ""
    executed = next((o for o in outcomes if o.type.name == rt.EFFECT_EXECUTED.name), None)
    resolved = next((o for o in outcomes if o.type.name == rt.EFFECT_RESOLVED.name), None)
    if executed is not None:
        return (Badge("fait", "ok") if executed.data.ok else Badge("échoué", "danger")), executed.data.result
    if resolved is not None and not resolved.data.approved:
        note = f" : « {said} »" if (said := resolved.data.said()) else ""
        return Badge("refusé", "muted"), f"par {resolved.data.by or 'un opérateur'}{note}"
    if resolved is not None or not proposal.data.approval:
        return Badge("en cours", "info"), ""
    return Badge("inconnu", "muted"), ""
