"""Schéma de configuration du module Réveil.

Le module n'en avait aucun : sa seule constante opérationnelle, la cadence à
laquelle il relève les demandes de réveil en attente, était un littéral, et
son espace de configuration dans le tableau de bord restait vide. Rien ne
distinguait « ce module n'a rien à régler » de « ses réglages ne sont pas
exposés ».

``MAX_WAKES_PER_TICK`` reste en dur volontairement : trois tours de pipeline
en série, c'est déjà jusqu'à six minutes de provider monopolisées au
détriment de la conversation en cours, et le reste du lot repart au tick
suivant — ce n'est pas un plafond qu'on règle, c'est une file qui s'écoule.
"""
from __future__ import annotations

from old.backend.configs.types import ConfigGroup, ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_wake", label="Modules · Réveil", icon="☼", order=72,
        family="systeme",
        summary="Le délai entre « réveille-la » et « elle parle ».",
        description=(
            "Messages spontanés déclenchés par une demande de réveil (cron "
            "ou API). Chaque demande traitée est un tour de pipeline complet."
        ),
    ),
    ConfigGroup(
        section="module_wake", key="Relevé", order=10,
        description="La cadence à laquelle les demandes de réveil en attente "
                    "sont relevées. Elle ne décide pas de la fréquence à "
                    "laquelle Mika parle — c'est le cron ou l'API qui la "
                    "décide — seulement de la latence entre la demande et le "
                    "tour de pipeline qu'elle déclenche.",
    ),
    ConfigItem(
        key="wake.check_interval_s", type="int", section="module_wake",
        group="Relevé", label="Intervalle de relevé (s)",
        default=30, min=5, max=3600, hot_reload=True,
        description=(
            "Cadence à laquelle les demandes de réveil en attente sont "
            "relevées. Une demande arrivée juste après un tour attend au pire "
            "cet intervalle : c'est le délai entre « réveille-la » et « elle "
            "parle », pas la fréquence à laquelle elle parle."
        ),
    ),
]
