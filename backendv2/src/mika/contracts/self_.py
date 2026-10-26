"""Contrat de ``self`` : la persona (un document), le tempérament, l'estime,
le récit de soi, le journal de ses journées et ses rêves.

Le **journal** est écrit la nuit par sa voix, un par journée vécue (une
heure du matin appartient encore à la veille ; la journée commence une heure
avant son matin) ; une nuit coupée par une conversation le fait réécrire. Ce
qu'elle en raconterait à n'importe qui (``shareable``) est rendu d'après les
faits, sans modèle : rien d'inventé, personne d'autre (ADR 0053). Les
**rêves** naissent en sommeil paradoxal, deux par nuit au plus, de fragments
de ce qu'elle a vécu ; **au réveil** (``self.woke_with``) elle se souvient —
parfois — du plus vif, et ce que la nuit a apaisé se ressent à ce moment-là.
L'un et l'autre peuvent mêler d'autres personnes : ils portent ce qu'ils
concernent et leur sensibilité, et ne se montrent qu'à qui peut les entendre.

**L'estime** est aussi un sociomètre : un merci ou un compliment d'une amie la
relève un peu, une insulte qui la vise la blesse un peu (``self.touched``, un
jugement lu dans la forme du message, enregistré). Des **excuses** sincères
(lues dans la forme, une fois par jour et par personne, et seulement quand il
y a quelque chose à pardonner) adoucissent ce que ses mots lui avaient fait —
et ce que la relation en garde (``affect`` les lit).

**Qui elle est** s'écrit une fois, en prose : son portrait (``portrait``), lu
partout — sa vie, ses goûts, ses avis, ce qui la définit ; ce qui est vrai
d'elle (``facts``) l'ancre contre l'invention ; ses centres d'intérêt
(``interests``) font vivre ses explorations et ses flux (ADR 0138). Ce qu'elle
ressent et fait de ses émotions, c'est son tempérament qui le dit, jamais un
texte. Ses façons de dire bonjour (``greetings``) donnent le ton d'une
salutation, sans jamais être recopiées ; ses exemples (``samples``) montrent sa
voix en chat. **Sa nature** (``nature``) dit ce qu'elle est : une IA qui le
sait (la persona livrée), ou une personne incarnée, dont rien ne parle d'IA
(ADR 0070). **Son nom** est celui de la persona, partout : aucun prompt ne
l'écrit en dur (``name_of``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.kernel.codec import digest
from mika.kernel.events import Content, Payload, VoiceProvenance, event_type
from mika.kernel.facts import FactKey
from mika.kernel.forms import Knob
from mika.vocab import reading
from mika.vocab.lineage import Lineage, subjects
from mika.vocab.temperament import Temperament

OWNER = "self"


def _lines(label: str, help: str, order: int, group: str = "Portrait") -> Knob:
    return Knob(label=label, help=help + " Une phrase par ligne.", group=group, advanced=False, order=order)


#: Le nom d'une persona qui n'en dit pas : celui de la persona livrée (``persona/mika.yaml``). Le seul endroit du
#: code où il s'écrit — partout ailleurs, son nom vient de sa persona (``name_of``, ADR 0070).
DEFAULT_NAME = "Mika"

#: Sa nature : une IA qui le sait (la persona livrée), ou une personne incarnée — rien ne lui parle alors d'IA.
AI, EMBODIED = "ia", "incarnee"
Nature = Literal["ia", "incarnee"]


class PersonaDoc(BaseModel):
    """Le personnage, rédigé. Chaque liste est une suite de phrases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Knob(label="Nom", help="Comme elle se présente.", group="Identité", advanced=False,
                              order=10)] = DEFAULT_NAME
    nature: Annotated[Nature, Knob(
        label="Nature", group="Identité", advanced=False, order=15,
        choices=((AI, "une IA qui le sait"), (EMBODIED, "une personne (incarnée)")),
        help="Une IA qui le sait (si on le lui demande sincèrement, elle ne le cache pas), ou une personne incarnée : "
             "rien de ce qu'on lui dit d'elle-même ne parle alors d'IA. Sa vie, ses goûts et ce qui est vrai d'elle "
             "(ci-dessous) doivent aller avec.")] = AI
    description: Annotated[str, Knob(
        label="Description", group="Identité", widget="textarea", advanced=False, order=20,
        help="Qui elle est, en une phrase ou deux : ce qu'elle lit d'elle dans ses prompts courts (murmurer, "
             "travailler), et sa présentation dans la console.")] = ""
    portrait: Annotated[str, Knob(
        label="Portrait", group="Portrait", widget="textarea", advanced=False, order=25,
        help="Qui elle est, écrit comme on décrit quelqu'un : en prose, à la deuxième personne (« Tu es… »), avec sa "
             "vie, ses goûts, ses avis, ce qui l'agace. Le seul texte qui la décrit : elle le lit partout (en "
             "conversation, dans son journal, ses rêves, son travail). Ce qu'elle ressent et montre, c'est son "
             "tempérament qui le dit : ne l'écris pas ici, il l'emporterait sur les curseurs.")] = ""
    reference_thread: Annotated[str, Knob(
        label="Fil de référence (registre)", group="Sa parole", widget="textarea", advanced=False, order=45,
        help="Un vrai fil de SMS entre deux personnes, tel qu'on voudrait qu'elle écrive : la longueur des messages, "
             "leur rythme, ce qu'on y dit et ce qu'on tait. Seule la seconde passe le lit (rôle « polish », une "
             "autrice qui écrit la suite du fil à partir de son premier jet) : il donne la façon d'écrire, jamais "
             "les sujets. Vide : l'autrice écrit sans référence.")] = ""
    language: Annotated[str, Knob(label="Langue", help="Celle dans laquelle elle parle et écrit.",
                                  group="Identité", advanced=False, order=30)] = "français"
    facts: Annotated[tuple[str, ...], _lines(
        "Ce qui est vrai d'elle", "Ce que rien d'autre ne dit et qu'elle ne doit ni esquiver ni inventer : son "
        "corps, son âge, comment elle parle d'elle (le tutoiement, le féminin), ce qu'elle ne fait pas.", 30)] = ()
    interests: Annotated[tuple[str, ...], _lines(
        "Centres d'intérêt", "Ce qui la passionne. Un sujet court d'abord, puis « — » et le détail (« Le dessin — "
        "illustration, aquarelle ») : le sujet seul titre ses explorations, et leurs mots décident des titres de ses "
        "flux qui la touchent.", 35)] = ()
    greetings: Annotated[tuple[str, ...], _lines(
        "Salutations", "Des exemples de ses bonjours : seuls leurs premiers mots (« hey », « yooo ») lui sont montrés "
        "quand elle salue quelqu'un qu'elle connaît — jamais la phrase, qu'un modèle recopiait.", 110,
        "Sa parole")] = ()
    samples: Annotated[tuple[str, ...], _lines(
        "Exemples en conversation", "Quelques échanges qui montrent sa voix en chat (« ce qu'on lui dit » → « ce qu'elle "
        "répond ») : montrés pour le ton et le registre quand elle parle à quelqu'un, jamais une phrase à recopier, "
        "et jamais dans un mail ni un texte à envoyer.", 105, "Sa parole")] = ()
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

    @model_validator(mode="after")
    def _embodied_has_a_name(self) -> PersonaDoc:
        """Une persona incarnée a un nom : vide, ``name_of`` lui rendrait celui de la persona livrée, et elle
        s'entendrait appeler « Mika ». (Seulement pour ``incarnee``, un champ neuf : un journal d'avant, où un nom
        vide aurait pu passer par fichier, se relit toujours.)"""
        if self.nature == EMBODIED and not self.name.strip():
            raise ValueError("une persona incarnée a un nom (« name ») : c'est elle, pas la persona livrée")
        return self


