"""Les issues, reflet des tickets (ADR 0275) : ce qui part chez l'hôte du dépôt distant, et ce qui en revient.

Le ticket du moteur fait foi. Un projet qui a un dépôt distant règle son reflet (``Project.issues`` : jamais, sur
accord — le défaut —, toujours) ; ici :

- **Ce qui part** est une capacité, avec son aperçu : publier un ticket (``projects.issue``), fermer ou rouvrir son
  issue (``projects.issue_state``), publier une note de son fil (``projects.issue_note``). Leurs arguments ne portent
  que des numéros : le texte se compose à l'aperçu et au départ (``compose``), à partir de la projection — ce que
  l'oubli a effacé n'y reste donc pas —, et l'accord l'épingle. Une publication se demande (``projects.issue_asked`` :
  « Publier » dans la console, ``ticket_publish`` en exécution), ou se propose d'elle-même quand le projet synchronise.
- **Ce qui ne part jamais sans accord** (``reasons``, ``needs_accord``), quel que soit le réglage : un ticket dont
  le niveau dépasse celui du projet, un ticket ouvert par un autre projet, un ticket d'un projet qui porte des sujets
  hérités (``read_about``) ; toute note qu'elle choisit elle-même de publier ; et (ADR 0278) un ticket qu'elle a
  ouvert elle-même, ou dont le titre ou le texte nomme une personne du projet. En synchronisation, seuls partent
  d'eux-mêmes les tickets ouverts par une personne — le propriétaire, qui pilote le projet, l'opérateur —, sans
  nom de personne.
- **Le fil ne se synchronise pas.** Du fil, seule part une note choisie, une par une. Elle dit dans son texte qui l'a
  écrite (``note_body``) : sa persona pour une note d'elle ; le nom d'une personne seulement quand c'est cette
  personne qui publie ; sinon aucun nom — tout part du compte du jeton.
- **Ce qui revient** (le processus ``projects.issues``, ``entering``) : une issue ouverte là-bas sans repère entre
  comme un ticket « proposé », son titre, son texte et le nom du compte dans des contenus effaçables ; un commentaire
  entre dans le fil du ticket, le nom du compte cité ; une fermeture ou une réouverture se suit (``verdict``). Tout
  cela est la donnée d'un inconnu : rien n'en lève une question, n'en valide un plan, n'en déclenche un objectif.
  Des commentaires, seuls ceux d'un ticket suivi comptent dans la borne d'une passe (ADR 0278) : ceux des pull
  requests et des issues non suivies, que l'hôte rend avec eux, ne retiennent plus les autres. Et les tickets venus
  de l'hôte sont bornés aussi par jour (``HOSTED_PER_DAY``).
- **Un ticket ne se publie qu'une fois.** L'issue porte un repère (``ticket_mark``) : l'hôte retrouve celle qui le
  porte déjà, et c'est à sa lecture que le ticket reçoit le numéro de son issue — un fait arrivé, posé une fois.

Les règles sont pures (``reasons``, ``unpublishable``, ``verdict`` ; le ticket que reflète une issue, que lisent la
console et l'API par personne : ``issue_ticket``) ; les textes de console sont dans
``inspect_issues.py``, ses phrases et ce qui part dans la voix (``projects.issues``).

Son fait est ici (ADR 0313) : la demande de publier (``projects.issue_asked``), sa charge utile et son réducteur —
elle attend sa proposition. Ce qui part ou doit partir (``Project.issue_moves``, ``IssueMove``), ce qu'un départ
fait du projet (``with_issue_move``) et les lectures que tous en font (``issue_move``, ``reflected``) sont dans
``faculty.py``, dont les réducteurs des effets les écrivent aussi ; le numéro d'une issue et son état, dans
``tracker.py``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects import tracker
from mika.faculties.projects.atelier import SEEN_KEY
from mika.faculties.projects.capability_common import effect_project, pin_of, project_refusal
from mika.faculties.projects.faculty import (
    INHERITED,
    ISSUE_CAPABILITY,
    ISSUE_NOTE_CAPABILITY,
    ISSUE_STATE_CAPABILITY,
    MOVE_CLOSE,
    MOVE_NOTE,
    MOVE_PUBLISH,
    MOVE_REOPEN,
    MOVE_TRIES_MAX,
    MOVES,
    PROJECTS,
    REFRAMED,
    TICKETS_OPEN_MAX,
    IssueMove,
    Item,
    Project,
    ProjectsState,
    board_ticket,
    issue_move,
    reflected,
    repo_page,
    subjects_of,
    with_issue_move,
    with_project,
    written,
)
from mika.faculties.projects.inspect_issues import CANNOT, DESCRIPTION, DONE, HOW, PREVIEW, SUMMARY, WHY
from mika.faculties.projects.pulls import named, names_someone
from mika.faculties.projects.tool_common import caretaker, gone_reply, running_project
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.faculty import CatchUp, ToolResult
from mika.kernel.frame import Frame
from mika.kernel.operate import Preview
from mika.ports.workshop import ISSUE_CLOSED, ISSUE_OPEN, ISSUE_STATES, Issue, Issues
from mika.vocab.episodes import PROJECT_KINDS, project_target
from mika.vocab.phrasebook import phrase

RUNS = list(PROJECT_KINDS)
#: entre deux lectures de l'hôte, au moins ; et l'écart minimal entre deux passes qui ont encore à faire
POLL_US = 10 * MINUTE
RETRY_US = MINUTE
#: les tickets proposés venus de l'hôte qu'un projet garde à la fois, au plus ; ce qu'une passe fait entrer : des
#: issues, des commentaires
HOSTED_PROPOSED_MAX = 30
IMPORTS_PER_PASS, REMARKS_PER_PASS = 10, 20
#: les tickets venus de l'hôte qu'un projet laisse entrer par jour, au plus (ADR 0278) : ouvrir puis fermer des
#: issues là-bas libérait la borne des proposés, passe après passe, sans limite dans le temps
HOSTED_PER_DAY = 30
#: la clé d'un ticket né d'une issue de l'hôte : une issue n'entre jamais deux fois
HOSTED_KEY = "issue-{number}"
_TICKET_MARK = re.compile(r"p(\d+)-t(\d+)")

# ── Les règles, pures ─────────────────────────────────────────────────────

#: pourquoi un texte ne part jamais sans accord (les clés de ``inspect_issues.WHY``)
LEVEL, OTHER_PROJECT, INHERITED_SUBJECTS, HERS = "level", "project", "inherited", "hers"
#: …et pourquoi la publication d'un ticket ne part jamais sans accord (ADR 0278) : c'est elle qui l'a ouvert ; son
#: titre ou son texte nomme une personne du projet
OWN, NAMED = "own", "named"
#: qui peut avoir ouvert un ticket qui se publie de lui-même en synchronisation : une personne, ou l'opérateur
BY_PEOPLE = (c.BY_PERSON, c.BY_OPERATOR)


def ticket_mark(project: int, number: int) -> str:
    """Le repère que porte l'issue d'un ticket : à sa relecture, on la reconnaît — elle ne s'ouvre pas deux fois, et
    n'entre pas comme l'issue d'un inconnu."""
    return f"p{project}-t{number}"


