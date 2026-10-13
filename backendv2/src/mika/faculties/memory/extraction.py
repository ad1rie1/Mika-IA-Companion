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
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from mika.contracts.memory import Relation
from mika.kernel.clock import instant
from mika.kernel.codec import digest
from mika.ports.llm import LLMResponse, ToolDecl
from mika.ports.sql import HANDLE_MAX, fit
from mika.vocab.affect import facets, facets_valence
from mika.vocab.circadian import DAYS_FR, MONTHS_FR
from mika.vocab.people import clean_tokens, fold
from mika.vocab.phrasebook import phrase, phrases
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import OPENERS, WORD, stems, words
from mika.vocab.words import fold as wfold

TOOL_NAME = "record_memories"
#: ce qu'une relecture peut écrire au plus (jetons) : chaque élément porte ses facettes de ressenti, ses personnes, ses
#: messages ; une conversation riche y ajoute prévisions et constats — et, par la CLI, la réflexion du modèle compte
#: dans ce plafond (sonde réelle du 2026-10-10 : 2 500 ne suffisaient plus pour quatre messages)
MAX_OUTPUT_TOKENS = 6000
#: Comment le modèle la désigne quand c'est elle (repliés) ; son nom s'y ajoute, celui de sa persona (``self_names``).
SELF_NAMES = frozenset({"moi", "je", "elle-meme", "elle meme"})
IMPORTANCE = {1: 0.2, 2: 0.45, 3: 0.7, 4: 0.95}
SENSITIVITY = {"anodin": Sensitivity.ANODYNE, "anodine": Sensitivity.ANODYNE, "anodyne": Sensitivity.ANODYNE,
               "personnel": Sensitivity.PERSONAL, "personnelle": Sensitivity.PERSONAL, "personal": Sensitivity.PERSONAL,
               "confidence": Sensitivity.CONFIDENCE, "confidentiel": Sensitivity.CONFIDENCE,
               "confidential": Sensitivity.CONFIDENCE, "intime": Sensitivity.CONFIDENCE}
ORIGIN = {"dit": "told", "observe": "observed", "observé": "observed", "deduit": "inferred", "déduit": "inferred"}
#: la confiance qu'une croyance peut avoir à sa naissance, selon d'où elle vient (ADR 0075) : ce qu'elle a vu plus que
#: ce qu'on lui a dit, ce qu'on lui a dit plus que ce qu'elle en déduit. Le modèle qui l'extrait ne la rend pas plus
#: sûre ; redire n'y ajoute rien — seule une autre personne qui le lui dit aussi (``corroborated``) la fait monter.
CONFIDENCE_CAP = {"observed": 0.9, "told": 0.8, "inferred": 0.6, "read": 0.7}  # lu : comme un témoin qui rapporte (ADR 0085)


def born_confidence(confidence: float, origin: str, kind: str = "claim") -> float:
    """La confiance d'une croyance qui naît, bornée par sa nature : une hypothèse vaut une déduction."""
    cap = CONFIDENCE_CAP["inferred"] if kind == "hypothesis" else CONFIDENCE_CAP.get(origin, CONFIDENCE_CAP["told"])
    return round(min(max(0.0, float(confidence)), cap), 3)
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


def _asks_veiled(schema: dict[str, Any]) -> None:
    """« sans_nom » est demandé au modèle (requis dans le schéma de l'outil, vide permis) : facultatif, un modèle
    léger ne l'écrivait que pour un tiers, jamais pour la vie de la personne qui parle (sonde réelle du 2026-10-11).
    La lecture, elle, reste indulgente : absent, il n'y a pas de version sans nom."""
    schema["required"] = sorted({*schema.get("required", []), "sans_nom"})


#: le genre d'une croyance (replié, sans accents) : sa famille et sa sorte de savoir. Ce qu'elle dit d'elle-même :
#: une anecdote s'efface en quelques jours ; un goût, un avis, un fait de sa vie la définit et tient (ADR 0087)
GENRES: dict[str, tuple[str, str]] = {
    "anecdote": ("anecdote", "claim"),
    "gout": ("gout", "preference"), "gouts": ("gout", "preference"),
    "preference": ("gout", "preference"), "preferences": ("gout", "preference"),
    "avis": ("avis", "opinion"), "opinion": ("avis", "opinion"),
    "fait": ("fait", "claim"), "biographie": ("fait", "claim"), "vie": ("fait", "claim"),
    "hypothese": ("hypothese", "hypothesis"),
}
DURABLE_SELF = frozenset({"gout", "avis", "fait"})


def kind_of_genre(genre: str | None) -> str:
    """La sorte de savoir que dit un genre : un avis, un goût, une hypothèse — sinon un fait rapporté."""
    return GENRES.get(fold(genre or "").strip(), ("", "claim"))[1]


