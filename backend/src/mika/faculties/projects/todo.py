"""À qui la main : ce qui, dans ses projets, attend une personne (ADR 0281) — la règle, pure.

Un projet avance seul jusqu'à ce qu'il lui faille quelqu'un. Ce module rend, pour un projet (``of_project``) et pour
tous (``everywhere``), **ce qui attend une personne**, dans l'ordre où elle devrait s'en occuper (``ORDER``) :

1. les effets proposés qui attendent un accord — un envoi, une récupération, une commande réseau, une pull request,
   une issue ou une note à publier, un pilotage demandé, l'appel d'un service pendant son travail ;
2. le plan d'un projet qui attend sa réponse ;
3. une demande d'aide d'un objectif (« j'ai besoin de toi pour… »), un projet arrêté par ses pannes, un objectif
   bloqué ;
4. les tickets dont la main est au propriétaire (``tickets.hand``) : proposés à accepter, question posée,
   proposition de l'écarter, plan à valider, pull request prête à fusionner, objectif qui bloque ;
5. les points d'arrêt d'un jalon dits prêts ;
6. un objectif que ses relectures ont refusé autant de fois qu'il se peut ;
7. les éléments ouverts d'une liste de suivi à la charge d'une personne.

Dans un même rang, le plus ancien d'abord. Chaque entrée (``Waiting``) dit le projet, de quoi il s'agit (sa sorte,
sa précision, la référence du texte qui le dit : jamais le texte), depuis quand, qui elle attend, et le geste
attendu (``Gesture`` : l'action de console qui la règle, l'onglet de la fiche où elle se fait, ou la file
« À valider », ou l'hôte du dépôt).

Rien ici ne dessine ni n'écrit : on ne lit que l'état des projets et le fait des effets en attente
(``runtime.PENDING_EFFECTS``). Ses mots, dans la console, sont dans ``inspect_todo.py``.

**Qui une attente attend** (``awaits``) est qui peut la régler : la personne nommée (une demande d'aide adressée, un
élément à sa charge, le plan de qui l'a demandé) ; pour un accord, qui s'occupe d'elle — « ton accord », dans une
ligne d'accès, est le sien (ADR 0133), même dans un projet confié à quelqu'un d'autre ; sinon le propriétaire du
projet (ADR 0286). La console, l'API par personne et ses clients le lisent ici.

**Par personne** (``for_person``) : ce qu'une personne peut voir et trancher de ces attentes. Son projet (elle en est
le propriétaire ; pour un projet à elle, quelqu'un qui s'occupe d'elle) : tout, et c'est elle qu'on attend — sauf ce
qui est à la charge d'une autre, et un accord, qui n'attend que qui s'occupe d'elle. Le projet d'un autre : seulement
ce que ses lignes d'accès lui donnent hors de toute conversation (``links.given_to``, la lecture serrée de l'ADR
0257) — le détail, donc le voir et le piloter au moins en lecture seule ; ce qu'elle peut y faire est le pilotage que
ces lignes lui laissent ; une reprise reste au propriétaire, un accord à qui s'occupe d'elle (c'est alors elle qu'il
attend, si elle en lit le détail). Un élément d'une liste à sa charge l'attend dès qu'elle voit le projet.

**Une limite, voulue** : les éléments d'une liste viennent de ce que l'état garde sous la main (``Board.items`` : tous
les tickets ouverts, puis les derniers éléments touchés). Une longue liste ancienne se lit dans sa projection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import links, tickets
from mika.faculties.projects.faculty import (
    Item,
    Objective,
    Project,
    ProjectsState,
    awaiting,
    handed_over,
    live,
)
from mika.kernel.frame import Frame
from mika.vocab.episodes import project_of

# ── Les sortes d'attente, dans l'ordre où l'on s'en occupe ────────────────

APPROVAL, PLAN, NEED, STALLED, BLOCKED = "approval", "plan", "need", "stalled", "blocked"
TICKET, CHECKPOINT, REVIEW, ITEM = "ticket", "checkpoint", "review", "item"
ORDER = (APPROVAL, PLAN, NEED, STALLED, BLOCKED, TICKET, CHECKPOINT, REVIEW, ITEM)
_RANK = {kind: n for n, kind in enumerate(ORDER)}

#: ce qu'un ticket attend du propriétaire (``Waiting.what``) : l'accepter, répondre à sa question, confirmer qu'elle
#: l'écarte, valider son plan, fusionner sa pull request, débloquer son objectif
ACCEPT, QUESTION, DISMISSAL, VALIDATION, MERGE, STUCK = "accept", "question", "dismissal", "validation", "merge", "stuck"

#: où se fait le geste : sur la fiche du projet (une action de console), dans la file « À valider », chez l'hôte
FICHE, QUEUE, HOST = "fiche", "queue", "host"
#: ce qui reste au propriétaire quel que soit le pilotage qu'un autre a reçu : la reprise après pannes
OWNER_ONLY = frozenset({STALLED})
#: ce que seul quelqu'un qui s'occupe d'elle règle, dans tout projet — même confié à un autre : un accord (ADR 0133)
KEEPER_ONLY = frozenset({APPROVAL})


@dataclass(frozen=True, slots=True)
class Gesture:
    """Le geste attendu : l'action de console qui le règle (vide : il ne se fait pas sur la fiche), où il se fait
    (``FICHE``, ``QUEUE``, ``HOST``), l'onglet de la fiche qui le porte, ce qui y ouvre l'objet (``params`` : un
    ticket, un élément) et ce que l'action sait déjà (``args``)."""

    action: str = ""
    where: str = FICHE
    tab: str = ""
    params: tuple[tuple[str, str], ...] = ()
    args: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Waiting:
    """Une chose qui attend une personne. ``kind`` : sa sorte (``ORDER``) ; ``what`` : sa précision — la capacité
    d'un effet proposé, ce qu'un ticket attend (``ACCEPT``…), le nom de la liste d'un élément ; ``ref`` : la
    référence du texte qui dit de quoi il s'agit (le résumé d'un effet, un besoin, le titre d'un ticket, le texte
    d'un jalon) — un contenu, que l'oubli atteint ; ``since`` : depuis quand ; ``person`` : qui elle attend (vide :
    le propriétaire du projet). Ses repères : l'objectif, un numéro (la proposition, le ticket, le jalon), une clé
    (l'élément d'une liste)."""

    project: int
    kind: str
    since: int
    gesture: Gesture
    what: str = ""
    ref: str = ""
    objective: int = 0
    number: int = 0
    key: str = ""
    person: str = ""


