"""Ce que les routes de l'API par personne se partagent : un instant, un extrait, ses comptes et son niveau sur chacun.

La règle de partage est dans ``vocab.ownership`` (ADR 0185, 0186, 0188) : ``held_by`` la lit pour un port et les
paramètres de son greffon, et ``allows`` dit ce qu'un niveau ouvre. Mail et Teams s'en servent à l'identique.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from mika.app.moi.api import Call, Denied, missing
from mika.vocab.access import PERSON, reaches
from mika.vocab.ownership import OWNED, held

#: le niveau de qui est connecté sur un compte qui est à elle ; sinon, celui de son partage (ADR 0188 : ``lire``,
#: ``preparer``, ``servir``)
OWN = OWNED
#: un compte et le niveau de qui est connecté dessus
Held = tuple[Any, str]


def millis(us: int) -> int:
    """Un instant du moteur (µs) tel que le client le lit (ms) ; 0 : jamais."""
    return us // 1000 if us else 0


def snippet(text: str, limit: int) -> str:
    """Le début d'un texte, sur une ligne : ``limit`` caractères au plus, ``…`` compris."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def allows(level: str, need: str) -> bool:
    """Son niveau sur un compte ouvre-t-il ce geste ? Le sien, tout ; un partage, ce qu'il atteint."""
    return level == OWN or reaches(level, need)


def held_by(call: Call, port: Any, params_of: Callable[[Any], Any]) -> dict[str, Held]:
    """Ce que qui est connecté a de ce port, par clé : le compte et son niveau — les siens, puis ceux qu'on lui partage.
    ``params_of`` lit les paramètres du greffon (``owners``, ``shares``) ; un port absent : rien."""
    if port is None:
        return {}
    params = params_of(call.frame)
    known = list(port.accounts())
    levels = held((a.key for a in known), params.owners, params.shares, PERSON + call.me.person, owner=call.me.owner)
    return {a.key: (a, levels[a.key]) for a in known if a.key in levels}


def opened(found: Held | None, need: str, too_low: Mapping[str, str], otherwise: str) -> Any:
    """Un compte de ``held_by``, si son niveau ouvre ce geste : sinon introuvable, ou refusé (ce que dit ce partage)."""
    if found is None:
        raise missing()
    if not allows(found[1], need):
        raise Denied(403, too_low.get(found[1], otherwise))
    return found[0]


def only_owner(found: Held | None, refusal: str) -> Any:
    """Un compte de ``held_by``, s'il est à elle : un partage n'y suffit pas (le régler, décider de ce qui en part)."""
    if found is None:
        raise missing()
    if found[1] != OWN:
        raise Denied(403, refusal)
    return found[0]