class _Item(_Lenient):
    texte: str = Field(min_length=3, max_length=600, validation_alias=_TEXT)
    sur_elle: bool = Field(default=False, description=phrase("memory.extraction.fields.sur_elle"))
    genre: str | None = Field(default=None, description=phrase("memory.extraction.fields.genre"))
    personnes: list[str] = Field(default_factory=list, description=phrase("memory.extraction.fields.personnes"))
    sensibilite: str | None = Field(default=None, validation_alias=_SENS,
                                    description=phrase("memory.extraction.fields.sensibilite"))
    secret: bool = Field(default=False, description=phrase("memory.extraction.fields.secret"))
    messages: list[int] = Field(default_factory=list, description=phrase("memory.extraction.fields.messages"))
    #: ce que la personne concernée en ressent, et ce qu'elle-même en ressent : jugés par la relecture, jamais
    #: devinés d'après les mots (ADR 0083)
    ressenti: dict[str, float] = Field(default_factory=dict, description=phrase("memory.extraction.fields.ressenti"))
    mon_ressenti: dict[str, float] = Field(default_factory=dict,
                                           validation_alias=AliasChoices("mon_ressenti", "emotion"),
                                           description=phrase("memory.extraction.fields.mon_ressenti"))

    @field_validator("ressenti", "mon_ressenti", mode="before")
    @classmethod
    def lenient_feelings(cls, v: Any) -> dict[str, float]:
        """Un objet, une liste, « colère:0.8, dégoût:0.4 » ou un mot seul : rangé parmi les 29 émotions (ADR 0083),
        jamais une erreur qui ferait perdre l'élément."""
        return dict(facets(v))

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
    model_config = ConfigDict(extra="ignore", json_schema_extra=_asks_veiled)

    importance: int = Field(default=2, ge=1, le=4)
    sans_nom: str | None = Field(default=None, description=phrase("memory.extraction.fields.sans_nom"))


class XCroyance(_Item):
    model_config = ConfigDict(extra="ignore", json_schema_extra=_asks_veiled)

    origine: str = Field(default="dit", validation_alias=AliasChoices("origine", "origin"))
    source: str | None = None
    confiance: float = Field(default=0.7, ge=0.0, le=1.0)
    importance: int = Field(default=2, ge=1, le=4)
    remplace: int | None = None
    point_de_vue: str | None = Field(default=None, description=phrase("memory.extraction.fields.point_de_vue"))
    sans_nom: str | None = Field(default=None, description=phrase("memory.extraction.fields.sans_nom"))
    relations: list[Relation] = Field(default_factory=list, description=phrase("memory.extraction.fields.relations"))
    entre_vous: bool = Field(default=False, validation_alias=AliasChoices("entre_vous", "entre_nous", "lien"),
                             description=phrase("memory.extraction.fields.entre_vous"))
    de_premiere_main: bool = Field(default=False, validation_alias=AliasChoices("de_premiere_main",
                                                                                "de_première_main", "premiere_main"),
                                   description=phrase("memory.extraction.fields.de_premiere_main"))
    depuis: str | None = Field(default=None, description=phrase("memory.extraction.fields.depuis"))
    jusqua: str | None = Field(default=None, validation_alias=AliasChoices("jusqua", "jusqu_a", "jusquà"),
                               description=phrase("memory.extraction.fields.jusqua"))


class XPromesse(_Lenient):
    texte: str = Field(min_length=3, max_length=400, validation_alias=_TEXT,
                       description=phrase("memory.extraction.fields.promise_text"))
    envers: str
    echeance: str | None = Field(default=None, validation_alias=AliasChoices("echeance", "échéance"),
                                 description=phrase("memory.extraction.fields.date"))
    travail: bool = Field(default=False, description=phrase("memory.extraction.fields.promise_work"))
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
                       description=phrase("memory.extraction.fields.event_text"))
    quand: str = Field(min_length=4, max_length=40, description=phrase("memory.extraction.fields.date"))
    en_cours: bool = Field(default=False, description=phrase("memory.extraction.fields.en_cours"))
    importance: int = Field(default=2, ge=1, le=4, description=phrase("memory.extraction.fields.event_importance"))
    a_feter: bool = Field(default=False, validation_alias=AliasChoices("a_feter", "à_fêter", "a_fêter", "festif"),
                          description=phrase("memory.extraction.fields.a_feter"))
    chaque_annee: bool = Field(default=False, validation_alias=AliasChoices("chaque_annee", "chaque_année",
                                                                            "annuel", "annuelle"),
                               description=phrase("memory.extraction.fields.chaque_annee"))
    #: un moment déjà noté (la liste « Moments à venir ») que celui-ci remplace : reporté, avancé, précisé (ADR 0076) ;
    #: ou, pour une situation en cours, une situation finie depuis peu qui revient (ADR 0079)
    remplace: int | None = Field(default=None, description=phrase("memory.extraction.fields.event_remplace"))
    #: ce qui arrive dans le monde (des élections, la sortie d'un film) ; un moment de quelqu'un qu'elle vivra à
    #: travers lui ; à quel point c'est sûr ; une date publique officielle (ADR 0084)
    monde: bool = Field(default=False, description=phrase("memory.extraction.fields.monde"))
    partage: bool = Field(default=False, validation_alias=AliasChoices("partage", "partagé"),
                          description=phrase("memory.extraction.fields.partage"))
    probabilite: str | float | None = Field(default=None, validation_alias=AliasChoices("probabilite", "probabilité"),
                                            description=phrase("memory.extraction.fields.probabilite"))
    date_officielle: bool = Field(default=False, description=phrase("memory.extraction.fields.date_officielle"))


