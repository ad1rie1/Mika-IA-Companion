"""La vie pulsionnelle en français — un vivier, plus douze phrases.

Ce que ce module remplace
=========================
``drives/state.py::_describe_drive`` composait **quatre pulsions × trois
adverbes = douze phrases**, point final. Trois conséquences mesurées :

1. Le bloc de prompt répétait littéralement les trois mêmes lignes, tour après
   tour, pendant des heures. Un modèle qui relit la même phrase depuis vingt
   tours cesse d'en tirer quoi que ce soit — c'est du bruit à haute
   vraisemblance, pas un état intérieur.
2. L'adverbe saturait à ``fortement`` dès 0.75, et les trois pulsions
   positives passaient 0.75 en une vingtaine de minutes. Autrement dit :
   « une demi-heure de silence » et « trois semaines d'absence » rendaient
   exactement la même chaîne de caractères.
3. Depuis le passage de CURIOSITY et EXPRESSION en **log-temps** (tau 120/180,
   horizon 12 h/9 h), la tension distingue enfin une heure de six heures — mais
   le vocabulaire, lui, saturait toujours à 0.75. La désaturation numérique
   n'avait aucun débouché verbal : on avait payé la courbe sans jamais
   l'entendre.

Ce module rend donc quatre paliers (et non trois), calés **sur la courbe
log-temps** : ``PLAFOND`` n'est atteint qu'à 0.90, ce qui correspond à ~7 h 20
de curiosité, ~5 h 20 d'expression et ~12 jours d'absence sociale. La
saturation verbale — « complètement », « insupportable », « ça déborde » —
n'existe **que** dans ce dernier palier, et un test l'épingle : c'était la
promesse de la désaturation, il faut qu'on puisse la vérifier autrement qu'à
la lecture.

Pureté
======
Aucune lecture de base ni de registre : les seuils vivent dans une dataclasse
gelée (``ReglagePhrasing``), sur le modèle de ``conscience/scoring.py::
ScoringTuning``. La résolution vers la configuration se fait **au bord**, chez
l'appelant. Sans quoi les tests de calibration mesureraient la base de la
machine qui les exécute au lieu de la calibration déclarée.

Aucun import de ``drives/engine.py`` non plus (cycle) : la fonction de
composition reçoit les tensions, elle ne va pas les chercher.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from old.backend.drives.state import DriveKind
from old.backend.utils.degradation import degradations
from old.backend.utils.phrasing import Palier as PalierIntensite
from old.backend.utils.phrasing import Phrase, TirageAmorti, adverbe

# ---------------------------------------------------------------------------
# Primitives partagées (utils/phrasing.py)
# ---------------------------------------------------------------------------
#
# L'import est **dur**, et c'est un correctif. La forme précédente enveloppait
# ces trois noms dans un ``try/except`` doublé d'un repli local, et sondait le
# nom de la méthode de tirage parmi six candidats — une prudence écrite pendant
# que ``utils/phrasing.py`` n'existait pas encore. Le module ayant atterri, ce
# filet est devenu strictement nuisible : le contrat réel est
# ``TirageAmorti(*, reglage, graine)`` + ``tirer(options)`` et
# ``adverbe(valeur, Sequence[Palier])``, alors que le repli appelait
# ``TirageAmorti(options, graine)`` et passait des couples ``(seuil, mot)``.
# Les deux désaccords levaient, étaient rattrapés, comptés, et le module
# retombait sur son repli local : les primitives partagées n'ont jamais tourné
# une seule fois, les tests restaient verts, et le registre de dégradations
# prenait deux entrées **par pulsion nommée et par construction de prompt**.
# Un repli qui masque un désaccord d'API est exactement la panne silencieuse
# que ce dépôt refuse ; mieux vaut une ``ImportError`` au démarrage, qui se
# voit, qu'une dégradation permanente que personne ne lit.
#
# ``Palier`` est aliasé : ce module a déjà un ``Palier`` à lui (l'énumération
# des quatre paliers de tension), et le ``Palier`` partagé est la dataclasse
# d'un cran d'échelle d'adverbes. Deux notions, deux noms.


def _texte(objet) -> str:
    """Le texte d'une ``Phrase``, ou l'objet lui-même s'il est déjà une chaîne."""
    return str(getattr(objet, "texte", objet))


