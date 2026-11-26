"""Les demandes d'un projet à un autre (ADR 0271) : les règles pures.

Un projet n'écrit jamais dans un autre. Quand il voit, dans un projet qu'il lit, quelque chose à faire, il lui ouvre
un ticket : sa demande. Le projet visé le traite comme ses autres tickets (ADR 0270). Ce module dit, à partir de
l'état des projets et de ce qu'un lien donne maintenant (``links.py``) :

- **si la demande peut partir** (``refusal``) : le projet visé est lu, le lien n'est pas suspendu, ses lignes d'accès
  donnent au propriétaire du demandeur le pilotage sur accord ou en modification (``Grant.ask``) ; trois demandes par
  exécution, cinq demandes ouvertes au plus par lien ;
- **comment elle naît** (``mode``) : proposée — le propriétaire du projet visé l'accepte ou l'écarte —, ou directe.
  Le mode direct est réglé lien par lien par le propriétaire du demandeur (``Project.direct``), et ne vaut que si la
  matrice du projet visé donne la modification **et** si ce qu'écrit le projet visé est au moins du niveau de ce
  qu'écrit le demandeur (``indirect``) : une demande fait passer de l'information du demandeur, qui lit peut-être
  plus confidentiel, vers le projet visé ;
- **ce que le demandeur en suit** (``Project.asks``) : le réducteur du registre y pose la demande quand le ticket naît
  (``born``) et y recopie son étape à chaque fait (``followed``) ; ``state`` la dit en cinq mots ;
- **qui sa fermeture réveille** (``followed``, ``roused``) : traitée ou écartée, elle devient une nouvelle à juger
  (``ask:<n>``, ADR 0265) ; le processus ``projects.stirs`` éveille l'objectif qui l'a ouverte si le lien donne
  encore le détail du projet visé (``reads``).

L'outil et ce que son exécution en lit sont dans ``demands.py`` ; rien ici n'agit.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from mika.contracts import projects as c
from mika.faculties.projects import links, triggers
from mika.faculties.projects.faculty import (
    ASKS_KEPT,
    ASKS_OPEN_MAX,
    ASKS_PER_RUN,
    Ask,
    Heard,
    Item,
    Project,
    ProjectsState,
    asked_by,
    live,
    objective_at,
    with_heard,
    with_project,
    written,
)
from mika.vocab.access import STEER_EDIT, STEER_NO

#: comment naît une demande : proposée (elle attend l'accord du propriétaire du projet visé), ou directe (non lue)
PROPOSED, DIRECT = "proposed", "direct"
#: pourquoi le mode direct ne vaut pas sur un lien (la console le dit en mots) : la matrice du projet visé ne donne
#: pas la modification ; ce qu'il écrit est d'un niveau plus bas que ce qu'écrit le demandeur
MATRIX, LEVEL = "matrix", "level"
#: pourquoi une demande ne part pas (les clés de ``projects.tools.ask.refused`` dans sa voix : NE PAS RENOMMER) : ce
#: projet n'est pas lu ; le lien est suspendu ; son propriétaire ne donne pas de lui demander ; trop pour cette
#: exécution ; trop de demandes ouvertes sur ce lien ; le projet visé a trop de tickets ouverts
UNREAD, SUSPENDED, NO_RIGHT, PER_RUN, PER_LINK, FULL = "unread", "suspended", "no_right", "per_run", "per_link", "full"
#: où en est une demande, telle que le demandeur la lit (les clés de ``projects.asks.states`` : NE PAS RENOMMER)
PENDING, ACCEPTED, WORKING, DONE, DROPPED = "pending", "accepted", "working", "done", "dropped"


def state(stage: str) -> str:
    """Où en est une demande, de l'étape de son ticket : en attente d'accord, acceptée (pas encore lue), en cours,
    traitée, écartée."""
    return {c.STAGE_PROPOSED: PENDING, c.STAGE_UNREAD: ACCEPTED, c.STAGE_TREATED: DONE,
            c.STAGE_DISMISSED: DROPPED}.get(stage, WORKING)


def opened(ask: Ask) -> bool:
    """La demande est-elle encore ouverte chez le projet visé ?"""
    return ask.status not in c.STAGES_CLOSED


def open_to(p: Project, target: int) -> int:
    """Ses demandes encore ouvertes chez ce projet."""
    return sum(1 for a in p.asks if a.target == target and opened(a))


def during(p: Project, run: str) -> int:
    """Les demandes que cette exécution a ouvertes (``run`` : son épisode)."""
    return sum(1 for a in p.asks if run and a.run == run)


def indirect(asker: Project, target: Project, grant: links.Grant) -> str:
    """Pourquoi une demande de ``asker`` n'entrerait pas directement chez ``target``, même si son lien le règle
    (vide : rien ne s'y oppose) : la matrice de ``target`` ne donne pas la modification au propriétaire de
    ``asker`` ; ou ce qu'écrit ``target`` est d'un niveau plus bas que ce qu'écrit ``asker``."""
    if grant.ask != STEER_EDIT:
        return MATRIX
    return LEVEL if written(target) < written(asker) else ""


def mode(asker: Project, target: Project, grant: links.Grant) -> str:
    """Comment naîtrait, maintenant, une demande de ``asker`` à ``target`` : directe (``DIRECT`` : le lien le règle,
    et la matrice comme le niveau le permettent encore), proposée (``PROPOSED``), ou pas du tout (``""`` : le lien ne
    donne pas de demander)."""
    if grant.ask == STEER_NO:
        return ""
    return DIRECT if target.id in asker.direct and not indirect(asker, target, grant) else PROPOSED


def refusal(asker: Project, reading: links.Reading | None, run: str) -> str:
    """Pourquoi ``asker`` ne peut pas adresser de demande par ce lien, maintenant (vide : il le peut). ``reading`` :
    le lien tel qu'il vaut (``links.readings``), ``None`` s'il ne lit pas ce projet ; ``run`` : l'exécution qui
    demande."""
    if reading is None:
        return UNREAD
    if reading.suspended or reading.project is None:
        return SUSPENDED
    if reading.grant.ask == STEER_NO:
        return NO_RIGHT
    if during(asker, run) >= ASKS_PER_RUN:
        return PER_RUN
    return PER_LINK if open_to(asker, reading.id) >= ASKS_OPEN_MAX else ""


def reads(s: ProjectsState, asker: Project, target: int, world: links.World) -> bool:
    """Le lien donne-t-il encore à ``asker`` le détail du projet ``target`` ? C'est ce qui décide de ce qu'il lit de
    ses demandes, et de ce qui le réveille : le droit de lire repris, il ne sait plus que le fait qu'elles
    existent."""
    t = s.projects.get(target)
    return t is not None and target in asker.reads and links.grant(asker, t, world).detail


def received(p: Project, target: int | None = None) -> list[Item]:
    """Les demandes que ``p`` a reçues d'autres projets : ses tickets qu'un projet a ouverts (``asking_project``),
    parmi ceux que son état garde, dans l'ordre de son registre — ceux du projet ``target`` seulement, s'il est
    dit."""
    return [x for x in p.board.items if x.list_name == c.TICKETS and (asker := c.asking_project(x.author))
            and (target is None or asker == target)]


# ── Ce que le demandeur suit (appelé par les réducteurs du registre) ──────


def _kept(asks: tuple[Ask, ...]) -> tuple[Ask, ...]:
    """``ASKS_KEPT`` au plus : les demandes fermées les plus anciennes tombent d'abord, puis les plus anciennes."""
    over = len(asks) - ASKS_KEPT
    if over <= 0:
        return asks
    closed = [i for i, a in enumerate(asks) if not opened(a)][:over]
    oldest = [i for i in range(len(asks)) if i not in closed][:over - len(closed)]
    return tuple(a for i, a in enumerate(asks) if i not in (*closed, *oldest))


def born(s: ProjectsState, e: Any, target: Project, item: Item, origin: int) -> ProjectsState:
    """Un ticket qu'un autre projet vient d'ouvrir chez ``target`` est une demande que ce projet suit : elle entre
    dans ses ``asks``, avec l'objectif d'où elle part et l'exécution qui l'a ouverte. Un projet inconnu, ou le
    projet lui-même : rien."""
    asker = s.projects.get(c.asking_project(item.author))
    if asker is None or asker.id == target.id or item.list_name != c.TICKETS:
        return s
    if any(a.target == target.id and a.key == item.key for a in asker.asks):
        return s
    ask = Ask(target.id, item.key, item.number, max(0, origin), e.at, item.status, run=e.correlation or "")
    return with_project(s, replace(asker, asks=_kept((*asker.asks, ask))))


def followed(s: ProjectsState, e: Any, target: Project, item: Item, noted: bool) -> ProjectsState:
    """Un ticket de ``target`` vient de bouger : si un projet le suit comme sa demande, l'étape y est recopiée.
    Fermée (traitée, écartée), elle garde l'événement qui porte la note de sa fermeture (``noted`` : il en porte
    une), et devient une nouvelle à juger quand l'objectif qui l'a ouverte est encore ouvert — le processus
    ``projects.stirs`` dira s'il se réveille (``roused``). Rouverte, elle se suit de nouveau."""
    found = asked_by(s, target.id, item.key) if item.list_name == c.TICKETS else None
    if found is None:
        return s
    asker, ask = found
    if ask.status == item.status:
        return s
    closing = item.status in c.STAGES_CLOSED
    new = replace(ask, status=item.status, closed_at=e.at if closing else 0,
                  note_seq=e.seq if closing and noted else 0)
    s = with_project(s, replace(asker, asks=tuple(new if a is ask else a for a in asker.asks)))
    o = objective_at(asker, ask.objective)
    if not closing or o is None or o.status != c.OPEN or not live(asker):
        return s
    return with_heard(s, e, triggers.ask_key(target.id), f"#{ask.number}", target.id)


def roused(s: ProjectsState, news: Heard, world: links.World) -> tuple[tuple[int, int], ...]:
    """Les objectifs que réveille la fermeture d'une demande : (projet, objectif) — celui qui l'a ouverte, quand le
    lien donne **encore** le détail du projet visé (``reads``). Un lien suspendu, ou qui ne laisse plus voir que le
    titre, ne réveille rien, ni alors ni plus tard (ADR 0265)."""
    target = triggers.asked(news.key)
    return tuple((p.id, a.objective) for p in s.projects.values() for a in p.asks
                 if a.target == target and a.objective and f"#{a.number}" == news.detail
                 and reads(s, p, target, world))