class XPrevision(_Item):
    """Ce que quelqu'un s'attend à voir arriver (« Léa pense qu'elle sera prise », « les taux vont remonter ») — elle
    aussi (« sur_elle » : son propre pronostic) : une croyance de la sorte « prévision » (ADR 0084)."""

    quand: str | None = Field(default=None, description=phrase("memory.extraction.fields.prevision_quand"))
    probabilite: str | float | None = Field(default=None, validation_alias=AliasChoices("probabilite", "probabilité"),
                                            description=phrase("memory.extraction.fields.probabilite"))
    point_de_vue: str | None = Field(default=None, description=phrase("memory.extraction.fields.point_de_vue"))


class XConstat(_Lenient):
    """Comment un moment passé a tourné, d'après ce que la personne concernée en dit (ADR 0086)."""

    numero: int = Field(validation_alias=AliasChoices("numero", "numéro", "id", "moment"),
                        description=phrase("memory.extraction.fields.constat_numero"))
    issue: str = Field(min_length=2, max_length=40, description=phrase("memory.extraction.fields.constat_issue"))
    en_bref: str | None = Field(default=None, description=phrase("memory.extraction.fields.constat_en_bref"))
    messages: list[int] = Field(default_factory=list, description=phrase("memory.extraction.fields.messages"))

    @field_validator("messages", mode="before")
    @classmethod
    def lenient_messages(cls, v: Any) -> list[int]:
        return _ints(v)


#: ce que la relecture écrit dans « issue », rabattu sur une issue (clés : ``fold``) ; l'ordre compte (« pas eu
#: lieu » avant « eu lieu »)
_ISSUES = (("annul", "cancelled"), ("pas eu lieu", "cancelled"), ("n'a pas eu lieu", "cancelled"),
           ("report", "moved"), ("deplac", "moved"), ("decal", "moved"), ("moved", "moved"),
           ("cancel", "cancelled"), ("eu lieu", "happened"), ("fait", "happened"), ("passe", "happened"),
           ("happened", "happened"))


def outcome_of(issue: str) -> str | None:
    """L'issue que la relecture a écrite (« a eu lieu », « annulé », « reporté »), ou rien d'interprétable."""
    text = fold(issue)
    return next((outcome for word, outcome in _ISSUES if word in text), None)


class Extraction(_Lenient):
    issues: list[str] = Field(default_factory=list, exclude=True)
    souvenirs: list[XSouvenir] = Field(default_factory=list)
    croyances: list[XCroyance] = Field(default_factory=list)
    promesses: list[XPromesse] = Field(default_factory=list)
    promesses_tenues: list[XTenue] = Field(default_factory=list)
    evenements: list[XEvenement] = Field(default_factory=list, validation_alias=AliasChoices("evenements",
                                                                                             "événements"))
    previsions: list[XPrevision] = Field(default_factory=list,
                                         validation_alias=AliasChoices("previsions", "prévisions"),
                                         description=phrase("memory.extraction.fields.previsions"))
    confidentiel: list[int] = Field(default_factory=list, description=phrase("memory.extraction.fields.confidentiel"))
    situations_finies: list[int] = Field(default_factory=list,
                                         description=phrase("memory.extraction.fields.situations_finies"))
    #: comment des moments passés ont tourné, de la bouche de la personne concernée (ADR 0086)
    constats: list[XConstat] = Field(default_factory=list, description=phrase("memory.extraction.fields.constats"))

    @field_validator("confidentiel", "situations_finies", mode="before")
    @classmethod
    def lenient_ids(cls, v: Any) -> list[int]:
        return _ints(v)


def tool(name: str) -> ToolDecl:
    """L'outil de la relecture, au nom de celle dont c'est la mémoire (``name``, celui de sa persona)."""
    return ToolDecl(TOOL_NAME, phrase("memory.extraction.tool", name=name), Extraction.model_json_schema())


def self_names(name: str) -> frozenset[str]:
    """Comment le modèle peut la désigner, elle (repliés) : « moi », « elle »… et son nom, en entier ou son prénom."""
    folded = " ".join(fold(name).split())
    return SELF_NAMES | {n for n in (folded, *folded.split()[:1]) if n}


def system(name: str) -> str:
    """La consigne de la relecture, au nom de celle dont c'est la mémoire (celui de sa persona : jamais écrit ici)."""
    return phrase("memory.extraction.system", name=name)


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
    lie: bool = False  # une de ses répliques qu'elle a marquée mensonge : elle ne dit pas le vrai
    #: une de ses répliques qui racontait sans nom ce qu'elle sait de quelqu'un (ADR 0091) : son texte ne se relit pas
    veiled: bool = False


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


