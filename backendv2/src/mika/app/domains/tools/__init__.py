"""Ses outils venus d'ailleurs, tels que la couche ``app`` les relie (ADR 0064, 0066, 0310) : leur fiche.

Ce dossier porte ce qu'un serveur MCP fait d'elle, écrit dans les réglages (``store.py`` : régler, brancher,
retirer), les serveurs qu'apporte un plugin système (``system.py`` : la recherche web), ses outils prêtés à un agent
(``lending.py`` : ``/mcp/pret/<nom>``), son module de l'API par personne (``api.py`` : ses services) et sa part de la
console (``console/`` : la fiche d'un service branché, ses gabarits).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

TOOLS = Domain(
    "tools",
)
