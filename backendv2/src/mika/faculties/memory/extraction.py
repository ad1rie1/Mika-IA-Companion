"""La consolidation, côté modèle : ce qu'on lui montre, ce qu'on attend en retour.

**Une conversation par appel** : un fil privé avec une personne, ou un salon
(un groupe, tout le monde y lit tout). Chaque personne y porte un **jeton**
unique (« Alice [P1] ») : deux Alice ne se confondent jamais, et le modèle
désigne les gens de la conversation par leur jeton. Un nom qui n'en a pas se
résout d'abord dans la conversation, puis parmi toutes les personnes qu'elle
connaît quand un seul porte ce nom ; sinon c'est une personne connue de nom
seulement (``name:…``). Elle-même n'est pas une personne « concernée » (c'est
sa propre vie).

Sortie structurée par un outil déclaré (``record_memories``) ; à défaut, le
premier objet JSON du texte, lu avec indulgence (« contenu » pour « texte »…).
Un élément illisible est écarté, jamais la fenêtre entière.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from mika.kernel.clock import instant
from mika.ports.llm import LLMResponse, ToolDecl
from mika.vocab.people import fold
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import stems

TOOL_NAME = "record_memories"
SELF_NAMES = frozenset({"mika", "moi", "je", "elle-meme", "elle meme", "elle"})
IMPORTANCE = {1: 0.2, 2: 0.45, 3: 0.7, 4: 0.95}
SENSITIVITY = {"anodin": Sensitivity.ANODYNE, "anodine": Sensitivity.ANODYNE, "anodyne": Sensitivity.ANODYNE,
               "personnel": Sensitivity.PERSONAL, "personnelle": Sensitivity.PERSONAL, "personal": Sensitivity.PERSONAL,
               "confidence": Sensitivity.CONFIDENCE, "confidentiel": Sensitivity.CONFIDENCE,
               "confidential": Sensitivity.CONFIDENCE, "intime": Sensitivity.CONFIDENCE}
ORIGIN = {"dit": "told", "observe": "observed", "observé": "observed", "deduit": "inferred", "déduit": "inferred"}
MAX_SOUVENIRS, MAX_BELIEFS, MAX_PROMISES, MAX_EVENTS = 12, 20, 6, 8
#: ce qui, dit par la personne, en fait un secret quoi qu'en dise le modèle (replié, sans accents)
SECRET_MARKERS = ("dis le a personne", "dis a personne", "le dis a personne", "le repete a personne", "repete pas",
                  "repete a personne", "entre nous", "garde le pour toi", "garde ca pour toi", "c est un secret",
                  "c est secret", "motus", "ne lui dis pas", "lui dis pas", "ne lui dis surtout pas",
                  "lui dis surtout pas", "dis lui pas", "le lui dis pas", "ne lui en parle pas", "lui en parle pas",
                  "lui repete pas", "le dis a personne", "n en parle a personne", "en parle a personne")
TOKEN = re.compile(r"\[?\bP(\d{1,3})\]?")

_TEXT = AliasChoices("texte", "contenu", "description", "text", "quoi")
_SENS = AliasChoices("sensibilite", "sensibilité", "sensitivity")


def _ints(value: Any) -> list[int]:
    """Des numéros de messages, tels qu'un modèle les écrit (25, « #25 », « [#25] »)."""
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    out = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
        else:
            out += [int(m) for m in re.findall(r"\d+", str(v))]
    return out


def _names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value] if isinstance(value, list) else []


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Item(_Lenient):
    texte: str = Field(min_length=3, max_length=600, validation_alias=_TEXT)
    sur_elle: bool = Field(default=False, description="ce que Mika raconte d'elle-même, de sa vie de tous les jours")
    personnes: list[str] = Field(default_factory=list, description="qui c'est concerne : le jeton ([P1]) pour "
                                 "quelqu'un de la conversation, le prénom pour quelqu'un d'autre ; jamais Mika")
    sensibilite: str | None = Field(default=None, validation_alias=_SENS,
                                    description="anodin, personnel ou confidence")
    secret: bool = Field(default=False, description="vrai si la personne a demandé de ne pas le répéter, à "
                                                    "personne ou à quelqu'un en particulier ; aussi ce qui laisse "
                                                    "deviner un secret")
    messages: list[int] = Field(default_factory=list, description="les numéros (#) des messages d'où tu le tires")

    @field_validator("personnes", mode="before")
    @classmethod
    def lenient_people(cls, v: Any) -> list[str]:
        return _names(v)

    @field_validator("messages", mode="before")
    @classmethod
    def lenient_messages(cls, v: Any) -> list[int]:
        return _ints(v)


