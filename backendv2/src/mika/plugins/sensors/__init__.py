"""Le plugin ``sensors`` : l'entrée des appareils. Il ne fait que porter
l'événement (l'attention, qui reçoit tous les signaux, fait le reste)."""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts import sensors as c
from mika.kernel.events import Content
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, InspectContext, Note, Ref, Table


@dataclass(frozen=True, slots=True)
class SensorsState:
    pass


SENSORS = Faculty("sensors", state=SensorsState, init=lambda p: SensorsState())
SENSORS.declare(*c.ALL)


# ── Inspection ────────────────────────────────────────────────────────────

SHOWN = 50
DEVICES_SHOWN = 20


def _said(summary: Content) -> str:
    """Ce qu'un appareil a signalé, relu au journal (« (oublié) » s'il a été oublié)."""
    return summary.text if summary.text is not None else "(oublié)"


@SENSORS.inspect("appareils", title="Appareils")
def _inspect(s: SensorsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    sensed = ctx.events([c.SENSED], SHOWN)
    if not sensed:
        return [Note("Aucun appareil ne lui a encore rien signalé : ils écrivent par POST /api/perceptions.",
                     tone="mut")]
    devices = ctx.tally(c.SENSED, "device")[:DEVICES_SHOWN]
    return [
        Table(("appareil", "signaux", "le dernier"),
              tuple((str(device or "—"), count, ctx.when(last)) for device, count, last in devices),
              title="Les appareils qui lui parlent"),
        Table(("quand", "appareil", "ce qu'il signale", "pertinence", "émotion", "journal"),
              tuple((ctx.when(e.at), str(e.data.device or "—"), _said(e.data.summary),
                     f"{float(e.data.pertinence or 0.0):.2f}", str(e.data.emotion or "—"),
                     Ref("event", str(e.seq), f"#{e.seq}")) for e in sensed),
              title=f"Ce qu'ils lui ont signalé (les {SHOWN} plus récents)"),
    ]
