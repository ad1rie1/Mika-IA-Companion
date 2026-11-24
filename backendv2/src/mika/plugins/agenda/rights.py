"""Le tableau de droits de chaque agenda (ADR 0309), sur le moteur commun (``vocab.access``, ADR 0133–0134) : des
lignes Qui × Par où × Quand, lues de haut en bas, puis la ligne par défaut, fermée ; ses colonnes : le lire, y écrire
(ajouter, modifier, supprimer), répondre à ses invitations, ce qu'elle en garde (``vocab.access.AgendaRule``).

- **Deux portes** : le propriétaire et le partage d'abord (``reach``) — un agenda sert à son propriétaire, en
  tête-à-tête, et à qui il le partage, à son niveau ; ni masqué, ni sous un compte décoché (``hers``) ; puis son
  tableau, serré par celui du canal et par le plafond de qui est en face (``vocab.rights.agenda_allowance``) : rien dans
  un salon ni pour une inconnue.
- **Le tableau par défaut** (``default_lines``) : son propriétaire, quand elle lui répond, lire, écrire et répondre avec
  son accord (elle en garde un souvenir) ; son propriétaire, quand elle prend la parole (ses rappels), lire ; elle
  seule, au travail (les invitations à préparer), lire et répondre avec accord ; personne d'autre.
- **Un partage ajoute la ligne de la personne** (``share_line``) : lire, lire ; lire et préparer, écrire aussi — sur
  l'accord du propriétaire, quoi que dise la ligne ; s'en servir, écrire et répondre selon le tableau, l'accord étant
  le sien. Le partage est aussi un plafond : « lire » n'écrit jamais, « lire et préparer » ne répond pas. Retirer le
  partage retire la ligne (``shared_table``, pour un tableau réglé ; sinon elle n'est plus dérivée).
- **Réglé** par son propriétaire (l'API par personne) ou par un opérateur (Réglages › Droits), un tableau est rangé
  dans les réglages et lu à chaque épisode (``Rights.agendas``, ``Settings.save_agenda_table``) ; sinon, celui que son
  propriétaire et ses partages donnent (``table_of``).
- **Qui donne l'accord** (``approval``) : la personne en face, sur une carte dans sa conversation ; pour un partage
  « lire et préparer », le propriétaire — dans son chat à lui (une de ses adresses), sinon la console (À valider).

Son nom désigne aussi la personne en face quand elle est une de ses propriétaires : le moteur ne lit, pour une
propriétaire, que « toi » — l'agenda du système d'une opératrice est pourtant à son nom (``as_seen``).

**D'elle-même** (lot 3b), les mêmes portes : un rappel ne se propose que si la ligne « quand elle te parle
d'elle-même » laisse lire l'agenda devant l'adresse où elle préviendrait (``audience_at`` : l'audience que l'identité
donnera à l'épisode, pour ce que le tableau en lit) ; une invitation ne se prépare que si la ligne « elle seule, au
travail » laisse y répondre (``at_work`` : personne n'écoute, ``WORKING``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.kernel.frame import Audience, Frame
from mika.plugins.agenda import AgendaParams, hers, owner, params_of
from mika.ports.agenda import DEFAULT_CALENDAR, calendar_key, split_calendar_key, system_account
from mika.vocab.access import (
    AGREE,
    ALONE,
    AT_OWNER,
    CARD,
    CLOSED_AGENDA,
    INTERNAL,
    NO,
    OWNER,
    OWNER_OK,
    PERSON,
    SELF,
    SHARE_PREPARE,
    SHARE_READ,
    SHARE_USE,
    WORK,
    AgendaRule,
    Table,
    situation,
)
from mika.vocab.episodes import Kind
from mika.vocab.ownership import best_handle, shared_with
from mika.vocab.privacy import ChannelTrust
from mika.vocab.rights import AgendaAllowance, Rights, agenda_allowance, closeness_of, rights_of

#: comment un agenda sert ici : à qui est en face (son propriétaire ; « à toi » pour une de ses propriétaires ; elle
#: seule, au travail), ou par un partage (son niveau, ``vocab.access.SHARES``)
OWNED = "proprietaire"
#: elle travaille seule : personne n'écoute (la règle de la console et de l'espace d'une personne)
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
#: ce qu'un partage ajoute, la ligne de la personne : lire ; lire et préparer, écrire aussi (sur l'accord du
#: propriétaire) ; s'en servir, écrire et répondre (sur le sien)
SHARE_COLUMNS: Mapping[str, Mapping[str, Any]] = {
    SHARE_READ: {"read": True},
    SHARE_PREPARE: {"read": True, "write": AGREE},
    SHARE_USE: {"read": True, "write": AGREE, "respond": AGREE},
}


def default_lines(holder: str) -> tuple[AgendaRule, ...]:
    """Les lignes d'un agenda dont on n'a pas réglé le tableau, à ce propriétaire (``personne:<clé>`` ; vide : à toi)."""
    who = (holder,) if holder else (OWNER,)
    return (AgendaRule(who=who, when=("conversation",), read=True, write=AGREE, respond=AGREE, keep="perso"),
            AgendaRule(who=who, when=("initiative",), read=True),
            AgendaRule(who=(SELF,), canal=(INTERNAL,), read=True, respond=AGREE))


def share_line(person: str, level: str) -> AgendaRule:
    """La ligne qu'un partage ajoute pour cette personne (``personne:<clé>``), à ce niveau."""
    return AgendaRule(who=(person,), when=("conversation",), **SHARE_COLUMNS.get(level, {}))


