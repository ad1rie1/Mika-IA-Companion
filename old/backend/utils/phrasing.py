"""Phrasage varié — sortir du figé sans payer un appel LLM.

Le vécu intérieur de Mika est aujourd'hui un *switch*. La raison d'un cycle de
conscience passe par une chaîne de ``elif`` sur des sous-chaînes
(``conscience/engine.py``) : quatre phrases littérales, et la première qui
matche gagne. Le ressenti est rendu par neuf gabarits pour vingt-neuf émotions,
la vie pulsionnelle par douze phrases. Conséquence mesurable : une réponse un
peu vive produit toujours la même rumination, à la virgule près, et un cycle
qui cumule *salutation* ET *débordement d'humeur* n'en garde qu'un — le premier
écrit dans la chaîne, jamais le plus fort.

Ce module fournit la moitié générique du correctif : un vivier de variantes,
un tirage qui **évite de se répéter**, une échelle d'adverbes qui ne retombe
pas sur « fortement » à chaque fois, et de quoi **composer plusieurs
déclencheurs en une seule phrase** — c'est le cœur : la chaîne de ``elif``
n'était pas seulement pauvre, elle était *exclusive*.

Trois propriétés tiennent tout le reste :

* **Zéro import du projet.** Pas de Django, pas de configuration, pas d'ORM,
  pas même ``utils.degradation``. Le module est appelé depuis les boucles de
  fond — non supervisées, où une exception qui s'échappe tue la boucle pour la
  vie du process — donc il ne fait aucune E/S et ne lève pas sur le chemin
  chaud : un vivier vide rend ``None`` ou ``""``, jamais une exception.
* **Pur et déterministe sous graine.** Chaque tirage porte son propre
  ``random.Random`` ; deux instances construites avec la même graine rendent la
  même suite. Les tests mesurent donc une politique déclarée, pas le hasard de
  la machine qui les exécute.
* **La configuration se résout au bord.** Sur le modèle de
  ``conscience/scoring.py::ScoringTuning``, les réglages vivent dans une
  dataclasse gelée dont les défauts *sont* les constantes de module. Le module
  ne lit aucun registre : ce sera à l'appelant de résoudre un
  ``ReglagePhrasing`` et de le passer, s'il veut rendre ces valeurs éditables.
"""

from __future__ import annotations

import math
import random
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence, TypeVar

# ── Constantes de réglage ────────────────────────────────────────────────────
#
# Elles restent au **niveau module** (et non en attributs de classe) parce que
# c'est la forme que la garde AST du dépôt sait relire, et parce qu'un repli
# doit être lisible là où on cherche la valeur qui a tourné.

#: Combien de choix récents le tirage garde en tête.
#:
#: Trop court (1) et le tirage se contente d'interdire le doublon immédiat, ce
#: qui produit une alternance mécanique sur un vivier de deux. Trop long et un
#: petit vivier finit avec toutes ses options amorties en même temps, donc plus
#: amorties du tout les unes par rapport aux autres.
MEMOIRE_TIRAGE = 4

#: Facteur appliqué au poids du **dernier** choix. Les choix plus anciens
#: remontent linéairement vers 1.0 à mesure qu'ils sortent de la mémoire.
#:
#: Ce n'est jamais 0 : une option bannie tant qu'elle est en mémoire rendrait le
#: tirage sur un vivier d'une seule option impossible, et surtout ferait de
#: l'anti-répétition une *règle* là où on veut un *penchant*. Mika peut redire
#: la même chose deux fois de suite — ça doit juste être rare.
AMORTISSEMENT = 0.15

#: Plancher dur de l'amortissement. Un appelant qui passerait 0.0 croirait
#: interdire la répétition ; il annulerait en fait tous les poids d'un vivier
#: dont chaque option est en mémoire, et le tirage retomberait sur son repli
#: uniforme — soit exactement le contraire de ce qu'il demandait.
AMORTISSEMENT_MINIMAL = 0.01

#: Nombre maximal de déclencheurs cités dans une phrase composée.
#:
#: Au-delà de trois, l'énumération cesse d'être une phrase : c'est une liste, et
#: le modèle la recopie au lieu de s'en servir. Les déclencheurs sont triés par
#: poids, donc ce sont les plus forts qui survivent à la coupe — pas le premier
#: écrit dans le code, qui était le critère de la chaîne de ``elif``.
MAX_DECLENCHEURS_COMPOSES = 3

