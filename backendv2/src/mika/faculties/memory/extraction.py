"""La consolidation, côté modèle : la consigne, l'outil, et ce qu'on attend en retour.

Sortie structurée par un outil déclaré (``record_memories``) ; à défaut, le
premier objet JSON du texte, lu avec indulgence (« contenu » pour « texte »…).
Un élément illisible est écarté, jamais la fenêtre entière.

Ce qu'on lui montre d'une conversation (ses personnes et leurs jetons, le
message rendu) vit dans ``conversation.py`` ; comment les noms qu'il écrit
redeviennent des personnes, dans ``speakers.py``. Ce que le code lit lui-même
dans les mots (un secret demandé, une chose à faire, un deuil, une réplique
recopiée, un surnom…), dans ``cues.py`` ; le filet qui vérifie une version
sans nom (ADR 0091), dans ``retelling.py``.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from mika.contracts.memory import Relation
from mika.kernel.clock import instant
from mika.kernel.faculty import schema_of
from mika.ports.llm import LLMResponse, ToolDecl
from mika.vocab.affect import facets
from mika.vocab.people import clean_tokens, fold
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

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


# les noms des classes du schéma (``XSouvenir``, ``XCroyance``, ``XPromesse``, ``XTenue``, ``XEvenement``,
# ``XPrevision``, ``XConstat``) et de leurs champs restent en français, à l'écart de la règle des identifiants
# anglais : le schéma de l'outil les montre au modèle (``schema_of(Extraction)['$defs']`` les nomme), ils sont du
# prompt. Ne pas les renommer.
class _Item(_Lenient):
    texte: str = Field(min_length=3, max_length=600, validation_alias=_TEXT)
    sur_elle: bool = Field(default=False, description=phrase("memory.extraction.fields.sur_elle"))
    genre: str | None = Field(default=None, description=phrase("memory.extraction.fields.genre"))
    personnes: list[str] = Field(default_factory=list, description=phrase("memory.extraction.fields.personnes"))
    sensibilite: str | None = Field(default=None, validation_alias=_SENS,
                                    description=phrase("memory.extraction.fields.sensibilite"))
    secret: bool = Field(default=False, description=phrase("memory.extraction.fields.secret"))
    messages: list[int] = Field(default_factory=list, description=phrase("memory.extraction.fields.messages"))
    #: les pièces jointes d'où il vient (leurs repères, « #12.1 ») — en plus de ses messages, plusieurs au besoin
    #: (ADR 0106)
    pieces: list[str] = Field(default_factory=list, description=phrase("memory.extraction.fields.pieces"))
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

    @field_validator("pieces", mode="before")
    @classmethod
    def lenient_pieces(cls, v: Any) -> list[str]:
        """« #12.1 », 12.1, « [#12.1] » ou un nom de fichier, seuls ou en liste."""
        return [str(x) for x in (v if isinstance(v, list) else [v] if v not in (None, "") else [])
                if isinstance(x, str | int | float) and not isinstance(x, bool)]

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
    return ToolDecl(TOOL_NAME, phrase("memory.extraction.tool", name=name), schema_of(Extraction))


def self_names(name: str) -> frozenset[str]:
    """Comment le modèle peut la désigner, elle (repliés) : « moi », « elle »… et son nom, en entier ou son prénom."""
    folded = " ".join(fold(name).split())
    return SELF_NAMES | {n for n in (folded, *folded.split()[:1]) if n}


def system(name: str, persona: str) -> str:
    """La consigne de la relecture, au nom de celle dont c'est la mémoire (celui de sa persona : jamais écrit ici),
    puis qui elle est (``persona``, sa persona rendue : ``self.portrayed``) — ce qu'elle garde d'elle-même se juge à
    ce qui est vrai d'elle, et ce qu'elle ressent à son caractère (ADR 0153)."""
    intro = phrase("self.portrayed.intro", name=name, persona=persona)
    return phrase("memory.extraction.system", name=name) + "\n\n" + intro


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
        # des numéros écrits « #12 », en texte ou un seul hors liste passent (``lenient_ids``) ; ce qui ne se lit pas
        # est signalé, jamais toute la fenêtre jetée pour lui quand souvenirs et croyances étaient valides
        ids = [i for i in Extraction.lenient_ids(items) if i > 0]
        if items and not ids:
            out.issues.append(f"{key}: identifiants illisibles")
        setattr(out, key, ids)
    return out


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