def _sorted(found: Iterable[Waiting]) -> tuple[Waiting, ...]:
    return tuple(sorted(found, key=lambda w: (_RANK[w.kind], w.since, w.project, w.objective, w.number, w.key)))


# ── Ce qu'un projet attend ────────────────────────────────────────────────


def _approvals(p: Project, pending: Iterable[Any]) -> list[Waiting]:
    """Ses effets proposés : chacun se décide dans la file « À valider », ouverte sur lui."""
    return [Waiting(p.id, APPROVAL, v.at, Gesture(where=QUEUE, params=(("demande", str(v.proposal)),)),
                    what=v.capability, ref=v.summary_ref, number=v.proposal)
            for v in pending if project_of(v.context) == p.id]


def _ticket(p: Project, item: Item) -> Waiting | None:
    """Ce qu'un ticket attend du propriétaire, d'après son étape (``tickets.hand``) ; rien : la main est à elle."""
    if item.closed or tickets.hand(item) != c.ACTOR_OWNER:
        return None
    name = f"#{item.number}"
    opened = (("element", name),)

    def settle(verdict: str) -> Gesture:
        return Gesture("projects.ticket_trancher", tab="tickets", params=opened,
                       args=(("item", name), ("verdict", verdict), ("plan", str(item.plan_seq))))

    if item.status == c.STAGE_PROPOSED:
        what, since, gesture = ACCEPT, item.at, settle("accept")
    elif item.status == c.STAGE_DECISION and item.dismissal_at:
        what, since, gesture = DISMISSAL, item.dismissal_at, settle("dismiss")
    elif item.status == c.STAGE_DECISION:
        what, since = QUESTION, item.asked_at
        gesture = Gesture("projects.element_noter", tab="tickets", params=opened,
                          args=(("list_name", c.TICKETS), ("item", name)))
    elif item.status == c.STAGE_VALIDATION:
        what, since, gesture = VALIDATION, item.updated_at, settle("validate")
    elif item.status == c.STAGE_PR_READY:
        what, since, gesture = MERGE, item.updated_at, Gesture(where=HOST, tab="tickets", params=opened)
    else:  # validé, et son objectif bloque : c'est lui qu'on rouvre
        what, since = STUCK, item.updated_at
        gesture = Gesture("projects.objectif_statut", tab="objectifs",
                          args=(("objective", str(item.objective)), ("status", c.OPEN)))
    return Waiting(p.id, TICKET, since or item.updated_at or item.at, gesture, what=what, ref=item.title_ref,
                   objective=item.objective, number=item.number)


