"""Config schema for the conscience engine."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="conscience", label="Conscience", icon="◉", order=50,
        description="Boucle de décision, seuil d'action, cooldown.",
    ),
    ConfigItem(
        key="conscience.decision_interval", type="int", section="conscience",
        label="Intervalle décision (s)",
        default=30, min=5, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="conscience.cooldown_seconds", type="int", section="conscience",
        label="Cooldown entre actions (s)",
        default=300, min=0, max=86400, hot_reload=True,
    ),
    ConfigItem(
        key="conscience.act_threshold", type="float", section="conscience",
        label="Seuil score → agir",
        default=0.5, min=0.0, max=1.0, hot_reload=True,
        hint="Plus haut = Mika parle moins spontanément.",
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
        key="conscience.ignored_backoff_factor", type="float",
        section="conscience", group="Initiative",
        label="Espacement après une relance sans réponse (×)",
        default=2.5, min=1.0, max=10.0, hot_reload=True,
        hint="Le cooldown est multiplié par ce facteur à chaque initiative "
             "restée sans réponse. À 1.0 elle relance toujours au même rythme "
             "— c'est ce qui produisait cinq messages en vingt minutes.",
    ),
]
