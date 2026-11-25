"""Teams, tel que la couche ``app`` le relie (ADR 0069, 0186, 0251, 0300, 0301, 0310) : sa fiche.

Ce dossier porte sa porte HTTP (``desk.py`` : ``/api/teams/…``, qui est aussi le port ``teams_keys`` : les clés de
l'extension, une par compte), son câblage (``wiring.py`` : son cache, le port ``teams`` ; la porte ; l'extension à
télécharger), son module de l'API par personne (``api.py`` : ses comptes, leurs conversations, les réponses qu'elle y
prépare ; ce qui attend son geste, pour la barre du haut), l'extension à télécharger (``extension.py``), sa part du
direct (``live.py``), sa part de la console (``console/`` : ses onglets, la fiche d'une conversation et celle d'une
réponse, leurs gabarits et leur feuille) et sa commande (``cli.py`` : ``mika teams``). Effacer ce que l'extension
d'un compte a apporté efface aussi ce qu'il a fait voir dans l'annuaire : il lit l'annuaire.

Ses réglages (``Settings.teams``, ``teams_keys``…) et leur rubrique (Teams › Paramètres) restent au cadre pour
l'instant : des pages du cadre les lisent.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain
from mika.inspector.catalog import Destination, MenuLink

TEAMS = Domain(
    "teams",
    needs=("contacts",),
    base=Base("teams", models="mika.adapters.teams.models",
              place="ce que l'extension Teams a apporté, et ce qui doit en repartir"),
    wiring="mika.app.domains.teams.wiring",
    api="mika.app.domains.teams.api",
    live="mika.app.domains.teams.live",
    console="mika.app.domains.teams.console",
    cli="mika.app.domains.teams.cli",
    destination=Destination(
        "teams", "Teams", "Les conversations Teams que l'extension lui apporte, et les réponses "
        "qu'elle prépare à ta place : posées, à accepter, parties.",
        subjects=("conversation_teams", "reponse_teams"),
        # ses paramètres (« Actif », ses comptes) : en haut à droite, comme le courrier (ADR 0206)
        builtin=("teams.parametres",), gear=("parametres",)),
    menu=MenuLink("Teams", "teams", hint="Ce qu'elle lit et pose dans Teams"),
    plugins={
        "teams": ("Ses comptes : à qui, sa façon d'y écrire, sa signature ; la clé de chaque extension", ("teams",),
                  ("Teams", "teams/conversations")),
    },
    labels={
        "faculties": {"teams": "Teams"},
        "sections": {
            "teams_messages": "Ses messages Teams récents",
            "teams_drafts": "Ses réponses Teams et ce qu'elles sont devenues",
            "teams_voice": "Comment elle écrit dans Teams (à ta place)",
            "teams_task": "Le message Teams auquel elle prépare une réponse (cité)",
            "teams_ask": "Ce qu'on lui demande d'y répondre (Teams)",
        },
        "reasons": {"teams_draft": "Préparer une réponse à un message Teams"},
        "processes": {
            "teams.triage": "Trier les messages Teams reçus",
            "teams.images": "Regarder les images des messages Teams",
            "teams.expire": "Laisser tomber les réponses Teams restées sans accord ou sans envoi",
            "teams.answered": "Refuser ses réponses Teams auxquelles on a répondu autrement dans la discussion",
        },
        "events": {
            "teams.noticed": "Un message Teams remarqué",
            "teams.sent": "Une réponse Teams partie",
            "teams.draft_asked": "Une réponse Teams demandée",
            "teams.received": "Des messages Teams reçus de l'extension",
            "teams.settled": "Une réponse Teams posée, partie ou laissée",
            "teams.written": "Un message Teams écrit depuis le web, en file pour l'extension",
            "teams.images": "Une image d'un message Teams reçue de l'extension",
            "teams.image_seen": "Une image d'un message Teams regardée",
        },
        "effects": {"teams:teams.settled": ("agit", "Une réponse Teams partie",
                                            "elle apprend qu'elle est partie, retouchée ou non")},
        "capabilities": {"teams.send": "Réponse Teams"},
        "enrichers": {"teams": "Ses conversations Teams"},
    },
)
