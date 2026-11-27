"""Le câblage des dessins (ADR 0061, 0063, 0317) : la passerelle d'images vivante, qui est le port ``imaging`` du
noyau — vide tant qu'aucun fournisseur n'est branché ; une fois le serveur là, la trace de chaque appel va au
registre des appels, commun avec celui des modèles ; dans le cycle de vie, elle se branche sur ses réglages
(``start``) et se ferme en dernier (``release``)."""

from __future__ import annotations

import logging
from typing import Any

from mika.adapters.imaging.config import LiveImaging, build_gateway
from mika.adapters.imaging.gateway import ImageTrace
from mika.adapters.llm.calls import CallLog
from mika.adapters.llm.gateway import LLMTrace
from mika.app.domains.imaging.settings import ImagingSettings
from mika.app.wiring import Wiring

NAME = "imaging"
#: le journal du serveur : ce que son démarrage dit de leur configuration y reste, sous le même nom
log = logging.getLogger("mika.server")


class ImagingService:
    """Les dessins en service (``Live.parts["imaging"]``) : la passerelle d'images vivante (``gateway``, le port
    ``imaging``), qui se rebranche sur leurs réglages sans redémarrer (``reload``), et la trace de chacun de ses
    appels (``trace``)."""

    def __init__(self, settings: ImagingSettings, clock: Any) -> None:
        self.settings = settings
        self.clock = clock
        #: la génération d'images (désactivée tant qu'aucun fournisseur n'est branché, ADR 0061)
        self.gateway = LiveImaging()
        #: le registre des appels du serveur (``Live.calls``), posé par ``bind`` : celui des modèles
        self.calls: CallLog | None = None

    def trace(self, tr: ImageTrace) -> None:
        """Un appel d'images : gardé en mémoire, et au registre des appels sous le rôle ``image.<rôle>`` — ce
        qu'il a coûté s'ajoute à celui des modèles."""
        self.gateway.traces.append(tr)
        if self.calls is not None:
            self.calls.record(LLMTrace(
                at=tr.at, role=f"image.{tr.role}", backend=tr.backend, model=tr.model, lane=tr.lane,
                priority=tr.priority, latency_us=tr.latency_us, wait_us=tr.wait_us,
                input_tokens=tr.text_tokens + tr.image_tokens, output_tokens=tr.output_tokens, outcome=tr.outcome,
                call_id=tr.call_id, cost_usd=tr.cost_usd, correlation=tr.correlation))

    async def reload(self) -> list[str]:
        """Rebranche la génération d'images sur ses réglages ; sans fournisseur, elle n'existe pas."""
        cfg = self.settings.imaging()
        problems = cfg.problems()
        if cfg.backends and not problems:
            self.gateway.set(build_gateway(cfg, self.clock, on_trace=self.trace))
        else:
            self.gateway.set(None)
        return problems


def wire(w: Wiring) -> None:
    """Avant le noyau : leurs réglages, et la passerelle, sans fournisseur jusqu'au démarrage (le port ``imaging``)."""
    service = ImagingService(w.settings.of(ImagingSettings), w.clock)
    w.ports[NAME] = service.gateway
    w.parts[NAME] = service


def bind(w: Wiring) -> None:
    """Une fois le serveur là : la trace de chaque appel va à son registre des appels."""
    w.parts[NAME].calls = w.live.calls


async def start(w: Wiring) -> None:
    """Leurs réglages ouverts : la passerelle s'y branche ; une configuration qui a un problème est dite au journal."""
    for problem in await w.parts[NAME].reload():
        log.warning("configuration des images : %s", problem)


async def release(w: Wiring) -> None:
    await w.parts[NAME].gateway.aclose()