def weekday_words(d: date) -> str:
    """Le jour de la semaine : « mardi »."""
    return phrases("memory.dates.weekdays")[d.weekday()]


def date_words(d: date) -> str:
    """Le jour et le mois : « 6 octobre », « 1er octobre »."""
    return phrase("memory.dates.date", day=phrase("memory.dates.first") if d.day == 1 else d.day,
                  month=phrases("memory.dates.months")[d.month - 1])


def day_words(d: date) -> str:
    """« mardi 6 octobre »."""
    return phrase("memory.dates.day", weekday=weekday_words(d), date=date_words(d))


#: Le calendrier montré à la relecture : la semaine d'avant les messages, et les deux semaines qui viennent (au plus
#: tant de jours, des plus récents) — « lundi » se lit « lundi 13 octobre », pas au jugé (ADR 0099).
CALENDAR_BEFORE, CALENDAR_AFTER, CALENDAR_MAX = 7, 14, 35


def calendar(first: date, today: date) -> str:
    """« lundi 5 octobre, mardi 6 octobre, … » : chaque jour, de la semaine qui précède le premier message aux deux
    semaines qui viennent — pour qu'un jour nommé se situe sans calcul (« on se voit lundi », écrit un vendredi)."""
    start = min(first, today) - timedelta(days=CALENDAR_BEFORE)
    end = today + timedelta(days=CALENDAR_AFTER)
    start = max(start, end - timedelta(days=CALENDAR_MAX - 1))
    return ", ".join(day_words(start + timedelta(days=i)) for i in range((end - start).days + 1))


def render(conv: Conversation, *, now: datetime, beliefs: Sequence[tuple[int, str]],
           promises: Sequence[tuple[int, str, str]], situations: Sequence[tuple[int, str, str]] = (),
           moments: Sequence[tuple[int, str, str]] = (), ended: Sequence[tuple[int, str, str]] = (),
           passed: Sequence[tuple[int, str, str]] = ()) -> str:
    """Le message d'une conversation : la date, qui parle, ce qui est déjà
    su, les promesses en cours, les situations en cours, celles finies depuis
    peu (qui peuvent revenir) et les moments à venir de ses personnes, puis
    les messages (avec la date dès qu'elle change)."""
    out = [phrase("memory.extraction.render.today", day=day_words(now.date()), year=now.year, hour=f"{now:%H}",
                  minute=f"{now:%M}")]
    first = datetime.fromtimestamp(conv.lines[0].at / 1e6, now.tzinfo).date() if conv.lines else now.date()
    out.append(phrase("memory.extraction.render.calendar", days=calendar(first, now.date())))
    who = ", ".join(s.label for s in conv.speakers)
    if conv.room:
        out.append(phrase("memory.extraction.render.room", who=who))
    else:
        out.append(phrase("memory.extraction.render.private", who=who))
    if beliefs:
        out += ["", phrase("memory.extraction.render.beliefs")] + [f"[#{i}] {text}" for i, text in beliefs]
    if promises:
        out += ["", phrase("memory.extraction.render.promises")] + [
            phrase("memory.extraction.render.promise", id=i, whom=whom, text=text) for i, whom, text in promises]
    if situations:
        out += ["", phrase("memory.extraction.render.situations")] + [
            f"[#{i}] ({whom}) {text}" for i, whom, text in situations]
    if ended:
        out += ["", phrase("memory.extraction.render.ended")] + [f"[#{i}] ({whom}) {text}" for i, whom, text in ended]
    if moments:
        out += ["", phrase("memory.extraction.render.moments")] + [
            f"[#{i}] ({whom}) {text}" for i, whom, text in moments]
    if passed:
        out += ["", phrase("memory.extraction.render.passed")] + [
            f"[#{i}] ({whom}) {text}" for i, whom, text in passed]
    out += ["", phrase("memory.extraction.render.messages")]
    day: date | None = None
    for ln in conv.lines:
        moment = datetime.fromtimestamp(ln.at / 1e6, now.tzinfo)
        if moment.date() != day:
            day = moment.date()
            out.append(phrase("memory.extraction.render.day", day=day_words(day)))
        aside = phrase("memory.extraction.render.aside") if ln.aside else ""
        lie = phrase("memory.extraction.render.lie") if ln.lie else ""
        text = phrase("memory.extraction.render.veiled_said") if ln.veiled else ln.text
        out.append(f"[#{ln.seq}] {moment:%H:%M} {ln.speaker}{aside} : {text}{lie}")
    return "\n".join(out)


