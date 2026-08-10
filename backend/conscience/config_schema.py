"""Config schema for the conscience engine.

Les onze facteurs du score de décision étaient des littéraux anonymes au
milieu de ``scoring.py`` : régler la spontanéité de Mika demandait de
modifier le code. Ils sont ici, nommés, avec les valeurs d'origine pour
défauts — la constante de repli reste dans le module, et vaut exactement
ce ``default``.

**Invariant à ne pas casser** : les trois plafonds — inactivité +0.30,
« on m'ignore » −0.30, pulsions +0.50 — somment *exactement* à
``conscience.act_threshold`` (0.50), comparé avec ``>=``. C'est cette
arithmétique qui fait qu'aucune quantité de silence ne peut la museler
complètement, et la déséquilibrer reproduit le bug documenté des « cinq
initiatives en vingt minutes, puis vingt-trois heures de silence ».
"""
from __future__ import annotations

from configs.types import ConfigGroup, ConfigItem, ConfigSection

#: Répété dans les trois plafonds qui se compensent. Un opérateur qui n'en
#: lit qu'un doit quand même voir l'équation entière.
_INVARIANT_PLAFONDS = (
    "INVARIANT : inactivité (+0.30) + pulsions (+0.50) − ignorée (−0.30) = "
    "0.50, soit exactement « Seuil score → agir », comparé avec ≥ — donc "
    "l'égalité agit. C'est ce qui empêche le silence de la museler tout à "
    "fait. Monter le plafond des pulsions ou baisser celui de « on "
    "m'ignore » recrée le défaut connu : cinq initiatives en vingt minutes, "
    "puis vingt-trois heures de mutisme."
)

_GROUPE_FACTEURS = "Pondération de la décision"
_GROUPE_PERTINENCE = "Pertinence sans appel LLM"
_GROUPE_ENTRETIEN = "Cadences d'entretien"
_GROUPE_SALUT = "Salutations"
_GROUPE_AUDIT = "Retour sur ce qu'elle vient de dire"
_GROUPE_BASE = "Seuil et cadence"
_GROUPE_PENSEES = "Pensées qui trottent"
_GROUPE_INITIATIVE = "Initiative"
_GROUPE_SOMMEIL = "Sommeil"
_GROUPE_BUDGETS = "Budgets d'appel"