#: Ponctuations qui closent déjà une phrase (on n'en rajoute pas).
_PONCTUATIONS_FINALES = ".!?…"


@dataclass(frozen=True)
class ReglagePhrasing:
    """Les réglages du phrasage, nommés, avec les constantes pour défauts.

    Ce module reste **pur** : il ne lit ni base ni registre. Un
    ``ReglagePhrasing()`` sans argument reproduit mot pour mot le comportement
    par défaut, ce qui laisse aux tests leur sens — ils mesurent la calibration
    déclarée, pas ce que contient la base de la machine.
    """

    memoire: int = MEMOIRE_TIRAGE
    amortissement: float = AMORTISSEMENT
    max_declencheurs: int = MAX_DECLENCHEURS_COMPOSES


#: Réglage partagé : le construire une fois évite de rebâtir la dataclasse à
#: chaque tirage.
REGLAGE_PAR_DEFAUT = ReglagePhrasing()


# ── Le tirage ────────────────────────────────────────────────────────────────

T = TypeVar("T")


class TirageAmorti:
    """Tirage pondéré qui évite de se répéter, sans jamais rien interdire.

    Le tirage pondéré nu a un défaut que l'on voit tout de suite à l'usage :
    sur un vivier de cinq phrases équiprobables, une répétition immédiate
    arrive une fois sur cinq, et l'utilisateur la lit comme un bug (« elle a
    buggé, elle a redit la même chose »). L'interdiction pure a le défaut
    inverse : sur un vivier de deux, elle produit une alternance parfaite, qui
    est un motif aussi reconnaissable que la répétition.

    D'où l'amortissement : le dernier choix garde un poids, simplement
    ``AMORTISSEMENT`` fois plus faible, et remonte vers son poids nominal à
    mesure qu'il sort de la mémoire. Sur cinq options équipondérées avec les
    défauts, la probabilité de répétition immédiate tombe de 20 % à ~5 %.

    Une occurrence *multiple* en mémoire prend le facteur de la plus récente —
    et non le produit des facteurs. Le produit (0.15² = 0.02) serait un
    bannissement de fait, ce que la classe s'interdit.

    L'instance porte son propre générateur : deux ``TirageAmorti(graine=…)``
    identiques rendent la même suite, et deux appelants distincts ne se volent
    pas leur mémoire d'anti-répétition.
    """

    __slots__ = ("_rng", "_memoire", "_amortissement", "_taille", "_verrou")

    def __init__(
        self,
        *,
        reglage: ReglagePhrasing | None = None,
        graine: int | None = None,
    ) -> None:
        r = reglage or REGLAGE_PAR_DEFAUT
        taille = max(0, int(r.memoire))
        self._taille = taille
        self._memoire: deque = deque(maxlen=taille)
        # Borné des deux côtés : au-dessus de 1.0 l'« amortissement »
        # *favoriserait* la répétition, ce qui n'est un réglage de personne.
        self._amortissement = min(1.0, max(AMORTISSEMENT_MINIMAL, float(r.amortissement)))
        # Un verrou plutôt qu'une confiance dans le GIL : le tirage est appelé
        # depuis la boucle asyncio *et* depuis les tics de modules exécutés en
        # threads. `random.Random` n'est pas réentrant, et une mémoire mutée à
        # deux mains rendrait le déterminisme sous graine faux au moment même
        # où on s'y fie.
        self._verrou = threading.Lock()
        self._rng = random.Random(graine)

    # -- lecture ---------------------------------------------------------

    @property
    def derniers(self) -> tuple:
        """Les choix mémorisés, du plus récent au plus ancien."""
        return tuple(self._memoire)

    def oublier(self) -> None:
        """Vider la mémoire d'anti-répétition (nouvelle situation, nouveau fil)."""
        with self._verrou:
            self._memoire.clear()

    # -- tirage ----------------------------------------------------------

    def tirer(
        self,
        options: Sequence[T] | Iterable[T],
        poids: Sequence[float] | Callable[[T], float] | None = None,
    ) -> T | None:
        """Rendre une option, amortie par les choix récents.

        ``poids`` accepte une suite parallèle, une fonction, ou rien — auquel
        cas l'attribut ``poids`` de l'option est lu s'il existe (c'est le cas de
        ``Phrase``), 1.0 sinon.

        Rend ``None`` sur un vivier vide : un appelant du chemin chaud n'a rien
        à gagner à une exception, et « pas de phrase » est une sortie valide.
        """
        liste = list(options)
        if not liste:
            return None

        bases = _poids_de_base(liste, poids)
        # Tout à zéro (ou négatif, ou NaN) : le vivier existe, l'appelant s'est
        # trompé de pondération. On tire uniformément plutôt que de rendre
        # `None` — se taire parce qu'un poids est mal écrit serait un silence
        # inexplicable pour celui qui lit la sortie.
        if not any(b > 0.0 for b in bases):
            bases = [1.0] * len(liste)

        with self._verrou:
            amortis = [b * self._facteur(o) for o, b in zip(liste, bases)]
            total = sum(amortis)
            if total <= 0.0:  # ceinture : l'amortissement est borné > 0
                choix = liste[self._rng.randrange(len(liste))]
            else:
                seuil = self._rng.random() * total
                cumul = 0.0
                choix = liste[-1]
                for option, poids_amorti in zip(liste, amortis):
                    cumul += poids_amorti
                    if seuil < cumul:
                        choix = option
                        break
            if self._taille:
                self._memoire.appendleft(_cle(choix))
            return choix

    # -- interne ---------------------------------------------------------

    def _facteur(self, option: object) -> float:
        """Poids relatif d'une option d'après son ancienneté dans la mémoire.

        Le plus récent vaut ``amortissement`` ; on remonte linéairement vers
        1.0 en sortant de la mémoire. ``deque.index`` rend la position la plus
        récente, donc le facteur le plus sévère : c'est bien la plus récente
        occurrence qui décide, jamais le produit des occurrences.
        """
        if not self._taille:
            return 1.0
        try:
            rang = self._memoire.index(_cle(option))
        except ValueError:
            return 1.0
        return self._amortissement + (1.0 - self._amortissement) * (rang / self._taille)