def parse(resp: LLMResponse) -> Extraction | None:
    """L'outil s'il a été appelé, sinon un objet JSON reconnu ; les éléments illisibles sont signalés séparément."""
    raw: Any = None
    structured = False
    for call in resp.tool_calls:
        if call.name == TOOL_NAME:
            raw = dict(call.args)
            structured = True
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
    expected = {"souvenirs", "croyances", "promesses", "promesses_tenues", "evenements", "confidentiel",
                "situations_finies", "previsions", "constats"}
    if ((not expected.intersection(raw) and not (structured and not raw))
            or resp.stop == "max_tokens" or resp.truncated_tool_call):
        return None
    out = Extraction()
    for key, model in (("souvenirs", XSouvenir), ("croyances", XCroyance), ("promesses", XPromesse),
                       ("promesses_tenues", XTenue), ("evenements", XEvenement), ("previsions", XPrevision),
                       ("constats", XConstat)):
        items = raw.get(key, [])
        if items is None:
            items = []
        if isinstance(items, str):
            try:
                items = json.loads(items)  # certains modèles passent la liste en texte
            except ValueError:
                return None
        if not isinstance(items, list):
            return None
        kept = []
        # La sortie est bornée par le fournisseur ; aucun élément valide n'est jeté après coup.
        for position, item in enumerate(items):
            try:
                kept.append(model.model_validate(item))
            except ValidationError as exc:
                kinds = sorted({error["type"] for error in exc.errors()})
                out.issues.append(f"{key}[{position}]: {', '.join(kinds)}")
        setattr(out, key, kept)
    for key in ("confidentiel", "situations_finies"):
        items = raw.get(key, [])
        if items is None:
            items = []
        if not isinstance(items, list) or any(type(i) is not int or i <= 0 for i in items):
            return None
        setattr(out, key, items)
    return out


def mention_scope(conversation: str) -> str:
    """La portée d'une mention inconnue (``name:<portée>:<nom>``) : la conversation où on l'a nommée."""
    return digest(conversation)[:16]


#: ``name:<portée>:<nom>`` — une mention liée à la conversation où elle a été faite
_SCOPED = re.compile(r"^name:([0-9a-f]{16}):")


def scope_of(key: str) -> str | None:
    """La portée d'une clé de mention, ``None`` pour une clé d'avant les portées (ou une personne)."""
    m = _SCOPED.match(key)
    return m.group(1) if m else None


@dataclass(frozen=True, slots=True)
class People:
    """Comment des noms deviennent des clés : les jetons de la conversation,
    puis ses prénoms (s'ils ne sont qu'à une personne), puis l'annuaire de
    tous ceux qu'elle connaît — un nom complet qu'une seule porte, ou un
    prénom qu'une seule porte parmi celles qu'elle a vues dans un salon avec
    quelqu'un de la conversation (``near``). Un prénom seul, sinon, reste une
    mention (``name:<portée>:<prénom>``) : la nouvelle collègue « Alice » de Bob
    n'est pas l'Alice qu'elle connaît. L'identité la *présume* (un fait
    révisable, jamais une liaison : ADR 0075)."""

    tokens: Mapping[str, str] = field(default_factory=dict)
    local: Mapping[str, str] = field(default_factory=dict)
    directory: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: comment le modèle la désigne, elle (``self_names`` : son nom compris)
    me: frozenset[str] = SELF_NAMES
    #: son prénom seul (replié) : elle, sauf si quelqu'un de la conversation ou de l'annuaire le porte aussi
    first: str = ""
    scope: str = ""
    #: celles qu'elle a vues dans un salon avec quelqu'un de la conversation : leur prénom seul les désigne
    near: frozenset[str] = frozenset()

    @classmethod
    def of(cls, speakers: Sequence[Speaker], directory: Mapping[str, tuple[str, ...]], her: str = "",
           scope: str = "", near: Sequence[str] = ()) -> People:
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
        return cls(tokens, local, directory, me, first,
                   mention_scope(scope or "|".join(sorted(s.person for s in speakers))), frozenset(near))

    def one(self, raw: str) -> str | None:
        """Une clé, ou ``None`` pour elle-même ou rien."""
        text = str(raw)
        m = TOKEN.search(text)
        if m and f"p{m.group(1)}" in self.tokens:
            return self.tokens[f"p{m.group(1)}"]
        folded = " ".join(fold(TOKEN.sub(" ", text)).split())
        if not folded or folded in self.me:
            return None
        key = self.local.get(folded)
        found: tuple[str, ...] = ()
        if key is None:
            found = self.directory.get(folded) or ()
            # un nom complet, ou quelqu'un que la conversation connaît : vu en salon avec l'un de ses locuteurs, ou
            # l'un d'eux sous une autre de ses adresses (« Robert » sur Telegram, « Bob » ici)
            if len(found) == 1 and (" " in folded or found[0] in self.near or found[0] in self.tokens.values()):
                key = found[0]
        if key is None and folded == self.first and len(found) != 1:
            return None  # son prénom seul, que personne d'autre de connu ne porte : c'est elle
        # une mention inconnue devient une clé (``memory_about``…) : un « nom » démesuré y est ramené à sa borne
        return key or fit(f"name:{self.scope}:{folded}", HANDLE_MAX)

    def resolve(self, names: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted({k for n in names if (k := self.one(n)) is not None}))

    def names_someone(self, text: str) -> bool:
        """Le texte nomme-t-il quelqu'un d'autre qu'elle : un locuteur de la conversation, ou une personne qu'elle
        connaît (son nom ou son prénom) ? « Alice est comptable à Lyon », tiré de sa propre réplique (« je sais que tu
        es comptable à Lyon »), n'est pas une note sur elle : la ranger ainsi la rendait dicible à tous (sonde réelle
        du 2026-10-09)."""
        said = " ".join(WORD.findall(fold(TOKEN.sub(" ", str(text)))))
        if not said:
            return False
        for key in (*self.local, *self.directory):
            if len(key) >= 3 and key not in self.me and key != self.first \
                    and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", said):
                return True
        return False


