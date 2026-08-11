"""Choisir une CONDUITE, et pas seulement « parler ou non ».

La boucle de décision sait, depuis toujours, répondre à une question binaire :
le score passe-t-il 0.5 ? Si oui elle « agit », et agir veut dire exactement
une chose — deux appels LLM puis un marquage. Elle ne choisit jamais *quoi*
faire (seulement à qui parler), ne va au bout de rien (aucun modèle ne porte un
travail entamé), et n'a donc qu'une seule manière d'exister : émettre une
phrase. Tout ce qui n'est pas une phrase est du silence indifférencié.

Ce module ouvre l'éventail. Il reçoit un état **déjà rassemblé** et rend une
décision : parler, poursuivre un travail commencé, en ouvrir un nouveau, ou se
taire. Il est **pur** — aucune base, aucun registre, aucun appel LLM, aucune
horloge cachée (``maintenant`` se passe). C'est ce qui lui permet de tourner
2 880 fois par jour sans rien coûter, et c'est ce qui permet aux tests de
mesurer la calibration *déclarée* plutôt que la base de la machine qui les
exécute.

**Où ça s'insère.** ``ConscienceEngine._decide_inner`` calcule un score puis en
tire « act / wait / skip ». Les deux conduites nouvelles vivent strictement
dans l'espace que ce triptyque appelait « wait » ou « skip », c'est-à-dire dans
le silence : la calibration du scoring n'est pas touchée, et une intégration ne
peut donc pas rendre Mika plus bavarde. Un pas de travail est muet par défaut
(voir ``decider_diffusion``) : il ne consomme pas le frein quotidien des
initiatives, parce qu'il ne dérange personne.

**Réglages.** Comme ``conscience/scoring.py``, ce module ne lit aucune
configuration : il expose une dataclasse gelée dont les défauts *sont* les
constantes de module. La résolution depuis le registre se fera au bord, chez
l'appelant, quand les clés seront déclarées. Un ``ConduiteTuning()`` sans
argument reproduit la calibration documentée ici.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from utils.degradation import degradations

# ---------------------------------------------------------------------------
# Constantes de repli — au NIVEAU MODULE, jamais en attribut de classe.
# La garde AST de tests/test_config_rapatriement.py résout un repli `ast.Name`
# en attribut du module et ignorerait silencieusement un `self._X`.
# ---------------------------------------------------------------------------

#: Pertinence minimale d'une observation pour qu'elle puisse **ouvrir un
#: travail**. Volontairement 0.45 et surtout pas 0.35.
#:
#: `interpreter.py` fixe le chemin heuristique : chat 0.30, telegram 0.40, RSS
#: apparié 0.55, RSS non apparié 0.20, forge 0.20. À 0.35, chaque message
#: Telegram — c'est-à-dire chaque phrase qu'on lui adresse — ouvrirait un
#: travail : elle se mettrait à « travailler » sur une conversation en cours au
#: lieu d'y répondre. La porte est calée *au-dessus* du trafic conversationnel
#: et *en dessous* du plafond du chemin heuristique (0.55), pour qu'un signal
#: extérieur réellement apparié à ses thèmes reste une amorce légitime.
GRAINE_OBS_PERTINENCE = 0.45

#: Intensité minimale d'une pensée active (Rumination) pour qu'elle amorce un
#: travail. Une rumination naît au-dessus de 0.5 et décroît en demi-vie de 6 h :
#: à 0.40 on attrape ce qui la préoccupe encore, pas ce qui s'éteint.
GRAINE_PENSEE_INTENSITE = 0.40

#: Tension minimale d'une pulsion pour qu'elle amorce un travail. Alignée sur
#: `drives/engine.py::_OBSERVATION_CURIOSITY_GATE` (0.50) : une pulsion qui
#: n'atteint pas ce niveau ne colore même pas la lecture d'une observation,
#: elle n'a certainement pas de quoi ouvrir un chantier.
GRAINE_PULSION_TENSION = 0.50

#: Les seules pulsions qui *fécondent* un travail.
#:
#: CURIOSITY veut apprendre, EXPRESSION veut formuler : les deux se soulagent
#: en produisant quelque chose. SOCIAL veut de la présence — son soulagement
#: est de parler à quelqu'un, pas d'ouvrir un dossier — et REST veut du
#: silence : en faire une amorce reviendrait à ouvrir un travail *parce
#: qu'elle est fatiguée*. C'est le défaut H1 de l'audit pris par le bon bout :
#: on donne un sujet à la curiosité, on ne transforme pas toute tension en
#: chantier.
PULSIONS_FECONDES = ("curiosity", "expression")

#: Nombre maximal d'amorces rendues par récolte. Au-delà, la liste n'est plus
#: un choix mais un inventaire, et le bord la re-trierait de toute façon.
GRAINES_MAX = 5

#: Demi-vie de l'envie portée par un travail, en secondes (6 h — la même que
#: celle d'une rumination : ce sont deux formes de la même chose, une chose
#: qui compte encore ou plus).
ENVIE_DEMI_VIE_S = 6 * 3600.0

#: En dessous, un travail est essoufflé : plus personne ne veut le faire
#: avancer et le garder « en cours » ne produit que des zombies.
ENVIE_PLANCHER_ABANDON = 0.10

#: Envie minimale pour dépenser un pas sur un travail. Au-dessus du plancher
#: d'abandon : il existe une bande où un travail vit encore sans qu'on y
#: touche, et c'est elle qui laisse une place aux travaux plus vifs.
ENVIE_POURSUITE_MIN = 0.25

#: Poids minimal d'une amorce pour qu'elle vaille l'ouverture d'un travail.
#:
#: Strictement **au-dessus** de la porte de récolte (0.45) : récolter est bon
#: marché, ouvrir engage un chantier qui occupera une des trois places pendant
#: des heures. Égaliser les deux rendrait l'une des deux portes décorative —
#: toute amorce récoltée ouvrirait, et « récolter » ne voudrait plus rien dire.
#: Calée à 0.50 pour qu'un RSS apparié (0.55) reste ouvrant : une porte que le
#: plafond du chemin heuristique ne franchit pas ne laisserait jamais le dehors
#: amorcer quoi que ce soit.
OUVERTURE_ENVIE_MIN = 0.50

#: Nombre de travaux ouverts simultanément. Trois, parce qu'un quatrième ne
#: serait plus jamais visité : à un pas par 15 min et un frein de diffusion,
#: la file se viderait plus lentement qu'elle ne se remplit.
TRAVAUX_ACTIFS_MAX = 3

#: Espacement minimal entre deux pas du **même** travail (15 min). La boucle
#: tourne toutes les 30 s : sans cet espacement, un travail consommerait tous
#: ses pas en une poignée de minutes, ce qui est l'inverse exact de « aller au
#: bout de quelque chose ».
PAS_INTERVALLE_MIN_S = 900.0

#: Au-dessus, le résultat d'un pas est jugé assez notable pour être dit à voix
#: haute sans qu'on le lui ait demandé. Volontairement très haut : le défaut
#: est le silence.
DIFFUSION_NOTABLE_MIN = 0.80

#: Espacement minimal entre deux diffusions spontanées de travail (4 h). Sans
#: lui, 4 travaux × 5 pas = 20 monologues par jour, et ces vingt-là passent
#: *hors* du frein quotidien des initiatives, qui ne compte que les actes.
DIFFUSION_INTERVALLE_MIN_S = 4 * 3600.0


# ---------------------------------------------------------------------------
# Les conduites
# ---------------------------------------------------------------------------

class Conduite(str, Enum):
    """Ce que la conscience peut décider de faire d'un tour de boucle.

    Nommées en français parce qu'elles sont lues dans le motif d'un
    ``ConscienceLog`` et sur les écrans de gestion, à côté de « act » / « wait »
    / « skip » qu'elles raffinent.
    """

    #: S'adresser à quelqu'un. C'est l'unique conduite d'avant.
    PARLER = "parler"
    #: Faire avancer d'un pas un travail déjà commencé. Muet par défaut.
    POURSUIVRE = "poursuivre"
    #: Ouvrir un nouveau travail à partir d'une amorce récoltée.
    OUVRIR = "ouvrir"
    #: Ne rien faire de ce tour. Issue valide, et de loin la plus fréquente.
    SE_TAIRE = "se_taire"


@dataclass(frozen=True)
class ConduiteTuning:
    """Les seuils, avec les constantes ci-dessus pour défauts.

    Même motif que ``ScoringTuning`` : le module reste pur, les valeurs
    rapatriées un jour dans la configuration seront résolues **par
    l'appelant** et passées ici.
    """

    graine_obs_pertinence: float = GRAINE_OBS_PERTINENCE
    graine_pensee_intensite: float = GRAINE_PENSEE_INTENSITE
    graine_pulsion_tension: float = GRAINE_PULSION_TENSION
    graines_max: int = GRAINES_MAX
    envie_demi_vie_s: float = ENVIE_DEMI_VIE_S
    envie_plancher_abandon: float = ENVIE_PLANCHER_ABANDON
    envie_poursuite_min: float = ENVIE_POURSUITE_MIN
    ouverture_envie_min: float = OUVERTURE_ENVIE_MIN
    travaux_actifs_max: int = TRAVAUX_ACTIFS_MAX
    pas_intervalle_min_s: float = PAS_INTERVALLE_MIN_S
    diffusion_notable_min: float = DIFFUSION_NOTABLE_MIN
    diffusion_intervalle_min_s: float = DIFFUSION_INTERVALLE_MIN_S


#: Réglage par défaut, partagé : le construire une fois évite de rebâtir la
#: dataclasse à chaque tour de boucle et à chaque test.
DEFAULT_TUNING = ConduiteTuning()


# ---------------------------------------------------------------------------
# Les objets d'état — décrits ici pour que ce module n'ait rien à savoir de l'ORM
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Graine:
    """Une amorce de travail : d'où elle vient, ce qu'elle vaut, ce qu'elle dit.

    ``reference`` est ce qui permettra au bord de retrouver la ligne d'origine
    (pk d'Observation, pk de Rumination, nom de pulsion). Ce module ne
    l'interprète jamais : il la transporte.
    """

    origine: str          # "observation" | "pensee" | "pulsion"
    reference: Any
    intitule: str
    poids: float          # 0..1 — pertinence, intensité ou tension selon l'origine
    themes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TravailEnCours:
    """Ce qu'il faut savoir d'un travail pour décider s'il mérite un pas.

    Volontairement sans FK, sans QuerySet, sans méthode : le bord construit ces
    objets depuis ce qu'il a stocké. Un module pur qui accepterait une instance
    ORM finirait par la relire, et ce serait la fin de la pureté.
    """

    identifiant: Any
    titre: str
    #: Envie **telle qu'écrite**, à facturer par ``envie_courante``.
    envie: float
    #: Date de la dernière écriture de l'envie. C'est l'ancre : elle n'avance
    #: qu'à l'écriture, jamais à la lecture.
    ancre_envie: datetime | None = None
    dernier_pas_le: datetime | None = None
    pas_effectues: int = 0
    #: 0 = pas de plafond.
    pas_max: int = 0
    #: Bloqué en attente de quelqu'un : un pas de plus ne ferait que
    #: reposer la même question.
    en_attente_de_reponse: bool = False
    themes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    """La conduite retenue, sa cible éventuelle, et un motif lisible.

    ``motif`` est destiné au champ ``reason`` d'un ``ConscienceLog`` : il dit
    *pourquoi*, en français, sans jamais citer de nombre destiné à être relu
    par une machine.
    """

    conduite: Conduite
    cible: Any = None
    motif: str = ""


@dataclass(frozen=True)
class Diffusion:
    """Faut-il dire à voix haute ce que ce pas a produit, et pourquoi."""

    diffuser: bool
    motif: str = ""


# ---------------------------------------------------------------------------
# L'envie — décroissance sur une ancre en temps réel
# ---------------------------------------------------------------------------

def _secondes_ecoulees(depuis: datetime | None, maintenant: datetime | None) -> float:
    """Secondes entre deux instants, jamais négatives, jamais levantes.

    Un retour d'horloge (NTP, changement d'heure, date en base plus récente que
    le présent) ne doit pas *augmenter* une envie : on facture zéro. Et un
    mélange naïf/aware lève un TypeError — sur le chemin chaud d'une boucle que
    personne ne supervise, ce serait la boucle qui meurt (C4).
    """
    if depuis is None or maintenant is None:
        return 0.0
    try:
        ecoule = (maintenant - depuis).total_seconds()
    except (TypeError, AttributeError, OverflowError) as exc:
        degradations.record("conduite: ancre d'envie illisible", exc)
        return 0.0
    return ecoule if ecoule > 0 else 0.0


def envie_courante(
    travail: TravailEnCours,
    maintenant: datetime | None = None,
    tuning: ConduiteTuning | None = None,
) -> float:
    """L'envie **à cet instant**, décroissance en demi-vie sur l'ancre.

    Même idiome que ``Rumination.decayed_at`` : l'ancre n'avance qu'à
    l'écriture. La décroissance est donc facturée sur le temps réellement
    écoulé, et non sur le nombre de tours de boucle passés — le défaut que
    cette forme répare précisément est celui qu'a connu la rumination, un
    ``*= 0.95`` par cycle qui liait la durée de vie d'une pensée à la cadence
    de la boucle : à 30 s le tour, elle s'éteignait en 22 minutes tandis que
    tous ses lecteurs raisonnaient en heures. Ici la conséquence serait
    identique et symétrique : une boucle ralentie ferait vivre les travaux
    éternellement, une boucle accélérée les tuerait en une heure.

    Lire ne facture rien : cette fonction ne touche pas ``travail``, qui est
    gelé. Le bord écrit le couple rendu par ``facturer_envie``.
    """
    t = tuning or DEFAULT_TUNING
    envie = _flottant(travail.envie, 0.0)
    if envie <= 0.0:
        return 0.0
    demi_vie = t.envie_demi_vie_s
    if demi_vie <= 0:
        return envie
    ecoule = _secondes_ecoulees(travail.ancre_envie, maintenant)
    if ecoule <= 0.0:
        return envie
    return envie * (0.5 ** (ecoule / demi_vie))


def facturer_envie(
    travail: TravailEnCours,
    maintenant: datetime,
    tuning: ConduiteTuning | None = None,
) -> tuple[float, datetime]:
    """``(envie décrue, nouvelle ancre)`` — ce que le bord doit écrire.

    Rendu comme un couple pour que l'écriture soit *atomique du point de vue de
    l'appelant* : écrire la valeur sans avancer l'ancre re-facturerait le même
    temps au tour suivant, écrire l'ancre sans la valeur effacerait la
    décroissance. Les deux moitiés du même geste ne doivent pas pouvoir se
    séparer — c'est exactement ce qui est arrivé à ``Connaissance``, ancrée sur
    un ``auto_now`` que Django ne rafraîchissait pas sous ``update_fields``.
    """
    return envie_courante(travail, maintenant, tuning), maintenant


def est_essouffle(
    travail: TravailEnCours,
    maintenant: datetime | None = None,
    tuning: ConduiteTuning | None = None,
) -> bool:
    """Le travail est-il tombé sous le plancher d'abandon ?

    Prédicat séparé parce que la décision d'abandonner n'appartient pas à ce
    tour de boucle : le bord peut vouloir marquer la ligne « abandonnée » sans
    que ce soit la conduite du cycle. Un travail essoufflé n'est pas supprimé,
    il cesse d'être candidat.
    """
    t = tuning or DEFAULT_TUNING
    return envie_courante(travail, maintenant, t) < t.envie_plancher_abandon


# ---------------------------------------------------------------------------
# La récolte d'amorces
# ---------------------------------------------------------------------------

def _flottant(valeur: Any, defaut: float = 0.0) -> float:
    """Conversion tolérante — un champ JSON mal formé ne tue pas le cycle."""
    try:
        return float(valeur)
    except (TypeError, ValueError) as exc:
        degradations.record("conduite: valeur numerique illisible", exc)
        return defaut


def _themes(valeur: Any) -> tuple[str, ...]:
    """Les thèmes d'une ligne, quels qu'ils soient dans la base.

    ``Observation.themes`` n'existe pas, ``Rumination.themes`` est un JSONField
    qu'un modèle local a déjà rempli avec autre chose qu'une liste de chaînes
    (le consolidateur a connu exactement ce cas). On normalise plutôt que de
    faire confiance.
    """
    if isinstance(valeur, str):
        return (valeur,) if valeur else ()
    # Un `dict` est itérable et rendrait ses **clés** : un JSONField contenant
    # `{"theme": "vrm"}` aurait produit le thème « theme ». Seules les
    # séquences comptent, et on ne devine rien du reste.
    if isinstance(valeur, Mapping) or not isinstance(valeur, Iterable):
        return ()
    sortie = []
    for item in valeur:
        if isinstance(item, str) and item:
            sortie.append(item)
    return tuple(sortie)


def _intitule(texte: Any, defaut: str) -> str:
    if isinstance(texte, str) and texte.strip():
        return texte.strip()
    return defaut


def recolter_graines(
    observations: Sequence[Any] = (),
    pensees: Sequence[dict] = (),
    pulsions: Sequence[tuple[str, float]] = (),
    tuning: ConduiteTuning | None = None,
) -> list[Graine]:
    """Les amorces de travail que l'état courant contient.

    Trois sources, trois natures :

    * les **observations en attente** — ce que le dehors a produit. Porte à
      ``graine_obs_pertinence`` (0.45), qui est la raison d'être de ce module :
      elle laisse passer un RSS apparié (0.55) et refuse un message Telegram
      (0.40), sans quoi chaque phrase qu'on lui adresse ouvrirait un chantier.
    * les **pensées actives** — les lignes rendues par
      ``ConscienceEngine._rumination_snapshot`` : des dicts
      ``{id, summary, themes, intensity, emotion}``. Une pensée qui persiste
      est déjà, littéralement, un travail qu'elle n'a pas fait.
    * les **pulsions saillantes** — ``(nom, tension)``. Seules CURIOSITY et
      EXPRESSION fécondent (voir ``PULSIONS_FECONDES``) : c'est le défaut H1,
      « la curiosité monte, pousse le score, produit une phrase, et rien ne
      choisit un sujet ».

    Ne lève jamais : une ligne illisible est comptée et sautée. La liste rendue
    est triée par poids décroissant et plafonnée à ``graines_max``.
    """
    t = tuning or DEFAULT_TUNING
    graines: list[Graine] = []

    for obs in observations or ():
        try:
            pertinence = _flottant(getattr(obs, "pertinence", 0.0))
            if pertinence < t.graine_obs_pertinence:
                continue
            graines.append(Graine(
                origine="observation",
                reference=getattr(obs, "pk", None) or getattr(obs, "id", None),
                intitule=_intitule(
                    getattr(obs, "summary", ""),
                    _intitule(getattr(obs, "event_type", ""), "signal sans résumé"),
                ),
                poids=min(1.0, max(0.0, pertinence)),
                themes=_themes(getattr(obs, "themes", ())),
            ))
        except Exception as exc:
            # Une observation malformée ne doit pas emporter la récolte
            # entière : les deux autres sources, elles, sont peut-être saines.
            degradations.record("conduite: observation illisible en graine", exc)

    for pensee in pensees or ():
        try:
            intensite = _flottant(pensee.get("intensity", 0.0))
            if intensite < t.graine_pensee_intensite:
                continue
            graines.append(Graine(
                origine="pensee",
                reference=pensee.get("id"),
                intitule=_intitule(pensee.get("summary"), "pensée sans énoncé"),
                poids=min(1.0, max(0.0, intensite)),
                themes=_themes(pensee.get("themes")),
            ))
        except Exception as exc:
            degradations.record("conduite: pensee illisible en graine", exc)

    for pulsion in pulsions or ():
        try:
            nom, tension = pulsion
            nom = str(nom)
            if nom not in PULSIONS_FECONDES:
                continue
            tension = _flottant(tension)
            if tension < t.graine_pulsion_tension:
                continue
            graines.append(Graine(
                origine="pulsion",
                reference=nom,
                intitule=f"envie de {nom}",
                poids=min(1.0, max(0.0, tension)),
                themes=(),
            ))
        except Exception as exc:
            degradations.record("conduite: pulsion illisible en graine", exc)

    # Tri stable : à poids égal, l'ordre d'arrivée décide — observations, puis
    # pensées, puis pulsions. Le dehors passe avant le dedans, ce qui est la
    # hiérarchie que le scoring applique déjà (Facteur 1 avant Facteur 9).
    graines.sort(key=lambda g: g.poids, reverse=True)
    return graines[: max(0, t.graines_max)]


# ---------------------------------------------------------------------------
# Le choix
# ---------------------------------------------------------------------------

def travail_a_poursuivre(
    travaux: Sequence[TravailEnCours],
    maintenant: datetime | None = None,
    tuning: ConduiteTuning | None = None,
) -> TravailEnCours | None:
    """Le travail qui mérite un pas maintenant, ou ``None``.

    Quatre refus, chacun réparant une manière de ne jamais finir :

    * ``en_attente_de_reponse`` — un pas de plus reposerait la même question ;
    * ``pas_max`` atteint — un travail sans terme n'est pas un travail ;
    * envie sous ``envie_poursuite_min`` — plus personne n'en veut ;
    * dernier pas trop récent — la boucle tourne toutes les 30 s, sans
      espacement un travail brûlerait tous ses pas en quelques minutes.

    Départage : la plus forte envie courante ; à égalité, le pas le plus ancien
    (``None`` = jamais fait = le plus ancien), pour qu'un travail jamais visité
    ne soit pas indéfiniment doublé par un autre de même envie.
    """
    t = tuning or DEFAULT_TUNING
    candidats: list[tuple[float, float, TravailEnCours]] = []

    for travail in travaux or ():
        if travail.en_attente_de_reponse:
            continue
        if travail.pas_max and travail.pas_effectues >= travail.pas_max:
            continue
        envie = envie_courante(travail, maintenant, t)
        if envie < t.envie_poursuite_min:
            continue
        depuis_dernier_pas = (
            float("inf") if travail.dernier_pas_le is None
            else _secondes_ecoulees(travail.dernier_pas_le, maintenant)
        )
        if depuis_dernier_pas < t.pas_intervalle_min_s:
            continue
        candidats.append((envie, depuis_dernier_pas, travail))

    if not candidats:
        return None
    candidats.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return candidats[0][2]


def choisir_conduite(
    *,
    score: float,
    seuil: float,
    travaux: Sequence[TravailEnCours] = (),
    graines: Sequence[Graine] = (),
    maintenant: datetime | None = None,
    peut_parler: bool = True,
    peut_travailler: bool = True,
    tuning: ConduiteTuning | None = None,
) -> Decision:
    """Quelle conduite tenir ce tour-ci.

    L'ordre est délibéré et conservateur :

    1. **PARLER** dès que le score franchit le seuil. La calibration du
       scoring n'est pas retouchée : ce qui déclenchait un acte en déclenche
       toujours un, exactement. Une intégration ne peut donc pas la rendre
       plus bavarde, seulement moins muette.
    2. **POURSUIVRE**, sinon, s'il existe un travail dû. C'est bon marché et
       silencieux ; ça vit dans l'espace qui s'appelait « wait ».
    3. **OUVRIR**, sinon, si une amorce vaut le coup et qu'il reste une place.
    4. **SE_TAIRE**. Issue valide, attendue de loin la plus fréquente : sur
       2 880 tours quotidiens, tout le reste est l'exception.

    ``peut_parler`` et ``peut_travailler`` sont deux vetos distincts que le
    bord renseigne : dormir interdit les deux, mais « personne n'est joignable »
    n'interdit que la parole — et c'est justement là qu'avancer un travail a du
    sens. Les confondre en un seul drapeau ferait retomber la conduite dans le
    binaire qu'elle sort.
    """
    t = tuning or DEFAULT_TUNING

    if peut_parler and score >= seuil:
        return Decision(
            conduite=Conduite.PARLER,
            cible=None,
            motif=f"score {score:.2f} au-dessus du seuil {seuil:.2f}",
        )

    if peut_travailler:
        travail = travail_a_poursuivre(travaux, maintenant, t)
        if travail is not None:
            return Decision(
                conduite=Conduite.POURSUIVRE,
                cible=travail.identifiant,
                motif=f"un pas de plus sur « {travail.titre} »",
            )

        actifs = sum(
            1 for tr in (travaux or ())
            if not est_essouffle(tr, maintenant, t)
        )
        if actifs < t.travaux_actifs_max:
            for graine in graines or ():
                if graine.poids >= t.ouverture_envie_min:
                    return Decision(
                        conduite=Conduite.OUVRIR,
                        cible=graine,
                        motif=f"nouvelle piste ({graine.origine}) : « {graine.intitule} »",
                    )

    return Decision(
        conduite=Conduite.SE_TAIRE,
        cible=None,
        motif="rien qui vaille ce tour-ci",
    )


# ---------------------------------------------------------------------------
# La diffusion
# ---------------------------------------------------------------------------

def decider_diffusion(
    conduite: Conduite,
    *,
    adresse_a_quelqu_un: bool = False,
    resultat_notable: float = 0.0,
    derniere_diffusion_le: datetime | None = None,
    maintenant: datetime | None = None,
    tuning: ConduiteTuning | None = None,
) -> Diffusion:
    """Faut-il dire à voix haute ce que ce pas a produit ? Par défaut, non.

    Parler *est* la conduite PARLER : elle diffuse par définition. Un pas de
    travail, lui, est muet — sans quoi 4 travaux × 5 pas font 20 monologues par
    jour, et ces vingt-là passent **hors** du frein quotidien des initiatives,
    qui ne compte que les actes. On finirait par avoir rendu bavarde la moitié
    du système qui devait la faire travailler en silence.

    Deux portes seulement l'ouvrent, et l'espacement s'applique aux deux :

    * ``adresse_a_quelqu_un`` — le pas a produit quelque chose *pour* une
      personne (un rapport demandé, une réponse promise). Ce n'est pas un
      monologue, c'est une livraison.
    * ``resultat_notable >= diffusion_notable_min`` (0.80) — très haut, parce
      que le juge de la notabilité est le même modèle qui vient de produire le
      résultat, et qu'un juge qui note son propre travail note haut.
    """
    t = tuning or DEFAULT_TUNING

    if conduite is Conduite.PARLER:
        return Diffusion(True, "parler, c'est diffuser")
    if conduite is Conduite.SE_TAIRE:
        return Diffusion(False, "rien à dire")

    if not (adresse_a_quelqu_un or resultat_notable >= t.diffusion_notable_min):
        return Diffusion(False, "pas de travail : muet par défaut")

    ecoule = (
        float("inf") if derniere_diffusion_le is None
        else _secondes_ecoulees(derniere_diffusion_le, maintenant)
    )
    if ecoule < t.diffusion_intervalle_min_s:
        return Diffusion(False, "diffusion trop récente")

    if adresse_a_quelqu_un:
        return Diffusion(True, "le pas produit quelque chose pour quelqu'un")
    return Diffusion(True, f"résultat notable ({resultat_notable:.2f})")