def note_mark(project: int, seq: int) -> str:
    """Le repère que porte une note publiée : elle ne se publie pas deux fois, et ne revient pas dans le fil."""
    return f"p{project}-n{seq}"


def issue_page(p: Project, number: int) -> str:
    """La page d'une issue chez l'hôte, composée du dépôt et de son numéro (jamais reprise d'une réponse)."""
    return f"{repo_page(p)}/issues/{number}" if p.remote and number > 0 else ""


def issue_ticket(p: Project, number: int) -> Item | None:
    """Le ticket que reflète cette issue : celui qui porte son numéro, ou qui en est né (``issue-<n>``)."""
    return next((x for x in p.board.items if x.list_name == c.TICKETS
                 and (x.issue == number or x.key == HOSTED_KEY.format(number=number))), None)


def reasons(p: Project, item: Item) -> tuple[str, ...]:
    """Pourquoi rien de ce ticket ne part sans accord, quel que soit le réglage du projet : son niveau dépasse ce
    qu'écrit le projet (une demande d'un projet qui lit plus confidentiel), un autre projet l'a ouvert, ou le projet
    porte des sujets hérités de ce qu'il lit — ce texte peut parler de personnes qui ne sont pas les siennes. Vide :
    le réglage décide."""
    out = []
    if item.level > written(p):
        out.append(LEVEL)
    if c.asking_project(item.author):
        out.append(OTHER_PROJECT)
    if p.read_about:
        out.append(INHERITED_SUBJECTS)
    return tuple(out)


def publishing(p: Project, item: Item, *, names: bool = False) -> tuple[str, ...]:
    """Pourquoi la publication de ce ticket ne part jamais sans accord, en plus de ``reasons`` (ADR 0278) : c'est
    elle qui l'a ouvert — une exécution qu'un texte lu aurait manipulée y écrirait ce qu'elle veut, vers un dépôt
    peut-être public — ; ou son titre ou son texte nomme une personne du projet (``names`` : ``names_person``).
    Seul un ticket ouvert par une personne, sans nom de personne, part de lui-même."""
    out = []
    if item.author not in BY_PEOPLE and not c.asking_project(item.author):
        out.append(OWN)
    if names:
        out.append(NAMED)
    return tuple(out)


def names_person(frame: Frame | None, p: Project, item: Item, *texts: str) -> bool:
    """Un de ces textes — le titre d'un ticket, son texte — nomme-t-il une personne du projet (ADR 0278) : pour qui
    il est, de qui il parle, qui s'occupe d'elle, les personnes des projets qu'il lit, qui a ouvert ce ticket, à qui
    il est confié ? Comme le corps d'une pull request, qui réduit ces lignes à leur état (``pulls.named``). Sans ce
    qu'elle vit, on ne sait pas : non."""
    known = named(frame, p, None, (item.by, item.person, item.accepted_by))
    return bool(known) and any(names_someone(x, known) for x in texts if x)