#: un moment vécu à travers quelqu'un, dit en bref (« un concert de jazz ») : au plus tant de caractères
GIST_MAX = 80


def gist_of(text: str | None, people: People) -> str | None:
    """Ce qu'elle a vécu à travers quelqu'un, dit sans personne (ADR 0087) : la relecture l'écrit, le code garde un
    filet — trop long, un nom qu'elle connaît, un chiffre (une date, une adresse), et il n'y en a pas."""
    said = " ".join((text or "").split()).strip(" .")
    if len(said) < 3 or len(said) > GIST_MAX or re.search(r"\d", said) or people.names_someone(said):
        return None
    return said


#: ce qu'elle sait de quelqu'un, raconté sans nom (ADR 0091) : au plus tant de caractères
VEILED_MAX = 240


#: un moment qui situerait le récit sans nom : une année, un mois (« le 10 octobre », « en janvier »), un jour de la
#: semaine — une durée (« six semaines »), non
_WHEN = re.compile(r"\b(?:19|20)\d{2}\b|\b(?:" + "|".join(wfold(m) for m in (*MONTHS_FR, *DAYS_FR)) + r")\b")
#: un mot (lettres, apostrophes et traits d'union compris : « l'Italie », « Saint-Malo »)
_TOKEN = re.compile(r"[^\W\d_][\w'’-]*")
#: ce qui précède un début de phrase : la majuscule y est la règle, pas un nom
_OPENS = re.compile(r"(?:^|[.!?…:;«\"“(]\s*)$")


def capitalized(text: str) -> tuple[set[str], set[str]]:
    """Les mots à majuscule d'un texte (repliés) : ceux qui ne sont pas en tête de phrase (un prénom, un lieu, une
    marque, un sigle), et ceux qui le sont."""
    inside: set[str] = set()
    opening: set[str] = set()
    for m in _TOKEN.finditer(text or ""):
        word = m.group(0)
        if any(ch.isupper() for ch in word):
            (opening if _OPENS.search(text[:m.start()]) else inside).add(wfold(word))
    return inside, opening


def veiled_refusal(text: str | None, people: People, original: str = "") -> str:
    """Pourquoi le filet écarte cette version sans nom (un code, pour le journal technique) — vide : il la garde.
    ``original`` : ce qu'elle raconte, nommé — ce qui y porte une majuscule (un nom, un employeur, une ville) ne
    revient pas dans la version sans nom, même en minuscules (ADR 0092)."""
    said = " ".join((text or "").split()).strip()
    if len(said) < 8:
        return "vide"
    if len(said) > VEILED_MAX:
        return "trop-longue"
    if _WHEN.search(wfold(said)):
        return "datee"
    if people.names_someone(said):
        return "nomme-quelqu-un"
    inside, opening = capitalized(said)
    if inside:
        return "nom-propre"
    named, starts = capitalized(original)
    found = {wfold(w) for w in _TOKEN.findall(said)}
    if found & named or (opening & starts) - OPENERS:
        return "reprend-un-nom"
    return ""


def veiled_of(text: str | None, people: People, original: str = "") -> str | None:
    """La même chose, racontée sans qu'on puisse reconnaître la personne : la relecture l'écrit, le code garde un
    filet — trop long, un nom qu'elle connaît, un nom propre (ou un de ceux de l'original), une date, un mois, un jour,
    et il n'y en a pas."""
    return None if veiled_refusal(text, people, original) else " ".join((text or "").split()).strip()


def durable_self(item: _Item) -> bool:
    """Ce qu'elle a dit d'elle qui la définit (un goût, un avis, un fait de sa vie) : elle s'en souviendra
    longtemps. Sans genre dit : une anecdote (ce qui s'efface en quelques jours, la règle d'avant)."""
    return item.sur_elle and GENRES.get(fold(item.genre or "").strip(), ("", ""))[0] in DURABLE_SELF


def sensitivity(value: str | None, *, has_person: bool) -> int:
    if value:
        found = SENSITIVITY.get(fold(value).strip())
        if found is not None:
            return int(found)
    return int(Sensitivity.PERSONAL if has_person else Sensitivity.ANODYNE)


def _flat(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9 ]", " ", fold(text)).split()) + " "


def says_secret(texts: Sequence[str]) -> bool:
    """La personne a-t-elle demandé de ne pas le répéter ?"""
    return any(marker in _flat(text) for text in texts for marker in SECRET_MARKERS)