def _objectives(p: Project, stuck: frozenset[int]) -> list[Waiting]:
    """Ce que ses objectifs attendent : une demande d'aide, un objectif bloqué (sauf celui d'un ticket qui le dit
    déjà), un point d'arrêt dit prêt, des relectures refusées autant qu'il se peut."""
    out: list[Waiting] = []
    for o in p.objectives:
        if o.status == c.OPEN and o.need_ref:
            out.append(Waiting(p.id, NEED, o.asked_at or o.last_run_at or o.at,
                               Gesture("projects.consigne", tab="objectifs"), ref=o.need_ref, objective=o.id,
                               person=o.asked_to))
        elif o.status == c.BLOCKED and o.id not in stuck:
            out.append(Waiting(p.id, BLOCKED, o.last_run_at or o.at,
                               Gesture("projects.objectif_statut", tab="objectifs",
                                       args=(("objective", str(o.id)), ("status", c.OPEN))),
                               ref=o.note_ref or o.text_ref, objective=o.id, person=o.asked_to))
        if o.status == c.OPEN and (m := awaiting(o)) is not None:
            out.append(Waiting(p.id, CHECKPOINT, m.ready_at,
                               Gesture("projects.jalon_trancher", tab="objectifs",
                                       args=(("objective", str(o.id)), ("milestone", str(m.id)))),
                               ref=m.text_ref, objective=o.id, number=m.id))
        if o.status in (c.OPEN, c.BLOCKED) and handed_over(o):
            out.append(Waiting(p.id, REVIEW, o.review_at or o.last_run_at or o.at,
                               Gesture("projects.consigne", tab="objectifs"),
                               ref=o.review_refused[-1] if o.review_refused else o.review_ref, objective=o.id))
    return out


def _items(p: Project) -> list[Waiting]:
    """Les éléments ouverts de ses listes de suivi à la charge d'une personne (le propriétaire, ou quelqu'un de
    nommé), parmi ceux que l'état garde."""
    closed = {lst.name: frozenset(lst.closed) for lst in p.board.lists}
    out: list[Waiting] = []
    for item in p.board.items:
        if item.list_name == c.TICKETS or item.list_name not in closed or item.status in closed[item.list_name]:
            continue
        if item.actor not in (c.ACTOR_OWNER, c.ACTOR_PERSON):
            continue
        out.append(Waiting(p.id, ITEM, item.updated_at or item.at,
                           Gesture("projects.element_statut", tab="suivi",
                                   params=(("liste", item.list_name), ("element", item.key)),
                                   args=(("list_name", item.list_name), ("item", item.key))),
                           what=item.list_name, ref=item.title_ref, key=item.key,
                           person=item.person if item.actor == c.ACTOR_PERSON else ""))
    return out


def of_project(p: Project, pending: Iterable[Any] = ()) -> tuple[Waiting, ...]:
    """Ce qui, dans ce projet, attend une personne, dans l'ordre où s'en occuper. ``pending`` : les effets proposés
    qui attendent un accord (``runtime.PENDING_EFFECTS``) — ceux d'un autre projet sont écartés ici. Un projet archivé
    n'attend personne."""
    if not live(p):
        return ()
    found: list[Waiting] = _approvals(p, pending)
    if p.status == c.ACTIVE and p.plan_state == c.PROPOSED:
        found.append(Waiting(p.id, PLAN, p.plan_at or p.created_at, Gesture("projects.plan_valider", tab="apercu"),
                             ref=p.plan_ref, person=p.asked_by or ""))
    if p.status == c.PAUSED and p.stalled_at:
        found.append(Waiting(p.id, STALLED, p.stalled_at, Gesture("projects.reprendre", tab="executions")))
    asked = [w for item in p.board.items if item.list_name == c.TICKETS and (w := _ticket(p, item)) is not None]
    found += asked
    found += _objectives(p, frozenset(w.objective for w in asked if w.what == STUCK))
    found += _items(p)
    return _sorted(found)


def everywhere(s: ProjectsState, pending: Iterable[Any] = ()) -> tuple[Waiting, ...]:
    """Ce qui attend une personne dans tous ses projets vivants, dans l'ordre où s'en occuper."""
    held = tuple(pending)
    return _sorted(w for p in s.projects.values() for w in of_project(p, held))