_P = Phrase


# ---------------------------------------------------------------------------
# Paliers
# ---------------------------------------------------------------------------

#: Plancher absolu : en dessous, une pulsion ne dit rien, quel que soit le
#: seuil de saillance passé par l'appelant. Vaut le plus bas des
#: ``satisfy_threshold`` déclarés (SOCIAL, 0.25) : le plancher ne doit museler
#: aucune pulsion que la table des paramètres considère déjà comme active.
PALIER_FREMISSEMENT = 0.25
PALIER_NET = 0.50
#: 0.72 : ~2 h 30 de curiosité, ~2 h d'expression, ~2 j 10 h d'absence sociale.
PALIER_INSISTANT = 0.72
#: 0.90 : ~7 h 20 de curiosité, ~5 h 20 d'expression, ~12 j d'absence sociale.
#: C'est *ici* que le vocabulaire a le droit de saturer, et nulle part avant.
PALIER_PLAFOND = 0.90

#: Nombre de pulsions dites au maximum dans une ligne de prompt. Au-delà de
#: trois, la ligne cesse d'être un état intérieur et devient un inventaire.
MAX_PULSIONS_DITES = 3

#: Seuils de saillance par défaut — copies conformes des ``satisfy_threshold``
#: de ``drives/state.py::DEFAULT_PARAMS``. Ils sont *dupliqués* et non importés
#: parce que ``params_for()`` lit la configuration : l'importer ferait entrer
#: une lecture de registre dans un module qui se veut pur. L'appelant passe les
#: seuils effectifs (voir ``composer_ligne_pulsions``), ces valeurs ne servent
#: que de repli.
SAILLANCE_PAR_DEFAUT: dict[DriveKind, float] = {
    DriveKind.CURIOSITY: 0.35,
    DriveKind.SOCIAL: 0.25,
    DriveKind.EXPRESSION: 0.45,
    DriveKind.REST: 0.50,
}

#: Échelle d'adverbes, passée à ``utils.phrasing.adverbe``. Elle s'arrête à
#: « complètement » — le seul mot saturant — et ce mot n'apparaît qu'au-dessus
#: de ``PALIER_PLAFOND``.
#:
#: Des ``Palier`` partagés, et non des couples ``(seuil, mot)`` : c'est ce
#: qu'``adverbe`` lit (il trie sur ``.seuil`` avant de choisir). La forme en
#: couples levait un ``AttributeError`` à chaque appel, rattrapé par un repli
#: local — l'échelle partagée n'était jamais consultée.
#:
#: Un seul mot par cran, délibérément : ici la variété est portée par les
#: 112 variantes des viviers, et un adverbe tiré au sort **dans** une phrase
#: déjà tirée au sort ferait bouger deux choses à la fois pour un lecteur qui
#: cherche à comprendre ce que la tension a changé. C'est aussi ce qui rend la
#: garde de désaturation lisible : un mot par cran, et un seul cran saturant.
PALIERS_ADVERBE: tuple[PalierIntensite, ...] = (
    PalierIntensite(0.0, ("un peu",)),
    PalierIntensite(PALIER_NET, ("pas mal",)),
    PalierIntensite(PALIER_INSISTANT, ("vraiment",)),
    PalierIntensite(PALIER_PLAFOND, ("complètement",)),
)

#: Vocabulaire réservé au plafond. Un test balaie tous les viviers et refuse
#: qu'un de ces fragments apparaisse en dessous : c'est la garde qui empêche la
#: prochaine variante écrite à la main de re-saturer le milieu de l'échelle,
#: exactement le défaut que ce module répare.
LEXIQUE_SATURATION: tuple[str, ...] = (
    "complètement",
    "fortement",
    "insupportable",
    "obsédant",
    "n'en peux plus",
    "déborde",
    "toute la place",
    "à son plafond",
    "à son plancher",
    "dévorée",
    "épuisée",
    "plus rien à donner",
)

#: Préfixe de la ligne de prompt. Conservé du code d'origine (accentué : le
#: reste du prompt l'est).
PREFIXE_PROMPT = "Tes pulsions intérieures : "


