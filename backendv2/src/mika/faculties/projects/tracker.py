"""Le registre d'un projet (ADR 0268) : ses tickets et ses listes de suivi.

Ce qui se suit en série — les constats d'un audit, ce qu'on demande au projet, des entreprises à contacter — se tient
dans le journal, pas dans un fichier qu'elle penserait à relire :

- **Les événements** : ``projects.list_set`` (une liste : son nom, son titre, ses statuts, qui agit par défaut),
  ``item_added``, ``item_changed``, ``item_noted`` (une note dans le fil d'un élément). Chacun porte les sujets du
  projet et ceux qu'il a hérités de ses lectures (``read_about``, ADR 0262).
- **Une liste de suivi** a des statuts posés à la main (``todo``, ``doing``, ``done``, ``dropped`` par défaut,
  réglables liste par liste). **Un ticket** (la liste ``tickets``, que tout projet a d'office) n'en a pas : il porte
  des faits — proposé ou accepté, ouvert ou fermé — et son étape s'en déduit, ici seulement (``stage``).
- **Pas de doublon** : ``adding`` est le seul endroit qui écrit un ajout, sous la clé ``projet:liste:clé``.
- **L'état reste borné** (``faculty.Board``) : les listes, des comptes par liste et par statut, le compteur des
  tickets, tous les tickets ouverts et les derniers éléments touchés. Tout le reste se lit dans la projection T0
  (``Items`` : ``project_items``, ``project_item_notes``), écrite dans la transaction de l'ajout.
- **Une seule règle des deux côtés** : ``added``, ``changed`` et ``after_note`` sont pures ; le réducteur les
  applique à ce que garde l'état, la projection à sa ligne. Un changement dit le statut que voyait qui l'écrit
  (``was``) : il ne vaut que si l'élément l'a encore — un élément que l'état ne garde plus le croit, et y revient (un
  second changement parti du même statut le trouve alors changé).
- **Qui le lit** : ce que chacun en lit (``Reader``, ``veiled``), devant qui ses outils de conversation sont offerts
  (``may_read``), si le détail d'un projet s'entend ici (``hears``), ce que la personne en face peut en lire
  (``reader_of``), qui tranche ses tickets (``settles``) et qui change le cadre d'un projet (``frames``, la même
  règle) — des règles de droits, que la console, l'API, le prompt et les jalons lisent aussi.
- **Ses outils** (en exécution ``items_add``, ``items_change``, ``items_note``, ``items_list`` ; en conversation
  ``project_items`` et ``project_item``) sont dans ``tracker_tools.py``.

Ce que la relecture a fixé (ADR 0272) : un élément garde le **niveau** de ses textes (``Item.level``) — il décide
de qui l'entend en conversation (``Reader``, ``veiled``), et ce qui s'écrit ensuite sur lui est au moins de ce
niveau, avec ses sujets (``changing``, ``noting``, ``validating``) ; un ticket **proposé** ne se lit qu'en une ligne
sans texte pendant une exécution, et elle ne le change pas ; le texte d'une demande proposée ne se lit que par qui
peut la trancher ; une demande verse ses personnes dans ``read_about`` du projet visé (``_item_added``) ; une
validation nomme le plan qu'elle valide.

Le parcours d'un ticket (ADR 0270) a ses règles à part, pures (``tickets.py`` : son étape, à qui la main, les faits
qu'un geste pose) : ``changed`` et le réducteur d'une note les appliquent, des deux côtés. Ici reste ce qui s'écrit
(``validating`` : un plan validé et l'objectif qui en naît) ; ce que le propriétaire en fait en conversation
(``project_item`` : valider, refuser) est dans ``tracker_tools.py``. Ses gestes à elle sont dans ``triage.py``. La
section du prompt est dans ``prompt.py``, la console dans ``inspect_tracker.py``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import BigInteger, Column, Index, Table, case, func, not_, or_, select, update

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import asks, milestones, tickets, triggers
from mika.faculties.projects.access import reads
from mika.faculties.projects.faculty import (
    INHERITED,
    ITEM_CHANGES_KEPT,
    ITEMS_RECENT,
    MOVE_CLOSE,
    MOVE_PUBLISH,
    MOVE_REOPEN,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    OBJECTIVES_KEPT,
    PROJECTS,
    Board,
    Change,
    Item,
    Listing,
    Project,
    ProjectsState,
    awaits_her,
    hear_if_listening,
    inherited_on,
    issue_settled,
    live,
    objective_at,
    spread_confidentiality,
    with_project,
    written,
    written_on,
)
from mika.faculties.projects.faculty import living as open_objectives
from mika.faculties.projects.tool_common import caretaker
from mika.kernel.clock import DAY
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.faculty import Tier
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.text import clipped, fold
from mika.ports.sql import HANDLE_MAX, Key, LongText, insert_ignore, projection_table
from mika.ports.store import Sql
from mika.ports.workshop import ISSUE_OPEN, ISSUE_STATES
from mika.vocab.days import ago_words
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity, hearable

# ── Les bornes ────────────────────────────────────────────────────────────

#: la clé d'un élément : un identifiant court, pas un texte (des minuscules, des chiffres, des tirets, des points)
KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,59}")
KEY_MAX = 60
#: un statut d'une liste : un mot de son vocabulaire, pas un texte gardé (des lettres, des chiffres, des espaces)
STATUS = re.compile(r"[^\W_][\w '’-]{0,23}")
STATUS_MAX, STATUSES_MAX = 24, 8
TITLE_MAX, TEXT_MAX, NOTE_MAX, LINK_MAX = 200, 4000, 2000, 300
#: les éléments d'un ajout, au plus ; une page de lecture
PER_CALL = 25
PAGE = 20
#: ce qu'un outil cite d'un titre, et le fil qu'il montre
TITLE_SHOWN = 120
THREAD_SHOWN = 50

TICKET_LIST = Listing(c.TICKETS, open=c.STAGES_OPEN, closed=c.STAGES_CLOSED)


# ── Les règles, pures ─────────────────────────────────────────────────────


def stage(item: Item) -> str:
    """L'étape d'un ticket, déduite de ses faits (ADR 0268) — jamais d'un statut posé à la main. Sa règle est celle
    de son parcours (``tickets.stage``, ADR 0270), le seul endroit qui la dit."""
    return tickets.stage(item)


def named_list(text: str) -> str | None:
    """Le nom d'une liste tel qu'on l'écrit, normalisé ; ``None`` s'il ne s'écrit pas ainsi (celui qu'un déclencheur
    ``item:<liste>`` nomme : ``triggers.NAME``)."""
    name = (text or "").strip().lower()
    return name if triggers.NAME.fullmatch(name) else None


def slug(text: str) -> str:
    """Une clé donnée à la main, normalisée (sans casse ni accents, ce qui n'est ni lettre ni chiffre devient un
    tiret) ; vide si rien n'en reste."""
    return re.sub(r"[^a-z0-9.]+", "-", fold(text or "")).strip("-.")[:KEY_MAX].strip("-.")


def key_of(given: str, title: str) -> str:
    """La clé d'un élément : celle qu'on lui donne, normalisée ; sinon déduite de son titre, stable (le même titre
    donne la même clé : un second ajout est un doublon) et illisible (une empreinte — le titre d'une personne ne
    reste pas en clair dans une clé que l'oubli n'atteint pas)."""
    key = slug(given)
    if key:
        return key
    return "t-" + hashlib.sha256(fold(" ".join((title or "").split())).encode()).hexdigest()[:16]


def status_label(text: str) -> str | None:
    """Un statut tel qu'on le règle sur une liste, normalisé ; ``None`` s'il ne s'écrit pas ainsi."""
    label = " ".join((text or "").split()).lower()
    return label if STATUS.fullmatch(label) else None