def name_of(doc: PersonaDoc) -> str:
    """Comment elle s'appelle : le nom de sa persona (blancs repliés) — celui de la persona livrée s'il est vide."""
    return " ".join(doc.name.split()) or DEFAULT_NAME


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


#: les champs que la persona n'a plus (ADR 0138) : chacun redisait un curseur du tempérament, le portrait, la consigne
#: de style ou une autrice
_GONE = ("tone", "traits", "quirks", "vulnerabilities", "values", "speech", "life", "tastes")


def _gone_dropped(raw: dict[str, Any]) -> dict[str, Any]:
    """v2 → v3 : une persona journalisée avec les champs d'avant se relit sans eux (le rejeu ne casse pas)."""
    raw = dict(raw)
    persona = raw.get("persona")
    if isinstance(persona, dict):
        raw["persona"] = {k: v for k, v in persona.items() if k not in _GONE}
    return raw


class PersonaRevised(Payload):
    persona: PersonaDoc


def temperament_hash(t: Temperament) -> str:
    """L'empreinte d'un tempérament (ses curseurs, ses choix, ses précisions) : le caractère écrit la porte, et ne
    vaut que pour elle."""
    return digest(t.model_dump(mode="json"))


class CharacterWritten(Payload):
    """Son caractère, écrit par le modèle d'après sa matrice (ADR 0139) : six à huit phrases qui disent ce que ses
    traits font ensemble, à la place des 29 mesures. Du texte sur elle, comme son portrait, personne d'autre n'y
    est : pas un ``Content``. Il ne vaut que pour le tempérament dont il porte l'empreinte."""

    text: str
    temperament: str
    voice: VoiceProvenance


