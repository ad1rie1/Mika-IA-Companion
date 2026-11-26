"""Ce que partagent les outils des projets, en conversation et pendant une exécution (``tools.py``, ``steer.py``,
``tracker_tools.py``, ``reaching.py``, ``triage.py``, l'atelier…).

Les sortes d'épisode d'une exécution (``RUNS``), le projet qu'elle fait et l'objectif qu'elle vise
(``running_project``), la réponse quand il n'est plus actif (``gone_reply``) ; qui lui parle (``speaker``), qui
s'occupe d'elle (``caretaker``), les textes gardés (``contents_of``) ; et ce qu'un geste de vive voix fait : le
numéro dont il s'agit (``which_one``), ceux parmi lesquels elle n'a pas su choisir (``choices_listed``), l'écrire
sous sa garde (``emit_gesture``) et la réponse quand le projet a changé sous elle (``changed_reply``).

La garde « projet inchangé » est dans ``inspect_common.py`` ; ce que partagent les capacités (après l'accord, par
les ports), dans ``capability_common.py``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import Objective, Project, ProjectsState, objective_at, objective_of
from mika.kernel.events import Draft
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.vocab.episodes import PROJECT_KINDS, Kind, project_of
from mika.vocab.phrasebook import phrase
from mika.vocab.words import stems

RUNS = list(PROJECT_KINDS)


def running_project(ctx: Any) -> tuple[Project, Objective | None] | None:
    """Le projet de l'exécution en cours et l'objectif qu'elle vise (``None`` : plus actif)."""
    ep = ctx.frame.episode
    pid = project_of(ep.target) if ep is not None else None
    s: ProjectsState = ctx.frame.state("projects")
    p = s.projects.get(pid) if pid is not None else None
    if p is None or p.status != c.ACTIVE:
        return None
    got = objective_of(ep.attrs.get("subject")) if ep is not None else None
    o = objective_at(p, got[1]) if got is not None and got[0] == p.id else None
    return p, o


def gone_reply() -> str:
    """La réponse de chaque outil d'exécution quand le projet n'est plus actif."""
    return phrase("projects.tools.gone")


def speaker(frame: Frame) -> tuple[str, str] | None:
    """Qui lui parle, en réponse : son adresse et sa personne (``None`` hors d'une réponse)."""
    ep = frame.episode
    if ep is None or not ep.target or ep.kind != Kind.REPLY:
        return None
    return ep.target, frame.get(identity_c.PERSON(ep.target))


def caretaker(frame: Frame) -> str:
    """Qui s'occupe d'elle, par son prénom (jamais « ta propriétaire »)."""
    return identity_c.keepers(frame, quoted=True)


def contents_of(ctx: Any, refs: list[str]) -> Mapping[str, str]:
    """Les textes gardés de ces références, lus d'un coup (les références vides écartées)."""
    store = ctx.ports.get("store")
    wanted = [r for r in refs if r]
    return store.content(wanted) if store is not None and wanted else {}


def which_one(said: str, rows: list[tuple[int, str]]) -> int | None:
    """Le numéro dont il s'agit : dit tel quel (« 3 », « n° 3 »), sinon le seul qu'il y a, sinon celui qui a le
    plus de mots en commun avec ce qu'elle en dit — s'il est seul dans ce cas (sinon rien : elle demande lequel)."""
    raw = said.strip().lower().removeprefix("n°").removeprefix("#").strip()
    if raw.isdigit():
        return int(raw) if any(i == int(raw) for i, _ in rows) else None
    if len(rows) == 1:
        return rows[0][0]
    said_stems = stems(said)
    scored = [(len(said_stems & stems(text)), i) for i, text in rows]
    best = max((n for n, _ in scored), default=0)
    top = [i for n, i in scored if n == best]
    return top[0] if best and len(top) == 1 else None


#: les projets, les objectifs qu'elle énumère quand elle ne sait pas duquel il s'agit
LISTED = 12


def choices_listed(rows: list[tuple[int, str]], empty: str) -> str:
    """Les projets (ou les objectifs) parmi lesquels elle n'a pas su choisir, un par ligne."""
    return "\n".join(phrase("projects.tools.steer.item", id=i, text=text or empty) for i, text in rows[:LISTED])


async def emit_gesture(ctx: Any, draft: Draft[Any], guard: Guard, *more: Draft[Any]) -> Any:
    """Écrire un geste sous sa garde (et ce qui s'écrit avec lui, ``more``) ; ``None`` quand c'est elle qui a cédé (le
    projet a changé entre-temps)."""
    try:
        return await ctx.emit(draft, *more, guard=guard)
    except Superseded:
        if guard.predicate is not None and guard.predicate(ctx.mind.frame().view):
            raise  # c'est la garde de la conversation qui a cédé
        return None


def changed_reply() -> ToolResult:
    """La réponse d'un geste quand le projet a changé sous elle (une garde a cédé) : rien n'a changé."""
    return ToolResult(ok=False, content=phrase("projects.tools.steer.changed"))