def pending_in(frame: Frame) -> tuple[Any, ...]:
    """Les effets proposés qui attendent un accord, tels que la vie les donne (un fait du runtime)."""
    return tuple(frame.get(rt.PENDING_EFFECTS) or ())


def counts(found: Iterable[Waiting]) -> Mapping[int, int]:
    """Combien de choses attendent, par projet."""
    out: dict[int, int] = {}
    for w in found:
        out[w.project] = out.get(w.project, 0) + 1
    return out


# ── Par personne : ce qu'elle peut voir et trancher ───────────────────────


@dataclass(frozen=True, slots=True)
class Seen:
    """Une attente telle qu'une personne la voit : ``mine`` — c'est elle qu'on attend ; ``steer`` — ce qu'elle peut y
    faire (``STEERS`` : la trancher, la demander sur l'accord du propriétaire, seulement la lire)."""

    entry: Waiting
    mine: bool
    steer: str


def owns(p: Project, person: str, world: links.World) -> bool:
    """Ce projet est-il à cette personne ? Elle en est le propriétaire ; pour un projet à elle, quelqu'un qui
    s'occupe d'elle."""
    owner = links.owner_of(p)
    return bool(person) and (person == owner if owner else world.keeper(person))


def reach(p: Project, person: str, world: links.World) -> links.Grant:
    """Ce que cette personne a de ce projet hors de toute conversation : tout s'il est à elle, sinon ce que ses
    lignes d'accès lui donnent (``links.given_to``)."""
    if owns(p, person, world):
        return links.Grant(True, c.STEER_EDIT, True, True) if live(p) else links.NOTHING
    return links.given_to(p, person, world)


def awaits(p: Project, w: Waiting) -> str:
    """Qui cette attente attend — qui peut la régler. Vide : quelqu'un qui s'occupe d'elle. La personne nommée ;
    pour un accord, toujours qui s'occupe d'elle, même dans un projet confié à un autre (« ton accord », ADR 0133) ;
    sinon le propriétaire du projet (pour un projet à elle : qui s'occupe d'elle)."""
    if w.kind in KEEPER_ONLY:
        return ""
    return w.person or links.owner_of(p)


def for_person(s: ProjectsState, world: links.World, person: str,
               found: Iterable[Waiting]) -> tuple[Seen, ...]:
    """Ce que ``person`` peut voir de ces attentes, dans leur ordre, et ce qu'elle peut y faire. Son « À faire » :
    celles où ``mine`` est vrai — celles qu'elle peut régler (``awaits``)."""
    reaches: dict[int, tuple[bool, links.Grant]] = {}
    keeper = bool(person) and world.keeper(person)
    out: list[Seen] = []
    for w in found:
        p = s.projects.get(w.project)
        if p is None or not person:
            continue
        if w.project not in reaches:
            reaches[w.project] = (owns(p, person, world), reach(p, person, world))
        own, grant = reaches[w.project]
        awaited = awaits(p, w)
        hers = awaited == person if awaited else keeper
        if own:
            out.append(Seen(w, hers, _capped(w, c.STEER_EDIT, own=True, keeper=keeper)))
        elif hers and (grant.detail if w.kind in KEEPER_ONLY else grant.see):
            # à sa charge : elle la voit dès qu'elle voit le projet ; un accord, dès qu'elle en lit le détail
            steer = grant.steer if grant.steer != c.STEER_NO else c.STEER_READ
            out.append(Seen(w, True, _capped(w, steer, own=False, keeper=keeper)))
        elif grant.detail:
            out.append(Seen(w, False, _capped(w, grant.steer, own=False, keeper=keeper)))
    return tuple(out)


def _capped(w: Waiting, steer: str, *, own: bool, keeper: bool) -> str:
    """Un accord se donne par qui s'occupe d'elle, et par personne d'autre ; une reprise reste au propriétaire : un
    autre ne fait que les lire."""
    if w.kind in KEEPER_ONLY:
        return c.STEER_EDIT if keeper else c.STEER_READ
    return c.STEER_READ if w.kind in OWNER_ONLY and not own else steer


def objective_of(p: Project, w: Waiting) -> Objective | None:
    """L'objectif qu'une attente concerne, s'il y en a un."""
    return next((o for o in p.objectives if o.id == w.objective), None) if w.objective else None
