"""Les réglages de ses outils venus d'ailleurs (ADR 0064, 0066, 0131, 0310) : les serveurs MCP branchés, les
décisions de l'opérateur sur leurs outils, et les accès réglés des serveurs du système (la recherche web).

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) : chaque
écriture s'y dit. Le jeton et les variables secrètes d'un serveur y sont scellés. Ce qu'un serveur fait d'elle se
relit puis se réécrit d'un seul tenant, sous le verrou des réglages (``writing``) : ``store.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from mika.adapters.mcp.config import McpConfig, McpServer, StoredReview
from mika.app.settings import SettingsPart

log = logging.getLogger("mika.settings")

#: les serveurs MCP branchés (ADR 0064 ; jeton et variables secrètes scellés) et les décisions sur leurs outils
MCP_KEY = "mcp"
MCP_TOOLS_KEY = "mcp_tools"
#: les lignes d'accès des serveurs du système (la recherche web), réglées sur leur fiche (ADR 0131)
MCP_SYSTEM_ACCESS_KEY = "mcp_system_access"
#: ce qu'on règle d'un serveur du système : ses accès seulement — le reste suit les paramètres de son plugin
SYSTEM_ACCESS_FIELDS = ("access", "default_read", "default_act", "default_keep")


class ToolsSettings(SettingsPart):
    # ── Outils extérieurs (MCP, ADR 0064) ──
    #: les secrets d'un serveur MCP (scellés à part)
    MCP_SECRETS = ("token", "secret_env", "secret_headers")

    def mcp(self) -> McpConfig:
        """Les serveurs MCP (secrets déchiffrés) ; un serveur illisible est écarté, jamais bloquant."""
        servers = {}
        for name, spec in dict(dict(self._get(MCP_KEY) or {}).get("servers") or {}).items():
            spec = dict(spec)
            for k in self.MCP_SECRETS:
                spec[k] = self.box.open(spec.pop(f"{k}_sealed", ""))
            try:
                servers[name] = McpServer.model_validate(spec)
            except ValueError:
                log.warning("mcp : le serveur « %s » est illisible, il est ignoré", str(name)[:40])
        try:
            return McpConfig(servers=servers)
        except ValueError:
            return McpConfig()

    async def save_mcp(self, cfg: McpConfig) -> McpConfig:
        cfg = McpConfig.model_validate({"servers": dict(cfg.servers)})
        servers = {}
        for name, server in cfg.servers.items():
            spec = server.model_dump(mode="json")
            for k in self.MCP_SECRETS:
                spec[f"{k}_sealed"] = self.box.seal(spec.pop(k))
            servers[name] = spec
        await self._put(MCP_KEY, {"servers": servers})
        return cfg

    def mcp_tools(self) -> dict[str, dict[str, StoredReview]]:
        """Les décisions de l'opérateur sur les outils des serveurs : serveur → outil → décision."""
        out: dict[str, dict[str, StoredReview]] = {}
        for server, tools in dict(self._get(MCP_TOOLS_KEY) or {}).items():
            kept = {}
            for remote, raw in dict(tools or {}).items():
                try:
                    kept[str(remote)] = StoredReview.model_validate(raw)
                except ValueError:
                    continue
            out[str(server)] = kept
        return out

    async def save_mcp_tools(self, reviews: dict[str, dict[str, StoredReview]]) -> None:
        """Les décisions sur les outils : serveur → outil → décision."""
        await self._put(MCP_TOOLS_KEY, {s: {r: v.model_dump(mode="json", by_alias=True) for r, v in tools.items()}
                                        for s, tools in reviews.items()})

    def mcp_system_access(self) -> dict[str, dict[str, Any]]:
        """Les accès réglés des serveurs du système : serveur → ses lignes et sa ligne par défaut. Rien d'enregistré
        sur sa fiche : celles de son plugin (``app/domains/tools/system.py``)."""
        raw = dict(self._get(MCP_SYSTEM_ACCESS_KEY) or {})
        return {str(k): {f: v[f] for f in SYSTEM_ACCESS_FIELDS if f in v} for k, v in raw.items()
                if isinstance(v, dict)}

    async def save_mcp_system_access(self, server: str, fields: Mapping[str, Any]) -> None:
        current = dict(self._get(MCP_SYSTEM_ACCESS_KEY) or {})
        current[server] = {f: fields[f] for f in SYSTEM_ACCESS_FIELDS if f in fields}
        await self._put(MCP_SYSTEM_ACCESS_KEY, current)


#: la classe que le cadre prend par le nom du domaine (``Settings.named``)
SETTINGS = ToolsSettings