class Narrated(Payload):
    """Son récit d'elle-même (« Je suis quelqu'un qui… »), écrit par sa voix."""

    text: Content
    voice: VoiceProvenance
    souvenirs: int = 0  # combien de souvenirs elle avait en l'écrivant
    #: les personnes à travers qui elle a vécu ce qu'il reprend (sans les nommer) : l'oubli l'atteint
    about: tuple[str, ...] = ()
    #: les souvenirs qu'elle a relus pour l'écrire : l'un devenu secret, remplacé, il se réécrit (ADR 0082)
    sources: tuple[int, ...] = ()
    #: ce qu'elle savait d'elle et ses centres d'intérêt (clé, niveau) en l'écrivant : changés, il se réécrit (ADR 0090)
    knows: tuple[str, ...] = ()
    interests: tuple[tuple[str, str], ...] = ()


class Journaled(Payload):
    day: str  # AAAA-MM-JJ : la journée vécue
    text: Content
    voice: VoiceProvenance
    about: tuple[str, ...] = ()
    dominant: str = ""
    messages: int = 0
    #: ce qu'elle raconterait de sa journée à n'importe qui : sa vie à elle, où personne d'autre n'apparaît —
    #: rendu d'après les faits qu'elle a le droit de dire, sans modèle (ADR 0053 ; avant : écrit par sa voix d'après
    #: des notes maigres, qu'elle comblait) ; ``None`` : un journal d'avant, qui ne se montre qu'à qui en est le seul
    #: concerné
    shareable: Content | None = None
    #: ce qu'elle a relu pour l'écrire (souvenirs, promesses, pensées, ce qu'on lui a dit) et devant qui ses sources
    #: permettent d'en montrer la version intime ; ``None`` : un journal d'avant, l'ancienne règle
    lineage: Lineage | None = None

    @model_validator(mode="after")
    def _inherited_subjects(self):
        about = tuple(sorted({*self.about, *subjects(self.lineage)}))
        if self.lineage is not None and about != self.about:
            object.__setattr__(self, "about", about)
        return self


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
    #: devant qui ses sources (les souvenirs et les pensées rêvés) permettent de le raconter ; ``None`` : un rêve
    #: d'avant, la règle de ses personnes
    lineage: Lineage | None = None

    @model_validator(mode="after")
    def _inherited_subjects(self):
        # le secret que Bob a confié sur Sam ne fait pas un rêve « sur Sam » seul : Bob y est aussi
        about = tuple(sorted({*self.about, *subjects(self.lineage)}))
        if self.lineage is not None and about != self.about:
            object.__setattr__(self, "about", about)
        return self


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
    """Ce qu'un message dit d'elle et qui touche son estime : un merci, un compliment, une insulte qui la vise, une
    déception (ADR 0107), des excuses. Le geste que le modèle qui lui a répondu a lu (``vocab.reading``, ADR 0093),
    enregistré : le rejeu retombe sur la même estime."""

    person: str
    handle: str
    message: int
    kind: str  # THANKED | COMPLIMENTED | INSULTED | APOLOGIZED | DISAPPOINTED


class InterestBorn(Payload):
    """Un intérêt vécu est né (ADR 0089) : la nuit, elle a vu revenir un sujet dans ce qu'elle a lu, exploré, dans
    ce dont on lui a parlé, sur plusieurs jours. ``label`` : le sujet, dit par elle, dicible à tous et sans nommer
    personne ; ``detail`` : ce qu'il est pour elle ; ``about`` : de qui viennent les pistes (l'oubli d'une personne
    l'efface) ; ``evidence`` : les pistes qui l'ont fait naître."""

    night: str
    label: Content
    detail: Content | None = None
    about: tuple[str, ...] = ()
    evidence: tuple[int, ...] = ()


class Reflected(Payload):
    """Sa réflexion de la nuit sur ce qui la passionne (ADR 0089) : les pistes relues jusqu'à ``upto``, celles qui
    nourrissent un intérêt qu'elle a déjà (``attached`` : piste, clé d'intérêt)."""

    night: str
    upto: int = 0
    attached: tuple[tuple[int, str], ...] = ()
    call_id: str = ""
    model: str = ""


