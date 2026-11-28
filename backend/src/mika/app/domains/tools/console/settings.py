"""Sa rubrique de réglages (ADR 0064, 0206, 0310) : les serveurs MCP branchés, dans Ses outils, derrière sa roue (Ses
outils › Paramètres) — la connexion de chacun ; qui peut quoi se règle sur sa fiche (« Accès aux outils »)."""

from __future__ import annotations

from typing import Any

from mika.adapters.mcp.config import McpConfig
from mika.app.domains.tools.settings import ToolsSettings
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX
from mika.kernel.inspect import Ref, plural


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Sa rubrique de réglages, pour ce serveur (``live`` : ses réglages ; le client MCP, ``live.parts["tools"]``)."""
    settings = live.settings.of(ToolsSettings)
    mcp = live.parts.get("tools")

    async def save_mcp(cfg: McpConfig) -> list[str]:
        await settings.save_mcp(cfg)
        if mcp is not None:  # les sessions dont la connexion a changé sont fermées, les serveurs actifs rejoints
            await mcp.reconfigure()
        return []

    def mcp_facts() -> list[tuple[str, Any]]:
        """Les serveurs réglés ici, puis ceux qu'un plugin système apporte (ADR 0066) : ils ne se règlent pas sur
        cette page, mais ils sont là — leur fiche dit où se règlent leurs bornes."""
        servers = settings.mcp().servers
        ready = sum(1 for x in servers.values() if x.enabled and x.ready)
        system = [st.name for st in (mcp.statuses() if mcp is not None else ()) if st.plugin]
        return [("Réglés ici", f"{len(servers)} ({plural(ready, 'actif et prêt', 'actifs et prêts')})"
                 if servers else "aucun"),
                *(("Du système", Ref("local", subject_url("serveur", name), f"{name}, réglé par son plugin"))
                  for name in system),
                ("État, outils et qui peut quoi", Ref("local", f"{PREFIX}/outils/serveurs",
                                                      "Outils › Venus d'ailleurs"))]

    return (
        SettingsSection("mcp", "Outils extérieurs", "plugins", McpConfig, settings.mcp, save_mcp, order=15,
                        lock=settings.writing,
                        description="Les serveurs MCP dont elle peut utiliser les outils. Jetons et variables "
                                    "secrètes chiffrés, jamais réaffichés.", facts=mcp_facts,
                        fixed_names=("servers",),
                        # qui peut quoi : sur la fiche du serveur, en lignes d'accès (« Accès aux outils », ADR 0131)
                        # — ici, la connexion seulement
                        exclude=tuple(f"servers.{k}" for k in ("access", "default_read", "default_act",
                                                               "default_keep")),
                        # dans Ses outils, en haut à droite, à côté de Venus d'ailleurs (ADR 0206) ; « Paramètres »,
                        # comme la roue à une page de Courrier, Teams et Réveils (audit du 2026-11-05, C6-Q3)
                        pages=(SettingsPage("serveurs-mcp", "Paramètres", ("servers",), description=(
                            "Chaque service branché (un serveur MCP) a sa page : à quoi il sert, pour elle — la ligne "
                            "de son catalogue —, puis "
                            "où le joindre (une adresse, ou une commande lancée ici, isolée) et ses bornes. Qui peut "
                            "quoi se règle sur sa fiche, dans « Accès aux outils »."), home="outils/parametres"),)),
    )
