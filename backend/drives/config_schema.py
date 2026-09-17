"""Config schema for the drive engine.

Les quatre pulsions intrinsèques — curiosité, social, expression, repos — se
calibrent l'une CONTRE l'autre et contre le reste du moteur : le scoring de la
conscience lit leur somme signée, le prompt lit leur description, le cycle de
sommeil lit REST. C'est précisément le genre de nombres qu'on essaie en
regardant Mika vivre, pas qu'on relit dans un fichier.

Chaque défaut ci-dessous vaut EXACTEMENT la constante correspondante de
``drives/state.py`` / ``drives/engine.py``, qui reste déclarée là-bas et sert
de repli quand le registre est hors d'atteinte (import avant ``migrate``, base
verrouillée, collecte des tests). Une installation neuve se comporte donc à
l'identique ; ce qui change, c'est l'origine de la valeur. Voir
``configs/runtime.py``.
"""
from __future__ import annotations

from configs.types import ConfigGroup, ConfigItem, ConfigSection

CURIOSITY_GROUP = "Curiosité"
SOCIAL_GROUP = "Social"
EXPRESSION_GROUP = "Expression"
REST_GROUP = "Repos"
ENERGY_GROUP = "Énergie"
COMMUN_GROUP = "Communs aux quatre pulsions"


def _drive_items(
    kind: str,
    group: str,
    *,
    growth_rate: float,
    decay_on_satisfy: float,
    weight: float,
    satisfy_threshold: float,
    growth_hint: str = "",
) -> list[ConfigItem]:
    """Les quatre champs que TOUTE pulsion possède.

    Déclarés par une fabrique plutôt qu'à la main quatre fois : les libellés
    et les bornes sont les mêmes, seuls les défauts diffèrent, et une pulsion
    à qui il manquerait un champ serait un réglage muet — la lecture, elle,
    passe par ``DriveParams`` et trouverait toujours quelque chose.
    """
    return [
        ConfigItem(
            key=f"drives.{kind}.growth_rate", type="float", section="drives",
            group=group, label="Croissance par seconde",
            default=growth_rate, min=0.0, max=0.1, hot_reload=True,
            hint=growth_hint or (
                "Tension gagnée par seconde tant que la pulsion n'est pas "
                "assouvie. À 0.0030 les pulsions positives saturaient en "
                "8 min : leur somme restait collée au plafond et le bloc de "
                "prompt répétait indéfiniment les trois mêmes phrases."
            ),
        ),
        ConfigItem(
            key=f"drives.{kind}.decay_on_satisfy", type="float", section="drives",
            group=group, label="Part retirée quand la pulsion est comblée",
            default=decay_on_satisfy, min=0.0, max=1.0, hot_reload=True,
            hint="Fraction de la tension effacée par un assouvissement plein. "
                 "À 1.0 chaque satisfaction remet la pulsion à zéro, sans "
                 "aucun résidu.",
        ),
        ConfigItem(
            key=f"drives.{kind}.weight", type="float", section="drives",
            group=group, label="Poids dans le score de conscience",
            default=weight, min=0.0, max=1.0, hot_reload=True,
            hint="Ce que la pulsion vaut dans le facteur 9 du scoring, à "
                 "tension pleine. REST y contribue en NÉGATIF (la fatigue "
                 "éloigne de l'action).",
        ),
        ConfigItem(
            key=f"drives.{kind}.satisfy_threshold", type="float",
            section="drives", group=group,
            label="Seuil en dessous duquel elle se tait",
            default=satisfy_threshold, min=0.0, max=1.0, hot_reload=True,
            hint="Sous ce seuil la pulsion ne contribue plus au score et "
                 "disparaît du prompt : en dessous, c'est du bruit.",
        ),
    ]