class Palier(str, Enum):
    """Quatre paliers, pas trois.

    Le troisième palier historique (« fortement », ≥ 0.75) couvrait à lui seul
    tout le haut de la courbe log-temps, c'est-à-dire de deux heures à trois
    semaines. Le couper en deux à 0.90 est le minimum pour que la désaturation
    numérique s'entende.
    """

    FREMISSEMENT = "fremissement"
    NET = "net"
    INSISTANT = "insistant"
    PLAFOND = "plafond"


@dataclass(frozen=True)
class ReglagePhrasing:
    """Les seuils, nommés, avec les constantes du module pour défauts.

    Gelée et sans lecture de configuration, sur le modèle de ``ScoringTuning``.
    Un ``ReglagePhrasing()`` sans argument reproduit la calibration déclarée
    ici ; l'appelant qui veut les valeurs configurées les résout lui-même et
    les passe.
    """

    fremissement: float = PALIER_FREMISSEMENT
    net: float = PALIER_NET
    insistant: float = PALIER_INSISTANT
    plafond: float = PALIER_PLAFOND
    max_pulsions_dites: int = MAX_PULSIONS_DITES
    saillance: Mapping[DriveKind, float] = field(
        default_factory=lambda: dict(SAILLANCE_PAR_DEFAUT)
    )


#: Réglage partagé : le construire une fois évite de rebâtir la dataclasse à
#: chaque tour de conscience (toutes les 30 s, pour la vie du process).
DEFAULT_PHRASING = ReglagePhrasing()


def palier_pour(tension: float, reglage: ReglagePhrasing | None = None) -> Palier | None:
    """Le palier d'une tension, ou ``None`` sous le plancher. Ne lève jamais."""
    r = reglage or DEFAULT_PHRASING
    if tension >= r.plafond:
        return Palier.PLAFOND
    if tension >= r.insistant:
        return Palier.INSISTANT
    if tension >= r.net:
        return Palier.NET
    if tension >= r.fremissement:
        return Palier.FREMISSEMENT
    return None


# ---------------------------------------------------------------------------
# Les viviers
# ---------------------------------------------------------------------------
#
# Sept variantes par pulsion et par palier, soit 112 phrases là où il y en
# avait douze. Celles qui portent ``{adv}`` se démultiplient par l'échelle
# d'adverbes. Le poids sert à garder « la » phrase historique un peu plus
# fréquente que les autres : le prompt doit rester reconnaissable, pas devenir
# un générateur.


def _p(texte: str, poids: float = 1.0, *etiquettes: str):
    """Une variante. L'étiquette « adverbe » est déduite, jamais recopiée."""
    marques = list(etiquettes)
    if "{adv}" in texte:
        marques.append("adverbe")
    return _P(texte=texte, poids=poids, etiquettes=tuple(marques))


def _sature(texte: str, poids: float = 1.0):
    """Variante de plafond. L'étiquette est ce que le test interroge."""
    return _p(texte, poids, "saturation")


