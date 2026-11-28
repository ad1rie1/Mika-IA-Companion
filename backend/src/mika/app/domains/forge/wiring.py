"""Le câblage de la Forge (ADR 0104, 0310) : ses réglages, une base par app, et l'hôte qui fait tourner ses apps —
les ports ``forge`` et ``forge_settings`` du noyau. Une fois le noyau là, l'hôte en lit ses outils (une app écrite ou
effacée : ils sont recalculés) et son heure. Le noyau arrête ses processus avec ses ports (``shutdown``)."""

from __future__ import annotations

from mika.adapters.forge import ForgeBases, ForgeHost
from mika.app import schema
from mika.app.domains.forge.settings import ForgeAppSettings
from mika.app.domains.forge.store import ForgeSettingsStore
from mika.app.wiring import Wiring

NAME = "forge"


def wire(w: Wiring) -> None:
    forge_settings = ForgeSettingsStore(w.settings.of(ForgeAppSettings))
    # une base par app, sur le même serveur que les siennes (ou des fichiers du dossier), son journal dans ``views``
    forge_bases = ForgeBases(w.data / "forge", server=schema.server_url() or None, prefix=schema.database_prefix(),
                             logs=w.bases["views"])
    forge = forge_settings.host = ForgeHost(w.data / "forge", config=forge_settings.values, bases=forge_bases)
    w.ports[NAME], w.ports["forge_settings"] = forge, forge_settings
    w.parts[NAME] = forge


def bind(w: Wiring) -> None:
    kernel, forge = w.port.kernel, w.parts[NAME]
    forge.on_change(kernel.refresh_tools)  # une app écrite ou effacée : ses outils aussi (ADR 0104)
    forge.zone = lambda: str(kernel.mind.registry.tz_of(kernel.mind.frame().root))  # son heure, dans ses apps
