"""Contrat de ``self`` : la persona (un document), le tempérament, l'estime,
le récit de soi, le journal de ses journées et ses rêves.

Le **journal** est écrit la nuit par sa voix, un par journée vécue (une
heure du matin appartient encore à la veille). Les **rêves** naissent en
sommeil paradoxal, deux par nuit au plus, de fragments de ce qu'elle a vécu.
L'un et l'autre peuvent mêler d'autres personnes : ils portent ce qu'ils
concernent et leur sensibilité, et ne se montrent qu'à qui peut les entendre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mika.kernel.events import Content, Payload, VoiceProvenance, event_type
from mika.kernel.facts import FactKey
from mika.kernel.forms import Knob
from mika.vocab.temperament import Temperament

OWNER = "self"


def _lines(label: str, help: str, order: int, group: str = "Caractère") -> Knob:
    return Knob(label=label, help=help + " Une phrase par ligne.", group=group, advanced=False, order=order)


class PersonaDoc(BaseModel):
    """Le personnage, rédigé. Chaque liste est une suite de phrases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Knob(label="Nom", help="Comme elle se présente.", group="Identité", advanced=False,
                              order=10)] = "Mika"
    description: Annotated[str, Knob(label="Description", help="Qui elle est, en quelques phrases.",
                                     group="Identité", widget="textarea", advanced=False, order=20)] = ""
    language: Annotated[str, Knob(label="Langue", help="Celle dans laquelle elle parle et écrit.",
                                  group="Identité", advanced=False, order=30)] = "français"
    tone: Annotated[str, Knob(label="Ton", help="Comment elle parle, en général.", group="Sa parole",
                              widget="textarea", advanced=False, order=40)] = ""
    traits: Annotated[tuple[str, ...], _lines("Traits", "Ce qui la définit.", 50)] = ()
    quirks: Annotated[tuple[str, ...], _lines("Manies", "Ses petites habitudes.", 60)] = ()
    vulnerabilities: Annotated[tuple[str, ...], _lines("Fragilités", "Ce qui la touche.", 70)] = ()
    values: Annotated[tuple[str, ...], _lines("Valeurs", "Ce à quoi elle tient.", 80)] = ()
    interests: Annotated[tuple[str, ...], _lines("Centres d'intérêt", "Ce qui la passionne.", 90)] = ()
    speech: Annotated[tuple[str, ...], _lines("Façons de parler", "Ses tournures.", 100, "Sa parole")] = ()
    greetings: Annotated[tuple[str, ...], _lines("Salutations", "Comment elle dit bonjour.", 110, "Sa parole")] = ()
    timezone: Annotated[str, Knob(label="Fuseau horaire", help="Celui qu'elle vit (nom IANA : Europe/Paris, "
                                                              "America/Montreal…).", group="Identité",
                                  advanced=False, order=35)] = "Europe/Paris"
    temperament: Annotated[Temperament, Knob(label="Tempérament", advanced=False, order=200)] = \
        Field(default_factory=Temperament)


class PersonaRevised(Payload):
    persona: PersonaDoc


class Narrated(Payload):
    """Son récit d'elle-même (« Je suis quelqu'un qui… »), écrit par sa voix."""

    text: Content
    voice: VoiceProvenance
    souvenirs: int = 0  # combien de souvenirs elle avait en l'écrivant
    #: les personnes des souvenirs qu'elle a relus : le récit peut les nommer (l'oubli l'atteint)
    about: tuple[str, ...] = ()


class Journaled(Payload):
    day: str  # AAAA-MM-JJ : la journée vécue
    text: Content
    voice: VoiceProvenance
    about: tuple[str, ...] = ()
    dominant: str = ""
    messages: int = 0


class Dreamt(Payload):
    night: str  # la journée vécue avant cette nuit
    text: Content
    voice: VoiceProvenance
    kind: str  # NIGHTMARE | PLEASANT | ASSOCIATIVE | MUNDANE
    vividness: float
    emotion: str = ""
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    sources: tuple[int, ...] = ()


NIGHTMARE, PLEASANT, ASSOCIATIVE, MUNDANE = "nightmare", "pleasant", "associative", "mundane"

PERSONA_REVISED = event_type("self.persona_revised", OWNER, PersonaRevised, public=True)
JOURNALED = event_type("self.journaled", OWNER, Journaled, public=True, content=("text",), subjects=("about",),
                       authored=True)
DREAMT = event_type("self.dreamt", OWNER, Dreamt, public=True, content=("text",), subjects=("about",),
                    authored=True)
NARRATED = event_type("self.narrated", OWNER, Narrated, public=True, content=("text",), subjects=("about",),
                      authored=True)

PERSONA = FactKey("self.persona", type=PersonaDoc)
#: L'estime de soi, dans [0,05 ; 0,95] : lente, revenant vers 0,5 (demi-vie de trois jours).
ESTEEM = FactKey("self.esteem", type=float, time_varying=True)


@dataclass(frozen=True, slots=True)
class JournalReading:
    day: str
    text_ref: str
    about: tuple[str, ...]
    dominant: str


@dataclass(frozen=True, slots=True)
class DreamReading:
    id: int
    night: str
    text_ref: str
    kind: str
    vividness: float
    emotion: str
    about: tuple[str, ...]
    sensitivity: int
    recalled: bool


#: Le journal de la dernière journée vécue avant aujourd'hui (``None`` s'il n'y en a pas).
YESTERDAY = FactKey("self.yesterday", type=object, time_varying=True)
#: Le rêve le plus vif de la nuit dernière (``None`` s'il n'y en a pas).
DREAM_RESIDUE = FactKey("self.dream_residue", type=object, time_varying=True)
