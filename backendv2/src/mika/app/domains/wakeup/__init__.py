"""Les réveils par API, tels que la couche ``app`` les relie (ADR 0068, 0310) : leur fiche.

Ce dossier porte leur porte HTTP (``desk.py`` : ``POST /api/wake/<nom>``, le port ``wakeup``), leurs réglages et
leurs clés (``settings.py``), leur câblage (``wiring.py``), leur commande (``cli.py`` : ``mika wakeup``), leur part
du port d'entrée (``port.py`` : un appel reçu, journalisé puis interprété) et leur part de la console (``console/`` :
leur onglet, la fiche d'un réveil, leur page de réglages, leurs gabarits et leur feuille). Un réveil peut porter sur
un projet : ils lisent les projets.
"""

from __future__ import annotations

from mika.app.domains.domain import Domain
from mika.inspector.catalog import Destination, MenuLink

WAKEUP = Domain(
    "wakeup",
    needs=("projects",),
    settings="mika.app.domains.wakeup.settings",
    wiring="mika.app.domains.wakeup.wiring",
    console="mika.app.domains.wakeup.console",
    port="mika.app.domains.wakeup.port",
    cli="mika.app.domains.wakeup.cli",
    destination=Destination(
        "reveils", "Réveils par API", "Les réveils que des systèmes extérieurs lui envoient "
        "(POST /api/wake/<nom>) : les déclarer, leurs clés, leurs appels et ce qu'ils ont donné.",
        subjects=("reveil",),
        # leurs réglages (chaque réveil, ses consignes, ses bornes) : en haut à droite (ADR 0206)
        builtin=("reveils.parametres",), gear=("parametres",)),
    menu=MenuLink("Réveils par API", "reveils", hint="Ce qui peut la réveiller"),
    plugins={
        "wakeup": ("Ce que chaque réveil lui fait faire, quand, à qui elle en rend compte ; ses clés sur sa fiche",
                   ("reveils",), ("Réveils par API", "reveils")),
    },
    labels={
        "faculties": {"wakeup": "Réveils par API"},
        "sections": {"wake_order": "Ce qu'un réveil par API lui demande (ses consignes)",
                     "wake_text": "Ce qu'apporte l'appel d'un réveil par API (cité)",
                     "wake_reports": "Ce que ses réveils par API ont donné"},
        "reasons": {"wakeup": "Un réveil par API à traiter",
                    "wakeup_done": "Rendre compte de ce qu'un réveil par API a donné"},
        "processes": {"wakeup.expire": "Laisser tomber les réveils par API restés trop longtemps en attente"},
        "events": {"wakeup.called": "Un réveil par API reçu", "wakeup.reported": "Le compte rendu d'un réveil par API",
                   "wakeup.expired": "Un réveil par API expiré sans avoir été traité",
                   "wakeup.cancelled": "Un réveil par API annulé"},
        "enrichers": {"wakeup": "Ses réveils par API"},
        # ce que fait chaque famille de ses outils, dit à l'opératrice (Réglages › Droits)
        "about": {
            "wakeup": "conclure un réveil par API : le compte rendu de ce que l'appel lui a fait faire",
        },
    },
)
