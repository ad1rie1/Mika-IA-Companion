"""Contrat de ``social`` : les liens.

La **proximité** d'une personne (inconnue, connaissance, amie, proche) naît
de leur **histoire vécue** : des jours de contact, des messages, et ce que
ces échanges ont installé (jamais amie d'une rancune installée). On ne
devient pas « proche » en trois messages, ni en une semaine — il y faut un
mois d'histoire **vécue** (du premier au dernier jour de contact : une
absence n'y ajoute rien), et de la chaleur installée ou un attachement
(``affect.bond`` ; un attachement plus modeste suffit à une longue
histoire — l'assiduité seule ne fait pas une intimité) —, quoi qu'on en
dise, ni quoi qu'en dise un modèle. Elle se lit sur une fenêtre glissante :
un long silence la fait descendre d'un cran ; une longue amitié ne tombe
jamais plus d'un cran sous ce qu'elle a été, une amitié courte que son
silence a dépassée redevient une connaissance (ADR 0058). Un opérateur peut
la déclarer (genèse, correction).

Le **rythme** d'une relation est l'écart médian entre les jours où la
personne a écrit : c'est à lui, pas à une horloge commune, que se mesure un
silence. La **réciprocité** compte qui ouvre les conversations : quand c'est
presque toujours elle, elle le remarque, et ses relances s'espacent.

**Qui a un lien avec qui** (``TIES``) : deux personnes qui étaient ensemble
dans une petite conversation se connaissent ; une personne qui en nomme une
autre en lui racontant sa vie la compte dans son entourage. Prononcer le nom
de quelqu'un ne crée aucun lien. C'est ce qui ouvre la confidence d'une
personne à une proche de Mika (``vocab.privacy``, ADR 0058).

**Longtemps après** (``REKINDLE``) : une amie partie sans plus répondre, elle
reprend de ses nouvelles une fois, doucement — des mois plus tard, ou après
une date que la personne lui avait annoncée ; puis plus rien tant qu'elle
n'a pas écrit (``agency``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.contracts.attention import Signal
from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "social"

GREETING = "greeting"
PRESENT_PERSON = "present"
RECONTACT = "recontact"
COMFORT = "comfort"
#: Envie de discuter avec une amie, sans autre raison que l'envie.
CHAT = "chat"
#: Reprendre des nouvelles d'une amie partie sans plus répondre, longtemps après — une fois (ADR 0058).
REKINDLE = "rekindle"
#: Veto : on ne va pas vers quelqu'un qui a installé une rancune. (Ne pas écrire deux fois de suite à
#: quelqu'un qui n'a pas répondu est la retenue d'``agency`` : ``agency.UNANSWERED``.)
GRUDGE = "grudge"

STRANGER, ACQUAINTANCE, FRIEND, CLOSE = "stranger", "acquaintance", "friend", "close"
CLOSENESS_LEVELS = (STRANGER, ACQUAINTANCE, FRIEND, CLOSE)


class ProfileRevised(Payload):
    """Ce qu'elle pense d'une personne, relu à partir de ce que cette personne
    lui a dit elle-même (jamais de ce qu'un tiers lui a confié sur elle). Tout
    le texte est gardé à part : l'oubli de la personne l'efface."""

    person: str
    summary: Content
    tone: Content | None = None
    #: un intérêt par ligne
    interests: Content | None = None
    #: un sujet délicat par ligne
    sensitive: Content | None = None
    upto: int = 0  # le dernier élément de mémoire relu
    call_id: str = ""
    model: str = ""
    #: avant la version 2, ces trois-là étaient gardés en clair (journal ancien)
    legacy_tone: str = ""
    legacy_interests: tuple[str, ...] = ()
    legacy_sensitive: tuple[str, ...] = ()


def _profile_v1(raw: dict[str, Any]) -> dict[str, Any]:
    """v1 → v2 : le ton, les intérêts et les sujets délicats en clair passent
    dans les champs d'héritage (le profil ancien se relit tel qu'il était)."""
    raw = dict(raw)
    raw["legacy_tone"] = str(raw.pop("tone", "") or "")
    raw["legacy_interests"] = tuple(raw.pop("interests", ()) or ())
    raw["legacy_sensitive"] = tuple(raw.pop("sensitive", ()) or ())
    return raw


class ClosenessSet(Payload):
    person: str
    closeness: str
    by: str = "operator"


class OneSided(Signal):
    """Elle remarque que, ces derniers temps, c'est presque toujours elle qui
    écrit la première à quelqu'un (un signal pour son attention : une pensée)."""


