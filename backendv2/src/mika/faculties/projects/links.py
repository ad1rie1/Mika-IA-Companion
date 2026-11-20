"""Les liens de lecture entre projets (ADR 0257) : les règles pures.

Un projet en lit d'autres, sans jamais y écrire. Ce module dit, à partir de l'état des projets et de ce qu'on lui
passe du reste de sa vie (``World`` : qui s'occupe d'elle, qui lui est proche, les tableaux des canaux) :

- **quels projets un projet peut lire** (``refusal``, ``candidates``) : ceux du même propriétaire, et ceux qu'un autre
  propriétaire lui laisse voir par ses lignes d'accès ; jamais lui-même, jamais un projet archivé, jamais en boucle,
  ``LINKS_MAX`` au plus ;
- **qui pose un lien** (``may_link``) : le propriétaire du projet lecteur ; pour un projet à elle, quelqu'un qui
  s'occupe d'elle ;
- **ce que le lien donne** (``grant``), lu dans les lignes d'accès du projet visé pour le propriétaire du projet
  lecteur. Rien n'en est gardé dans l'état : on le relit à chaque fois, et un droit retiré coupe ce qu'il donnait dès
  l'exécution suivante ;
- **un lien suspendu** (``Reading.suspended``) : le projet visé est archivé, ou ses lignes ne le laissent plus voir.
  Le lien reste posé, il ne donne plus rien.
- **la vue de l'atelier** (``views``, ``views_workshop``, ADR 0260) : les fichiers du projet lu, quand ses lignes les
  donnent. Ce droit se relit plus souvent que le reste : à chaque appel d'un outil de l'atelier.

Les deux règles de structure que le réducteur applique lui-même — pas de boucle, ``LINKS_MAX`` — vivent à côté de lui
(``faculty.linked``, ``faculty.reaches``) ; ``refusal`` les redit à qui pose un lien, avec leur raison.

**Comment une ligne se juge hors de toute conversation.** Une ligne d'accès dit qui, par où (un canal) et quand ; une
exécution n'a ni canal ni personne en face. La lecture retenue est la plus serrée qui serve encore :

- le lien se juge **pour le propriétaire du projet lecteur** (``standing``) : une de ses propriétaires, une autre
  personne par son nom — ou elle seule, au travail, pour un projet à elle ;
- **seule une ligne qui le désigne ouvre un lien.** La ligne par défaut est faite pour qui n'est pas nommé, en
  conversation, où sa confidentialité filtre encore ce qu'elle dit ; un lien n'a pas ce filtre. Partager un
  projet, c'est y écrire une ligne ;
- un projet à elle a une situation qui existe : le canal « elle seule », sans moment. La première ligne qui la
  désigne par ce canal décide, comme au travail ;
- une personne n'a, elle, **que ce que les lignes lui donnent par tous les canaux et à tout moment**. On prend
  les lignes qui la désignent, de haut en bas, jusqu'à la première qui vaut partout et toujours : selon le canal
  et le moment, chacune pourrait décider. La plus serrée décide de chaque colonne. Si aucune ne vaut partout et
  toujours, le lien ne donne rien ;
- le tableau du canal « elle seule » serre encore le pilotage et les fichiers (``door``) : c'est par lui qu'une
  exécution arrive, et une demande passe toujours ses deux portes (ADR 0134).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    LINKS_MAX,
    Project,
    ProjectsState,
    access_of,
    live,
    reaches,
    readers_of,
)
from mika.kernel.frame import Frame
from mika.vocab.access import (
    ACCOUNT,
    AT_OWNER,
    INTERNAL,
    STEER_NO,
    STEER_RANK,
    WORK,
    Canal,
    canal_key,
    decide,
    designates,
    tighten,
    via,
)
from mika.vocab.canals import CanalRule, Canals
from mika.vocab.rights import closeness_of, rights_of

#: pourquoi un projet ne peut pas en lire un autre (les clés de ``projects.links.refused`` dans sa voix : NE PAS
#: RENOMMER) : il n'existe pas ; c'est lui-même ; il est archivé ; il le lit déjà, de près ou de loin ; son
#: propriétaire ne le lui laisse pas voir ; il lit déjà ``LINKS_MAX`` projets
UNKNOWN, ITSELF, ARCHIVED, LOOP, UNSHARED, FULL = "unknown", "itself", "archived", "loop", "unshared", "full"
#: … et pourquoi son plan ne peut pas le demander : la personne qui a demandé le projet ne peut pas le voir
HIDDEN = "hidden"


# ── Ce qu'elles lisent hors des projets ────────────────────────────────────


@dataclass(frozen=True, slots=True)
class World:
    """Ce que les règles lisent hors des projets : qui s'occupe d'elle (``keeper`` : cette personne est-elle une de
    ses propriétaires ?), qui lui est proche (``close`` : ce que lit la source « tes proches » d'une ligne), et les
    tableaux des canaux qu'un opérateur a réglés (``canals`` ; rien : les minimums vitaux)."""

    keeper: Callable[[str], bool]
    close: Callable[[str], bool] | None = None
    canals: Canals | None = None


def world_of(frame: Frame) -> World:
    """Ce que les règles lisent de ce qu'elle vit. Qui l'appelle déclare ``identity.IS_OWNER`` dans ses lectures."""
    return World(keeper=lambda person: bool(frame.get(identity_c.IS_OWNER(person))),
                 close=closeness_of(frame.env, frame), canals=rights_of(frame.env).canals)


# ── À qui est un projet ────────────────────────────────────────────────────


def owner_of(p: Project) -> str:
    """Le propriétaire d'un projet : la personne pour qui il est (un projet confié) ; vide : un projet à elle — ou un
    projet confié sans personne, qui se juge de même."""
    return (p.owner or "") if p.authority == c.USER else ""


def standing(p: Project, world: World) -> tuple[str, str]:
    """Pour qui se juge ce que lit ce projet : sa situation (``vocab.access`` : elle seule au travail, une de ses
    propriétaires, une autre personne) et, pour une autre personne, sa clé."""
    return _standing(owner_of(p), world)


def _standing(person: str, world: World) -> tuple[str, str]:
    if not person:
        return WORK, ""
    return (AT_OWNER, "") if world.keeper(person) else (ACCOUNT, person)


def may_link(p: Project, person: str, world: World) -> bool:
    """Cette personne peut-elle poser ce que lit ce projet ? Son propriétaire ; pour un projet à elle, quelqu'un qui
    s'occupe d'elle."""
    owner = owner_of(p)
    return bool(person) and (person == owner if owner else world.keeper(person))


# ── Ce que le lien donne ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Grant:
    """Ce que les lignes d'accès d'un projet donnent à un projet qui le lit : le voir, le piloter (``STEERS``), ses
    fichiers — et ce que le lecteur en reçoit."""

    see: bool = False
    steer: str = STEER_NO
    files: bool = False

    @property
    def detail(self) -> bool:
        """Ses comptes rendus, ses décisions, ses objectifs ouverts : le voir, et le piloter au moins en lecture
        seule."""
        return self.see and self.steer != STEER_NO

    @property
    def view(self) -> bool:
        """La vue de son atelier : le voir, et ses fichiers."""
        return self.see and self.files

    @property
    def ask(self) -> str:
        """Lui adresser une demande : sur l'accord de son propriétaire (``STEER_ASK``), directement
        (``STEER_EDIT``), ou pas du tout (``STEER_NO``)."""
        return self.steer if self.see and self.steer in c.CHANGES else STEER_NO


#: un lien qui ne donne rien
NOTHING = Grant()


def door(canals: Canals | None) -> CanalRule:
    """La première porte d'une exécution (ADR 0134) : la ligne du tableau du canal « elle seule » qui la désigne. Elle
    plafonne ce qu'un lien donne — par défaut, elle laisse tout."""
    alone = Canal(INTERNAL)
    table, _ = (canals or Canals()).table_of(alone)
    return decide(table.lines, table.default,
                  lambda line: designates(line.who, WORK, "") and via(line.canal, alone)).line


def _reachable(line: c.ProjectAccess) -> bool:
    """Une personne peut-elle arriver par un canal de cette ligne ? Pas par « elle seule », où personne n'est en face."""
    return not line.canal or any(canal_key(canal)[0] != INTERNAL for canal in line.canal)


def _deciding(rows: tuple[c.ProjectAccess, ...], where: str, person: str,
              close: Callable[[str], bool] | None) -> tuple[c.ProjectAccess, ...]:
    """Les lignes qui décident pour qui se juge le lien ; aucune : le lien ne donne rien (la ligne par défaut n'en
    ouvre pas). Elle seule : la première ligne qui la désigne par le canal « elle seule ». Une personne : chaque ligne
    qui la désigne, jusqu'à la première qui vaut partout et toujours — sans une telle ligne, rien."""
    if where == WORK:
        alone = Canal(INTERNAL)
        return tuple(line for line in rows if designates(line.who, WORK, "") and via(line.canal, alone))[:1]
    found: list[c.ProjectAccess] = []
    for line in rows:
        if not designates(line.who, where, person, close) or not _reachable(line):
            continue
        found.append(line)
        if not line.canal and not line.when:
            return tuple(found)
    return ()


def granted(rows: Iterable[c.ProjectAccess], where: str, person: str = "",
            close: Callable[[str], bool] | None = None, through: CanalRule | None = None) -> Grant:
    """Ce que des lignes d'accès donnent hors de toute conversation, à qui se juge le lien (``where``, ``person`` :
    ``standing``) : la plus serrée des lignes qui décident pour lui, colonne par colonne, serrée encore par la porte
    du canal « elle seule » (``through``). Sans ligne qui le désigne, ou sans le voir, rien."""
    lines = _deciding(tuple(rows), where, person, close)
    if not lines or not all(line.see for line in lines):
        return NOTHING
    steer = min((line.steer for line in lines), key=lambda level: STEER_RANK.get(level, 0))
    files = all(line.files for line in lines)
    if through is not None:
        steer, files = tighten(steer, through.steer, STEER_RANK), files and through.files
    return Grant(True, steer, files)


def _granted_to(target: Project, where: str, person: str, world: World) -> Grant:
    if not live(target):
        return NOTHING
    rows, _ = access_of(target)
    return granted(rows, where, person, world.close, door(world.canals))


def grant(reader: Project, target: Project, world: World) -> Grant:
    """Ce que ``target`` donne à ``reader`` s'il le lit : ses lignes d'accès, appliquées au propriétaire de
    ``reader``. Un projet archivé ne donne rien."""
    return _granted_to(target, *standing(reader, world), world)


# ── Quels projets un projet peut lire ──────────────────────────────────────


def refusal(s: ProjectsState, reader: Project, target: int, world: World) -> str:
    """Pourquoi ``reader`` ne peut pas se mettre à lire le projet ``target`` (vide : il le peut) : il n'existe pas,
    c'est lui-même, il est archivé, il le lit déjà de près ou de loin, ou il n'est ni du même propriétaire ni partagé
    par ses lignes d'accès."""
    t = s.projects.get(target)
    if t is None:
        return UNKNOWN
    if t.id == reader.id:
        return ITSELF
    if not live(t):
        return ARCHIVED
    if reaches(s.projects, t.id, reader.id):
        return LOOP
    if owner_of(t) != owner_of(reader) and not grant(reader, t, world).see:
        return UNSHARED
    return ""


def chosen(s: ProjectsState, reader: Project, asked: Iterable[int],
           world: World) -> tuple[tuple[int, ...], tuple[tuple[int, str], ...]]:
    """Ce que ``reader`` lira de ce qu'on demande, et ce qui est refusé avec sa raison. Un lien déjà posé reste, même
    suspendu : seul un lien nouveau se justifie. ``LINKS_MAX`` au plus."""
    kept: list[int] = []
    refused: list[tuple[int, str]] = []
    for target in dict.fromkeys(asked):
        why = "" if target in reader.reads else refusal(s, reader, target, world)
        if not why and len(kept) >= LINKS_MAX:
            why = FULL
        if why:
            refused.append((target, why))
        else:
            kept.append(target)
    return tuple(kept), tuple(refused)


def candidates(s: ProjectsState, reader: Project, world: World, seen_by: str = "") -> tuple[Project, ...]:
    """Les projets que ``reader`` peut se mettre à lire, par numéro. ``seen_by`` : seulement ceux que cette personne
    peut voir elle aussi — la liste qu'on montre à une séance de cadrage finit dans un plan, dit à qui l'a demandé."""
    found = (t for t in sorted(s.projects.values(), key=lambda t: t.id)
             if t.id not in reader.reads and not refusal(s, reader, t.id, world))
    if seen_by and seen_by != owner_of(reader):
        return tuple(t for t in found if _granted_to(t, *_standing(seen_by, world), world).see)
    return tuple(found)


def askable(s: ProjectsState, reader: Project, world: World) -> tuple[Project, ...]:
    """Les projets que le plan de ``reader`` peut demander à lire : ceux qu'il peut lire, et que la personne qui a
    demandé le projet peut voir elle aussi — son plan les nommera devant elle."""
    return candidates(s, reader, world, seen_by=reader.asked_by or "")


# ── Les liens tels qu'ils valent maintenant ────────────────────────────────


@dataclass(frozen=True, slots=True)
class Reading:
    """Un lien tel qu'il vaut maintenant : le projet lu (``None`` s'il n'existe plus) et ce que ses lignes donnent."""

    id: int
    project: Project | None
    grant: Grant

    @property
    def suspended(self) -> bool:
        """Le projet visé est archivé, ou ses lignes ne le laissent plus voir : le lien reste, il ne donne rien."""
        return self.project is None or not self.grant.see


def readings(s: ProjectsState, reader: Project, world: World) -> tuple[Reading, ...]:
    """Ce que ``reader`` lit, dans l'ordre où ses liens ont été posés, chacun avec ce qu'il donne maintenant."""
    out = []
    for target in reader.reads:
        t = s.projects.get(target)
        out.append(Reading(target, t, grant(reader, t, world) if t is not None else NOTHING))
    return tuple(out)


def readers(s: ProjectsState, target: Project, world: World) -> tuple[tuple[Project, Grant], ...]:
    """Qui lit ``target``, par numéro, et ce que chacun en reçoit maintenant."""
    return tuple((reader, grant(reader, target, world)) for reader in readers_of(s, target.id))


def views_workshop(s: ProjectsState, reader: int, target: int, world: World) -> bool:
    """Le projet ``reader`` a-t-il droit à la vue de l'atelier du projet ``target`` ? Il le lit, le lien n'est pas
    suspendu, et les lignes d'accès de ``target`` donnent ses fichiers au propriétaire de ``reader``."""
    r, t = s.projects.get(reader), s.projects.get(target)
    return r is not None and t is not None and target in r.reads and grant(r, t, world).view


def views(s: ProjectsState, reader: Project, world: World) -> tuple[int, ...]:
    """Les projets dont ``reader`` a droit à la vue de l'atelier, maintenant (ADR 0260), dans l'ordre de ses liens :
    aucun s'il est archivé. C'est ce qu'on relit au départ d'une exécution, à chaque appel d'un outil de l'atelier et
    quand on fait le ménage des vues — rien n'en est gardé."""
    return tuple(r.id for r in readings(s, reader, world) if r.grant.view) if live(reader) else ()


# ── Ce qu'un plan demande à lire ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Approved:
    """Ce que deviennent, quand on valide un plan, les projets qu'il demande à lire. ``pending`` : ceux qu'il demande
    et ne lit pas encore ; ``reads`` : toute la liste à poser (vide : rien à poser) ; ``refused`` : ceux qui ne se
    posent pas, et pourquoi ; ``denied`` : qui valide n'est pas son propriétaire, rien ne se pose."""

    pending: tuple[int, ...] = ()
    reads: tuple[int, ...] = ()
    refused: tuple[tuple[int, str], ...] = ()
    denied: bool = False

    @property
    def added(self) -> tuple[int, ...]:
        """Les liens que cette validation pose."""
        return tuple(t for t in self.reads if t in self.pending)


def approved(s: ProjectsState, p: Project, person: str, world: World) -> Approved:
    """Le plan de ``p`` est validé par ``person`` : ce qu'il demandait à lire se pose si c'est son propriétaire, et si
    chaque projet peut encore être lu. Les liens déjà posés restent."""
    pending = tuple(t for t in p.plan_reads if t not in p.reads)
    if not pending:
        return Approved()
    if not may_link(p, person, world):
        return Approved(pending=pending, denied=True)
    kept, refused = chosen(s, p, (*p.reads, *pending), world)
    return Approved(pending=pending, reads=kept if any(t in pending for t in kept) else (), refused=refused)
