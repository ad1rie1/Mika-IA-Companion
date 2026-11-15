"""Ce que la console montre de la caméra (Connexions › Ses sens › Caméra) — jamais une image : ses appareils
(reçoivent-ils encore ?), ce qu'elle voit en ce moment, ses derniers regards — des textes relus au journal.
"""

from __future__ import annotations

from typing import Any

from mika.contracts import camera as c
from mika.kernel.clock import MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    FORGOTTEN,
    Badge,
    Block,
    Column,
    Disclosure,
    Entry,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Pager,
    Ref,
    Stat,
    Stats,
    Table,
    Text,
    Timeline,
    When,
    content_text,
    paginate,
)
from mika.plugins.camera import CAMERA, CameraParams, CameraState, params

#: une page de ses regards (au journal, du plus récent au plus ancien), des appareils, de ce qu'elle a vu
PAGE = 25
#: des tuiles pour les premiers appareils seulement : le tableau, lui, les montre tous
TILES_SHOWN = 8


def _devices(port: Any, frame: Frame, ctx: InspectContext, p: CameraParams) -> list[Block]:
    names = port.devices()
    if not names:
        return [Note("Aucun appareil ne s'est encore connecté.", tone="muted")]
    snaps = {device: port.latest(device) for device in names}
    fresh = {device: snap is not None and frame.now - snap.at <= p.fresh_us for device, snap in snaps.items()}
    live = sum(fresh.values())
    tiles = tuple(Stat(device, Badge("en direct", "ok") if fresh[device] else Badge("silencieux", "muted"),
                       sub=f"dernière image : {ctx.when(snap.at)}" if snap is not None else "aucune image encore",
                       tone="ok" if fresh[device] else "")
                  for device, snap in list(snaps.items())[:TILES_SHOWN])
    page, pager = paginate(names, ctx.pager("page_appareils", size=PAGE))
    # jamais l'image elle-même : sa taille et son empreinte suffisent
    rows = tuple((device, "oui" if fresh[device] else "non", When(snap.at) if snap is not None else None,
                  snap.mime if snap is not None else "—",
                  f"{max(1, len(snap.data) // 1024)} Ko" if snap is not None else "—",
                  Text(snap.digest, kind="mono") if snap is not None else "—")
                 for device, snap in ((d, snaps[d]) for d in page))
    note = (Note(f"{live} appareil(s) envoie(nt) des images en ce moment.", tone="ok") if live
            else Note("Aucun appareil n'envoie d'image en ce moment.", tone="muted"))
    more = len(names) > TILES_SHOWN
    title = f"Appareils (les {TILES_SHOWN} premiers sur {len(names)} : tous dans le détail)" if more else "Appareils"
    return [note, Stats(tiles, title=title),
            # replié, sauf quand les tuiles n'en montrent qu'une partie ou qu'on y tourne les pages
            Disclosure("Détail des appareils", (Table(
                ("appareil", "envoie", "dernière image", "format", "taille", "empreinte"), rows,
                title=f"Appareils ({len(names)})", empty="aucun appareil ne s'est encore connecté", pager=pager),),
                open=more or ctx.int_param("page_appareils", 1) > 1)]


@CAMERA.inspect("camera", title="Caméra", section="sens", order=30,
                description="Ce qu'elle voit de la pièce : ses appareils, ce qu'elle a vu, jamais les images.")
def _inspect(s: CameraState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("camera")
    p = params(frame.env.params_of("camera", frame.root))
    blocks: list[Block] = (_devices(port, frame, ctx, p) if port is not None else
                           [Note("Caméra non configurée : aucun appareil ne peut lui envoyer d'images.",
                                 tone="muted")])
    blocks.insert(0, Nav((
        NavItem("Connecter une caméra", Ref.settings("appareils", "Accès des appareils")),
        NavItem("Régler les observations", Ref.settings("comportement-camera", "Réglages de la caméra")),)))
    views, shown = paginate(frame.get(c.VIEWS), ctx.pager("page_vus", size=PAGE))
    texts = ctx.store.content([v.summary_ref for v in views if v.summary_ref])
    blocks.append(Table(
        ("appareil", Column("vu", "fit"), Column("fraîcheur", "fit"), Column("notable", "fit"), "ce qu'elle a vu"),
        tuple((v.device, When(v.at),
               Badge("elle en parle encore", "ok") if frame.now - v.at <= p.shown_for_us else Badge("ancien", "muted"),
               Badge("notable", "warn") if v.notable else Badge("calme", "muted"),
               Text(texts.get(v.summary_ref, FORGOTTEN), clamp=400)) for v in views),
        title="Ce qu'elle a vu en dernier", empty="elle n'a encore rien vu", pager=shown,
        caption=f"Le dernier regard de chaque appareil. Ce qu'elle a vu reste dans ses conversations "
                f"{p.shown_for_us // MINUTE} min, pour ses propriétaires seulement."))
    # ses regards, au journal : une page, puis « plus anciens » (un de plus pour savoir s'il y en a)
    before = ctx.int_param("avant", 0) or None
    found = ctx.events([c.SEEN], PAGE + 1, before=before)
    looks = found[:PAGE]
    older = (("avant", str(looks[-1].seq)),) if len(found) > PAGE else ()
    blocks.append(Timeline(
        tuple(Entry(e.at, str(e.data.device or "—") + (" — quelque chose se passe" if e.data.notable else ""),
                    content_text(e.data.summary), tone="warn" if e.data.notable else "",
                    href=Ref("event", str(e.seq), f"#{e.seq}"),
                    meta=f"pertinence {float(e.data.pertinence or 0.0):.2f}"
                         + (" · encore frais" if frame.now - e.at <= p.shown_for_us else ""))
              for e in looks),
        title="Ses regards, du plus récent au plus ancien" + (" (plus anciens)" if before else ""),
        empty="plus rien avant" if before else "aucun regard pour l'instant",
        pager=Pager(param="avant", size=PAGE, older=older) if older or before else None))
    return blocks
