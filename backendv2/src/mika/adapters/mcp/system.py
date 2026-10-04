"""Les serveurs que Mika apporte elle-même (ADR 0066) : le serveur MCP d'un plugin système, joint par le client
comme un serveur local de l'opérateur, mais dont les outils sont **approuvés d'office**.

- Ils s'ajoutent à la configuration de l'opérateur (``config``), tant que leur plugin les donne (actif) ; un
  serveur de l'opérateur du même nom s'efface devant eux (le journal le dit, une fois).
- Leurs accords se **calculent**, jamais ne se rangent (``reviews``) : l'empreinte de chaque outil est prise, par la
  fonction même du client (``live_tool``), sur ce que le plugin dit que son serveur proposera. Un serveur qui
  proposerait autre chose verrait l'outil suspendu, comme chez n'importe quel serveur. Un outil qui se dit en
  lecture seule part sans accord ; un autre attendrait celui de l'opérateur.
- L'opérateur ne range rien pour eux (``saving`` retire leurs entrées avant d'écrire) : on les règle dans les
  paramètres de leur plugin.
- Si ce qui les donne échoue (des paramètres illisibles), il n'y en a aucun : rien d'offert plutôt qu'un outil
  faux.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mika.adapters.mcp.client import live_tool
from mika.adapters.mcp.config import McpConfig, McpServer, StoredReview

log = logging.getLogger("mika.mcp")

#: qui a donné l'accord d'un outil système
BY = "système"

Reviews = dict[str, dict[str, StoredReview]]


@dataclass(frozen=True, slots=True)
class Provided:
    """Un serveur système : comment le joindre, et ce qu'il proposera (son ``tools/list``)."""

    spec: McpServer
    tools: tuple[Mapping[str, Any], ...]


class SystemServers:
    def __init__(self, provide: Callable[[], Mapping[str, Provided]]) -> None:
        self._provide = provide
        self._said: set[str] = set()

    def current(self) -> dict[str, Provided]:
        try:
            return dict(self._provide())
        except Exception as exc:  # noqa: BLE001 — sans paramètres lisibles, aucun serveur système
            self._once(f"serveurs système indisponibles ({type(exc).__name__}) : aucun n'est offert")
            return {}

    def names(self) -> frozenset[str]:
        return frozenset(self.current())

    def config(self, base: McpConfig) -> McpConfig:
        mine = self.current()
        for name in sorted(set(base.servers) & set(mine)):
            self._once(f"le serveur « {name} » de l'opérateur s'efface devant celui du système du même nom")
        servers = {k: v for k, v in base.servers.items() if k not in mine}
        servers.update({k: p.spec for k, p in mine.items()})
        return McpConfig(servers=servers)

    def reviews(self, base: Reviews) -> Reviews:
        mine = self.current()
        out: Reviews = {k: dict(v) for k, v in base.items() if k not in mine}
        for name, provided in mine.items():
            out[name] = dict(_approved(provided.tools))
        return out

    def saving(self, save: Callable[[Reviews], Awaitable[Any]]) -> Callable[[Reviews], Awaitable[Any]]:
        async def saved(reviews: Reviews) -> Any:
            mine = self.names()
            return await save({k: v for k, v in reviews.items() if k not in mine})

        return saved

    def _once(self, message: str) -> None:
        if message not in self._said:
            self._said.add(message)
            log.warning("%s", message)


def _approved(raw_tools: Sequence[Mapping[str, Any]]) -> dict[str, StoredReview]:
    out = {}
    for raw in raw_tools:
        tool = live_tool(raw)
        if tool is None:
            continue
        reading = tool.read_only_hint
        out[tool.remote] = StoredReview(
            fingerprint=tool.fingerprint, enabled=True, nature="lecture" if reading else "action",
            approval="aucun" if reading else "operateur", server_description=tool.description, title=tool.title,
            schema=dict(tool.schema), by=BY)
    return out
