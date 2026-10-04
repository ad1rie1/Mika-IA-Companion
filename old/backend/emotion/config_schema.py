"""Config schema for the emotion engine."""
from __future__ import annotations

from old.backend.configs.types import ConfigGroup, ConfigItem, ConfigSection

# Les 29 émotions en couples ``(valeur, libellé)``. La valeur stockée reste le
# nom canonique de ``emotion/types.py`` — c'est lui que le modèle produit dans
# sa balise ``[EMOTION:...]`` et lui qui compose la variable CSS — mais une
# liste déroulante en français ne peut pas proposer « mischievous ».
#
# La table est recopiée ici plutôt qu'importée d'``emotion.types`` +
# ``GestionSysteme.formatting`` : ce module est chargé pour construire le
# registre, avant que les applications Django ne soient prêtes, et il ne doit
# dépendre de rien. Un test vérifie qu'elle couvre exactement les 29 émotions.
MOOD_CHOICES: tuple[tuple[str, str], ...] = (
    ("neutral", "neutre"),
    ("happy", "contente"),
    ("excited", "excitée"),
    ("love", "amoureuse"),
    ("proud", "fière"),
    ("grateful", "reconnaissante"),
    ("playful", "joueuse"),
    ("amused", "amusée"),
    ("hopeful", "pleine d'espoir"),
    ("relieved", "soulagée"),
    ("sad", "triste"),
    ("angry", "en colère"),
    ("scared", "effrayée"),
    ("disgusted", "dégoûtée"),
    ("frustrated", "frustrée"),
    ("lonely", "seule"),
    ("anxious", "anxieuse"),
    ("bored", "s'ennuie"),
    ("jealous", "jalouse"),
    ("surprised", "surprise"),
    ("thinking", "pensive"),
    ("confused", "confuse"),
    ("embarrassed", "gênée"),
    ("nostalgic", "nostalgique"),
    ("dreamy", "rêveuse"),
    ("determined", "déterminée"),
    ("mischievous", "malicieuse"),
    ("curious", "curieuse"),
    ("melancholic", "mélancolique"),
)

# Le tempérament vivait dans ``personality.yaml``, en lecture seule sur la page
# « Vie intérieure » : cinq nombres qui décident du point de repos de
# l'oscillateur et de sa façon d'y revenir, affichés à côté de l'humeur qu'ils
# gouvernent, mais modifiables uniquement en éditant un fichier puis en
# redémarrant. Ils sont ici, hors du YAML — pas *aussi* ici : deux défauts
# déclarés pour un même réglage, c'est exactement ce que le retrait du pont
# ``env_fallback`` a coûté à ranger.
TEMPERAMENT_GROUP = "Tempérament"

# Les groupes des réglages rapatriés depuis le code. Chaque constante reste
# déclarée dans son module et sert de repli : ce qui change ici, c'est
# l'ORIGINE de la valeur, jamais la robustesse du site de lecture (cf.
# ``configs/runtime.py``). Un défaut ci-dessous vaut donc exactement la
# constante correspondante — une installation neuve se comporte à l'identique.
OSC_GROUP = "Oscillateur"
DIFFUSION_GROUP = "Diffusion"
ANCRAGE_GROUP = "Ancrage relationnel"
DERIVE_GROUP = "Dérive spontanée"
GLOBALE_GROUP = "Humeur globale"

DYNAMIQUE_GROUP = "Dynamique"