def _cle(option: object) -> object:
    """Clé de mémoire d'une option.

    Un ``Phrase`` gelé est hachable ; une liste ou un dict passé par un
    appelant ne l'est pas. On retombe alors sur sa représentation textuelle,
    ce qui donne une anti-répétition approximative plutôt qu'un ``TypeError``
    au fond d'une boucle de fond.
    """
    try:
        hash(option)
    except TypeError:
        return ("§repr", repr(option))
    return option


def _poids_de_base(
    liste: list,
    poids: Sequence[float] | Callable | None,
) -> list[float]:
    """Normaliser les poids : négatif, NaN et infini valent zéro.

    Un NaN qui traverse la roulette rend *toutes* les comparaisons fausses et
    fait sortir systématiquement la dernière option — un biais silencieux, donc
    exactement le genre de panne que ce dépôt refuse d'avaler sans le dire.
    """
    brut: list[float]
    if poids is None:
        brut = [_flottant(getattr(o, "poids", 1.0)) for o in liste]
    elif callable(poids):
        brut = [_flottant(poids(o)) for o in liste]
    else:
        valeurs = list(poids)
        # Une suite trop courte complète à 1.0 : mieux vaut un poids par défaut
        # qu'un IndexError sur le chemin chaud.
        brut = [
            _flottant(valeurs[i]) if i < len(valeurs) else 1.0 for i in range(len(liste))
        ]
    return [b if b > 0.0 else 0.0 for b in brut]


def _flottant(valeur: object) -> float:
    try:
        v = float(valeur)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return v


# ── Les variantes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Phrase:
    """Une variante d'un vivier : un texte, un poids, des étiquettes.

    Les étiquettes disent **quand** la variante a le droit de sortir, et pas
    à quoi elle sert : une phrase sans étiquette convient à toute situation,
    une phrase étiquetée ``{"nuit"}`` n'est éligible que si « nuit » est dans la
    situation, et une étiquette préfixée ``!`` est une exclusion
    (``"!inconnu"`` = jamais devant quelqu'un qu'elle n'identifie pas).

    Écrire les textes en **propositions** (sans point final, sans majuscule
    imposée) : ``composer`` les enchaîne avec des liants et pose la ponctuation.

    Gelée, donc hachable : la mémoire d'anti-répétition peut s'en servir
    directement comme clé, sans passer par le texte.
    """

    texte: str
    poids: float = 1.0
    etiquettes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Confort d'écriture : un vivier se déclare avec des tuples ou des sets
        # littéraux ; on normalise ici pour que l'égalité et le hachage de deux
        # phrases identiques ne dépendent pas du conteneur choisi à l'écriture.
        if not isinstance(self.etiquettes, frozenset):
            object.__setattr__(self, "etiquettes", frozenset(self.etiquettes or ()))


