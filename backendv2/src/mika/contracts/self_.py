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

**Sa vie** est rédigée dans la persona : ce qu'elle fait à sa façon
(``life``), ses goûts et avis tranchés (``tastes``), ce qui est vrai d'elle
(``facts``) — pour qu'elle ne se contredise pas d'un jour à l'autre ; ses
façons de dire bonjour (``greetings``) donnent le ton d'une salutation, sans
jamais être recopiées. **Sa nature** (``nature``) dit ce qu'elle est : une IA
qui le sait (la persona livrée), ou une personne incarnée, dont rien ne parle
d'IA (ADR 0070). **Son nom** est celui de la persona, partout : aucun prompt ne
l'écrit en dur (``name_of``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.kernel.events import Content, Payload, VoiceProvenance, event_type
from mika.kernel.facts import FactKey
from mika.kernel.forms import Knob
from mika.vocab.temperament import Temperament

OWNER = "self"


def _lines(label: str, help: str, order: int, group: str = "Caractère") -> Knob:
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
    interests: Annotated[tuple[str, ...], _lines(
        "Centres d'intérêt", "Ce qui la passionne. Un sujet court d'abord, puis « — » et le détail (« Le café — "
        "snob sans en avoir jamais bu ») : le sujet seul titre ses explorations.", 90)] = ()
    speech: Annotated[tuple[str, ...], _lines("Façons de parler", "Ses tournures.", 100, "Sa parole")] = ()
    greetings: Annotated[tuple[str, ...], _lines(
        "Salutations", "Des exemples de ses bonjours : seuls leurs premiers mots (« hey », « yooo ») lui sont montrés "
        "quand elle salue quelqu'un qu'elle connaît — jamais la phrase, qu'un modèle recopiait.", 110,
        "Sa parole")] = ()
    life: Annotated[tuple[str, ...], _lines(
        "Sa vie, à sa façon", "Ce qu'elle fait vraiment de ses journées (jouer, regarder, lire des recettes, "
        "travailler…) : ce qu'elle raconte de son quotidien reste compatible avec ça.", 120, "Sa vie")] = ()
    tastes: Annotated[tuple[str, ...], _lines(
        "Ses goûts et ses avis", "Tranchés et stables : son plat préféré ne change pas d'une conversation à "
        "l'autre.", 130, "Sa vie")] = ()
    facts: Annotated[tuple[str, ...], _lines(
        "Ce qui est vrai d'elle", "Sa biographie (d'où elle vient, où elle habite, ce qu'elle a ou n'a pas) : ce "
        "qu'on lui demande de base, sans qu'elle esquive ni n'invente.", 140, "Sa vie")] = ()
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
    #: ce qu'elle raconterait de sa journée à n'importe qui : sa vie à elle, où personne d'autre n'apparaît —
    #: rendu d'après les faits qu'elle a le droit de dire, sans modèle (ADR 0053 ; avant : écrit par sa voix d'après
    #: des notes maigres, qu'elle comblait) ; ``None`` : un journal d'avant, qui ne se montre qu'à qui en est le seul
    #: concerné
    shareable: Content | None = None


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
    kind: str  # THANKED | COMPLIMENTED | INSULTED | APOLOGIZED


NIGHTMARE, PLEASANT, ASSOCIATIVE, MUNDANE = "nightmare", "pleasant", "associative", "mundane"
#: Un rêve triste, sans peur : ce qui pèse sans menacer.
MELANCHOLIC = "melancholic"
DREAM_KINDS = (NIGHTMARE, PLEASANT, MELANCHOLIC, ASSOCIATIVE, MUNDANE)
THANKED, COMPLIMENTED, INSULTED = "thanked", "complimented", "insulted"
#: des excuses (« pardon, je le pensais pas ») : une fois par jour et par personne, quand il y a de quoi pardonner
APOLOGIZED = "apologized"

PERSONA_REVISED = event_type("self.persona_revised", OWNER, PersonaRevised, public=True, version=2,
                             upcasters={1: _zone_repaired})
JOURNALED = event_type("self.journaled", OWNER, Journaled, public=True, content=("text", "shareable"),
                       subjects=("about",),
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
    #: sa journée à elle, sans personne d'autre (vide : un journal d'avant)
    shareable_ref: str = ""


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
