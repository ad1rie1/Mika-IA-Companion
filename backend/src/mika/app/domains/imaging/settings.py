"""Les réglages des dessins (ADR 0061, 0310, 0317) : leurs fournisseurs d'images, la clé de chacun, qui dessine quoi.

Rangés dans les réglages du serveur (``mind.db``), sous la clé ``imaging``, par leur porte
(``app/settings.py::SettingsPart``) : chaque écriture s'y dit. La clé d'API d'un fournisseur n'est jamais gardée en
clair : scellée par la porte (``api_key_sealed``), rouverte à la lecture, jamais réaffichée. Aucun fournisseur : la
génération d'images est désactivée.
"""

from __future__ import annotations

from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig
from mika.app.settings import SettingsPart
from mika.ports.imaging import ROLES as IMAGE_ROLES

#: les fournisseurs d'images et leurs rôles (clés scellées)
IMAGING_KEY = "imaging"
#: ce que la fiche d'un fournisseur garde scellé
SEALED = ("api_key",)


class ImagingSettings(SettingsPart):
    def imaging(self) -> ImagingConfig:
        """Les fournisseurs d'images (clés déchiffrées) ; aucun : la génération d'images est désactivée. Un
        rôle qui n'existe plus est ignoré, jamais bloquant."""
        data = self._get(IMAGING_KEY) or {}
        backends = {}
        for name, spec in (data.get("backends") or {}).items():
            backends[name] = ImageBackendSpec.model_validate(self._opened(spec, SEALED))
        routes = {r: b for r, b in dict(data.get("routes") or {}).items() if r in IMAGE_ROLES}
        return ImagingConfig(backends=backends, routes=routes)

    async def save_imaging(self, cfg: ImagingConfig) -> ImagingConfig:
        """Enregistre les fournisseurs d'images et rend la configuration qui vaut désormais (revalidée : le
        premier fournisseur déclaré sert « dessiner » d'office) ; refusée, en le disant, si elle a un problème."""
        cfg = ImagingConfig.model_validate({"backends": dict(cfg.backends), "routes": dict(cfg.routes)})
        problems = cfg.problems()
        if problems:
            raise ValueError("; ".join(problems))
        backends = {}
        for name, spec in cfg.backends.items():
            backends[name] = self._sealed(spec.model_dump(), SEALED)
        await self._put(IMAGING_KEY, {"backends": backends, "routes": dict(cfg.routes)})
        return cfg


#: la classe que le cadre prend par le nom du domaine (``Settings.named``)
SETTINGS = ImagingSettings