class XSouvenir(_Item):
    emotion: str | None = None
    importance: int = Field(default=2, ge=1, le=4)


class XCroyance(_Item):
    origine: str = Field(default="dit", validation_alias=AliasChoices("origine", "origin"))
    source: str | None = None
    confiance: float = Field(default=0.7, ge=0.0, le=1.0)
    importance: int = Field(default=2, ge=1, le=4)
    remplace: int | None = None


class XPromesse(_Lenient):
    texte: str = Field(min_length=3, max_length=400, validation_alias=_TEXT,
                       description="ce qu'elle a promis, à l'infinitif")
    envers: str
    echeance: str | None = Field(default=None, validation_alias=AliasChoices("echeance", "échéance"))
    messages: list[int] = Field(default_factory=list)

    @field_validator("messages", mode="before")
    @classmethod
    def lenient_messages(cls, v: Any) -> list[int]:
        return _ints(v)


class XTenue(_Lenient):
    id: int
    statut: str


class XEvenement(_Item):
    texte: str = Field(min_length=3, max_length=300, validation_alias=_TEXT,
                       description="ce qui va arriver, en quelques mots (« son entretien chez Ubisoft »)")
    quand: str = Field(min_length=8, max_length=40, description="AAAA-MM-JJ, ou AAAA-MM-JJTHH:MM si l'heure est dite")


class Extraction(_Lenient):
    souvenirs: list[XSouvenir] = Field(default_factory=list)
    croyances: list[XCroyance] = Field(default_factory=list)
    promesses: list[XPromesse] = Field(default_factory=list)
    promesses_tenues: list[XTenue] = Field(default_factory=list)
    evenements: list[XEvenement] = Field(default_factory=list, validation_alias=AliasChoices("evenements",
                                                                                             "événements"))
    confidentiel: list[int] = Field(default_factory=list, description="les numéros des croyances déjà connues "
                                    "que la personne vient de demander de garder pour soi")

    @field_validator("confidentiel", mode="before")
    @classmethod
    def lenient_ids(cls, v: Any) -> list[int]:
        return _ints(v)


def tool() -> ToolDecl:
    return ToolDecl(TOOL_NAME, "Enregistre ce que Mika retient de cette conversation.", Extraction.model_json_schema())


SYSTEM = """Tu es la mémoire de Mika. On te montre une de ses conversations — un fil privé avec une personne, ou \
un salon où plusieurs personnes parlent ; tu décides ce qu'elle en gardera, comme quelqu'un qui repense à sa \
journée : pas tout, l'important.

Chaque personne de la conversation est marquée d'un jeton : « Alice [P1] ». Deux personnes peuvent porter le même \
prénom ; le jeton, lui, est unique.

Ce que tu peux retenir :
- des souvenirs : ce qu'elle a vécu, à la première personne (« J'ai consolé Adrien : son chat Pixel est mort ce \
matin »). Un souvenir se suffit à lui-même : des prénoms, jamais « il », « l'utilisateur » ou « la personne ».
- des croyances : des faits sur quelqu'un ou sur le monde (« Le chat d'Adrien s'appelait Pixel »), avec qui les a \
dits (source) et d'où elle le tient (origine : dit, observé ou déduit). Si une croyance déjà connue est contredite, \
donne dans « remplace » le numéro qu'elle remplace. Ne répète pas une croyance déjà connue.
- ce que Mika raconte d'elle-même, sa petite vie de tous les jours (« J'ai ressorti mon fer à souder pour réparer \
ma lampe ») : une croyance à la première personne, avec « sur_elle » vrai, sans personne, importance 1 — elle s'en \
souviendra quelques jours, pour ne pas se contredire.
- des promesses : ce que Mika elle-même a promis de faire pour quelqu'un — une chose à faire, à l'infinitif (« lui \
demander comment s'est passé son entretien »), pas « garder le secret » (ça, c'est le secret lui-même) —, avec \
l'échéance si elle a été dite (AAAA-MM-JJ). Si une promesse en cours a été tenue ou abandonnée, indique-la dans \
promesses_tenues.
- des événements : ce qui va arriver dans la vie de quelqu'un et dont on prend des nouvelles après (un entretien, \
un examen, un rendez-vous médical, un départ, un mariage), en quelques mots (« son entretien chez Ubisoft »), avec \
sa date dans « quand » (AAAA-MM-JJ, ou AAAA-MM-JJTHH:MM si l'heure est dite), calculée d'après la date \
d'aujourd'hui. Seulement ce qui est à venir et daté.

Pour chaque élément :
- « personnes » : qui il concerne — le jeton pour quelqu'un de la conversation ([P1]), le prénom pour quelqu'un \
d'autre ; jamais Mika elle-même ; toujours, même quand c'est évident ;
- « messages » : les numéros des messages d'où tu le tires (#) — c'est ce qui dit qui le lui a confié ;
- l'importance (1 anodin, 2 notable, 3 important, 4 marquant) ;
- la sensibilité — anodin (ce qu'on dirait devant n'importe qui : goûts, loisirs, anecdotes ; ce qui a été annoncé \
à tout un groupe), personnel (au moins personnel dès que ça touche la santé, le travail, l'argent, la famille, les \
amours ou les émotions de quelqu'un), confidence (lourd, intime : ce qu'on ne raconte qu'à des proches). Dans le \
doute : personnel ;
- « secret » : vrai si la personne a demandé de ne pas le répéter — à personne (« dis-le à personne », « entre \
nous », « garde-le pour toi ») ou à quelqu'un en particulier (« ne lui dis pas »). Tout ce qui laisse deviner un \
secret est secret aussi. Si elle le demande pour une croyance déjà connue, donne son numéro dans « confidentiel ».
Dans un salon, ce qui est marqué « (entre eux) » ne lui était pas adressé : n'en retiens que ce qui compte.
N'invente rien. Une conversation sans rien d'important donne des listes vides.
Réponds uniquement en appelant l'outil record_memories."""


