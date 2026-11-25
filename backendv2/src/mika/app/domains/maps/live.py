"""La part de la carte dans le direct (ADR 0308, 0310) : une position que le téléphone donne ou retire, un voyage qui
change — à sa personne seule ; régler les paramètres des voyages ou de la localisation change ce qu'en montrent les
écrans, à toutes."""

from __future__ import annotations

from typing import Any

from mika.app.domains.domain import LivePart
from mika.app.me.touches import PERSON, Touch
from mika.app.me.touches import both as _both
from mika.contracts import location as location_c
from mika.contracts import trips as trips_c
from mika.plugins import trips as trips_p
from mika.ports.changes import PHONE_POSITION, TRIPS


def _location(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    return [Touch(PHONE_POSITION, PERSON, owners=_both(e.data.handle, e.data.person))]


def _trips(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Un voyage est à sa personne, telle que l'identité la relie maintenant ; un regard, aussi à l'adresse qui l'a
    demandé (la règle de ``maps``)."""
    d = e.data
    return [Touch(TRIPS, PERSON, owners=_both(trips_p.owner_key(frame.get, d.person), getattr(d, "handle", "")))]


LIVE = LivePart(events={location_c.OWNER: _location, trips_c.OWNER: _trips},
                params={trips_c.OWNER: (TRIPS,), location_c.OWNER: (PHONE_POSITION,)})