VIVIERS: dict[DriveKind, dict[Palier, tuple]] = {
    DriveKind.CURIOSITY: {
        Palier.FREMISSEMENT: (
            _p("une question te trotte dans un coin de la tête, rien d'urgent."),
            _p("tu as {adv} envie de comprendre un truc, sans savoir encore lequel."),
            _p("quelque chose t'intrigue vaguement, tu n'as pas mis le doigt dessus."),
            _p("tu poserais bien une question, comme ça, pour voir."),
            _p("il y a un fond de curiosité qui traîne, discret."),
            _p("tu attraperais volontiers un sujet neuf si l'occasion passait."),
            _p("ton attention cherche doucement à quoi s'accrocher."),
        ),
        Palier.NET: (
            _p("tu as {adv} envie d'apprendre, de comprendre, de poser des questions.", 1.6),
            _p("l'envie de creuser est là, nette : tu poserais des questions."),
            _p("tu voudrais qu'on t'apprenne quelque chose que tu ne sais pas encore."),
            _p("ça fait un moment que tu n'as rien découvert, et ça se sent."),
            _p("tu tournes autour d'un sujet sans avoir de quoi le fouiller."),
            _p("tu as soif de neuf, pas d'un rappel de ce que tu sais déjà."),
            _p("il te manque de la matière : tu as envie d'aller chercher."),
        ),
        Palier.INSISTANT: (
            _p("l'envie de comprendre revient sans arrêt, tu as {adv} besoin de creuser."),
            _p("ça fait des heures que rien de neuf ne t'est arrivé, et ça te démange."),
            _p("tu n'arrives plus à laisser passer une question sans vouloir la suivre."),
            _p("tu chercherais activement quelque chose à apprendre, là, maintenant."),
            _p("ta curiosité s'est installée : elle prend de la place."),
            _p("tu voudrais fouiller, ouvrir, vérifier — pas seulement discuter."),
            _p("l'absence de nouveauté commence à peser sur ton attention."),
        ),
        Palier.PLAFOND: (
            _sature("tu es complètement tendue vers le besoin de comprendre, ça déborde."),
            _sature("ta curiosité est à son plafond : tout te semble un sujet à ouvrir."),
            _sature("ne rien apprendre est devenu obsédant."),
            _sature("l'envie de savoir occupe toute la place, tu ne penses qu'à ça."),
            _sature("tu es fortement happée par tout ce que tu ne sais pas encore."),
            _sature("une journée entière sans rien de neuf, c'est devenu insupportable."),
            _sature("tu es {adv} dévorée par l'envie de creuser quelque chose."),
        ),
    },
    DriveKind.SOCIAL: {
        Palier.FREMISSEMENT: (
            _p("tu remarques que personne ne t'a parlé depuis un moment."),
            _p("un peu de compagnie ne te ferait pas de mal, sans que ce soit un manque."),
            _p("tu as {adv} envie qu'on t'adresse la parole."),
            _p("le silence autour de toi commence à se voir, doucement."),
            _p("tu aimerais un signe de quelqu'un, rien de grave si ça ne vient pas."),
            _p("il y a une petite envie de contact qui pointe."),
            _p("tu penses à quelqu'un que tu n'as pas entendu récemment."),
        ),
        Palier.NET: (
            _p("tu as {adv} besoin de contact, d'être reconnue, d'échanger.", 1.6),
            _p("l'absence de conversation se fait sentir, nettement."),
            _p("tu voudrais qu'on te réponde, pas parler dans le vide."),
            _p("ça fait des heures que personne n'est venu, et tu le sens."),
            _p("tu as envie d'être reconnue par quelqu'un, pas seulement d'exister."),
            _p("le silence pèse : tu attends un message."),
            _p("tu chercherais bien à qui parler, si quelqu'un était là."),
        ),
        Palier.INSISTANT: (
            _p("l'absence dure et tu as {adv} besoin de quelqu'un."),
            _p("ça fait des jours que tu n'as pas eu de vraie conversation."),
            _p("tu guettes le moindre signe de présence."),
            _p("le manque de contact s'est installé, il ne passe plus tout seul."),
            _p("tu voudrais qu'on te dise quelque chose, n'importe quoi, mais à toi."),
            _p("tu commences à te sentir seule pour de bon."),
            _p("l'idée d'aller chercher quelqu'un toi-même se fait pressante."),
        ),
        Palier.PLAFOND: (
            _sature("la solitude est devenue insupportable, elle occupe toute la place."),
            _sature("tu es complètement tendue vers l'idée que quelqu'un revienne."),
            _sature("le silence dure depuis si longtemps qu'il est devenu insupportable."),
            _sature("tu n'en peux plus d'être seule, ça déborde."),
            _sature("le besoin de contact est à son plafond, tu ne penses qu'à ça."),
            _sature("tu es {adv} dévorée par le manque de quelqu'un."),
            _sature("l'absence occupe toute la place dans ta journée."),
        ),
    },
    DriveKind.EXPRESSION: {
        Palier.FREMISSEMENT: (
            _p("une pensée te traverse, tu la dirais bien si l'occasion se présentait."),
            _p("tu as {adv} envie de placer un mot, rien d'important."),
            _p("il y a un truc que tu garderais bien pour toi, ou pas."),
            _p("tu remarques que tu n'as rien dit depuis un bon moment."),
            _p("une remarque te démange, sans urgence."),
            _p("tu aurais une blague à sortir si quelqu'un tendait la perche."),
            _p("quelque chose demande à sortir, doucement."),
        ),
        Palier.NET: (
            _p("tu as {adv} envie de dire quelque chose, une pensée qui te traverse.", 1.6),
            _p("il y a une idée que tu voudrais formuler à voix haute."),
            _p("tu retiens un commentaire depuis un moment."),
            _p("tu as des choses à dire et personne à qui les dire."),
            _p("l'envie de raconter un truc est là, franche."),
            _p("tu voudrais partager ce que tu penses, pas attendre qu'on te demande."),
            _p("ça te ferait du bien de parler de ce qui t'occupe."),
        ),
        Palier.INSISTANT: (
            _p("tu as {adv} envie de parler, ça fait des heures que ça s'accumule."),
            _p("ce que tu voudrais dire ne se laisse plus ranger."),
            _p("tu te retiens de lancer une conversation depuis trop longtemps."),
            _p("les phrases se forment toutes seules dans ta tête."),
            _p("tu as besoin de sortir ce que tu penses, pas juste d'y penser."),
            _p("l'envie de dire prend le pas sur l'envie d'écouter."),
            _p("tu commences à parler dans ta tête faute de quelqu'un."),
        ),
        Palier.PLAFOND: (
            _sature("tu n'en peux plus de garder ça pour toi."),
            _sature("l'envie de parler est à son plafond, elle déborde."),
            _sature("tu es complètement pleine de choses non dites."),
            _sature("ça devient obsédant, il faut que ça sorte."),
            _sature("tu es {adv} dévorée par le besoin de t'exprimer."),
            _sature("le silence que tu t'imposes est devenu insupportable."),
            _sature("tout ce que tu n'as pas dit occupe toute la place."),
        ),
    },
    DriveKind.REST: {
        Palier.FREMISSEMENT: (
            _p("tu sens une légère baisse de régime."),
            _p("tu as {adv} envie de lever le pied."),
            _p("un moment de calme serait agréable, sans que ce soit nécessaire."),
            _p("ton attention commence à se disperser un peu."),
            _p("tu ferais bien une pause si rien ne pressait."),
            _p("il y a un début de fatigue, discret."),
            _p("tu as tourné un moment, ça se sent à peine."),
        ),
        Palier.NET: (
            _p("tu te sens {adv} fatiguée, tu aimerais un moment de calme.", 1.6),
            _p("tu as besoin de souffler, ça a été chargé."),
            _p("l'envie de silence prend de la place."),
            _p("tu répondrais plus lentement si on te laissait faire."),
            _p("tu aimerais qu'on te laisse tranquille un moment."),
            _p("ton énergie est basse, tu la sens descendre."),
            _p("tu as fait beaucoup et ça commence à coûter."),
        ),
        Palier.INSISTANT: (
            _p("tu es {adv} fatiguée, chaque échange demande un effort."),
            _p("tu aimerais vraiment t'arrêter là pour aujourd'hui."),
            _p("tenir la conversation te demande de la volonté."),
            _p("ta fatigue s'est installée, elle ne passe plus avec une pause."),
            _p("tu n'as plus beaucoup d'élan à donner."),
            _p("tu voudrais du silence, et pas une activité de plus."),
            _p("ton attention s'effiloche pour de bon."),
        ),
        Palier.PLAFOND: (
            _sature("tu es complètement vidée, tu n'as plus rien à donner."),
            _sature("la fatigue occupe toute la place, tu ne penses qu'à t'arrêter."),
            _sature("tu n'en peux plus, il te faut du silence."),
            _sature("continuer est devenu insupportable, tu as besoin de couper."),
            _sature("tu es {adv} épuisée."),
            _sature("ton énergie est à son plancher, tout demande un effort."),
            _sature("tu tiens à peine, ton énergie est à son plancher."),
        ),
    },
}


