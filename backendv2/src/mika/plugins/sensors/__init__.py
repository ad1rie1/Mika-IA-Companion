"""Le plugin ``sensors`` : l'entrée des appareils. Il ne fait que porter
l'événement (l'attention, qui reçoit tous les signaux, fait le reste)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.contracts import sensors as c
from mika.kernel.events import Content
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Block,
    Column,
    Disclosure,
    InspectContext,
    Meter,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    paginate,
)
from mika.vocab.affect import emotion_cell


@dataclass(frozen=True, slots=True)
class SensorsState:
    pass


SENSORS = Faculty("sensors", state=SensorsState, init=lambda p: SensorsState())
SENSORS.declare(*c.ALL)


# ── Inspection ────────────────────────────────────────────────────────────
#
# Lecture seule, au journal : qui lui parle, et ce qu'ils lui ont dit. Le nom
# d'un appareil et ce qu'il signale viennent d'ailleurs : du texte, jamais la
# clé d'un lien.

SHOWN = 50
#: des tuiles pour les appareils les plus récents seulement : le tableau, lui, les montre tous
TILES_SHOWN = 8
DEVICES_PAGE = 25


def _said(summary: Content) -> str:
    """Ce qu'un appareil a signalé, relu au journal (« (oublié) » s'il a été oublié)."""
    return summary.text if summary.text is not None else "(oublié)"


def _filter(name: Any) -> Ref | None:
    """Le lien qui filtre la page sur cet appareil (son nom n'est jamais que la valeur du filtre)."""
    return Ref.view("sensors", "appareils", str(name), appareil=str(name)[:200]) if name else None


def _devices_table(devices: list[tuple[Any, int, int]], device: str, ctx: InspectContext) -> Table:
    """Tous les appareils qui lui ont parlé, le plus récent d'abord."""
    page, pager = paginate(devices, ctx.pager("page_appareils", size=DEVICES_PAGE))
    rows = tuple(Row((_filter(name) or Text("—", kind="muted"), count, When(last)),
                     tone="info" if device and str(name) == device else "") for name, count, last in page)
    return Table(("appareil", Column("signaux", "num"), Column("le dernier", "fit")), rows,
                 title=f"Tous les appareils ({len(devices)})", empty="aucun appareil", pager=pager,
                 caption="Cliquer un appareil filtre la page sur lui.")


def _signal(e: Any) -> Row:
    d = e.data
    pertinence = float(d.pertinence or 0.0)
    return Row((When(e.at), Text(str(d.device or "—")), Text(_said(d.summary), clamp=300),
                Meter(pertinence, f"{pertinence:.2f}"), emotion_cell(d.emotion, d.intensity or None),
                Ref("event", str(e.seq), f"#{e.seq}")))


@SENSORS.inspect("appareils", title="Appareils", section="sens", order=40,
                 description="Ce que lui signalent des appareils (une sonnette, une domotique, un script).",
                 params=[Param("appareil", "Appareil", placeholder="nom exact d'un appareil")])
def _inspect(s: SensorsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    devices = ctx.tally(c.SENSED, "device")
    if not devices:
        return [Note("Aucun appareil ne lui a encore rien signalé : ils écrivent par POST /api/perceptions.",
                     tone="muted")]
    device = ctx.value("appareil") or ""
    before = ctx.int_param("avant", 0) or None
    sensed = ctx.events([c.SENSED], SHOWN, where=("device", device) if device else None, before=before)
    more = f" (les {TILES_SHOWN} plus récents sur {len(devices)} : tous dans le tableau)" \
        if len(devices) > TILES_SHOWN else ""
    tiles = Stats(tuple(
        Stat(str(name or "—"), count, sub=f"le dernier : {ctx.when(last)}", href=_filter(name),
             tone="info" if device and str(name) == device else "")
        for name, count, last in devices[:TILES_SHOWN]), title="Les appareils qui lui parlent" + more)
    older = (("avant", str(sensed[-1].seq)),) if len(sensed) == SHOWN else ()
    title = "Ce qu'ils lui ont signalé" if not device else f"Ce que « {device} » lui a signalé"
    # replié, sauf quand les tuiles n'en montrent qu'une partie ou qu'on y tourne les pages
    listing = Disclosure("Tous les appareils", (_devices_table(devices, device, ctx),),
                         open=len(devices) > TILES_SHOWN or ctx.int_param("page_appareils", 1) > 1)
    return [tiles, listing, Table(
        (Column("quand", "fit"), "appareil", "ce qu'il signale", Column("pertinence", "fit"),
         Column("émotion", "fit"), Column("journal", "fit")),
        tuple(_signal(e) for e in sensed), title=title + (" — plus anciens" if before else ""),
        empty="rien de cet appareil" if device else "rien pour l'instant",
        # la dernière page garde sa pagination : « plus récents » y ramène
        pager=Pager(param="avant", size=SHOWN, older=older) if older or before else None)]
