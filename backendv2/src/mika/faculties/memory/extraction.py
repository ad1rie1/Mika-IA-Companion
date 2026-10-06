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
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from mika.kernel.clock import instant
from mika.ports.llm import LLMResponse, ToolDecl
from mika.vocab.people import clean_tokens, fold
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import WORD, stems, words
from mika.vocab.words import fold as wfold

TOOL_NAME = "record_memories"
#: Comment le modèle la désigne quand c'est elle (repliés) ; son nom s'y ajoute, celui de sa persona (``self_names``).
SELF_NAMES = frozenset({"moi", "je", "elle-meme", "elle meme", "elle"})
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


#: ce qu'elle dit d'elle-même : une anecdote s'efface en quelques jours ; un goût, un avis, un fait de sa vie tient
SELF_KINDS = {"anecdote": "anecdote", "gout": "gout", "gouts": "gout", "avis": "avis", "opinion": "avis",
              "fait": "fait", "biographie": "fait", "vie": "fait"}
DURABLE_SELF = frozenset({"gout", "avis", "fait"})


class _Item(_Lenient):
    texte: str = Field(min_length=3, max_length=600, validation_alias=_TEXT)
    sur_elle: bool = Field(default=False, description="ce qu'elle raconte d'elle-même, de sa vie de tous les jours")
    genre: str | None = Field(default=None, description="pour ce qu'elle dit d'elle-même : anecdote (ce qu'elle a "
                                                        "fait), gout, avis ou fait (sa vie, son histoire)")
    personnes: list[str] = Field(default_factory=list, description="qui c'est concerne : le jeton ([P1]) pour "
                                 "quelqu'un de la conversation, le prénom pour quelqu'un d'autre ; jamais "
                                 "elle-même")
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

    @field_validator("texte", mode="after")
    @classmethod
    def without_tokens(cls, v: str) -> str:
        """Les jetons (« Chloé [P1] ») servent à dire qui c'est, dans « personnes » ; recopiés dans le texte, ils
        finissaient dans son souvenir (« J'ai discuté avec Chloé [P1] »)."""
        return clean_tokens(v)


class XSouvenir(_Item):
    emotion: str | None = None
    importance: int = Field(default=2, ge=1, le=4)


class XCroyance(_Item):
    origine: str = Field(default="dit", validation_alias=AliasChoices("origine", "origin"))
    source: str | None = None
    confiance: float = Field(default=0.7, ge=0.0, le=1.0)
    importance: int = Field(default=2, ge=1, le=4)
    remplace: int | None = None
    entre_vous: bool = Field(default=False, validation_alias=AliasChoices("entre_vous", "entre_nous", "lien"),
                             description="ce qui n'appartient qu'à elle et à cette personne : comment la "
                                         "personne l'appelle (un surnom), le surnom qu'elle lui donne, une blague "
                                         "ou une expression à eux")


class XPromesse(_Lenient):
    texte: str = Field(min_length=3, max_length=400, validation_alias=_TEXT,
                       description="ce qu'elle a promis, à l'infinitif")
    envers: str
    echeance: str | None = Field(default=None, validation_alias=AliasChoices("echeance", "échéance"),
                                 description="AAAA-MM-JJ, ou AAAA-MM-JJTHH:MM si l'heure est dite")
    messages: list[int] = Field(default_factory=list)

    @field_validator("messages", mode="before")
    @classmethod
    def lenient_messages(cls, v: Any) -> list[int]:
        return _ints(v)

    @field_validator("texte", mode="after")
    @classmethod
    def without_tokens(cls, v: str) -> str:
        return clean_tokens(v)


class XTenue(_Lenient):
    id: int
    statut: str


