"""Les réglages de Teams (ADR 0069, 0186, 0310) : ce qu'un opérateur règle, ses comptes compris, et la clé de
l'extension de chaque compte — dont seule l'empreinte est gardée.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``). Les pages du
cadre qui croisent plusieurs domaines (les partages, les droits, l'annuaire) les prennent par le nom du domaine
(``Settings.named("teams")``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mika.adapters.teams import TeamsConfig
from mika.app.settings import Settings, SettingsPart
from mika.ports.teams import DEFAULT_ACCOUNT as DEFAULT_TEAMS_ACCOUNT

log = logging.getLogger("mika.settings")

#: Teams (ADR 0069, 0186) : ce qu'un opérateur règle, ses comptes compris ; la clé de l'extension de chaque compte
#: à part (``TEAMS_KEYS_KEY``), dont seule l'empreinte est gardée
TEAMS_KEY = "teams"
TEAMS_KEYS_KEY = "teams_key"


class TeamsSettings(SettingsPart):
    def __init__(self, door: Settings) -> None:
        super().__init__(door)
        #: les clés de l'extension Teams, relues puis réécrites d'un seul tenant (pris sous ``writing`` ou seul : il
        #: ne prend jamais ``writing``)
        self._keys = asyncio.Lock()

    def teams(self) -> TeamsConfig:
        """Ce qu'un opérateur a réglé de Teams, ses comptes compris (ADR 0186 : une configuration d'avant devient le
        compte ``principal``) ; illisible, les valeurs par défaut (jamais bloquant)."""
        try:
            return TeamsConfig.model_validate(dict(self._get(TEAMS_KEY) or {}))
        except ValueError:
            log.warning("teams : réglages illisibles, valeurs par défaut")
            return TeamsConfig()

    async def save_teams(self, cfg: TeamsConfig) -> TeamsConfig:
        """Enregistre Teams ; la clé d'un compte retiré part avec lui (un compte recréé sous ce nom n'en a pas)."""
        cfg = TeamsConfig.model_validate(cfg.model_dump())
        await self._put(TEAMS_KEY, cfg.model_dump(mode="json"))
        async with self._keys:
            keys = self.teams_keys()
            kept = {k: v for k, v in keys.items() if k in cfg.accounts}
            if kept != keys:
                await self._put(TEAMS_KEYS_KEY, kept)
        return cfg

    def teams_keys(self) -> dict[str, dict[str, Any]]:
        """Compte → ``{digest, hint, created_at, by}`` de la clé de son extension : jamais la clé elle-même (un compte
        absent : aucune).

        La clé unique d'avant l'ADR 0186 (un seul Teams, jusqu'au 2026-11-04 : ``{digest, …}`` au premier niveau)
        se lit encore comme celle du compte ``principal`` — la reprise que promet l'ADR 0186. Cette branche part
        quand une révision de données de la base ``mind`` aura réécrit les réglages gardés à la forme du jour (audit
        du 2026-11-05), avec la voix à plat de ``TeamsConfig._from_flat_voice``."""
        got = self._get(TEAMS_KEYS_KEY)
        if not isinstance(got, dict):
            return {}
        if "digest" in got:  # la forme d'avant l'ADR 0186 : une seule clé
            return {DEFAULT_TEAMS_ACCOUNT: dict(got)} if got.get("digest") else {}
        return {str(k): dict(v) for k, v in got.items() if isinstance(v, dict) and v.get("digest")}

    async def save_teams_key(self, account: str, digest: str, hint: str, created_at: int, by: str) -> None:
        # relues puis réécrites d'un seul tenant (``_keys``) : deux comptes qui reçoivent leur clé en même temps
        # gardent chacun la sienne
        async with self._keys:
            keys = self.teams_keys()
            keys[account] = {"digest": digest, "hint": hint, "created_at": int(created_at), "by": by[:80]}
            await self._put(TEAMS_KEYS_KEY, keys)

    async def revoke_teams_key(self, account: str) -> bool:
        async with self._keys:
            keys = self.teams_keys()
            if account not in keys:
                return False
            del keys[account]
            await self._put(TEAMS_KEYS_KEY, keys)
            return True


#: la classe que le cadre prend par le nom du domaine (``Settings.named``)
SETTINGS = TeamsSettings
