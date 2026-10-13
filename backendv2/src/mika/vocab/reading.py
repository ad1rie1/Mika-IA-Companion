"""Ce qu'elle a senti de la personne qui lui écrit (ADR 0093) — pur.

Le modèle qui lui répond lit le message ; c'est lui qui juge, jamais une liste de mots. À la fin de sa réponse il
écrit une balise que la personne ne voit pas :

    [EN_FACE: sad 0.6, anxious 0.3 | geste : excuses | grave : rupture]

- **ce qu'elle ressent**, en facettes (les 29 émotions, une intensité de 0 à 1) — « rien » quand rien ne se lit ;
- **son geste envers Mika**, s'il est net : un merci, un compliment, des excuses, des mots qui blessent, ou ce
  qui la déçoit (un oubli, de la froideur, un rejet) ;
- **un événement grave** qui la touche : un deuil, une maladie ou un accident, une rupture, une perte de travail,
  de la détresse.

Le geste et l'événement sont des catégories que le modèle choisit parmi celles qu'on lui donne ; ce module les
range (comme ``vocab.affect.emotion_named`` range un nom d'émotion), il ne lit jamais le message de la personne.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mika.vocab.affect import Facet, facets
from mika.vocab.words import fold

_MD = r"[*_`~]*"
#: ``[EN_FACE: …]``, ``[EN FACE : …]``, crochets doublés, parenthèses ; non fermée en fin de ligne
TAG = re.compile(
    _MD + r"(?:\[\[|[\[({])\s*EN[\s_\-]?FACE\s*[:=]\s*(?P<body>[^\]\)}\n]{0,240}?)\s*(?:\]\]|[\])}]|(?=\n|$))"
    + _MD, re.IGNORECASE)

# Les gestes envers elle (les mêmes valeurs que ``contracts.self_``).
THANKED, COMPLIMENTED, INSULTED, APOLOGIZED = "thanked", "complimented", "insulted", "apologized"
#: ce qui la déçoit venant de la personne : un oubli, de la froideur, un rejet — pas des mots qui la visent, mais une
#: blessure quand même (ADR 0107)
DISAPPOINTED = "disappointed"
GESTURES = (THANKED, COMPLIMENTED, INSULTED, APOLOGIZED, DISAPPOINTED)
#: les gestes qui la blessent : sa peine n'y est pas de l'empathie (``affect``), elle refroidit la relation
HURTING = frozenset({INSULTED, DISAPPOINTED})
#: les mots du modèle pour un geste (repliés, début de mot) → le geste
_GESTURE_WORDS = (
    (("merci", "remerci", "gratitude", "reconnaissan"), THANKED),
    (("compliment", "eloge", "flatt", "admir"), COMPLIMENTED),
    (("excus", "pardon", "desole", "regret"), APOLOGIZED),
    (("bless", "insult", "mechan", "mepris", "agress", "offens", "humili", "cruel", "rabaiss"), INSULTED),
    (("decev", "decu", "decept", "oubli", "froid", "rejet", "delaiss", "neglig", "ignor"), DISAPPOINTED),
)

# Les événements graves : les sortes que le modèle choisit (``ToneRead.grave_kind``).
DISTRESS, MOURNING, ILLNESS, JOB_LOSS, BREAKUP = "distress", "mourning", "illness", "job_loss", "breakup"
#: un événement que le modèle dit grave sans le ranger : grave quand même
OTHER = "other"
_GRAVE_WORDS = (
    (("detresse", "suicid", "idees noires", "desespoir", "veut mourir", "en finir"), DISTRESS),
    (("deuil", "deces", "mort", "decede", "perte d un proche", "enterrement"), MOURNING),
    (("malad", "sante", "hopital", "accident", "blessure", "cancer", "operation", "urgence"), ILLNESS),
    (("rupture", "separ", "divorc", "quitte", "largu"), BREAKUP),
    (("travail", "emploi", "licenci", "chomage", "boulot", "job", "renvoi"), JOB_LOSS),
)
#: ce qui dit « rien » (repliés)
_NOTHING = frozenset({"", "rien", "aucun", "aucune", "non", "neant", "pas de", "rien de particulier", "calme",
                      "neutre", "neutral", "none", "-", "—"})


@dataclass(frozen=True, slots=True)
class Reading:
    """Ce que le modèle a lu de la personne : ses facettes (la plus forte d'abord ; aucune : rien ne se lisait),
    son geste envers elle (``""`` : aucun), un événement grave (``""`` : aucun ; ``OTHER`` : grave, sans sorte)."""

    felt: tuple[Facet, ...] = ()
    gesture: str = ""
    grave: str = ""

    def encode(self) -> str:
        felt = ",".join(f"{e}:{x:.2f}" for e, x in self.felt)
        return f"{felt};{self.gesture};{self.grave}"

    @classmethod
    def decode(cls, raw: str | None) -> Reading | None:
        if raw is None:
            return None
        felt_raw, _, rest = raw.partition(";")
        gesture, _, grave = rest.partition(";")
        felt = facets(felt_raw) if felt_raw else ()
        return cls(felt, gesture if gesture in GESTURES else "",
                   grave if grave in (*_kinds(), OTHER) else "")


def _kinds() -> tuple[str, ...]:
    return tuple(kind for _words, kind in _GRAVE_WORDS)


def _match(value: str, table: tuple[tuple[tuple[str, ...], str], ...]) -> str:
    key = " ".join(re.findall(r"[a-z0-9]+", fold(value)))
    for words, kind in table:
        if any(f" {w}" in f" {key}" for w in words):
            return kind
    return ""


def gesture_of(value: str) -> str:
    """Le geste qu'un modèle nomme (« excuses », « un merci », « des mots blessants ») ; ``""`` sinon."""
    return _match(value, _GESTURE_WORDS)


def grave_of(value: str) -> str:
    """La sorte d'un événement grave qu'un modèle nomme ; ``OTHER`` pour un événement grave qu'il ne range pas ;
    ``""`` pour « aucun »."""
    key = " ".join(re.findall(r"[a-z0-9]+", fold(value)))
    if key in _NOTHING:
        return ""
    return _match(value, _GRAVE_WORDS) or OTHER


_PART = re.compile(r"[|;]")
_KEYED = re.compile(r"^\s*(?P<key>gestes?|grave)\s*[:=]\s*(?P<value>.*)$", re.IGNORECASE)


def body_of(body: str) -> Reading:
    """Le contenu d'une balise ``EN_FACE`` : des facettes, puis ``geste : …`` et ``grave : …`` séparés par ``|``."""
    felt_parts: list[str] = []
    gesture = grave = ""
    for part in _PART.split(body):
        keyed = _KEYED.match(part)
        if keyed is None:
            felt_parts.append(part)
        elif keyed["key"].lower().startswith("geste"):
            gesture = gesture_of(keyed["value"])
        else:
            grave = grave_of(keyed["value"])
    return Reading(facets(", ".join(felt_parts)), gesture, grave)


def read(text: str) -> tuple[str, Reading | None]:
    """Le texte sans sa balise ``EN_FACE`` (toutes retirées : la personne ne les voit jamais), et ce que la dernière
    disait (``None`` : aucune balise — le modèle n'a rien déclaré, rien ne se lit)."""
    found = list(TAG.finditer(text or ""))
    if not found:
        return text or "", None
    return TAG.sub(" ", text), body_of(found[-1].group("body"))
