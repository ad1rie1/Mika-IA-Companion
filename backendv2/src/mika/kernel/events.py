"""Événements : types déclarés par leur propriétaire, brouillons, enveloppes.

Règle des charges utiles : un événement porte des observations, des
intentions, des deltas et des tirages enregistrés (texte d'un modèle, hasard,
saisie, jugement qui a demandé une E/S) — jamais un état recalculé.

Les textes libres vivent dans des champs ``Content`` : à l'ajout, le magasin
les range dans une table à part (effaçable pour l'oubli) et l'événement ne
garde qu'une référence. Les réducteurs ne voient donc jamais de texte.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator


class Payload(BaseModel):
    """Charge utile d'un événement : gelée, sans champ inconnu."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Content(BaseModel):
    """Un texte libre, rangé hors de l'enveloppe.

    Côté émetteur : ``Content.of("…")``. Côté réducteur : seule ``ref`` est
    renseignée. Côté projection (même transaction, ou relecture) : ``text``
    est restitué tant que le contenu n'a pas été oublié.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str | None = None
    text: str | None = None
    level: int = 0  # sensibilité (0 = anodin) ; la table des niveaux vit dans vocab

    @classmethod
    def of(cls, text: str, level: int = 0) -> Content:
        return cls(text=text, level=level)

    @model_validator(mode="after")
    def _one_side(self) -> Content:
        if self.ref is None and self.text is None:
            raise ValueError("un contenu porte un texte ou une référence")
        return self


class VoiceProvenance(Payload):
    """Preuve qu'un texte a été écrit par sa voix, avec sa persona."""

    call_id: str
    persona_hash: str
    role: str
    model: str


class Origin(enum.StrEnum):
    EXTERNAL = "external"
    PROCESS = "process"
    TOOL = "tool"
    KERNEL = "kernel"
    GENESIS = "genesis"


P = TypeVar("P", bound=Payload)

Upcaster = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True, eq=False)
class EventType(Generic[P]):
    name: str
    owner: str
    payload: type[P]
    version: int = 1
    public: bool = False
    upcasters: Mapping[int, Upcaster] = field(default_factory=dict)
    content_fields: frozenset[str] = frozenset()
    subject_fields: frozenset[str] = frozenset()
    authored: bool = False

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EventType) and other.name == self.name

    def __repr__(self) -> str:
        return f"EventType({self.name!r})"

    def draft(self, payload: P | None = None, /, *, dedupe_key: str | None = None, **fields: Any) -> Draft[P]:
        """Un brouillon, depuis une charge utile ou ses champs (``payload`` est
        positionnel : un champ peut s'appeler ``data``)."""
        if payload is None:
            payload = self.payload(**fields)
        return Draft(self, payload, dedupe_key)

    def upcast(self, version: int, raw: dict[str, Any]) -> dict[str, Any]:
        """JSON brut d'une version ancienne → JSON de la version courante."""
        if version > self.version:
            raise ValueError(f"{self.name} v{version} est plus récent que le code (v{self.version})")
        while version < self.version:
            step = self.upcasters.get(version)
            if step is None:
                raise ValueError(f"{self.name} : pas d'upcaster depuis v{version}")
            raw = step(dict(raw))
            version += 1
        return raw


@dataclass(frozen=True, slots=True)
class Draft(Generic[P]):
    type: EventType[P]
    data: P
    dedupe_key: str | None = None


@dataclass(frozen=True, slots=True)
class Event(Generic[P]):
    seq: int
    id: str
    type: EventType[P]
    at: int
    data: P
    causation: str | None
    correlation: str
    basis: int
    origin: Origin

    @property
    def name(self) -> str:
        return self.type.name


class EventRegistry:
    """Tous les types d'événements connus, par nom."""

    def __init__(self, types: Iterable[EventType[Any]] = ()) -> None:
        self._by_name: dict[str, EventType[Any]] = {}
        for t in types:
            self.add(t)

    def add(self, t: EventType[Any]) -> None:
        if t.name in self._by_name and self._by_name[t.name] is not t:
            raise ValueError(f"type d'événement déclaré deux fois : {t.name}")
        self._by_name[t.name] = t

    def get(self, name: str) -> EventType[Any]:
        try:
            return self._by_name[name]
        except KeyError:
            raise KeyError(f"type d'événement inconnu : {name}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def all(self) -> list[EventType[Any]]:
        return [self._by_name[k] for k in sorted(self._by_name)]

    def decode(self, name: str, version: int, raw_json: str) -> tuple[EventType[Any], Payload]:
        t = self.get(name)
        if version == t.version:
            return t, t.payload.model_validate_json(raw_json)
        raw = t.upcast(version, json.loads(raw_json))
        return t, t.payload.model_validate(raw)

    def decode_or_retired(self, name: str, version: int, raw_json: str) -> tuple[EventType[Any], Payload]:
        """Comme ``decode`` ; un type que plus personne ne déclare (une faculté ou un plugin retiré de la
        composition) se relit comme un événement **retiré** : son contenu brut, aucun réducteur — le journal
        reste lisible, la vie continue sans ce qu'elle ne sait plus faire."""
        if name in self._by_name:
            return self.decode(name, version, raw_json)
        try:
            raw = json.loads(raw_json)
        except ValueError:
            raw = {}
        return retired(name, version), Retired(data=raw if isinstance(raw, dict) else {})


#: Le propriétaire d'un événement retiré (son type n'est plus déclaré par personne).
RETIRED_OWNER = "retired"


class Retired(Payload):
    """La charge utile d'un événement retiré, telle qu'elle était écrite."""

    data: dict[str, Any] = {}


def retired(name: str, version: int = 1) -> EventType[Any]:
    """Le type d'un événement que plus personne ne déclare : aucun réducteur ne le voit, rien ne l'émet."""
    return EventType(name=name, owner=RETIRED_OWNER, payload=Retired, version=version)


def event_type(
    name: str,
    owner: str,
    payload: type[P],
    *,
    version: int = 1,
    public: bool = False,
    upcasters: Mapping[int, Upcaster] | None = None,
    content: Iterable[str] = (),
    subjects: Iterable[str] = (),
    authored: bool = False,
) -> EventType[P]:
    """Déclare un type d'événement hors d'une faculté (dans un contrat) ; la
    faculté propriétaire l'adopte ensuite par ``Faculty.declare``."""
    return EventType(
        name=name, owner=owner, payload=payload, version=version, public=public,
        upcasters=dict(upcasters or {}), content_fields=frozenset(content),
        subject_fields=frozenset(subjects), authored=authored,
    )


def content_fields_of(payload: Payload, names: frozenset[str]) -> dict[str, Content]:
    out: dict[str, Content] = {}
    for n in names:
        v = getattr(payload, n, None)
        if isinstance(v, Content):
            out[n] = v
    return out