@dataclass(frozen=True, slots=True)
class Speaker:
    token: str  # « P1 »
    person: str  # la clé de personne
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} [{self.token}]"


@dataclass(frozen=True, slots=True)
class Line:
    seq: int
    at: int
    speaker: str  # le libellé affiché (« Alice [P1] »), ou « Mika »
    text: str
    person: str | None = None  # la clé de personne de qui parle (``None`` : Mika)
    aside: bool = False  # dans un salon, pas adressé à Mika


@dataclass(frozen=True, slots=True)
class Conversation:
    """Un fil privé (``room`` vide, une personne) ou un salon."""

    key: str
    speakers: tuple[Speaker, ...]
    lines: tuple[Line, ...]
    room: str | None = None

    @property
    def persons(self) -> tuple[str, ...]:
        return tuple(sorted({s.person for s in self.speakers}))

    @property
    def seqs(self) -> tuple[int, ...]:
        return tuple(ln.seq for ln in self.lines)

    def author(self, seq: int) -> str | None:
        return next((ln.person for ln in self.lines if ln.seq == seq), None)


DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]


def day_words(d: date) -> str:
    return f"{DAYS[d.weekday()]} {'1er' if d.day == 1 else d.day} {MONTHS[d.month - 1]}"


def render(conv: Conversation, *, now: datetime, beliefs: Sequence[tuple[int, str]],
           promises: Sequence[tuple[int, str, str]]) -> str:
    """Le message d'une conversation : la date, qui parle, ce qui est déjà
    su, les promesses en cours, puis les messages (avec la date dès qu'elle change)."""
    out = [f"Aujourd'hui : {day_words(now.date())} {now.year}, {now:%H h %M}."]
    who = ", ".join(s.label for s in conv.speakers)
    if conv.room:
        out.append(f"Un salon de groupe (tout le monde y lit tout) : {who}.")
    else:
        out.append(f"Conversation privée avec {who}.")
    if beliefs:
        out += ["", "Croyances déjà connues :"] + [f"[#{i}] {text}" for i, text in beliefs]
    if promises:
        out += ["", "Promesses en cours :"] + [f"[#{i}] (à {whom}) {text}" for i, whom, text in promises]
    out += ["", "Les messages :"]
    day: date | None = None
    for ln in conv.lines:
        moment = datetime.fromtimestamp(ln.at / 1e6, now.tzinfo)
        if moment.date() != day:
            day = moment.date()
            out.append(f"— {day_words(day)} —")
        aside = " (entre eux)" if ln.aside else ""
        out.append(f"[#{ln.seq}] {moment:%H:%M} {ln.speaker}{aside} : {ln.text}")
    return "\n".join(out)