def eligibles(vivier: Iterable[Phrase], situation: Iterable[str] = ()) -> list[Phrase]:
    """Les phrases du vivier compatibles avec la situation, dans l'ordre déclaré.

    Le filtre est *permissif par défaut* : une phrase ne demandant rien passe
    partout. C'est ce qui permet d'écrire un vivier générique et de n'étiqueter
    que les variantes qui ont une condition — sans quoi tout ajout d'étiquette
    dans la situation aurait rétréci le vivier au lieu de l'enrichir.
    """
    contexte = set(situation)
    retenues = []
    for phrase in vivier:
        requises = {e for e in phrase.etiquettes if not e.startswith("!")}
        interdites = {e[1:] for e in phrase.etiquettes if e.startswith("!")}
        if requises <= contexte and not (interdites & contexte):
            retenues.append(phrase)
    return retenues


def formuler(
    vivier: Iterable[Phrase],
    *,
    situation: Iterable[str] = (),
    tirage: TirageAmorti | None = None,
) -> str:
    """Filtrer puis tirer une variante ; rendre son texte, ou ``""``.

    ``""`` et non ``None`` : le seul usage est la concaténation dans un prompt,
    où un ``None`` deviendrait la chaîne « None » au premier f-string distrait.
    """
    choix = (tirage or _tirage_partage()).tirer(eligibles(vivier, situation))
    return choix.texte if choix is not None else ""


# ── L'échelle d'adverbes ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Palier:
    """Un palier d'intensité : sa borne basse (incluse) et ses formulations."""

    seuil: float
    formulations: tuple[str, ...]


#: Échelle par défaut, pour une valeur dans [0, 1] (intensité d'émotion,
#: tension de pulsion, pression de rumination).
#:
#: Plusieurs formulations par palier, parce que le défaut réparé ici est
#: précis : un seul mot par palier fait que *toute* la nuance mesurée par
#: l'oscillateur se réduit, dans le prompt, à cinq phrases possibles pour la
#: vie affective entière.
PALIERS_INTENSITE: tuple[Palier, ...] = (
    Palier(0.00, ("à peine", "tout juste", "vaguement")),
    Palier(0.20, ("un peu", "légèrement", "doucement")),
    Palier(0.45, ("assez", "plutôt", "pas qu'un peu")),
    Palier(0.70, ("vraiment", "nettement", "franchement")),
    Palier(0.88, ("profondément", "intensément", "complètement")),
)


def adverbe(
    valeur: float,
    paliers: Sequence[Palier] = PALIERS_INTENSITE,
    *,
    tirage: TirageAmorti | None = None,
) -> str:
    """Rendre une intensité en mots, sans retomber deux fois sur le même.

    Les paliers sont **retriés** à l'appel plutôt que supposés ordonnés : un
    vivier déclaré dans le désordre choisirait sinon un palier faux en
    silence, et une échelle d'adverbes fausse ne se voit pas dans un prompt —
    elle se lit comme une émotion mal jaugée.

    Une valeur hors échelle (négative, > 1, NaN) est ramenée aux extrêmes : le
    chemin chaud ne lève pas, et l'appelant qui divise par zéro quelque part en
    amont obtient « à peine » plutôt qu'une boucle morte.
    """
    ordonnes = sorted(paliers, key=lambda p: p.seuil)
    if not ordonnes:
        return ""
    v = _flottant(valeur)
    retenu = ordonnes[0]
    for palier in ordonnes:
        if v >= palier.seuil:
            retenu = palier
        else:
            break
    if not retenu.formulations:
        return ""
    choix = (tirage or _tirage_partage()).tirer(retenu.formulations)
    return choix if choix is not None else ""