NIGHTMARE, PLEASANT, ASSOCIATIVE, MUNDANE = "nightmare", "pleasant", "associative", "mundane"
#: Un rêve triste, sans peur : ce qui pèse sans menacer.
MELANCHOLIC = "melancholic"
DREAM_KINDS = (NIGHTMARE, PLEASANT, MELANCHOLIC, ASSOCIATIVE, MUNDANE)
#: ce qu'une personne fait envers elle, tel que le modèle qui lui répond le lit (``vocab.reading``, ADR 0093) ;
#: des excuses comptent une fois par jour et par personne, quand il y a de quoi pardonner
THANKED, COMPLIMENTED, INSULTED, APOLOGIZED = reading.THANKED, reading.COMPLIMENTED, reading.INSULTED, \
    reading.APOLOGIZED
DISAPPOINTED = reading.DISAPPOINTED

PERSONA_REVISED = event_type("self.persona_revised", OWNER, PersonaRevised, public=True, version=3,
                             upcasters={1: _zone_repaired, 2: _gone_dropped})
CHARACTER_WRITTEN = event_type("self.character_written", OWNER, CharacterWritten, public=True)
JOURNALED = event_type("self.journaled", OWNER, Journaled, public=True, content=("text", "shareable"),
                       subjects=("about",),
                       authored=True)
DREAMT = event_type("self.dreamt", OWNER, Dreamt, public=True, content=("text",), subjects=("about",),
                    authored=True)
NARRATED = event_type("self.narrated", OWNER, Narrated, public=True, content=("text",), subjects=("about",),
                      authored=True)
WOKE_WITH = event_type("self.woke_with", OWNER, WokeWith, public=True)
TOUCHED = event_type("self.touched", OWNER, Touched, public=True, subjects=("person",))
INTEREST_BORN = event_type("self.interest_born", OWNER, InterestBorn, public=True, content=("label", "detail"),
                           subjects=("about",))
REFLECTED = event_type("self.reflected", OWNER, Reflected, public=True)

PERSONA = FactKey("self.persona", type=PersonaDoc)
#: son caractère écrit par le modèle pour le tempérament courant (ADR 0139) ; « » tant qu'il ne l'est pas — rien
#: ne le remplace : sa persona ne dit alors rien de son caractère
CHARACTER = FactKey("self.character", type=str)
#: L'estime de soi, dans [0,05 ; 0,95] : lente, revenant vers 0,5 (demi-vie de trois jours).
ESTEEM = FactKey("self.esteem", type=float, time_varying=True)
#: Ce qu'elle sait d'elle (ADR 0088) : des tendances tirées de ses réussites et de ses ratés récents — des codes
#: (``PROMISES_KEPT``…), jamais un nombre. L'estime n'en dépend pas.
KNOWS = FactKey("self.knows", type=tuple, time_varying=True)
PROMISES_KEPT, PROMISES_SLIP = "promises_kept", "promises_slip"
FINISHING_DONE, FINISHING_STRUGGLE = "finishing_done", "finishing_struggle"
FORESIGHT_RIGHT, FORESIGHT_OFF = "foresight_right", "foresight_off"
#: Ses centres d'intérêt vivants (ADR 0089), les plus vifs d'abord : des ``vocab.interests.InterestView`` — ceux de
#: sa persona n'y manquent jamais (endormis peut-être), ceux qu'elle a vécus y naissent et s'en vont.
INTERESTS = FactKey("self.interests", type=tuple, time_varying=True)


@dataclass(frozen=True, slots=True)
class JournalReading:
    day: str
    text_ref: str
    about: tuple[str, ...]
    dominant: str
    #: sa journée à elle, sans personne d'autre (vide : un journal d'avant)
    shareable_ref: str = ""
    #: devant qui sa version intime peut se montrer (``None`` : un journal d'avant, l'ancienne règle)
    lineage: Lineage | None = None
    #: une de ses sources est devenue secrète : seule la version partageable se montre (ADR 0082)
    masked: bool = False


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
    #: devant qui il peut se raconter (``None`` : un rêve d'avant, la règle de ses personnes)
    lineage: Lineage | None = None
    #: une de ses sources est devenue secrète : il ne se raconte plus (ADR 0082)
    masked: bool = False


#: Le journal de la dernière journée vécue avant aujourd'hui (``None`` s'il n'y en a pas) — pas forcément
#: celui d'hier : ``day`` le dit.
YESTERDAY = FactKey("self.yesterday", type=object, time_varying=True)
#: Le rêve de la nuit dernière dont elle s'est souvenue au réveil (``None`` : aucun — la plupart des matins).
DREAM_RESIDUE = FactKey("self.dream_residue", type=object, time_varying=True)