def parse(resp: LLMResponse) -> Extraction | None:
    """L'outil s'il a été appelé, sinon le premier objet JSON du texte ; les
    éléments illisibles sont écartés un à un."""
    raw: Any = None
    for call in resp.tool_calls:
        if call.name == TOOL_NAME:
            raw = dict(call.args)
            break
    if raw is None:
        match = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not match:
            return None
        try:
            raw = json.loads(match.group(0))
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    raw = {fold(str(k)): v for k, v in raw.items()}
    out = Extraction()
    for key, model, cap in (("souvenirs", XSouvenir, MAX_SOUVENIRS), ("croyances", XCroyance, MAX_BELIEFS),
                            ("promesses", XPromesse, MAX_PROMISES), ("promesses_tenues", XTenue, 50),
                            ("evenements", XEvenement, MAX_EVENTS)):
        items = raw.get(key) or []
        if isinstance(items, str):
            try:
                items = json.loads(items)  # certains modèles passent la liste en texte
            except ValueError:
                continue
        if not isinstance(items, list):
            continue
        kept = []
        for item in items[:cap]:
            try:
                kept.append(model.model_validate(item))
            except ValidationError:
                continue
        setattr(out, key, kept)
    out.confidentiel = _ints(raw.get("confidentiel"))
    return out


@dataclass(frozen=True, slots=True)
class People:
    """Comment des noms deviennent des clés : les jetons de la conversation,
    puis ses prénoms (s'ils ne sont qu'à une personne), puis l'annuaire de
    tous ceux qu'elle connaît (s'il n'y en a qu'un de ce nom)."""

    tokens: Mapping[str, str] = field(default_factory=dict)
    local: Mapping[str, str] = field(default_factory=dict)
    directory: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def of(cls, speakers: Sequence[Speaker], directory: Mapping[str, tuple[str, ...]]) -> People:
        tokens = {s.token.lower(): s.person for s in speakers}
        named: dict[str, set[str]] = {}
        for s in speakers:
            folded = " ".join(fold(s.name).split())
            for key in {folded, *folded.split()[:1]}:
                if key:
                    named.setdefault(key, set()).add(s.person)
        local = {k: next(iter(v)) for k, v in named.items() if len(v) == 1}
        return cls(tokens, local, directory)

    def one(self, raw: str) -> str | None:
        """Une clé, ou ``None`` pour elle-même ou rien."""
        text = str(raw)
        m = TOKEN.search(text)
        if m and f"p{m.group(1)}" in self.tokens:
            return self.tokens[f"p{m.group(1)}"]
        folded = " ".join(fold(TOKEN.sub(" ", text)).split())
        if not folded or folded in SELF_NAMES:
            return None
        first = folded.split()[0]
        key = self.local.get(folded) or self.local.get(first)
        if key is None:
            found = self.directory.get(folded) or self.directory.get(first) or ()
            key = found[0] if len(found) == 1 else None
        return key or f"name:{folded}"

    def resolve(self, names: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted({k for n in names if (k := self.one(n)) is not None}))


def sensitivity(value: str | None, *, has_person: bool) -> int:
    if value:
        found = SENSITIVITY.get(fold(value).strip())
        if found is not None:
            return int(found)
    return int(Sensitivity.PERSONAL if has_person else Sensitivity.ANODYNE)


def says_secret(texts: Sequence[str]) -> bool:
    """La personne a-t-elle demandé de ne pas le répéter ?"""
    for text in texts:
        flat = " ".join(re.sub(r"[^a-z0-9 ]", " ", fold(text)).split())
        if any(marker in flat for marker in SECRET_MARKERS):
            return True
    return False


def echoes(text: str, secrets: Sequence[str], names: set[str]) -> bool:
    """Ce texte laisse-t-il deviner un de ces secrets ? (au moins deux mots du
    sujet en commun — un seul si le secret n'en a qu'un —, prénoms exclus)."""
    mine = stems(text) - names
    for secret in secrets:
        theirs = stems(secret) - names
        if theirs and len(mine & theirs) >= min(2, len(theirs)):
            return True
    return False


def due(value: str | None, tz: ZoneInfo) -> int | None:
    got = when(value, tz)
    return got[0] if got else None


def when(value: str | None, tz: ZoneInfo) -> tuple[int, bool] | None:
    """Une date dite (AAAA-MM-JJ, avec l'heure si elle est dite) : l'instant,
    et si c'est le jour entier (alors 18 h, la fin d'une journée : « jeudi,
    son entretien » est passé jeudi soir)."""
    if not value:
        return None
    text = value.strip()
    try:
        d = datetime.fromisoformat(text)
        all_day = len(text) <= 10
    except ValueError:
        try:
            d, all_day = datetime.combine(date.fromisoformat(text[:10]), time(18, 0)), True
        except ValueError:
            return None
    if all_day:
        d = datetime.combine(d.date(), time(18, 0))
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz)
    return instant(d), all_day
