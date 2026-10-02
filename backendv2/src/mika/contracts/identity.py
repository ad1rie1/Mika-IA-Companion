"""Contrat d'``identity`` : qui est derrière une adresse, à quel point elle en
est sûre, et ce que ça ouvre.

Une **clé de personne** est l'adresse d'une personne (``user_7``, ``tg_42``)
ou, pour quelqu'un connu seulement de nom, ``name:<nom replié>``. Une adresse
parle pour elle-même, sauf si elle a été **liée** à une autre personne :
quand ce qu'elle a dit recoupe ce que seule cette personne pouvait savoir, ou
quand un opérateur l'a relié.

La confiance ne monte que par des preuves que le noyau mesure (connexion,
recoupement de souvenirs privés, lien d'opérateur) ; le modèle, lui, ne peut
que douter ou oublier une liaison — jamais s'en laisser conter.

Un **recoupement** se gagne sur deux messages espacés, jamais dans celui qui
revendique, dont un au moins s'appuie sur un détail rare (un nom propre, un
nombre, une date) ; tant qu'un opérateur ne l'a pas confirmée, une liaison
par simple recoupement n'ouvre pas le fil verbatim des autres adresses de la
personne et ne lui écrit pas d'elle-même par cette adresse.

Les **droits d'une propriétaire** tiennent à l'adresse qui parle, pas à la
personne : une session d'opérateur, une adresse déclarée sur un canal qui
prouve le compte, ou une adresse qu'un opérateur a reliée à une propriétaire
sur un tel canal — jamais dans un salon public.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.vocab.privacy import ChannelTrust, Disclosure

OWNER = "identity"

SHARED_MEMORY = "shared_memory"
#: la première moitié d'un recoupement : un souvenir recoupé, qui ne compte
#: qu'avec un second, sur un autre message (sans poids à lui seul)
SHARED_HINT = "shared_hint"
#: un opérateur se porte garant d'une revendication (compte une fois)
VOUCHED = "vouched"
DENIED = "denied"
CONTRADICTED = "contradicted"
REVOKED = "revoked"

#: Ce que vise un démenti, jugé à la lecture (le texte du nom démenti, lui, s'oublie).
DENIES_BINDING, DENIES_CLAIM, DENIES_NAME = "binding", "claim", "name"
#: Comment une adresse a été reliée : par un opérateur (« Relier »), par sa garantie, par recoupement.
VIA_OPERATOR, VIA_VOUCHED, VIA_CORROBORATED = "operator", "vouched", "corroborated"
#: Une liaison qu'un opérateur a décidée : seule celle-là ouvre tout ce qui est verbatim.
CONFIRMED_VIA = frozenset({VIA_OPERATOR, VIA_VOUCHED})


class Claimed(Payload):
    """« Moi c'est Alice. » ``target`` : la personne revendiquée — l'adresse
    elle-même quand personne d'autre ne porte ce nom (elle se présente),
    ``None`` quand plusieurs le portent (on ne sait pas laquelle)."""

    handle: str
    name: str
    target: str | None = None
    message: int | None = None
    public: bool = False


class Evidence(Payload):
    """Une raison de croire, ou de ne plus croire. ``kind`` : une clé de
    ``vocab.privacy.EVIDENCE`` ou ``COUNTER_EVIDENCE`` (ou ``SHARED_HINT``).

    Le nom démenti et la note sont des textes gardés à part : l'oubli les
    atteint (la personne revendiquée est un sujet, ``about``). Ce que vise un
    démenti est jugé à la lecture (``denies``) : le réducteur ne relit jamais
    un nom."""

    handle: str
    kind: str
    name: Content | None = None  # le nom refusé (démenti)
    item: int | None = None  # le souvenir recoupé
    message: int | None = None
    by: str = "kernel"  # kernel | tool | operator (l'opérateur lui-même est nommé par l'audit)
    note: Content | None = None
    #: un démenti vise sa liaison, sa revendication, ou le nom qu'elle lui prête (``DENIES_*``)
    denies: str = ""
    #: le recoupement s'appuie sur un détail rare (un nom propre, un nombre, une date)
    rare: bool = False
    #: la personne que la preuve concerne (celle qu'elle dit être)
    about: tuple[str, ...] = ()
    #: avant la version 2, le nom démenti et la note étaient gardés en clair (journal ancien)
    legacy_name: str = ""
    legacy_note: str = ""


def _evidence_v1(raw: dict[str, Any]) -> dict[str, Any]:
    """v1 → v2 : le nom et la note passent en clair dans les champs d'héritage ;
    rien d'autre ne change (le démenti se juge alors comme avant, par le nom)."""
    raw = dict(raw)
    raw["legacy_name"] = str(raw.pop("name", "") or "")
    raw["legacy_note"] = str(raw.pop("note", "") or "")
    return raw