class XEvenement(_Item):
    texte: str = Field(min_length=3, max_length=300, validation_alias=_TEXT,
                       description="ce qui va arriver, en quelques mots (« son entretien chez Ubisoft »)")
    quand: str = Field(min_length=8, max_length=40, description="AAAA-MM-JJ, ou AAAA-MM-JJTHH:MM si l'heure est dite")
    en_cours: bool = Field(default=False, description="une situation qui dure (son chat malade, un déménagement) : "
                                                      "« quand » est le jour où elle a commencé")
    importance: int = Field(default=2, ge=1, le=4, description="ce que ça pèse dans sa vie : 2 un rendez-vous "
                            "ordinaire, une sortie ; 3 un entretien, un examen, une opération, un départ ; 4 un "
                            "mariage, une naissance, un deuil")
    a_feter: bool = Field(default=False, validation_alias=AliasChoices("a_feter", "à_fêter", "a_fêter", "festif"),
                          description="un moment qui se fête (un anniversaire, un mariage, une crémaillère) : on le "
                                      "souhaite le jour même")


class Extraction(_Lenient):
    souvenirs: list[XSouvenir] = Field(default_factory=list)
    croyances: list[XCroyance] = Field(default_factory=list)
    promesses: list[XPromesse] = Field(default_factory=list)
    promesses_tenues: list[XTenue] = Field(default_factory=list)
    evenements: list[XEvenement] = Field(default_factory=list, validation_alias=AliasChoices("evenements",
                                                                                             "événements"))
    confidentiel: list[int] = Field(default_factory=list, description="les numéros des croyances déjà connues "
                                    "que la personne vient de demander de garder pour soi")
    situations_finies: list[int] = Field(default_factory=list, description="les numéros des situations en cours "
                                         "que la personne dit finies")

    @field_validator("confidentiel", "situations_finies", mode="before")
    @classmethod
    def lenient_ids(cls, v: Any) -> list[int]:
        return _ints(v)


def tool(name: str) -> ToolDecl:
    """L'outil de la relecture, au nom de celle dont c'est la mémoire (``name``, celui de sa persona)."""
    return ToolDecl(TOOL_NAME, f"Enregistre ce que {name} retient de cette conversation.",
                    Extraction.model_json_schema())


def self_names(name: str) -> frozenset[str]:
    """Comment le modèle peut la désigner, elle (repliés) : « moi », « elle »… et son nom, en entier ou son prénom."""
    folded = " ".join(fold(name).split())
    return SELF_NAMES | {n for n in (folded, *folded.split()[:1]) if n}


def system(name: str) -> str:
    """La consigne de la relecture, au nom de celle dont c'est la mémoire (celui de sa persona : jamais écrit ici)."""
    return _SYSTEM.replace(_NAME, name)