#: ce qui laisse entendre, sans le demander, que c'est à garder (replié, sans accents) : « je l'ai encore dit à
#: personne », « tu es la seule à savoir » — le jugement du modèle y tient
PRIVATE_CUES = ("dit a personne", "personne ne le sait", "personne le sait", "personne n est au courant",
                "seule a savoir", "seul a savoir", "seule au courant", "seul au courant", "pas encore officiel",
                "pas officiel", "pas encore annonce", "pas encore dit")
#: ce qui accompagne une demande de silence sans rien raconter (replié) : « stp », « hein », « surtout »
_INSISTENCE = frozenset("stp svp please steuplait surtout hein promis promets jure vraiment okay ok compris "
                        "merci".split())


def hints_private(text: str) -> bool:
    flat = _flat(text)
    return any(cue in flat for cue in (*SECRET_MARKERS, *PRIVATE_CUES))


def _only_asks(text: str) -> bool:
    """Le message ne fait que demander le silence (« garde ça pour toi », « surtout dis-le à personne ») : il ne
    raconte rien lui-même."""
    flat = _flat(text)
    for marker in sorted(SECRET_MARKERS, key=len, reverse=True):
        flat = flat.replace(f" {marker} ", " ")
    return not [w for w in words(flat) if w not in _INSISTENCE]


def silence_scope(lines: Sequence[Line]) -> frozenset[int] | None:
    """Les messages qu'une demande de silence couvre (ADR 0092) — ``None`` : personne n'en a demandé dans cette
    conversation, le modèle seul en juge. Une demande dans un message qui raconte quelque chose couvre ce message ;
    une demande seule (« garde ça pour toi ») couvre ce que la même personne vient de dire, jusqu'à sa demande
    précédente. Pas au-delà : « je suis enceinte, dis-le à personne » ne fait pas un secret du licenciement raconté
    juste avant."""
    covered: set[int] = set()
    asked = False
    for i, ln in enumerate(lines):
        if ln.person is None or not says_secret([ln.text]):
            continue
        asked = True
        covered.add(ln.seq)
        if not _only_asks(ln.text):
            continue
        for prev in reversed(lines[:i]):
            if prev.person != ln.person:
                continue
            if says_secret([prev.text]):
                break
            covered.add(prev.seq)
    return frozenset(covered) if asked else None


def scoped_secrets(ex: Extraction, lines: Sequence[Line]) -> list[str]:
    """La relecture, corrigée par la portée des demandes de silence (ADR 0092) : un élément qui s'appuie sur un
    message couvert est un secret, que le modèle l'ait noté ou non ; un « secret » que le modèle pose hors de toute
    demande, dans une conversation où l'on en a fait une, ne l'est pas — sauf si ses messages laissent eux-mêmes
    entendre qu'il est à garder — mais reste une confidence (dans le doute, discrète, pas muette). Modifie ``ex`` ;
    rend les textes déclassés (pour le journal technique, jamais affichés)."""
    scope = silence_scope(lines)
    if scope is None:
        return []
    by_seq = {ln.seq: ln for ln in lines}
    lowered: list[str] = []
    for item in (*ex.souvenirs, *ex.croyances, *ex.evenements, *ex.previsions):
        theirs = {s for s in item.messages if s in by_seq and by_seq[s].person}
        if not theirs:
            continue  # rien de cité : la règle d'avant (une confidence d'une conversation où l'on a demandé le silence)
        if theirs & scope:
            item.secret = True
        elif item.secret and not any(hints_private(by_seq[s].text) for s in theirs):
            item.secret = False
            if sensitivity(item.sensibilite, has_person=True) < Sensitivity.CONFIDENCE:
                item.sensibilite = "confidence"
            lowered.append(item.texte)
    return lowered


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
#: ce qui revient chaque année, quoi qu'en dise le modèle (replié, sans accents) : « son anniversaire »,
#: « l'anniversaire de la mort de son père », « ça fera un an que… » — pas « la soirée d'anniversaire de Léa » ni
#: « l'anniversaire de Léa » où elle va, une fête qui n'a lieu qu'une fois pour qui y va
_YEARLY = re.compile(r"\b(?:son|sa|ses|leur|mon|ma|ton|ta)\s+anniv\w*|"
                     r"\bl'anniv\w*\s+de\s+(?:la\s+mort|sa\s+mort|son\s+deces|mariage|leur\s+rencontre)\b|"
                     r"\bca\s+(?:fera|fait)\s+(?:un|deux|trois|\d+)\s+ans?\s+qu")


def task_words(text: str) -> bool:
    """Une chose à faire, pas un moment de la vie de quelqu'un (« prendre rendez-vous chez le dentiste »)."""
    return bool(_TASK.search(fold(text)))


#: ce qui dit qu'un moment parle d'une mort (replié, sans accents) — un fait, pas une émotion : dans le texte que la
#: relecture a écrit, jamais dans le message de la personne. Le filet qui garde de souhaiter « l'anniversaire de la
#: mort de son père »
_DEATH = re.compile(r"\b(?:mort|morte|deces|decede\w*|deuil|disparition|obseques|enterrement(?! de vie)|"
                    r"commemoration|hommage)\b")