PROFILE_REVISED = event_type("social.profile_revised", OWNER, ProfileRevised, version=2, public=True,
                             upcasters={1: _profile_v1}, content=("summary", "tone", "interests", "sensitive"),
                             subjects=("person",))
CLOSENESS_SET = event_type("social.closeness_set", OWNER, ClosenessSet, public=True, subjects=("person",))
ONE_SIDED = event_type("social.one_sided", OWNER, OneSided, public=True, content=("summary",), subjects=("about",))
ALL = (PROFILE_REVISED, CLOSENESS_SET, ONE_SIDED)


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
    #: le dernier message de la personne avant la conversation en cours (deux heures de silence
    #: séparent deux conversations ; 0 : aucun), et le début de celle-ci
    previous: int = 0
    since: int = 0
    #: qui a ouvert leurs dernières conversations : elle, ou la personne
    her_starts: int = 0
    their_starts: int = 0
    #: c'est presque toujours elle qui écrit la première
    one_sided: bool = False
    #: leur rythme tel qu'il était à leur dernier jour de contact (un long silence ne le change pas : c'est à lui
    #: qu'il se mesure) ; ``rhythm_days`` est celui d'aujourd'hui, qui retombe sur un repli après des mois
    usual_days: float = 0.0


#: Instant de la dernière salutation adressée à cette personne (0 si jamais).
GREETED = FactFamily("social.greeted", arg=str, type=int)
#: Une des ``CLOSENESS_LEVELS`` (elle varie avec le temps : un long silence la fait descendre).
CLOSENESS = FactFamily("social.closeness", arg=str, type=str, time_varying=True)
CONTACT = FactFamily("social.contact", arg=str, type=ContactReading, time_varying=True)
#: Les sujets délicats avec cette personne (repliés), d'après un profil d'avant
#: la version 2, gardés en clair. Les profils récents gardent les leurs à part :
#: ``SENSITIVE_REF``.
SENSITIVE = FactFamily("social.sensitive", arg=str, type=tuple)
#: La référence du contenu de ses sujets délicats (un par ligne, à lire dans le
#: magasin ; vide : aucun). Oubliée, la personne n'en a plus.
SENSITIVE_REF = FactFamily("social.sensitive_ref", arg=str, type=str)

#: Les amies et proches — d'aujourd'hui ou d'avant : une amie partie sans plus donner de nouvelles manque encore —
#: dont le silence dépasse une fois et demie leur rythme : ``(personne, silence ÷ rythme)``, du plus long au plus
#: court.
MISSED = FactKey("social.missed", type=tuple, time_varying=True)
#: Celles qui sont, ou ont pu être, des amies ou des proches (assez d'histoire, une proximité déclarée, une
#: propriétaire) : un tri bon marché, sans affect, qui contient toute amie ou proche d'aujourd'hui — ce qui ne
#: regarde que les amies ne paie pas le prix de toutes les inconnues de passage.
CIRCLE = FactKey("social.circle", type=tuple)
#: Les personnes avec qui celle-ci a un lien (elles étaient ensemble dans une petite conversation, ou l'une l'a
#: nommée en lui racontant sa vie), telles qu'elles valent maintenant (ADR 0058).
TIES = FactFamily("social.ties", arg=str, type=tuple)