def needs_accord(p: Project, item: Item | None, what: str, author: str = "", *,
                 names: bool = False) -> tuple[str, ...] | bool:
    """Ce départ attend-il un accord ? Les raisons qui l'imposent quel que soit le réglage (un texte qui porte plus
    que le projet ; un ticket qu'elle a ouvert elle-même, ou qui nomme une personne du projet — ``names`` — ; une
    note qu'elle choisit elle-même), sinon ce que dit le réglage : toujours, sauf quand le projet synchronise. Une
    fermeture ne porte aucun texte : le réglage seul décide. Un ticket qu'on ne retrouve pas : oui."""
    if what in (MOVE_CLOSE, MOVE_REOPEN):
        return p.issues != c.ISSUES_ALWAYS
    if item is None:
        return True
    why = (*reasons(p, item), *(publishing(p, item, names=names) if what == MOVE_PUBLISH else ()),
           *((HERS,) if what == MOVE_NOTE and author == c.BY_SELF else ()))
    return why or p.issues != c.ISSUES_ALWAYS


def unpublishable(item: Item) -> str:
    """Pourquoi ce ticket ne se publie pas (une clé de ``inspect_issues.CANNOT``), ou ``""`` : il a déjà son issue
    — un ticket ne se publie qu'une fois —, il vient de l'hôte, il attend encore son accord, ou il est fermé."""
    if item.list_name != c.TICKETS:
        return "not_ticket"
    if item.issue:
        return "published"
    if item.author == c.BY_HOST:
        return "hosted"
    if item.proposed or item.status == c.STAGE_PROPOSED:
        return "proposed"
    return "closed" if item.closed else ""


#: ce qu'une lecture de l'hôte demande pour un ticket qui a son issue : rien ; poser ce que l'hôte dit ; l'hôte
#: l'emporte (le ticket suit) ; le ticket l'emporte (l'issue suit)
NOTHING, SEEN, HOST, LOCAL = "", "seen", "host", "local"


def verdict(item: Item, seen: Issue) -> tuple[str, bool]:
    """Ce que l'état d'une issue relue demande pour son ticket, et si les deux ont changé depuis la dernière lecture.

    - Ils disent la même chose : rien, ou seulement le fait neuf de l'hôte.
    - L'hôte seul a changé (ce qu'il dit n'est plus ce qu'on savait de lui) : le ticket suit.
    - Le ticket seul a changé (il ne dit plus ce que l'hôte disait) : l'issue suit.
    - Les deux ont changé — un ticket rouvert ici pendant que l'hôte la refermait : **le dernier changement
      l'emporte**, l'heure du ticket (sa fermeture, sa dernière réouverture) face à celle que dit l'hôte."""
    local = ISSUE_CLOSED if item.closed else ISSUE_OPEN
    host_new = seen.state != item.issue_state or (seen.state == ISSUE_CLOSED and seen.state_at > item.issue_at)
    if seen.state == local:
        return (SEEN if host_new else NOTHING), False
    local_new = local != item.issue_state
    if host_new and not local_new:
        return HOST, False
    if not host_new:
        return LOCAL, False
    local_at = item.closed_at if item.closed else item.reopened_at
    host_at = seen.state_at if seen.state == ISSUE_CLOSED else seen.at
    return (HOST if host_at >= local_at else LOCAL), True


# ── Son fait et son réducteur (ADR 0313) ──────────────────────────────────


class IssueAsked(Payload):
    """Quelqu'un demande de publier un ticket en issue, ou une note de son fil (ADR 0275) : elle, pendant une
    exécution, ou une personne depuis la console. Aucun texte : des numéros — ce qui partira se compose à l'aperçu."""

    project: int
    ticket: int
    #: ``MOVE_PUBLISH`` ou ``MOVE_NOTE`` (et alors ``note`` : l'événement qui porte la note)
    what: str = MOVE_PUBLISH
    note: int = 0
    #: qui le demande (``self``, ``operator``, ``person``) et sa personne
    author: str = c.BY_SELF
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


ISSUE_ASKED = PROJECTS.event("issue_asked", IssueAsked, subjects=("owner", "about", "by", INHERITED))


@PROJECTS.reducer(ISSUE_ASKED)
def _issue_asked(s: ProjectsState, e, cx) -> ProjectsState:
    """Une publication demandée (ADR 0275) attend sa proposition (le processus ``projects.issues``). Total : un
    projet qui ne reflète rien, une sorte inconnue, un départ déjà en route ou déjà fait ne changent rien ; un
    départ refusé ou en échec repart de zéro — le redemander est un geste."""
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not reflected(p) or d.what not in (MOVE_PUBLISH, MOVE_NOTE) or d.ticket <= 0:
        return s
    note = max(0, d.note) if d.what == MOVE_NOTE else 0
    if d.what == MOVE_NOTE and not note:
        return s
    old = issue_move(p, d.ticket, d.what, note)
    if old is not None and (old.proposal or old.sent_at):
        return s
    return with_project(s, with_issue_move(p, IssueMove(d.ticket, d.what, note, d.author, d.by, asked=e.seq, at=e.at)))


# ── Ce qui doit partir ────────────────────────────────────────────────────


def _held(p: Project) -> list[Item]:
    return [x for x in p.board.items if x.list_name == c.TICKETS]


