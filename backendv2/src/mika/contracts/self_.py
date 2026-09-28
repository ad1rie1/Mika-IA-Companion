"""Contrat de ``self`` : la persona (un document), le tempérament."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactKey
from mika.vocab.temperament import Temperament

OWNER = "self"


class PersonaDoc(BaseModel):
    """Le personnage, rédigé. Chaque liste est une suite de phrases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "Mika"
    description: str = ""
    language: str = "français"
    tone: str = ""
    traits: tuple[str, ...] = ()
    quirks: tuple[str, ...] = ()
    vulnerabilities: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    speech: tuple[str, ...] = ()
    greetings: tuple[str, ...] = ()
    timezone: str = "Europe/Paris"
    temperament: Temperament = Field(default_factory=Temperament)


class PersonaRevised(Payload):
    persona: PersonaDoc


PERSONA_REVISED = event_type("self.persona_revised", OWNER, PersonaRevised, public=True)

PERSONA = FactKey("self.persona", type=PersonaDoc)