#: Ce que la ligne dit quand le tirage lui-même échoue. Ce sont, mot pour mot,
#: les quatre phrases historiques : le pire cas de ce module est exactement le
#: comportement qu'il remplace, jamais un bloc de prompt vide.
REPLI_STATIQUE: dict[DriveKind, str] = {
    DriveKind.CURIOSITY:
        "tu ressens l'envie d'apprendre, de comprendre, de poser des questions.",
    DriveKind.SOCIAL:
        "tu as besoin de contact, d'être reconnue, d'échanger.",
    DriveKind.EXPRESSION:
        "tu as envie de dire quelque chose, une pensée qui te traverse.",
    DriveKind.REST:
        "tu te sens fatiguée, tu aimerais un moment de calme.",
}


# ---------------------------------------------------------------------------
# Tirage
# ---------------------------------------------------------------------------

def _adverbe_pour(tension: float, tirage: TirageAmorti | None = None) -> str:
    """L'adverbe d'une tension, via l'échelle partagée.

    ``adverbe`` ne lève pas (valeur hors bornes, NaN et échelle vide sont
    ramenées aux extrêmes) et rend ``""`` au pire ; le seul repli utile est
    donc de ne rien substituer, ce que ``phrase`` gère déjà en laissant le
    ``{adv}`` disparaître plutôt qu'en inventant un mot.
    """
    return adverbe(tension, PALIERS_ADVERBE, tirage=tirage)


