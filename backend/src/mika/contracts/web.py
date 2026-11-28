"""Contrat du plugin ``web`` : chercher sur le web et lire des pages (ADR 0066).

Ses outils viennent du client MCP (le lot ``mcp.WEB_BUNDLE``) ; le plugin dit seulement s'il est actif.

- ``web.available`` : le web est actif, elle peut y aller chercher du neuf — ses centres d'intérêt l'y mènent
  (ADR 0160).
"""

from __future__ import annotations

from mika.kernel.facts import FactKey

OWNER = "web"
#: le plugin est actif : ses outils lui sont offerts, elle peut aller voir ce qu'il y a de neuf sur un sujet
AVAILABLE = FactKey("web.available", type=bool, doc="le web est actif")
