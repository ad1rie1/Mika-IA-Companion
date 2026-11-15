"""Ce que les routes de l'API par personne se partagent : un instant, un extrait, des textes du journal, les réglages
et leur plafond, ses comptes et son niveau sur chacun.

La règle de partage est dans ``vocab.ownership`` (ADR 0185, 0186, 0188) : ``held_by`` la lit pour un port et les
paramètres de son greffon, et ``allows`` dit ce qu'un niveau ouvre. Mail et Teams s'en servent à l'identique.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from mika.app.me.api import OWN_MAX, Call, Denied, missing
from mika.vocab.access import PERSON, reaches
from mika.vocab.ownership import OWNED, held

#: un compte et le niveau de qui est connecté dessus
Held = tuple[Any, str]


def millis(us: int) -> int:
    """Un instant du moteur (µs) tel que le client le lit (ms) ; 0 : jamais."""
    return us // 1000 if us else 0


def snippet(text: str, limit: int) -> str:
    """Le début d'un texte, sur une ligne : ``limit`` caractères au plus, ``…`` compris."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def texts_of(call: Call, refs: Iterable[str]) -> dict[str, str]:
    """Les textes du journal que ces références désignent (un contenu : lu à la demande, jamais dans la tranche),
    chacun une fois, les vides écartés ; sans magasin, rien. Le téléphone et la carte les lisent ici (``phone.py``,
    ``maps.py``) ; ``teams._notes`` a sa propre lecture, qui écarte ce qui est à elle."""
    wanted = [r for r in dict.fromkeys(refs) if r]
    store = call.port("store")
    return dict(store.content(wanted)) if wanted and store is not None else {}


def settings_of(call: Call) -> Any:
    """Les réglages du serveur (``Settings``), ou 503 s'ils ne sont pas branchés : ce que lisent les routes qui en
    écrivent (``settings.py`` : boîtes, comptes Teams, règles ; ``shares.set_share``)."""
    settings = call.api.settings
    if settings is None:
        raise Denied(503, "Les réglages ne sont pas branchés.")
    return settings


def own_room(call: Call, count: int) -> None:
    """Une personne qui n'est pas opératrice branche au plus ``OWN_MAX`` ressources de chaque sorte (409 au-delà) :
    ``count``, celles de cette sorte qui sont déjà à elle. Boîtes et comptes Teams (``settings.py``) et services
    (``mcp._plug``) le disent ainsi."""
    if not call.me.operator and count >= OWN_MAX:
        raise Denied(409, f"Tu en as déjà {OWN_MAX} : retires-en avant d'en brancher d'autres.")


def allows(level: str, need: str) -> bool:
    """Son niveau sur un compte ouvre-t-il ce geste ? Le sien, tout ; un partage, ce qu'il atteint."""
    return level == OWNED or reaches(level, need)


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
    if found[1] != OWNED:
        raise Denied(403, refusal)
    return found[0]
