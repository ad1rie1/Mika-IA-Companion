"""Config schema for the memory subsystem."""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="memory", label="Mémoire", icon="❖", order=30,
        description="Court-terme, consolidation, décroissance, récupération sémantique.",
    ),
    ConfigItem(
        key="memory.short_term_limit", type="int", section="memory", group="Court-terme",
        label="Messages en RAM (garde-fou)",
        default=500, min=5, max=1000, hot_reload=True,
        hint="Garde-fou en NOMBRE ; la taille du fil est gouvernée par le "
             "budget de contexte et la compaction (résumé roulant). "
             "L'ancien défaut 20 amputait la conversation bien avant la "
             "fenêtre du modèle.",
    ),
    ConfigItem(
        key="memory.compaction_interval", type="int", section="memory", group="Compaction",
        label="Période de compaction (s)",
        default=120, min=30, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="memory.compaction_keep_last", type="int", section="memory", group="Compaction",
        label="Messages toujours en clair",
        default=30, min=10, max=100, hot_reload=True,
        hint="Le plancher de récence : les N derniers messages ne sont "
             "jamais repliés dans le résumé.",
    ),
    ConfigItem(
        key="memory.consolidation_interval", type="int", section="memory", group="Consolidation",
        label="Période consolidation (s)",
        default=60, min=10, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="memory.decay_rate", type="float", section="memory", group="Décroissance",
        label="Taux de décroissance/jour",
        default=0.95, min=0.5, max=1.0, hot_reload=True,
        hint="0.95 = perd 5% d'importance par jour.",
    ),
    ConfigItem(
        key="memory.min_importance", type="float", section="memory", group="Décroissance",
        label="Seuil de rappel spontané",
        default=0.1, min=0.0, max=1.0, hot_reload=True,
        hint="En dessous, un souvenir ne remonte plus tout seul dans le "
             "prompt. Il n'est PAS effacé : il reste retrouvable par une "
             "recherche délibérée et ranimable par un boost.",
    ),
    ConfigItem(
        key="memory.dormant_importance", type="float", section="memory",
        group="Décroissance", label="Plancher de sommeil",
        default=0.02, min=0.0, max=1.0, hot_reload=True,
        hint="Importance à laquelle un vieux souvenir cesse de décroître et "
             "s'endort. Doit rester SOUS le seuil de rappel spontané. "
             "Auparavant ce seuil déclenchait un DELETE : la mémoire "
             "interprétée avait un horizon de six semaines pendant que la "
             "transcription brute, elle, était éternelle.",
    ),
    ConfigItem(
        key="memory.retrieval_souvenirs", type="int", section="memory", group="Récupération",
        label="Souvenirs retournés",
        default=5, min=1, max=50, hot_reload=True,
    ),
    ConfigItem(
        key="memory.retrieval_connaissances", type="int", section="memory", group="Récupération",
        label="Connaissances retournées",
        default=10, min=1, max=50, hot_reload=True,
    ),
    ConfigItem(
        key="memory.retrieval_fetch_multiplier", type="int", section="memory", group="Récupération",
        label="Facteur de vivier avant re-ranking",
        default=3, min=1, max=10, hot_reload=True,
        hint="On récupère N×ce facteur candidats pour que le classement par "
             "saillance puisse faire remonter un souvenir marquant mais moins "
             "proche lexicalement. Plus haut = vivier plus large, plus de calcul.",
    ),
    ConfigItem(
        key="memory.salience_importance_weight", type="float", section="memory",
        group="Saillance du rappel", label="Poids de l'importance",
        default=0.6, min=0.0, max=3.0, hot_reload=True,
        hint="L'humain rappelle « ce qui a compté », pas seulement « ce qui "
             "ressemble ». 0 = comportement d'avant (importance = filtre seul).",
    ),
    ConfigItem(
        key="memory.salience_emotion_weight", type="float", section="memory",
        group="Saillance du rappel", label="Poids de la charge émotionnelle",
        default=0.6, min=0.0, max=3.0, hot_reload=True,
        hint="Mémoire flashbulb : un souvenir fortement émotionnel surnage "
             "l'anodin à pertinence égale. 0 = désactivé.",
    ),
    ConfigItem(
        key="memory.salience_mood_weight", type="float", section="memory",
        group="Saillance du rappel", label="Poids de la congruence d'humeur",
        default=0.3, min=0.0, max=2.0, hot_reload=True,
        hint="Rappel humeur-congruent (doux, amorti en humeur négative pour "
             "éviter les spirales). 0 = l'humeur du moment n'oriente pas le rappel.",
    ),
    ConfigItem(
        key="memory.assoc_expansion_enabled", type="bool", section="memory",
        group="Rappel associatif", label="Expansion associative (« ça me rappelle… »)",
        default=True, hot_reload=True,
        hint="Ressort un souvenir LIÉ par thème/entité aux meilleurs hits, même "
             "s'il n'est pas lexicalement proche. Ancré sur ce qui est déjà "
             "pertinent, donc sûr — actif par défaut.",
    ),
    ConfigItem(
        key="memory.assoc_expansion_max", type="int", section="memory",
        group="Rappel associatif", label="Associations max par tour",
        default=1, min=0, max=5, hot_reload=True,
        hint="0 = désactive l'expansion associative.",
    ),
    ConfigItem(
        key="memory.assoc_min_importance", type="float", section="memory",
        group="Rappel associatif", label="Importance min. d'une association",
        default=0.5, min=0.0, max=1.0, hot_reload=True,
        hint="On ne ressort pas de la trivia parce qu'elle partage un thème.",
    ),
    ConfigItem(
        key="memory.intrusion_enabled", type="bool", section="memory",
        group="Rappel associatif", label="Intrusion d'un souvenir intense (expérimental)",
        default=False, hot_reload=True,
        hint="Fait surgir un souvenir très intense MÊME hors-sujet — le souvenir "
             "qui s'impose. Risque de bruit/répétition : OFF par défaut. Ne se "
             "déclenche que sur un tour déjà émotionnellement chargé (nécessite "
             "la passe de préparation active).",
    ),
    ConfigItem(
        key="memory.intrusion_charge_threshold", type="float", section="memory",
        group="Rappel associatif", label="Charge du tour minimale pour une intrusion",
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        hint="La charge émotionnelle du tour (estimée par la préparation) doit "
             "dépasser ce seuil — une mémoire ne surgit pas à froid.",
    ),
    ConfigItem(
        key="memory.intrusion_min_importance", type="float", section="memory",
        group="Rappel associatif", label="Importance min. d'une intrusion",
        default=0.85, min=0.0, max=1.0, hot_reload=True,
        hint="Seul un souvenir vraiment marquant peut s'imposer hors-sujet.",
    ),
    ConfigItem(
        key="memory.episodic_enabled", type="bool", section="memory", group="Épisodique",
        label="Index épisodique actif",
        default=True, restart_required=True,
        hint="Indexe les échanges bruts dans ChromaDB au fil de l'eau "
             "(embeddings seuls, aucun LLM) — « tu te souviens de ce que je "
             "t'ai dit ce matin ? » marche le jour même.",
    ),
    ConfigItem(
        key="memory.episodic_index_interval", type="int", section="memory", group="Épisodique",
        label="Période d'indexation (s)",
        default=60, min=10, max=3600, restart_required=True,
    ),
    ConfigItem(
        key="memory.episodic_retention_days", type="int", section="memory", group="Épisodique",
        label="Rétention des chunks (jours)",
        default=75, min=7, max=365, hot_reload=True,
        hint="Après ce délai la valeur durable a été promue en souvenirs/"
             "connaissances par la nuit ; le SQL garde tout, pour toujours.",
    ),
    ConfigItem(
        key="memory.episodic_chunk_max_chars", type="int", section="memory", group="Épisodique",
        label="Taille max d'un chunk (car.)",
        default=600, min=200, max=2000, hot_reload=True,
        hint="Au-delà de ~450 caractères l'encodeur (MiniLM, 128 tokens) "
             "tronque de toute façon.",
    ),
    ConfigItem(
        key="memory.episodic_flush_age_s", type="int", section="memory", group="Épisodique",
        label="Délai de flush d'une question sans réponse (s)",
        default=600, min=30, max=7200, hot_reload=True,
    ),
    ConfigItem(
        key="memory.retrieval_exchanges", type="int", section="memory", group="Récupération",
        label="Échanges bruts retournés",
        default=3, min=0, max=20, hot_reload=True,
        hint="0 = désactive la voie épisodique du rappel de conversation.",
    ),
    ConfigItem(
        key="memory.reorg_cluster_similarity", type="float", section="memory",
        group="Réorganisation nocturne", label="Seuil de similarité des clusters",
        default=0.55, min=0.3, max=0.9, hot_reload=True,
        hint="Cosinus minimal pour qu'un chunk rejoigne un thème existant.",
    ),
    ConfigItem(
        key="memory.reorg_dedup_distance", type="float", section="memory",
        group="Réorganisation nocturne", label="Distance max de fusion",
        default=0.12, min=0.0, max=0.3, hot_reload=True,
        hint="Deux souvenirs du jour plus proches que cette distance sont "
             "fusionnés (importance max, références repointées).",
    ),
    ConfigItem(
        key="memory.sleep_check_interval", type="int", section="memory", group="Consolidation",
        label="Période check sleep cycle (s)",
        default=60, min=10, max=600, restart_required=True,
        hint="Cadence de la boucle dédiée qui appelle sleep_cycle.run_if_due() "
             "(journal/rêves/digestion). Découplée du consolidator.",
    ),
    ConfigItem(
        key="memory.sleep_llm_timeout", type="int", section="memory", group="Consolidation",
        label="Budget d'un appel LLM nocturne (s)",
        default=120, min=30, max=600, hot_reload=True,
        hint="Journal et rêves. 45 s passaient sous les 76-219 s mesurés sur "
             "un modèle local : la vie nocturne s'éteignait à l'installation, "
             "sans signal. Aligné sur ai.call_timeout_seconds.",
    ),
]
