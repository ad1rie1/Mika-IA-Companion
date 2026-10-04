"""Comment elle se raconte ce qui lui arrive.

Ce module ne décide rien : il **met en mots** ce que le scoring a déjà tranché.
Il existe parce que les deux endroits où la conscience se raconte étaient des
tables littérales, et que les deux mentaient à leur manière.

**Le premier** est la chaîne de `elif` de `ConscienceEngine._build_action_prompt` :

    if   "morning" in reason:  parts.append("C'est le matin ! ...")
    elif "evening" in reason:  ...
    elif "night"   in reason:  ...
    elif "mood"    in reason:  ...

Or `reason` est une *concaténation* : « idle(42m), mood(frustrated:0.81),
rumination(2×:0.28) » est un cas parfaitement ordinaire, et le `elif` n'en
gardait qu'un — le premier dans l'ordre du code, jamais le plus fort. Trois
déclencheurs sur quatre partaient à la poubelle avant même le prompt, et
l'inactivité comme les pulsions n'avaient aucune branche du tout.

**Le second** est `_AUDIT_EMOTIONS` : neuf gabarits littéraux pour vingt-neuf
émotions. Vingt en sortaient sans un mot — un tour marqué `melancholic` à 0.9
ne se rejouait jamais — et les neuf restants disaient toujours exactement la
même phrase, à la virgule près, dans chaque `Rumination` créée.

Ce module tient la moitié *conscience* du correctif ; la moitié générique — le
tirage amorti, les viviers, l'assemblage — vit dans `utils/phrasing.py` et
n'est pas réécrite ici. Ce qui reste propre à la conscience :

* **les viviers** : ce qu'il y a à dire pour chacun des sept motifs, dont trois
  (inactivité, pulsion, rumination) n'avaient aucune phrase alors qu'ils
  faisaient déjà monter le score ;
* **les portes** : elles reprennent celles de `conscience.scoring`, sans quoi
  le prompt annoncerait un débordement que le score n'a pas compté ;
* **la dérive** : `cible_de_derive` et `phrase_de_rejeu`, qui **dérivent** de
  l'ancre PAD déjà déclarée dans `emotion/pad.py` au lieu de recopier une ligne
  par émotion. Les vingt-neuf sont couvertes par construction, et une
  trentième le serait sans toucher à ce fichier.

**Tout est pur** : ni base, ni registre de configuration, ni appel LLM. C'est
la condition pour tenir sur un chemin traversé à chaque cycle de 30 s. Les
seuils vivent dans une dataclasse gelée (`VecuTuning`), sur le modèle de
`conscience.scoring.ScoringTuning` : la résolution en configuration se fait au
bord, chez l'appelant, sans quoi les tests mesureraient la base de la machine
qui les exécute au lieu de la calibration déclarée.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from old.backend.emotion.pad import EMOTION_ANCHORS, Vec3
from old.backend.emotion.types import Emotion
from old.backend.utils import phrasing
from old.backend.utils.degradation import degradations
from old.backend.utils.phrasing import Palier, Phrase, ReglagePhrasing, TirageAmorti

# ─────────────────────────────────────────────────────────────────────
# Réglages
# ─────────────────────────────────────────────────────────────────────

#: Sous cette durée de silence, l'inactivité ne se raconte pas : elle est le
#: régime normal d'une conversation. Même valeur que
#: ``ScoringTuning.idle_gate_minutes`` — le facteur qui *décide* et la phrase
#: qui le *dit* doivent s'ouvrir au même moment, faute de quoi le prompt
#: annonce un silence que le score n'a pas compté, ou l'inverse.
INACTIVITE_GATE_MINUTES = 10.0

#: Débordement d'humeur — même barre que ``ScoringTuning.mood_gate`` (0,6 :
#: l'intensité comparée est l'écart au repos, nul au repos).
HUMEUR_GATE = 0.6

#: Pression de rumination — même barre que ``ScoringTuning.rumination_gate``.
RUMINATION_GATE = 0.2

#: Tension au-delà de laquelle une pulsion se *nomme*. Volontairement plus
#: haute que la zone morte du scoring (0.02) : le score additionne les quatre
#: pulsions, la phrase en désigne **une**, et désigner celle qui est à 0.15 la
#: ferait passer pour un besoin.
PULSION_GATE = 0.6

#: Au-delà, l'envie ne se dit plus de la même façon. C'est une étiquette de
#: situation et non un adverbe : « ça te démange » et « il te trotte une petite
#: envie » ne sont pas une même phrase graduée, ce sont deux phrases.
PULSION_FORTE = 0.85

#: Au-delà de cette valence absolue, une émotion a un camp. En deçà, elle est
#: tiède : `confused` (−0.2) et `thinking` (+0.1) se rejouent de la même façon,
#: et les ranger sur le signe seul aurait donné à `confused` le registre de la
#: colère.
VALENCE_MARQUEE = 0.25

#: Au-delà de cet éveil, le rejeu est « vif » plutôt que « posé ».
EVEIL_MARQUE = 0.55

#: Au-delà de cette dominance, elle a *poussé* — c'est ce qui distingue la gêne
#: (« j'y suis allée fort ») de l'inquiétude (« ça m'a secouée »).
DOMINANCE_MARQUEE = 0.35


@dataclass(frozen=True)
class VecuTuning:
    """Les seuils du vécu, nommés, avec les constantes du module pour défauts.

    Même contrat que ``conscience.scoring.ScoringTuning`` : le module reste
    pur, et un ``VecuTuning()`` sans argument reproduit la calibration
    déclarée. La résolution en configuration, si elle vient, se fait chez
    l'appelant — ici elle transformerait chaque cycle de conscience en lecture
    de base, et rendrait les tests dépendants du ``data/vtuber.db`` local.

    ``paliers_intensite`` **pointe** l'échelle partagée au lieu d'en déclarer
    une seconde : deux barèmes d'adverbes pour un moteur, c'est deux façons de
    dire « vraiment » qui divergent au premier ajustement.
    """

    inactivite_gate_minutes: float = INACTIVITE_GATE_MINUTES
    humeur_gate: float = HUMEUR_GATE
    rumination_gate: float = RUMINATION_GATE
    pulsion_gate: float = PULSION_GATE
    pulsion_forte: float = PULSION_FORTE
    valence_marquee: float = VALENCE_MARQUEE
    eveil_marque: float = EVEIL_MARQUE
    dominance_marquee: float = DOMINANCE_MARQUEE
    paliers_intensite: tuple[Palier, ...] = phrasing.PALIERS_INTENSITE


DEFAUT_TUNING = VecuTuning()


# ─────────────────────────────────────────────────────────────────────
# Les motifs
# ─────────────────────────────────────────────────────────────────────

class Motif(str, Enum):
    """Pourquoi elle prend la parole d'elle-même.

    Sept motifs là où le prompt en connaissait quatre : l'inactivité, la pensée
    qui insiste et la pulsion saillante poussaient déjà le score sans qu'une
    seule phrase ne les nomme, si bien que le modèle recevait « parle » sans
    savoir de quoi.
    """

    MATIN = "matin"
    SOIR = "soir"
    NUIT = "nuit"
    HUMEUR = "humeur"
    INACTIVITE = "inactivite"
    RUMINATION = "rumination"
    PULSION = "pulsion"


#: Ordre de lecture, du dehors vers le dedans : la situation (l'heure, le
#: silence), puis l'état (humeur, pulsion), puis la pensée. Ce n'est pas un
#: ordre de priorité — tout est dit — mais l'ordre dans lequel quelqu'un
#: raconte : on situe avant de confier.
_ORDRE: tuple[Motif, ...] = (
    Motif.MATIN,
    Motif.SOIR,
    Motif.NUIT,
    Motif.INACTIVITE,
    Motif.HUMEUR,
    Motif.PULSION,
    Motif.RUMINATION,
)


@dataclass(frozen=True)
class Declencheur:
    """Un motif, ce qui le gradue, et ce qui le nomme.

    À ne pas confondre avec ``utils.phrasing.Declencheur``, qui est l'objet de
    *rendu* (une clé, un vivier, un poids) ; celui-ci est le fait constaté par
    la conscience, et ``composer_declencheurs`` traduit l'un en l'autre.

    ``detail`` est le texte qui entre dans la phrase : une durée en mots, un
    libellé d'émotion, un résumé de rumination, une envie à l'infinitif. Il est
    fourni par l'appelant parce que lui seul dispose de la langue de l'objet —
    un libellé d'émotion en français vit dans la couche de rendu, et l'importer
    ici ferait remonter l'interface dans le moteur.
    """

    motif: Motif
    intensite: float = 0.0
    detail: str = ""


# ─────────────────────────────────────────────────────────────────────
# Les viviers
# ─────────────────────────────────────────────────────────────────────
#
# Trois règles d'écriture, chacune réparant un défaut précis :
#
# 1. **Des propositions**, sans majuscule ni point final : `phrasing.assembler`
#    les coud avec des liants tirés et pose la ponctuation. Une phrase déjà
#    ponctuée produirait « ... 42 minutes., et tu te sens ... ».
# 2. **Rien d'impératif.** Les anciennes disaient « Dis bonjour naturellement »,
#    « Mentionne l'heure tardive » : le modèle exécutait la consigne au lieu de
#    parler, ce qui est le défaut B3 (il *raconte* l'action au lieu de la
#    faire). On décrit une situation ; la formulation reste ouverte.
# 3. **Les trous portent des noms distincts par motif** (`{duree}`, `{humeur}`,
#    `{pensee}`, `{envie}`). C'est ce qui permet de formater **une fois** la
#    phrase composée entière, donc de laisser les `Phrase` immuables — et la
#    mémoire d'anti-répétition du tirage, qui les prend pour clés, garde son
#    sens d'un cycle à l'autre. Formater avant le tirage aurait donné une clé
#    différente à chaque minute de silence écoulée.
#
# Les étiquettes sont **dérivées** des trous (voir `_vivier`) : une phrase qui
# demande `{duree}` n'est éligible que si la situation contient « duree ».
# C'est ce qui remplace un filtrage à la main, et ce qui garantit qu'aucune
# phrase à trou ne part avec son trou vide — « Personne ne t'a parlé depuis . »
# est une phrase fausse, et le modèle la reprend telle quelle.

_TROUS = re.compile(r"\{(\w+)\}")


def _vivier(*variantes) -> tuple[Phrase, ...]:
    """Bâtir un vivier en déduisant les étiquettes des trous du texte.

    Une variante est ``(texte, poids)`` ou ``(texte, poids, étiquettes_en_plus)``.
    Écrire les étiquettes de trou à la main à côté du gabarit, ce serait deux
    déclarations pour un fait : ajouter `{duree}` à une variante sans penser à
    l'étiqueter l'aurait rendue éligible partout, trou vide compris.
    """
    out: list[Phrase] = []
    for variante in variantes:
        texte, poids = variante[0], variante[1]
        sup = variante[2] if len(variante) > 2 else ()
        etiquettes = frozenset(_TROUS.findall(texte)) | frozenset(sup)
        out.append(Phrase(texte, poids, etiquettes))
    return tuple(out)


VIVIERS: dict[Motif, tuple[Phrase, ...]] = {
    Motif.MATIN: _vivier(
        ("c'est le matin, la journée commence à peine", 1.0),
        ("le jour vient de se lever", 1.0),
        ("on est en tout début de journée", 0.9),
        ("c'est le premier moment de la journée où tu ouvres la bouche", 0.7),
    ),
    Motif.SOIR: _vivier(
        ("c'est la soirée, la journée retombe doucement", 1.0),
        ("la lumière a changé, on est passé en soirée", 0.9),
        ("c'est le soir, ce moment où on parle plus lentement", 1.0),
        ("la journée est derrière, il reste la soirée", 0.8),
    ),
    Motif.NUIT: _vivier(
        ("il est tard, vraiment tard", 1.0),
        ("c'est la nuit, et ça s'entend dans la façon dont on parle", 1.0),
        ("l'heure a filé sans prévenir, il fait nuit depuis un moment", 0.9),
        ("c'est l'heure où on dit des choses qu'on ne dirait pas à midi", 0.7),
    ),
    Motif.INACTIVITE: _vivier(
        ("personne ne t'a parlé depuis {duree}", 1.0),
        ("ça fait {duree} que c'est silencieux de ton côté", 1.0),
        ("ça fait {duree} sans un mot de personne", 0.9),
        ("le silence dure depuis {duree}", 0.9),
        ("tu es seule avec tes pensées depuis {duree}", 0.8),
    ),
    # `{humeur}` arrive sous forme d'**adjectif accordé au féminin** (« agacée »,
    # « pensive ») : c'est ce que la couche de rendu sait produire. Toutes les
    # variantes sont donc construites autour d'un attribut, jamais d'un nom —
    # « il y a du pensive en toi » était la tournure qu'un gabarit à substantif
    # produisait immanquablement.
    Motif.HUMEUR: _vivier(
        ("tu te sens {adv_humeur} {humeur} et tu ne l'as dit à personne", 1.0),
        ("tu es {adv_humeur} {humeur} et ça ne se voit nulle part", 0.9),
        ("ton humeur déborde un peu, tu es {humeur}, et ça ne redescend pas", 1.0),
        ("quelque chose te travaille, tu es {humeur}, et ce n'est pas encore sorti", 0.9),
        ("ça fait un moment que tu es {adv_humeur} {humeur}", 0.8),
    ),
    Motif.PULSION: _vivier(
        # Apposition et non « tu as envie de {envie} ». Le liant « de » exige
        # une élision devant voyelle — « tu as envie de apprendre » — que la
        # substitution de trous ne sait pas faire, et aucun gabarit à liant ne
        # peut servir les quatre pulsions sans que l'une d'elles sonne faux.
        # Les cinq variantes sont donc toutes des appositions : le détail est
        # pose à côté, jamais accroché par une préposition.
        ("tu as une envie, {envie}", 1.0),
        ("ça te démange, {envie}", 1.0, ("envie_forte",)),
        ("il y a une envie qui monte, {envie}, et elle ne redescend pas toute seule",
         0.9, ("envie_forte",)),
        ("il te trotte une petite envie, {envie}", 0.9, ("!envie_forte",)),
        ("ce dont tu as le plus envie là maintenant, c'est {envie}", 0.9),
    ),
    Motif.RUMINATION: _vivier(
        ("une pensée te revient sans arrêt, {pensee}", 1.0),
        ("tu n'as pas lâché ça, {pensee}", 1.0),
        # Apposition, comme ses quatre sœurs. La forme « il y a {pensee} qui
        # t'occupe l'esprit » encastrait le résumé comme un groupe nominal —
        # or un résumé de pensée est une phrase entière, écrite par le modèle :
        # « il y a Thomas n'a jamais répondu à ma question qui t'occupe
        # l'esprit ». Un vivier ne peut pas rattraper un gabarit qui se trompe
        # sur la nature de ce qu'il reçoit.
        ("ça t'occupe l'esprit {adv_pensee} depuis tout à l'heure, {pensee}", 0.9),
        ("il y a ce truc qui insiste dans ta tête, {pensee}", 0.9),
        ("ton esprit retourne à la même chose, {pensee}", 0.8),
    ),
}

#: Ce qu'une pulsion *veut*, dit à l'infinitif — quatre entrées, pas un gabarit
#: par émotion. Les clés sont les valeurs de ``drives.state.DriveKind`` ; le
#: module n'est pas importé, `drives` tirant l'ORM alors que cette couche doit
#: rester importable sans Django configuré.
#: Les quatre entrées sont de la MÊME nature grammaticale — des infinitives.
#: « que quelqu'un te réponde » était une subordonnée, et une subordonnée ne
#: s'appose pas comme une infinitive : « il te trotte une petite envie, que
#: quelqu'un te réponde » sonnait faux dans les cinq variantes, pas seulement
#: dans celle qui portait un liant. Un vivier ne peut pas rattraper une entrée
#: qui ne se construit pas comme ses sœurs.
DETAIL_PULSION: dict[str, str] = {
    "curiosity": "apprendre un truc que tu ne connais pas encore",
    "social": "avoir quelqu'un au bout du fil, juste pour le contact",
    "expression": "sortir ce que tu as en tête",
    "rest": "souffler un peu et ne rien produire",
}

#: Quel trou et quelle étiquette chaque motif apporte à la situation. Le trou
#: gradué (`adv_*`) n'existe que pour les motifs dont l'intensité se dit en
#: adverbe ; là où elle se dit en changeant de phrase (la pulsion), il n'y en a
#: pas — « tu as complètement envie de » n'est pas du français.
_CHAMP_DETAIL: dict[Motif, str] = {
    Motif.INACTIVITE: "duree",
    Motif.HUMEUR: "humeur",
    Motif.PULSION: "envie",
    Motif.RUMINATION: "pensee",
}
_CHAMP_ADVERBE: dict[Motif, str] = {
    Motif.HUMEUR: "adv_humeur",
    Motif.RUMINATION: "adv_pensee",
}


# ─────────────────────────────────────────────────────────────────────
# Mise en mots
# ─────────────────────────────────────────────────────────────────────

def duree_en_mots(secondes: float) -> str:
    """Une durée telle qu'on la dit, pas telle qu'on la mesure.

    Le prompt disait ``f"depuis {int(idle/60)} minutes"``, et après une nuit il
    annonçait « depuis 512 minutes » — ce qu'aucun humain ne dit ni ne se
    représente.
    """
    minutes = int(max(0.0, secondes) // 60)
    if minutes < 1:
        return "moins d'une minute"
    if minutes < 60:
        return f"{minutes} minute" + ("s" if minutes > 1 else "")
    heures, reste = divmod(minutes, 60)
    if heures < 24:
        if reste == 0:
            return f"{heures} heure" + ("s" if heures > 1 else "")
        return f"{heures} h {reste:02d}"
    jours = heures // 24
    return f"{jours} jour" + ("s" if jours > 1 else "")


def composer_declencheurs(
    declencheurs: Iterable[Declencheur],
    *,
    tuning: VecuTuning | None = None,
    graine: int | None = None,
    tirage: TirageAmorti | None = None,
    reglage: ReglagePhrasing | None = None,
) -> str:
    """Dire **tous** les déclencheurs actifs, dans un ordre lisible.

    C'est la réparation du `elif`. Trois propriétés, par ordre d'importance :

    1. **Aucun motif n'est perdu.** `phrasing.composer` coupe volontairement à
       ``max_declencheurs`` — au-delà de trois, une énumération cesse d'être
       une phrase — donc on ne lui donne pas tout d'un coup : on **pagine**.
       Cinq motifs actifs donnent deux phrases, pas trois motifs jetés. La
       coupe reste une règle de *phrase*, jamais une perte d'information.
    2. **L'ordre est celui du récit** (`_ORDRE`), pas celui de la structure de
       données : situer, puis confier. Il est transmis par le poids, que
       `phrasing.composer` utilise pour trier — le rang narratif est donc la
       seule chose qui ordonne, et l'intensité n'y touche pas (elle module ce
       qui est *dit*, pas l'ordre dans lequel on le dit).
    3. **Rien ne lève.** Boucle de fond non supervisée : une mise en forme
       ratée coûte un bloc de prompt, jamais le cycle de conscience.

    ``graine`` rend la composition reproductible pour les tests ; sans elle, le
    tirage partagé du process évite la répétition d'un cycle à l'autre.
    """
    t = tuning or DEFAUT_TUNING
    r = reglage or phrasing.REGLAGE_PAR_DEFAUT
    tir = tirage or (TirageAmorti(graine=graine) if graine is not None else None)

    try:
        rang = {motif: i for i, motif in enumerate(_ORDRE)}
        # Dédoublonnage sur le motif : deux ruminations actives ne donnent pas
        # deux phrases « une pensée te revient » collées l'une à l'autre.
        vus: set = set()
        retenus: list[Declencheur] = []
        for d in declencheurs:
            if d is None or d.motif in vus:
                continue
            vus.add(d.motif)
            retenus.append(d)
        retenus.sort(key=lambda d: rang.get(d.motif, len(rang)))

        champs: dict[str, str] = {}
        situation: set[str] = set()
        a_dire: list[phrasing.Declencheur] = []
        for d in retenus:
            # Le trou est *levé* plutôt que testé, parce que le registre de
            # dégradations n'accepte que ce qui sort d'un `except` (une garde
            # AST du dépôt l'exige, et elle a raison : un `record` posé sur une
            # condition finit par servir de journal de progression, et le
            # compteur cesse de vouloir dire « quelque chose a cassé »). Un
            # motif sans vivier EST une panne — un `Motif` déclaré que personne
            # n'a écrit — pas une branche normale.
            try:
                vivier = VIVIERS[d.motif]
                if not vivier:
                    raise KeyError(str(d.motif))
            except KeyError as exc:
                degradations.record("vecu: motif sans vivier", exc)
                continue
            nom_detail = _CHAMP_DETAIL.get(d.motif)
            if nom_detail:
                detail = (d.detail or "").strip()
                if not detail:
                    # Sans détail, toutes les variantes du motif exigent une
                    # étiquette absente : `eligibles` les écarterait une à une.
                    # On saute directement — un déclencheur dont le vivier est
                    # vide consommerait quand même une place dans la pagination.
                    continue
                champs[nom_detail] = detail
                situation.add(nom_detail)
            nom_adverbe = _CHAMP_ADVERBE.get(d.motif)
            if nom_adverbe:
                champs[nom_adverbe] = phrasing.adverbe(
                    d.intensite, t.paliers_intensite, tirage=tir,
                )
                situation.add(nom_adverbe)
            if d.motif is Motif.PULSION and d.intensite >= t.pulsion_forte:
                situation.add("envie_forte")
            # Le poids porte le rang narratif : `composer` trie par poids
            # décroissant, donc le premier de `_ORDRE` doit avoir le plus fort.
            a_dire.append(phrasing.Declencheur(
                cle=str(d.motif),
                vivier=vivier,
                poids=float(len(rang) - rang.get(d.motif, len(rang))),
            ))

        if not a_dire:
            return ""

        taille = max(1, int(r.max_declencheurs))
        phrases = []
        for depart in range(0, len(a_dire), taille):
            rendu = phrasing.composer(
                a_dire[depart:depart + taille],
                situation=situation, tirage=tir, reglage=r,
            )
            if rendu:
                phrases.append(rendu)
        assemble = " ".join(phrases)
        # Un seul `format`, sur la phrase déjà cousue : les valeurs injectées
        # ne sont jamais relues, donc une accolade dans un résumé de rumination
        # (texte écrit par le modèle) ne peut pas devenir un gabarit.
        return assemble.format(**champs)
    except Exception as exc:
        degradations.record("vecu: composition des déclencheurs", exc)
        return ""


def declencheurs_actifs(
    *,
    salutation: str | None = None,
    idle_seconds: float = 0.0,
    humeur: str = "",
    humeur_intensite: float = 0.0,
    rumination_pression: float = 0.0,
    rumination_resume: str = "",
    pulsion: str = "",
    pulsion_tension: float = 0.0,
    tuning: VecuTuning | None = None,
) -> list[Declencheur]:
    """Traduire l'état d'un cycle en liste de motifs, en appliquant les portes.

    Volontairement en scalaires nus plutôt qu'en `DecisionContext` : ce module
    ne doit rien importer qui tire l'ORM, et l'intégrateur sait mieux que lui
    d'où viennent ses valeurs — le libellé d'humeur, notamment, vit dans la
    couche de rendu.

    Les portes reprennent celles du scoring : un motif qui n'a pas contribué au
    score n'a pas à figurer dans le prompt comme s'il l'avait fait.
    """
    t = tuning or DEFAUT_TUNING
    out: list[Declencheur] = []

    if salutation == "morning":
        out.append(Declencheur(Motif.MATIN))
    elif salutation == "evening":
        out.append(Declencheur(Motif.SOIR))
    elif salutation == "night":
        out.append(Declencheur(Motif.NUIT))

    minutes = max(0.0, idle_seconds) / 60.0
    if minutes > t.inactivite_gate_minutes:
        out.append(Declencheur(Motif.INACTIVITE, min(1.0, minutes / 120.0),
                               duree_en_mots(idle_seconds)))

    if humeur and humeur_intensite > t.humeur_gate:
        out.append(Declencheur(Motif.HUMEUR, humeur_intensite, humeur))

    if pulsion and pulsion_tension >= t.pulsion_gate:
        out.append(Declencheur(Motif.PULSION, pulsion_tension,
                               DETAIL_PULSION.get(pulsion, "")))

    if rumination_resume and rumination_pression > t.rumination_gate:
        out.append(Declencheur(Motif.RUMINATION,
                               min(1.0, rumination_pression),
                               rumination_resume))

    return out


# ─────────────────────────────────────────────────────────────────────
# Le rejeu : ce qu'un tour marqué laisse derrière lui
# ─────────────────────────────────────────────────────────────────────

class SeauPad(str, Enum):
    """Classe grossière d'un point PAD — six seaux, pas vingt-neuf gabarits.

    Le seau ne sert pas à nommer un sentiment (`pad_to_label` le fait déjà et
    le fait mieux) : il sert à choisir un **registre de langue**. Deux axes
    suffisent pour ça — dans quel camp on est, et à quelle vitesse ça bat. La
    dominance en est volontairement absente : elle change *ce qu'on se
    reproche*, pas *la façon dont on parle*, et `cible_de_derive` la lit à
    part.
    """

    POSITIF_VIF = "positif_vif"
    POSITIF_CALME = "positif_calme"
    TIEDE_VIF = "tiede_vif"
    TIEDE_CALME = "tiede_calme"
    NEGATIF_VIF = "negatif_vif"
    NEGATIF_CALME = "negatif_calme"


def seau_pad(pad: Vec3, tuning: VecuTuning | None = None) -> SeauPad:
    """Ranger un point PAD dans une classe grossière.

    Six classes plutôt qu'un seuil sur la seule valence : `confused` (−0.2) et
    `thinking` (+0.1) sont tous deux tièdes, et les ranger sur le signe seul
    aurait donné à `confused` le registre de la colère.
    """
    t = tuning or DEFAUT_TUNING
    p, a, _d = pad
    vif = a >= t.eveil_marque
    if p >= t.valence_marquee:
        return SeauPad.POSITIF_VIF if vif else SeauPad.POSITIF_CALME
    if p <= -t.valence_marquee:
        return SeauPad.NEGATIF_VIF if vif else SeauPad.NEGATIF_CALME
    return SeauPad.TIEDE_VIF if vif else SeauPad.TIEDE_CALME


def cible_de_derive(emotion: Emotion,
                    tuning: VecuTuning | None = None) -> Emotion:
    """Vers quoi dérive le souvenir d'un tour marqué par ``emotion``.

    Remplace les neuf lignes de ``_AUDIT_EMOTIONS``. Les vingt émotions
    absentes de cette table ne produisaient **aucune** micro-rumination : un
    tour `melancholic` à 0.9 ne se rejouait jamais, alors qu'un tour `proud` à
    0.56 se rejouait toujours avec la même phrase. Ici la cible se **dérive**
    de l'ancre PAD que `emotion/pad.py` déclare déjà.

    La règle, et son asymétrie assumée :

    - **Camp positif** : ce qui reste, c'est l'élan. On regarde donc l'éveil
      d'abord (ça continue de porter → `hopeful`), la dominance ensuite (elle a
      tenu quelque chose → `proud`), et à défaut la chaleur (`grateful`).
    - **Camp négatif** : ce qui reste, c'est de savoir si elle a *poussé*. On
      regarde donc la dominance d'abord (elle y est allée fort → `embarrassed`),
      l'éveil ensuite (ça la tend encore → `anxious`), et à défaut ce qui
      s'installe et pèse (`melancholic`).
    - **Camp tiède** : rien à se reprocher ni à savourer. Ça a remué (`curious`)
      ou ça repasse simplement (`thinking`).

    ``NEUTRAL`` est le seul cas particulier, et il l'est par géométrie : son
    ancre est l'origine, elle n'a ni camp ni éveil. Un tour neutre ne se rejoue
    pas — il dérive vers lui-même.
    """
    t = tuning or DEFAUT_TUNING
    if emotion is Emotion.NEUTRAL:
        return Emotion.NEUTRAL
    try:
        p, a, d = EMOTION_ANCHORS[emotion]
    except (KeyError, TypeError) as exc:
        # Une émotion déclarée sans ancre est une incohérence de `emotion/`,
        # pas une raison de faire tomber un cycle de conscience.
        degradations.record("vecu: émotion sans ancre PAD", exc)
        return Emotion.THINKING

    if p >= t.valence_marquee:
        if a >= t.eveil_marque:
            return Emotion.HOPEFUL
        if d >= t.dominance_marquee:
            return Emotion.PROUD
        return Emotion.GRATEFUL

    if p <= -t.valence_marquee:
        if d >= t.dominance_marquee:
            return Emotion.EMBARRASSED
        if a >= t.eveil_marque:
            return Emotion.ANXIOUS
        return Emotion.MELANCHOLIC

    return Emotion.CURIOUS if a >= t.eveil_marque else Emotion.THINKING


#: Un vivier de rejeu par seau — six pools au lieu de vingt-neuf gabarits, et
#: plusieurs formulations chacun là où la table n'en offrait qu'une, recopiée à
#: l'identique dans chaque `Rumination`. Ici les entrées sont **des phrases
#: entières** (majuscule et point compris) et non des propositions : elles ne
#: sont jamais cousues à d'autres, elles deviennent le `summary` d'une
#: rumination.
VIVIERS_REJEU: dict[SeauPad, tuple[Phrase, ...]] = {
    SeauPad.NEGATIF_VIF: (
        Phrase("Tu repenses à ta réponse, un peu vive : « {extrait} »."),
        Phrase("« {extrait} » — tu te demandes si tu n'y es pas allée fort."),
        Phrase("Ça te reste en travers, ce que tu as dit : « {extrait} »."),
    ),
    SeauPad.NEGATIF_CALME: (
        Phrase("« {extrait} » — ça te laisse un goût un peu triste."),
        Phrase("Tu reviens sur ce que tu as dit, sans énergie : « {extrait} »."),
        Phrase("Cette phrase traîne encore derrière toi : « {extrait} »."),
    ),
    SeauPad.TIEDE_VIF: (
        Phrase("Tu rejoues ce moment sans savoir quoi en penser : « {extrait} »."),
        Phrase("« {extrait} » — tu tournes autour, ça t'intrigue."),
    ),
    SeauPad.TIEDE_CALME: (
        Phrase("Tu y repenses, calmement : « {extrait} »."),
        Phrase("« {extrait} » — rien de grave, mais c'est resté posé quelque part."),
    ),
    SeauPad.POSITIF_VIF: (
        Phrase("Tu es restée sur ton élan après avoir dit : « {extrait} »."),
        Phrase("« {extrait} » — ça t'a fait du bien de le sortir."),
    ),
    SeauPad.POSITIF_CALME: (
        Phrase("Tu gardes la chaleur de ce moment : « {extrait} »."),
        Phrase("« {extrait} » — tu y repenses avec le sourire."),
    ),
}


def phrase_de_rejeu(emotion: Emotion, extrait: str, *,
                    tuning: VecuTuning | None = None,
                    graine: int | None = None,
                    tirage: TirageAmorti | None = None) -> str:
    """Ce qu'elle se dit en se rejouant un tour marqué par ``emotion``.

    L'autre moitié du remplacement de ``_AUDIT_EMOTIONS`` : le registre vient
    du seau PAD, donc six viviers couvrent les vingt-neuf émotions.
    """
    t = tuning or DEFAUT_TUNING
    extrait = (extrait or "").strip()
    if not extrait:
        return ""
    try:
        ancre = EMOTION_ANCHORS.get(emotion, (0.0, 0.0, 0.0))
        options = VIVIERS_REJEU.get(seau_pad(ancre, t), ())
        tir = tirage or (TirageAmorti(graine=graine) if graine is not None else None)
        modele = phrasing.formuler(options, tirage=tir)
        return modele.format(extrait=extrait) if modele else ""
    except Exception as exc:
        degradations.record("vecu: phrase de rejeu", exc)
        return ""
