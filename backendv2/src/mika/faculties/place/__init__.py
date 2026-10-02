"""``place`` : où elle est dans sa chambre, tel que les écrans le lisent (ADR 0049, repris par l'ADR 0050).

Depuis l'ADR 0050, son corps vit dans ``world`` : c'est là qu'elle décide d'aller quelque part (``go_to``), que
le sommeil la met au lit et que ses déplacements se concluent. Il reste ici ce que d'autres lisent déjà :

- le contrat ``place`` : le type ``place.moved`` (public), que des journaux contiennent — ``world`` le relit
  comme un de ses déplacements, rien n'est perdu au rejeu ;
- les faits ``place.current`` et ``place.since``, que les écrans reçoivent dans l'état intérieur
  (``inner_state.place``) : un état, pas un ordre — là où elle est, ou là où elle va quand elle est en chemin
  (le corps du frontend marche jusque-là, et ne repart pas si le même lieu revient).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.contracts import place as c
from mika.contracts import world as world_c
from mika.kernel.faculty import Faculty


@dataclass(frozen=True, slots=True)
class PlaceState:
    """Plus rien à tenir ici : son corps est dans le monde."""


PLACE = Faculty("place", state=PlaceState, init=lambda p: PlaceState(), state_version=2)
PLACE.declare(*c.ALL)


@PLACE.fact(c.PLACE, reads=[world_c.SELF])
def _place(s: PlaceState, cx: Any) -> c.Place:
    me: world_c.ActorState = cx.facts.get(world_c.SELF)
    target = me.moving.to_place if me.moving is not None else me.place
    try:
        return c.Place(target)
    except ValueError:
        return c.Place.CENTER  # un lieu que l'écran ne connaît pas encore : il la montre au milieu


@PLACE.fact(c.SINCE, reads=[world_c.SELF])
def _since(s: PlaceState, cx: Any) -> int:
    me: world_c.ActorState = cx.facts.get(world_c.SELF)
    return me.moving.started if me.moving is not None else me.since