class Linked(Payload):
    """Un opérateur relie une adresse à une personne (``None`` : délie)."""

    handle: str
    person: str | None
    by: str = "operator"


class NameBound(Payload):
    """Un opérateur dit que la personne dont on lui a parlé sous ce nom (``name:alice``, une clé de la mémoire)
    est cette personne-là (``None`` : défait). Jamais déduit d'une ressemblance de nom : deux Alice ne se
    confondent pas d'elles-mêmes (la certitude sur qui est qui reste mécanique)."""

    name: str
    person: str | None
    by: str = "operator"


class Registered(Payload):
    """Un compte du système (web, console) tel qu'il est : il existe comme personne,
    authentifiée, sous son nom (nom complet, sinon identifiant), dès sa création — sans
    attendre qu'il se connecte. Réémis quand le compte change (nom, rôle, activité)."""

    handle: str
    name: str
    operator: bool = False
    active: bool = True


CLAIMED = event_type("identity.claimed", OWNER, Claimed, public=True, subjects=("handle",))
EVIDENCE = event_type("identity.evidence", OWNER, Evidence, version=2, public=True, upcasters={1: _evidence_v1},
                      content=("name", "note"), subjects=("handle", "about"))
LINKED = event_type("identity.linked", OWNER, Linked, public=True, subjects=("handle",))
REGISTERED = event_type("identity.registered", OWNER, Registered, public=True, subjects=("handle",))
NAME_BOUND = event_type("identity.name_bound", OWNER, NameBound, public=True, subjects=("name",))
ALL = (CLAIMED, EVIDENCE, LINKED, REGISTERED, NAME_BOUND)


@dataclass(frozen=True, slots=True)
class IdentityView:
    handle: str
    person: str  # la clé de personne pour laquelle l'adresse parle
    name: str
    trust: ChannelTrust  # ce que prouve le transport de cette adresse
    certainty: float  # que cette adresse soit bien ``person`` (effective sur ce transport)
    authenticated: bool
    operator: bool
    known: bool  # l'adresse a déjà été vue
    bound: bool = False  # liée à une autre personne qu'elle-même
    claim: str = ""  # un nom revendiqué, pas encore confirmé
    claim_certainty: float = 0.0
    claim_target: str | None = None
    channel: str = ""
    push: bool = False  # on peut lui écrire sans qu'elle soit connectée (message privé)
    first_seen: int = 0  # la première fois que cette personne a été vue, toutes adresses
    #: comment elle a été reliée (``VIA_*``), vide pour une adresse qui parle pour elle-même
    via: str = ""


#: La clé de relation d'une adresse : la personne à laquelle elle est liée,
#: sinon l'adresse elle-même.
PERSON = FactFamily("identity.person", arg=str, type=str)
IDENTITY = FactFamily("identity.identity", arg=str, type=IdentityView)
#: Argument : (adresse, canal, public). Toute panne → ``CLOSED``.
DISCLOSURE = FactFamily("identity.disclosure", arg=tuple, type=Disclosure)
#: Les adresses qui parlent pour une personne (triées).
HANDLES = FactFamily("identity.handles", arg=str, type=tuple)
#: Celles où l'on peut lui écrire d'elle-même (messages privés), triées. Une
#: adresse reliée par simple recoupement n'en est pas, tant qu'un opérateur
#: n'a pas confirmé : on ne pousse pas ce qui la concerne vers un compte peut-être usurpé.
REACHABLE = FactFamily("identity.reachable", arg=str, type=tuple)
#: Argument : l'adresse qui parle. Les adresses dont le fil privé (verbatim)
#: peut se montrer à qui écrit par elle : la sienne, et celles de sa personne
#: dont la liaison est confirmée (compte, opérateur) — une liaison par simple
#: recoupement ne voit que son propre fil. Triées.
THREAD = FactFamily("identity.thread", arg=str, type=tuple)
#: La personne est-elle une propriétaire (compte d'opérateur, ou déclarée) ? Une
#: question sur la *personne* (à qui raconter son travail) ; pour savoir si
#: celle qui parle en a les droits, c'est ``SPEAKS_AS_OWNER``.
IS_OWNER = FactFamily("identity.is_owner", arg=str, type=bool)
#: Argument : l'adresse qui parle. A-t-elle les droits d'une propriétaire ?
#: Seulement si elle le prouve elle-même : une session d'opérateur, une adresse
#: déclarée sur un canal qui prouve le compte, ou une adresse qu'un opérateur a
#: reliée à une propriétaire sur un tel canal. Jamais par recoupement, garantie
#: ni sur un transport qui ne prouve rien. (Le salon, lui, est jugé par l'audience.)
SPEAKS_AS_OWNER = FactFamily("identity.speaks_as_owner", arg=str, type=bool)
#: Ses propriétaires (clés de personne), triés.
OWNERS = FactKey("identity.owners", type=tuple)