def _stalled(move: IssueMove | None) -> bool:
    """Ce départ est-il déjà en route, fait, ou épuisé (un refus, trois échecs) ? Il ne se repropose alors pas."""
    return move is not None and bool(move.proposal or move.sent_at or move.tries >= MOVE_TRIES_MAX)


def _follows(p: Project, item: Item) -> str:
    """La fermeture ou la réouverture que l'état de ce ticket demande à son issue, d'après ce que l'hôte en disait
    en dernier (``""`` : ils disent la même chose, ou ce départ est déjà en route, fait ou épuisé)."""
    if not item.issue or item.issue_state not in ISSUE_STATES:
        return ""
    what = MOVE_CLOSE if item.closed else MOVE_REOPEN
    same = (ISSUE_CLOSED if item.closed else ISSUE_OPEN) == item.issue_state
    return "" if same or _stalled(issue_move(p, item.number, what)) else what


def pending(p: Project) -> bool:
    """Quelque chose reste-t-il à proposer pour ce projet : une publication demandée, un ticket accepté que la
    synchronisation n'a pas encore publié, une fermeture que son issue n'a pas suivie ?"""
    if any(not _stalled(m) for m in p.issue_moves if m.what in (MOVE_PUBLISH, MOVE_NOTE)):
        return True
    held = _held(p)
    if p.issues == c.ISSUES_ALWAYS and any(
            not unpublishable(x) and issue_move(p, x.number, MOVE_PUBLISH) is None for x in held):
        return True
    return any(_follows(p, x) for x in held)


def awaited(p: Project, now: int) -> bool:
    """Un départ vient-il de se faire, dont le fait (le numéro de l'issue, son état) est encore à lire chez l'hôte ?"""
    return any(m.sent_at and m.what != MOVE_NOTE and now - m.sent_at < POLL_US for m in p.issue_moves)


def proposal(p: Project, ticket: int, what: str, *, note: int = 0, approval: bool = True) -> Draft[Any]:
    """La proposition d'un départ vers les issues. Ses arguments ne portent que des numéros et le dépôt ; son résumé
    ne dit rien de plus."""
    capability = {MOVE_PUBLISH: ISSUE_CAPABILITY, MOVE_NOTE: ISSUE_NOTE_CAPABILITY}.get(what, ISSUE_STATE_CAPABILITY)
    args = {"project": p.id, "ticket": ticket, "what": what, "note": note, "url": p.remote}
    summary = SUMMARY[what].format(ticket=ticket, project=p.id, url=p.remote)
    return rt.EFFECT_PROPOSED.draft(
        capability=capability, owner=PROJECTS.name, context=project_target(p.id), approval=approval,
        args_json=json.dumps(args), summary=Content.of(summary[:600], level=written(p)), about=subjects_of(p))


def _ticket(p: Project, store: Any, number: int) -> Item | None:
    """Un ticket du projet par son numéro : dans l'état s'il y est encore, sinon dans la projection."""
    held = board_ticket(p, number)
    if held is not None or number <= 0:
        return held
    e = tracker.ticket(store, p.id, number)
    return e.item if e is not None else None


def _linked(p: Project, store: Any, issue: int) -> Item | None:
    """Le ticket dont c'est l'issue : dans l'état s'il y est encore, sinon dans la projection."""
    held = next((x for x in _held(p) if x.issue == issue), None)
    if held is not None or issue <= 0:
        return held
    e = tracker.by_issue(store, p.id, issue)
    return e.item if e is not None else None


def _names(p: Project, store: Any, frame: Frame | None, item: Item | None) -> bool:
    """Ce ticket, tel que la projection le garde, nomme-t-il une personne du projet dans son titre ou son texte ?
    Lu seulement quand le projet synchronise : ailleurs l'accord est demandé de toute façon."""
    if item is None or p.issues != c.ISSUES_ALWAYS:
        return False
    e = tracker.ticket(store, p.id, item.number) if store is not None else None
    return e is not None and names_person(frame, p, item, e.title, e.body)


def leaving(p: Project, store: Any, seen: Issues | None, frame: Frame | None = None) -> list[Draft[Any]]:
    """Ce qu'une passe propose de faire partir : les publications demandées, les tickets acceptés d'un projet qui
    synchronise, et — l'hôte relu — les fermetures et réouvertures que les issues n'ont pas suivies. Une issue
    absente de la lecture (elle n'a pas bougé depuis longtemps) dit ce qu'elle disait en dernier. ``frame`` : ce
    qu'elle vit — les noms des personnes du projet s'y lisent (ADR 0278)."""
    out: list[Draft[Any]] = []
    for m in p.issue_moves:
        if m.what in (MOVE_PUBLISH, MOVE_NOTE) and not _stalled(m):
            item = _ticket(p, store, m.ticket)
            names = m.what == MOVE_PUBLISH and _names(p, store, frame, item)
            out.append(proposal(p, m.ticket, m.what, note=m.note,
                                approval=bool(needs_accord(p, item, m.what, m.author, names=names))))
    held = _held(p)
    if p.issues == c.ISSUES_ALWAYS:
        out += [proposal(p, x.number, MOVE_PUBLISH,
                         approval=bool(needs_accord(p, x, MOVE_PUBLISH, names=_names(p, store, frame, x))))
                for x in held if not unpublishable(x) and issue_move(p, x.number, MOVE_PUBLISH) is None]
    if seen is None:
        return out
    said = {x.number: x for x in seen.items}
    for item in held:
        what = _follows(p, item)
        last = said.get(item.issue) or Issue(number=item.issue, state=item.issue_state, state_at=item.issue_at)
        if what and verdict(item, last)[0] == LOCAL:
            out.append(proposal(p, item.number, what, approval=bool(needs_accord(p, item, what))))
    return out


