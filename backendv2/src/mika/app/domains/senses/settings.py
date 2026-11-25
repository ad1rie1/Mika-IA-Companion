"""Les réglages de ses sens (ADR 0310) : les flux qu'elle suit.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) : chaque
écriture s'y dit. La transcription des messages vocaux et le jeton des appareils restent dans ``Settings`` : la
première sert le prétraitement, le second partage avec la console MCP le mécanisme des jetons hachés.
"""

from __future__ import annotations

from mika.app.settings import SettingsPart

#: les adresses des flux qu'elle suit (RSS ou Atom)
FEEDS_KEY = "feeds"


class SensesSettings(SettingsPart):
    def feeds(self) -> list[str]:
        return [str(u) for u in (self._get(FEEDS_KEY) or [])]

    async def save_feeds(self, urls: list[str]) -> list[str]:
        clean = sorted({u.strip() for u in urls if u.strip().startswith(("http://", "https://"))})
        await self._put(FEEDS_KEY, clean)
        return clean
