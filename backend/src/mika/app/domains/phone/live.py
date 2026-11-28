"""La part des messages du téléphone dans le direct (ADR 0308, 0310) : ses messages et ses réponses offertes, à elle
seule — la personne dont c'est le téléphone.

Une réponse offerte est aussi un effet du moteur (proposée, décidée, partie) : ``effect`` la reconnaît par sa
proposition.
"""

from __future__ import annotations

from typing import Any

from mika.app.domains.domain import LivePart
from mika.app.me.touches import PERSON, Touch, both, state_of
from mika.contracts import phone as phone_c
from mika.plugins.phone import PHONE as PLUGIN
from mika.ports.changes import ME, PHONE, SETTINGS


def from_event(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Ses messages, ses réponses offertes : à elle seule — son adresse ou sa personne, la règle de ``api._mine``."""
    d, name = e.data, e.type.name
    s = state_of(frame, PLUGIN.name)
    if name == phone_c.RECEIVED.name:
        m = s.messages.get(e.seq) if s is not None else None
        if m is None:
            return [Touch(PHONE, PERSON, owners=both(d.handle))]
        return [Touch(PHONE, PERSON, keys=(f"{m.source}|{m.thread}",), owners=both(m.handle, m.person))]
    offer = (s.offers.get(e.seq if name == phone_c.DRAFTED.name else d.draft) if s is not None else None)
    if offer is None:
        return []
    return _offered(offer)


def _offered(o: Any) -> list[Touch]:
    who = both(o.handle, o.person)
    return [Touch(PHONE, PERSON, keys=(f"{o.source}|{o.thread}",), owners=who), Touch(ME, PERSON, owners=who)]


def effect(proposal: int, frame: Any, kernel: Any, event: Any = None) -> list[Touch] | None:
    """Un effet du moteur est-il une réponse offerte sur le téléphone ? Ses touches, ou ``None``."""
    phone = state_of(frame, PLUGIN.name)
    offer = next((o for o in phone.offers.values() if o.proposal == proposal), None) if phone is not None else None
    return _offered(offer) if offer is not None else None


LIVE = LivePart(events={phone_c.OWNER: from_event}, params={phone_c.OWNER: (SETTINGS, PHONE)}, effects=effect)
