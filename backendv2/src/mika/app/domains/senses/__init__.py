"""Ses sens (ses flux, sa caméra, ses appareils), tel que la couche ``app`` le relie (ADR 0310) : sa fiche.

Ce dossier porte ses réglages (``settings.py`` : les flux qu'elle suit), son câblage (``wiring.py`` : ses flux, le
port ``feeds``, et sa caméra, le port ``camera``, que l'application web remplit aussi), sa commande (``cli.py`` :
``mika rss``) et sa part de la console (``console/`` : les onglets de Ses sens, sa rubrique de réglages, leurs
gabarits). Ses onglets montrent aussi les messages du téléphone et sa localisation, rangés dans la même
destination : ils lisent le téléphone et la carte.

Restent au cadre, parce qu'ils règlent ce que tiennent les réglages du serveur : la transcription des messages vocaux
(elle sert le prétraitement) et le jeton des appareils (``POST /api/perceptions`` : il partage avec la console MCP le
mécanisme des jetons hachés), leurs rubriques de réglages et leurs commandes (``mika stt``, ``mika sensors``) ; et le
port d'entrée, qui reçoit ce que signalent ses appareils (``app/mindport.py``).
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain
from mika.inspector.catalog import Destination, MenuLink

SENSES = Domain(
    "senses",
    needs=("maps", "phone"),
    base=Base("feeds", models="mika.adapters.feeds.models",
              place="les flux suivis et leurs articles"),
    settings="mika.app.domains.senses.settings",
    wiring="mika.app.domains.senses.wiring",
    console="mika.app.domains.senses.console",
    cli="mika.app.domains.senses.cli",
    destination=Destination("sens", "Ses sens", "Ce qu'elle lit du monde (flux RSS), ce qu'elle voit "
                            "(caméra), ce que ses appareils lui signalent.",
                            # leurs réglages, derrière une seule roue : les flux suivis, l'accès des appareils, la
                            # transcription des messages vocaux (ADR 0206)
                            builtin=("sens.parametres-flux", "sens.parametres-appareils",
                                     "sens.parametres-transcription"),
                            gear=("parametres-flux", "parametres-appareils", "parametres-transcription")),
    menu=MenuLink("Ses sens", "sens", hint="Ce qu'elle lit, voit et reçoit"),
    plugins={
        "rss": ("Les adresses des flux qu'elle suit", ("flux",), ("Ses sens › Flux RSS", "sens/flux")),
        "camera": ("La fréquence de ses regards et la durée de ses observations", (),
                   ("Ses sens › Caméra", "sens/camera")),
        "sensors": ("Le jeton avec lequel les appareils lui envoient leurs signaux", ("appareils",),
                    ("Ses sens › Appareils", "sens/appareils")),
    },
    labels={
        "faculties": {"rss": "Flux RSS", "camera": "Caméra", "sensors": "Appareils"},
        "sections": {"headlines": "Les titres de ses flux", "views": "Ce que voit la caméra"},
        "reasons": {"rss_for": "Partager un titre qui lui a fait penser à cette personne"},
        "signals": {"entry": "un article", "view": "ce que voit la caméra"},
        "processes": {"rss.poll": "Relever les flux", "camera.look": "Regarder par la caméra"},
        "events": {"rss.read": "Un article lu", "rss.noticed": "Un article remarqué",
                   "rss.thought_of": "Un article qui lui a fait penser à quelqu'un",
                   "camera.seen": "Ce que la caméra a vu", "sensors.sensed": "Un appareil a signalé"},
        "enrichers": {"headlines": "Les titres de ses flux", "views": "Ce que voit la caméra"},
        "needs": {"feeds": ("elle ne suit aucun flux", "flux")},
    },
)
