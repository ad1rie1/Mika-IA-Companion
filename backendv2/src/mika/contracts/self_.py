"""Contrat de ``self`` : la persona (un document), le tempérament, l'estime,
le récit de soi, le journal de ses journées et ses rêves.

Le **journal** est écrit la nuit par sa voix, un par journée vécue (une
heure du matin appartient encore à la veille ; la journée commence une heure
avant son matin) ; une nuit coupée par une conversation le fait réécrire. Les
**rêves** naissent en sommeil paradoxal, deux par nuit au plus, de fragments
de ce qu'elle a vécu ; **au réveil** (``self.woke_with``) elle se souvient —
parfois — du plus vif, et ce que la nuit a apaisé se ressent à ce moment-là.
L'un et l'autre peuvent mêler d'autres personnes : ils portent ce qu'ils
concernent et leur sensibilité, et ne se montrent qu'à qui peut les entendre.

**L'estime** est aussi un sociomètre : un merci ou un compliment d'une amie la
relève un peu, une insulte qui la vise la blesse un peu (``self.touched``, un
jugement lu dans la forme du message, enregistré).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("timezone", mode="before")
    @classmethod
    def _known_zone(cls, value: Any) -> Any:
        """Un fuseau inconnu est refusé ici, à l'entrée : accepté, il mettait en
        panne toute lecture de l'heure (la console, la conversation)."""
        if not isinstance(value, str):
            return value
        name = value.strip()
        if not valid_zone(name):
            raise ValueError(f"fuseau horaire inconnu : « {name[:60]} » (un nom IANA : Europe/Paris, "
                             "America/Montreal…)")
        return name


#: Le fuseau d'une persona dont le fuseau journalisé ne se lit pas (journal d'avant la validation).
DEFAULT_ZONE = "Europe/Paris"


def valid_zone(name: str) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def _zone_repaired(raw: dict[str, Any]) -> dict[str, Any]:
    """v1 → v2 : une persona journalisée avant la validation du fuseau garde
    tout, sauf un fuseau illisible, ramené au défaut (le rejeu ne casse pas)."""
    raw = dict(raw)
    persona = raw.get("persona")
    if isinstance(persona, dict) and "timezone" in persona:
        zone = persona["timezone"]
        name = zone.strip() if isinstance(zone, str) else ""
        raw["persona"] = {**persona, "timezone": name if valid_zone(name) else DEFAULT_ZONE}
    return raw


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
    kind: str  # NIGHTMARE | PLEASANT | MELANCHOLIC | ASSOCIATIVE | MUNDANE
    vividness: float
    emotion: str = ""
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    sources: tuple[int, ...] = ()


class WokeWith(Payload):
    """Ce qu'elle emporte de sa nuit au réveil : le rêve le plus vif — dont elle
    se souvient, ou pas (un tirage enregistré) — et les pensées que la nuit a
    apaisées. Ce que ça lui fait se pose à cet instant, pas en pleine nuit."""

    night: str  # la journée vécue avant cette nuit
    woke_at: int
    dream: int = 0  # le n° du rêve le plus vif (0 : aucun rêve)
    kind: str = ""
    emotion: str = ""
    vividness: float = 0.0
    #: elle s'en souvient : il lui reviendra dans la matinée
    remembered: bool = False
    #: les pensées que la digestion de la nuit a apaisées
    eased: int = 0


class Touched(Payload):
    """Ce qu'un message dit d'elle et qui touche son estime : un merci, un
    compliment, une insulte qui la vise. Un jugement lu dans la forme du
    message (sans modèle), enregistré : le rejeu retombe sur la même estime."""

    person: str
    handle: str
    message: int
    kind: str  # THANKED | COMPLIMENTED | INSULTED


NIGHTMARE, PLEASANT, ASSOCIATIVE, MUNDANE = "nightmare", "pleasant", "associative", "mundane"
#: Un rêve triste, sans peur : ce qui pèse sans menacer.
MELANCHOLIC = "melancholic"
DREAM_KINDS = (NIGHTMARE, PLEASANT, MELANCHOLIC, ASSOCIATIVE, MUNDANE)
THANKED, COMPLIMENTED, INSULTED = "thanked", "complimented", "insulted"

PERSONA_REVISED = event_type("self.persona_revised", OWNER, PersonaRevised, public=True, version=2,
                             upcasters={1: _zone_repaired})
JOURNALED = event_type("self.journaled", OWNER, Journaled, public=True, content=("text",), subjects=("about",),
                       authored=True)
DREAMT = event_type("self.dreamt", OWNER, Dreamt, public=True, content=("text",), subjects=("about",),
                    authored=True)
NARRATED = event_type("self.narrated", OWNER, Narrated, public=True, content=("text",), subjects=("about",),
                      authored=True)
WOKE_WITH = event_type("self.woke_with", OWNER, WokeWith, public=True)
TOUCHED = event_type("self.touched", OWNER, Touched, public=True, subjects=("person",))

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


#: Le journal de la dernière journée vécue avant aujourd'hui (``None`` s'il n'y en a pas) — pas forcément
#: celui d'hier : ``day`` le dit.
YESTERDAY = FactKey("self.yesterday", type=object, time_varying=True)
#: Le rêve de la nuit dernière dont elle s'est souvenue au réveil (``None`` : aucun — la plupart des matins).
DREAM_RESIDUE = FactKey("self.dream_residue", type=object, time_varying=True)