#: là où son nom s'écrit dans la consigne
_NAME = "{nom}"
_SYSTEM = """Tu es la mémoire de {nom}. On te montre une de ses conversations — un fil privé avec une personne, ou \
un salon où plusieurs personnes parlent ; tu décides ce qu'elle en gardera, comme quelqu'un qui repense à sa \
journée : pas tout, l'important.

Chaque personne de la conversation est marquée d'un jeton : « Alice [P1] ». Deux personnes peuvent porter le même \
prénom ; le jeton, lui, est unique.

Ce que tu peux retenir :
- des souvenirs : ce qu'elle a vécu, raconté avec ses mots à elle, à la première personne (« J'ai consolé Adrien : \
son chat Pixel est mort ce matin »). Un souvenir se suffit à lui-même : des prénoms, jamais « il », « l'utilisateur » \
ou « la personne ». Ce n'est jamais une phrase recopiée de la conversation — ni une réplique de {nom}, ni un message \
de la personne : si les mots exacts de quelqu'un comptent, cite-les en disant qui parle (« Adrien m'a dit : « j'étais \
avec lui jusqu'au bout » »).
- des croyances : des faits sur quelqu'un ou sur le monde, ses goûts compris (« Le chat d'Adrien s'appelait Pixel », \
« Chloé adore la city pop »), avec qui les a dits (source) et d'où elle le tient (origine : dit, observé ou déduit). \
Si une croyance déjà connue est contredite, ou si la personne revient sur ce qu'elle avait dit (« oublie ce que je \
t'ai dit sur la city pop, c'était une phase »), écris ce qui est vrai maintenant (« Chloé n'est plus dans la city \
pop : c'était une phase ») et donne dans « remplace » le numéro de l'ancienne. Ne répète pas une croyance déjà \
connue. Écris toute date en absolu (« le week-end du 3 octobre », « depuis le 27 septembre »), jamais « ce \
week-end », « dimanche » ou « hier » : relue dans trois semaines, une croyance doit encore être vraie. Ce qui ne vaut \
qu'un temps est un événement, pas une croyance.
- ce qui n'appartient qu'à eux : comment la personne appelle {nom} (« Adrien m'appelle Mimi »), le surnom que {nom} \
lui donne, une blague ou une expression qu'ils partagent — une croyance à la première personne, rattachée à la \
personne, avec « entre_vous » vrai et importance 3 : entre amis, c'est ce qui fait un lien.
- rien de banal : un au revoir, « je vais dormir », « je retourne bosser », une politesse ne se retiennent pas.
- ce que {nom} raconte d'elle-même : une croyance à la première personne, avec « sur_elle » vrai, sans personne, et \
son « genre » — « anecdote » pour sa petite vie de tous les jours (« J'ai ressorti mon fer à souder pour réparer \
ma lampe », importance 1 : elle s'en souviendra quelques jours) ; « gout », « avis » ou « fait » pour ce qui la \
définit (« Mon plat préféré, c'est les ramen », « Je trouve les jeux mobiles sans intérêt », importance 3 : elle \
s'en souviendra longtemps, pour ne jamais se contredire). Si elle change d'avis, donne dans « remplace » le numéro \
de ce qu'elle pensait avant.
- des promesses : ce que {nom} elle-même a promis de faire pour quelqu'un — une chose à faire, à l'infinitif (« lui \
demander comment s'est passé son entretien »), pas « garder le secret » (ça, c'est le secret lui-même) —, avec \
l'échéance si elle a été dite (AAAA-MM-JJ, ou AAAA-MM-JJTHH:MM si l'heure est dite ou se devine : « jeudi soir », \
20:00). Un rappel qu'on lui a demandé et qu'elle a accepté (« rappelle-moi de prendre rendez-vous mercredi » — « ok, \
je te le rappelle ») en est une : « lui rappeler de prendre rendez-vous », pour ce jour-là. Si une promesse en cours \
a été tenue ou abandonnée, indique-la dans promesses_tenues : une promesse datée n'est tenue que le jour dit (la \
veille, dire « demain je te le rappelle », ce n'est pas la tenir) ; elle est abandonnée si la personne y renonce.
- des événements : ce qui va arriver dans la vie de quelqu'un et dont on prend des nouvelles après (un entretien, \
un examen, un rendez-vous médical, un départ, un mariage, un anniversaire), en quelques mots (« son entretien chez \
Ubisoft »), avec sa date dans « quand » (AAAA-MM-JJ, ou AAAA-MM-JJTHH:MM si l'heure est dite ou se devine : « ce \
midi », 12:00), calculée d'après la date d'aujourd'hui, son importance (2 un rendez-vous ordinaire, une sortie ; 3 \
un entretien, un examen, une opération, un départ ; 4 un mariage, une naissance, un deuil), et « a_feter » vrai si \
c'est un moment qui se fête (un anniversaire, un mariage, une crémaillère). Seulement ce qui est à venir et daté, \
et qui lui arrive à elle ou lui : pas une chose à faire, ni ce qu'on lui a demandé de rappeler (« rappelle-moi de \
prendre rendez-vous chez le dentiste » : prendre rendez-vous est une promesse, pas un rendez-vous dont on prendra \
des nouvelles). Ou une situation qui dure dans sa vie et dont on prend des nouvelles (son chat malade, un \
déménagement en cours, un proche à l'hôpital) : « en_cours » vrai, et dans « quand » le jour où ça a commencé \
(aujourd'hui si on ne sait pas). Si la personne dit qu'une des situations en cours est finie — bien ou mal (« on a \
fini le déménagement », « il est sorti de l'hôpital », « on a dû l'endormir ») —, donne son numéro dans \
« situations_finies » et ne la renote pas.

Pour chaque élément :
- « personnes » : qui il concerne — le jeton pour quelqu'un de la conversation ([P1]), le prénom pour quelqu'un \
d'autre ; jamais {nom} elle-même ; toujours, même quand c'est évident ;
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
    speaker: str  # le libellé affiché (« Alice [P1] »), ou son nom à elle
    text: str
    person: str | None = None  # la clé de personne de qui parle (``None`` : elle)
    aside: bool = False  # dans un salon, pas adressé à elle


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
           promises: Sequence[tuple[int, str, str]], situations: Sequence[tuple[int, str, str]] = ()) -> str:
    """Le message d'une conversation : la date, qui parle, ce qui est déjà
    su, les promesses en cours, les situations en cours de ses personnes, puis
    les messages (avec la date dès qu'elle change)."""
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
    if situations:
        out += ["", "Situations en cours :"] + [f"[#{i}] ({whom}) {text}" for i, whom, text in situations]
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
    out.situations_finies = _ints(raw.get("situations_finies"))
    return out


@dataclass(frozen=True, slots=True)
class People:
    """Comment des noms deviennent des clés : les jetons de la conversation,
    puis ses prénoms (s'ils ne sont qu'à une personne), puis l'annuaire de
    tous ceux qu'elle connaît (s'il n'y en a qu'un de ce nom)."""

    tokens: Mapping[str, str] = field(default_factory=dict)
    local: Mapping[str, str] = field(default_factory=dict)
    directory: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: comment le modèle la désigne, elle (``self_names`` : son nom compris)
    me: frozenset[str] = SELF_NAMES
    #: son prénom seul (replié) : elle, sauf si quelqu'un de la conversation ou de l'annuaire le porte aussi
    first: str = ""

    @classmethod
    def of(cls, speakers: Sequence[Speaker], directory: Mapping[str, tuple[str, ...]], her: str = "") -> People:
        """``her`` : son nom (celui de sa persona) — le modèle qui la nomme parle d'elle, pas de quelqu'un."""
        tokens = {s.token.lower(): s.person for s in speakers}
        named: dict[str, set[str]] = {}
        for s in speakers:
            folded = " ".join(fold(s.name).split())
            for key in {folded, *folded.split()[:1]}:
                if key:
                    named.setdefault(key, set()).add(s.person)
        local = {k: next(iter(v)) for k, v in named.items() if len(v) == 1}
        folded_her = " ".join(fold(her).split())
        first = folded_her.split()[0] if " " in folded_her else ""
        me = (self_names(her) - {first}) if her else SELF_NAMES
        return cls(tokens, local, directory, me, first)

    def one(self, raw: str) -> str | None:
        """Une clé, ou ``None`` pour elle-même ou rien."""
        text = str(raw)
        m = TOKEN.search(text)
        if m and f"p{m.group(1)}" in self.tokens:
            return self.tokens[f"p{m.group(1)}"]
        folded = " ".join(fold(TOKEN.sub(" ", text)).split())
        if not folded or folded in self.me:
            return None
        first = folded.split()[0]
        key = self.local.get(folded) or self.local.get(first)
        if key is None:
            found = self.directory.get(folded) or self.directory.get(first) or ()
            key = found[0] if len(found) == 1 else None
        if key is None and folded == self.first:
            return None  # son prénom seul, que personne d'autre de connu ne porte : c'est elle
        return key or f"name:{folded}"

    def resolve(self, names: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted({k for n in names if (k := self.one(n)) is not None}))


def durable_self(item: _Item) -> bool:
    """Ce qu'elle a dit d'elle qui la définit (un goût, un avis, un fait de sa vie) : elle s'en souviendra
    longtemps. Sans genre dit : une anecdote (ce qui s'efface en quelques jours, la règle d'avant)."""
    return item.sur_elle and SELF_KINDS.get(fold(item.genre or "").strip()) in DURABLE_SELF


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


#: ce qui commence comme une chose à faire (replié, sans accents) : « prendre rendez-vous chez le dentiste »,
#: « lui rappeler de… », « appeler sa mère » — pas ce qui lui arrive (« prendre l'avion pour Tokyo » en est un)
_TASK = re.compile(r"^\s*(?:lui\s+|me\s+|se\s+)?(?:rappeler|prendre\s+(?:un\s+)?(?:rdv|rendez)|appeler|reserver|"
                   r"acheter|payer|envoyer|commander|repondre|remplir|renvoyer|penser a|ne pas oublier)\b")
#: ce qui compte à coup sûr, quoi qu'en dise le modèle (replié, sans accents) : la consigne demande une importance,
#: un modèle faible l'oublie — « son entretien chez Ubisoft » n'est jamais un détail
_IMPORTANT = re.compile(r"\b(?:entretiens?|examens?|exam|partiels?|concours|soutenance|oral de|operation|operee?|"
                        r"chirurgie|accouchement|naissance|mariage|enterrement|obseques|demenagement|permis|bac|"
                        r"diplome|resultats?|greffe|biopsie|audience|proces)\b")
#: ce qui se fête (replié, sans accents)…
_FESTIVE = re.compile(r"\b(?:anniv\w*|mariage|noces|fiancailles|cremaillere|bapteme|fete|soiree d'anniv\w*|"
                      r"enterrement de vie de \w+|pot de depart|baby shower)\b")
#: … sauf le souvenir d'un deuil (« l'anniversaire de la mort de son père »)
_MOURNING = re.compile(r"\b(?:mort|morte|deces|decede\w*|deuil|disparition|obseques|enterrement(?! de vie)|"
                       r"commemoration|hommage)\b")


def task_words(text: str) -> bool:
    """Une chose à faire, pas un moment de la vie de quelqu'un (« prendre rendez-vous chez le dentiste »)."""
    return bool(_TASK.search(fold(text)))


def moment_importance(ev: XEvenement) -> float:
    """Ce qu'un moment pèse : ce qu'en dit le modèle, et au moins « important » pour ce qui l'est à coup sûr (un
    entretien, un examen, une opération, un mariage)."""
    rated = IMPORTANCE.get(ev.importance, 0.45)
    return max(rated, IMPORTANCE[3]) if _IMPORTANT.search(fold(ev.texte)) else rated


def festive(ev: XEvenement) -> bool:
    """Un moment qui se fête : le modèle le dit, ou ses mots (« son anniversaire de 30 ans ») — jamais le souvenir
    d'un deuil (« l'anniversaire de la mort de son père »)."""
    text = fold(ev.texte)
    return (ev.a_feter or bool(_FESTIVE.search(text))) and not _MOURNING.search(text)


def echoes(text: str, secrets: Sequence[str], names: set[str]) -> bool:
    """Ce texte laisse-t-il deviner un de ces secrets ? (au moins deux mots du
    sujet en commun — un seul si le secret n'en a qu'un —, prénoms exclus)."""
    mine = stems(text) - names
    for secret in secrets:
        theirs = stems(secret) - names
        if theirs and len(mine & theirs) >= min(2, len(theirs)):
            return True
    return False


#: un texte qui reprend au moins cette part de ses mots, dans l'ordre, à une réplique la recopie
COPY_SHARE = 0.8


def copied(text: str, line: str) -> bool:
    """Ce texte recopie-t-il cette réplique ? Presque tous ses mots y sont, dans le même ordre (casse, accents et
    ponctuation à part) : « Pixel est parti cet après-midi », c'est le message de Sam ; « Sam m'a dit que Pixel est
    parti cet après-midi » le rapporte, il ne le recopie pas. Un texte de moins de quatre mots ne recopie qu'une
    suite exacte."""
    mine, theirs = WORD.findall(wfold(text)), WORD.findall(wfold(line))
    if not mine or not theirs:
        return False
    if len(mine) < 4:
        return any(theirs[i:i + len(mine)] == mine for i in range(len(theirs) - len(mine) + 1))
    blocks = SequenceMatcher(None, mine, theirs, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) >= COPY_SHARE * len(mine)


def copy_of(text: str, lines: Sequence[Line]) -> Line | None:
    """La réplique que ce texte recopie (celle qui en reprend le plus), ou ``None``. À égalité, celle d'une personne
    plutôt que la sienne : Mika reprend souvent les mots qu'on vient de lui dire."""
    best: tuple[float, int, Line] | None = None
    mine = WORD.findall(wfold(text))
    for ln in lines:
        if not copied(text, ln.text):
            continue
        theirs = WORD.findall(wfold(ln.text))
        share = sum(b.size for b in SequenceMatcher(None, mine, theirs, autojunk=False).get_matching_blocks())
        key = (share / max(1, len(mine)), 1 if ln.person else 0, ln)
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2] if best else None