def shared_table(table: Table[AgendaRule], person: str, level: str | None) -> Table[AgendaRule]:
    """Un tableau réglé, une fois cette personne partagée à ce niveau (sa ligne, à la place de celle qu'elle avait,
    au-dessus de la ligne par défaut) ou son partage retiré (``None`` : sa ligne part)."""
    kept = [line for line in table.lines if tuple(line.who) != (person,)]
    if level:
        kept.append(share_line(person, level))
    return Table[AgendaRule](lines=tuple(kept), default=table.default)


def table_of(p: AgendaParams, rights: Rights, calendar: str) -> Table[AgendaRule]:
    """Le tableau de cet agenda : celui qu'on a réglé, sinon celui que son propriétaire et ses partages donnent."""
    stored = rights.agendas.get(calendar)
    if stored is not None:
        return stored
    account, _local = split_calendar_key(calendar)
    lines = default_lines(owner(p, account))
    shares = p.shares.get(calendar, {})
    return Table[AgendaRule](lines=lines + tuple(share_line(k, v) for k, v in sorted(shares.items())),
                             default=CLOSED_AGENDA)


def reach(p: AgendaParams, calendar: str, audience: Any, kind: str) -> str:
    """Par où cet agenda sert ici (la première porte) : ``OWNED``, le niveau d'un partage, ou vide (il ne sert pas).
    Son propriétaire, reconnu, en tête-à-tête — pour un agenda « à toi », une de ses propriétaires ; elle seule, au
    travail ; qui il est partagé, à son niveau. Jamais masqué, ni sous un compte décoché."""
    if not hers(p, calendar):
        return ""
    where = situation(audience, kind)
    if where == WORK:
        return OWNED
    me = shared_with(audience, kind)
    if not me:
        return ""
    account, _local = split_calendar_key(calendar)
    holder = owner(p, account)
    if holder == me or (not holder and where == AT_OWNER):
        return OWNED
    return p.shares.get(calendar, {}).get(me, "")