# ── Ce qui revient de l'hôte ──────────────────────────────────────────────


def _said(author: str, text: str, limit: int) -> str:
    """Ce qu'un inconnu a écrit chez l'hôte, précédé du nom de son compte là-bas — dans le même contenu : l'oubli
    efface l'un avec l'autre. Borné ici aussi : ce qu'un port rend ne se croit pas sur parole."""
    name, words = " ".join(author.split())[:80], text.strip()[:limit]
    return f"{name} : {words}" if name else words


def imported(p: Project, issue: Issue) -> Draft[Any]:
    """Le ticket « proposé » que fait naître une issue ouverte chez l'hôte par quelqu'un d'autre : sa clé dit son
    numéro là-bas — elle n'entre jamais deux fois —, son texte porte le nom du compte qui l'a écrite, sa référence est
    sa page. Tout cela est écrit par un inconnu : le propriétaire l'accepte ou l'écarte avant qu'elle y travaille."""
    return tracker.adding(p, c.TICKETS, HOSTED_KEY.format(number=issue.number), issue.title,
                          text=_said(issue.author, issue.body, tracker.TEXT_MAX - 100),
                          link=issue_page(p, issue.number), proposed=True, author=c.BY_HOST, issue=issue.number)


def followed(p: Project, item: Item, issue: Issue) -> list[Draft[Any]]:
    """Les faits qu'une issue relue pose sur son ticket (``verdict``) : ce que l'hôte dit ; sa fermeture — traité,
    écarté quand il la dit « non prévue » ou que le ticket était encore proposé ; sa réouverture — proposé de
    nouveau quand le ticket venait de l'hôte. Quand les deux ont changé, la note du fil dit qui l'emporte."""
    what, both = verdict(item, issue)
    fact = {"issue_state": issue.state, "issue_at": issue.state_at}
    if what == SEEN:
        return [tracker.changing(p, item, author=c.BY_HOST, **fact)]
    if what == HOST:
        note = phrase("projects.issues.thread.host_wins") if both else ""
        if issue.state == ISSUE_CLOSED:
            closed = c.DROPPED if issue.dropped or item.proposed else c.DONE
            return [tracker.changing(p, item, author=c.BY_HOST, closed=closed, note=note, **fact)]
        return [tracker.changing(p, item, author=c.BY_HOST, closed="", reproposed=item.author == c.BY_HOST,
                                 note=note, **fact)]
    if what == LOCAL and both:  # ce que l'hôte a fait entre-temps se pose, et se dit : l'issue suivra le ticket
        return [tracker.changing(p, item, note=phrase("projects.issues.thread.local_wins"), **fact)]
    return []


def entering(p: Project, store: Any, seen: Issues, now: int | None = None) -> list[Draft[Any]]:
    """Ce qu'une lecture de l'hôte fait entrer : le numéro de l'issue d'un ticket qu'on vient de publier (elle porte
    son repère), l'état des issues suivies, les issues ouvertes là-bas par d'autres — des tickets proposés, bornés
    à la fois et par jour (``now`` : l'heure du moteur ; sans elle, celle de la lecture) —, puis les commentaires
    faits là-bas, dans le fil de leur ticket, une seule fois chacun. Ce qui porte un repère d'ici n'entre jamais
    comme la parole d'un inconnu."""
    out: list[Draft[Any]] = []
    waiting = sum(1 for x in _held(p) if x.author == c.BY_HOST and x.status == c.STAGE_PROPOSED)
    today = tracker.hosted_day(p, seen.read_at if now is None else now)[1]
    room = min(IMPORTS_PER_PASS, HOSTED_PROPOSED_MAX - waiting, HOSTED_PER_DAY - today,
               TICKETS_OPEN_MAX - tracker.open_tickets(p.board))
    born = False
    for issue in sorted(seen.items, key=lambda x: x.number):
        if issue.number <= 0 or issue.state not in ISSUE_STATES:
            continue
        mine = _TICKET_MARK.fullmatch(issue.mark) if issue.mark else None
        if mine is not None:
            item = _ticket(p, store, int(mine.group(2))) if int(mine.group(1)) == p.id else None
            if item is None or item.issue not in (0, issue.number):
                continue  # le reflet d'un autre projet, ou d'un ticket qui a déjà une autre issue
            if not item.issue:
                out.append(tracker.changing(p, item, issue=issue.number, issue_state=issue.state,
                                            issue_at=issue.state_at))
                continue
        elif issue.mark:
            continue
        else:
            item = _linked(p, store, issue.number)
            if item is None:
                if issue.state == ISSUE_OPEN and room > 0 and issue.title.strip():
                    out.append(imported(p, issue))
                    room, born = room - 1, True
                continue
        out += followed(p, item, issue)
    if born:
        return out  # les commentaires d'une issue qui vient d'entrer attendent la passe suivante : son ticket existera
    # ceux d'un ticket suivi d'abord, la borne ensuite (ADR 0278) : l'hôte rend aussi les commentaires des pull
    # requests et des issues non suivies — vingt d'entre eux devant un commentaire lié le retenaient pour toujours.
    # Déjà entré : écrit avant le repère, ou à sa seconde avec un numéro déjà pris — deux commentaires de la même
    # seconde entrent tous les deux, aucun deux fois (sa clé de dédoublonnage le garde aussi)
    tickets_of: dict[int, Item | None] = {}
    fresh = []
    for r in sorted(seen.remarks, key=lambda r: (r.at, r.id)):
        if r.mark or not r.body.strip() or r.issue <= 0 or tracker.remark_entered(p, r.at, r.id):
            continue
        if r.issue not in tickets_of:
            tickets_of[r.issue] = _linked(p, store, r.issue)
        if tickets_of[r.issue] is not None:
            fresh.append((r, tickets_of[r.issue]))
    for r, item in fresh[:REMARKS_PER_PASS]:
        out.append(tracker.noting(p, item, _said(r.author, r.body, tracker.NOTE_MAX - 100), author=c.BY_HOST,
                                  host_at=r.at, host_id=r.id, dedupe_key=f"remark:{p.id}:{r.id}"))
    return out


