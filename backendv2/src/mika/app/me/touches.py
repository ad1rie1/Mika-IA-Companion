"""Une touche du direct (ADR 0308) : une chose qui a changé, et à qui elle va.

Le service qui les regroupe et les envoie est ``app/me/changes.py``. Ce module ne porte que leur forme : un domaine
qui dit ce qu'il change (sa part du direct, ``app/domains/domain.py::LivePart``) n'importe que lui — jamais le
service, qui lit les fiches des domaines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.vocab.access import SHARE_PREPARE, SHARE_READ
from mika.vocab.ownership import OWNED

#: à qui va une touche, quand ce n'est pas la règle d'un domaine : une personne (son téléphone, sa position, ses
#: voyages) ; tout le monde
PERSON, EVERYONE = "person", "all"
#: le niveau qu'il faut sur une boîte ou un compte : le lire, y préparer (ses réponses en chemin), en être propriétaire
#: (ce qui attend ta décision : les pastilles)
READ, PREPARE, OWN = SHARE_READ, SHARE_PREPARE, OWNED


@dataclass(frozen=True, slots=True)
class Touch:
    """Une chose qui a changé : son sujet ; à qui elle va (``rule``) et à quel niveau (``need``) ; ce que la trame
    nommera (``keys`` : des boîtes, des références, des conversations, des projets) ; sans clé, les comptes qu'elle
    concerne (``owners`` : boîtes, comptes Teams, adresses et personnes, projets, sources ``source|compte`` — vide :
    tout le domaine). Une touche ``weak`` ne demande que ce que toute trame de son sujet fait relire (les comptes de
    Teams, quand la présence de leur extension change) : elle ne l'emporte pas sur ce qu'une autre y nomme."""

    topic: str
    rule: str
    need: str = READ
    keys: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    weak: bool = False


def state_of(frame: Any, owner: str) -> Any:
    """La tranche d'un propriétaire, ou ``None`` s'il n'est pas dans la composition."""
    return frame.root.slices.get(owner)


def both(*values: str) -> tuple[str, ...]:
    """Ces valeurs, sans les vides ni les doublons, dans leur ordre : une adresse et sa personne."""
    return tuple(dict.fromkeys(v for v in values if v))
