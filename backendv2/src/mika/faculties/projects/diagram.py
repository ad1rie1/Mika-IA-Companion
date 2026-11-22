"""Le diagramme des objectifs d'un projet (ADR 0290, 0297), pur : de vraies dates seulement, lues dans sa tranche et
dans les départs de ses exécutions — rien n'est estimé. Deux lecteurs s'en servent : l'API par personne
(``app/me/project_activity.py``, ``GET …/diagramme``), qui y ajoute les mots et ce que chacun a le droit de lire, et la
fiche de la console (``app/handmade/subjects/project_goals.py``), qui le dessine côté serveur.

- ``episode_sort`` : ce qu'était un épisode de ce projet (un cadrage, du travail, une relecture) et l'objectif visé ;
- ``starts_of`` : les départs de ses exécutions de travail, par objectif, du plus ancien au plus récent ;
- ``spans`` : pour chaque jalon vivant, quand elle s'y est mise et combien d'exécutions il a prises ;
- ``rows`` : ses objectifs et ses missions dans l'ordre du plan, leurs jalons, leurs dates (0 : pas encore arrivé).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    Objective,
    Project,
    frame_of,
    milestones_of,
    objective_of,
    review_of,
)

#: ce qu'était un épisode d'un projet : sa séance de cadrage, du travail sur un objectif, une relecture indépendante
FRAME, RUN, REVIEW = "frame", "run", "review"
#: les passages d'une mission que le diagramme rend, au plus
PASSES_SHOWN = 60


def episode_sort(p: Project, subject: str | None) -> tuple[str, int] | None:
    """Ce qu'était un épisode de ce projet — une séance de cadrage, du travail, une relecture — et l'objectif qu'il
    visait ; ``None`` : une prise de parole sur lui (un récit, une demande), pas une exécution."""
    if frame_of(subject) == p.id:
        return FRAME, 0
    reviewed = review_of(subject)
    if reviewed is not None and reviewed[0] == p.id:
        return REVIEW, reviewed[1]
    aimed = objective_of(subject)
    return (RUN, aimed[1]) if aimed is not None and aimed[0] == p.id else None


def starts_of(p: Project, started: Iterable[Any]) -> dict[int, list[int]]:
    """Les départs de ses exécutions de travail, par objectif, du plus ancien au plus récent — ``started`` : ses
    épisodes commencés (``episode.started``), décodés, du plus récent au plus ancien, comme le journal les rend."""
    starts: dict[int, list[int]] = {}
    for e in reversed(list(started)):
        found = episode_sort(p, e.data.subject)
        if found is not None and found[0] == RUN and found[1]:
            starts.setdefault(found[1], []).append(e.at)
    return starts


def spans(o: Objective, starts: Sequence[int]) -> dict[int, tuple[int, int]]:
    """Pour chaque jalon vivant d'un objectif : quand elle s'y est mise, et combien d'exécutions il a prises —
    déduits de ses exécutions (``starts``, leurs départs, du plus ancien au plus récent). Elle se met à un jalon à la
    première exécution qui suit le jalon d'avant atteint ; atteint dans la même exécution que lui, il part de
    celle-là. Sans exécution depuis, il n'a pas commencé (0)."""
    out: dict[int, tuple[int, int]] = {}
    bound = 0
    for m in milestones_of(o):
        end = m.reached_at or 0
        later = [s for s in starts if s >= bound and (not end or s <= end)]
        start = later[0] if later else max((s for s in starts if end and s <= end), default=0)
        runs = sum(1 for s in starts if start and s >= start and (not end or s <= end))
        out[m.id] = (start, runs)
        if not end:
            break  # les suivants attendent celui-ci
        bound = end
    return out


@dataclass(frozen=True, slots=True)
class Mark:
    """Un jalon sur le diagramme : son texte (une référence), son statut, comment il se vérifie, s'il est dit prêt,
    et ses dates — posé, commencé (déduit), dit prêt, atteint ; combien d'exécutions il a prises."""

    id: int
    text_ref: str
    status: str
    check: str
    ready: bool
    added_at: int
    started_at: int
    ready_at: int
    reached_at: int
    runs: int


@dataclass(frozen=True, slots=True)
class Row:
    """Un objectif ou une mission sur le diagramme : son texte (une référence), sa sorte, son statut, l'objectif
    dont il dépend, son rang dans le plan, le ticket dont il est né, ses dates (posé, première exécution, dernière,
    clôture), ses exécutions, ses jalons vivants et combien sont atteints, les passages d'une mission."""

    id: int
    text_ref: str
    kind: str
    status: str
    after: int
    rank: int
    ticket: int
    added_at: int
    started_at: int
    last_run: int
    closed_at: int
    runs: int
    reached: int
    marks: tuple[Mark, ...]
    passes: tuple[int, ...]


def rows(p: Project, starts: Mapping[int, Sequence[int]]) -> tuple[Row, ...]:
    """Ses objectifs et ses missions qui ne sont pas retirés, dans l'ordre du plan, avec leurs jalons et leurs
    dates."""
    shown = sorted((o for o in p.objectives if o.status != c.DROPPED), key=lambda o: (o.rank or 10_000, o.id))
    out = []
    for o in shown:
        mine = list(starts.get(o.id, ()))
        found = spans(o, mine) if o.kind == c.ONCE else {}
        alive = milestones_of(o)
        out.append(Row(
            o.id, o.text_ref, o.kind, o.status, o.after, o.rank, o.ticket, o.at, mine[0] if mine else 0,
            o.last_run_at, o.closed_at, len(mine) or o.worked, sum(1 for m in alive if m.status == c.REACHED),
            tuple(Mark(m.id, m.text_ref, m.status, m.check, bool(m.ready_at and m.status == c.OPEN), m.at,
                       found.get(m.id, (0, 0))[0], m.ready_at, m.reached_at, found.get(m.id, (0, 0))[1])
                  for m in alive),
            tuple(mine[-PASSES_SHOWN:]) if o.kind == c.CONSTANT else ()))
    return tuple(out)
