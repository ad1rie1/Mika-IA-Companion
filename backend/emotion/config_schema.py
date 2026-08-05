"""Config schema for the emotion engine."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

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

CONFIG_SCHEMA = [
    ConfigSection(
        key="emotion", label="Émotion", icon="❋", order=40,
        description=(
            "Tempérament du personnage, snapshots, rétention."
        ),
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
]