# ── La composition ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Declencheur:
    """Une raison d'ouvrir la bouche, et les façons de la dire.

    ``poids`` sert deux fois : à trier (les plus forts survivent à la coupe de
    ``max_declencheurs``) et à ordonner la phrase produite. La chaîne de
    ``elif`` qu'on remplace triait par *position dans le code* et n'en gardait
    qu'un : un cycle qui cumulait salutation et débordement d'humeur perdait le
    second, quelle que soit son intensité.
    """

    cle: str
    vivier: tuple[Phrase, ...]
    poids: float = 1.0


#: Liants pour enchaîner deux propositions. Tirés comme le reste, sinon la
#: variété des fragments serait mangée par la fixité de la couture : trois
#: phrases différentes cousues par un « , et » invariable se lisent comme une
#: seule phrase à trous.
LIANTS: tuple[Phrase, ...] = (
    Phrase(", et "),
    Phrase(" — et "),
    Phrase(" ; "),
    Phrase(", en plus "),
)


def assembler(
    fragments: Sequence[str],
    *,
    tirage: TirageAmorti | None = None,
    liants: Sequence[Phrase] = LIANTS,
) -> str:
    """Coudre des propositions en une phrase capitalisée et ponctuée.

    Les fragments vides sont ignorés (un vivier filtré à zéro rend ``""``, et
    ce trou ne doit pas produire « , et  , et »).
    """
    utiles = [f.strip() for f in fragments if f and f.strip()]
    if not utiles:
        return ""
    t = tirage or _tirage_partage()
    texte = utiles[0]
    for suite in utiles[1:]:
        liant = t.tirer(liants)
        texte += (liant.texte if liant is not None else ", et ") + suite
    texte = texte[0].upper() + texte[1:]
    if texte[-1] not in _PONCTUATIONS_FINALES:
        texte += "."
    return texte


def composer(
    declencheurs: Iterable[Declencheur],
    *,
    situation: Iterable[str] = (),
    tirage: TirageAmorti | None = None,
    reglage: ReglagePhrasing | None = None,
    liants: Sequence[Phrase] = LIANTS,
) -> str:
    """Dire **tous** les déclencheurs retenus en une phrase.

    C'est le correctif central : ce qui déclenche un cycle est presque toujours
    pluriel (inactivité *et* pulsion, salutation *et* humeur), et n'en énoncer
    qu'un donnait au modèle un motif appauvri de sa propre situation.

    Les déclencheurs sont triés par poids décroissant — le tri de Python est
    stable, donc à poids égal l'ordre de déclaration est conservé et la sortie
    reste reproductible sous graine — puis coupés à ``max_declencheurs``.
    """
    r = reglage or REGLAGE_PAR_DEFAUT
    t = tirage or _tirage_partage()
    contexte = set(situation)

    tries = sorted(declencheurs, key=lambda d: -_flottant(d.poids))
    fragments = []
    for decl in tries:
        if len(fragments) >= max(0, int(r.max_declencheurs)):
            break
        texte = formuler(decl.vivier, situation=contexte, tirage=t)
        # Un déclencheur dont tout le vivier est filtré ne consomme pas une
        # place : sinon une étiquette de situation restreinte ferait taire les
        # déclencheurs suivants, plus faibles mais eux disponibles.
        if texte:
            fragments.append(texte)
    return assembler(fragments, tirage=t, liants=liants)


# ── Tirage partagé (repli quand l'appelant n'en fournit pas) ─────────────────

_TIRAGE_PARTAGE: TirageAmorti | None = None
_VERROU_PARTAGE = threading.Lock()


def _tirage_partage() -> TirageAmorti:
    """Le tirage utilisé quand l'appelant n'en passe pas.

    Partagé volontairement : l'anti-répétition n'a de sens que si la mémoire
    survit d'un appel à l'autre, et un appelant qui construirait un
    ``TirageAmorti`` neuf à chaque phrase obtiendrait un tirage nu — le défaut
    qu'on répare. Un appelant qui veut du déterminisme (les tests, un
    rejeu) passe le sien.
    """
    global _TIRAGE_PARTAGE
    with _VERROU_PARTAGE:
        if _TIRAGE_PARTAGE is None:
            _TIRAGE_PARTAGE = TirageAmorti()
        return _TIRAGE_PARTAGE


def reinitialiser_tirage_partage() -> None:
    """Repartir d'une mémoire vierge (bascule de contexte, isolation de test)."""
    global _TIRAGE_PARTAGE
    with _VERROU_PARTAGE:
        _TIRAGE_PARTAGE = None