# ── Ce qui sort de la machine : son texte ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class Made:
    """Un départ tel qu'il partirait maintenant : sa sorte, le ticket et son issue, le titre et le texte (vides : une
    fermeture n'en porte pas), son repère, pourquoi un accord est requis quoi qu'il arrive, et le condensé qui épingle
    le tout."""

    what: str
    ticket: int
    issue: int
    title: str
    body: str
    mark: str
    closed: str
    why: tuple[str, ...]
    digest: str


def note_body(frame: Frame, note: tracker.ThreadNote, move: IssueMove | None) -> str:
    """Le texte d'une note publiée : il dit qui l'a écrite. Une note d'elle part sous le nom de sa persona. Le nom
    d'une personne n'y figure que si c'est cette personne qui publie ; sinon la note part sans nom — chez l'hôte,
    tout part du même compte, et nommer quelqu'un à sa place serait le publier sans lui."""
    text = note.text.strip()
    if note.author == c.BY_SELF:
        return phrase("projects.issues.text.note_self", name=self_c.name_of(frame.get(self_c.PERSONA)), text=text)
    publisher = move.by if move is not None and move.author in (c.BY_PERSON, c.BY_OPERATOR) else ""
    hers = bool(publisher) and note.by == publisher and note.author in (c.BY_PERSON, c.BY_OPERATOR)
    name = identity_c.person_name(frame, note.by) if hers else ""
    return phrase("projects.issues.text.note_named", name=name, text=text) if name else \
        phrase("projects.issues.text.note_bare", text=text)


