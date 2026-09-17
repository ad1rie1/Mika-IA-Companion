"""Config schema for the memory subsystem."""
from __future__ import annotations

from configs.types import ConfigGroup, ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="memory", label="Mémoire", icon="❖", order=30, family="vie_interieure",
        summary="Ce qu'elle retient, comment elle le retrouve, ce que la nuit en fait.",
        description="Court-terme, consolidation, décroissance, récupération sémantique.",
    ),
        # ── Organisation de l'écran ─────────────────────────────────────
    #
    # Dix-sept groupes sur soixante-dix-sept réglages : sans ordre ni
    # explication, la page se lisait comme un tas. L'ordre suit maintenant le
    # trajet d'un souvenir — ce qu'elle vient d'entendre, ce qu'elle en garde,
    # ce qu'elle retrouve, ce que la nuit en fait — et les blocs qu'on
    # n'ouvre qu'en diagnostic sont repliés (`advanced`).
    #
    # « Replié » ne veut pas dire caché : le bloc reste cherchable, il
    # s'ouvre seul s'il contient une valeur modifiée, et Ctrl+F du navigateur
    # sait déplier un `<details>`.
    ConfigGroup(
        section="memory", key="Court-terme", order=10,
        description="Combien de messages elle garde sous la main, en clair, "
                    "avant que la compaction ne s'en mêle.",
    ),
    ConfigGroup(
        section="memory", key="Compaction", order=20,
        description="Quand le fil devient trop long, les vieux échanges sont "
                    "repliés en un résumé. Le verbatim, lui, ne bouge pas : il "
                    "reste en base et dans l'index épisodique.",
    ),
    ConfigGroup(
        section="memory", key="Consolidation", order=30,
        description="La boucle de fond qui relit les échanges et en extrait "
                    "souvenirs, connaissances et engagements.",
    ),
    ConfigGroup(
        section="memory", key="Extraction par thème", order=35, advanced=True,
        description="Quand une passe de consolidation dépasse une tranche "
                    "(reprise après panne, grosse journée), la fenêtre est "
                    "découpée par thème — sur les embeddings déjà stockés de "
                    "l'index épisodique — plutôt qu'en tranches linéaires : "
                    "« trois conversations aujourd'hui : le projet, la "
                    "dispute, les vacances ». Un tick ordinaire de 60 s "
                    "n'est pas concerné et ne lit pas l'index.",
    ),
    ConfigGroup(
        section="memory", key="Récupération", order=40,
        description="Combien de souvenirs et de connaissances remontent dans "
                    "le prompt à chaque tour. Ce sont des planchers : si le "
                    "modèle a de la place, elle en sert davantage.",
    ),
    ConfigGroup(
        section="memory", key="Saillance du rappel", order=50,
        description="Ce qui fait qu'un souvenir revient plutôt qu'un autre : "
                    "son importance, sa charge émotionnelle, l'humeur du moment.",
    ),
    ConfigGroup(
        section="memory", key="Rappel", order=60,
        description="L'anti-répétition. Sans lui, elle ressort le même "
                    "« ça me rappelle… » à quarante tours d'intervalle.",
    ),
    ConfigGroup(
        section="memory", key="Sommeil", order=70,
        description="À quelle heure elle se couche, et ce qu'il faut de calme "
                    "pour qu'elle s'endorme. La fatigue avance l'heure du "
                    "coucher, elle ne l'empêche jamais.",
    ),
    ConfigGroup(
        section="memory", key="Rêves", order=80,
        description="Phase REM : elle rapproche des souvenirs de thèmes "
                    "différents. Un rêve assez net peut être mentionné le "
                    "lendemain matin.",
    ),
    ConfigGroup(
        section="memory", key="Journal intime", order=90,
        description="Le récit de la journée écoulée, écrit en début de nuit et "
                    "relu le lendemain.",
    ),
    ConfigGroup(
        section="memory", key="Sommeil profond", order=100,
        description="La digestion des pensées qui traînent : elles perdent de "
                    "l'intensité, changent de couleur, et les plus fortes "
                    "laissent un souvenir réfléchi.",
    ),
    ConfigGroup(
        section="memory", key="Décroissance", order=110, advanced=True,
        description="Un souvenir peu sollicité perd de l'importance. Il ne "
                    "s'efface pas pour autant : sous le seuil il s'endort, et "
                    "une recherche délibérée le retrouve encore.",
    ),
    ConfigGroup(
        section="memory", key="Rappel associatif", order=120, advanced=True,
        description="Les deux voies détournées : l'expansion de proche en "
                    "proche, et l'intrusion — un souvenir chargé qui s'invite "
                    "sans qu'on l'ait cherché.",
    ),
    ConfigGroup(
        section="memory", key="Épisodique", order=130, advanced=True,
        description="L'index vectoriel des échanges bruts, qui rend une "
                    "conversation du jour retrouvable avant même que la nuit "
                    "en ait tiré quoi que ce soit.",
    ),
    ConfigGroup(
        section="memory", key="Réorganisation nocturne", order=140, advanced=True,
        description="Fusion, en fin de nuit, des souvenirs que la journée a "
                    "écrits en double. Le regroupement par thème, lui, vit "
                    "dans « Extraction par thème » : la nuit ne relit plus "
                    "le verbatim.",
    ),
    ConfigGroup(
        section="memory", key="Profils", order=150, advanced=True,
        description="Cadence de régénération de la fiche que Mika tient sur "
                    "chaque personne.",
    ),
    ConfigGroup(
        section="memory", key="Auto-narratif", order=160, advanced=True,
        description="Cadence de régénération du paragraphe « qui tu es "
                    "devenue », et la matière qu'on lui donne.",
    ),
    ConfigGroup(
        section="memory", key="Outils de mémoire", order=170, advanced=True,
        description="Plafonds des outils que Mika appelle elle-même pour "
                    "fouiller sa mémoire en cours de conversation.",
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
        group="Extraction par thème", label="Seuil de similarité des thèmes",
        default=0.55, min=0.3, max=0.9, hot_reload=True,
        hint="Cosinus minimal pour qu'un échange rejoigne un thème existant. "
             "Plus bas = moins de thèmes, plus gros ; plus haut = un appel "
             "d'extraction par nuance.",
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
    # ── Compaction (suite) ───────────────────────────────────────
    ConfigItem(
        key="memory.compaction_survival_factor", type="float", section="memory",
        group="Compaction", label="Part du texte qui survit au repli",
        default=0.15, min=0.01, max=1.0, hot_reload=True,
        hint="Estimation de ce qu'un résumé conserve du volume replié. Elle "
             "sert à prévoir jusqu'où descendre : trop haute, on replie trop "
             "peu et le watermark reste franchi au tick suivant.",
    ),
    ConfigItem(
        key="memory.compaction_summary_target_chars", type="int", section="memory",
        group="Compaction", label="Longueur max du résumé roulant (car.)",
        default=6000, min=500, max=30000, hot_reload=True,
        hint="Le résumé ne doit jamais manger la part du fil vivant. Annoncé "
             "au modèle dans la consigne, et appliqué en ceinture à la sortie.",
    ),
    ConfigItem(
        key="memory.compaction_llm_timeout", type="float", section="memory",
        group="Compaction", label="Budget de l'appel de compaction (s)",
        default=45.0, min=5.0, max=600.0, hot_reload=True,
        hint="Boucle de fond : un dépassement ne coûte que le tick, le buffer "
             "absorbe et la passe repart au suivant.",
    ),

    # ── Épisodique (suite) ───────────────────────────────────────
    ConfigItem(
        key="memory.episodic_message_text_cap", type="int", section="memory",
        group="Épisodique", label="Troncature d'un message dans le chunk (car.)",
        default=2000, min=200, max=20000, hot_reload=True,
        hint="Un collage démesuré est borné dans le DOCUMENT indexé ; le SQL "
             "garde l'intégralité et le deux-temps la restitue.",
    ),
    ConfigItem(
        key="memory.episodic_max_msgs_per_tick", type="int", section="memory",
        group="Épisodique", label="Messages indexés par tick",
        default=500, min=10, max=5000, hot_reload=True,
        hint="Un backlog laissé par une indisponibilité est absorbé sur "
             "plusieurs ticks plutôt qu'en un seul encode géant.",
    ),
    ConfigItem(
        key="memory.episodic_prune_interval_s", type="int", section="memory",
        group="Épisodique", label="Période de purge des chunks (s)",
        default=3600, min=60, max=86400, hot_reload=True,
        hint="La rétention se mesure en jours : un balayage horaire suffit, "
             "comme pour la décroissance.",
    ),

    # ── Profils de personnes ─────────────────────────────────────
    ConfigItem(
        key="memory.profile_min_age_hours", type="int", section="memory",
        group="Profils", label="Âge min. d'un profil avant régénération (h)",
        default=24, min=1, max=720, hot_reload=True,
        hint="Sa lecture de quelqu'un ne doit pas osciller toutes les dix "
             "minutes.",
    ),
    ConfigItem(
        key="memory.profile_min_new_souvenirs", type="int", section="memory",
        group="Profils", label="Souvenirs neufs exigés pour régénérer",
        default=3, min=1, max=100, hot_reload=True,
        hint="Comptés depuis la dernière génération, et sur les souvenirs qui "
             "mentionnent CETTE personne.",
    ),
    ConfigItem(
        key="memory.profile_activity_window_days", type="int", section="memory",
        group="Profils", label="Fenêtre d'activité d'une personne (jours)",
        default=14, min=1, max=365, hot_reload=True,
        hint="Au-delà, la personne est inactive et ne consomme plus de budget "
             "LLM.",
    ),
    ConfigItem(
        key="memory.profile_max_souvenirs", type="int", section="memory",
        group="Profils", label="Souvenirs envoyés au modèle par profil",
        default=15, min=1, max=100, hot_reload=True,
    ),
    ConfigItem(
        key="memory.profile_max_anchor_souvenirs", type="int", section="memory",
        group="Profils", label="Souvenirs d'ancrage par profil (toutes époques)",
        default=5, min=0, max=100, hot_reload=True,
        hint="Ajoutés au vécu neuf depuis la dernière fiche : ce qui a compté "
             "avec cette personne, quel que soit son âge.",
    ),
    ConfigItem(
        key="memory.profile_max_connaissances", type="int", section="memory",
        group="Profils", label="Connaissances envoyées au modèle par profil",
        default=10, min=1, max=100, hot_reload=True,
    ),
    ConfigItem(
        key="memory.profile_timeout_seconds", type="int", section="memory",
        group="Profils", label="Budget d'un profil (s)",
        default=45, min=5, max=600, hot_reload=True,
        hint="Les personnes sont traitées en série dans la boucle : le budget "
             "est par personne, pas par cycle.",
    ),
    ConfigItem(
        key="memory.profile_check_interval_s", type="int", section="memory",
        group="Profils", label="Période de la sélection des fiches (s)",
        default=3600, min=60, max=86400, hot_reload=True,
        hint="La sélection agrège toutes les personnes et leurs souvenirs ; "
             "la faire à chaque passe de 60 s pour une porte à 24 h grossit "
             "avec l'installation. Horaire suffit.",
    ),
    ConfigItem(
        key="memory.profile_max_persons_per_cycle", type="int", section="memory",
        group="Profils", label="Personnes traitées par cycle",
        default=3, min=1, max=50, hot_reload=True,
        hint="Garde-fou de coût si une dizaine de nouvelles têtes apparaissent "
             "d'un coup.",
    ),

    # ── Auto-narratif (qui elle devient) ─────────────────────────
    ConfigItem(
        key="memory.narrative_min_age_hours", type="int", section="memory",
        group="Auto-narratif", label="Âge min. de l'auto-narratif (h)",
        default=24, min=1, max=720, hot_reload=True,
        hint="Son self-concept ne doit pas se réécrire toutes les dix minutes.",
    ),
    ConfigItem(
        key="memory.narrative_min_new_souvenirs", type="int", section="memory",
        group="Auto-narratif", label="Souvenirs neufs exigés pour régénérer",
        default=5, min=1, max=100, hot_reload=True,
    ),
    ConfigItem(
        key="memory.narrative_window_days", type="int", section="memory",
        group="Auto-narratif", label="Fenêtre du vécu récent (jours)",
        default=14, min=1, max=365, hot_reload=True,
        hint="La porte compte le NEUF : l'échantillon doit en contenir, sinon "
             "le self-concept se fige sur les souvenirs à forte importance.",
    ),
    ConfigItem(
        key="memory.narrative_max_recent_souvenirs", type="int", section="memory",
        group="Auto-narratif", label="Souvenirs récents dans le prompt",
        default=18, min=1, max=100, hot_reload=True,
    ),
    ConfigItem(
        key="memory.narrative_max_anchor_souvenirs", type="int", section="memory",
        group="Auto-narratif", label="Souvenirs d'ancrage (toutes époques)",
        default=7, min=0, max=100, hot_reload=True,
        hint="Ce qui a compté, quel que soit son âge — l'ordre du prompt met "
             "quand même le récent d'abord.",
    ),
    ConfigItem(
        key="memory.narrative_max_connaissances", type="int", section="memory",
        group="Auto-narratif", label="Connaissances dans le prompt",
        default=20, min=0, max=100, hot_reload=True,
    ),
    ConfigItem(
        key="memory.narrative_timeout_seconds", type="int", section="memory",
        group="Auto-narratif", label="Budget de l'appel (s)",
        default=60, min=5, max=600, hot_reload=True,
        hint="Tourne dans la boucle de consolidation : un provider bloqué ne "
             "doit pas la retenir.",
    ),

    # ── Extraction par thème (suite) ─────────────────────────────
    # Les clés gardent leur préfixe « reorg_ » : elles sont nées dans la
    # réorganisation nocturne, et les renommer perdrait la valeur réglée de
    # chaque installation. Le volume max d'un thème n'a plus de clé propre :
    # c'est la tranche d'extraction (memory.extraction_max_chars) qui borne.
    ConfigItem(
        key="memory.reorg_max_clusters", type="int", section="memory",
        group="Extraction par thème", label="Thèmes max par fenêtre",
        default=20, min=1, max=200, hot_reload=True,
        hint="Au-delà, un échange rejoint le thème le plus proche même sous le "
             "seuil de similarité — un thème de plus est un appel LLM de plus.",
    ),
    ConfigItem(
        key="memory.reorg_min_cluster_chars", type="int", section="memory",
        group="Extraction par thème",
        label="Verbatim min pour qu'un thème parte seul (car.)",
        default=200, min=0, max=5000, hot_reload=True,
        hint="Un thème plus petit n'est pas perdu : il rejoint la tranche "
             "résiduelle, extraite en ordre linéaire avec ce que l'index "
             "épisodique n'a pas encore découpé.",
    ),

    # ── Réorganisation nocturne (suite) ──────────────────────────
    ConfigItem(
        key="memory.reorg_max_merges_per_night", type="int", section="memory",
        group="Réorganisation nocturne", label="Fusions de souvenirs max par nuit",
        default=50, min=0, max=1000, hot_reload=True,
        hint="0 = le dédoublonnage ne fusionne plus rien.",
    ),

    # ── Anti-répétition du rappel ────────────────────────────────
    ConfigItem(
        key="memory.recall_memo_turns", type="int", section="memory",
        group="Rappel", label="Tours pendant lesquels un souvenir servi reste connu",
        default=3, min=1, max=20, restart_required=True,
        hint="Profondeur du mémo anti-répétition. Elle fixe la taille du "
             "tampon créé à la première mémorisation d'une personne : un mémo "
             "déjà ouvert garde son ancienne profondeur jusqu'au redémarrage.",
    ),
    ConfigItem(
        key="memory.recall_repeat_penalty", type="float", section="memory",
        group="Rappel", label="Démotion d'un souvenir déjà servi",
        default=0.45, min=0.0, max=1.0, hot_reload=True,
        hint="On DÉMOTE, on n'exclut pas : à la même question posée deux fois, "
             "une mémoire qui ne rend plus rien est pire que la répétition. "
             "1.0 = plus d'anti-répétition du tout.",
    ),

    # ── Outils de mémoire (rappel actif) ─────────────────────────
    ConfigItem(
        key="memory.tools_max_search_results", type="int", section="memory",
        group="Outils de mémoire", label="Résultats max d'une recherche",
        default=8, min=1, max=50, hot_reload=True,
        hint="Plafond pour que la réponse d'un outil ne fasse pas exploser le "
             "budget de la conversation.",
    ),
    ConfigItem(
        key="memory.tools_max_journals", type="int", section="memory",
        group="Outils de mémoire", label="Journaux max relus d'un coup",
        default=7, min=1, max=50, hot_reload=True,
    ),

    # ── Sommeil : les portes de la nuit ──────────────────────────
    ConfigItem(
        key="memory.sleep_idle_seconds_threshold", type="int", section="memory",
        group="Sommeil", label="Inactivité exigée pour s'endormir (s)",
        default=900, min=60, max=21600, hot_reload=True,
        hint="Une interaction la réveille quelle que soit l'heure ; ce délai "
             "est ce qu'il faut de silence pour se rendormir.",
    ),
    ConfigItem(
        key="memory.sleep_endogenous_wake_grace_seconds", type="int",
        section="memory", group="Sommeil",
        label="Grâce après un réveil (s)",
        default=180, min=0, max=3600, hot_reload=True,
        hint="Délai pendant lequel un réveil tient même si personne n'a rien "
             "dit. L'inactivité ne compte que ce que les AUTRES font : une "
             "initiative nocturne la réveillait un tick, puis la porte la "
             "rendormait pendant qu'elle parlait — et la voix se tait en "
             "sommeil, si bien que le message s'affichait, muet, prononcé par "
             "quelqu'un que l'écran montrait endormi. Assez long pour qu'un "
             "tour aboutisse (l'appel IA est borné à 120 s), pas au point de "
             "faire une insomnie.",
    ),
    ConfigItem(
        key="memory.sleep_early_night_max_advance_hours", type="int", section="memory",
        group="Sommeil", label="Avance max du coucher par la fatigue (h)",
        default=1, min=0, max=6, hot_reload=True,
        hint="La tension REST n'interdit plus de dormir, elle avance l'heure "
             "du coucher — d'au plus ce nombre d'heures à fatigue pleine "
             "(cinq heures d'activité soutenue). À 2, une soirée de "
             "conversation la couchait à 21 h.",
    ),

    # ── Journal intime (sommeil léger) ───────────────────────────
    ConfigItem(
        key="memory.journal_attempt_interval_s", type="int", section="memory",
        group="Journal intime", label="Espacement des reprises (s)",
        default=30 * 60, min=60, max=21600, hot_reload=True,
        hint="Un journal en échec n'avance pas sa date : sans espacement, la "
             "boucle rejouerait l'appel LLM toutes les 60 s jusqu'au matin.",
    ),
    ConfigItem(
        key="memory.journal_max_attempts_per_night", type="int", section="memory",
        group="Journal intime", label="Tentatives max par nuit",
        default=3, min=1, max=20, hot_reload=True,
        hint="Un modèle qui a échoué trois fois de suite ne réussira pas la "
             "quatrième.",
    ),

    # ── Rêves (REM) ──────────────────────────────────────────────
    ConfigItem(
        key="memory.dream_probability", type="float", section="memory",
        group="Rêves", label="Probabilité de rêver à chaque passage en REM",
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        hint="0 = plus aucun rêve. Le point de dev qui force un rêve écrase ce "
             "réglage le temps de son appel.",
    ),
    ConfigItem(
        key="memory.dream_max_per_night", type="int", section="memory",
        group="Rêves", label="Rêves max par nuit",
        default=2, min=0, max=10, hot_reload=True,
    ),
    ConfigItem(
        key="memory.dream_attempt_interval_s", type="int", section="memory",
        group="Rêves", label="Espacement des épisodes REM (s)",
        default=45 * 60, min=60, max=21600, hot_reload=True,
        hint="Un vrai épisode REM revient toutes les ~90 min. Au-delà du "
             "réalisme, cela empêche l'avatar de clignoter entre deux phases "
             "à chaque tick.",
    ),

    # ── Sommeil profond (digestion) ──────────────────────────────
    ConfigItem(
        key="memory.digestion_min_age_minutes", type="int", section="memory",
        group="Sommeil profond", label="Âge min. d'une rumination digérée (min)",
        default=120, min=5, max=1440, hot_reload=True,
        hint="À accorder avec la demi-vie des ruminations : trop haut, la "
             "phase de guérison n'a jamais rien à digérer.",
    ),
    ConfigItem(
        key="memory.digestion_to_souvenir_threshold", type="float", section="memory",
        group="Sommeil profond",
        label="Intensité au-dessus de laquelle une rumination devient un souvenir",
        default=0.4, min=0.0, max=1.0, hot_reload=True,
        hint="L'insight avec lequel on se réveille : « Après y avoir repensé "
             "cette nuit… ».",
    ),

    # ── Consolidation (suite) ────────────────────────────────────
    ConfigItem(
        key="memory.retention_sweep_interval_s", type="int", section="memory",
        group="Consolidation", label="Période du balayage de rétention (s)",
        default=3600, min=60, max=86400, hot_reload=True,
        hint="Ménage sur des tables qui se mesurent en jours : le faire à "
             "chaque tick de 60 s serait de la charge pure.",
    ),
    ConfigItem(
        key="memory.extraction_max_chars", type="int", section="memory",
        group="Consolidation", label="Volume max d'une tranche d'extraction (car.)",
        default=8000, min=500, max=100000, hot_reload=True,
        hint="Au-delà, la fenêtre est découpée par thème (bloc « Extraction "
             "par thème »), chaque tranche restant sous ce volume et sur les "
             "frontières de messages — jamais au milieu d'un tour.",
    ),
    ConfigItem(
        key="memory.consolidation_max_window_messages", type="int", section="memory",
        group="Consolidation", label="Messages lus par passe",
        default=400, min=10, max=5000, hot_reload=True,
        hint="Le checkpoint ne bouge plus quand l'extraction est "
             "indisponible : sans ce plafond, tout le backlog serait relu à "
             "chaque tick.",
    ),
    ConfigItem(
        key="memory.commitment_max_age_days", type="int", section="memory",
        group="Consolidation", label="Péremption d'un engagement en attente (jours)",
        default=30, min=1, max=365, hot_reload=True,
        hint="Passé ce délai un engagement jamais résolu est abandonné, plutôt "
             "que ré-affirmé dans chaque prompt.",
    ),
    ConfigItem(
        key="memory.emotion_aggregation_interval_s", type="int", section="memory",
        group="Consolidation", label="Période de l'agrégat émotionnel (s)",
        default=300, min=30, max=86400, hot_reload=True,
        hint="L'agrégat a le JOUR pour granularité. Rien n'est perdu à "
             "espacer : la passe recalcule la journée entière, pas un delta.",
    ),
    ConfigItem(
        key="memory.weekly_volatile_spread", type="float", section="memory",
        group="Consolidation",
        label="Dispersion au-delà de laquelle une semaine est « instable »",
        default=0.4, min=0.0, max=2.0, hot_reload=True,
        hint="Écart de valence entre le meilleur et le pire jour. Sur sept "
             "jours c'est la dispersion qui porte l'information, pas le "
             "déplacement moyen.",
    ),
    ConfigItem(
        key="memory.extraction_min_messages", type="int", section="memory",
        group="Consolidation", label="Messages minimum pour extraire",
        default=6, min=1, max=200, hot_reload=True,
        hint="Une fenêtre part quand elle atteint ce nombre de messages, OU "
             "quand plus rien n'arrive depuis le délai de calme. À 1, chaque "
             "tick de 60 s extrayait un message seul : une question à un "
             "appel, sa réponse au suivant, et 60 à 90 appels par heure de "
             "conversation là où cinq suffisent.",
    ),
    ConfigItem(
        key="memory.extraction_quiet_seconds", type="int", section="memory",
        group="Consolidation", label="Calme avant d'extraire une petite fenêtre (s)",
        default=300, min=0, max=86400, hot_reload=True,
        hint="Une fenêtre trop petite part quand même après ce silence. Et "
             "une question sans réponse plus fraîche que ce délai est "
             "retenue : sa réponse arrive, la paire doit partir ensemble.",
    ),
    ConfigItem(
        key="memory.max_contradiction_checks", type="int", section="memory",
        group="Consolidation", label="Vérifications de contradiction par connaissance",
        default=1, min=0, max=10, hot_reload=True,
        hint="Chaque vérification est un appel LLM séquentiel de plus dans un "
             "tick — sur un backend à un créneau, en concurrence avec le tour "
             "de conversation en cours. 0 = plus de contrôle.",
    ),

    # ── Décroissance (suite) ─────────────────────────────────────
    ConfigItem(
        key="memory.decay_interval_s", type="int", section="memory",
        group="Décroissance", label="Période du balayage de décroissance (s)",
        default=3600, min=60, max=86400, hot_reload=True,
        hint="La décroissance se mesure en jours ; une ligne sautée garde son "
             "ancre, donc rien ne se perd à espacer.",
    ),
    ConfigItem(
        key="memory.decay_batch", type="int", section="memory",
        group="Décroissance", label="Lignes réécrites par passe",
        default=500, min=10, max=10000, hot_reload=True,
        hint="Chaque écriture ré-indexe dans ChromaDB (un encode) : un premier "
             "passage sur un gros historique reste borné, le reste attend "
             "l'heure suivante.",
    ),
]