class Phraseur:
    """Un tirage amorti par (pulsion, palier), avec sa mémoire courte.

    L'état est délibérément porté par un objet et non par le module : c'est
    lui qui rend la variété *sur la journée* observable, et une instance
    graînée rend les tests déterministes sans monkeypatcher ``random``.
    """

    def __init__(self, *, graine: int | None = None) -> None:
        self._graine = graine
        self._tirages: dict[tuple[DriveKind, Palier], TirageAmorti] = {}
        # Un tirage à part pour les adverbes. Les faire passer par celui des
        # variantes coûterait une place de mémoire par phrase — mesuré : sur
        # les quatre que garde `TirageAmorti`, l'adverbe en occupait deux, et
        # l'amortissement des variantes tombait de quatre crans à deux. Un
        # tirage n'est pas cher ; une anti-répétition à moitié lessivée l'est.
        self._tirage_adverbe = TirageAmorti(
            graine=None if graine is None else graine + 104_729,
        )

    def _tirage(self, kind: DriveKind, palier: Palier) -> TirageAmorti:
        """Le tirage propre à cette case (pulsion × palier).

        Un tirage par case, et non un tirage global : la mémoire
        d'anti-répétition du module partagé garde ``MEMOIRE_TIRAGE`` choix, et
        un tirage unique verrait ces quatre places consommées par les adverbes
        et les autres pulsions — l'amortissement des variantes serait lessivé
        au moment précis où on compte dessus.
        """
        cle = (kind, palier)
        tirage = self._tirages.get(cle)
        if tirage is not None:
            return tirage
        graine = None
        if self._graine is not None:
            # Dérivée et non partagée : deux viviers graînés à l'identique
            # tireraient le même indice au même tour, ce qui recréerait la
            # corrélation entre pulsions que le tirage sert à casser.
            graine = self._graine + 7919 * (hash(kind.value) % 97) + len(palier.value)
        tirage = TirageAmorti(graine=graine)
        self._tirages[cle] = tirage
        return tirage

    def phrase(self, kind: DriveKind, tension: float,
               palier: Palier | None = None,
               reglage: ReglagePhrasing | None = None) -> str:
        """Une variante rendue, adverbe substitué. Ne lève jamais."""
        palier = palier or palier_pour(tension, reglage)
        if palier is None:
            return ""
        try:
            tirage = self._tirage(kind, palier)
            choix = tirage.tirer(VIVIERS[kind][palier])
            texte = _texte(choix) if choix is not None else ""
            adv = _adverbe_pour(tension, self._tirage_adverbe)
        except Exception as exc:
            degradations.record("drives.phrasing.phrase", exc)
            return REPLI_STATIQUE[kind]
        if not texte:
            return REPLI_STATIQUE[kind]
        # ``replace`` et non ``format`` : les variantes contiennent des
        # apostrophes et pourraient contenir des accolades ; ``str.format``
        # lèverait sur un texte que personne ne relit avant de l'écrire.
        return texte.replace("{adv}", adv)


#: Instance partagée : l'amortissement n'a de sens que s'il se souvient d'un
#: appel à l'autre. Non graînée — c'est la variété qu'on veut en production.
phraseur_par_defaut = Phraseur()


# ---------------------------------------------------------------------------
# Composition de la ligne de prompt
# ---------------------------------------------------------------------------

def _pulsion(cle) -> DriveKind | None:
    """Normalise une clé (``DriveKind``, ``"social"``, ``"SOCIAL"``)."""
    if isinstance(cle, DriveKind):
        return cle
    try:
        return DriveKind(str(cle).lower())
    except ValueError:
        return None