CONFIG_SCHEMA = [
    ConfigSection(
        key="drives", label="Pulsions", icon="◈", order=45,
        family="vie_interieure",
        summary="Ce qui la pousse à parler d'elle-même, et ce qui l'en retient.",
        description=(
            "Curiosité, social, expression, repos : ce qui pousse Mika à "
            "parler d'elle-même, et ce qui l'en retient."
        ),
    ),
    # ── Organisation de l'écran ─────────────────────────────────────
    #
    # Un bloc par pulsion, dans l'ordre où elles se lisent : les trois qui
    # poussent vers l'action, puis celle qui l'en retire, puis l'énergie qui
    # les résume. Le bloc « communs » est replié : ce sont deux seuils de
    # lecture, pas des curseurs de comportement.
    ConfigGroup(
        section="drives", key=CURIOSITY_GROUP, order=10,
        description="Son envie d'apprendre quelque chose. Elle monte toute "
                    "seule avec le temps et retombe quand une conversation ou "
                    "une observation lui apporte de la matière.",
    ),
    ConfigGroup(
        section="drives", key=SOCIAL_GROUP, order=20,
        description="Son besoin de contact — la seule pulsion qui parle "
                    "d'ABSENCE, donc la seule dont l'échelle de temps se compte "
                    "en jours. Sa croissance est logarithmique : en linéaire, "
                    "une heure, un jour et trois semaines de silence rendaient "
                    "la même phrase de prompt.",
    ),
    ConfigGroup(
        section="drives", key=EXPRESSION_GROUP, order=30,
        description="Son envie de dire quelque chose d'elle-même. Une prise de "
                    "parole spontanée la vide entièrement, une simple réponse "
                    "n'en retire qu'une part.",
    ),
    ConfigGroup(
        section="drives", key=REST_GROUP, order=40,
        description="Sa fatigue. Elle ne monte pas avec le temps mais avec "
                    "l'activité, et elle avance l'heure du coucher. ⚠ Monter la "
                    "décroissance naturelle a déjà rendu TOUT le cycle de "
                    "sommeil inatteignable — la nuit n'ouvre qu'après 900 s "
                    "d'inactivité, pendant lesquelles la tension ne fait que "
                    "baisser : ce coefficient borne mécaniquement ce qu'il en "
                    "reste au moment du test.",
    ),
    ConfigGroup(
        section="drives", key=ENERGY_GROUP, order=50,
        description="Comment le rythme de la journée et la fatigue accumulée se "
                    "mélangent en un seul nombre — lu par le malus de fatigue du "
                    "scoring, par le bloc « ton rythme » du prompt et par la "
                    "jauge de l'interface.",
    ),
    ConfigGroup(
        section="drives", key=COMMUN_GROUP, order=60, advanced=True,
        description="Deux seuils de lecture partagés : à partir de quelle "
                    "tension on ose désigner une pulsion « dominante », et sur "
                    "quelle fenêtre les événements d'activité sont comptés.",
    ),

    *_drive_items(
        "curiosity", CURIOSITY_GROUP,
        growth_rate=0.0, decay_on_satisfy=0.6,
        weight=0.30, satisfy_threshold=0.35,
        growth_hint=(
            "Laissé à 0.0 : la curiosité croît en LOG-TEMPS, via les deux "
            "réglages ci-dessous. En linéaire elle saturait en 20 min 50, et "
            "comme son poids et celui de l'expression somment à 0.55 — au-delà "
            "du plafond du facteur « pulsions » (+0.50) — passé la demi-heure "
            "ce facteur valait la constante +0.50 quoi qu'il arrive."
        ),
    ),
    ConfigItem(
        key="drives.observation_curiosity_gate", type="float", section="drives",
        group=CURIOSITY_GROUP, label="Pertinence qui assouvit la curiosité",
        default=0.50, min=0.0, max=1.0, hot_reload=True,
        hint="Un signal observé au moins aussi pertinent que cette valeur "
             "calme un peu la curiosité. Réglée SOUS le plafond du chemin "
             "d'interprétation sans LLM (0.55 pour un article RSS apparié) : "
             "au-dessus, seul un e-mail — le seul signal payant un appel LLM — "
             "pouvait la franchir, et sur une installation sans compte mail "
             "apprendre quelque chose du monde ne la calmait jamais.",
    ),
    ConfigItem(
        key="drives.curiosity.growth_tau", type="float", section="drives",
        group=CURIOSITY_GROUP, label="Échelle du début de courbe (s)",
        default=120.0, min=0.0, max=86400.0, hot_reload=True,
        hint="Plus ce paramètre est petit, plus les premières minutes comptent.",
    ),
    ConfigItem(
        key="drives.curiosity.growth_horizon_days", type="float",
        section="drives", group=CURIOSITY_GROUP,
        label="Horizon de saturation (jours)",
        default=0.5, min=0.0, max=3650.0, hot_reload=True,
        hint="Temps au bout duquel la curiosité vaut 1.0. Courbe obtenue au "
             "défaut : 10 min → 0.30, 21 min → 0.42, 1 h → 0.58, 12 h → 1.0. "
             "À 0.0 la croissance logarithmique est DÉSACTIVÉE et « Croissance "
             "par seconde » reprend la main.",
    ),

    *_drive_items(
        "social", SOCIAL_GROUP,
        growth_rate=0.0, decay_on_satisfy=0.7,
        weight=0.35, satisfy_threshold=0.25,
        growth_hint=(
            "Laissé à 0.0 : SOCIAL ne croît pas linéairement mais en "
            "LOG-TEMPS, via les deux réglages ci-dessous. Une valeur non "
            "nulle ici reste inerte tant que l'horizon est renseigné."
        ),
    ),
    ConfigItem(
        key="drives.social.growth_tau", type="float", section="drives",
        group=SOCIAL_GROUP, label="Échelle du début de courbe (s)",
        default=300.0, min=0.0, max=86400.0, hot_reload=True,
        hint="SOCIAL est la seule pulsion qui parle d'ABSENCE, donc la seule "
             "dont l'échelle de temps doit dépasser le quart d'heure. En "
             "linéaire elle saturait en 16 min 40, après quoi une heure, un "
             "jour et trois semaines rendaient la même phrase de prompt. Plus "
             "ce paramètre est petit, plus les premières minutes comptent.",
    ),
    ConfigItem(
        key="drives.social.growth_horizon_days", type="float", section="drives",
        group=SOCIAL_GROUP, label="Horizon de saturation (jours)",
        default=30.0, min=0.0, max=3650.0, hot_reload=True,
        hint="Temps au bout duquel l'absence vaut 1.0. Courbe obtenue au "
             "défaut : 1 h → 0.28, 1 j → 0.63, 1 sem → 0.84, 3 sem → 0.96. "
             "À 0.0 la croissance logarithmique est DÉSACTIVÉE et « Croissance "
             "par seconde » reprend la main.",
    ),

    *_drive_items(
        "expression", EXPRESSION_GROUP,
        growth_rate=0.0, decay_on_satisfy=0.8,
        weight=0.25, satisfy_threshold=0.45,
        growth_hint=(
            "Laissé à 0.0 : l'expression croît en LOG-TEMPS, via les deux "
            "réglages ci-dessous. En linéaire elle saturait en 23 min 49."
        ),
    ),
    ConfigItem(
        key="drives.expression.growth_tau", type="float", section="drives",
        group=EXPRESSION_GROUP, label="Échelle du début de courbe (s)",
        default=180.0, min=0.0, max=86400.0, hot_reload=True,
    ),
    ConfigItem(
        key="drives.expression.growth_horizon_days", type="float",
        section="drives", group=EXPRESSION_GROUP,
        label="Horizon de saturation (jours)",
        default=0.375, min=0.0, max=3650.0, hot_reload=True,
        hint="Temps au bout duquel l'envie de dire quelque chose vaut 1.0. "
             "Horizon plus court que la curiosité : une envie de s'exprimer se "
             "constitue dans la journée, pas sur trois semaines comme une "
             "absence. Courbe obtenue au défaut : 10 min → 0.28, 24 min → "
             "0.42, 1 h → 0.59, 9 h → 1.0.",
    ),

    *_drive_items(
        "rest", REST_GROUP,
        growth_rate=0.0, decay_on_satisfy=0.3,
        weight=0.20, satisfy_threshold=0.50,
        growth_hint=(
            "Laissé à 0.0 : REST ne monte pas avec le temps qui passe mais "
            "avec le temps d'ACTIVITÉ — voir « Fatigue gagnée par heure "
            "d'activité soutenue » ci-dessous."
        ),
    ),
    ConfigItem(
        key="drives.rest.growth_per_active_hour", type="float", section="drives",
        group=REST_GROUP, label="Fatigue gagnée par heure d'activité soutenue",
        default=0.2, min=0.0, max=2.0, hot_reload=True,
        hint="REST monte avec le TEMPS passé à répondre et à agir, pas avec "
             "le nombre de messages : chaque réponse ouvre une fenêtre "
             "d'activité (« Fenêtre glissante d'activité » plus bas) pendant "
             "laquelle la fatigue croît à ce taux. À 0.2, deux heures de "
             "conversation dense valent 0.4 et cinq heures la saturent ; une "
             "réponse isolée ajoute ~0.03. Elle était comptée par réponse "
             "(0.04 × la longueur) : quatorze réponses — quinze minutes de "
             "chat — l'épuisaient.",
    ),
    ConfigItem(
        key="drives.rest.natural_decay_per_second", type="float",
        section="drives", group=REST_GROUP,
        label="Décroissance naturelle du repos (par seconde)",
        default=0.0002, min=0.0, max=0.0008, hot_reload=True,
        hint="Hors activité seulement (pendant une fenêtre d'activité, REST "
             "ne fait que monter). À 0.0002 (0.72/h), la fatigue d'un chat de "
             "deux heures (0.4) s'absorbe en ~35 min de calme ; à 0.0001 elle "
             "durait trois heures. REST n'interdit plus de dormir (il avance "
             "l'heure du coucher), donc ce coefficient ne ferme plus la nuit "
             "comme il l'a fait jadis à 0.0008 ; le sommeil reste ce qui vide "
             "une fatigue installée.",
    ),

    ConfigItem(
        key="drives.dominant_min_tension", type="float", section="drives",
        group=COMMUN_GROUP,
        label="Tension minimale d'une pulsion « dominante »",
        default=0.2, min=0.0, max=1.0, hot_reload=True,
        hint="En dessous, aucune pulsion n'est déclarée dominante : tout est "
             "calme, et le dire vaut mieux que désigner un gagnant à 0.03.",
    ),
    ConfigItem(
        key="drives.activity_window_seconds", type="float", section="drives",
        group=COMMUN_GROUP,
        label="Fenêtre glissante d'activité (s)",
        default=600.0, min=1.0, max=86400.0, hot_reload=True,
        hint="Combien de temps une réponse ou un acte « tient » comme "
             "activité : tant que la fenêtre court, la fatigue monte ; passé "
             "ce délai sans nouvel échange, elle redescend.",
    ),

    ConfigItem(
        key="drives.energy.circadian_weight", type="float", section="drives",
        group=ENERGY_GROUP, label="Part du rythme circadien",
        default=0.7, min=0.0, max=1.0, hot_reload=True,
        hint="energie = part circadienne × courbe horaire + part repos × "
             "(1 − tension REST). Le premier terme donne les matins et les "
             "nuits, le second la fatigue à court terme.",
    ),
    ConfigItem(
        key="drives.energy.rest_weight", type="float", section="drives",
        group=ENERGY_GROUP, label="Part de la fatigue accumulée",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
        hint="Les deux parts somment à 1.0 au défaut. Le résultat est de "
             "toute façon ramené dans [0, 1] : les désaccorder ne casse rien, "
             "cela déplace seulement le milieu de l'échelle — et l'énergie "
             "est lue par le scoring, par le prompt et par la jauge de "
             "l'interface.",
    ),
]
