"""Réglages des canaux d'entrée — web, historique, caméra.

``communication`` est une application Django installée : ce module est donc
découvert tout seul par ``ConfigRegistry.autodiscover`` (contrairement au
schéma Telegram, enregistré à la main depuis ``apps.py`` pour des raisons
historiques — les clés Telegram vont là-bas, section ``comm_telegram``).

Ce qui est ici et ce qui n'y est pas : on rapatrie les bornes qu'un opérateur
peut légitimement vouloir bouger (débit accepté, longueur d'un message,
cadence d'une caméra). Restent en dur les invariants de protocole et les
garde-fous d'injection — longueur d'un ``person_id``, préfixes réservés, nom
du groupe de diffusion, plafonds de purge des dictionnaires en RAM : les
tourner en réglages n'offrirait qu'un moyen de casser le canal.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    # ── Web ──────────────────────────────────────────────────────
    ConfigSection(
        key="comm_web", label="Communication · Web", icon="◇", order=31,
        description=(
            "Connexion WebSocket du frontend : ce qu'une socket a le droit "
            "d'envoyer, et à quel rythme."
        ),
    ),
    ConfigItem(
        key="comm.web.max_message_length", type="int", section="comm_web",
        group="Message", label="Longueur max d'un message (caractères)",
        default=2000, min=100, max=100_000, hot_reload=True,
        hint=(
            "Au-delà, le message est REFUSÉ (ack « too_long »), jamais coupé : "
            "tronquer laissait le navigateur afficher le texte complet qu'il "
            "avait peint lui-même pendant que le serveur en gardait une "
            "version raccourcie — deux phrases différentes, l'une marquée "
            "délivrée. Le monter coûte du prompt à chaque tour, ce message "
            "étant réémis tant qu'il reste dans le tampon court terme."
        ),
    ),
    ConfigItem(
        key="comm.web.rate_limit_max_messages", type="int", section="comm_web",
        group="Débit", label="Messages max par fenêtre",
        default=20, min=1, max=1000, hot_reload=True,
        hint=(
            "Fenêtre glissante par *connexion* (le pendant Telegram compte "
            "par compte, faute de connexion). Chaque message accepté coûte un "
            "tour de pipeline complet — prompt système, mémoire, outils."
        ),
    ),
    ConfigItem(
        key="comm.web.rate_limit_window_seconds", type="float",
        section="comm_web", group="Débit", label="Fenêtre de comptage (s)",
        default=10.0, min=0.5, max=3600.0, hot_reload=True,
        hint=(
            "Largeur de la fenêtre glissante, commune aux deux compteurs "
            "ci-dessus et ci-dessous (messages et trames de contrôle)."
        ),
    ),
    ConfigItem(
        key="comm.web.rate_limit_max_control", type="int", section="comm_web",
        group="Débit", label="Trames de contrôle max par fenêtre",
        default=12, min=1, max=1000, hot_reload=True,
        hint=(
            "Budget séparé pour ``sync`` et ``identify``. Ni l'un ni l'autre "
            "n'est gratuit — un rattrapage interroge une table que six "
            "boucles de fond écrivent, un identify réécrit le handle — et "
            "seuls les messages étaient comptés, ce qui revenait à ne faire "
            "payer que les trames contenant des mots."
        ),
    ),
    ConfigItem(
        key="comm.web.greeting_cooldown_seconds", type="float",
        section="comm_web", group="Accueil",
        label="Délai avant de resaluer quelqu'un (s)",
        default=3600.0, min=0.0, max=86400.0, hot_reload=True,
        hint=(
            "Compté par *personne*, pas par socket : un portable qui se "
            "réveille, un proxy qui recycle une socket inactive, la "
            "surveillance de liveness du client — chaque reconnexion "
            "achetait sinon un tour LLM complet, persisté, pendant qu'une "
            "vraie question attendait derrière. 0 = saluer à chaque "
            "connexion (le comportement d'avant ce plafond)."
        ),
    ),

    # ── Historique ───────────────────────────────────────────────
    ConfigSection(
        key="comm_historique", label="Communication · Historique", icon="≡",
        order=33,
        description=(
            "Ce qu'un client reçoit en ouvrant un onglet, et ce qu'il "
            "rattrape après une coupure."
        ),
    ),
    ConfigItem(
        key="comm.history.default_limit", type="int", section="comm_historique",
        label="Messages servis à l'ouverture",
        default=50, min=1, max=200, hot_reload=True,
        hint=(
            "Calé sur le plafond ChatOverlay.MAX_MESSAGES du frontend : le "
            "monter côté serveur seul envoie des bulles que l'interface "
            "évince immédiatement — de la bande passante et une requête pour "
            "rien. Les deux se règlent ensemble ou pas du tout."
        ),
    ),
    ConfigItem(
        key="comm.history.max_limit", type="int", section="comm_historique",
        label="Plafond dur d'un rattrapage",
        default=200, min=1, max=2000, hot_reload=True,
        hint=(
            "Un client absent une semaine n'a pas besoin de la semaine : il "
            "lui faut la fin, plus l'aveu que c'en est la fin (drapeau "
            "``truncated``). Doit rester ≥ « messages servis à l'ouverture », "
            "qu'il borne aussi ; sinon la valeur déclarée est ignorée au "
            "profit du repli."
        ),
    ),

    # ── Caméra ───────────────────────────────────────────────────
    # Section propre au *canal* (la socket qui reçoit les trames) ; le module
    # caméra, qui décide quoi en faire, garde la sienne (``module_camera``).
    ConfigSection(
        key="comm_camera", label="Communication · Caméra", icon="◉", order=34,
        description=(
            "Débit accepté sur la socket caméra. Une trame n'est jamais "
            "gratuite : elle est décodée pour son empreinte perceptuelle."
        ),
    ),
    ConfigItem(
        key="comm.camera.rate_limit_max_frames", type="int",
        section="comm_camera", label="Trames max par fenêtre",
        default=20, min=1, max=1000, hot_reload=True,
        hint=(
            "Fenêtre glissante par connexion. 20 pour 10 s est déjà large : "
            "le module n'analyse au mieux qu'une trame toutes les 30 s."
        ),
    ),
    ConfigItem(
        key="comm.camera.rate_limit_window_seconds", type="float",
        section="comm_camera", label="Fenêtre de comptage (s)",
        default=10.0, min=0.5, max=3600.0, hot_reload=True,
        hint="Largeur de la fenêtre glissante appliquée aux trames.",
    ),
    ConfigItem(
        key="comm.camera.min_frame_interval_seconds", type="float",
        section="comm_camera", label="Espacement minimal entre deux trames (s)",
        default=0.4, min=0.0, max=60.0, hot_reload=True,
        hint=(
            "Plancher partagé par *device*, en plus de la fenêtre ci-dessus, "
            "qui laisse deux trous : dix sockets ouvertes sur le même device "
            "donnent dix budgets, et une moyenne n'interdit pas la rafale — "
            "ses vingt trames peuvent tenir en deux cents millisecondes, soit "
            "vingt décodages d'image lancés d'un coup. 0 = plancher désactivé, "
            "la fenêtre reste seule."
        ),
    ),
]
