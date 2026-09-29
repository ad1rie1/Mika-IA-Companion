"""Contrat de ``social`` : les liens.

La **proximité** d'une personne (inconnue, connaissance, amie, proche) naît
de leur **histoire vécue** : des jours de contact, des messages, et ce que
ces échanges ont installé (jamais amie d'une rancune). On ne devient pas
« proche » en trois messages, quoi qu'on en dise — ni quoi qu'en dise un
modèle. Un opérateur peut la déclarer (genèse, correction).

Le **rythme** d'une relation est l'écart médian entre les jours où la
personne a écrit : c'est à lui, pas à une horloge commune, que se mesure un
silence.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily

OWNER = "social"

GREETING = "greeting"
PRESENT_PERSON = "present"
RECONTACT = "recontact"
COMFORT = "comfort"
#: Veto : on ne va pas vers quelqu'un qui a installé une rancune.
GRUDGE = "grudge"

STRANGER, ACQUAINTANCE, FRIEND, CLOSE = "stranger", "acquaintance", "friend", "close"
CLOSENESS_LEVELS = (STRANGER, ACQUAINTANCE, FRIEND, CLOSE)


class ProfileRevised(Payload):
    """Ce qu'elle pense d'une personne, relu à partir de ce qu'elle en sait."""

    person: str
    summary: Content
    tone: str = ""
    interests: tuple[str, ...] = ()
    sensitive: tuple[str, ...] = ()
    upto: int = 0  # le dernier élément de mémoire relu
    call_id: str = ""
    model: str = ""


class ClosenessSet(Payload):
    person: str
    closeness: str
    by: str = "operator"


PROFILE_REVISED = event_type("social.profile_revised", OWNER, ProfileRevised, public=True, content=("summary",),
                             subjects=("person",))
CLOSENESS_SET = event_type("social.closeness_set", OWNER, ClosenessSet, public=True, subjects=("person",))
ALL = (PROFILE_REVISED, CLOSENESS_SET)


@dataclass(frozen=True, slots=True)
class ContactReading:
    person: str
    days: int  # jours distincts où la personne a écrit
    inbound: int  # messages reçus d'elle
    first_in: int
    last_in: int
    last_out: int
    rhythm_days: float  # l'écart habituel entre deux jours de contact
    measured: bool  # mesuré sur leur histoire (sinon : repli selon la proximité)
    unanswered: int  # ses initiatives restées sans réponse depuis le dernier message
    silence_ratio: float  # silence actuel ÷ rythme (0 si jamais écrit)


#: Instant de la dernière salutation adressée à cette personne (0 si jamais).
GREETED = FactFamily("social.greeted", arg=str, type=int)
#: Une des ``CLOSENESS_LEVELS``.
CLOSENESS = FactFamily("social.closeness", arg=str, type=str)
CONTACT = FactFamily("social.contact", arg=str, type=ContactReading, time_varying=True)
#: Les sujets délicats avec cette personne (repliés), d'après son profil.
SENSITIVE = FactFamily("social.sensitive", arg=str, type=tuple)