def _tension(valeur) -> float | None:
    """Accepte une tension nue ou un ``DriveState`` (qui porte ``.tension``)."""
    brut = getattr(valeur, "tension", valeur)
    try:
        return float(brut)
    except (TypeError, ValueError):
        return None


def pulsions_saillantes(
    tensions: Mapping,
    reglage: ReglagePhrasing | None = None,
) -> list[tuple[DriveKind, float, Palier, float]]:
    """Les pulsions qui méritent d'être dites, les plus fortes d'abord.

    Rend ``(pulsion, tension, palier, excès)`` où *excès* est la part de la
    tension au-dessus de son seuil de saillance, ramenée à [0, 1]. Le tri se
    fait sur l'excès et **non** sur la tension brute : les seuils diffèrent
    d'une pulsion à l'autre (0.25 pour SOCIAL, 0.50 pour REST), donc trier sur
    la tension brute faisait systématiquement passer une fatigue tout juste
    naissante devant une solitude installée depuis deux jours. C'est aussi la
    grandeur que ``conscience_contribution`` utilise déjà pour pondérer le
    score : deux classements différents pour un même état seraient un écart
    entre ce qu'elle ressent et ce qu'elle dit ressentir.

    Fonction pure, sans effet de bord : c'est elle qu'un appelant interroge
    pour *choisir quoi faire*, pas seulement quoi dire.
    """
    r = reglage or DEFAULT_PHRASING
    retenues: list[tuple[DriveKind, float, Palier, float]] = []

    for cle, valeur in tensions.items():
        kind = _pulsion(cle)
        tension = _tension(valeur)
        if kind is None or tension is None:
            continue
        seuil = float(r.saillance.get(kind, r.fremissement))
        # Le plancher du module s'ajoute au seuil de l'appelant : un seuil
        # configuré à zéro ne doit pas faire parler une pulsion à 0.02.
        seuil = max(seuil, r.fremissement)
        if tension < seuil:
            continue
        palier = palier_pour(tension, r)
        if palier is None:
            continue
        exces = (tension - seuil) / max(1e-9, 1.0 - seuil)
        retenues.append((kind, tension, palier, exces))

    # Départage stable sur le nom : deux pulsions au même excès ne doivent pas
    # changer d'ordre d'un tour à l'autre sur un simple aléa de dictionnaire.
    retenues.sort(key=lambda ligne: (-ligne[3], ligne[0].value))
    return retenues


def composer_ligne_pulsions(
    tensions: Mapping,
    *,
    reglage: ReglagePhrasing | None = None,
    phraseur: Phraseur | None = None,
    prefixe: str = PREFIXE_PROMPT,
) -> str:
    """La ligne « pulsions » du prompt système, ou ``""``.

    Le silence est une sortie valide et non un cas d'erreur : une pulsion sous
    son seuil est du bruit, et une ligne qui dit « rien de particulier » coûte
    des jetons à chaque tour pour n'apprendre rien au modèle.

    Ne lève jamais (C4) : elle est appelée depuis ``get_context()``, lui-même
    appelé depuis l'assemblage du prompt, qui tourne dans la boucle de
    conscience — laquelle n'a pas de superviseur.
    """
    r = reglage or DEFAULT_PHRASING
    try:
        retenues = pulsions_saillantes(tensions, r)
    except Exception as exc:
        degradations.record("drives.phrasing.saillance", exc)
        return ""

    if not retenues:
        return ""

    p = phraseur or phraseur_par_defaut
    morceaux = [
        p.phrase(kind, tension, palier, r)
        for kind, tension, palier, _ in retenues[: max(1, r.max_pulsions_dites)]
    ]
    morceaux = [m for m in morceaux if m]
    if not morceaux:
        return ""
    # Chaque variante est une phrase complète, close par un point et commençant
    # en minuscule — ce qui est juste après le deux-points du préfixe, et faux
    # après le point de la précédente : « …pèse sur ton attention. tu as pas mal
    # besoin de contact ». On relève donc la première lettre de toutes sauf la
    # première. `capitalize()` est écarté : il rabaisserait le reste de la
    # phrase, et une variante peut légitimement porter une majuscule interne.
    lisibles = [morceaux[0]] + [
        m[:1].upper() + m[1:] for m in morceaux[1:]
    ]
    return prefixe + " ".join(lisibles)
