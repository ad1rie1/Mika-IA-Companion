"""Schéma de configuration du module RSS.

La section ne contenait qu'un intervalle de polling, avec en description
« Flux gérés dans la table RSSFeed (page dédiée) » — page qui n'existait pas.
Les flux n'étaient donc éditables que par l'admin Django ou une variable
d'environnement héritée, ce qui rendait l'onglet Configuration littéralement
vide de tout ce qui compte.

Les flux sont maintenant une ``record_list`` adossée au modèle ``RSSFeed``
(voir ``config_backend.py``) : ils s'ajoutent, se modifient et se désactivent
depuis le tableau de bord, sans jamais transiter par ``ConfigRecordItem``.

Les réglages scalaires sont regroupés — le formulaire les rend par ``group``,
et « ce que le relevé télécharge » n'est pas la même question que « ce qui
mérite de déranger Mika ».
"""
from __future__ import annotations

# L'import enregistre le backend — effet de bord voulu, comme pour l'email.
from modules.plugins.rss import config_backend  # noqa: F401

from configs.types import (
    ConfigGroup, ConfigItem, ConfigRecord, ConfigSection, record_item,
)

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_rss", label="Modules · RSS", icon="⌁", order=73,
        family="systeme",
        summary="Les flux suivis, la cadence du relevé, et ce qui a le droit de l'interrompre.",
        description=(
            "Flux suivis, cadence de relevé, et ce qui mérite de réveiller "
            "Mika. Les articles relevés se consultent dans l'onglet Articles."
        ),
    ),

    # ── Organisation de l'écran ─────────────────────────────────────────
    # « Ce que le relevé télécharge » et « ce qui mérite de déranger Mika »
    # ne sont pas la même question, et la seconde est celle qu'on vient
    # régler. La plomberie HTTP et la rétention sont repliées : on les ouvre
    # quand un flux ne répond plus, pas quand on ajoute un abonnement.
    ConfigGroup(
        section="module_rss", key="Flux", order=10,
        description="Les abonnements. Une ligne désactivée n'est plus relevée "
                    "mais garde ses articles ; ses mots-clés décident de ce "
                    "qui est signalé plutôt que simplement stocké.",
    ),
    ConfigGroup(
        section="module_rss", key="Relevé", order=20,
        description="À quelle cadence les flux sont interrogés, et combien "
                    "d'articles un tour examine. C'est ici que se règle le "
                    "premier relevé d'un flux volumineux, qui sinon arrive "
                    "d'un bloc.",
    ),
    ConfigGroup(
        section="module_rss", key="Rattrapage", order=25,
        description="Ce qui se passe quand l'arriéré arrive d'un bloc : premier "
                    "relevé d'un flux, ou reprise après une coupure. "
                    "L'actualité tombe normalement au fil de l'eau — mesuré "
                    "ici, une entrée par heure environ sur l'ensemble des flux "
                    "— mais un démarrage à froid en a déjà produit 119 d'un "
                    "coup, autant d'observations et de réveils de la conscience, "
                    "et une fatigue saturée pour deux heures. Ces bornes ne "
                    "retirent RIEN de ce qu'elle peut lire : les articles sont "
                    "stockés, listables et proposables comme avant. Elles "
                    "bornent seulement ce qui vient la chercher.",
    ),
    ConfigGroup(
        section="module_rss", key="Attention", order=30,
        description="Le droit d'interrompre. Un article signalé passe par la "
                    "conscience, qui décide ; un article en mot-clé d'alerte "
                    "coupe la file et ouvre un tour de conversation "
                    "directement. Tout décocher fait du module une revue de "
                    "presse silencieuse.",
    ),
    ConfigGroup(
        section="module_rss", key="Transport HTTP", order=40, advanced=True,
        description="Ce que le client HTTP accepte de faire face à un éditeur : "
                    "combien de temps il attend, combien il télécharge, et sous "
                    "quel nom il se présente. On l'ouvre quand un flux précis "
                    "revient toujours en erreur.",
    ),
    ConfigGroup(
        section="module_rss", key="Conservation", order=50, advanced=True,
        description="Combien d'articles restent en base par flux. Les plus "
                    "anciens sont supprimés au-delà ; la déduplication n'en "
                    "souffre pas.",
    ),

    # ── Les flux ───────────────────────────────────────────────────────
    ConfigItem(
        key="rss.feeds", type="record_list", section="module_rss",
        group="Flux", label="Flux suivis", min_items=0, max_items=100,
        description=(
            "Chaque ligne est un flux RSS, Atom ou RDF. Une ligne désactivée "
            "n'est plus relevée mais garde ses articles."
        ),
        record=ConfigRecord(
            name="rss_feed", label="Flux RSS",
            fields=(
                record_item(
                    key="url", type="str", label="URL du flux",
                    hint="Adresse du flux lui-même, pas de la page d'accueil.",
                ),
                record_item(
                    key="name", type="str", label="Nom",
                    hint="Laissé vide : le nom du domaine, puis le titre annoncé par le flux.",
                ),
                record_item(
                    key="category", type="str", label="Catégorie",
                    hint="Regroupement libre — Tech, Actu, Science… Sert de filtre.",
                ),
                record_item(
                    key="keywords", type="str", label="Mots-clés",
                    hint="Séparés par des virgules. Renseignés, seuls les articles "
                         "qui en contiennent sont signalés ; les autres sont "
                         "stockés sans rien déclencher.",
                ),
                record_item(
                    key="emit_events", type="bool", label="Signaler les nouveaux articles",
                    default=True,
                    hint="Décoché : le flux est relevé et consultable, mais ne "
                         "réveille jamais la conscience.",
                ),
            ),
        ),
    ),

    # ── Relevé ─────────────────────────────────────────────────────────
    ConfigItem(
        key="rss.poll_interval", type="int", section="module_rss",
        group="Relevé", label="Intervalle de relevé (s)",
        default=600, min=60, max=86400, hot_reload=True,
        description="Un flux public n'aime pas être interrogé plus souvent que toutes les 5 min.",
    ),
    ConfigItem(
        key="rss.fetch_timeout", type="int", section="module_rss",
        group="Transport HTTP", label="Délai maximum par flux (s)",
        default=20, min=5, max=120, hot_reload=True,
        description="Au-delà, le flux est abandonné pour ce tour et compté en erreur.",
    ),
    ConfigItem(
        key="rss.max_entries_per_poll", type="int", section="module_rss",
        group="Relevé", label="Articles examinés par flux et par tour",
        default=15, min=1, max=100, hot_reload=True,
        description=(
            "Borne le premier relevé d'un flux volumineux : sans elle, un "
            "abonnement à cinq flux produit d'un coup des centaines d'articles."
        ),
    ),
    ConfigItem(
        key="rss.keep_per_feed", type="int", section="module_rss",
        group="Conservation", label="Articles conservés par flux",
        default=200, min=20, max=5000, hot_reload=True,
        description="Les plus anciens sont supprimés au-delà. La déduplication n'en souffre pas.",
    ),
    ConfigItem(
        key="rss.max_feed_kb", type="int", section="module_rss",
        group="Transport HTTP", label="Taille max téléchargée par flux (Ko)",
        default=5120, min=64, max=51200, hot_reload=True,
        description=(
            "Un flux est une liste de titres ; au-delà, ce n'en est pas un. "
            "La lecture s'arrête à cette taille, et c'est la seule borne de "
            "ce que l'analyseur reçoit — un flux à contenu intégral tient "
            "déjà un fil plusieurs centaines de millisecondes."
        ),
    ),
    ConfigItem(
        key="rss.user_agent", type="str", section="module_rss",
        group="Transport HTTP", label="User-Agent",
        default="vtuber-rss/2.0 (+https://localhost)", hot_reload=True,
        description=(
            "Envoyé à chaque requête. Certains éditeurs refusent un client "
            "anonyme ou inconnu ; d'autres demandent une adresse de contact. "
            "Vidé, la valeur d'usine reprend la main."
        ),
    ),

    # ── Attention ──────────────────────────────────────────────────────
    ConfigItem(
        key="rss.emit_events", type="bool", section="module_rss",
        group="Attention", label="Signaler les nouveaux articles",
        default=True, hot_reload=True,
        description=(
            "Interrupteur global. Décoché, aucun flux n'émet d'événement ni "
            "n'interrompt Mika sur un mot-clé d'alerte : le module devient "
            "une revue de presse silencieuse."
        ),
    ),
    ConfigItem(
        key="rss.alert_keywords", type="list", section="module_rss",
        group="Attention", label="Mots-clés d'alerte",
        default=[], hot_reload=True,
        description=(
            "Un article qui en contient un interrompt Mika directement "
            "(notify_ai) au lieu d'attendre qu'elle y prête attention. "
            "À garder très court. Ne s'applique qu'aux articles qu'un flux a "
            "le droit de signaler : un flux décoché reste muet, alerte comprise."
        ),
    ),
    ConfigItem(
        key="rss.seed_silently", type="bool", section="module_rss",
        group="Rattrapage", label="Premier relevé silencieux",
        default=True, hot_reload=True,
        description=(
            "À la découverte d'un flux, toute sa page est un fonds, pas une "
            "actualité. Les articles sont engrangés et rien n'est signalé ; "
            "le flux ne parle qu'à partir du relevé suivant."
        ),
    ),
    ConfigItem(
        key="rss.emit_max_age_hours", type="int", section="module_rss",
        group="Rattrapage", label="Âge maximum d'un article signalé (h)",
        default=12, min=0, max=168, hot_reload=True,
        description=(
            "Au-delà, l'article est enregistré sans être signalé : un titre "
            "d'avant-hier découvert aujourd'hui n'est pas un événement qui "
            "arrive. 0 désactive la fenêtre. Un article sans date lisible est "
            "traité comme récent — ne pas savoir n'est pas savoir que c'est "
            "vieux."
        ),
    ),
    ConfigItem(
        key="rss.emit_max_per_poll", type="int", section="module_rss",
        group="Rattrapage", label="Articles signalés au maximum, par flux et par tour",
        default=5, min=0, max=50, hot_reload=True,
        description=(
            "Borne un éditeur qui publie vingt articles d'un coup, tous "
            "légitimement récents. Les suivants sont enregistrés sans être "
            "signalés. 0 lève le plafond."
        ),
    ),
    ConfigItem(
        key="rss.max_alerts_per_poll", type="int", section="module_rss",
        group="Attention", label="Alertes maximum par tour",
        default=2, min=0, max=10, hot_reload=True,
        description="Un mot-clé trop large ne doit pas pouvoir déclencher trente interruptions.",
    ),
    ConfigItem(
        key="rss.context_items", type="int", section="module_rss",
        group="Attention", label="Titres injectés dans l'invite",
        default=4, min=0, max=15, hot_reload=True,
        description=(
            "Nombre de titres récents non lus visibles par Mika pendant une "
            "conversation. 0 : elle ne sait pas ce qui est arrivé sans aller le lire."
        ),
    ),
]
