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
_GROUPE_AUDIT = "Retour sur ce qu'elle vient de dire"
_GROUPE_BASE = "Seuil et cadence"
_GROUPE_PENSEES = "Pensées qui trottent"
_GROUPE_INITIATIVE = "Initiative"
_GROUPE_SOMMEIL = "Sommeil"
_GROUPE_BUDGETS = "Budgets d'appel"
_GROUPE_PORTES = "Portes de pertinence"
_GROUPE_TROUSSE = "Trousse d'un acte"
_GROUPE_VECU = "Ce qu'elle se raconte"
_GROUPE_MURMURE = "Ce qu'on l'entend se dire"
_GROUPE_TRAVAIL = "Ce qu'elle entreprend"
_GROUPE_TRAVAIL_CAL = "Ce qu'elle entreprend · calibrage"

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
        section="conscience", key=_GROUPE_TROUSSE, order=22,
        description="Quels outils elle a réellement sous la main quand elle "
                    "prend la parole d'elle-même. La trousse se dérivait des "
                    "seules sources d'observation — or l'inactivité, une "
                    "salutation, un débordement d'humeur, une pulsion ou une "
                    "pensée qui insiste n'en créent aucune : le seul cas où "
                    "elle agissait spontanément était aussi le seul où elle "
                    "n'avait aucune main, pendant que le prompt lui énumérait "
                    "tout ce que le système sait faire.",
    ),
    ConfigItem(
        key="conscience.trousse.socle", type="list",
        section="conscience", group=_GROUPE_TROUSSE,
        label="Modules toujours chargés pour un acte spontané",
        default=["conscience_tools", "memory_tools"], hot_reload=True,
        hint="Jamais coupés par le plafond : les couper reviendrait au défaut "
             "d'origine par une autre porte.",
    ),
    ConfigItem(
        key="conscience.trousse.curiosite", type="list",
        section="conscience", group=_GROUPE_TROUSSE,
        label="Modules ajoutés quand la curiosité est saillante",
        default=["rss", "files"], hot_reload=True,
        hint="Les surfaces où quelque chose de neuf peut être TROUVÉ plutôt "
             "qu'inventé — la mémoire, déjà au socle, ne rend que du "
             "déjà-vécu.",
    ),
    ConfigItem(
        key="conscience.trousse.social", type="list",
        section="conscience", group=_GROUPE_TROUSSE,
        label="Modules ajoutés quand le besoin de contact est saillant",
        default=["email", "identity_tools"], hot_reload=True,
        hint="L'e-mail est le seul canal sortant qu'elle peut ouvrir d'elle-"
             "même ; l'identité va avec, joindre quelqu'un suppose de savoir "
             "de qui on parle.",
    ),
    ConfigItem(
        key="conscience.trousse.plafond_caracteres", type="int",
        section="conscience", group=_GROUPE_TROUSSE,
        label="Plafond de la trousse (caractères de déclaration)",
        default=8000, min=0, max=60000, hot_reload=True,
        hint="Une déclaration d'outil est du PROMPT, re-payé à chaque "
             "itération de la boucle d'outils. Mesuré : le socle pèse ~2 900 "
             "caractères, les dix modules ~20 600. Le plafond se consomme "
             "module par module et jamais outil par outil — une demi-trousse "
             "est un piège, le modèle voyant « envoyer un mail » sans « lire "
             "les mails » conclut qu'il peut écrire à l'aveugle.",
    ),
    ConfigItem(
        key="conscience.trousse.porte_pulsion", type="float",
        section="conscience", group=_GROUPE_TROUSSE,
        label="Tension à partir de laquelle une pulsion élargit la trousse",
        default=0.50, min=0.0, max=1.0, hot_reload=True,
        hint="Alignée sur la porte d'assouvissement de la curiosité et "
             "volontairement sous le plafond du chemin sans LLM (0.55) : une "
             "porte qu'aucun signal ne franchit est une porte fermée.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_VECU, order=23,
        description="Ce qu'elle se dit à elle-même quand elle décide de "
                    "parler. Un cycle cumule souvent plusieurs motifs — une "
                    "salutation ET une humeur qui déborde — et ils sont "
                    "maintenant tous dits. Les portes d'inactivité, d'humeur "
                    "et de pensée ne sont PAS réglables ici : elles sont "
                    "reprises telles quelles du bloc de pondération, pour "
                    "qu'il soit impossible d'annoncer dans le prompt un motif "
                    "que le score n'a pas compté.",
    ),
    ConfigItem(
        key="conscience.vecu.porte_pulsion", type="float",
        section="conscience", group=_GROUPE_VECU,
        label="Tension à partir de laquelle une pulsion se dit",
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        hint="Propre au récit, contrairement aux trois autres portes : le "
             "score pondère les quatre pulsions ensemble, là où une phrase ne "
             "peut nommer que celle qui domine.",
    ),
    ConfigItem(
        key="conscience.vecu.pulsion_forte", type="float",
        section="conscience", group=_GROUPE_VECU,
        label="Tension au-dessus de laquelle l'envie se dit plus fort",
        default=0.85, min=0.0, max=1.0, hot_reload=True,
        hint="Change le registre de la phrase, pas le fait de la dire.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_MURMURE, order=24,
        description="Ce qu'on l'entend se dire à elle-même avant d'agir — "
                    "« oh tiens, si j'allais voir… ». Diffusé au groupe "
                    "global, sans destinataire : une pensée adressée à "
                    "quelqu'un partirait en note vocale. Les six gardes sont "
                    "toutes évaluées AVANT l'appel au modèle, donc un quota "
                    "épuisé ou une absence de public ne coûtent rien.",
    ),
    ConfigItem(
        key="conscience.murmure.quota_quotidien", type="int",
        section="conscience", group=_GROUPE_MURMURE,
        label="Murmures par jour",
        default=8, min=0, max=200, hot_reload=True,
        hint="Compté sur la journée locale, et partagé entre la conscience et "
             "le lanceur de projets : c'est le même personnage qui pense à "
             "voix haute. À 0, elle ne murmure jamais.",
    ),
    ConfigItem(
        key="conscience.murmure.delai_min_secondes", type="float",
        section="conscience", group=_GROUPE_MURMURE,
        label="Délai minimal entre deux tentatives (s)",
        default=600.0, min=0.0, max=86400.0, hot_reload=True,
        hint="S'applique même quand le modèle n'a rien rendu — sinon un modèle "
             "en échec serait rappelé à chacun des tours de conscience, toutes "
             "les 30 s.",
    ),
    ConfigItem(
        key="conscience.murmure.longueur_max", type="int",
        section="conscience", group=_GROUPE_MURMURE,
        label="Longueur maximale d'un murmure (caractères)",
        default=160, min=1, max=2000, hot_reload=True,
        hint="Coupe de sécurité côté sortie : la voix intérieure plafonne déjà, "
             "mais depuis SA configuration, et le murmure ne doit pas grandir "
             "parce qu'un autre réglage a bougé.",
    ),
    ConfigItem(
        key="conscience.murmure.fenetre_repetition_secondes", type="float",
        section="conscience", group=_GROUPE_MURMURE,
        label="Fenêtre anti-répétition (s)",
        default=3600.0, min=0.0, max=86400.0, hot_reload=True,
        hint="Deux intentions identiques dans cette fenêtre ne donnent qu'un "
             "murmure. C'est ce qui empêche de dépenser le quota du jour en "
             "huit variantes d'une même pensée.",
    ),
    ConfigItem(
        key="conscience.murmure.endormie", type="bool",
        section="conscience", group=_GROUPE_MURMURE,
        label="Murmurer aussi pendant le sommeil",
        default=False, hot_reload=True,
        hint="Ce n'est PAS un doublon de la politique vocale : celle-ci laisse "
             "délibérément passer une pensée intérieure même endormie — c'est "
             "ce qui rend la nuit habitée plutôt que muette — et ne refuse que "
             "la parole adressée. Le silence nocturne ne peut donc se décider "
             "qu'ici, seul endroit qui précède la dépense.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_TRAVAIL, order=26,
        description="Ce qui lui ouvre un chantier, et combien elle en mène de "
                    "front. Une pensée qui insiste ou une curiosité saillante "
                    "devient une amorce ; au-delà d'un certain désir, l'amorce "
                    "devient un travail qui persiste en base, décroît en temps "
                    "d'horloge, s'essouffle et finit par être abandonné. C'est "
                    "ce qui manquait pour qu'« aller au bout » veuille dire "
                    "quelque chose : aucun modèle ne portait un travail, donc "
                    "chaque cycle repartait de zéro.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_TRAVAIL_CAL, order=27, advanced=True,
        description="Les seuils fins de la récolte et de la poursuite. La "
                    "porte des amorces se lit CONTRE le plafond du chemin sans "
                    "LLM (0.55) : au-dessus, aucune observation ne peut ouvrir "
                    "de chantier ; trop bas, chaque message qu'on lui adresse "
                    "en ouvre un.",
    ),
    ConfigItem(
        key="conscience.travail.travaux_actifs_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL,
        label="Chantiers menés de front",
        default=2, min=0, max=20, hot_reload=True,
        hint="À 0, elle n'entreprend plus rien — les chantiers déjà ouverts "
             "continuent de vieillir et de s'abandonner.",
    ),
    ConfigItem(
        key="conscience.travail.ouverture_envie_min", type="float",
        section="conscience", group=_GROUPE_TRAVAIL,
        label="Désir minimal pour ouvrir un chantier",
        default=0.50, min=0.0, max=1.0, hot_reload=True,
        hint="Une amorce sous cette barre reste une amorce. Volontairement "
             "au-dessus du plafond d'une micro-rumination d'audit (0.425) : se "
             "repasser sa propre réponse ne doit pas ouvrir de chantier.",
    ),
    ConfigItem(
        key="conscience.travail.envie_demi_vie_s", type="float",
        section="conscience", group=_GROUPE_TRAVAIL,
        label="Demi-vie du désir (s)",
        default=6 * 3600.0, min=60.0, max=30 * 86400.0, hot_reload=True,
        hint="En temps d'horloge, sur une ancre qui n'avance qu'à l'écriture — "
             "même idiome que les pensées. Une décroissance par tour de boucle "
             "lierait la durée de vie d'une intention à la cadence du moteur, "
             "alors que tous ses lecteurs raisonnent en heures.",
    ),
    ConfigItem(
        key="conscience.travail.pas_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL,
        label="Pas maximum par chantier",
        default=5, min=1, max=100, hot_reload=True,
        hint="Un travail sans terme n'est pas un travail.",
    ),
    ConfigItem(
        key="conscience.travail.pas_intervalle_min_s", type="float",
        section="conscience", group=_GROUPE_TRAVAIL,
        label="Silence minimal entre deux pas (s)",
        default=1800.0, min=0.0, max=86400.0, hot_reload=True,
        hint="La boucle tourne toutes les 30 s : sans espacement, un chantier "
             "brûlerait tous ses pas en quelques minutes. Chaque pas est une "
             "boucle d'outils complète, muette : à 900 s et trois chantiers, "
             "jusqu'à douze appels par heure sans qu'on la voie travailler.",
    ),
    ConfigItem(
        key="conscience.travail.pas_par_heure_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL,
        label="Pas de chantier par heure, tous chantiers confondus",
        default=4, min=0, max=60, hot_reload=True,
        hint="Le vrai poste de coût de la vie intérieure : un pas est une "
             "boucle d'outils. Ce plafond borne l'heure quel que soit le "
             "nombre de chantiers ouverts ; un pas refusé attend le cycle "
             "suivant, rien n'est perdu. 1 ou 2 derrière un modèle local.",
    ),
    ConfigItem(
        key="conscience.travail.graine_obs_pertinence", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Pertinence d'une observation qui peut ouvrir un chantier",
        default=0.45, min=0.0, max=1.0, hot_reload=True,
        hint="Laisse passer un article RSS apparié (0.55) et refuse un message "
             "Telegram (0.40). Descendre sous 0.40 fait ouvrir un chantier à "
             "chaque phrase qu'on lui adresse.",
    ),
    ConfigItem(
        key="conscience.travail.graine_pensee_intensite", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Intensité d'une pensée qui peut ouvrir un chantier",
        default=0.40, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.travail.graine_pulsion_tension", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Tension d'une pulsion qui peut ouvrir un chantier",
        default=0.50, min=0.0, max=1.0, hot_reload=True,
        hint="Seules la curiosité et l'expression fécondent : le besoin de "
             "contact veut une personne, pas un chantier, et le repos ne veut "
             "rien entreprendre.",
    ),
    ConfigItem(
        key="conscience.travail.graines_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Amorces retenues par cycle",
        default=5, min=1, max=50, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.travail.envie_poursuite_min", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Désir sous lequel un chantier n'avance plus",
        default=0.25, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.travail.envie_plancher_abandon", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Désir sous lequel un chantier est abandonné",
        default=0.10, min=0.0, max=1.0, hot_reload=True,
        hint="Abandonné, pas supprimé : la ligne reste lisible à l'écran. "
             "L'inachevé est une information sur elle.",
    ),
    ConfigItem(
        key="conscience.travail.diffusion_notable_min", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Notabilité d'un résultat qui vaut d'être dit",
        default=0.80, min=0.0, max=1.0, hot_reload=True,
        hint="Un pas de chantier est muet par défaut : quatre travaux à cinq "
             "pas feraient vingt monologues par jour, et ceux-là passeraient "
             "HORS du frein quotidien des initiatives.",
    ),
    ConfigItem(
        key="conscience.travail.diffusion_intervalle_min_s", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Silence minimal entre deux annonces de chantier (s)",
        default=4 * 3600.0, min=0.0, max=86400.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.verdict.delai_defaut_s", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Délai retenu quand elle dit « attendre » sans préciser (s)",
        default=300.0, min=0.0, max=86400.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.verdict.delai_max_s", type="float",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Délai maximum qu'un verdict peut demander (s)",
        default=86400.0, min=1.0, max=30 * 86400.0, hot_reload=True,
        hint="Borne d'un lecteur face à une sortie de modèle : « reprends dans "
             "dix ans » se ramène ici.",
    ),
    ConfigItem(
        key="conscience.brief.observations_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Observations montrées au modèle par acte",
        default=5, min=0, max=50, hot_reload=True,
        hint="C'est aussi le nombre qui sera CLOS : l'acte ne marque comme "
             "traité que ce qu'il a mis sous les yeux. Le prompt en montrait "
             "cinq et l'acte en clôturait vingt.",
    ),
    ConfigItem(
        key="conscience.brief.include_scheduled_action", type="bool",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Traiter une action programmée par acte",
        default=True, hot_reload=True,
        hint="Une seule intention est réservée par acte pour attribuer correctement ses effets.",
    ),
    ConfigItem(
        key="conscience.scheduled.tentatives_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Tentatives d'une action programmée avant abandon",
        default=3, min=1, max=50, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.scheduled.reessai_s", type="int",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Délai avant de retenter une action programmée échouée (s)",
        default=300, min=0, max=86400, hot_reload=True,
        hint="Multiplié par le nombre de tentatives déjà faites. Pendant ce "
             "délai l'action n'est plus « due » : elle ne lève ni le cooldown "
             "ni le veto de sommeil. Sans lui, un rendez-vous prioritaire dont "
             "l'appel IA échoue était retenté à chaque cycle de 30 s.",
    ),
    ConfigItem(
        key="conscience.cycles_sautes_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Cycles sautés d'affilée avant de signaler un blocage",
        default=6, min=1, max=1000, hot_reload=True,
        hint="Un acte tient le verrou de décision jusqu'à ~135 s, soit quatre "
             "cycles : en sauter quelques-uns est normal. Au-delà, la boucle "
             "compte un échec — sinon « figée » et « en bonne santé » sont "
             "indiscernables sur l'écran fait pour les distinguer.",
    ),
    ConfigItem(
        key="conscience.travail.graines_modules_max", type="int",
        section="conscience", group=_GROUPE_TRAVAIL_CAL,
        label="Sujets retenus parmi ceux que les modules proposent",
        default=3, min=0, max=50, hot_reload=True,
        hint="Quand la curiosité est saillante, les modules qui ont quelque "
             "chose à offrir (articles non lus, par exemple) proposent des "
             "sujets — c'est ce qui donne un OBJET à une envie qui, sinon, ne "
             "pouvait que se redire. À 0, la curiosité retombe sur une amorce "
             "générique.",
    ),
    ConfigGroup(
        section="conscience", key=_GROUPE_PORTES, order=75, advanced=True,
        description="À partir de quelle pertinence un signal déclenche chacun "
                    "des mécanismes qui en dépendent. Ces portes se lisent "
                    "CONTRE le bloc précédent : le chemin sans LLM ne produit "
                    "au mieux que 0.55, et tant qu'une porte est au-dessus, "
                    "seul un e-mail — le seul signal payant un appel — peut la "
                    "franchir. C'est ainsi que six mécanismes sont restés "
                    "inertes en permanence sur une installation sans compte "
                    "mail : rien ne devenait une pensée, aucun souvenir n'était "
                    "ravivé, rien ne la réveillait entre deux cycles.",
    ),
    ConfigItem(
        key="conscience.promotion.rumination_pertinence", type="float",
        section="conscience", group=_GROUPE_PORTES,
        label="Pertinence qui fait d'une observation une pensée",
        default=0.45, min=0.0, max=1.0, hot_reload=True,
        hint="Une observation restée sans suite jusqu'à péremption, au moins "
             "aussi pertinente que cette valeur, devient une rumination.",
    ),
    ConfigItem(
        key="conscience.promotion.rumination_actives_max", type="int",
        section="conscience", group=_GROUPE_PORTES,
        label="Pensées actives au-delà desquelles on ne promeut plus",
        default=6, min=1, max=50, hot_reload=True,
        hint="Une pensée de plus n'est pas une pensée mieux pensée. Sans ce "
             "plafond, ouvrir la porte ci-dessus installe une pression "
             "permanente sur le facteur « ruminations ».",
    ),
    ConfigItem(
        key="conscience.maintenance.boost_pertinence", type="float",
        section="conscience", group=_GROUPE_PORTES,
        label="Pertinence qui ravive les souvenirs d'un thème",
        default=0.50, min=0.0, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.maintenance.contradiction_pertinence", type="float",
        section="conscience", group=_GROUPE_PORTES,
        label="Pertinence qui déclenche une vérification de cohérence",
        default=0.80, min=0.0, max=1.0, hot_reload=True,
        hint="Volontairement HAUTE, contrairement aux autres portes : cette "
             "branche coûte jusqu'à cinq appels IA, et seuls le chat et "
             "Telegram la visent.",
    ),
    ConfigItem(
        key="conscience.rumination_pressure_full", type="float",
        section="conscience", group=_GROUPE_PORTES,
        label="Somme d'intensités valant une pression pleine",
        default=2.5, min=0.01, max=20.0, hot_reload=True,
        hint="La pression des pensées est cette somme rapportée à 1.0. À 1.0, "
             "deux pensées à 0.5 saturaient déjà le facteur, qui cessait alors "
             "d'informer.",
    ),
    ConfigItem(
        key="conscience.sleep_wake_scheduled_priority", type="float",
        section="conscience", group=_GROUPE_PORTES,
        label="Priorité d'une action programmée qui vaut un réveil",
        default=0.8, min=0.0, max=1.0, hot_reload=True,
        hint="La nuit, une action programmée ne lève le veto de sommeil que si "
             "elle est au moins aussi prioritaire. Sans cette barre, un « pense "
             "à relire ce brouillon » la réveillait comme une urgence.",
    ),
    ConfigItem(
        key="conscience.suppress_release_idle_seconds", type="float",
        section="conscience", group=_GROUPE_PORTES,
        label="Inactivité en deçà de laquelle le frein quotidien se lève (s)",
        default=600.0, min=0.0, max=86400.0, hot_reload=True,
        hint="Le frein quotidien n'a aucune sortie propre : le compteur "
             "d'initiatives ignorées ne retombe qu'en agissant, ce que le frein "
             "interdit. Quelqu'un qui vient de parler est la seule preuve que "
             "le silence imposé n'a plus lieu d'être.",
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
        default=0.35, min=0.0, max=1.0, hot_reload=True,
        hint="Fraction de l'intensité de la rumination envoyée comme "
             "impulsion émotionnelle. À 1.0 une pensée tenace impose son "
             "émotion à l'humeur globale. À 0.15, un « je bloque » de 0.35 "
             "laissait un écart au repos de 7 % — invisible ; à 0.35, "
             "« à peine frustrée », lisible sans envahir.",
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
    ConfigItem(
        key="conscience.cooldown_jitter", type="float",
        section="conscience", group="Initiative",
        label="Gigue du silence entre deux initiatives (± fraction)",
        default=0.15, min=0.0, max=0.5, hot_reload=True,
        hint="Un métronome se remarque : à cadence exacte, ses relances "
             "tombent aux mêmes minutes. Tirée une fois par acte, jamais "
             "au-delà du plafond de six heures. À 0, cadence exacte.",
    ),
    ConfigItem(
        key="conscience.ennui.idle_minutes", type="int",
        section="conscience", group=_GROUPE_PENSEES,
        label="Minutes de vide avant que l'ennui la gagne",
        default=120, min=5, max=1440, hot_reload=True,
        hint="Rien à observer, aucun chantier en cours, personne depuis ce "
             "délai : son humeur glisse doucement vers l'ennui — le visage "
             "et le murmure prennent la couleur de ces après-midi-là, et "
             "l'envie d'ouvrir un chantier gagne une raison lisible.",
    ),
    ConfigItem(
        key="conscience.ennui.intensite", type="float",
        section="conscience", group=_GROUPE_PENSEES,
        label="Intensité du glissement vers l'ennui",
        default=0.2, min=0.0, max=1.0, hot_reload=True,
        hint="Une teinte, pas une crise : sous la porte de débordement "
             "d'humeur, l'ennui colore sans jamais forcer une prise de "
             "parole à lui seul. À 0, l'ennui n'existe pas. Dosé comme un "
             "état tenu — toutes les dix minutes — plutôt qu'en dents de "
             "scie : à 0.4 par demi-heure, l'écart retombait de 0.36 à 0.10 "
             "entre deux impulsions ; à 0.2 par dix minutes il se tient à "
             "~0.25, « légèrement lasse », et ne bouge plus.",
    ),
    ConfigGroup(
        section="conscience", key="Manque", order=21,
        description="Quand quelqu'un lui manque. Le silence se mesure au "
                    "rythme propre de chaque relation — la médiane des écarts "
                    "entre les jours où la personne écrit — jamais à un seuil "
                    "global : deux jours inquiètent pour un ami quotidien et "
                    "ne veulent rien dire pour un ami mensuel. Elle ne pense "
                    "qu'à UNE personne à la fois, préfère ceux dont elle est "
                    "proche et vers qui son fond affectif est chaud, et ne "
                    "relance jamais quelqu'un resté muet sans avoir attendu "
                    "bien plus longtemps.",
    ),
    ConfigItem(
        key="conscience.recontact_facteur", type="float",
        section="conscience", group="Manque",
        label="Silence ressenti comme un manque (× le rythme du lien)",
        default=1.5, min=0.1, max=10.0, hot_reload=True,
        hint="À 1.5, un ami qui écrit tous les 2 jours manque après 3 jours "
             "de silence. Monter la valeur la rend moins demandeuse.",
    ),
    ConfigItem(
        key="conscience.recontact_relance_facteur", type="float",
        section="conscience", group="Manque",
        label="Patience après une relance restée sans réponse (×)",
        default=3.0, min=1.0, max=20.0, hot_reload=True,
        hint="Si SON dernier message n'a pas eu de réponse, il faut ce "
             "multiple de silence en plus avant de re-proposer la personne : "
             "elle re-tente après un vrai moment, elle ne double-texte pas.",
    ),
    ConfigItem(
        key="conscience.recontact_rythme_ami_jours", type="int",
        section="conscience", group="Manque",
        label="Rythme supposé d'un ami sans historique (jours)",
        default=7, min=1, max=365, hot_reload=True,
        hint="Sert de repli tant que la relation n'a pas trois jours actifs "
             "d'historique — ensuite le rythme mesuré prend le dessus.",
    ),
    ConfigItem(
        key="conscience.recontact_rythme_proche_jours", type="int",
        section="conscience", group="Manque",
        label="Rythme supposé d'un proche sans historique (jours)",
        default=3, min=1, max=365, hot_reload=True,
        hint="Un proche manque plus vite qu'un ami : même repli, plus court.",
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
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        hint="En dessous, l'observation la plus pertinente ne contribue pas. "
             "Le chemin sans LLM plafonne à 0,55, relevé jusqu'à 0,63 quand "
             "le signal va dans le sens de son humeur : à 0,7 ce facteur ne "
             "vivait que par un compte mail ; à 0,6, un titre qui résonne "
             "avec ce qu'elle ressent compte, un titre banal non.",
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
        key="conscience.factor.urgency_observation_gate", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F2 · Urgence accumulée : pertinence minimale d'une observation",
        default=0.3, min=0.0, max=1.0, hot_reload=True,
        hint="Une observation ne compte dans la somme que si elle DÉPASSE "
             "cette valeur, strictement. Au défaut, un message de chat — dont "
             "la pertinence sans LLM vaut exactement 0.3 — pèse donc "
             "rigoureusement zéro dans ce facteur.",
    ),
    ConfigItem(
        key="conscience.factor.urgency_per_observation", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F2 · Urgence accumulée : poids d'une observation dans la somme",
        default=0.5, min=0.0, max=2.0, hot_reload=True,
        hint="Chaque observation retenue apporte sa pertinence multipliée par "
             "cette valeur. À ne pas confondre avec « poids » ci-dessus, qui "
             "convertit la somme obtenue en points de score.",
    ),
    ConfigItem(
        key="conscience.factor.mood_gate", type="float",
        section="conscience", group=_GROUPE_FACTEURS,
        label="F3 · Débordement d'humeur : seuil d'entrée",
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        hint="Écart de l'humeur globale à son repos, rapporté à l'émotion "
             "vers laquelle elle a dérivé, au-delà duquel elle a quelque chose "
             "de non exprimé. Au repos l'écart vaut 0 (il lisait 0.4–0.5 "
             "quand la porte comparait la position absolue, d'où l'ancien "
             "0.7) ; à 0.6, trois tours « sad 0.8 » de quelqu'un la "
             "franchissent, une joie ordinaire non.",
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
        default=1, min=1, max=100, hot_reload=True,
        hint="À 2, la toute première initiative restée sans réponse ne coûtait "
             "rien : elle relançait au délai nominal, et les trois premiers "
             "actes de la journée tombaient en une demi-heure. Le backoff du "
             "délai, lui, comptait déjà dès la première — les deux moitiés du "
             "même mécanisme ne partaient pas au même moment.",
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
        default=0.55, min=0.0, max=1.0, hot_reload=True,
        hint="Seule pertinence de ce bloc qui porte un intérêt APPARIÉ : "
             "l'article touche un thème qu'elle suit. C'est aussi le plafond "
             "de tout le chemin sans LLM — les portes du bloc « Portes de "
             "pertinence » se règlent en dessous, sinon elles sont "
             "inatteignables sur une installation sans compte mail.",
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
        default=20, min=1, max=1440, hot_reload=True,
        hint="Au-delà, l'initiative est comptée comme ignorée — ce qui "
             "allonge le cooldown et pèse au facteur 8. Un humain ne se vexe "
             "pas d'une réponse à douze minutes : 10 comptait « ignorée » la "
             "plupart des réponses réelles.",
    ),
    ConfigItem(
        key="conscience.ignored_reply_window_telegram_factor", type="float",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Multiplicateur du délai sur Telegram",
        default=3.0, min=1.0, max=20.0, hot_reload=True,
        hint="Un message Telegram se lit quand on y pense, pas quand il "
             "arrive : le délai avant de compter une initiative ignorée y est "
             "multiplié par ce facteur.",
    ),
    ConfigItem(
        key="conscience.inactivite_restauree_max_seconds", type="int",
        section="conscience", group=_GROUPE_ENTRETIEN,
        label="Inactivité maximale restaurée au démarrage (s)",
        default=72 * 3600, min=0, max=30 * 86400, restart_required=True,
        hint="Au démarrage, le silence est relu sur le dernier message d'une "
             "vraie personne, plafonné à ceci : après une semaine d'arrêt, "
             "elle ne doit pas se réveiller avec sept jours de manque d'un "
             "coup. Lue par le moteur mais non déclarée jusqu'ici.",
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
    ConfigItem(
        key="conscience.audit.espacement_s", type="int",
        section="conscience", group=_GROUPE_AUDIT,
        label="Espacement entre deux audits pour une même personne (s)",
        default=1800, min=0, max=86400, hot_reload=True,
        hint="Un audit par personne par fenêtre. Sans lui, chaque réponse "
             "chargée d'une conversation animée écrivait sa pensée, et le "
             "facteur « ruminations » restait à son plafond pendant des heures.",
    ),
    ConfigItem(
        key="conscience.audit.actives_max", type="int",
        section="conscience", group=_GROUPE_AUDIT,
        label="Micro-ruminations d'audit actives au maximum",
        default=3, min=1, max=20, hot_reload=True,
        hint="Au-delà, la plus faible se fane avant que la nouvelle ne "
             "s'écrive : la dernière réponse est celle qu'on se rejoue.",
    ),
]