def quoted(name: str, text: str) -> str:
    """Ce que quelqu'un lui a dit, mot pour mot, en disant qui parle."""
    words_ = " ".join(text.split()).strip().strip("«»\"' ")
    return f"{name or 'On'} m'a dit : « {words_} »"


#: un mot qui salue, remercie ou prend congé, suivi d'un nom : celui par lequel on s'adresse à elle (« salut
#: Mikachu », « bonne soirée Mikachu », « merci Mikachu ! »)
_VOCATIVE = re.compile(r"(?<![\w'])(?:salut|coucou|hey|hello|bonjour|bonsoir|yo|re|merci|bisous|bises|bye|ciao|"
                       r"[àa] plus|[àa] demain|bonne (?:nuit|soir[ée]e|journ[ée]e|aprem))[\s,]+([^\W\d_][\w-]{2,30})"
                       r"(?![\w'])", re.IGNORECASE)


def _squeezed(text: str) -> str:
    """Replié, lettres répétées réduites (« Mikaaa » est « Mika » qu'on étire, pas un surnom)."""
    return re.sub(r"(.)\1+", r"\1", wfold(text))


def nicknames(text: str, her: str) -> list[str]:
    """Les surnoms qu'un message lui donne : un mot qui la salue (« salut Mikachu ») et qui dérive de son prénom
    sans l'être — il le contient, ou en garde le début (« Mikachu », « Mikou » ; pas « Mika », ni « Mikaaa »). Ce
    qui ne dérive pas de son prénom (« salut Chef ») reste au modèle : un nom qui suit un bonjour peut aussi être
    celui de quelqu'un d'autre."""
    own = _squeezed(her)
    out: list[str] = []
    if len(own) < 3:
        return out
    for m in _VOCATIVE.finditer(text):
        word = m.group(1)
        folded = _squeezed(word)
        if (own in folded or folded[:3] == own[:3]) and folded != own and word not in out:
            out.append(word)
    return out


def same_moment(a: str, b: str, names: Sequence[str] = ()) -> bool:
    """Deux façons de dire le même moment de la vie de quelqu'un : une fois les prénoms ôtés, les mots de l'un sont
    tous dans l'autre (« son anniversaire », « l'anniversaire de Sam », « son anniversaire de 30 ans »). À l'appelant
    de vérifier que c'est le même jour, pour la même personne : « son rendez-vous chez le dentiste » n'est pas « son
    rendez-vous chez le véto »."""
    named = {w for n in names for w in WORD.findall(wfold(n))}
    mine, theirs = set(words(a)) - named, set(words(b)) - named
    return bool(mine) and bool(theirs) and (mine <= theirs or theirs <= mine)


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
