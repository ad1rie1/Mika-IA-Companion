"""Sa part du port d'entrée (ADR 0310) : ce que lui signale un de ses appareils (``sense`` : ``POST /api/perceptions``,
la porte de ``adapters/web/app.py``), journalisé comme un signal de ses sens. ``app/mindport.py::KernelPort`` mêle
sa méthode aux siennes."""

from __future__ import annotations

from mika.app.domains.domain import PortPart
from mika.contracts import sensors as sensors_c
from mika.kernel.events import Content, Origin
from mika.vocab.affect import emotion_of


class SensesPort:
    """Ce qu'un appareil lui signale. Elle lit ``self.kernel``, que pose ``KernelPort``."""

    async def sense(self, device: str, text: str, *, pertinence: float = 0.5, emotion: str = "",
                    sensitivity: int = 1) -> int | None:
        emotion = emotion if emotion_of(emotion) is not None else ""
        level = max(0, min(3, int(sensitivity)))
        draft = sensors_c.SENSED.draft(
            source=f"appareil:{device}", kind="signal", summary=Content.of(text[:400], level=level),
            pertinence=max(0.0, min(1.0, float(pertinence))), emotion=emotion, intensity=0.2 if emotion else 0.0,
            sensitivity=level, device=device)
        commit = await self.kernel.mind.append([draft], emitter="sensors", correlation=f"appareil:{device}",
                                               origin=Origin.EXTERNAL)
        return commit.seqs[-1] if commit.seqs else None


PORT = PortPart(methods=SensesPort)