def as_seen(lines: Iterable[AgendaRule], audience: Any, kind: str) -> tuple[AgendaRule, ...]:
    """Les lignes telles que le moteur les lit pour qui est en face : une propriétaire n'y est désignée que par « toi »
    — son nom (``personne:<clé>``) la désigne aussi, comme pour toute personne reconnue."""
    lines = tuple(lines)
    person = getattr(audience, "person", "") or ""
    if not person or situation(audience, kind) != AT_OWNER:
        return lines
    me = PERSON + person
    return tuple(line.model_copy(update={"who": tuple(dict.fromkeys(OWNER if w == me else w for w in line.who))})
                 if me in line.who else line for line in lines)


@dataclass(frozen=True, slots=True)
class Here:
    """Ce qu'elle fait d'un agenda devant qui est en face : par où il sert (``reach``), ce que son tableau laisse
    (``allowance``), et ce qui en reste une fois le partage passé — le lire, y écrire, répondre (``POLICIES``), ce
    qu'elle en garde ; ``owner_decides`` : un partage « lire et préparer », le propriétaire donne l'accord."""

    calendar: str
    reach: str
    allowance: AgendaAllowance
    read: bool
    write: str
    respond: str
    keep: str
    owner_decides: bool = False

    @property
    def owned(self) -> bool:
        return self.reach == OWNED


def here(p: AgendaParams, rights: Rights, calendar: str, audience: Any, kind: str,
         close: Callable[[str], bool] | None = None) -> Here | None:
    """Ce qu'elle fait de cet agenda ici ; ``None`` : il ne sert pas (ni à elle, ni partagé, ni lisible)."""
    got = reach(p, calendar, audience, kind)
    if not got:
        return None
    table = table_of(p, rights, calendar)
    allowed = agenda_allowance(as_seen(table.lines, audience, kind), table.default, audience, kind, rights,
                               close=close)
    if allowed is None or not allowed.read:
        return None
    write, respond = allowed.write, allowed.respond
    if got == SHARE_READ:  # le partage est un plafond : lire n'écrit ni ne répond
        write = respond = NO
    elif got == SHARE_PREPARE:  # préparer : écrire, sur l'accord du propriétaire ; jamais répondre à sa place
        write = OWNER_OK if write != NO else NO
        respond = NO
    return Here(calendar, got, allowed, True, write, respond, allowed.keep, owner_decides=got == SHARE_PREPARE)


def audience_at(frame: Frame, handle: str) -> Audience:
    """L'audience d'une adresse où elle prendrait la parole d'elle-même, telle que l'identité la donnera à
    l'épisode, pour ce que le tableau d'un agenda en lit : qui (la personne derrière l'adresse), par où (son canal), ce
    que prouve son transport, si elle y parle en propriétaire. Les niveaux de divulgation n'y sont pas : un tableau
    n'en dépend pas. Qui l'appelle lit ``IDENTITY`` et ``SPEAKS_AS_OWNER``."""
    view = frame.get(identity_c.IDENTITY(handle))
    public = view.trust is ChannelTrust.PUBLIC
    return Audience(persons=(handle,), channel=view.channel or "web", public=public, trust=view.trust.value,
                    certainty=view.certainty, name=view.name, person=view.person or handle,
                    owner=bool(frame.get(identity_c.SPEAKS_AS_OWNER(handle))) and not public)


def at_work(p: AgendaParams, rights: Rights, calendar: str, close: Callable[[str], bool] | None = None) -> Here | None:
    """Ce qu'elle fait de cet agenda seule, au travail (une tâche : personne n'écoute) ; ``None`` : il ne sert pas."""
    return here(p, rights, calendar, WORKING, Kind.TASK, close)


def candidates(p: AgendaParams, audience: Any, kind: str, known: Iterable[str]) -> list[str]:
    """Les agendas qui peuvent servir ici, avant leur tableau : ceux que la base connaît (``known``), plus « Mon
    agenda » de la personne en face (il existe sans rien faire)."""
    out = dict.fromkeys(known)
    person = getattr(audience, "person", "") or ""
    if person and shared_with(audience, kind):
        out.setdefault(calendar_key(system_account(person), DEFAULT_CALENDAR))
    return [c for c in out if c and reach(p, c, audience, kind)]


