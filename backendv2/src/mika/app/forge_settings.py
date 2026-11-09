"""Le port ``forge_settings`` : les réglages d'une app forgée, rangés par ``Settings``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.adapters.forge import ForgeHost
from mika.app.settings import Settings


class ForgeSettingsStore:
    """Le port ``forge_settings`` : ce qu'un opérateur règle pour une app forgée,
    rangé par ``Settings``. Un secret y est **scellé** (``SecretBox``) et rendu en
    clair à l'app seulement (``values`` sert ``api.config``) ; une liste y est
    rangée en lignes. Ce qui n'est plus déclaré par l'app n'est plus rendu."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.host: ForgeHost | None = None

    def _fields(self, app: str) -> dict[str, Any]:
        info = self.host.info(app) if self.host is not None else None
        return {f.path: f for f in info.config_fields} if info is not None else {}

    def values(self, app: str) -> dict[str, Any]:
        fields = self._fields(app)
        out: dict[str, Any] = {}
        for key, value in self.settings.forge_config(app).items():
            f = fields.get(key)
            if f is None:
                continue
            if f.kind == "secret":
                out[key] = self.settings.box.open(str(value)) if value else ""
            elif f.kind == "lines" and isinstance(value, str):
                out[key] = [line for line in value.split("\n") if line]
            else:
                out[key] = value
        return out

    async def save(self, app: str, values: Mapping[str, Any]) -> None:
        fields = self._fields(app)
        clean: dict[str, Any] = {}
        for key, value in values.items():
            f = fields.get(key)
            if f is None or value is None:
                continue
            if f.kind == "secret":
                if value:
                    clean[key] = self.settings.box.seal(str(value))
            elif f.kind == "lines":
                clean[key] = "\n".join(str(v) for v in value) if isinstance(value, list | tuple) else str(value)
            else:
                clean[key] = value
        await self.settings.save_forge_config(app, clean)
