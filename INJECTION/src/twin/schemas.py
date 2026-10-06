"""Ce que Claude Code rend quand il lit ses archives : des schémas validés, ancrés sur l'archive.

Les champs reprennent ceux de la mémoire du moteur (``mika.faculties.memory.extraction`` :
souvenirs, croyances, promesses, événements, avec importance, sensibilité, secret) pour
que le rejoueur puisse les lui servir tels quels pendant l'avance rapide. Une différence :
ici, ``messages`` désigne des numéros de messages **de l'archive** (``[m123]`` → 123), et
``personnes`` des personnes du corpus (``p12``). Le rejoueur les traduira en numéros du
journal et en jetons de conversation.

Le schéma est lu avec indulgence (champs inconnus ignorés, un élément invalide écarté sans
perdre le reste), comme le fait le moteur.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

#: les 29 émotions du moteur (``mika.vocab.affect.Emotion``), dans son ordre — un test vérifie l'accord
EMOTIONS = ("neutral", "happy", "excited", "love", "proud", "grateful", "playful", "amused", "hopeful", "relieved",
            "sad", "angry", "scared", "disgusted", "frustrated", "lonely", "anxious", "bored", "jealous", "surprised",
            "thinking", "confused", "embarrassed", "nostalgic", "dreamy", "determined", "mischievous", "curious",
            "melancholic")
Emotion = Literal[
    "neutral", "happy", "excited", "love", "proud", "grateful", "playful", "amused", "hopeful", "relieved",
    "sad", "angry", "scared", "disgusted", "frustrated", "lonely", "anxious", "bored", "jealous", "surprised",
    "thinking", "confused", "embarrassed", "nostalgic", "dreamy", "determined", "mischievous", "curious",
    "melancholic"]
Sensitivity = Literal["anodin", "personnel", "confidence"]


def _ints(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    out: list[int] = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
        else:
            out += [int(m) for m in re.findall(r"\d+", str(v))]
    return out


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MessageEmotion(_Lenient):
    id: int = Field(description="le numéro d'un de SES messages ([m123] → 123)")
    emotion: Emotion
    intensite: float = Field(ge=0.0, le=1.0, description="0,2 à peine ; 0,5 net ; 0,8 fort ; 1 submergée")

    @field_validator("id", mode="before")
    @classmethod
    def lenient_id(cls, v: Any) -> int:
        found = _ints(v)
        if not found:
            raise ValueError("numéro de message illisible")
        return found[0]


class _Item(_Lenient):
    texte: str = Field(min_length=3, max_length=600)
    personnes: list[str] = Field(default_factory=list, description="qui c'est concerne : p12 pour une personne "
                                 "de la liste, un prénom sinon ; jamais elle-même")
    messages: list[int] = Field(default_factory=list, description="les numéros des messages d'où tu le tires")
    importance: int = Field(default=2, ge=1, le=4, description="1 anodin, 2 notable, 3 important, 4 marquant")
    sensibilite: Sensitivity = "personnel"
    secret: bool = False

    @field_validator("messages", mode="before")
    @classmethod
    def lenient_messages(cls, v: Any) -> list[int]:
        return _ints(v)

    @field_validator("personnes", mode="before")
    @classmethod
    def lenient_people(cls, v: Any) -> list[str]:
        if v is None:
            return []
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]


class Souvenir(_Item):
    emotion: Emotion | None = None


class Croyance(_Item):
    origine: Literal["dit", "observe", "deduit"] = "dit"
    confiance: float = Field(default=0.7, ge=0.0, le=1.0)
    sur_elle: bool = Field(default=False, description="ce qu'elle dit ou pense d'elle-même")
    genre: Literal["anecdote", "gout", "avis", "fait"] | None = None
    entre_vous: bool = Field(default=False, description="un surnom, une blague, une expression à eux deux")


class Promesse(_Lenient):
    texte: str = Field(min_length=3, max_length=400, description="ce qu'elle a promis, à l'infinitif")
    envers: str = Field(description="p12, ou un prénom")
    echeance: str | None = Field(default=None, description="AAAA-MM-JJ ou AAAA-MM-JJTHH:MM")
    messages: list[int] = Field(default_factory=list)

    @field_validator("messages", mode="before")
    @classmethod
    def lenient_messages(cls, v: Any) -> list[int]:
        return _ints(v)


class Evenement(_Item):
    texte: str = Field(min_length=3, max_length=300)
    quand: str = Field(min_length=4, max_length=40, description="AAAA-MM-JJ (ou AAAA-MM-JJTHH:MM, ou AAAA-MM)")
    en_cours: bool = False
    a_feter: bool = False


class Reve(_Lenient):
    """Un rêve qu'elle raconte (« cette nuit j'ai rêvé que… ») : il deviendra un vrai rêve de sa nuit."""

    texte: str = Field(min_length=10, max_length=1500, description="le rêve, à la première personne, avec ses mots")
    nuit: str | None = Field(default=None, description="AAAA-MM-JJ : la nuit qui finit ce matin-là, si on la sait")
    emotion: Emotion | None = None
    personnes: list[str] = Field(default_factory=list)
    messages: list[int] = Field(default_factory=list)

    @field_validator("messages", mode="before")
    @classmethod
    def lenient_messages(cls, v: Any) -> list[int]:
        return _ints(v)


class SessionLight(_Lenient):
    """Lecture légère (palier B) : ce qu'elle a ressenti et de quoi il s'agissait."""

    seance: str = Field(description="l'identifiant de la séance (s123 ou d45)")
    resume: str = Field(min_length=3, max_length=1500, description="2 à 5 phrases, à la première personne, dates "
                        "en absolu")
    humeur_debut: Emotion = "neutral"
    humeur_fin: Emotion = "neutral"
    emotions: list[MessageEmotion] = Field(default_factory=list, description="une entrée par message d'ELLE")
    restes: list[str] = Field(default_factory=list, description="ce qui pourrait lui revenir en rêve : images, "
                              "lieux, inquiétudes, visages (quelques mots chacun)")
    signifiance: float = Field(default=0.3, ge=0.0, le=1.0, description="ce que ce moment pèse dans sa vie")


class SessionFull(SessionLight):
    """Lecture à fond (palier A)."""

    souvenirs: list[Souvenir] = Field(default_factory=list)
    croyances: list[Croyance] = Field(default_factory=list)
    promesses: list[Promesse] = Field(default_factory=list)
    evenements: list[Evenement] = Field(default_factory=list)
    reves: list[Reve] = Field(default_factory=list)


class BatchFull(_Lenient):
    seances: list[SessionFull]


class BatchLight(_Lenient):
    seances: list[SessionLight]


def lenient_list(model: type[BaseModel], items: Any) -> tuple[list[Any], int]:
    """Valide élément par élément : un élément invalide est écarté, le reste est gardé."""
    kept, dropped = [], 0
    for raw in items if isinstance(items, list) else []:
        try:
            kept.append(model.model_validate(raw))
        except ValidationError:
            dropped += 1
    return kept, dropped


def parse_batch(data: dict[str, Any] | None, full: bool) -> tuple[list[SessionLight], int]:
    """Les séances d'une réponse, validées avec indulgence ; le nombre d'éléments écartés."""
    if not isinstance(data, dict):
        raise ValueError("réponse sans objet JSON")
    sessions: list[SessionLight] = []
    dropped = 0
    for raw in data.get("seances") or []:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        base = {k: v for k, v in raw.items() if k not in ("emotions", "souvenirs", "croyances", "promesses",
                                                         "evenements", "reves")}
        emotions, d = lenient_list(MessageEmotion, raw.get("emotions"))
        dropped += d
        extra: dict[str, Any] = {"emotions": emotions}
        if full:
            for key, model in (("souvenirs", Souvenir), ("croyances", Croyance), ("promesses", Promesse),
                               ("evenements", Evenement), ("reves", Reve)):
                items, d = lenient_list(model, raw.get(key))
                extra[key] = items
                dropped += d
        try:
            sessions.append((SessionFull if full else SessionLight).model_validate({**base, **extra}))
        except ValidationError:
            dropped += 1
    return sessions, dropped
