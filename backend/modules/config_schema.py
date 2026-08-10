"""Cross-cutting module infrastructure settings.

Module-specific settings live in each module's ``config_schema()``
class method so they stay co-located with the code that consumes them.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="modules_runtime", label="Modules · Runtime", icon="▦", order=70,
        description=(
            "Planificateur cron partagé par tous les modules, bus "
            "d'événements, et registre des dégradations."
        ),
    ),
    ConfigItem(
        key="modules.cron_tick_interval", type="int", section="modules_runtime",
        label="Tick scheduler (s)",
        default=60, min=1, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="modules.event_handler_timeout_s", type="int",
        section="modules_runtime", label="Timeout d'un abonné au bus (s)",
        default=0, min=0, max=600, restart_required=True,
        description=(
            "Un module abonné en mode « await » fait attendre l'émetteur le "
            "temps de son on_event ; sans borne, un handler qui reste bloqué "
            "bloque l'émetteur avec lui, indéfiniment. "
            "0 = illimité, le comportement historique — c'est la valeur "
            "d'usine, et aucun module ne déclare de délai propre, donc tout "
            "le bus tourne aujourd'hui sans échéance. "
            "Un module qui déclare son propre EVENT_TIMEOUT garde le sien : "
            "ce réglage ne s'applique qu'aux autres. L'abonnement est posé au "
            "démarrage du module, d'où le redémarrage nécessaire."
        ),
    ),
    ConfigItem(
        key="modules.degradation_max_labels", type="int",
        section="modules_runtime", label="Sites de dégradation suivis",
        default=256, min=32, max=10000, hot_reload=True,
        description=(
            "Le registre des dégradations compte les échecs avalés, un "
            "compteur par site. Ce plafond existe pour qu'une étiquette bâtie "
            "par erreur à partir d'une donnée d'entrée ne le fasse pas "
            "grossir sans fin — mais au-delà, un site *nouveau* est "
            "silencieusement ignoré, c'est-à-dire exactement l'aveuglement "
            "que le registre existe pour supprimer. Le monter si "
            "/gestion/systeme/sante/ affiche un nombre de sites collé au "
            "plafond."
        ),
    ),
]
