"""La part de Teams dans le direct (ADR 0308, 0310) : ce que le journal et le cache de Teams y changent, et qui le voit.

Ce qui change dans un compte Teams va à qui le tient, à son niveau (``ACCOUNTS`` : les comptes de la personne, les
siens et ceux qu'on lui partage — la règle même de ses routes, ``api.accounts``) ; une conversation (``compte~id``)
est au compte qui la porte. Une réponse qu'elle prépare est aussi un effet du moteur (proposée, décidée, partie) et
une tâche (``effect``, ``work``). La présence de l'extension d'un compte se dit d'elle-même (``presence``, posée par
le câblage).
"""

from __future__ import annotations

from typing import Any

from mika.app.domains.domain import LivePart
from mika.app.domains.teams import api as teams_me
from mika.app.domains.teams.settings import TEAMS_KEY, TEAMS_KEYS_KEY
from mika.app.me.api import Call
from mika.app.me.touches import OWN, PREPARE, Touch
from mika.app.me.touches import state_of as _state
from mika.contracts import teams as teams_c
from mika.plugins import teams as teams_p
from mika.ports.changes import (
    CONTACTS,
    ME,
    OUTBOX,
    SETTINGS,
    TEAMS,
    TEAMS_DRAFTS,
    TEAMS_REPLIES,
    TEAMS_WORK,
    Change,
)
from mika.ports.teams import DEFAULT_ACCOUNT, conversation_key, split_conversation_key

#: à qui va une touche de Teams : à qui tient son compte (ses propriétaires et ses partages)
ACCOUNTS = "accounts"


def _teams_key(frame: Any, kernel: Any, ref: str) -> str:
    """La conversation d'un message (``compte~id``) : ce qu'elle en a remarqué ou ce qu'on lui a demandé, sinon le
    cache."""
    s = _state(frame, teams_p.TEAMS.name)
    seen = s.messages.get(ref) if s is not None else None
    if seen is not None:
        return conversation_key(seen.account, seen.conversation)
    asked = s.asked.get(ref) if s is not None else None
    if asked is not None:
        return conversation_key(asked.account, asked.conversation)
    port = kernel.ports.get("teams")
    found = port.message(ref) if port is not None and ref else None
    return conversation_key(found.account, found.conversation) if found is not None else ""


def _teams(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    d, name = e.data, e.type.name
    account = str(getattr(d, "account", "") or DEFAULT_ACCOUNT)
    conversation = str(getattr(d, "conversation", "") or "")
    if name == teams_p.SETTLED.name:  # une de ses réponses (une réponse de la personne : le cache le dit)
        s = _state(frame, teams_p.TEAMS.name)
        seen = teams_p.latest(s, d.draft) if s is not None else None
        if seen is None:
            return []
        account, conversation = seen.account, seen.conversation
    yours = (account,)
    if name in (teams_p.RECEIVED.name, teams_p.IMAGES.name, teams_p.IMAGE_SEEN.name):
        # ce qui est arrivé, le cache le nomme ; une réponse à laquelle la personne a répondu autrement ne part plus
        return [Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=yours), Touch(ME, ACCOUNTS, OWN, owners=yours)] \
            if getattr(d, "replied", ()) else []
    keys = (conversation_key(account, conversation),) if conversation else ()
    out = [Touch(TEAMS, ACCOUNTS, keys=keys, owners=yours)]
    if name == teams_c.DRAFT_ASKED.name:
        out.append(Touch(TEAMS_WORK, ACCOUNTS, PREPARE, keys=keys, owners=yours))
    if name in (teams_c.SENT.name, teams_p.SETTLED.name):
        out += [Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=yours), Touch(ME, ACCOUNTS, OWN, owners=yours)]
    return out


def from_change(change: Change) -> list[Touch]:
    """Une écriture du cache de Teams, une fois validée : ses comptes et ses conversations."""
    if change.topic == TEAMS:
        return [Touch(TEAMS, ACCOUNTS, keys=change.keys, owners=change.accounts)]
    if change.topic in (TEAMS_DRAFTS, OUTBOX):  # un brouillon, ce que la boîte d'envoi en fait : son fil, ses réponses
        return [Touch(TEAMS, ACCOUNTS, keys=change.keys, owners=change.accounts),
                Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=change.accounts)]
    return []


def effect(proposal: int, frame: Any, kernel: Any, event: Any = None) -> list[Touch] | None:
    """Un effet du moteur est-il une de ses réponses Teams (ce que sa tranche en garde, par sa proposition) ? Ses
    touches, ou ``None``."""
    teams = _state(frame, teams_p.TEAMS.name)
    reply = teams.drafts.get(proposal) if teams is not None else None
    if reply is not None:
        yours = (reply.account,)
        keys = (conversation_key(reply.account, reply.conversation),) if reply.conversation else ()
        return [Touch(TEAMS, ACCOUNTS, keys=keys, owners=yours), Touch(TEAMS_WORK, ACCOUNTS, PREPARE, keys=keys),
                Touch(TEAMS_REPLIES, ACCOUNTS, PREPARE, owners=yours), Touch(ME, ACCOUNTS, OWN, owners=yours)]
    return None


def work(ref: str, frame: Any, kernel: Any) -> list[Touch]:
    """Où elle en est d'une réponse à un message de Teams (ADR 0306) : sa conversation."""
    key = _teams_key(frame, kernel, ref)
    return [Touch(TEAMS_WORK, ACCOUNTS, PREPARE, keys=(key,))] if key else []


def levels(call: Call) -> dict[str, str]:
    """Ses comptes Teams et son niveau sur chacun (les siens, ceux qu'on lui partage)."""
    return {key: level for key, (_, level) in teams_me.accounts(call).items()}


def owner_of(topic: str, key: str) -> str:
    """Le compte d'une conversation."""
    return split_conversation_key(key)[0]


def presence(changes: Any, account: str) -> None:
    """La présence de l'extension de ce compte Teams se voit autrement (``TeamsDesk.on_presence``) : ses comptes se
    relisent, chez qui le lit — une touche faible, que ce qu'un lot du même instant nomme suffit à dire. ``changes`` :
    le direct (``LiveChanges``)."""
    changes.add([Touch(TEAMS, ACCOUNTS, owners=(account,), weak=True)])


LIVE = LivePart(
    events={teams_c.OWNER: _teams},
    # ce que change le réglage de Teams (``kernel.params_changed``) : qui voit quoi, ce qui se règle — à toutes —, les
    # contacts compris (qui voit ceux d'un compte Teams suit ses propriétaires et ses partages : ``contacts.reach``)
    params={teams_c.OWNER: (SETTINGS, TEAMS, TEAMS_REPLIES, ME, CONTACTS)},
    # un compte Teams, la clé de son extension (``Settings._put``, par leur clé)
    saved={TEAMS_KEY: (SETTINGS, TEAMS, TEAMS_REPLIES, ME, CONTACTS), TEAMS_KEYS_KEY: (SETTINGS, TEAMS)},
    changes={TEAMS: from_change, TEAMS_DRAFTS: from_change, OUTBOX: from_change},
    levels={ACCOUNTS: levels},
    owner_of={ACCOUNTS: owner_of},
    # ses comptes tels que ses réglages les disent, sans son extension : lus une fois par envoi, sur la boucle
    listed={"teams": lambda port: port.accounts(extension=False)},
    effects=effect,
    tasks={teams_c.OWNER: work},
)
