"""Les messages du téléphone, tels que la couche ``app`` les relie (ADR 0120, 0310) : leur fiche.

Ce dossier porte leur porte HTTP (``desk.py`` : ``/api/phone/…``, le port ``phone``), leur câblage (``wiring.py`` :
la porte, l'application à télécharger, puis le port d'entrée et les notifications des téléphones) et leur module de
l'API par personne (``api.py`` : ses téléphones, ses messages, sa position, l'application ; ce qui attend son geste,
pour la barre du haut). Sa position se lit dans la localisation : il lit la carte.

Leur part du direct est dans ``live.py`` : ses messages, ses réponses offertes, et l'effet du moteur qu'est une
réponse proposée, décidée, partie.
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

PHONE = Domain(
    "phone",
    needs=("maps",),
    wiring="mika.app.domains.phone.wiring",
    api="mika.app.domains.phone.api",
    live="mika.app.domains.phone.live",
    plugins={
        "phone": ("Les messages WhatsApp, Messenger et SMS que ton téléphone lui relaie, et ce qu'elle en fait",
                  (),
                  ("Ses sens › Messages du téléphone", "sens/messages")),
    },
    labels={
        "faculties": {"phone": "Messages du téléphone"},
        "sections": {"phone_offers": "Ce que sont devenues ses réponses proposées sur le téléphone"},
        "processes": {"phone.expire": "Laisser tomber les réponses proposées sur le téléphone restées sans geste"},
        "events": {"phone.received": "Un message montré par le téléphone",
                   "phone.drafted": "Une réponse préparée pour le téléphone",
                   "phone.settled": "Une réponse proposée sur le téléphone : partie, laissée ou expirée"},
        "capabilities": {"phone.send": "Réponse téléphone"},
        "enrichers": {"phone": "Les messages du téléphone"},
    },
)