CONFIG_SCHEMA = [
    ConfigSection(
        key="conscience", label="Conscience", icon="◉", order=50,
        family="vie_interieure",
        summary="Ce qui décide qu'elle prend la parole d'elle-même, et à quelle fréquence.",
        description="Boucle de décision, seuil d'action, cooldown.",
    ),
    # ── Organisation de l'écran ─────────────────────────────────────
    #
    # Soixante-six réglages, dont vingt-sept qui ne sont que les poids des
    # onze facteurs du score : le tas rendait invisible les cinq qu'on règle
    # vraiment. L'ordre suit la question qu'on se pose en arrivant — quand
    # parle-t-elle, à quel rythme relance-t-elle, que garde-t-elle en tête,
    # dort-elle — et tout ce qui relève du calibrage est replié.
    #
    # « Replié » n'est pas « caché » : le bloc reste cherchable, et il s'ouvre
    # de lui-même s'il contient une valeur modifiée.
    ConfigGroup(
        section="conscience", key=_GROUPE_BASE, order=10,
        description="Les trois nombres qui décident si elle parle : à quelle "
                    "cadence elle se pose la question, le score qu'il faut pour "
                    "que la réponse soit oui, et le silence minimal entre deux "
                    "prises de parole. C'est ici qu'on rend Mika plus ou moins "
                    "bavarde, avant de toucher au moindre poids.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_INITIATIVE, order=20,
        description="Ce que ça lui fait d'être ignorée. Chaque relance sans "
                    "réponse espace la suivante, jusqu'à un plafond, puis un "
                    "frein dur tombe. Sans cet espacement, elle dépensait ses "
                    "cinq initiatives du jour en vingt minutes puis se taisait "
                    "vingt-trois heures.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_PENSEES, order=30,
        description="Les signaux pertinents qu'elle n'a pas traités deviennent "
                    "des pensées qui traînent : elles s'éteignent sur une "
                    "demi-vie en heures d'horloge, changent de couleur avec le "
                    "temps et teintent son humeur. Cette échelle en heures est "
                    "ce qui permet à une contrariété du soir d'être encore là "
                    "au coucher, donc d'être digérée par la nuit.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_SALUT, order=40,
        description="Les trois créneaux où un bonjour est de mise, une fois par "
                    "période et par jour. Le bonus ne suffit jamais seul à la "
                    "faire parler, délibérément : la période n'est marquée "
                    "« saluée » que si le cycle décide vraiment d'ouvrir la "
                    "bouche.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_SOMMEIL, order=50,
        description="Ce qu'il faut pour la réveiller, et à quel point dormir la "
                    "rend silencieuse. Un veto seul ne suffisait pas : dormir "
                    "vide la fatigue, donc annule le malus de fatigue, ce qui la "
                    "rendait mécaniquement plus bavarde à 3 h que la veille au "
                    "soir.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_FACTEURS, order=60, advanced=True,
        description="Les poids des onze facteurs qui composent le score. "
                    "⚠ INVARIANT : les trois plafonds — inactivité (+0.30), "
                    "pulsions (+0.50), « on m'ignore » (−0.30) — somment "
                    "EXACTEMENT au seuil d'action (0.50), comparé avec ≥, donc "
                    "l'égalité agit. C'est ce qui empêche le silence de la "
                    "museler tout à fait. Les déséquilibrer recrée le défaut "
                    "connu : cinq initiatives en vingt minutes, puis vingt-trois "
                    "heures de mutisme.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_PERTINENCE, order=70, advanced=True,
        description="Ce que vaut un signal quand on ne paie PAS un appel LLM "
                    "pour l'interpréter. Ce raccourci couvre tout ce qui est "
                    "volumineux — chat, Telegram, RSS, modules forgés — parce "
                    "que l'interprétation tourne en série dans la boucle du "
                    "module qui émet : cinq flux RSS, c'était ~75 appels à la "
                    "suite avec l'ordonnanceur figé.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_BUDGETS, order=80, advanced=True,
        description="Combien de temps elle s'accorde pour interpréter un "
                    "signal, choisir à qui parler et vérifier une connaissance. "
                    "Ces appels tiennent le verrou de décision ou la boucle du "
                    "module émetteur : les allonger fige autre chose, ce n'est "
                    "jamais gratuit.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_ENTRETIEN, order=90, advanced=True,
        description="Le ménage de fond : combien de temps une observation reste "
                    "en attente, quand elle est périmée, quand elle est purgée, "
                    "et à quelle cadence les pulsions sont sauvegardées. Un "
                    "instantané seulement à l'arrêt propre ne survit pas à un "
                    "« kill -9 » — soit exactement le cas où la fatigue du soir "
                    "disparaissait avec la nuit qu'elle devait déclencher.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_AUDIT, order=100, advanced=True,
        description="Ce qui arrive quand elle vient de dire quelque chose de "
                    "chargé : elle se le repasse, et ça laisse une "
                    "micro-rumination. Le plafond est bas exprès — une personne "
                    "normale rejoue une ou deux fois, elle ne ressasse pas.",
    ),
    ConfigItem(
        key="conscience.decision_interval", type="int", section="conscience",
        group=_GROUPE_BASE,
        label="Intervalle décision (s)",
        default=30, min=5, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="conscience.cooldown_seconds", type="int", section="conscience",
        group=_GROUPE_BASE,
        label="Cooldown entre actions (s)",
        default=300, min=0, max=86400, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.act_threshold", type="float", section="conscience",
        group=_GROUPE_BASE,
        label="Seuil score → agir",
        default=0.5, min=0.0, max=1.0, hot_reload=True,
        hint="Plus haut = Mika parle moins spontanément. " + _INVARIANT_PLAFONDS,
    ),
    ConfigItem(
        key="conscience.rumination_half_life_hours", type="float",
        section="conscience", group="Pensées qui trottent",
        label="Demi-vie d'une pensée (h)",
        default=6.0, min=0.25, max=72.0, hot_reload=True,
        hint="Temps au bout duquel une pensée non résolue a perdu la moitié "
             "de son intensité. Se compte en HEURES écoulées, pas en tours de "
             "boucle : c'est ce qui permet à une contrariété du soir d'être "
             "encore là au coucher, donc d'être digérée par la nuit.",
    ),
    ConfigItem(
        key="conscience.rumination_drift_hours", type="float",
        section="conscience", group="Pensées qui trottent",
        label="Délai avant que la pensée change de forme (h)",
        default=1.0, min=0.1, max=24.0, hot_reload=True,
        hint="Au-delà, une frustration devient de l'inquiétude, un "
             "enthousiasme devient de la nostalgie.",
    ),
    ConfigItem(
        key="conscience.rumination_bleed_interval_seconds", type="float",
        section="conscience", group="Pensées qui trottent",
        label="Espacement entre deux teintes d'humeur (s)",
        default=600.0, min=30.0, max=86400.0, hot_reload=True,
        hint="Une pensée colore l'humeur globale, elle ne la matraque pas. "
             "Tant qu'une rumination mourait en 22 minutes, saigner à chaque "
             "cycle de 30 s était auto-limité ; maintenant qu'elle vit des "
             "heures, la même cadence clouerait l'humeur sur son émotion pour "
             "la soirée entière.",
    ),
    ConfigItem(
        key="conscience.rumination_bleed_intensity", type="float",
        section="conscience", group="Pensées qui trottent",
        label="Part de la pensée versée dans l'humeur (×)",
        default=0.15, min=0.0, max=1.0, hot_reload=True,
        hint="Fraction de l'intensité de la rumination envoyée comme "
             "impulsion émotionnelle. À 1.0 une pensée tenace impose son "
             "émotion à l'humeur globale.",
    ),
    ConfigItem(
        key="conscience.ignored_backoff_factor", type="float",
        section="conscience", group="Initiative",
        label="Espacement après une relance sans réponse (×)",
        default=2.5, min=1.0, max=10.0, hot_reload=True,
        hint="Le cooldown est multiplié par ce facteur à chaque initiative "
             "restée sans réponse. À 1.0 elle relance toujours au même rythme "
             "— c'est ce qui produisait cinq messages en vingt minutes.",
    ),
    ConfigItem(
        key="conscience.cooldown_max_seconds", type="float",
        section="conscience", group="Initiative",
        label="Plafond de l'espacement (s)",
        default=21600.0, min=60.0, max=172800.0, hot_reload=True,
        hint="Au-delà d'une demi-journée sans un mot, se taire davantage "
             "n'est plus de la retenue, c'est une panne. Le frein quotidien "
             "reste la borne du jour.",
    ),
    ConfigItem(
        key="conscience.daily_acts_cap", type="int",
        section="conscience", group="Initiative",
        label="Initiatives par jour avant frein",
        default=5, min=0, max=200, hot_reload=True,
        hint="Frein dur : au-delà de ce nombre d'actes dans la journée ET de "
             "« Relances ignorées avant frein » relances sans réponse, le "
             "score est ramené au plancher.",
    ),
    ConfigItem(
        key="conscience.suppress_after_ignored", type="int",
        section="conscience", group="Initiative",
        label="Relances ignorées avant frein",
        default=3, min=0, max=50, hot_reload=True,
        hint="Deuxième condition du frein dur ; les deux doivent être "
             "réunies pour qu'il tombe.",
    ),
    ConfigItem(
        key="conscience.suppressed_score", type="float",
        section="conscience", group="Initiative",
        label="Score plafonné une fois freinée",
        default=0.1, min=0.0, max=1.0, hot_reload=True,
        hint="Doit rester sous le seuil d'action, sinon le frein ne freine "
             "rien.",
    ),

    # ── Sommeil ──────────────────────────────────────────────────
    ConfigItem(
        key="conscience.sleep_wake_pertinence", type="float",
        section="conscience", group="Sommeil",
        label="Pertinence qui la réveille",
        default=0.85, min=0.0, max=1.0, hot_reload=True,
        hint="Une seule valeur pour deux sites : le veto « elle dort » du "
             "scoring et le fast-path de décision immédiate d'``observe``. "
             "Un acte non urgent la nuit est un réveil, pas une initiative.",
    ),
    ConfigItem(
        key="conscience.sleep_penalty", type="float",
        section="conscience", group="Sommeil",
        label="Malus de score pendant le sommeil",
        default=0.30, min=0.0, max=1.0, hot_reload=True,
        hint="Retranché au score quand elle dort, en plus du veto : dormir "
             "vide REST, donc annule la pénalité de fatigue, ce qui la "
             "rendait mécaniquement plus bavarde la nuit que la veille au "
             "soir.",
    ),

    # ── Les onze facteurs ────────────────────────────────────────
    ConfigItem(
        key="conscience.factor.pertinence_gate", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F1 · Pertinence : seuil d'entrée",
        default=0.7, min=0.0, max=1.0, hot_reload=True,
        hint="En dessous, l'observation la plus pertinente ne contribue pas.",
    ),
    ConfigItem(
        key="conscience.factor.pertinence_weight", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F1 · Pertinence : poids",
        default=0.4, min=0.0, max=2.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.urgency_gate", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F2 · Urgence accumulée : seuil d'entrée",
        default=0.5, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.urgency_weight", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F2 · Urgence accumulée : poids",
        default=0.3, min=0.0, max=2.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.urgency_cap", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F2 · Urgence accumulée : plafond",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.mood_gate", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F3 · Débordement d'humeur : seuil d'entrée",
        default=0.7, min=0.0, max=1.0, hot_reload=True,
        hint="Intensité de l'humeur globale au-delà de laquelle elle a "
             "quelque chose de non exprimé.",
    ),
    ConfigItem(
        key="conscience.factor.mood_bonus", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F3 · Débordement d'humeur : bonus",
        default=0.25, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.idle_gate_minutes", type="int",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F4 · Inactivité : silence avant de compter (min)",
        default=10, min=0, max=1440, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.idle_ramp_minutes", type="int",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F4 · Inactivité : montée jusqu'au plafond (min)",
        default=30, min=1, max=1440, hot_reload=True,
        hint="Durée, après le seuil, au bout de laquelle le plafond est "
             "atteint.",
    ),
    ConfigItem(
        key="conscience.factor.idle_cap", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F4 · Inactivité : plafond",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
        hint=_INVARIANT_PLAFONDS,
    ),
    ConfigItem(
        key="conscience.factor.greeting_bonus", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F5 · Salutation : bonus",
        default=0.35, min=0.0, max=1.0, hot_reload=True,
        hint="Ne suffit pas seul à franchir le seuil, délibérément : la "
             "période n'est marquée « saluée » que si le cycle décide "
             "vraiment de parler.",
    ),
    ConfigItem(
        key="conscience.factor.scheduled_weight", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F6 · Action programmée : poids",
        default=0.5, min=0.0, max=2.0, hot_reload=True,
        hint="Multiplie la priorité de l'action due la plus prioritaire.",
    ),
    ConfigItem(
        key="conscience.factor.pressure_min_waits", type="int",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F7 · Pression : attentes consécutives requises",
        default=3, min=1, max=100, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.pressure_per_wait", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F7 · Pression : par attente au-delà",
        default=0.035, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.pressure_cap", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F7 · Pression : plafond",
        default=0.25, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.ignored_min_acts", type="int",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F8 · On m'ignore : relances sans réponse requises",
        default=2, min=1, max=100, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.ignored_per_act", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F8 · On m'ignore : malus par relance",
        default=0.1, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.ignored_cap", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F8 · On m'ignore : plafond du malus",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
        hint=_INVARIANT_PLAFONDS,
    ),
    ConfigItem(
        key="conscience.factor.drives_floor", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F9 · Pulsions : plancher (fatigue)",
        default=-0.4, min=-2.0, max=0.0, hot_reload=True,
        hint="REST soustrait ; la soustraction est appliquée APRÈS le "
             "plafond des pulsions positives, sinon REST à 0.0 et REST à 1.0 "
             "rendent exactement le même score.",
    ),
    ConfigItem(
        key="conscience.factor.drives_cap", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F9 · Pulsions : plafond des positives",
        default=0.5, min=0.0, max=2.0, hot_reload=True,
        hint=_INVARIANT_PLAFONDS,
    ),
    ConfigItem(
        key="conscience.factor.drives_deadband", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F9 · Pulsions : zone morte",
        default=0.02, min=0.0, max=1.0, hot_reload=True,
        hint="En deçà en valeur absolue, la contribution n'est ni comptée ni "
             "mentionnée dans la raison journalisée.",
    ),
    ConfigItem(
        key="conscience.factor.rumination_gate", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F10 · Ruminations : seuil d'entrée",
        default=0.2, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.rumination_weight", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F10 · Ruminations : poids",
        default=0.35, min=0.0, max=2.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.rumination_cap", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F10 · Ruminations : plafond",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
        hint="Une pensée qui trotte, seule, ne doit pas pouvoir forcer la "
             "prise de parole.",
    ),
    ConfigItem(
        key="conscience.factor.fatigue_gate", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F11 · Fatigue : énergie sous laquelle elle pèse",
        default=0.5, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.fatigue_slope", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F11 · Fatigue : pente",
        default=0.5, min=0.0, max=2.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.factor.fatigue_cap", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F11 · Fatigue : plafond du malus",
        default=0.25, min=0.0, max=1.0, hot_reload=True,
        hint="Un signal vraiment pertinent doit encore passer à 3 h du matin.",
    ),

    # ── Salutations ──────────────────────────────────────────────
    ConfigItem(
        key="conscience.greeting.morning_start", type="int",
        section="conscience", group=_GROUPE_SALUT,
        label="Matin : début (h)",
        default=7, min=0, max=23, hot_reload=True,
        hint="Une salutation par période et par jour. Les bornes de fin sont "
             "exclues (7 ≤ heure < 10).",
    ),
    ConfigItem(
        key="conscience.greeting.morning_end", type="int",
        section="conscience", group=_GROUPE_SALUT,
        label="Matin : fin (h, exclue)",
        default=10, min=0, max=24, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.greeting.evening_start", type="int",
        section="conscience", group=_GROUPE_SALUT,
        label="Soir : début (h)",
        default=18, min=0, max=23, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.greeting.evening_end", type="int",
        section="conscience", group=_GROUPE_SALUT,
        label="Soir : fin (h, exclue)",
        default=20, min=0, max=24, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.greeting.night_start", type="int",
        section="conscience", group=_GROUPE_SALUT,
        label="Nuit : début (h, sans fin)",
        default=23, min=0, max=23, hot_reload=True,
    ),

    # ── Pertinences heuristiques ─────────────────────────────────
    ConfigItem(
        key="conscience.pertinence.chat_message", type="float",
        section="conscience", group=_GROUPE_PERTINENCE,
        label="Message de chat",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
        hint="ATTENTION : l'urgence accumulée ne somme que les observations "
             "de pertinence STRICTEMENT supérieure à 0.3 (littéral du moteur, "
             "non configurable). À la valeur par défaut, un message de chat "
             "contribue donc exactement zéro à ce facteur — comportement "
             "d'origine, préservé tel quel. Monter cette valeur au-dessus de "
             "0.3 le fait basculer.",
    ),
    ConfigItem(
        key="conscience.pertinence.chat_presence", type="float",
        section="conscience", group=_GROUPE_PERTINENCE,
        label="Connexion / déconnexion",
        default=0.1, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.pertinence.telegram_message", type="float",
        section="conscience", group=_GROUPE_PERTINENCE,
        label="Message Telegram",
        default=0.4, min=0.0, max=1.0, hot_reload=True,
        hint="Plus haut qu'un message web : le canal est asynchrone, elle ne "
             "l'a pas forcément vu passer.",
    ),
    ConfigItem(
        key="conscience.pertinence.rss_matched", type="float",
        section="conscience", group=_GROUPE_PERTINENCE,
        label="Article RSS touchant un de ses thèmes",
        default=0.45, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.pertinence.rss_unmatched", type="float",
        section="conscience", group=_GROUPE_PERTINENCE,
        label="Article RSS sans thème reconnu",
        default=0.2, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.pertinence.forge_event", type="float",
        section="conscience", group=_GROUPE_PERTINENCE,
        label="Signal d'un module forgé",
        default=0.2, min=0.0, max=1.0, hot_reload=True,
        hint="Elle a écrit le module et choisi ce qu'il rapporte. Un module "
             "forgé qui veut son attention passe par ``api.notify_ai``.",
    ),
    ConfigItem(
        key="conscience.pertinence.fallback", type="float",
        section="conscience", group=_GROUPE_PERTINENCE,
        label="Signal non interprété (repli)",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
        hint="Servi quand l'appel d'interprétation échoue, expire ou rend un "
             "JSON illisible.",
    ),

    # ── Budgets d'appel ──────────────────────────────────────────
    ConfigItem(
        key="conscience.interpretation_timeout_seconds", type="int",
        section="conscience", group="Budgets d'appel",
        label="Interprétation d'un signal (s)",
        default=15, min=1, max=600, hot_reload=True,
        hint="Un appel plus long immobilise la boucle du module qui émet "
             "l'événement : la conscience observe en AWAIT.",
    ),
    ConfigItem(
        key="conscience.recipient_timeout_seconds", type="int",
        section="conscience", group="Budgets d'appel",
        label="Choix du destinataire (s)",
        default=15, min=1, max=600, hot_reload=True,
        hint="Passe 1 de la parole spontanée. L'expiration se replie sur le "
             "broadcast interne — ne rien dire à personne est un résultat "
             "valide. Dépenser ici la borne d'un tour de conversation "
             "immobiliserait le verrou de décision pour quatre cycles.",
    ),
    ConfigItem(
        key="conscience.validity_timeout_seconds", type="int",
        section="conscience", group="Budgets d'appel",
        label="Validation d'une connaissance (s)",
        default=15, min=1, max=600, hot_reload=True,
        hint="Budget par appel, pas par lot : jusqu'à cinq candidats sont "
             "validés en série, verrou de décision tenu.",
    ),

    # ── Cadences d'entretien ─────────────────────────────────────
    ConfigItem(
        key="conscience.pending_window_minutes", type="int",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Fenêtre des observations en attente (min)",
        default=30, min=1, max=1440, hot_reload=True,
        hint="Une seule valeur pour trois lectures qui doivent s'accorder : "
             "ce que le scoring voit, ce que le balayage périme, et la borne "
             "haute de la promotion en rumination.",
    ),
    ConfigItem(
        key="conscience.ignored_reply_window_minutes", type="int",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Délai pour qu'une relance compte comme répondue (min)",
        default=10, min=1, max=1440, hot_reload=True,
        hint="Au-delà, l'initiative est comptée comme ignorée — ce qui "
             "allonge le cooldown et pèse au facteur 8.",
    ),
    ConfigItem(
        key="conscience.observation_retention_hours", type="int",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Rétention des observations closes (h)",
        default=48, min=1, max=8760, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.stale_sweep_interval_seconds", type="int",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Balayage des observations périmées (s)",
        default=300, min=10, max=86400, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.cleanup_interval_seconds", type="int",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Purge des vieilles observations (s)",
        default=3600, min=60, max=86400, hot_reload=True,
        hint="Un lot plein reprogramme le passage au cycle suivant plutôt "
             "que dans une heure : rien ne s'accumule.",
    ),
    ConfigItem(
        key="conscience.drive_save_interval_seconds", type="int",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Instantané des pulsions (s)",
        default=300, min=10, max=86400, hot_reload=True,
        hint="Sauver au seul arrêt propre ne couvre pas un « kill -9 », qui "
             "est exactement le cas où la fatigue du soir disparaissait avec "
             "la nuit qu'elle devait déclencher.",
    ),

    # ── Audit d'après-coup ───────────────────────────────────────
    ConfigItem(
        key="conscience.audit.min_intensity", type="float",
        section="conscience", group=_GROUPE_AUDIT,
        label="Intensité minimale pour se repasser sa réponse",
        default=0.55, min=0.0, max=1.0, hot_reload=True,
        hint="Sous ce niveau, aucune micro-rumination : une réponse tiède ne "
             "se rejoue pas mentalement.",
    ),
    ConfigItem(
        key="conscience.audit.base_intensity", type="float",
        section="conscience", group=_GROUPE_AUDIT,
        label="Intensité de départ de la micro-rumination",
        default=0.2, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.audit.slope", type="float",
        section="conscience", group=_GROUPE_AUDIT,
        label="Pente au-delà du seuil",
        default=0.5, min=0.0, max=2.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.audit.max_intensity", type="float",
        section="conscience", group=_GROUPE_AUDIT,
        label="Plafond de la micro-rumination",
        default=0.45, min=0.0, max=1.0, hot_reload=True,
        hint="Une personne normale ne ressasse pas, elle rejoue une ou deux "
             "fois.",
    ),
]