def statuses_of(opened: Iterable[str], closed: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Les statuts d'une liste, tels qu'elle les garde : ouverts puis clos, chacun une fois, ``STATUSES_MAX`` au
    plus ; sans un statut ouvert qui se lise, ceux par défaut — la règle du réducteur, qui reste total."""
    first = tuple(dict.fromkeys(x for x in map(status_label, opened) if x))
    second = tuple(dict.fromkeys(x for x in map(status_label, closed) if x and x not in first))
    if not first:
        return c.ITEM_OPEN, c.ITEM_CLOSED
    first = first[:STATUSES_MAX]
    return first, second[:STATUSES_MAX - len(first)]


def listing(board: Board, name: str) -> Listing | None:
    """Une liste du projet par son nom ; ``tickets`` existe toujours."""
    return TICKET_LIST if name == c.TICKETS else next((x for x in board.lists if x.name == name), None)


def listings(board: Board) -> tuple[Listing, ...]:
    """Ses listes : ``tickets`` d'abord, puis ses listes de suivi dans l'ordre où elles sont nées."""
    return (TICKET_LIST, *board.lists)


def count(board: Board, name: str, status: str | None = None) -> int:
    """Combien d'éléments dans cette liste (dans ce statut, ou en tout)."""
    return sum(n for lst, st, n in board.counts if lst == name and (status is None or st == status))


def living(board: Board, lst: Listing) -> int:
    """Ses éléments ouverts : ceux dont le statut n'est pas un de ses statuts clos."""
    return sum(n for name, st, n in board.counts if name == lst.name and st not in lst.closed)


def _counted(counts: tuple[tuple[str, str, int], ...], name: str, status: str, delta: int
             ) -> tuple[tuple[str, str, int], ...]:
    got = {(lst, st): n for lst, st, n in counts}
    got[(name, status)] = max(0, got.get((name, status), 0) + delta)
    return tuple(sorted((lst, st, n) for (lst, st), n in got.items() if n > 0))


def writer(d: Any) -> str:
    """Qui a écrit, tel que le garde un changement : la personne (ou l'opérateur) par sa clé, sinon son rôle
    (``self``, ``project:<n>``)."""
    return d.by if d.author in (c.BY_PERSON, c.BY_OPERATOR) and d.by else d.author


#: les numéros, chez l'hôte, des commentaires entrés à la seconde du repère, au plus (une lecture en rend cinquante)
REMARK_IDS_KEPT = 60


def hosted_day(p: Project, at: int) -> tuple[int, int]:
    """La journée en cours des tickets venus de l'hôte, à ``at`` (ADR 0278) : (son début, combien y sont entrés).
    Passé un jour depuis son début, elle est finie : (0, 0) — le prochain en ouvre une autre."""
    return (p.hosted_since, p.hosted_count) if p.hosted_since and 0 <= at - p.hosted_since < DAY else (0, 0)


def remark_entered(p: Project, at: int, ident: int) -> bool:
    """Ce commentaire de l'hôte est-il déjà entré, d'après le repère du projet (ADR 0278) ? Oui s'il a été écrit
    avant le dernier entré, ou à la même seconde avec un numéro déjà pris."""
    return at < p.remarks_at or (at == p.remarks_at and ident in p.remarks_ids)


def addable(d: Any) -> bool:
    """Un ajout qui se lit : un nom de liste et une clé bien écrits — la même règle pour le réducteur et la
    projection."""
    return bool(triggers.NAME.fullmatch(d.list_name or "")) and bool(KEY.fullmatch(d.key or ""))


def _ref(content: Content | None, seq: int, field: str) -> str:
    """La référence d'un contenu de l'événement ``seq`` (``""`` : il n'en porte pas)."""
    return "" if content is None else (content.ref or f"{seq}.{field}")


def _level(*contents: Content | None) -> int:
    """Le niveau le plus haut de ces contenus."""
    return max((x.level for x in contents if x is not None), default=0)


def added(d: ItemAdded, at: int, seq: int, number: int) -> Item:
    """L'élément qu'un ajout fait naître. ``number`` : pour un ticket, le suivant du projet. Son niveau est celui de
    ses textes (ADR 0272)."""
    ticket = d.list_name == c.TICKETS
    actor = d.actor if d.actor in c.ACTORS else c.ACTOR_SELF
    item = Item(
        list_name=d.list_name, key=d.key, number=number if ticket else 0, seq=seq,
        title_ref=_ref(d.title, seq, "title"), text_ref=_ref(d.text, seq, "text"), link_ref=_ref(d.link, seq, "link"),
        status=status_label(d.status) or c.TODO, actor=actor, person=d.person if actor == c.ACTOR_PERSON else "",
        objective=max(0, d.objective), kind=(d.kind if d.kind in c.TICKET_KINDS else c.TASK) if ticket else "",
        priority=d.priority if d.priority in c.PRIORITIES else c.NORMAL, author=d.author, by=d.by,
        proposed=ticket and d.proposed, level=_level(d.title, d.text, d.link), at=at, updated_at=at,
        touched_by=d.author,
        # un ticket qu'elle ouvre elle-même, elle l'a écrit : il ne naît pas « non lu » mais « en analyse » (ADR
        # 0280) — le constat d'un audit n'attend pas qu'un autre ouvre un ticket pour être lu
        taken_at=at if ticket and d.author == c.BY_SELF and not d.proposed else 0,
        # une issue ouverte chez l'hôte par quelqu'un d'autre (ADR 0275) : le ticket naît avec elle
        issue=max(0, d.issue) if ticket else 0, issue_state=ISSUE_OPEN if ticket and d.issue > 0 else "")
    return replace(item, status=stage(item)) if ticket else item


def changed(item: Item, d: ItemChanged, at: int, seq: int) -> Item | None:
    """L'élément après ce changement ; ``None`` : rien ne change — ce n'est plus le statut que voyait qui écrit
    (``was``), ou le changement ne change rien. Un ticket ne reçoit jamais de statut : ses faits changent (accepté,
    fermé, rouvert) et son étape se redéduit. Fermé, il n'est plus « proposé » : le rouvrir, c'est l'accepter. Un
    ticket encore proposé ne se ferme pas « traité » (ADR 0272) : il s'accepte d'abord, ou s'écarte. Une validation
    qui ne vaut pas (``tickets.validates``) n'attache pas non plus l'objectif qu'elle apportait."""
    if not d.was or item.status != d.was:
        return None
    by, what, new = writer(d), [], item
    unheld = False
    if item.list_name == c.TICKETS:
        if d.accepted and new.proposed and not new.closed:
            new = replace(new, proposed=False, accepted_at=at, accepted_by=by)
            what.append("accepted")
        if d.closed is not None and d.closed != new.closed and d.closed in ("", c.DONE, c.DROPPED) \
                and not (d.closed == c.DONE and new.proposed):
            new = replace(new, closed=d.closed, closed_at=at if d.closed else 0, closed_by=by if d.closed else "",
                          proposed=False)
            what.append(f"closed:{d.closed}" if d.closed else "reopened")
            if not d.closed:  # rouvert : son parcours repart de rien (ADR 0270)
                new = replace(tickets.reset(new), reopened_at=at)
                if d.reproposed:
                    # rouvert chez l'hôte, par un inconnu (ADR 0275) : il attend de nouveau l'accord du propriétaire
                    new = replace(new, proposed=True, accepted_at=0, accepted_by="")
                    what.append("reproposed")
            elif d.closed == c.DONE and d.pull == c.PULL_MERGED and new.validated_at:
                # fermé par la fusion de la pull request de son objectif (ADR 0274) : il le garde
                new = replace(new, pull=c.PULL_MERGED, pull_number=d.pull_number or new.pull_number)
                what.append(f"pull:{c.PULL_MERGED}")
        new, steps = tickets.stepped(new, d, at, by)  # les faits de son parcours
        what += steps
        # son reflet chez l'hôte (ADR 0275) : le numéro de son issue, posé une fois ; ce que l'hôte en dit
        if d.issue > 0 and not new.issue:
            new = replace(new, issue=d.issue)
            what.append(f"issue:{d.issue}")
        if d.issue_state in ISSUE_STATES and new.issue and \
                (d.issue_state, max(0, d.issue_at)) != (new.issue_state, new.issue_at):
            if d.issue_state != new.issue_state:
                what.append(f"issue:{d.issue_state}")
            new = replace(new, issue_state=d.issue_state, issue_at=max(0, d.issue_at))
        unheld = d.validated and "validated" not in steps
        if d.kind in c.TICKET_KINDS and d.kind != new.kind:
            new = replace(new, kind=d.kind)
            what.append(f"kind:{d.kind}")
        if d.priority in c.PRIORITIES and d.priority != new.priority:
            new = replace(new, priority=d.priority)
            what.append(f"priority:{d.priority}")
    else:
        status = status_label(d.status) if d.status is not None else None
        if status and status != new.status:
            what.append(f"status:{new.status}>{status}")
            new = replace(new, status=status)
    for field in ("title", "text", "link"):
        content = getattr(d, field)
        if content is not None:
            new = replace(new, **{f"{field}_ref": _ref(content, seq, field)}, level=max(new.level, content.level))
            what.append(field)
    if d.actor in c.ACTORS:
        person = (d.person or "") if d.actor == c.ACTOR_PERSON else ""
        if (d.actor, person) != (new.actor, new.person):
            new = replace(new, actor=d.actor, person=person)
            what.append(f"actor:{d.actor}")
    if d.objective is not None and max(0, d.objective) != new.objective and not unheld:
        new = replace(new, objective=max(0, d.objective))
        what.append(f"objective:{new.objective}")
    if not what:
        # ce qu'une exécution de son objectif a changé se compte sans être un changement à dire (ADR 0270) ; l'heure
        # d'une fermeture que l'hôte redit aussi (ADR 0275)
        return new if tickets.measured(item, new) or new.issue_at != item.issue_at else None
    new = replace(new, updated_at=at, touched_by=d.author, notes=new.notes + (1 if d.note is not None else 0),
                  changes=(*new.changes, Change(at, by, ",".join(what)))[-ITEM_CHANGES_KEPT:])
    if new.list_name != c.TICKETS:
        return new
    new = tickets.coherent(new)
    return replace(new, status=stage(new))


def after_note(item: Item, d: ItemNoted, at: int, seq: int) -> Item:
    """L'élément après une note de son fil : elle se compte ; sur un ticket, elle peut poser un fait de son parcours
    (``tickets.noted`` : sa question, son plan, la réponse d'un autre) — la même règle pour l'état et la projection."""
    new = replace(item, notes=item.notes + 1, updated_at=at, touched_by=d.author)
    if new.list_name != c.TICKETS:
        return new
    new = tickets.noted(new, d, at, seq)
    return replace(new, status=stage(new))


@dataclass(frozen=True, slots=True)
class Passage:
    """Un passage d'un ticket par une étape (ADR 0293) : celle où il entre, celle qu'il quitte (vide : sa naissance),
    quand, par quel événement, et qui l'y a fait passer (``author``, ``by`` : ceux de l'événement)."""

    stage: str
    was: str
    at: int
    seq: int
    author: str
    by: str


def passages(events: Iterable[Any]) -> tuple[Passage, ...]:
    """L'histoire des étapes d'un ticket, rejouée de ses événements — du plus ancien au plus récent — par les règles
    mêmes de l'état (``added``, ``changed``, ``after_note``) : une ligne par changement d'étape, rien n'est écrit à
    côté. Des événements qui ne commencent pas par son ajout ne se rejouent pas : aucune histoire."""
    item: Item | None = None
    out: list[Passage] = []
    for e in events:
        d, name = e.data, e.type.name
        if name == ITEM_ADDED.name:
            if item is not None:
                continue  # la même clé ajoutée deux fois : le second ajout n'a rien fait
            new = added(d, e.at, e.seq, 0)
        elif item is None:
            return ()
        elif name == ITEM_CHANGED.name:
            new = changed(item, d, e.at, e.seq) or item
        elif name == ITEM_NOTED.name:
            new = after_note(item, d, e.at, e.seq)
        else:
            continue
        if item is None or new.status != item.status:
            out.append(Passage(new.status, item.status if item is not None else "", e.at, e.seq, d.author, d.by))
        item = new
    return tuple(out)


def unknown(d: ItemChanged) -> Item:
    """Un élément que l'état ne garde plus, tel qu'un changement le redit : sa clé, le statut que voyait qui écrit —
    et, pour un ticket, les faits que dit cette étape (un ticket ouvert reste toujours dans l'état : seul un ticket
    fermé arrive ici). Son numéro et son niveau ne changent jamais : le changement les redit (ADR 0272) — sans son
    numéro, l'objectif né d'un ticket rouvert ne retrouverait pas son ticket. Le numéro de son issue non plus (ADR
    0275) : ce que l'hôte en dit ensuite doit s'y poser."""
    ticket = d.list_name == c.TICKETS
    closed = {c.STAGE_TREATED: c.DONE, c.STAGE_DISMISSED: c.DROPPED}.get(d.was, "") if ticket else ""
    return Item(list_name=d.list_name, key=d.key, number=max(0, d.number) if ticket else 0, status=d.was,
                proposed=ticket and d.was == c.STAGE_PROPOSED, closed=closed, level=max(0, d.level), known=False,
                issue=max(0, d.issue) if ticket else 0)


def _pinned(item: Item) -> bool:
    """Un ticket ouvert ne quitte jamais l'état : son étape se déduit de faits qu'il faut avoir sous la main."""
    return item.list_name == c.TICKETS and item.status in c.STAGES_OPEN


def kept(items: Sequence[Item]) -> tuple[Item, ...]:
    """Ce que l'état garde : tous les tickets ouverts, et les ``ITEMS_RECENT`` derniers éléments touchés."""
    loose = [i for i, x in enumerate(items) if not _pinned(x)]
    drop = set(loose[:-ITEMS_RECENT]) if len(loose) > ITEMS_RECENT else set()
    return tuple(x for i, x in enumerate(items) if i not in drop)


def held(board: Board, name: str, key: str) -> Item | None:
    """Un élément que l'état a sous la main."""
    return next((x for x in board.items if x.list_name == name and x.key == key), None)


def open_tickets(board: Board) -> int:
    return sum(count(board, c.TICKETS, st) for st in c.STAGES_OPEN)


# ── Ses événements ────────────────────────────────────────────────────────


class ListSet(Payload):
    """Une liste de suivi, créée ou réglée d'un coup : son titre, ses statuts ouverts puis clos (vides : ceux par
    défaut), qui agit par défaut sur ses éléments."""

    project: int
    name: str
    title: Content | None = None
    open: tuple[str, ...] = ()
    closed: tuple[str, ...] = ()
    actor: str = c.ACTOR_SELF
    #: la personne qui agit, quand ``actor`` vaut ``person``
    person: str = ""
    #: qui l'a réglée (``self``, ``person``, ``operator``) et sa personne
    author: str = c.BY_SELF
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class ItemAdded(Payload):
    """Un élément de plus dans une liste. Son numéro (un ticket) n'est pas ici : le réducteur et la projection le
    comptent."""

    project: int
    list_name: str
    key: str
    title: Content
    text: Content | None = None
    #: une liste de suivi : son statut de départ ; un ticket n'en a pas
    status: str = ""
    actor: str = c.ACTOR_SELF
    person: str = ""
    #: une référence extérieure (une adresse, un numéro)
    link: Content | None = None
    #: l'objectif qui le tient (0 : aucun)
    objective: int = 0
    #: un ticket : sa sorte, sa priorité, et s'il naît proposé (il attend que le propriétaire l'accepte)
    kind: str = ""
    priority: str = c.NORMAL
    proposed: bool = False
    #: qui l'a ouvert (``self``, ``person``, ``operator``, ``project:<n>``) et sa personne
    author: str = c.BY_SELF
    by: str = ""
    #: une demande d'un autre projet (``author`` : ``project:<n>``, ADR 0271) : l'objectif de ce projet dont
    #: l'exécution l'a ouverte (0 : aucun) — sa fermeture le réveille
    origin: int = 0
    #: une issue ouverte chez l'hôte par quelqu'un d'autre (``author`` : ``host``, ADR 0275) : son numéro là-bas
    issue: int = 0
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class ItemChanged(Payload):
    """Un élément changé (``None`` : inchangé). ``was`` : le statut — l'étape, pour un ticket — que voyait qui
    écrit : le changement ne vaut que si l'élément l'a encore."""

    project: int
    list_name: str
    key: str
    was: str = ""
    #: ce qui ne change jamais d'un élément, redit pour l'état qui ne le garderait plus (ADR 0272) : le numéro d'un
    #: ticket (comme sa clé), et le niveau de ses textes
    number: int = 0
    level: int = 0
    #: une liste de suivi : son nouveau statut
    status: str | None = None
    title: Content | None = None
    text: Content | None = None
    link: Content | None = None
    actor: str | None = None
    person: str | None = None
    objective: int | None = None
    kind: str | None = None
    priority: str | None = None
    #: un ticket, ses faits : accepté par le propriétaire ; fermé (``done`` : traité, ``dropped`` : écarté) ou rouvert
    #: (``""``)
    accepted: bool = False
    closed: str | None = None
    #: un ticket, les faits de son parcours (ADR 0270 ; ``tickets.stepped``) : elle l'a pris ; elle propose de
    #: l'écarter ; son plan est validé, ou refusé ; son objectif bloque (ou ne bloque plus) ; pris comme petit, il a
    #: dépassé sa borne (pourquoi : ``files``, ``lines``, ``dependencies``, ``protected``) ; ce qu'une exécution de
    #: son objectif a changé (des fichiers, des lignes : ils s'ajoutent)
    taken: bool = False
    dismissal: bool = False
    validated: bool = False
    #: le plan que cette validation valide (la note qui le porte, ADR 0272) : elle ne vaut que si c'est encore
    #: celui du ticket (0 : elle ne nomme rien — elle valide le plan qu'elle écrit dans le même geste)
    plan: int = 0
    refused: bool = False
    stuck: bool | None = None
    outgrown: str = ""
    diff_files: int = 0
    diff_lines: int = 0
    #: ces chiffres sont le diff entier de la branche de son objectif face à sa base (ADR 0274) : ils remplacent,
    #: au lieu de s'ajouter
    measured: bool = False
    #: ce qu'il dit de la pull request de son objectif (``c.PULLS`` ; ``None`` : inchangé), et son numéro chez l'hôte
    pull: str | None = None
    pull_number: int = 0
    #: son reflet chez l'hôte (ADR 0275) : le numéro de son issue — posé une fois, puis redit comme ``number`` — ; ce
    #: que l'hôte en dit (``ISSUE_STATES`` du port ; ``None`` : rien de neuf) et quand il dit l'avoir fermée : un fait
    #: arrivé, daté ; et, quand c'est là-bas qu'on le rouvre, s'il redevient proposé (il venait d'un inconnu)
    issue: int = 0
    issue_state: str | None = None
    issue_at: int = 0
    reproposed: bool = False
    #: ce qu'on en dit (la raison d'un ticket écarté, le commentaire d'une validation) : entre dans son fil
    note: Content | None = None
    author: str = c.BY_SELF
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class ItemNoted(Payload):
    """Une note dans le fil d'un élément. Sur un ticket, une note à elle peut avoir une sorte (ADR 0270) : sa
    question, son plan (``small`` : elle le juge petit) — un fait de son parcours (``tickets.noted``)."""

    project: int
    list_name: str
    key: str
    text: Content
    kind: str = ""
    small: bool = False
    #: un commentaire fait chez l'hôte (``author`` : ``host``, ADR 0275) : l'heure où il a été écrit là-bas (µs) et
    #: son numéro là-bas — il n'entre dans le fil qu'une fois, et deux commentaires de la même seconde y entrent
    #: tous les deux (ADR 0278)
    host_at: int = 0
    host_id: int = 0
    author: str = c.BY_SELF
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


_SUBJECTS = ("owner", "about", "by", "person", INHERITED)
LIST_SET = PROJECTS.event("list_set", ListSet, content=("title",), subjects=_SUBJECTS)
ITEM_ADDED = PROJECTS.event("item_added", ItemAdded, content=("title", "text", "link"), subjects=_SUBJECTS)
ITEM_CHANGED = PROJECTS.event("item_changed", ItemChanged, content=("title", "text", "link", "note"),
                              subjects=_SUBJECTS)
ITEM_NOTED = PROJECTS.event("item_noted", ItemNoted, content=("text",), subjects=("owner", "about", "by", INHERITED))
#: ce qui fait bouger une liste : ce qu'attend un déclencheur ``item:<liste>`` (le processus ``projects.stirs``)
MOVES = (ITEM_ADDED, ITEM_CHANGED, ITEM_NOTED)


# ── Écrire : les seuls endroits qui font un brouillon ─────────────────────


def _about(p: Project) -> dict[str, Any]:
    return {"owner": p.owner, "about": p.about, "read_about": p.read_about}


def _about_item(p: Project, item: Item) -> dict[str, Any]:
    """Les sujets de ce qui s'écrit sur un élément : ceux du projet, et — pour l'oubli seulement — ceux de ses
    lectures, qui a ouvert l'élément et qui y agit (``inherited_on``, ADR 0272)."""
    return {"owner": p.owner, "about": p.about, INHERITED: inherited_on(p, item)}


def _opt(text: str, level: int) -> Content | None:
    return Content.of(text.strip(), level=level) if (text or "").strip() else None


def dedupe_key(project: int, name: str, key: str) -> str:
    """La clé de dédoublonnage d'un ajout : ``projet:liste:clé``."""
    return f"{project}:{name}:{key}"


def adding(p: Project, name: str, key: str, title: str, *, text: str = "", status: str = "",
           actor: str = c.ACTOR_SELF, person: str = "", link: str = "", objective: int = 0, kind: str = "",
           priority: str = c.NORMAL, proposed: bool = False, author: str = c.BY_SELF, by: str = "",
           origin: int = 0, level: int = 0, inherited: Iterable[str] = (), issue: int = 0) -> Draft[Any]:
    """Le brouillon d'un ajout — le seul endroit qui en fait un : sa clé de dédoublonnage y est toujours.

    Une demande d'un autre projet (ADR 0271) dit en plus l'objectif d'où elle part (``origin``), le niveau de ce
    qu'écrit le demandeur (``level`` : le ticket s'écrit au plus haut des deux) et ses personnes (``inherited``) —
    elles rejoignent ``read_about``, pour l'oubli seulement (ADR 0262) : de qui parle ce projet ne bouge pas."""
    level = max(written(p), level)
    about = {**_about(p), INHERITED: tuple(dict.fromkeys((*p.read_about, *inherited)))}
    return ITEM_ADDED.draft(
        project=p.id, list_name=name, key=key, title=Content.of(clipped(title, TITLE_MAX), level=level),
        text=_opt(text, level), status=status, actor=actor, person=person, link=_opt(link, level),
        objective=objective, kind=kind, priority=priority, proposed=proposed, author=author, by=by, origin=origin,
        issue=issue, **about, dedupe_key=dedupe_key(p.id, name, key))


def changing(p: Project, item: Item, *, author: str = c.BY_SELF, by: str = "", status: str | None = None,
             title: str = "", text: str = "", link: str = "", actor: str | None = None, person: str | None = None,
             objective: int | None = None, kind: str | None = None, priority: str | None = None,
             accepted: bool = False, closed: str | None = None, note: str = "", dedupe_key: str | None = None,
             **steps: Any) -> Draft[Any]:
    """Le brouillon d'un changement, parti du statut qu'on voit (``was``). ``steps`` : les faits du parcours d'un
    ticket (``taken``, ``dismissal``, ``validated``, ``plan``, ``refused``, ``stuck``, ``outgrown``, ``diff_files``,
    ``diff_lines`` — ADR 0270 ; ``measured``, ``pull``, ``pull_number`` — ADR 0274). Ce qu'il écrit est au moins du niveau de l'élément, et porte ses sujets (ADR
    0272) ; il redit son numéro et son niveau, pour l'état qui ne le garderait plus."""
    level = written_on(p, item)
    # le numéro de son issue se redit comme son numéro (ADR 0275) ; le poser pour la première fois passe par ``steps``
    steps.setdefault("issue", item.issue)
    return ITEM_CHANGED.draft(
        project=p.id, list_name=item.list_name, key=item.key, was=item.status, number=item.number, level=item.level,
        status=status,
        title=Content.of(clipped(title, TITLE_MAX), level=level) if title.strip() else None, text=_opt(text, level),
        link=_opt(link, level), actor=actor, person=person, objective=objective, kind=kind, priority=priority,
        accepted=accepted, closed=closed, note=_opt(note, level), author=author, by=by, **steps,
        **_about_item(p, item), **({"dedupe_key": dedupe_key} if dedupe_key else {}))


def noting(p: Project, item: Item, text: str, *, author: str = c.BY_SELF, by: str = "", kind: str = "",
           small: bool = False, host_at: int = 0, host_id: int = 0, dedupe_key: str | None = None) -> Draft[Any]:
    """Le brouillon d'une note dans le fil d'un élément — ce qu'un outil écrit pour y parler. ``kind`` : sur un
    ticket, sa question ou son plan (ADR 0270). Elle est au moins du niveau de l'élément, et porte ses sujets (ADR
    0272)."""
    return ITEM_NOTED.draft(project=p.id, list_name=item.list_name, key=item.key,
                            text=Content.of(text.strip(), level=written_on(p, item)), kind=kind, small=small,
                            host_at=host_at, host_id=host_id, author=author, by=by, **_about_item(p, item),
                            **({"dedupe_key": dedupe_key} if dedupe_key else {}))


#: ce qu'un objectif né d'un ticket garde de son plan : son texte, son critère (caractères)
OBJECTIVE_TEXT_MAX, CRITERION_MAX = 600, 1500


def validating(p: Project, item: Item, plan: str, *, author: str, by: str = "", comment: str = "",
               plan_seq: int | None = None) -> list[Draft[Any]]:
    """Les brouillons d'un plan validé (ADR 0270) — le seul endroit qui les fait : le fait sur le ticket, et
    l'objectif ponctuel qui en naît (``Objective.ticket``), son texte et son critère tirés du plan, sa consigne du
    commentaire de la validation. Un ticket qui a déjà son objectif (pris comme petit, il a dépassé sa borne) le
    garde : seule sa consigne change. ``author`` : qui valide (``BY_SELF`` : un petit ticket, sans attendre).

    La validation nomme le plan qu'elle valide (``plan_seq`` : par défaut celui qu'on voit sur le ticket ; 0 quand
    le plan s'écrit dans le même geste) : un plan réécrit entre-temps ne se valide pas à la place de celui qu'on a
    lu (ADR 0272). Ce qui en naît est au moins du niveau du ticket, et porte ses sujets. L'objectif prend le numéro
    suivant du projet : à écrire sous ``free_number``, pour qu'un ajout concurrent ne le lui prenne pas.

    Les jalons que le plan écrivait en texte naissent avec l'objectif (ADR 0273 : ``tickets.plan_steps``), dans le
    même lot — donc sous la même garde, au même niveau et avec les mêmes sujets ; elle dira comment chacun est
    rempli, et pourra les affiner à sa première exécution. Validé par une personne, ils sont à cette personne (ADR
    0278, ``Milestone.agreed``) : elle peut alors seulement leur donner une vérification, jamais les retirer ni les
    réécrire. Un ticket qui garde son objectif garde ses jalons."""
    level = written_on(p, item)
    named = item.plan_seq if plan_seq is None else plan_seq
    brief = _opt(comment, level)
    about = _about_item(p, item)
    # sur un projet qui passe par des pull requests, le ticket validé attend la sienne (ADR 0274)
    via = {"pull": c.PULL_AWAITED} if p.flow == c.FLOW_PR else {}
    held_by = objective_at(p, item.objective) if item.objective else None
    if held_by is not None and held_by.ticket == item.number and held_by.status in (c.OPEN, c.BLOCKED):
        drafts = [changing(p, item, author=author, by=by, validated=True, plan=named, note=comment, **via)]
        if brief is not None:
            drafts.append(OBJECTIVE_CHANGED.draft(project=p.id, objective=item.objective, brief=brief, by=by, **about))
        return drafts
    head, rest = tickets.plan_parts(plan)
    number = p.objective_seq + 1
    text = phrase("projects.tickets.objective.text", number=item.number, plan=clipped(head, OBJECTIVE_TEXT_MAX))
    criterion = clipped(rest, CRITERION_MAX) or phrase("projects.tickets.objective.done_when", number=item.number)
    writer_ = {c.BY_SELF: "self", c.BY_OPERATOR: "operator"}.get(author, "owner")
    return [
        changing(p, item, author=author, by=by, validated=True, plan=named, objective=number, note=comment, **via),
        OBJECTIVE_ADDED.draft(project=p.id, objective=number, text=Content.of(text, level=level), kind=c.ONCE,
                              author=writer_, by=by, done_when=Content.of(criterion, level=level), ticket=item.number,
                              brief=brief, **about),
        # validé par une personne, ses jalons sont à elle (ADR 0278) : en exécution, ils ne se défont plus
        *milestones.posed(p, number, (milestones.Spec(x) for x in tickets.plan_steps(plan)), level=level,
                          inherited=about[INHERITED], author="self", agreed=author != c.BY_SELF),
    ]


def free_number(p: Project, item: Item) -> Guard | None:
    """La garde d'une validation qui fait naître un objectif (ADR 0272) : le numéro qu'elle lui donne — le suivant
    du projet, lu sur un état qui a pu vieillir — est encore libre au moment d'écrire. Sans elle, un objectif ajouté
    entre-temps prendrait ce numéro, le réducteur renuméroterait celui du ticket, et le ticket pointerait sur
    l'objectif d'un autre. ``None`` : le ticket garde l'objectif qu'il a déjà."""
    held_by = objective_at(p, item.objective) if item.objective else None
    if held_by is not None and held_by.ticket == item.number and held_by.status in (c.OPEN, c.BLOCKED):
        return None
    key = (p.id, p.objective_seq + 1)
    return Guard("numéro d'objectif libre", predicate=lambda view, k=key: view.get(c.OBJECTIVE_STATUS(k)) == "")


def not_validated(why: str, number: int) -> str:
    """Le refus d'une validation, en mots (``validation_refusal``)."""
    if why == "forgotten":
        return phrase("projects.tickets.refused.forgotten", number=number)
    if why == "full":
        return phrase("projects.tickets.refused.full", number=number)
    return phrase("projects.tickets.refused.no_plan", number=number)


def validation_refusal(p: Project, item: Item, plan: str) -> str:
    """Pourquoi ce plan ne se valide pas (``no_plan``, ``forgotten``, ``full``), ou ``""``."""
    if item.list_name != c.TICKETS or item.status != c.STAGE_VALIDATION:
        return "no_plan"
    if not plan.strip():
        return "forgotten"
    if not item.objective and open_objectives(p) >= OBJECTIVES_KEPT:
        return "full"
    return ""


def list_setting(p: Project, name: str, *, title: str = "", opened: Iterable[str] = (), closed: Iterable[str] = (),
                 actor: str = c.ACTOR_SELF, person: str = "", author: str = c.BY_SELF, by: str = "") -> Draft[Any]:
    """Le brouillon d'une liste créée ou réglée."""
    return LIST_SET.draft(project=p.id, name=name, title=_opt(title, written(p)), open=tuple(opened),
                          closed=tuple(closed), actor=actor, person=person, author=author, by=by, **_about(p))


def changes_nothing(draft: Draft[Any], item: Item) -> bool:
    """Ce changement ne changerait rien à l'élément qu'on voit."""
    return changed(item, draft.data, 0, 0) is None


# ── Réducteurs ────────────────────────────────────────────────────────────


def _moved(s: ProjectsState, e: Any, p: Project, item: Item, author: str) -> ProjectsState:
    """Ce qui bouge dans une liste est ce qu'attend peut-être un objectif du projet (``item:<liste>``, ADR 0265) —
    quand ce n'est pas elle qui a écrit. Le détail d'une cause est un numéro ou une clé, jamais un texte."""
    if author in (c.BY_SELF, c.BY_HOST):
        return s  # ce qu'un inconnu écrit chez l'hôte ne déclenche aucun objectif (ADR 0275)
    detail = f"#{item.number}" if item.number else item.key
    return hear_if_listening(s, e, triggers.item_key(item.list_name), detail, p.id)


@PROJECTS.reducer(LIST_SET)
def _list_set(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or d.name == c.TICKETS or not triggers.NAME.fullmatch(d.name or ""):
        return s  # la liste des tickets ne se règle pas : elle n'a pas de statuts posés à la main
    b = p.board
    old = next((x for x in b.lists if x.name == d.name), None)
    opened, closed = statuses_of(d.open, d.closed)
    actor = d.actor if d.actor in c.ACTORS else c.ACTOR_SELF
    title_ref = (d.title.ref or "") if d.title is not None else (old.title_ref if old is not None else "")
    lst = Listing(d.name, title_ref, opened, closed, actor, d.person if actor == c.ACTOR_PERSON else "",
                  old.at if old is not None else e.at)
    lists = tuple(lst if x.name == d.name else x for x in b.lists) if old is not None else (*b.lists, lst)
    return with_project(s, replace(p, board=replace(b, lists=lists)))


@PROJECTS.reducer(ITEM_ADDED)
def _item_added(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not addable(d):
        return s
    b = p.board
    if held(b, d.list_name, d.key) is not None:
        return s  # un doublon passé hors de sa clé de dédoublonnage : la projection l'ignore aussi
    ticket = d.list_name == c.TICKETS
    number = b.ticket_seq + 1 if ticket else 0
    item = added(d, e.at, e.seq, number)
    # un élément arrive dans une liste jamais réglée : elle naît avec les statuts par défaut
    lists = b.lists if listing(b, d.list_name) is not None else (*b.lists, Listing(d.list_name, at=e.at))
    b = replace(b, lists=lists, counts=_counted(b.counts, item.list_name, item.status, 1),
                ticket_seq=max(b.ticket_seq, number), items=kept((*b.items, item)))
    p = replace(p, board=b)
    if d.author == c.BY_HOST:  # venu de l'hôte : compté dans sa journée (ADR 0278)
        since, count = hosted_day(p, e.at)
        p = replace(p, hosted_since=since or e.at, hosted_count=count + 1)
    s = with_project(s, p)
    if c.asking_project(d.author):
        # une demande fait passer un texte du demandeur vers ce projet : ce qu'il en écrira ensuite — une note, un
        # plan, l'objectif qui en naît, ses comptes rendus — doit être atteint par l'oubli des personnes du demandeur
        # (ADR 0272, la règle de 0262 dans l'autre sens). Elles rejoignent ``read_about``, puis celui de ses lecteurs ;
        # ``about`` ne bouge pas : personne n'entend davantage
        own = (p.owner, *p.about)
        poured = tuple(dict.fromkeys(x for x in (*p.read_about, *d.read_about) if x and x not in own))
        if poured != p.read_about:
            p = replace(p, read_about=poured)
            s = spread_confidentiality(with_project(s, p), p.id)
            p = s.projects[p.id]
    # ouvert par un autre projet, c'est une demande que ce projet suit (ADR 0271)
    s = asks.born(s, e, p, item, d.origin)
    if d.author == c.BY_SELF and awaits_her(item):
        # un ticket qu'elle vient d'ouvrir elle-même attend qu'elle le traite (ADR 0280) : c'est ce qu'attend
        # l'objectif qui traite les tickets — sans cela ceux de son propre audit n'étaient jamais repris. Ses autres
        # gestes (changer, noter) n'éveillent toujours rien : son propre travail ne se relance pas
        return hear_if_listening(s, e, triggers.item_key(c.TICKETS), f"#{item.number}", p.id)
    return _moved(s, e, p, item, d.author)


@PROJECTS.reducer(ITEM_CHANGED)
def _item_changed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not addable(d):
        return s
    b = p.board
    old = held(b, d.list_name, d.key)
    base = old if old is not None else unknown(d)
    new = changed(base, d, e.at, e.seq)
    if new is None:
        return s
    counts = b.counts
    if new.status != base.status:
        counts = _counted(_counted(counts, new.list_name, base.status, -1), new.list_name, new.status, 1)
    items = (*(x for x in b.items if x is not old), new)  # touché en dernier
    p = replace(p, board=replace(b, counts=counts, items=kept(items)))
    if new.issue and not base.issue:  # son issue a son numéro : sa publication n'est plus à faire (ADR 0275)
        p = issue_settled(p, new.number, MOVE_PUBLISH)
    if (bool(new.closed), new.issue_state) != (bool(base.closed), base.issue_state):
        # son état a changé, ici ou chez l'hôte : ce qui devait le porter là-bas est fait, ou n'a plus lieu d'être
        p = issue_settled(p, new.number, MOVE_CLOSE, MOVE_REOPEN)
    s = with_project(s, p)
    # le projet qui l'a demandé suit son étape, et sa fermeture le réveille (ADR 0271)
    return _moved(asks.followed(s, e, p, new, d.note is not None), e, p, new, d.author)


@PROJECTS.reducer(ITEM_NOTED)
def _item_noted(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    # un commentaire de l'hôte n'entre qu'une fois (ADR 0275) : le repère avance sur tout commentaire posé au
    # journal, même quand sa note ne se compte pas — son heure là-bas, et les numéros entrés à cette seconde-là
    # (ADR 0278)
    if d.host_at > p.remarks_at:
        p = replace(p, remarks_at=d.host_at, remarks_ids=(d.host_id,) if d.host_id else ())
        s = with_project(s, p)
    elif d.host_at and d.host_at == p.remarks_at and d.host_id and d.host_id not in p.remarks_ids:
        p = replace(p, remarks_ids=(*p.remarks_ids, d.host_id)[-REMARK_IDS_KEPT:])
        s = with_project(s, p)
    if not addable(d):  # comme le projecteur : une note se compte même si son texte ne se lit plus
        return s
    b = p.board
    old = held(b, d.list_name, d.key)
    if old is None:  # l'état ne le garde plus : sa note est dans la projection, rien ne se compte ici
        return _moved(s, e, p, Item(d.list_name, d.key), d.author)
    new = after_note(old, d, e.at, e.seq)
    counts = b.counts
    if new.status != old.status:
        counts = _counted(_counted(counts, new.list_name, old.status, -1), new.list_name, new.status, 1)
    items = (*(x for x in b.items if x is not old), new)
    s = with_project(s, replace(p, board=replace(b, counts=counts, items=kept(items))))
    return _moved(asks.followed(s, e, p, new, False), e, p, new, d.author)


# ── La projection T0 ──────────────────────────────────────────────────────

_FACTS = ("number", "seq", "status", "actor", "person", "objective", "kind", "priority", "author", "by", "proposed",
          "accepted_at", "accepted_by", "closed", "closed_at", "closed_by", "taken_at", "asked_at", "dismissal_at",
          "plan_seq", "small", "validated_at", "validated_by", "stuck", "diff_files", "diff_lines", "outgrown",
          "pull", "pull_number", "issue", "issue_state", "issue_at", "reopened_at", "level", "at", "updated_at",
          "touched_by", "notes")
#: les faits qui sont des oui ou des non (rangés en entiers)
_FLAGS = ("proposed", "small", "stuck", "outgrown")
_COLUMNS = ("project", "list_name", "item_key", *_FACTS, "changes", "title", "body", "link", "search", "subjects")
_NOTE_COLUMNS = ("seq", "project", "list_name", "item_key", "at", "author", "by", "kind", "text", "subjects")
#: une note du fil, ou ce qu'on a dit d'un changement ; sur un ticket, une note à elle qui a une sorte (ADR 0270)
NOTE, CHANGE = "note", "change"
NOTE_KINDS = (c.NOTE_QUESTION, c.NOTE_PLAN)


@functools.cache
def items_table(sfx: str = "") -> Table:
    """``project_items`` (suffixée de sa version) : une ligne par élément de liste (ADR 0101 : déclarée pour les
    deux moteurs, hors des migrations — une projection évolue par sa version)."""
    name = f"{c.REGISTRY_TABLE}{sfx}"
    return projection_table(
        name,
        Column("project", BigInteger, primary_key=True),
        Column("list_name", Key(40), primary_key=True),
        Column("item_key", Key(KEY_MAX), primary_key=True),
        Column("number", BigInteger, nullable=False),
        Column("seq", BigInteger, nullable=False),
        Column("status", Key(STATUS_MAX), nullable=False),
        Column("actor", Key(16), nullable=False),
        Column("person", Key(HANDLE_MAX), nullable=False),
        Column("objective", BigInteger, nullable=False),
        Column("kind", Key(16), nullable=False),
        Column("priority", Key(16), nullable=False),
        Column("author", Key(64), nullable=False),
        Column("by", Key(HANDLE_MAX), nullable=False),
        Column("proposed", BigInteger, nullable=False),
        Column("accepted_at", BigInteger, nullable=False),
        Column("accepted_by", Key(HANDLE_MAX), nullable=False),
        Column("closed", Key(16), nullable=False),
        Column("closed_at", BigInteger, nullable=False),
        Column("closed_by", Key(HANDLE_MAX), nullable=False),
        Column("taken_at", BigInteger, nullable=False),
        Column("asked_at", BigInteger, nullable=False),
        Column("dismissal_at", BigInteger, nullable=False),
        Column("plan_seq", BigInteger, nullable=False),
        Column("small", BigInteger, nullable=False),
        Column("validated_at", BigInteger, nullable=False),
        Column("validated_by", Key(HANDLE_MAX), nullable=False),
        Column("stuck", BigInteger, nullable=False),
        Column("diff_files", BigInteger, nullable=False),
        Column("diff_lines", BigInteger, nullable=False),
        Column("outgrown", BigInteger, nullable=False),
        Column("pull", Key(16), nullable=False),
        Column("pull_number", BigInteger, nullable=False),
        Column("issue", BigInteger, nullable=False),
        Column("issue_state", Key(16), nullable=False),
        Column("issue_at", BigInteger, nullable=False),
        Column("reopened_at", BigInteger, nullable=False),
        Column("level", BigInteger, nullable=False),
        Column("at", BigInteger, nullable=False),
        Column("updated_at", BigInteger, nullable=False),
        Column("touched_by", Key(64), nullable=False),
        Column("notes", BigInteger, nullable=False),
        Column("changes", LongText, nullable=False),
        Column("title", LongText, nullable=False),
        Column("body", LongText, nullable=False),
        Column("link", LongText, nullable=False),
        Column("search", LongText, nullable=False),
        Column("subjects", LongText, nullable=False),
        Index(f"{name}_status", "project", "list_name", "status", "updated_at"),
        Index(f"{name}_number", "project", "list_name", "number"),
        Index(f"{name}_issue", "project", "issue"),
    )


@functools.cache
def notes_table(sfx: str = "") -> Table:
    """``project_item_notes`` : une ligne par note du fil d'un élément (l'événement qui l'a écrite)."""
    name = f"{c.REGISTRY_NOTES_TABLE}{sfx}"
    return projection_table(
        name,
        Column("seq", BigInteger, primary_key=True),
        Column("project", BigInteger, nullable=False),
        Column("list_name", Key(40), nullable=False),
        Column("item_key", Key(KEY_MAX), nullable=False),
        Column("at", BigInteger, nullable=False),
        Column("author", Key(64), nullable=False),
        Column("by", Key(HANDLE_MAX), nullable=False),
        Column("kind", Key(16), nullable=False),
        Column("text", LongText, nullable=False),
        Column("subjects", LongText, nullable=False),
        Index(f"{name}_item", "project", "list_name", "item_key", "seq"),
    )


@dataclass(frozen=True, slots=True)
class Entry:
    """Un élément lu de la projection : ses faits, et ses textes (vides une fois oubliés)."""

    item: Item
    title: str = ""
    body: str = ""
    link: str = ""


@dataclass(frozen=True, slots=True)
class ThreadNote:
    """Une note du fil d'un élément : quand, qui, sa sorte (``note``, ``change``), son texte."""

    seq: int
    at: int
    author: str
    by: str
    kind: str
    text: str


def _text(content: Content | None) -> str:
    return (content.text or "") if content is not None else ""


def _subjects(d: Any) -> str:
    """Les sujets d'une ligne, entre barres (``|user_7|name:alice|``) : l'oubli d'un seul d'entre eux la vide."""
    keys = sorted({k for k in (d.owner, *d.about, *d.read_about, d.by, getattr(d, "person", "") or "") if k})
    return "|" + "|".join(keys) + "|"


def _merged(old: str, new: str) -> str:
    keys = sorted({k for k in (*old.split("|"), *new.split("|")) if k})
    return "|" + "|".join(keys) + "|"


def _search(key: str, title: str, link: str) -> str:
    """Ce qu'une recherche compare : la clé, le titre et la référence, repliés (``kernel.text.fold``)."""
    return fold(" ".join(x for x in (key, title, link) if x))


def _values(item: Item) -> dict[str, Any]:
    got: dict[str, Any] = {name: getattr(item, name) for name in _FACTS}
    got.update({name: int(getattr(item, name)) for name in _FLAGS})
    got["changes"] = json.dumps([[x.at, x.by, x.what] for x in item.changes], ensure_ascii=False)
    return got


def _entry(row: Sequence[Any]) -> Entry:
    got = dict(zip(_COLUMNS, row, strict=True))
    try:
        changes = tuple(Change(int(at), str(by), str(what)) for at, by, what in json.loads(got["changes"] or "[]"))
    except (ValueError, TypeError):
        changes = ()
    facts = {name: got[name] for name in _FACTS}
    facts.update({name: bool(got[name]) for name in _FLAGS})
    return Entry(Item(list_name=got["list_name"], key=got["item_key"], changes=changes, **facts),
                 title=got["title"] or "", body=got["body"] or "", link=got["link"] or "")


def _columns(t: Table) -> list[Any]:
    return [t.c[n] for n in _COLUMNS]


def _at(t: Table, project: int, name: str, key: str) -> Any:
    return (t.c.project == project) & (t.c.list_name == name) & (t.c.item_key == key)


class Items:
    """T0 : une ligne par élément, une ligne par note de son fil — dans la transaction de l'ajout : une exécution
    relit aussitôt ce qu'elle vient d'écrire. Les règles sont celles du réducteur (``added``, ``changed``)."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(items_table(sfx))
        sql.create(notes_table(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(items_table(sfx))
        sql.drop(notes_table(sfx))

    def apply(self, sql: Sql, items: Sequence[Any], sfx: str) -> None:
        t, n = items_table(sfx), notes_table(sfx)
        for e in items:
            name = e.type.name
            if not addable(e.data):
                continue
            if name == ITEM_ADDED.name:
                self._add(sql, t, e)
            elif name == ITEM_CHANGED.name:
                self._change(sql, t, n, e)
            elif name == ITEM_NOTED.name:
                self._note(sql, t, n, e)

    def _add(self, sql: Sql, t: Table, e: Any) -> None:
        d = e.data
        number = 0
        if d.list_name == c.TICKETS:  # le suivant du projet, comme le compte le réducteur
            got = sql.query(select(func.max(t.c.number)).where(t.c.project == d.project,
                                                              t.c.list_name == c.TICKETS))
            number = int((got[0][0] if got else 0) or 0) + 1
        item = added(d, e.at, e.seq, number)
        title, link = _text(d.title), _text(d.link)
        insert_ignore(sql, t, {"project": d.project, "list_name": d.list_name, "item_key": d.key, **_values(item),
                               "title": title, "body": _text(d.text), "link": link,
                               "search": _search(d.key, title, link), "subjects": _subjects(d)})

    def _change(self, sql: Sql, t: Table, n: Table, e: Any) -> None:
        d = e.data
        where = _at(t, d.project, d.list_name, d.key)
        rows = sql.query(select(*_columns(t)).where(where))
        if not rows:
            return
        old = _entry(rows[0])
        new = changed(old.item, d, e.at, e.seq)
        if new is None:
            return
        title = _text(d.title) if d.title is not None else old.title
        link = _text(d.link) if d.link is not None else old.link
        subjects = _merged(str(rows[0][_COLUMNS.index("subjects")] or ""), _subjects(d))
        sql.execute(update(t).where(where).values(
            **_values(new), title=title, body=_text(d.text) if d.text is not None else old.body, link=link,
            search=_search(d.key, title, link), subjects=subjects))
        if d.note is not None:
            self._thread(sql, n, e, CHANGE, _text(d.note), subjects)

    def _note(self, sql: Sql, t: Table, n: Table, e: Any) -> None:
        d = e.data
        where = _at(t, d.project, d.list_name, d.key)
        rows = sql.query(select(*_columns(t)).where(where))
        if not rows:
            return
        sql.execute(update(t).where(where).values(**_values(after_note(_entry(rows[0]).item, d, e.at, e.seq))))
        subjects = _merged(str(rows[0][_COLUMNS.index("subjects")] or ""), _subjects(d))
        self._thread(sql, n, e, d.kind if d.kind in NOTE_KINDS else NOTE, _text(d.text), subjects)

    def _thread(self, sql: Sql, n: Table, e: Any, kind: str, text: str, subjects: str) -> None:
        """Une ligne du fil. ``subjects`` : ceux de la note et ceux de l'élément — l'oubli d'une personne de
        l'élément (celles d'une demande) atteint ce qu'on a écrit dessus ensuite (ADR 0272)."""
        d = e.data
        insert_ignore(sql, n, dict(zip(_NOTE_COLUMNS, (
            e.seq, d.project, d.list_name, d.key, e.at, d.author, d.by, kind, text, subjects), strict=True)))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        """L'oubli d'une personne vide les textes de ce qui la concerne : l'élément, son numéro et son statut
        restent (les comptes de l'état aussi), plus son titre, son texte, sa référence ni ses notes."""
        t, n = items_table(sfx), notes_table(sfx)
        mark = f"|{subject}|"
        sql.execute(update(t).where(func.instr(t.c.subjects, mark) > 0)
                    .values(title="", body="", link="", search=""))
        sql.execute(update(n).where(func.instr(n.c.subjects, mark) > 0).values(text=""))


# v2 : les faits du parcours d'un ticket (ADR 0270), une colonne chacun ; la sorte d'une note (sa question, son plan)
# v3 : le niveau d'un élément et le fait qu'il a dépassé sa borne (ADR 0272) ; une note porte les sujets de son élément
# v5 : son reflet chez l'hôte (ADR 0275) — le numéro de son issue, ce que l'hôte en dit, sa dernière réouverture
# v6 : la forme ne change pas, la règle si (ADR 0280) — un ticket qu'elle ouvre elle-même naît « en analyse »
PROJECTS.projector(c.REGISTRY_TABLE, version=6, tier=Tier.T0, types=[ITEM_ADDED, ITEM_CHANGED, ITEM_NOTED])(Items)


# ── Lire la projection ────────────────────────────────────────────────────


#: pourquoi les textes d'un élément ne se disent pas à qui lit (``veiled``) : un ticket proposé, pas encore
#: accepté ; un élément d'un niveau que l'audience n'entend pas
PROPOSED_VEIL, LEVEL_VEIL = "proposed", "level"


@dataclass(frozen=True, slots=True)
class Reader:
    """Qui lit le registre d'un projet, et ce que ses éléments lui laissent lire (ADR 0272).

    - Une **exécution** (``RUN``) lit tout ce qui est accepté ; un ticket encore proposé ne lui dit qu'une ligne,
      sans titre ni texte : ce n'est pas à elle tant que le propriétaire ne l'a pas accepté.
    - En **conversation**, le titre, le texte et les notes d'un élément ne se disent qu'à qui entend son niveau
      (``level`` : le plus haut que cette audience entend de ce projet) ; le texte d'une demande d'un autre projet
      encore proposée, qu'à qui peut la trancher (``settles``)."""

    level: int = int(Sensitivity.CONFIDENCE)
    settles: bool = False
    run: bool = False


#: une exécution du projet : elle lit à tous les niveaux, sauf ce qui n'est pas encore accepté
RUN = Reader(run=True)
#: l'opérateur, dans la console : tout
ALL = Reader(settles=True)


def may_read(audience: Any, kind: str, frame: Any = None) -> bool:
    """Seulement devant qui une ligne d'accès laisse lire le détail d'un projet vivant qui a un registre (ADR 0133 :
    le piloter au moins en lecture seule) ; sans ce qu'elle vit, non."""
    if frame is None:
        return False
    s: ProjectsState = frame.state("projects")
    return any(reads(p, audience, kind, frame) for p in s.projects.values() if live(p) and p.board.counts)


def hears(p: Project, person: str, aud: Any) -> bool:
    """Le détail de ce projet peut-il s'entendre ici (la règle de « TES PROJETS ») ?"""
    return hearable(p.about, written(p), person, aud.level, aud.witness_level, aud.private_ok)


def reader_of(frame: Frame, p: Project, person: str, aud: Any) -> Reader:
    """Ce que la personne en face peut lire du registre de ce projet (ADR 0272) : le plus haut niveau qu'elle en
    entend — la règle de « TES PROJETS », niveau par niveau —, et si elle peut trancher ses tickets."""
    heard = [int(lvl) for lvl in Sensitivity
             if hearable(p.about, int(lvl), person, aud.level, aud.witness_level, aud.private_ok)]
    return Reader(level=max(heard, default=-1), settles=settles(frame, p, person))


def settles(frame: Frame, p: Project, person: str) -> bool:
    """Qui accepte ou écarte un ticket, valide ou refuse son plan : le propriétaire du projet, ou qui s'occupe
    d'elle."""
    return bool(person) and (person == p.owner or bool(frame.get(identity_c.IS_OWNER(person))))


def frames(frame: Frame, p: Project, person: str) -> bool:
    """Qui change le cadre d'un projet — son titre, son mode, son rythme, ce qui sort, ses outils, son dépôt,
    l'archiver, le restaurer : son propriétaire (la personne pour qui il est fait), ou qui s'occupe d'elle. La règle de
    qui tranche (``tracker.settles``) : piloter un projet ne suffit pas."""
    return settles(frame, p, person)


def veiled(reader: Reader, item: Item) -> str:
    """Pourquoi les textes de cet élément ne se disent pas à qui lit (``PROPOSED_VEIL``, ``LEVEL_VEIL``), ou
    ``""`` : il les lit."""
    if item.list_name == c.TICKETS and item.status == c.STAGE_PROPOSED:
        # ce qu'un autre projet, ou un inconnu chez l'hôte (ADR 0275), a écrit ne se lit que par qui peut le trancher
        outside = c.asking_project(item.author) or item.author == c.BY_HOST
        if reader.run or (outside and not reader.settles):
            return PROPOSED_VEIL
    return LEVEL_VEIL if item.level > reader.level else ""


def _legible(t: Table, reader: Reader) -> Any:
    """Les lignes dont ce lecteur lit les textes (``veiled``, en SQL) : une recherche ne compare que celles-là —
    trouver un mot dans un titre qu'on ne peut pas lire serait déjà le lire."""
    proposed = (t.c.list_name == c.TICKETS) & (t.c.status == c.STAGE_PROPOSED)
    legible = t.c.level <= reader.level
    if reader.run:
        return legible & not_(proposed)
    if not reader.settles:
        return legible & not_(proposed & (t.c.author.like(f"{c.BY_PROJECT}:%") | (t.c.author == c.BY_HOST)))
    return legible


def entry(store: Any, project: int, name: str, key: str) -> Entry | None:
    """Un élément par sa clé."""
    if store is None or not key:
        return None
    t = items_table()
    rows = store.query_mind(select(*_columns(t)).where(_at(t, project, name, key)))
    return _entry(rows[0]) if rows else None


def ticket(store: Any, project: int, number: int) -> Entry | None:
    """Un ticket par son numéro."""
    if store is None or number <= 0:
        return None
    t = items_table()
    rows = store.query_mind(select(*_columns(t)).where(
        t.c.project == project, t.c.list_name == c.TICKETS, t.c.number == number))
    return _entry(rows[0]) if rows else None


def by_issue(store: Any, project: int, issue: int) -> Entry | None:
    """Le ticket dont c'est l'issue chez l'hôte (ADR 0275)."""
    if store is None or issue <= 0:
        return None
    t = items_table()
    rows = store.query_mind(select(*_columns(t)).where(
        t.c.project == project, t.c.list_name == c.TICKETS, t.c.issue == issue))
    return _entry(rows[0]) if rows else None


def find(store: Any, project: int, name: str, said: str) -> Entry | None:
    """L'élément qu'on désigne : un ticket par son numéro (« 12 », « #12 »), tout élément par sa clé."""
    raw = (said or "").strip()
    number = raw.lstrip("#").strip()
    if name == c.TICKETS and number.isdecimal():
        return ticket(store, project, int(number))
    return entry(store, project, name, slug(raw))


def _filtered(t: Table, project: int, name: str, statuses: Sequence[str], actor: str, search: str,
              reader: Reader = ALL) -> Any:
    query = (t.c.project == project) & (t.c.list_name == name)
    if statuses:
        query &= t.c.status.in_(list(statuses))
    if actor:
        query &= t.c.actor == actor
    if search.strip():  # une recherche ne compare que les textes que ce lecteur peut lire (ADR 0272)
        query &= (func.instr(t.c.search, fold(search.strip())) > 0) & _legible(t, reader)
    return query


def page(store: Any, project: int, name: str, *, statuses: Sequence[str] = (), actor: str = "", search: str = "",
         limit: int = PAGE, offset: int = 0, reader: Reader = ALL) -> list[Entry]:
    """Une page d'une liste, les derniers touchés d'abord."""
    if store is None:
        return []
    t = items_table()
    query = select(*_columns(t)).where(_filtered(t, project, name, statuses, actor, search, reader))
    return [_entry(r) for r in store.query_mind(
        query.order_by(t.c.updated_at.desc(), t.c.seq.desc()).limit(limit).offset(max(0, offset)))]


def total(store: Any, project: int, name: str, *, statuses: Sequence[str] = (), actor: str = "",
          search: str = "", reader: Reader = ALL) -> int:
    """Combien d'éléments cette lecture trouve, toutes pages confondues."""
    if store is None:
        return 0
    t = items_table()
    rows = store.query_mind(select(func.count()).select_from(t).where(
        _filtered(t, project, name, statuses, actor, search, reader)))
    return int(rows[0][0]) if rows else 0


def moved(store: Any, project: int, since: int, limit: int) -> list[Entry]:
    """Ce qu'un autre qu'elle a touché depuis ``since`` (un ajout, un changement, une note), le plus récent
    d'abord."""
    if store is None:
        return []
    t = items_table()
    return [_entry(r) for r in store.query_mind(select(*_columns(t)).where(
        t.c.project == project, t.c.updated_at > since, t.c.touched_by != c.BY_SELF)
        .order_by(t.c.updated_at.desc(), t.c.seq.desc()).limit(limit))]


def oldest_open(store: Any, project: int, board: Board, limit: int, actor: str = c.ACTOR_SELF) -> list[Entry]:
    """Les éléments ouverts dont ``actor`` a la main, les plus anciens d'abord, toutes listes confondues."""
    if store is None:
        return []
    t = items_table()
    names = [lst for lst in listings(board) if living(board, lst)]
    if not names:
        return []
    opened = or_(*(((t.c.list_name == lst.name) & t.c.status.not_in(list(lst.closed))) if lst.closed
                   else (t.c.list_name == lst.name) for lst in names))
    return [_entry(r) for r in store.query_mind(select(*_columns(t)).where(
        t.c.project == project, t.c.actor == actor, opened).order_by(t.c.at, t.c.seq).limit(limit))]


def note_text(store: Any, seq: int) -> str:
    """Le texte d'une note du fil, par l'événement qui l'a écrite (le plan d'un ticket : ``Item.plan_seq``) ; vide :
    aucune, ou oubliée."""
    if store is None or seq <= 0:
        return ""
    n = notes_table()
    rows = store.query_mind(select(n.c.text).where(n.c.seq == seq))
    return str(rows[0][0] or "") if rows else ""


def note_at(store: Any, project: int, name: str, key: str, seq: int) -> ThreadNote | None:
    """Une note du fil de cet élément, par l'événement qui l'a écrite (ADR 0275 : celle qu'on choisit de publier) ;
    ``None`` : elle n'est pas dans ce fil."""
    if store is None or seq <= 0:
        return None
    n = notes_table()
    rows = store.query_mind(select(n.c.seq, n.c.at, n.c.author, n.c.by, n.c.kind, n.c.text).where(
        n.c.seq == seq, n.c.project == project, n.c.list_name == name, n.c.item_key == key))
    return ThreadNote(*rows[0]) if rows else None


def by_priority(store: Any, project: int, stages: Sequence[str], limit: int) -> list[Entry]:
    """Les tickets du projet à ces étapes, les plus prioritaires d'abord, puis les plus anciens (ADR 0270 : ce que
    lit le passage qui traite les tickets)."""
    if store is None or not stages:
        return []
    t = items_table()
    rank = case({c.URGENT: 0, c.HIGH: 1, c.NORMAL: 2}, value=t.c.priority, else_=3)
    return [_entry(r) for r in store.query_mind(select(*_columns(t)).where(
        t.c.project == project, t.c.list_name == c.TICKETS, t.c.status.in_(list(stages)))
        .order_by(rank, t.c.at, t.c.seq).limit(limit))]


def thread(store: Any, project: int, name: str, key: str, limit: int = THREAD_SHOWN) -> list[ThreadNote]:
    """Le fil d'un élément, de la plus ancienne note à la plus récente (les ``limit`` dernières)."""
    if store is None:
        return []
    n = notes_table()
    rows = store.query_mind(select(n.c.seq, n.c.at, n.c.author, n.c.by, n.c.kind, n.c.text).where(
        n.c.project == project, n.c.list_name == name, n.c.item_key == key).order_by(n.c.seq.desc()).limit(limit))
    return [ThreadNote(*r) for r in reversed(rows)]


# ── Ses mots ──────────────────────────────────────────────────────────────


def status_words(name: str, status: str) -> str:
    """Un statut en mots : l'étape d'un ticket, un statut par défaut d'une liste, sinon le mot réglé tel quel."""
    words = family("projects.tracker.stages") if name == c.TICKETS else family("projects.tracker.statuses")
    return words.get(status, status)


def read_status(lst: Listing, said: str) -> str | None:
    """Le statut de cette liste qu'on désigne — par son code ou par son mot, sans casse ni accents ; ``None`` : ce
    n'en est pas un."""
    wanted = fold(" ".join((said or "").split()))
    for status in (*lst.open, *lst.closed):
        if wanted in (fold(status), fold(status_words(lst.name, status))):
            return status
    return None


def statuses_said(lst: Listing) -> str:
    return ", ".join(status_words(lst.name, st) for st in (*lst.open, *lst.closed))


def list_title(lst: Listing, texts: Mapping[str, str]) -> str:
    """Le titre d'une liste : celui qu'on lui a donné, sinon son nom."""
    if lst.name == c.TICKETS:
        return phrase("projects.tracker.tickets")
    return texts.get(lst.title_ref, "") or lst.name


def by_words(frame: Frame, by: str) -> str:
    """Qui, tel qu'un changement le garde (``writer``) : elle (« toi »), un autre projet, l'opérateur, sinon une
    personne par son prénom."""
    if by == c.BY_SELF:
        return phrase("projects.tracker.by.self")
    if by.startswith(f"{c.BY_PROJECT}:"):
        return phrase("projects.tracker.by.project", id=by.partition(":")[2])
    if by == c.BY_OPERATOR:
        return phrase("projects.tracker.by.operator")
    if by == c.BY_HOST:
        return phrase("projects.tracker.by.host")
    name = identity_c.person_name(frame, by) if by and by != c.BY_PERSON else ""
    return name or phrase("projects.tracker.by.someone")


def who_words(frame: Frame, author: str, by: str = "") -> str:
    """Qui a écrit, en mots, à partir de son rôle et de sa personne."""
    if author in (c.BY_PERSON, c.BY_OPERATOR):
        name = identity_c.person_name(frame, by) if by else ""
        return name or by_words(frame, author)
    return by_words(frame, author)


def actor_words(frame: Frame, item: Item) -> str:
    """Qui agit sur un élément, en mots."""
    if item.actor == c.ACTOR_OWNER:
        return caretaker(frame)
    if item.actor == c.ACTOR_PERSON:
        return identity_c.person_name(frame, item.person) or phrase("projects.tracker.by.someone")
    return phrase("projects.tracker.by.self")


def handle(item: Item) -> str:
    """Comment on désigne un élément : un ticket par son numéro, un élément de liste par sa clé."""
    return f"#{item.number}" if item.number else item.key


def counts_line(board: Board, lst: Listing, title: str) -> str:
    """Les comptes d'une liste en une ligne : « Tickets (tickets) : 2 non lu, 1 proposé, 14 traité »."""
    parts = [phrase("projects.tracker.counts.part", count=count(board, lst.name, st),
                    status=status_words(lst.name, st))
             for st in dict.fromkeys((*lst.open, *lst.closed, *(s for n, s, _ in board.counts if n == lst.name)))
             if count(board, lst.name, st)]
    return phrase("projects.tracker.counts.line", title=title, name=lst.name,
                  counts=", ".join(parts) or phrase("projects.tracker.counts.none"))


def veiled_line(frame: Frame, item: Item, why: str, reader: Reader) -> str:
    """Un élément dont les textes ne se disent pas à qui lit (``veiled``) : une ligne, sans titre ni texte."""
    if why == PROPOSED_VEIL and reader.run:
        return phrase("projects.tracker.line.proposed", number=item.number)
    if why == PROPOSED_VEIL:
        return phrase("projects.tracker.line.sealed", number=item.number, by=who_words(frame, item.author, item.by),
                      who=caretaker(frame))
    return phrase("projects.tracker.line.withheld", handle=handle(item),
                  status=status_words(item.list_name, item.status))


def line(frame: Frame, e: Entry, reader: Reader = ALL) -> str:
    """Un élément en une ligne — son titre cité : ce qu'une personne y a écrit est une donnée. Devant qui ne peut
    pas lire ses textes (``veiled``, ADR 0272), une ligne sans titre."""
    item = e.item
    why = veiled(reader, item)
    if why:
        return veiled_line(frame, item, why, reader)
    title = clipped(e.title, TITLE_SHOWN) or phrase("projects.tracker.forgotten")
    ago = ago_words(max(0, frame.now - item.updated_at))
    status = status_words(item.list_name, item.status)
    if item.list_name == c.TICKETS:
        return phrase("projects.tracker.line.ticket", number=item.number, stage=status,
                      kind=family("projects.tracker.kinds").get(item.kind, item.kind),
                      priority=family("projects.tracker.priorities").get(item.priority, item.priority),
                      title=title, by=who_words(frame, item.author, item.by), ago=ago)
    return phrase("projects.tracker.line.item", key=item.key, status=status, title=title,
                  actor=actor_words(frame, item), ago=ago)


def change_words(name: str, what: str) -> str:
    """Un changement en mots, à partir de ses codes (``status:todo>done``, ``closed:done``, ``accepted``…)."""
    words = family("projects.tracker.changes")
    said = []
    for code in what.split(","):
        head, _, tail = code.partition(":")
        if head == "status":
            before, _, after = tail.partition(">")
            said.append(phrase("projects.tracker.changes_status", before=status_words(name, before),
                               after=status_words(name, after)))
        elif head == "closed":
            said.append(words["treated"] if tail == c.DONE else words["dismissed"])
        elif head == "priority":
            said.append(phrase("projects.tracker.changes_priority",
                               priority=family("projects.tracker.priorities").get(tail, tail)))
        elif head == "kind":
            said.append(phrase("projects.tracker.changes_kind",
                               kind=family("projects.tracker.kinds").get(tail, tail)))
        elif head == "pull":  # ce qu'il dit de la pull request de son objectif (ADR 0274)
            said.append(family("projects.tracker.pull_changes").get(tail, tail))
        elif head == "issue":  # son reflet chez l'hôte (ADR 0275) : son numéro, puis ce que l'hôte en dit
            said.append(phrase("projects.tracker.changes_issue", number=tail) if tail.isdecimal() else
                        family("projects.tracker.issue_changes").get(tail, tail))
        else:
            said.append(words.get(head, head))
    return ", ".join(said)


def detail(frame: Frame, store: Any, project: int, e: Entry, reader: Reader = ALL) -> str:
    """Un élément en détail : sa ligne, son texte, sa référence, ses derniers changements et son fil — le plan
    d'un ticket qui attend sa validation y porte son numéro, celui que la validation nomme (ADR 0272). Devant qui
    ne peut pas lire ses textes (``veiled``), sa ligne seule : ni texte, ni fil."""
    item = e.item
    lines = [line(frame, e, reader)]
    if veiled(reader, item):
        return lines[0]
    if e.body:
        lines.append(phrase("projects.tracker.detail.text", text=clipped(e.body, TEXT_MAX)))
    if e.link:
        lines.append(phrase("projects.tracker.detail.link", link=clipped(e.link, LINK_MAX)))
    if item.objective:
        lines.append(phrase("projects.tracker.detail.objective", id=item.objective))
    if item.issue:  # son reflet chez l'hôte (ADR 0275)
        lines.append(phrase("projects.tracker.detail.issue", number=item.issue,
                            state=family("projects.tracker.issue_states").get(item.issue_state, item.issue_state)))
    for change in item.changes:
        lines.append(phrase("projects.tracker.detail.change", ago=ago_words(max(0, frame.now - change.at)),
                            by=by_words(frame, change.by),
                            what=change_words(item.list_name, change.what)))
    for note in thread(store, project, item.list_name, item.key):
        said = {"ago": ago_words(max(0, frame.now - note.at)), "by": who_words(frame, note.author, note.by),
                "text": clipped(note.text, NOTE_MAX) or phrase("projects.tracker.forgotten")}
        if note.seq == item.plan_seq and item.status == c.STAGE_VALIDATION:
            lines.append(phrase("projects.tracker.detail.plan", seq=note.seq, **said))
        elif item.issue and note.author != c.BY_HOST:
            # un ticket qui a son issue chez l'hôte (ADR 0275) : chaque note dit son numéro — celui qu'on nomme pour
            # la publier (ticket_publish)
            lines.append(phrase("projects.tracker.detail.note_numbered", seq=note.seq, **said))
        else:
            lines.append(phrase("projects.tracker.detail.note", **said))
    return "\n".join(lines)


def listed(frame: Frame, store: Any, p: Project, lst: Listing, *, status: str = "", actor: str = "",
           search: str = "", number: int = 1, texts: Mapping[str, str] | None = None, reader: Reader = ALL) -> str:
    """Une page d'une liste, en mots : ses comptes, puis une ligne par élément."""
    chosen = (status,) if status else ()
    found = total(store, p.id, lst.name, statuses=chosen, actor=actor, search=search, reader=reader)
    pages = max(1, -(-found // PAGE))
    number = min(max(1, number), pages)
    rows = page(store, p.id, lst.name, statuses=chosen, actor=actor, search=search, offset=(number - 1) * PAGE,
                reader=reader)
    lines = [counts_line(p.board, lst, list_title(lst, texts or {}))]
    if not rows:
        lines.append(phrase("projects.tracker.empty"))
    lines += ["- " + line(frame, e, reader) for e in rows]
    if pages > 1:
        lines.append(phrase("projects.tracker.paged", page=number, pages=pages))
    return "\n".join(lines)


def overview(board: Board, texts: Mapping[str, str]) -> str:
    """Toutes les listes du projet et leurs comptes, une par ligne."""
    return "\n".join("- " + counts_line(board, lst, list_title(lst, texts)) for lst in listings(board))
