"""La Forge, telle que la couche ``app`` la relie (ADR 0104, 0310) : sa fiche.

Ce dossier porte ses réglages (``settings.py`` : ce qu'un opérateur règle pour chaque app, tenu en mémoire pour les
fils de la Forge), le port ``forge_settings`` (``store.py`` : ces réglages rendus à l'app, ses secrets ouverts), son
câblage (``wiring.py`` : ses réglages, une base par app et l'hôte qui fait tourner ses apps ; puis, le noyau là, ses
outils et son heure), sa commande (``cli.py`` : ``mika forge promote|demote``) et sa part de la console
(``console/`` : l'onglet Apps forgées, son gabarit et sa feuille). Le journal de ses apps est rangé dans la base
``views`` (``models``) ; ses apps, leurs versions et leurs bases, dans le dossier ``forge/`` (``places``).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain
from mika.inspector.catalog import Destination, MenuLink

FORGE = Domain(
    "forge",
    models=("mika.adapters.forge.bases",),
    places={"forge": "ses apps forgées, leurs versions et leurs bases"},
    wiring="mika.app.domains.forge.wiring",
    console="mika.app.domains.forge.console",
    cli="mika.app.domains.forge.cli",
    destination=Destination("apps", "Apps forgées", "Les petites apps qu'elle écrit elle-même.", subjects=("app",)),
    menu=MenuLink("Apps forgées", "apps", hint="Ce qu'elle a construit"),
    plugins={
        "forge": ("Le comportement du moteur qui exécute ses apps ; les réglages d'une app restent sur sa fiche", (),
                  ("Apps forgées", "apps")),
    },
    labels={
        "faculties": {"forge": "Moteur de la Forge", "forge_signals": "Signaux de ses apps"},
        "sections": {"apps": "Ses apps forgées", "app_news": "Ce que ses apps ont trouvé pour la personne",
                     "app_signals": "Ce qu'une app a mis dans sa file",
                     "app_consignes": "Les consignes du projet d'une app",
                     "app_calls": "Ce que ses apps lui ont rendu après un accord"},
        "reasons": {"app_answered": "Dire ce qu'une app a rendu après un accord",
                    "app_news": "Dire ce qu'une app a trouvé",
                    "app_alert": "Prévenir d'une urgence qu'une app a trouvée",
                    "app_triage": "Lire la file de signaux d'une app"},
        "processes": {"forge.tick": "Faire tourner les apps", "forge.events": "Transmettre les événements aux apps",
                      "forge.discover": "Découvrir les apps",
                      "forge.calls_expire": "Refuser les appels d'apps restés sans accord"},
        "events": {"forge.answered": "Ce qu'une app a rendu après un accord",
                   "forge.access_set": "Les accès d'une app sans projet réglés", "forge.emitted": "Une app a signalé",
                   "forge.handled": "Une app a traité un événement",
                   "forge.proved": "Une version d'app prouvée à l'essai", "forge.signaled": "Une app l'a interpellée",
                   "forge.switched": "Une app allumée ou éteinte", "forge.queued": "Un signal d'app mis en file",
                   "forge.judged": "Une file d'app lue",
                   "forge.raised": "Une app d'un projet a signalé (son nom, sans le texte du signal)",
                   "forge.ticked": "Une app a tourné", "forge.written": "Une app écrite"},
        "effects": {
            "forge:effect.executed": ("agit", "Une app installée", "une version de ses apps forgées, après ton accord"),
            "forge:effect.resolved": ("agit", "Une version d'app refusée",
                                      "mise de côté puis refusée : elle ne traîne plus"),
        },
        "bundles": {"forge": "La Forge (écrire ses apps)", "forge_signals": "Ce que ses apps lui signalent",
                    "forge_apps.*": "Son app « {} »"},
        "capabilities": {"forge.call": "Outil d'app", "forge.install": "Version d'app"},
        "enrichers": {"apps": "Ses apps forgées", "calls": "Ses demandes à ses apps",
                      "signals": "Ce qu'une app a mis dans sa file",
                      "news": "Ce que ses apps ont trouvé pour la personne"},
    },
)
