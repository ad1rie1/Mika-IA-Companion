"""La part de l'agenda dans le direct (ADR 0308, 0309, 0310) : ce que le journal et sa base y changent, et qui le voit.

Un agenda va à qui le voit (``CALENDARS``) : à elle par son compte ou par un partage encore ouvert — la règle même de
ses routes, ``reach.seen_calendars`` ; une règle qui juge elle-même (``judge``). Ce qu'elle propose d'écrire dans un
agenda est aussi un effet du moteur (``effect``). La connexion Google ou Microsoft d'un compte se dit d'elle-même
(``signed``, posée par le câblage).
"""

from __future__ import annotations

from typing import Any

from mika.app.domains.agenda.reach import seen_calendars
from mika.app.domains.agenda.settings import AGENDA_GOOGLE_KEY, AGENDA_GRANTS_KEY, AGENDA_KEY
from mika.app.domains.domain import LivePart
from mika.app.me.touches import Touch
from mika.app.me.touches import both as _both
from mika.app.me.touches import state_of as _state
from mika.plugins import agenda as agenda_p
from mika.ports.agenda import split_calendar_key
from mika.ports.changes import AGENDA, ME, SETTINGS, Change

#: à qui va une touche de l'agenda : à qui le voit (son compte, ses partages : ``reach.seen_calendars``)
CALENDARS = "calendars"


def _calendar(calendar: str) -> list[Touch]:
    """Un agenda a changé : à qui le voit (son compte, ses partages), et ses pastilles (ce qui attend sa décision)."""
    if not calendar:
        return []
    account = split_calendar_key(calendar)[0]
    return [Touch(AGENDA, CALENDARS, keys=(calendar,)), Touch(ME, CALENDARS, owners=_both(account))]


def _agenda(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Ce qu'elle a écrit, et les invitations dont elle prépare la réponse : leur agenda."""
    d, name = e.data, e.type.name
    if name in (agenda_p.WRITTEN.name, agenda_p.INVITATION_NOTICED.name):
        return _calendar(str(d.calendar))
    if name == agenda_p.INVITATION_SETTLED.name:
        s = _state(frame, agenda_p.OWNER)
        inv = s.invitations.get(d.key) if s is not None else None
        return _calendar(inv.calendar) if inv is not None else []
    return []


def effect(proposal: int, frame: Any, kernel: Any, event: Any = None) -> list[Touch] | None:
    """Un effet du moteur est-il ce qu'elle propose d'écrire dans un agenda (ce que sa tranche en garde, par sa
    proposition) ? Ses touches, ou ``None``."""
    agenda = _state(frame, agenda_p.OWNER)
    written = agenda.writes.get(proposal) if agenda is not None else None
    if written is not None:  # ce qu'elle propose d'écrire dans un agenda : proposé, décidé, fait
        return _calendar(written.calendar)
    return None


def from_change(change: Change) -> list[Touch]:
    """Une écriture de sa base, une fois validée : un agenda relu, écrit, réglé ; un compte synchronisé (sa dernière
    synchro, son erreur)."""
    return [Touch(AGENDA, CALENDARS, keys=change.keys, owners=change.accounts),
            Touch(ME, CALENDARS, owners=change.accounts)]


def judge(reader: Any, t: Touch) -> tuple[bool, tuple[str, ...]]:
    """Un agenda est à elle par son compte, ou par un partage encore ouvert ; un compte, s'il est à elle ou si un
    de ses agendas lui est partagé. Sans clé ni compte : tout le domaine (elle a toujours son agenda). Ce qu'elle a
    — les agendas qu'on lui partage, ses comptes d'agenda (``reach.seen_calendars``) — se lit une fois par personne
    et par envoi."""
    shared, accounts = reader.once(CALENDARS, lambda: seen_calendars(reader.call), (frozenset(), frozenset()))
    if t.keys:
        kept = tuple(k for k in t.keys if k in shared or split_calendar_key(k)[0] in accounts)
        return bool(kept), kept
    if not t.owners:
        return True, ()
    reach = accounts | {split_calendar_key(c)[0] for c in shared}
    return bool(reach & set(t.owners)), ()


def signed(changes: Any, account: str) -> None:
    """La connexion Google ou Microsoft d'un compte d'agenda a changé (``on_state`` : connecté, refusé, échu, le
    code d'appareil entré) : à qui le lit. ``changes`` : le direct (``LiveChanges``)."""
    changes.add([Touch(AGENDA, CALENDARS, owners=(account,))])


LIVE = LivePart(
    events={agenda_p.OWNER: _agenda},
    # ce que change le réglage de l'agenda (``kernel.params_changed``) : qui voit quoi, ce qui se règle — à toutes
    params={agenda_p.OWNER: (SETTINGS, AGENDA, ME)},
    # ses comptes, leurs connexions, l'application Google du serveur (``Settings._put``, par leur clé)
    saved={AGENDA_KEY: (SETTINGS, AGENDA, ME), AGENDA_GRANTS_KEY: (SETTINGS, AGENDA),
           AGENDA_GOOGLE_KEY: (SETTINGS, AGENDA)},
    changes={AGENDA: from_change},
    judge={CALENDARS: judge},
    effects=effect,
)
