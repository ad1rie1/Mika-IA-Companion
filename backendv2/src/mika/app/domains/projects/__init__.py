"""Les projets, tels que la couche ``app`` les relie (ADR 0031, 0310) : leur fiche.

Ce dossier porte leurs réglages (``settings.py`` : le jeton de leurs dépôts git distants), leur module de l'API par
personne (``api/`` : ses projets et « À faire », leur code, leur documentation, ce qu'on y gère, leur activité), le
point MCP de leur documentation (``docs_mcp.py`` : ``/mcp/moi``), leur part de la console (``console/`` : Activité › Projets, la fiche d'un projet et ses onglets, leurs gabarits,
leurs feuilles et leur script) et ce que l'aperçu en montre (``demo.py`` : une chaîne de travail d'exemple ;
``demo_git.py`` : un dépôt face à son distant, sans réseau ; ``demo_activity.py`` : des états fictifs de l'activité),
que l'aperçu du cadre pose. Ils lisent la Forge (les apps d'un projet), le courrier (la forme d'un fichier : une image
envoyée par MCP à leur documentation) et les outils (le protocole MCP).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

PROJECTS = Domain(
    "projects",
    needs=("forge", "mail", "tools"),
    settings="mika.app.domains.projects.settings",
    wiring="mika.app.domains.projects.wiring",
    api="mika.app.domains.projects.api",
    live="mika.app.domains.projects.live",
)
