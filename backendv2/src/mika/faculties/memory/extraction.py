"""La consolidation, côté modèle : ce qu'on lui montre, ce qu'on attend en retour.

Sortie structurée par un outil déclaré (``record_memories``) ; à défaut,
le premier objet JSON du texte. Un élément illisible est écarté, jamais la
fenêtre entière. Les noms sont rattachés aux personnes présentes ; un nom
inconnu devient une personne mentionnée (``name:…``) ; elle-même n'est pas
une personne « concernée » (c'est sa propre vie).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mika.kernel.clock import instant
from mika.ports.llm import LLMResponse, ToolDecl
from mika.vocab.people import fold
from mika.vocab.privacy import Sensitivity

TOOL_NAME = "record_memories"
SELF_NAMES = frozenset({"mika", "moi", "je", "elle-meme", "elle meme"})
IMPORTANCE = {1: 0.2, 2: 0.45, 3: 0.7, 4: 0.95}
SENSITIVITY = {"anodin": Sensitivity.ANODYNE, "personnel": Sensitivity.PERSONAL, "confidence": Sensitivity.CONFIDENCE}
ORIGIN = {"dit": "told", "observe": "observed", "observé": "observed", "deduit": "inferred", "déduit": "inferred"}
MAX_SOUVENIRS, MAX_BELIEFS, MAX_PROMISES = 12, 20, 6


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class XSouvenir(_Lenient):
    texte: str = Field(min_length=3, max_length=600)
    personnes: list[str] = Field(default_factory=list)
    emotion: str | None = None
    importance: int = Field(default=2, ge=1, le=4)
    sensibilite: str | None = None


class XCroyance(_Lenient):
    texte: str = Field(min_length=3, max_length=600)
    personnes: list[str] = Field(default_factory=list)
    origine: str = "dit"
    source: str | None = None
    confiance: float = Field(default=0.7, ge=0.0, le=1.0)
    importance: int = Field(default=2, ge=1, le=4)
    sensibilite: str | None = None
    remplace: int | None = None


class XPromesse(_Lenient):
    texte: str = Field(min_length=3, max_length=400)
    envers: str
    echeance: str | None = None


class XTenue(_Lenient):
    id: int
    statut: str


class Extraction(_Lenient):
    souvenirs: list[XSouvenir] = Field(default_factory=list)
    croyances: list[XCroyance] = Field(default_factory=list)
    promesses: list[XPromesse] = Field(default_factory=list)
    promesses_tenues: list[XTenue] = Field(default_factory=list)


def tool() -> ToolDecl:
    return ToolDecl(TOOL_NAME, "Enregistre ce que Mika retient de ces conversations.", Extraction.model_json_schema())


SYSTEM = """Tu es la mémoire de Mika. On te montre des extraits de ses conversations ; tu décides ce qu'elle en \
gardera, comme une personne qui repense à sa journée : pas tout, l'important.

Trois sortes de choses :
- des souvenirs : ce qu'elle a vécu, à la première personne (« J'ai consolé Adrien : son chat Pixel est mort ce \
matin »). Un souvenir se suffit à lui-même : des prénoms, jamais « il », « l'utilisateur » ou « la personne ».
- des croyances : des faits sur quelqu'un ou sur le monde (« Le chat d'Adrien s'appelait Pixel »), avec qui les a \
dits (source) et d'où elle le tient (origine : dit, observé ou déduit). Si une croyance déjà connue est contredite, \
donne dans « remplace » le numéro qu'elle remplace. Ne répète pas une croyance déjà connue.
- des promesses : ce que Mika elle-même a promis de faire pour quelqu'un, avec l'échéance si elle a été dite \
(AAAA-MM-JJ). Si une promesse en cours a été tenue ou abandonnée, indique-la dans promesses_tenues.

Pour chaque élément : « personnes », la liste des prénoms des personnes qu'il concerne (toujours, même quand c'est \
évident ; jamais Mika elle-même) ; l'importance (1 anodin, 2 notable, 3 important, 4 marquant) ; et la sensibilité — \
anodin (ce qu'on dirait devant n'importe qui : goûts, loisirs, anecdotes), personnel (confié, pas secret ; au moins \
personnel dès que ça touche la santé, le travail, l'argent, la famille, les amours ou les émotions de quelqu'un), \
confidence (à ne répéter à personne). Dans le doute : personnel.
N'invente rien. Ce que Mika improvise sur son quotidien n'est pas un fait durable. Une fenêtre sans rien \
d'important donne des listes vides.
Réponds uniquement en appelant l'outil record_memories."""


@dataclass(frozen=True, slots=True)
class Line:
    seq: int
    at: int
    speaker: str  # le nom affiché, ou « Mika »
    text: str


@dataclass(frozen=True, slots=True)
class Thread:
    person: str
    name: str
    lines: tuple[Line, ...]


def render(threads: Sequence[Thread], *, now: datetime, beliefs: Sequence[tuple[int, str]],
           promises: Sequence[tuple[int, str, str]]) -> str:
    """Le message de la fenêtre : la date, les personnes, ce qui est déjà su,
    les promesses en cours, puis chaque conversation dans l'ordre."""
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
              "novembre", "décembre"]
    out = [f"Aujourd'hui : {days[now.weekday()]} {now.day} {months[now.month - 1]} {now.year}, {now:%H h %M}.",
           "Personnes : " + ", ".join(t.name for t in threads) + "."]
    if beliefs:
        out += ["", "Croyances déjà connues :"] + [f"[#{i}] {text}" for i, text in beliefs]
    if promises:
        out += ["", "Promesses en cours :"] + [f"[#{i}] (à {who}) {text}" for i, who, text in promises]
    for t in threads:
        out += ["", f"Conversation avec {t.name} :"]
        out += [f"[#{ln.seq}] {datetime.fromtimestamp(ln.at / 1e6, now.tzinfo):%H:%M} {ln.speaker} : {ln.text}"
                for ln in t.lines]
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
    out = Extraction()
    for key, model, cap in (("souvenirs", XSouvenir, MAX_SOUVENIRS), ("croyances", XCroyance, MAX_BELIEFS),
                            ("promesses", XPromesse, MAX_PROMISES), ("promesses_tenues", XTenue, 50)):
        items = raw.get(key) or []
        if not isinstance(items, list):
            continue
        kept = []
        for item in items[:cap]:
            try:
                kept.append(model.model_validate(item))
            except ValidationError:
                continue
        setattr(out, key, kept)
    return out


def resolve(names: Sequence[str], people: Mapping[str, str]) -> tuple[str, ...]:
    """Des noms → des clés de personnes. ``people`` : nom replié → clé."""
    keys: set[str] = set()
    for name in names:
        folded = fold(str(name))
        if not folded or folded in SELF_NAMES:
            continue
        key = people.get(folded) or people.get(folded.split()[0])
        keys.add(key or f"name:{folded}")
    return tuple(sorted(keys))


def sensitivity(value: str | None, *, has_person: bool) -> int:
    if value:
        found = SENSITIVITY.get(fold(value))
        if found is not None:
            return int(found)
    return int(Sensitivity.PERSONAL if has_person else Sensitivity.ANODYNE)


def due(value: str | None, tz: ZoneInfo) -> int | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.strip())
    except ValueError:
        try:
            d = datetime.combine(date.fromisoformat(value.strip()[:10]), time(18, 0))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz)
    return instant(d)
