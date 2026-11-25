"""Ses outils venus d'ailleurs, tels que la couche ``app`` les relie (ADR 0064, 0066, 0122, 0310) : leur fiche.

Ce dossier porte leurs réglages (``settings.py`` : les serveurs MCP branchés, les décisions sur leurs outils, les
accès réglés des serveurs du système), ce qu'un serveur MCP fait d'elle, écrit dans ces réglages (``store.py`` :
régler, brancher, retirer), les serveurs qu'apporte un plugin système (``system.py`` : la recherche web, le plugin
``web``), leur câblage (``wiring.py`` : le client MCP, le port ``mcp`` ; puis, le noyau là, ce qui le reconfigure et
ses outils prêtés à un agent, ``lending.py``, servis sous ``/mcp/pret/<nom>``), leur module de l'API par personne
(``api.py`` : ses services), leur part du direct (``live.py``), leur commande (``cli.py`` : ``mika mcp``) et leur part
de la console (``console/`` : la fiche d'un service branché, sa rubrique de réglages, leurs gabarits). Les services
MCP lancés sur cette machine vivent dans le dossier ``mcp/`` (``places``).

Restent au cadre : la destination « Ses outils » et ses onglets (``app/handmade/tabs/tools.py`` : tous ses outils,
leurs droits, ce qui vient d'ailleurs, le prêt) ; leurs points de prêt, que la console règle par les réglages du
serveur (« Prêter à un agent », ``inspector/pages/tools.py``, lit ``Settings.lent``) ; le relais MCP des fournisseurs
Claude Code (``adapters/mcp/relay``) ; le point MCP de la console (``inspector/mcp``) ; et les pages qui croisent les
domaines (qui peut quoi, ce que concerne un accord, les partages, la fiche d'une personne).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

TOOLS = Domain(
    "tools",
    places={"mcp": "les services MCP lancés sur cette machine, chacun dans sa cage"},
    settings="mika.app.domains.tools.settings",
    wiring="mika.app.domains.tools.wiring",
    api="mika.app.domains.tools.api",
    live="mika.app.domains.tools.live",
    console="mika.app.domains.tools.console",
    cli="mika.app.domains.tools.cli",
    plugins={
        "web": ("Sa recherche sur le web : ses bornes", (), ("La fiche du serveur « web »", "fiche/serveur/web")),
        "mcp": ("Les serveurs MCP : à quoi ils servent pour elle, où les joindre ; qui peut quoi, sur leur fiche",
                ("serveurs-mcp",), ("Outils › Venus d'ailleurs", "outils/serveurs")),
    },
    labels={
        "faculties": {"mcp": "Outils extérieurs", "web": "Recherche web"},
        "sections": {"services": "Ce que ses services extérieurs lui ont rendu",
                     # ADR 0255
                     "work_services": "Ce que ses services extérieurs ont rendu à son travail (après un accord)"},
        "reasons": {"service_answered": "Dire ce qu'un service extérieur a rendu"},
        "processes": {"mcp.watch": "Rejoindre les serveurs d'outils extérieurs",
                      "mcp.expire": "Refuser les accords restés sans réponse"},
        "events": {"mcp.consulted": "Une page consultée en travaillant",
                   "mcp.status": "L'état de ses serveurs extérieurs",
                   "mcp.answered": "Ce qu'un service extérieur a rendu"},
        "effects": {
            "mcp:effect.executed": ("agit", "Ce qu'un service a rendu", "le résultat d'un appel à un service branché"),
        },
        "bundles": {"mcp.*": "Service « {} »"},
        "capabilities": {"mcp.call": "Outil extérieur"},
        "enrichers": {"services": "Ses demandes aux outils extérieurs",
                      "work_services": "Ses demandes aux outils extérieurs, faites en travaillant"},
    },
)