async def compose(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Made | str:
    """Le départ que ces arguments feraient maintenant, composé de la projection — ou pourquoi il ne peut pas partir
    (une clé de ``inspect_issues.CANNOT``, déjà en mots). Les arguments ne portent que des numéros et le dépôt."""
    frame = ports["frame"]() if "frame" in ports else None
    store = ports.get("store")
    pid, number, what = args.get("project"), args.get("ticket"), str(args.get("what") or "")
    p = frame.state("projects").projects.get(pid) if frame is not None and isinstance(pid, int) else None
    e = tracker.ticket(store, p.id, number) if p is not None and isinstance(number, int) else None
    if p is None or e is None or what not in MOVES:
        return CANNOT["missing"]
    url = str(args.get("url") or "")
    if not reflected(p) or url != p.remote:
        return CANNOT["moved"]
    item = e.item
    made = {"what": what, "ticket": item.number, "issue": item.issue, "title": "", "body": "", "mark": "",
            "closed": item.closed, "why": ()}
    if what == MOVE_PUBLISH:
        if why := unpublishable(item):
            return CANNOT[why]
        if not e.title.strip():
            return CANNOT["forgotten"]
        body = "\n\n".join(x for x in (e.body.strip(), phrase("projects.issues.text.foot", number=item.number)) if x)
        # pourquoi l'accord est demandé quel que soit le réglage : ce que porte le ticket, qui l'a ouvert, et
        # s'il nomme une personne du projet (ADR 0278)
        why = (*reasons(p, item), *publishing(p, item, names=names_person(frame, p, item, e.title, e.body)))
        made.update(title=e.title.strip(), body=body, mark=ticket_mark(p.id, item.number), why=why)
    elif not item.issue:
        return CANNOT["unpublished"]
    elif what == MOVE_NOTE:
        seq = args.get("note")
        note = tracker.note_at(store, p.id, c.TICKETS, item.key, seq) if isinstance(seq, int) else None
        if note is None:
            return CANNOT["no_note"]
        if note.author == c.BY_HOST:
            return CANNOT["from_host"]
        if not note.text.strip():
            return CANNOT["forgotten"]
        move = issue_move(p, item.number, MOVE_NOTE, seq)
        accord = needs_accord(p, item, MOVE_NOTE, move.author if move is not None else "")
        made.update(body=note_body(frame, note, move), mark=note_mark(p.id, seq),
                    why=accord if isinstance(accord, tuple) else ())
    elif bool(item.closed) != (what == MOVE_CLOSE):
        return CANNOT["turned"]  # fermé puis rouvert (ou l'inverse) depuis la proposition : elle ne vaut plus
    digest = pin_of(url=url, **{k: v for k, v in made.items() if k != "why"})
    return Made(digest=digest, **made)


def writes_issues(ports: Mapping[str, Any] | None, url: str) -> bool:
    """L'hôte de ce dépôt sait-il écrire dans ses issues ? Un hôte qui ne le sait pas n'a pas la méthode : non."""
    host = (ports or {}).get("repo_host")
    return bool(url) and callable(getattr(host, "open_issue", None)) and bool(host.handles(url))


async def preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui partirait : pour une publication ou une note, le titre et le texte ; pour une fermeture,
    ce qu'elle change et rien d'autre. Et pourquoi l'accord est demandé quel que soit le réglage. Le condensé épingle
    le texte : changé depuis, rien ne part."""
    pid = args.get("project")
    if not isinstance(pid, int):
        return None
    made = await compose(args, ports)
    if isinstance(made, str):
        return Preview(PREVIEW["cannot"].format(why=made), pin_of(why=made), made)
    url = str(args.get("url") or "")
    blocked = project_refusal(ports, pid).removeprefix("refusé : ") or ("" if writes_issues(ports, url) else CANNOT["no_host"])
    said = {"number": made.ticket, "issue": made.issue, "url": url, "how": HOW.get(made.closed, made.closed)}
    rows = [PREVIEW[made.what].format(**said)]
    if made.title:
        rows += ["", PREVIEW["title"].format(title=made.title)]
    if made.body:
        rows += ["", PREVIEW["body"], made.body]
    if made.why:
        rows += ["", PREVIEW["why"].format(why=" ; ".join(WHY[x] for x in made.why))]
    return Preview("\n".join(rows), made.digest, blocked)


async def _leave(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    """Le départ lui-même, après le commit du journal : recomposé, comparé à ce que l'accord a vu, puis écrit chez
    l'hôte — et rien d'autre. Ce qu'il rend ne porte que des numéros et un lien composé."""
    host = ports.get("repo_host")
    pid = effect_project(args, context)
    if pid is None:
        return False, f"refusé : {CANNOT['missing']}"
    if why := project_refusal(ports, pid):
        return False, why
    made = await compose(args, ports)
    if isinstance(made, str):
        return False, f"refusé : {made}"
    seen = str(args.get(SEEN_KEY) or "")
    if seen and seen != made.digest:
        return False, f"refusé : {CANNOT['changed']}"
    url = str(args.get("url") or "")
    if host is None or not writes_issues(ports, url):
        return False, f"refusé : {CANNOT['no_host']}"
    if made.what == MOVE_PUBLISH:
        got = await host.open_issue(url, title=made.title, body=made.body, mark=made.mark)
        number, link = got.number, got.url
    elif made.what == MOVE_NOTE:
        got = await host.remark(url, made.issue, body=made.body, mark=made.mark)
        number, link = made.issue if got.id else 0, ""
    else:
        got = await host.set_issue(url, made.issue, closed=made.what == MOVE_CLOSE, dropped=made.closed == c.DROPPED)
        number, link = got.number, ""
    if got.error or not number:
        return False, "refusé : " + CANNOT["unsent"].format(why=got.error or CANNOT["unsaid"])
    return True, DONE[made.what].format(number=number, url=link)


PROJECTS.capability(ISSUE_CAPABILITY, description=DESCRIPTION["publish"], preview=preview)(_leave)
PROJECTS.capability(ISSUE_STATE_CAPABILITY, description=DESCRIPTION["state"], preview=preview)(_leave)
PROJECTS.capability(ISSUE_NOTE_CAPABILITY, description=DESCRIPTION["note"], preview=preview)(_leave)


# ── Le processus : proposer ce qui part, relire l'hôte ────────────────────


def mirrored(s: ProjectsState) -> list[Project]:
    """Les projets dont les tickets se reflètent en issues : un dépôt distant, et leur réglage."""
    return [p for p in sorted(s.projects.values(), key=lambda p: p.id) if reflected(p)]


@PROJECTS.process("projects.issues", wake_on=[*tracker.MOVES, ISSUE_ASKED, REFRAMED, rt.EFFECT_EXECUTED,
                                              rt.EFFECT_RESOLVED],
                  catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=46)
class Reflect:
    """Tenir les issues pour le reflet des tickets (ADR 0275). Rien ne part d'ici : un départ est une capacité,
    exécutée après le commit du journal, avec ou sans accord selon le projet et ce que porte le texte ; une lecture
    de l'hôte ne fait qu'écrire ce qu'il dit. L'heure de la dernière lecture de chaque dépôt n'est gardée qu'en
    mémoire : elle ne borne que les appels à l'hôte, rien ne s'en déduit."""

    def __init__(self) -> None:
        self._read: dict[int, int] = {}
        self._down: dict[int, int] = {}

    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        mine = mirrored(s)
        if not mine:
            return None
        if last_run is None:
            return frame.now
        fresh = any(pending(p) or awaited(p, frame.now) for p in mine)
        return max(frame.now, last_run + (RETRY_US if fresh else POLL_US))

    async def _seen(self, host: Any, p: Project, now: int) -> Issues | None:
        """La lecture de l'hôte pour ce projet, si elle est due : la précédente a plus de dix minutes, ou quelque
        chose attend d'elle. Un hôte qui n'a pas répondu n'est pas redemandé avant dix minutes."""
        read = getattr(host, "issues", None)
        if not callable(read) or not host.handles(p.remote):
            return None
        last = self._read.get(p.id)
        due = last is None or now - last >= POLL_US or pending(p) or awaited(p, now)
        if not due or now - self._down.get(p.id, now - POLL_US) < POLL_US:
            return None
        got = await read(p.remote)
        self._read[p.id] = now
        if got.error:
            self._down[p.id] = now
            return None
        self._down.pop(p.id, None)
        return got

    async def run(self, ctx: Any) -> None:
        s: ProjectsState = ctx.state
        host, store = ctx.ports.get("repo_host"), ctx.ports.get("store")
        facts: list[Draft[Any]] = []
        proposals: list[Draft[Any]] = []
        for p in mirrored(s):
            seen = await self._seen(host, p, ctx.now) if host is not None else None
            if seen is not None:
                facts += entering(p, store, seen, ctx.now)
            proposals += leaving(p, store, seen, ctx.frame)
        if facts:
            await ctx.emit(*facts)
        if proposals:
            await ctx.emit(*proposals, emitter=rt.OWNER)


# ── Son geste en exécution : demander de publier ──────────────────────────

PUBLISH = "ticket_publish"


class PublishArgs(BaseModel):
    item: str = Field(min_length=1, max_length=12, description=phrase("projects.tools.publish.arg.item"))
    note: int = Field(default=0, ge=0, description=phrase("projects.tools.publish.arg.note"))


def asking(p: Project, item: Item, *, note: int = 0, author: str = c.BY_SELF, by: str = "") -> Draft[Any]:
    """La demande de publier un ticket, ou une note de son fil — le seul endroit qui en fait le brouillon. Elle ne
    porte que des numéros, et les sujets du ticket pour l'oubli."""
    return ISSUE_ASKED.draft(project=p.id, ticket=item.number, what=MOVE_NOTE if note else MOVE_PUBLISH, note=note,
                             author=author, by=by, owner=p.owner, about=p.about, read_about=p.read_about)


def refusal(p: Project, item: Item, note: tracker.ThreadNote | None, wanted: int) -> str:
    """Pourquoi cette publication ne se demande pas (une clé de ``inspect_issues.CANNOT``), ou ``""``."""
    if not wanted:
        return unpublishable(item)
    if not item.issue:
        return "unpublished"
    if note is None:
        return "no_note"
    if note.author == c.BY_HOST:
        return "from_host"
    return "" if note.text.strip() else "forgotten"


@PROJECTS.tool(PUBLISH, acts=True, description=phrase("projects.tools.publish.description"),
               label=phrase("projects.tools.publish.label"), args=PublishArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=6)
async def ticket_publish(args: PublishArgs, ctx: Any) -> Any:
    """Demander de publier un ticket du projet en issue, ou une note de son fil en commentaire (ADR 0275). Rien ne
    part d'ici : la demande s'écrit, la capacité se propose ensuite — sur accord, sauf quand le projet synchronise et
    que rien n'impose l'accord ; une note qu'elle choisit attend toujours l'accord."""
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    store = ctx.ports.get("store")
    if not reflected(p) or not writes_issues(ctx.ports, p.remote):
        return ToolResult(ok=False, content=phrase("projects.tools.publish.unset"))
    e = tracker.find(store, p.id, c.TICKETS, args.item)
    if e is None:
        return ToolResult(ok=False, content=phrase("projects.tools.items.unknown", item=args.item, name=c.TICKETS))
    item = e.item
    what = MOVE_NOTE if args.note else MOVE_PUBLISH
    note = tracker.note_at(store, p.id, c.TICKETS, item.key, args.note) if args.note else None
    if refusal(p, item, note, args.note) or (not args.note and not e.title.strip()):
        return ToolResult(ok=False, content=phrase("projects.tools.publish.cannot", number=item.number))
    if _stalled(issue_move(p, item.number, what, args.note)):
        return ToolResult(ok=False, content=phrase("projects.tools.publish.already", number=item.number))
    await ctx.emit(asking(p, item, note=args.note))
    names = not args.note and names_person(ctx.frame, p, item, e.title, e.body)
    if needs_accord(p, item, what, c.BY_SELF, names=names):
        return phrase("projects.tools.publish.asked", number=item.number, who=caretaker(ctx.frame))
    return phrase("projects.tools.publish.leaving", number=item.number)


__all__ = ["Made", "asking", "compose", "entering", "issue_page", "leaving", "names_person", "needs_accord",
           "publishing", "reasons", "refusal", "unpublishable", "verdict"]
