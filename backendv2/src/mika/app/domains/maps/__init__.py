"""La carte et les voyages (ADR 0193–0196, 0244–0245, 0256, 0295) et la localisation (ADR 0119), tels que la couche
``app`` les relie (ADR 0310) : leur fiche.

Ce dossier porte leurs réglages (``settings.py`` : d'où viennent les tuiles, les lieux et les adresses, les
itinéraires, les données touristiques, le réchauffage des caches, les avis), leur câblage (``wiring.py`` : le port
``maps`` et les tuiles de la carte de sa position ; le réchauffage, démarré puis arrêté avec elle), les points de ce
réchauffage (``warm_points.py`` : la dernière position de chacun), leur module de l'API par personne (``api.py`` : le
fond de carte, les lieux, les fiches, les événements, les photos, les adresses, les itinéraires et tes voyages), leur
part du direct (``live.py``), leur commande (``cli.py`` : ``mika carte``), leur part du port d'entrée (``port.py`` :
la position que donne un téléphone et la case de la carte qui se précharge, les bulles de ses messages) et leur part
de la console (``console/`` : leurs rubriques de Réglages › Carte et téléphone, l'onglet Voyages et l'onglet Sa
position de la fiche d'une personne, le GPX d'un voyage). Leur dossier du dossier de données est ``cartes/``
(``places``, ADR 0193). Ils lisent ses sens : Sa position reprend les morceaux de Ses sens › Localisation.

Restent au cadre : l'aperçu de la console (``app/preview/`` : les voyages de Béa), la sauvegarde (``app/backup.py`` :
ce qu'elle garde de ``cartes/``), et, dans le même onglet de Réglages, les notifications du téléphone
(``app/settings_sections/map_phone.py``) ; Ses sens › Localisation est dessinée par ses sens.
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

MAPS = Domain(
    "maps",
    needs=("senses",),
    backup="mika.app.domains.maps.backup",
    places={"cartes": "la carte de sa position, l'index des lieux et les caches de la carte ; ses compteurs du "
                      "mois, eux, se sauvegardent"},
    settings="mika.app.domains.maps.settings",
    wiring="mika.app.domains.maps.wiring",
    api="mika.app.domains.maps.api",
    live="mika.app.domains.maps.live",
    console="mika.app.domains.maps.console",
    port="mika.app.domains.maps.port",
    cli="mika.app.domains.maps.cli",
    plugins={
        "location": ("D'où viennent les tuiles de la carte de sa position", ("carte",),
                     ("Ses sens › Localisation", "sens/positions")),
        "trips": ("Où chercher un lieu et une adresse, qui calcule les itinéraires, d'où viennent les données "
                  "touristiques et les événements (l'écran Carte de frontendv2)",
                  ("lieux", "itineraires", "tourisme", "rechauffage"), None),
    },
    labels={
        "faculties": {"location": "Localisation", "trips": "Carte et voyages"},
        "events": {
            "location.located": "Son téléphone a dit où était la personne",
            "location.cleared": "La personne ne partage plus où elle est",
            "trips.created": "Un voyage préparé",
            "trips.changed": "Un voyage modifié",
            "trips.stop_added": "Un arrêt ajouté à un voyage",
            "trips.stop_moved": "Un arrêt de voyage déplacé",
            "trips.stop_noted": "Un arrêt de voyage noté",
            "trips.stop_removed": "Un arrêt retiré d'un voyage",
            "trips.removed": "Un voyage supprimé",
            "trips.looked": "Elle a regardé la carte (des lieux, un trajet)",
            "trips.shown": "Elle a montré une carte dans la conversation",
        },
        # le port des cartes (``adapters/maps/desk.py``, ``MapsDesk``) ne déclare pas ``configured`` : il n'est pas
        # prêt seulement quand la composition ne le branche pas ; le serveur le branche toujours, et chaque appel dit
        # alors ce qui manque (rien de réglé, un serveur qui ne répond pas)
        "needs": {"maps": ("les lieux, les adresses et les itinéraires ne sont pas branchés", "lieux")},
    },
)
