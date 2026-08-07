"""Schéma de configuration du module caméra.

Le module est **opt-in**, et il ne l'était pas. Le seul producteur de frames
est un appareil externe qui se connecte à ``ws/camera`` — aucun client n'est
livré dans ``frontend/`` — donc « aucune caméra » est le cas nominal, pas le
cas dégradé. Le module tournait quand même : ``camera_see`` et
``camera_list_devices`` étaient déclarés à chaque itération de la boucle
d'outils, à chaque tour, sur une installation où aucun device n'existera
jamais, et le modèle était invité à appeler un outil qui répond « Aucune
caméra disponible ».

``get_capabilities()`` savait déjà se taire sans device ; ``return_tools()``
ne pouvait pas faire pareil, parce que ``ModuleCollectors.tools()`` met la
liste en cache et ne l'invalide qu'au changement de cycle de vie — le
résultat aurait dépendu du moment où le cache a été bâti. Un interrupteur
adossé à ``is_available()`` règle les trois d'un coup : ni déclaration
d'outils, ni tick toutes les 10 s, ni appel ``get_context()`` à chaque tour.
C'est le seul réglage de cette section qui n'est **pas** relu à chaud : il
décide du démarrage du module, pas du contenu d'un tour de boucle.

Une fois allumé, le module est, par construction, le plus gros consommateur de
tokens du moteur — chaque analyse envoie une image complète au modèle vision —
et c'était le seul à n'exposer aucun réglage : cadence, droit d'interrompre et
existence même d'une analyse de fond étaient trois littéraux. Sur une scène
vivante le hash perceptuel change en permanence, donc la boucle déclenchait une
analyse toutes les 30 s (2 880 par jour et par device), et chaque verdict
« notable » ouvrait un tour de pipeline complet sans le moindre délai de garde
— là où la Forge borne son équivalent (``forge.notify_cooldown_s``).

Trois questions distinctes, donc trois groupes :

- **Analyse proactive** — est-ce qu'elle regarde d'elle-même, à quelle cadence,
  et jusqu'à quand après la dernière interaction. L'interrupteur est séparé de
  l'outil ``camera_see`` : décoché, Mika ne regarde plus toute seule, mais elle
  regarde toujours quand on le lui demande.
- **Attention** — le droit d'interrompre. Un changement notable reste observé
  et visible dans l'invite même quand il n'a pas le droit d'ouvrir un tour.
- **Regard actif** — la fréquence maximale de l'outil, que seul « pas deux
  analyses en parallèle » bornait jusqu'ici.
- **Accès** — qui a le droit de pousser des frames. Ce que la socket injecte
  n'est pas anonyme : la description produite par le modèle vision entre dans
  ``--- CONTEXTE MODULES ---`` à chaque tour pendant dix minutes, et un
  changement notable ouvre un tour complet. Un device n'a pas de session
  Django, d'où un jeton plutôt que la session du consumer principal.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_camera", label="Modules · Caméra", icon="◉", order=75,
        description=(
            "Perception visuelle : ce que Mika regarde d'elle-même, à quelle "
            "cadence, et ce qui a le droit de l'interrompre. Les devices se "
            "connectent sur ws/camera?device=<id>&label=<nom>&token=<jeton>."
        ),
    ),

    ConfigItem(
        key="camera.enabled", type="bool", section="module_camera",
        label="Caméra activée", default=False,
        description=(
            "Décoché, le module ne démarre pas : ses deux outils ne sont pas "
            "déclarés à Mika, aucune analyse vision n'est programmée et les "
            "flux entrants sont refusés. Les réglages ci-dessous restent "
            "modifiables. Après avoir coché, démarre le module avec le bouton "
            "« Activer » de cet espace."
        ),
    ),

    # ── Accès ──────────────────────────────────────────────────────────
    ConfigItem(
        key="camera.device_token", type="secret", section="module_camera",
        group="Accès", label="Jeton des devices caméra",
        default="", sensitive=True, hot_reload=True,
        description=(
            "Comparé au paramètre token= de l'URL de connexion. Une frame "
            "devient du texte réinjecté dans l'invite système à chaque tour "
            "pendant 10 min, et un changement notable ouvre un tour complet : "
            "la socket dépense donc des tokens et écrit dans le prompt. Vide, "
            "seule une session Django authentifiée est admise — et si "
            "CONSUMER_REQUIRE_AUTH est désactivé, la socket reste ouverte à "
            "tous, comme le consumer principal."
        ),
    ),

    # ── Analyse proactive ──────────────────────────────────────────────
    ConfigItem(
        key="camera.proactive_enabled", type="bool", section="module_camera",
        group="Analyse proactive", label="Analyser les flux en continu",
        default=True, hot_reload=True,
        description=(
            "Décoché : plus aucune analyse de fond, donc plus aucun appel "
            "vision automatique. Les frames continuent d'arriver et l'outil "
            "camera_see reste utilisable — elle ne regarde plus d'elle-même, "
            "elle regarde quand on le lui demande."
        ),
    ),
    ConfigItem(
        key="camera.analysis_interval_s", type="int", section="module_camera",
        group="Analyse proactive",
        label="Intervalle minimum entre deux analyses (s)",
        default=120, min=10, max=3600, hot_reload=True,
        description=(
            "Par device, et c'est le poste de dépense principal : chaque "
            "analyse transporte une frame complète. À 30 s — l'ancienne valeur "
            "en dur — une scène vivante coûtait 2 880 appels vision par jour ; "
            "à 120 s l'observation reste largement plus fraîche que les 10 min "
            "au bout desquelles elle sort de l'invite."
        ),
    ),
    ConfigItem(
        key="camera.idle_pause_s", type="int", section="module_camera",
        group="Analyse proactive", label="Pause après inactivité (s)",
        default=900, min=0, max=86400, hot_reload=True,
        description=(
            "Au-delà de ce silence, l'analyse de fond s'arrête : l'observation "
            "produite expirerait sans qu'aucun tour ne l'ait lue. Elle reprend "
            "au premier échange. Même ordre de grandeur que le cycle de "
            "sommeil, qui attend 15 min d'inactivité. 0 : jamais de pause — "
            "elle continue de regarder une pièce vide, à ses frais."
        ),
    ),

    # ── Attention ──────────────────────────────────────────────────────
    ConfigItem(
        key="camera.notify_enabled", type="bool", section="module_camera",
        group="Attention", label="Interrompre sur un changement notable",
        default=True, hot_reload=True,
        description=(
            "Décoché : un changement notable est toujours observé et injecté "
            "dans l'invite, mais n'ouvre plus de tour de conversation."
        ),
    ),
    ConfigItem(
        key="camera.notify_cooldown_s", type="int", section="module_camera",
        group="Attention", label="Délai minimum entre deux interruptions (s)",
        default=300, min=10, max=86400, hot_reload=True,
        description=(
            "Par device. Une interruption est un tour de pipeline complet : "
            "invite système, déclaration de tous les outils, historique, "
            "persistance, extraction mémoire en aval. Sans délai de garde, une "
            "webcam pointée vers quelqu'un qui travaille pouvait en déclencher "
            "deux par minute."
        ),
    ),

    # ── Regard actif ───────────────────────────────────────────────────
    ConfigItem(
        key="camera.see_min_interval_s", type="int", section="module_camera",
        group="Regard actif", label="Délai minimum entre deux camera_see (s)",
        default=10, min=0, max=600, hot_reload=True,
        description=(
            "Un regard demandé vaut plus qu'un balayage périodique, donc le "
            "plancher est bien plus court que l'intervalle d'analyse — mais il "
            "existe : rien n'empêchait le modèle d'enchaîner les appels vision "
            "dans une même boucle d'outils. 0 : aucune limite."
        ),
    ),
]
