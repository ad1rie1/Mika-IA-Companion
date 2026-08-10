"""Config schema for the projects subsystem."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="projects", label="Projets", icon="◱", order=60,
        description="Runner des projets agent.",
    ),
    ConfigItem(
        key="projects.prompt_history_size", type="int", section="projects",
        label="Buffer prompt history",
        default=30, min=0, max=500,
        hint="0 = désactive la capture prompt/response.",
    ),
    ConfigItem(
        key="projects.runner_interval", type="int", section="projects",
        label="Période runner (s)",
        default=30, min=5, max=600, restart_required=True,
        hint="Cadence de la boucle dédiée qui fait avancer les projets dus. "
             "Découplée du consolidator — un interval:30s tient vraiment 30s.",
    ),
    ConfigItem(
        key="projects.max_advances_per_tick", type="int", section="projects",
        label="Projets avancés par tick",
        default=3, min=1, max=20, hot_reload=True,
        hint=(
            "Garde-fou anti-rafale : si une douzaine de projets arrivent à "
            "échéance en même temps, seuls les N premiers (par priorité) "
            "avancent, les autres attendent le tick suivant. Chaque avance "
            "coûte un appel LLM complet."
        ),
    ),
    ConfigItem(
        key="projects.llm_timeout_seconds", type="int", section="projects",
        label="Timeout d'une avance (s)",
        default=90, min=5, max=600, hot_reload=True,
        hint=(
            "Second plafond, plus serré : `ai.call_timeout_seconds` (120 s "
            "par défaut) borne déjà le même appel depuis l'intérieur du "
            "routeur. Le mettre au-dessus ne rallonge donc rien — c'est le "
            "plus petit des deux qui décide. Le garder plus bas évite qu'une "
            "avance de fond monopolise l'unique emplacement d'un modèle local "
            "pendant que quelqu'un attend une réponse."
        ),
    ),
    ConfigItem(
        key="projects.runs_since_input_cap", type="int", section="projects",
        label="Avances max sans retour humain",
        default=10, min=1, max=100, hot_reload=True,
        hint=(
            "Au-delà, le projet cesse d'être dû jusqu'à ce que quelqu'un "
            "revienne (message, avance manuelle, mise à jour). Sans ce "
            "plafond, un projet mal cadré tourne indéfiniment tout seul en "
            "brûlant des appels."
        ),
    ),
    ConfigItem(
        key="projects.match_confidence_threshold", type="float",
        section="projects", label="Seuil de détection en conversation",
        default=0.4, min=0.0, max=1.0, hot_reload=True,
        hint=(
            "Score minimal (heuristique, sans LLM : titre, mots-clés, "
            "propriétaire) pour qu'un message soit rattaché à un projet. "
            "Attention, ce rattachement ne fait pas qu'ajouter un bloc de "
            "contexte : un projet en `emotion_policy=OFF` bascule le tour en "
            "mode professionnel — plus de tag [EMOTION:], plus de bloc de "
            "variabilité. Baisser le seuil rend Mika plate sur des messages "
            "qui n'ont rien à voir ; le monter lui fait oublier le projet "
            "dont on est en train de lui parler."
        ),
    ),
]