#: une tonalité en deçà (au-delà) de laquelle un ressenti est négatif (positif) — la même que ``memory.salience``
SIGN = 0.15


def _felt_valence(ev: XEvenement) -> float:
    """Ce que la personne en ressent, tel que la relecture l'a jugé (ses facettes) : sa tonalité, 0 sans ressenti."""
    return facets_valence(facets(ev.ressenti))


def _painful(ev: XEvenement) -> bool:
    """Un moment qui fait mal : la personne le vit douloureusement (son ressenti, jugé par la relecture, ADR 0093),
    ou il parle d'une mort (un fait)."""
    return _felt_valence(ev) < -SIGN or bool(_DEATH.search(fold(ev.texte)))


def moment_importance(ev: XEvenement) -> float:
    """Ce qu'un moment pèse : ce qu'en dit le modèle, et au moins « important » pour ce qui l'est à coup sûr (un
    entretien, un examen, une opération, un mariage) ; « marquant » pour une date qui revient chaque année et qui fait
    mal — la date d'un deuil, d'une séparation."""
    rated = IMPORTANCE.get(ev.importance, 0.45)
    if yearly(ev) and _painful(ev):
        return max(rated, IMPORTANCE[4])
    return max(rated, IMPORTANCE[3]) if _IMPORTANT.search(fold(ev.texte)) else rated


def festive(ev: XEvenement) -> bool:
    """Un moment qui se fête : le modèle le dit, ou ses mots (« son anniversaire de 30 ans ») — jamais ce qui fait
    mal (« l'anniversaire de la mort de son père », une date que la personne vit douloureusement)."""
    return (ev.a_feter or bool(_FESTIVE.search(fold(ev.texte)))) and not _painful(ev)


def yearly(ev: XEvenement) -> bool:
    """Une date qui revient chaque année (un anniversaire, la date d'un deuil) : le modèle le dit, ou ses mots
    (« son anniversaire », « ça fera un an que… ») — jamais une situation qui dure."""
    return not ev.en_cours and (ev.chaque_annee or bool(_YEARLY.search(fold(ev.texte))))


#: ce qui date un élément sans dire de quoi il parle : deux souvenirs du même mois ne se ressemblent pas pour autant
#: (sonde réelle du 2026-10-11 : « … le dimanche 11 octobre 2026, sa mère hospitalisée » devenait secret parce qu'un
#: secret de la semaine disait aussi « octobre 2026 »)
_DATING = frozenset(stems(" ".join((*DAYS_FR, *MONTHS_FR, "semaine", "dernier", "derniere", "prochain", "prochaine",
                                    "matin", "matinee", "soir", "soiree", "journee", "lundi", "aujourd'hui", "hier",
                                    "demain", "weekend", "week-end"))))


def _subject(text: str, names: set[str]) -> set[str]:
    return {s for s in stems(text) - names if s not in _DATING and not s.isdigit()}


def echoes(text: str, secrets: Sequence[str], names: set[str]) -> bool:
    """Ce texte laisse-t-il deviner un de ces secrets ? (au moins deux mots du
    sujet en commun — un seul si le secret n'en a qu'un —, prénoms, dates et
    nombres exclus)."""
    mine = _subject(text, names)
    for secret in secrets:
        theirs = _subject(secret, names)
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


#: un souvenir à la première personne qui reprend au moins cette part des mots d'une autre parle à sa place
VOICE_SHARE = 0.6
#: ce par quoi commence un texte à la première personne (replié)
_FIRST_PERSON = frozenset({"je", "j", "moi", "mon", "ma", "mes"})


def voice_of(text: str, lines: Sequence[Line]) -> Line | None:
    """La réplique d'une autre personne qu'un souvenir à la première personne reprend à son compte : « J'ai eu une
    petite fille, Jeanne : je suis épuisée mais tellement heureuse », tiré de Carol (« je viens d'avoir une petite
    fille, Jeanne, je suis épuisée… »), fait parler Mika à sa place (sonde réelle du 2026-10-09) — reformulé, il
    échappe à ``copied``. Un souvenir à elle (« J'ai consolé Carol, épuisée mais heureuse ») en reprend trop peu."""
    mine = WORD.findall(wfold(text))
    if not mine or mine[0] not in _FIRST_PERSON:
        return None
    best: tuple[float, Line] | None = None
    for ln in lines:
        if not ln.person:
            continue
        theirs = WORD.findall(wfold(ln.text))
        share = sum(b.size for b in SequenceMatcher(None, mine, theirs, autojunk=False).get_matching_blocks())
        share /= len(mine)
        if share >= VOICE_SHARE and (best is None or share > best[0]):
            best = (share, ln)
    return best[1] if best else None


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
    return phrase("memory.extraction.quoted", name=name or phrase("memory.extraction.someone"), words=words_)


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
