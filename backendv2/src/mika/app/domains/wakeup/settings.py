"""Les réglages des réveils par API (ADR 0068, 0117, 0310) : les réveils déclarés, et leurs clés.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) : chaque
écriture s'y dit. Une clé n'est jamais gardée en clair — son empreinte, son début ; pour un réveil signé, sa copie
scellée, qu'il faut relire pour vérifier une signature.
"""

from __future__ import annotations

import logging
from typing import Any

from mika.app.domains.wakeup.desk import WakeEndpoint, WakeupConfig
from mika.app.settings import SettingsPart

log = logging.getLogger("mika.settings")

#: les réveils par API (ADR 0068) ; leurs clés à part, dont seule l'empreinte est gardée
WAKEUP_KEY = "wakeup"
WAKEUP_KEYS_KEY = "wakeup_keys"


class WakeupSettings(SettingsPart):
    def wakeup(self) -> WakeupConfig:
        """Les réveils déclarés ; un réveil illisible est écarté, jamais bloquant."""
        endpoints = {}
        for name, spec in dict(dict(self._get(WAKEUP_KEY) or {}).get("endpoints") or {}).items():
            try:
                endpoints[str(name)] = WakeEndpoint.model_validate(spec)
            except ValueError:
                log.warning("réveils : « %s » est illisible, il est ignoré", str(name)[:40])
        try:
            return WakeupConfig(endpoints=endpoints)
        except ValueError:
            return WakeupConfig()

    async def save_wakeup(self, cfg: WakeupConfig) -> WakeupConfig:
        """Enregistre les réveils ; la clé d'un réveil retiré part avec lui (un réveil recréé sous ce nom n'en a
        pas), et la copie chiffrée de la clé d'un réveil qui ne signe plus aussi (ADR 0117)."""
        cfg = WakeupConfig.model_validate({"endpoints": dict(cfg.endpoints)})
        await self._put(WAKEUP_KEY, {"endpoints": {n: ep.model_dump(mode="json") for n, ep in cfg.endpoints.items()}})
        keys = self.wakeup_keys()
        kept = {n: k if cfg.endpoints[n].signed else {f: v for f, v in k.items() if f != "sealed"}
                for n, k in keys.items() if n in cfg.endpoints}
        if kept != keys:
            await self._put(WAKEUP_KEYS_KEY, kept)
        return cfg

    def wakeup_keys(self) -> dict[str, dict[str, Any]]:
        """Réveil → ``{digest, hint, created_at, by}`` : jamais la clé en clair — et, pour un réveil signé,
        ``sealed`` : la clé chiffrée, qu'il faut relire pour vérifier une signature."""
        return {str(n): dict(k) for n, k in dict(self._get(WAKEUP_KEYS_KEY) or {}).items() if isinstance(k, dict)}

    async def save_wakeup_key(self, name: str, digest: str, hint: str, created_at: int, by: str,
                              sealed: str = "") -> None:
        keys = self.wakeup_keys()
        keys[name] = {"digest": digest, "hint": hint, "created_at": int(created_at), "by": by[:80]}
        if sealed:
            keys[name]["sealed"] = sealed
        await self._put(WAKEUP_KEYS_KEY, keys)

    async def revoke_wakeup_key(self, name: str) -> bool:
        keys = self.wakeup_keys()
        if name not in keys:
            return False
        del keys[name]
        await self._put(WAKEUP_KEYS_KEY, keys)
        return True
