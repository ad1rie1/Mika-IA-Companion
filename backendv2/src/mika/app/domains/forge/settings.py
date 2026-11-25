"""Les réglages des apps forgées (ADR 0104, 0310) : ce qu'un opérateur règle pour chaque app, des valeurs simples qui
surchargent son manifeste.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) : chaque
écriture s'y dit. Les fils de la Forge les lisent : ils sont tenus en mémoire, lus à l'ouverture des réglages
(``open``) — leur classe se prend donc dans le câblage du domaine, avant l'ouverture (``wiring.py``). Le port
``forge_settings`` (``store.py``) les rend à l'app, ses secrets ouverts.
"""

from __future__ import annotations

from typing import Any

from mika.app.settings import Settings, SettingsPart

FORGE_CONFIG_KEY = "forge_config"


class ForgeAppSettings(SettingsPart):
    def __init__(self, door: Settings) -> None:
        super().__init__(door)
        #: lus depuis les fils de la Forge : tenus en mémoire (une connexion SQLite
        #: appartient à son fil)
        self._forge: dict[str, dict[str, Any]] = {}

    async def open(self) -> None:
        data = self._get(FORGE_CONFIG_KEY) or {}
        self._forge = {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}

    # ── Réglages des apps forgées (valeurs simples, surchargent le manifeste) ──
    def forge_config(self, app: str | None = None) -> dict[str, Any]:
        """Sans base : appelable depuis n'importe quel fil (celui d'une app)."""
        if app is None:
            return {k: dict(v) for k, v in self._forge.items()}
        return dict(self._forge.get(app, {}))

    async def save_forge_config(self, app: str, values: dict[str, Any]) -> None:
        clean = {str(k)[:40]: v for k, v in values.items() if isinstance(v, str | int | float | bool)}
        data = self.forge_config()
        if clean:
            data[app] = clean
        else:
            data.pop(app, None)
        await self._put(FORGE_CONFIG_KEY, data)
        self._forge = data


#: la classe que le cadre prend par le nom du domaine (``Settings.named``)
SETTINGS = ForgeAppSettings
