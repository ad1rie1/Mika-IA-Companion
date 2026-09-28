"""Contrat d'``identity`` : qui est derrière une poignée, à quel point elle en
est sûre, et ce que ça ouvre."""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.facts import FactFamily
from mika.vocab.privacy import ChannelTrust, Disclosure

OWNER = "identity"


@dataclass(frozen=True, slots=True)
class IdentityView:
    handle: str
    person: str
    name: str
    trust: ChannelTrust
    certainty: float  # effective : relevée au plancher du canal, bornée au plafond
    authenticated: bool
    operator: bool
    known: bool  # la poignée a déjà été vue


#: La clé de relation d'une poignée : la personne à laquelle elle est liée,
#: sinon la poignée elle-même.
PERSON = FactFamily("identity.person", arg=str, type=str)
IDENTITY = FactFamily("identity.identity", arg=str, type=IdentityView)
#: Argument : (poignée, canal, public). Toute panne → ``CLOSED``.
DISCLOSURE = FactFamily("identity.disclosure", arg=tuple, type=Disclosure)
