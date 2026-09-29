"""Contrat d'``identity`` : qui est derrière une poignée, à quel point elle en
est sûre, et ce que ça ouvre.

Une **clé de personne** est la poignée d'une personne (``user_7``, ``tg_42``)
ou, pour quelqu'un connu seulement de nom, ``name:<nom replié>``. Une poignée
parle pour elle-même, sauf si elle a été **liée** à une autre personne :
quand ce qu'elle a dit recoupe ce que seule cette personne pouvait savoir, ou
quand un opérateur l'a relié.

La confiance ne monte que par des preuves que le noyau mesure (connexion,
recoupement de souvenirs privés, lien d'opérateur) ; le modèle, lui, ne peut
que douter ou oublier une liaison — jamais s'en laisser conter.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.vocab.privacy import ChannelTrust, Disclosure

OWNER = "identity"

SHARED_MEMORY = "shared_memory"
#: un opérateur se porte garant d'une revendication (compte une fois)
VOUCHED = "vouched"
DENIED = "denied"
CONTRADICTED = "contradicted"
REVOKED = "revoked"


class Claimed(Payload):
    """« Moi c'est Alice. » ``target`` : la personne revendiquée — la poignée
    elle-même quand personne d'autre ne porte ce nom (elle se présente),
    ``None`` quand plusieurs le portent (on ne sait pas laquelle)."""

    handle: str
    name: str
    target: str | None = None
    message: int | None = None
    public: bool = False


class Evidence(Payload):
    """Une raison de croire, ou de ne plus croire. ``kind`` : une clé de
    ``vocab.privacy.EVIDENCE`` ou ``COUNTER_EVIDENCE``."""

    handle: str
    kind: str
    name: str = ""  # le nom refusé (démenti)
    item: int | None = None  # le souvenir recoupé
    message: int | None = None
    by: str = "kernel"  # kernel | tool | operator (l'opérateur lui-même est nommé par l'audit)
    note: str = ""


class Linked(Payload):
    """Un opérateur relie une poignée à une personne (``None`` : délie)."""

    handle: str
    person: str | None
    by: str = "operator"


CLAIMED = event_type("identity.claimed", OWNER, Claimed, public=True, subjects=("handle",))
EVIDENCE = event_type("identity.evidence", OWNER, Evidence, public=True, subjects=("handle",))
LINKED = event_type("identity.linked", OWNER, Linked, public=True, subjects=("handle",))
ALL = (CLAIMED, EVIDENCE, LINKED)


@dataclass(frozen=True, slots=True)
class IdentityView:
    handle: str
    person: str  # la clé de personne pour laquelle la poignée parle
    name: str
    trust: ChannelTrust  # ce que prouve le transport de cette poignée
    certainty: float  # que cette poignée soit bien ``person`` (effective sur ce transport)
    authenticated: bool
    operator: bool
    known: bool  # la poignée a déjà été vue
    bound: bool = False  # liée à une autre personne qu'elle-même
    claim: str = ""  # un nom revendiqué, pas encore confirmé
    claim_certainty: float = 0.0
    claim_target: str | None = None
    channel: str = ""
    push: bool = False  # on peut lui écrire sans qu'elle soit connectée (message privé)
    first_seen: int = 0  # la première fois que cette personne a été vue, toutes poignées


#: La clé de relation d'une poignée : la personne à laquelle elle est liée,
#: sinon la poignée elle-même.
PERSON = FactFamily("identity.person", arg=str, type=str)
IDENTITY = FactFamily("identity.identity", arg=str, type=IdentityView)
#: Argument : (poignée, canal, public). Toute panne → ``CLOSED``.
DISCLOSURE = FactFamily("identity.disclosure", arg=tuple, type=Disclosure)
#: Les poignées qui parlent pour une personne (triées).
HANDLES = FactFamily("identity.handles", arg=str, type=tuple)
#: Celles où l'on peut lui écrire d'elle-même (messages privés), triées.
REACHABLE = FactFamily("identity.reachable", arg=str, type=tuple)
#: La personne est-elle une propriétaire (opératrice, ou déclarée) ?
IS_OWNER = FactFamily("identity.is_owner", arg=str, type=bool)
#: Ses propriétaires (clés de personne), triés.
OWNERS = FactKey("identity.owners", type=tuple)