CONFIG_SCHEMA = [
    ConfigSection(
        key="emotion", label="Émotion", icon="❋", order=40,
        family="vie_interieure",
        summary="Son tempérament, et la physique qui la ramène à son humeur de fond.",
        description=(
            "Tempérament du personnage, snapshots, rétention."
        ),
    ),
    # ── Organisation de l'écran ─────────────────────────────────────
    #
    # Deux blocs se règlent en regardant Mika vivre — le tempérament et les
    # cadences —, les cinq autres sont la calibration de l'oscillateur PAD :
    # des nombres qui n'ont de sens que rapportés les uns aux autres, et dont
    # trois portent un invariant écrit noir sur blanc. Ils restent ouvrables,
    # cherchables et modifiables, mais repliés : on ne tombe pas dessus en
    # venant changer une humeur par défaut.
    ConfigGroup(
        section="emotion", key=TEMPERAMENT_GROUP, order=10,
        description="Le caractère de fond : vers quelle émotion elle revient, "
                    "avec quelle amplitude elle réagit, à quelle vitesse elle "
                    "encaisse. Cinq curseurs qu'on essaie en regardant l'humeur "
                    "bouger — tous appliqués sans redémarrage.",
    ),
    ConfigGroup(
        section="emotion", key=DYNAMIQUE_GROUP, order=20,
        description="Les cadences : à quel rythme l'état est relevé en base et "
                    "poussé vers l'avatar entre deux répliques, et combien de "
                    "temps on garde ces relevés. Sans cette poussée, le visage "
                    "resterait figé sur la dernière phrase dite.",
    ),
    ConfigGroup(
        section="emotion", key=OSC_GROUP, order=30, advanced=True,
        description="La physique elle-même : constantes de temps du retour au "
                    "repos, gain d'une impulsion, composition du point de repos. "
                    "Descendre les deux constantes sous la durée d'un tour "
                    "(30–120 s) fait disparaître l'émotion d'un tour avant le "
                    "suivant — prompt, relevé et gestes reliraient tous le repos.",
    ),
    ConfigGroup(
        section="emotion", key=DIFFUSION_GROUP, order=40, advanced=True,
        description="Ce qui déteint de sa stance envers une personne sur son "
                    "humeur de fond, et à quelle vitesse celle-ci retombe. "
                    "Trois clés y portent un invariant : plancher + pente doit "
                    "valoir le facteur maximal (0.4 + 1.6 = 2.0), sinon le "
                    "plafond mord avant l'intensité 1.0 ou reste hors d'atteinte.",
    ),
    ConfigGroup(
        section="emotion", key=ANCRAGE_GROUP, order=50, advanced=True,
        description="Ce qui distingue un ami d'un troll : le point de repos "
                    "qu'elle finit par avoir envers quelqu'un, comment il "
                    "s'apprend et comment il cicatrise. La lenteur de "
                    "l'apprentissage devant la guérison est ce qui donne à la "
                    "fois de l'attachement et de la rancune.",
    ),
    ConfigGroup(
        section="emotion", key=DERIVE_GROUP, order=60, advanced=True,
        description="La petite dérive au hasard qui empêche une Mika inactive "
                    "de tenir exactement son point de repos. Réservée à l'humeur "
                    "globale ; trop fréquente, les dérives se composent en marche "
                    "aléatoire visible au lieu d'un frémissement.",
    ),
    ConfigGroup(
        section="emotion", key=GLOBALE_GROUP, order=70, advanced=True,
        description="Comment son état se raconte dans le prompt : à partir de "
                    "quelle intensité c'est « nettement plus que d'habitude », et "
                    "combien de temps la balise [EMOTION:] qu'elle vient d'écrire "
                    "prime sur la position de l'oscillateur pour dire ce qu'elle "
                    "éprouve.",
    ),
    ConfigItem(
        key="emotion.temperament.default_mood", type="select", section="emotion",
        group=TEMPERAMENT_GROUP, label="Humeur par défaut",
        description=(
            "Point de repos de l'oscillateur : l'émotion vers laquelle elle "
            "revient une fois le stimulus passé."
        ),
        choices=MOOD_CHOICES, default="happy", hot_reload=True,
    ),
    ConfigItem(
        key="emotion.temperament.volatility", type="float", section="emotion",
        group=TEMPERAMENT_GROUP, label="Volatilité",
        description=(
            "Amplitude de réaction à un stimulus. Haut = elle part au quart "
            "de tour ; bas = il en faut beaucoup pour la faire bouger."
        ),
        default=0.7, min=0.05, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="emotion.temperament.intensity_base", type="float", section="emotion",
        group=TEMPERAMENT_GROUP, label="Intensité de base",
        description="Gain appliqué à chaque impulsion émotionnelle.",
        default=0.6, min=0.1, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="emotion.temperament.recovery_speed", type="float", section="emotion",
        group=TEMPERAMENT_GROUP, label="Vitesse de récupération",
        description=(
            "Raideur du ressort qui la ramène à son humeur par défaut. "
            "Haut = elle encaisse et repart vite."
        ),
        default=0.5, min=0.05, max=1.0, hot_reload=True,
    ),
    ConfigItem(
        key="emotion.temperament.global_bleed", type="float", section="emotion",
        group=TEMPERAMENT_GROUP, label="Diffusion globale",
        description=(
            "Part de ce qu'elle ressent envers une personne qui déteint sur "
            "son humeur de fond. À 0 elle compartimente entièrement."
        ),
        default=0.3, min=0.0, max=1.0, hot_reload=True,
    ),
    # Pas de curseur « décroissance/seconde » ici : la décroissance émotionnelle
    # n'est pas un taux, c'est la physique de l'oscillateur. Masse, raideur et
    # amortissement sont dérivés du tempérament par ``_recompute_params`` et
    # intégrés par ``dynamics.py`` — c'est « Vitesse de récupération » qu'on
    # règle pour la faire revenir plus ou moins vite à son humeur de fond.
    ConfigItem(
        key="emotion.snapshot_interval", type="int", section="emotion",
        group="Dynamique", label="Intervalle snapshot (s)",
        default=30, min=5, max=600, hot_reload=True,
    ),
    ConfigItem(
        key="emotion.sync_interval", type="float", section="emotion",
        group="Dynamique", label="Rafraîchissement frontend (s)",
        description=(
            "Cadence à laquelle l'état émotionnel courant est poussé vers "
            "l'avatar entre deux répliques. Une trame ne part que si "
            "l'émotion a réellement bougé."
        ),
        default=3.0, min=0.5, max=60.0,
    ),
    ConfigItem(
        key="emotion.snapshot_retention_days", type="int", section="emotion",
        group="Dynamique", label="Rétention snapshots (jours)",
        default=2, min=1, max=90,
    ),
    ConfigItem(
        key="emotion.summary_retention_days", type="int", section="emotion",
        group="Dynamique", label="Portée des résumés quotidiens (jours)",
        default=30, min=1, max=3650, hot_reload=True,
        hint="Repli quand les relevés ont été purgés : au-delà de cet âge un "
             "``EmotionalSummary`` ne produit plus aucune humeur, et entre "
             "les deux il n'en produit qu'une fraction (l'intensité décroît "
             "linéairement jusqu'à ce seuil).",
    ),
    ConfigItem(
        key="emotion.idle_eviction_seconds", type="int", section="emotion",
        group="Dynamique", label="Sortie de RAM d'une humeur inactive (s)",
        default=3600, min=60, max=604800, hot_reload=True,
        hint="Une humeur sans message depuis ce délai ET revenue à son repos "
             "quitte la mémoire vive — jamais la base. Une connexion vivante "
             "protège toujours son oscillateur.",
    ),
    ConfigItem(
        key="emotion.sync_min_intensity_delta", type="float", section="emotion",
        group="Dynamique", label="Écart minimal pour repousser une trame",
        default=0.04, min=0.0, max=1.0, hot_reload=True,
        hint="En dessous, un nouveau rendu afficherait le même pourcentage "
             "arrondi et bougerait les blend shapes de moins que la "
             "respiration. À 0.0 une trame part à chaque tick.",
    ),

    # ── Oscillateur ────────────────────────────────────────────────
    ConfigItem(
        key="emotion.person_tau_fast", type="float", section="emotion",
        group=OSC_GROUP, label="Constante de temps la plus rapide (s)",
        default=240.0, min=10.0, max=3600.0, hot_reload=True,
        hint="Bout « rapide » du curseur Vitesse de récupération : τ à 1.0. "
             "L'interpolation entre les deux bornes est géométrique.",
    ),
    ConfigItem(
        key="emotion.person_tau_slow", type="float", section="emotion",
        group=OSC_GROUP, label="Constante de temps la plus lente (s)",
        default=1800.0, min=30.0, max=86400.0, hot_reload=True,
        hint="Bout « lent » du curseur, τ à 0.05. Doit rester au-dessus de la "
             "constante rapide. Descendre les deux sous la durée d'un tour "
             "(30–120 s) fait disparaître l'émotion d'un tour avant le "
             "suivant : prompt, relevé, fiche affect et gestes reliraient "
             "tous le repos.",
    ),
    ConfigItem(
        key="emotion.ratchet_base", type="float", section="emotion",
        group=OSC_GROUP, label="Gain de base d'une impulsion",
        default=1.0, min=0.05, max=2.0, hot_reload=True,
        hint="Une impulsion est un cliquet : elle parcourt une fraction de ce "
             "qui reste jusqu'à l'ancre déclarée, donc elle ne peut jamais la "
             "dépasser. Ce gain est ensuite modulé par le tempérament.",
    ),
    ConfigItem(
        key="emotion.resonance_strength", type="float", section="emotion",
        group=OSC_GROUP, label="Résonance avec le fond du tempérament",
        default=0.45, min=0.0, max=2.0, hot_reload=True,
        hint="Une émotion alignée sur l'humeur par défaut du personnage frappe "
             "plus fort : gain × (1 + k·cos), amplification seulement — les "
             "émotions contraires ne sont jamais atténuées. À 0, un "
             "mélancolique ne vibre pas plus à la tristesse qu'un neutre.",
    ),
    ConfigItem(
        key="emotion.ratchet_max", type="float", section="emotion",
        group=OSC_GROUP, label="Plafond du gain d'impulsion",
        default=0.75, min=0.05, max=1.0, hot_reload=True,
        hint="À 1.0 une seule réplique la poserait exactement sur l'émotion "
             "déclarée, sans aucune inertie relationnelle.",
    ),
    ConfigItem(
        key="emotion.max_advance_seconds", type="float", section="emotion",
        group=OSC_GROUP, label="Rattrapage maximal en une passe (s)",
        default=10800.0, min=60.0, max=86400.0, hot_reload=True,
        hint="Temps simulé maximal qu'une passe d'intégration rattrape. "
             "L'ancienne borne de 30 s était invisible tant que τ valait ~7 s "
             "mais figeait l'état d'une machine sortie de veille ; à 1 h, une "
             "hibernation de cinq heures laissait encore 17 % de l'écart au "
             "fond. Au-delà de dix constantes de temps, la passe pose "
             "directement le repos.",
    ),
    ConfigItem(
        key="emotion.home_default_mood_weight", type="float", section="emotion",
        group=OSC_GROUP, label="Poids de l'humeur par défaut au repos",
        default=0.15, min=0.0, max=1.0, hot_reload=True,
        hint="Le point de repos vaut « humeur par défaut × ce poids + teinte "
             "circadienne ». Volontairement petit : le personnage doit rester "
             "reconnaissable sans écraser les impulsions du moment.",
    ),
    ConfigItem(
        key="emotion.circadian_bias_magnitude", type="float", section="emotion",
        group=OSC_GROUP, label="Teinte circadienne du repos",
        default=0.35, min=0.0, max=1.0, hot_reload=True,
        hint="Amplitude de la teinte que l'heure donne au point de repos "
             "(matin plein d'espoir, nuit rêveuse). À 0.0 les journées de "
             "Mika n'ont plus de couleur.",
    ),

    # ── Diffusion vers l'humeur de fond ────────────────────────────
    ConfigItem(
        key="emotion.global_tau_factor", type="float", section="emotion",
        group=DIFFUSION_GROUP, label="Paresse de l'humeur globale (×τ)",
        default=2.0, min=1.0, max=10.0, hot_reload=True,
        hint="L'humeur de fond met ce multiple du temps d'une stance "
             "personnelle à revenir au repos.",
    ),
    ConfigItem(
        key="emotion.ratchet_global", type="float", section="emotion",
        group=DIFFUSION_GROUP, label="Gain d'impulsion vers l'humeur globale",
        default=0.45, min=0.0, max=1.0, hot_reload=True,
        hint="Multiplié par « Diffusion globale » du tempérament, qui promet "
             "« à 0 elle compartimente entièrement » — d'où un gain relatif, "
             "jamais un plancher absolu.",
    ),
    ConfigItem(
        key="emotion.global_ratchet_max", type="float", section="emotion",
        group=DIFFUSION_GROUP, label="Plafond du gain global",
        default=0.5, min=0.0, max=1.0, hot_reload=True,
        hint="Garde contre un tempérament très perméable. Ce plafond "
             "s'applique en DEUX endroits — au calcul des paramètres globaux "
             "et à la modulation par l'intensité déclarée — et les deux "
             "lisent cette même clé : c'est ce qui les empêche de diverger.",
    ),
    ConfigItem(
        key="emotion.global_gain_floor", type="float", section="emotion",
        group=DIFFUSION_GROUP, label="Plancher de modulation par l'intensité",
        default=0.4, min=0.0, max=2.0, hot_reload=True,
        hint="gain_effectif = gain_base × (plancher + pente × intensité), "
             "plafonné. INVARIANT : plancher + pente = « facteur maximal » "
             "(0.4 + 1.6 = 2.0), sinon le plafond mord avant l'intensité "
             "1.0 ou reste hors d'atteinte.",
    ),
    ConfigItem(
        key="emotion.global_gain_slope", type="float", section="emotion",
        group=DIFFUSION_GROUP, label="Pente de modulation par l'intensité",
        default=1.6, min=0.0, max=4.0, hot_reload=True,
        hint="À 0.2 d'intensité une émotion effleure l'humeur de fond, à 1.0 "
             "elle la traverse. INVARIANT : plancher + pente = facteur "
             "maximal (0.4 + 1.6 = 2.0).",
    ),
    ConfigItem(
        key="emotion.global_gain_max_factor", type="float", section="emotion",
        group=DIFFUSION_GROUP, label="Facteur maximal de modulation",
        default=2.0, min=1.0, max=4.0, hot_reload=True,
        hint="Ce que peut valoir le gain global au maximum, relativement au "
             "gain de base. INVARIANT : doit valoir plancher + pente "
             "(0.4 + 1.6 = 2.0).",
    ),

    # ── Ancrage relationnel ────────────────────────────────────────
    ConfigItem(
        key="emotion.person_anchor_weight", type="float", section="emotion",
        group=ANCRAGE_GROUP, label="Part de l'ancre dans le repos personnel",
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        hint="Le reste vient du repos circadien commun. À 0.0 un ami, un "
             "troll et un inconnu reviennent tous exactement au même point.",
    ),
    ConfigItem(
        key="emotion.anchor_max_norm", type="float", section="emotion",
        group=ANCRAGE_GROUP, label="Norme maximale d'une ancre",
        default=0.7, min=0.0, max=1.5, hot_reload=True,
        hint="Une stance envers quelqu'un reste un point de repos, pas une "
             "émotion permanente à pleine intensité.",
    ),
    ConfigItem(
        key="emotion.anchor_alpha", type="float", section="emotion",
        group=ANCRAGE_GROUP, label="Vitesse d'apprentissage de l'ancre",
        default=0.15, min=0.01, max=1.0, hot_reload=True,
        hint="Part du dernier relevé fondue dans l'ancre. Volontairement lent "
             "devant les mots : c'est ce rapport avec la guérison qui donne à "
             "la fois de l'attachement et de la rancune.",
    ),
    ConfigItem(
        key="emotion.anchor_sample", type="int", section="emotion",
        group=ANCRAGE_GROUP, label="Relevés relus pour reconstruire une ancre",
        default=20, min=1, max=200, hot_reload=True,
        hint="Moyenne pondérée par la récence, relue à la réhydratation d'une "
             "humeur sortie de RAM.",
    ),
    ConfigItem(
        key="emotion.anchor_heal_half_life_days", type="float", section="emotion",
        group=ANCRAGE_GROUP, label="Demi-vie de la guérison d'une stance (j)",
        default=3.0, min=0.05, max=365.0, hot_reload=True,
        hint="Temps qu'il faut, SANS aucun échange, pour que l'ancre ait fait "
             "la moitié du chemin vers le repos commun. Trois jours : une "
             "brouille du lundi est encore lisible le mercredi, oubliée la "
             "semaine suivante. Très haut = une rancune que seule une "
             "vingtaine de tours chaleureux peut défaire.",
    ),
    ConfigItem(
        key="emotion.anchored_min_norm", type="float", section="emotion",
        group=ANCRAGE_GROUP, label="Intensité minimale d'une stance « ancrée »",
        default=0.4, min=0.0, max=1.5, hot_reload=True,
        hint="En dessous, le prompt ne dit pas « cette émotion est bien "
             "ancrée ».",
    ),
    ConfigItem(
        key="emotion.anchored_min_impulses", type="int", section="emotion",
        group=ANCRAGE_GROUP, label="Impulsions concordantes requises",
        default=2, min=1, max=20, hot_reload=True,
        hint="Une stance construite, pas déclenchée une fois.",
    ),
    ConfigItem(
        key="emotion.anchored_window_seconds", type="float", section="emotion",
        group=ANCRAGE_GROUP, label="Fenêtre de comptage des impulsions (s)",
        default=900.0, min=30.0, max=86400.0, hot_reload=True,
    ),

    # ── Dérive spontanée ───────────────────────────────────────────
    ConfigItem(
        key="emotion.spontaneous_nudge_probability", type="float",
        section="emotion", group=DERIVE_GROUP,
        label="Probabilité d'une dérive par tick",
        default=0.004, min=0.0, max=1.0, hot_reload=True,
        hint="Sans cela, une Mika reposée et inactive tient exactement son "
             "point de repos — pas un humain. Le tick vaut 1 s et une dérive "
             "vit maintenant ~τ (des minutes) : à l'ancienne cadence, dix "
             "fois plus haute, elles se composaient en marche aléatoire "
             "visible.",
    ),
    ConfigItem(
        key="emotion.spontaneous_nudge_max", type="float", section="emotion",
        group=DERIVE_GROUP, label="Amplitude maximale d'une dérive (PAD)",
        default=0.05, min=0.0, max=1.0, hot_reload=True,
        hint="Réservé à l'humeur globale : une stance envers quelqu'un est "
             "toujours réactive, jamais spontanée.",
    ),

    # ── Humeur globale ─────────────────────────────────────────────
    ConfigItem(
        key="emotion.marked_intensity", type="float", section="emotion",
        group=GLOBALE_GROUP, label="Seuil « nettement plus que d'habitude »",
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        hint="Au-delà, l'humeur ne se lit plus « dans la pente naturelle » du "
             "personnage : le prompt le dit.",
    ),
    ConfigItem(
        key="emotion.declared_window_seconds", type="float", section="emotion",
        group=GLOBALE_GROUP, label="Fraîcheur d'une émotion déclarée (s)",
        default=1200.0, min=0.0, max=86400.0, hot_reload=True,
        hint="Pendant ce délai, ce qu'elle vient de déclarer dans sa balise "
             "[EMOTION:] prime sur la position de l'oscillateur pour dire ce "
             "qu'elle éprouve. Vingt minutes : le temps réel du retour au "
             "repos (le vrai 1/e est ~950 s, le repos à ~20 min). À 700 s, "
             "la fenêtre lâchait pendant que la position lisait encore une "
             "troisième émotion (« determined » après une colère).",
    ),
]