def here_all(frame: Frame, calendars: Iterable[str]) -> dict[str, Here]:
    """Ce qu'elle fait de chacun de ces agendas devant qui est en face, dans ce qu'elle vit (ses paramètres, les
    tableaux réglés, qui lui est proche) : seulement ceux qui servent et se lisent ici."""
    kind = frame.episode.kind if frame.episode is not None else ""
    p, rights, close = params_of(frame), rights_of(frame.env), closeness_of(frame.env, frame)
    out: dict[str, Here] = {}
    for cal in candidates(p, frame.audience, kind, calendars):
        got = here(p, rights, cal, frame.audience, kind, close)
        if got is not None:
            out[cal] = got
    return out


def offered(audience: Any, kind: str, frame: Frame | None) -> bool:
    """Qui est en face a un agenda à soi ou qu'on lui partage, qu'elle peut lire ici : reconnue, en tête-à-tête —
    jamais dans un salon, jamais une inconnue ; sans ce qu'elle vit (une console qui juge sans lui), personne."""
    if frame is None or not shared_with(audience, kind):
        return False
    p = params_of(frame)
    rights, close = rights_of(frame.env), closeness_of(frame.env, frame)
    person = getattr(audience, "person", "") or ""
    mine = calendar_key(system_account(person), DEFAULT_CALENDAR)
    known = [mine, *p.shares, *p.hidden, *p.reminders]
    if any(here(p, rights, c, audience, kind, close) is not None for c in dict.fromkeys(known)):
        return True
    # un compte branché à elle (ou « à toi », pour une de ses propriétaires) : ses agendas sont dans la base
    me = PERSON + person
    return any(holder == me or (not holder and situation(audience, kind) == AT_OWNER)
               for account, holder in ((a, owner(p, a)) for a in p.kinds) if account not in p.accounts_off)


def approval(frame: Frame, h: Here, holder: str) -> tuple[bool, str]:
    """Qui donne l'accord d'une écriture : (une carte dans une conversation ?, l'adresse de qui décide). La personne en
    face, sur une carte dans sa conversation ; sur ton accord (un canal qui serre) et devant une autre qu'une de ses
    propriétaires, la console ; pour un partage « lire et préparer », le propriétaire — dans son chat à lui (une de
    ses adresses présente, sinon une où l'on peut lui écrire), sinon la console. Qui l'appelle lit ``IDENTITY``,
    ``HANDLES``, ``REACHABLE`` et ``presence.PRESENT``."""
    if h.owner_decides:
        if not holder.startswith(PERSON):
            return False, ""
        person = holder[len(PERSON):]
        handle = best_handle(list(frame.get(identity_c.HANDLES(person)) or (person,)),
                             set(frame.get(presence_c.PRESENT)), set(frame.get(identity_c.REACHABLE(person))))
        return bool(handle), handle
    ep, audience = frame.episode, frame.audience
    target = (ep.target if ep is not None else None) or ""
    if not target or audience is None:
        return False, ""
    if h.write == OWNER_OK and not audience.owner:
        return False, ""
    return True, target


def policy_of(level: str) -> str:
    """Une colonne serrée, dite comme une ligne d'agenda la dit : seule, avec accord, non."""
    return ALONE if level == ALONE else AGREE if level in (CARD, OWNER_OK) else NO


def holders(p: AgendaParams, calendars: Sequence[str]) -> dict[str, str]:
    """À qui est chacun de ces agendas (``personne:<clé>`` ; vide : à toi)."""
    return {c: owner(p, split_calendar_key(c)[0]) for c in calendars}


__all__ = ["OWNED", "SHARE_COLUMNS", "WORKING", "Here", "approval", "as_seen", "at_work", "audience_at", "candidates",
           "default_lines", "here", "here_all", "holders", "offered", "policy_of", "reach", "share_line",
           "shared_table", "table_of"]
