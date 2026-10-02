"""Contrat d'``affect`` : l'humeur, la posture envers chacun, la chaleur.

Trois échelles de temps, que les lectures gardent séparées :

- l'**émotion du moment** (une vingtaine de minutes) : ce qu'une impulsion
  vient de déplacer — ce qui « déborde » ;
- le **fond d'une journée** (quelques heures d'éveil) : ce que l'émotion du
  moment, tenue longtemps, laisse derrière elle — le sommeil l'allège ;
- ce qu'une **relation** a installé (jours, semaines) : l'ancre, qui guérit, et
  l'attachement, plus lent encore.

Toutes les mesures d'une relation se lisent contre son repos **moyen sur
24 h** : elles ne varient jamais avec l'heure qu'il est.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.facts import FactFamily, FactKey
from mika.vocab.affect import ORIGIN, Declared, Emotion, Vec3

OWNER = "affect"

#: Raisons de preuve d'initiative.
MOOD_OVERFLOW = "mood_overflow"


@dataclass(frozen=True, slots=True)
class MoodReading:
    position: Vec3
    #: là où serait son humeur sans rien de ce qu'elle a vécu (le repos commun,
    #: rejoint en douceur après un changement de phase) : ce dont on mesure ``felt``
    home: Vec3
    felt: Emotion  # ce que dit l'écart au repos (émotion du moment + fond)
    felt_intensity: float
    overflow: float  # ce que lisent les portes : l'émotion du moment seule, pas le fond
    label: Emotion  # la position absolue (ce que montre le visage)
    intensity: float
    #: le fond d'une journée (borné), compris dans ``position``
    fond: Vec3 = ORIGIN
    #: pourquoi elle se sent ainsi, si elle le sait : un code (``talk``, ``retour``,
    #: ``rêve``…), jamais un texte libre ; ``""`` : sans trop savoir pourquoi
    cause: str = ""
    #: la personne d'un échange qui l'a mise dans cet état (``cause == "talk"``)
    cause_person: str = ""
    #: ce que le fond garde de sa journée (« un petit reste de tristesse ») : l'émotion
    #: récente qui l'explique le mieux, pas une lecture contre le repos de l'heure
    fond_emotion: Emotion = Emotion.NEUTRAL
    #: la cause est un état qui a pris fin (« personne ne t'a parlé » — et quelqu'un est venu depuis) : elle se
    #: dit au passé, ce qui en reste au présent
    cause_over: bool = False


@dataclass(frozen=True, slots=True)
class StanceReading:
    person: str
    position: Vec3
    home: Vec3  # là où serait sa posture sans les impulsions récentes (son repos envers la personne)
    felt: Emotion
    felt_intensity: float
    #: ce qu'elle lui a déclaré, en décroissance — tant que ça dit plus que la position
    declared: Declared | None
    anchor: Vec3 | None  # l'ancre en absolu (repos moyen + ce que la relation a installé)
    at_rest: bool  # rien de particulier sur le moment
    anchored: bool  # plusieurs tours de suite dans le même sens, un écart net
    reference: Vec3 = ORIGIN  # son repos moyen sur 24 h
    regard: float = 0.0  # voir ``REGARD``
    hostility: float = 0.0  # voir ``HOSTILITY``
    bond: float = 0.0  # voir ``BOND``
    declared_at: int = 0
    declared_reply: bool = True  # sa déclaration était une réponse (sinon : elle avait écrit d'elle-même)
    #: l'ancre porte ce que dit la posture : ça ne passera pas en deux minutes
    lasting: bool = False
    #: la dernière fois que cette personne s'est excusée, et que ça a compté (0 : jamais)
    apologized_at: int = 0


@dataclass(frozen=True, slots=True)
class Face:
    """Ce que montrent le visage et les trames : la balise de sa dernière
    réplique tant qu'elle dure (en décroissance), sinon 60 % la posture envers
    la personne, 40 % son humeur à elle."""

    emotion: Emotion
    intensity: float
    blend: tuple[tuple[Emotion, float], ...]
    person: tuple[Emotion, float]
    mood: tuple[Emotion, float]


MOOD = FactKey("affect.mood", type=MoodReading, time_varying=True)
STANCE = FactFamily("affect.stance", arg=str, type=StanceReading, time_varying=True)
#: ``max(0, REGARD)`` : la chaleur, dans [0, 1].
WARMTH = FactFamily("affect.warmth", arg=str, type=float, time_varying=True)
#: Ce que cette personne a installé, signé, dans [−1, 1] : la part du chemin du
#: plaisir de son repos moyen vers le plaisir maximal (> 0) ou minimal (< 0) que
#: l'ancre a parcourue, **plus** une part de l'attachement (``BOND`` ×
#: ``bond_regard``). Une longue amitié garde donc un regard positif après une
#: dispute ; un chagrin partagé ne le fait pas baisser (l'empathie se fond vers
#: la tendresse). 14 soirées chaleureuses : de l'ordre de 0,3.
REGARD = FactFamily("affect.regard", arg=str, type=float, time_varying=True)
#: L'hostilité que cette personne a installée, dans [0, 1] : un écart déplaisant
#: **et** dominant de l'ancre (la colère, le dégoût, la frustration) — pas le
#: chagrin partagé — multiplié par ``1 − bond_damping × BOND`` (on en veut moins
#: à une amie de longue date), jamais sous une méfiance plancher (0,1, quatorze
#: jours) envers quelqu'un qui n'est pas une amie et dont l'hostilité a passé
#: 0,3. Elle guérit lentement : une demi-vie qui s'allonge avec la répétition
#: (jusqu'à trois semaines). La rancune se lit ici.
HOSTILITY = FactFamily("affect.hostility", arg=str, type=float, time_varying=True)
#: L'attachement à cette personne, dans [0, 1] : nourri par ses déclarations
#: chaleureuses **et** empathiques envers elle, demi-vie de deux mois, jamais
#: négatif. Une dispute ne l'entame pas.
BOND = FactFamily("affect.bond", arg=str, type=float, time_varying=True)
FACE = FactFamily("affect.face", arg=str, type=Face, time_varying=True)
