"""Le plugin ``camera`` : ce qu'elle voit de la pièce.

- **Regarder** (éveillée) : quand l'image d'un appareil a changé, au plus
  toutes les deux minutes, elle la fait décrire (rôle ``caption``) et
  **remarque** ce qu'elle voit — un signal, plus pertinent s'il se passe
  quelque chose. Une image n'entre jamais dans le journal : seulement ce
  qu'elle en a vu.
- Ce qu'elle voit se montre en conversation (« ce que tu vois ») à ses
  propriétaires seulement, **en privé** (jamais devant un salon), cité, tant
  que c'est récent ; une image de la pièce est personnelle.
- ``camera_look`` : regarder maintenant, pour la personne qui s'occupe d'elle,
  en privé. Une image figée (l'appareil n'envoie plus rien) n'est pas décrite
  comme si elle était actuelle : elle dit depuis quand elle ne voit plus rien.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import body as body_c
from mika.contracts import camera as c
from mika.contracts import self_ as self_c
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp, Faculty, ToolResult, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
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
    paginate,
)
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import Image, LLMRequest, Message
from mika.ports.preprocess import inert
from mika.vocab.episodes import CONVERSATIONAL, WORKING, Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

BUNDLE = "camera"


class CameraParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    look_every_us: Annotated[int, Knob(
        label="Regarder au plus toutes les", group="Regarder", lo=MINUTE, hi=2 * HOUR,
        help="Éveillée, elle regarde à ce rythme ; une image inchangée n'est pas redécrite. Chaque regard est un "
             "appel au modèle de vision : plus court, plus coûteux.")] = 2 * MINUTE
    fresh_us: Annotated[int, Knob(
        label="Image encore fraîche", group="Regarder", lo=MINUTE, hi=HOUR,
        help="Une image plus vieille que ça (caméra figée ou déconnectée) n'est pas décrite, et l'appareil "
             "passe pour silencieux.")] = 5 * MINUTE
    shown_for_us: Annotated[int, Knob(
        label="Montré en conversation pendant", group="Regarder", lo=MINUTE, hi=6 * HOUR,
        help="Ce qu'elle a vu reste dans ses conversations avec ses propriétaires pendant ce temps, puis ne se "
             "montre plus.")] = 10 * MINUTE


@dataclass(frozen=True, slots=True)
class Looked:
    seq: int
    digest: str
    at: int
    notable: bool
    summary_ref: str


@dataclass(frozen=True, slots=True)
class CameraState:
    views: FrozenDict[str, Looked] = field(default_factory=FrozenDict)


CAMERA = Faculty("camera", state=CameraState, init=lambda p: CameraState(), params=CameraParams)
CAMERA.bundle(BUNDLE, phrase("camera.bundle"))
CAMERA.declare(*c.ALL)


def params(p: CameraParams | None) -> CameraParams:
    return p if p is not None else CameraParams()


@CAMERA.reducer(c.SEEN)
def _seen(s: CameraState, e, cx) -> CameraState:
    d = e.data
    return replace(s, views=s.views.set(d.device, Looked(e.seq, d.digest, e.at, d.notable, d.summary.ref or "")))


@CAMERA.fact(c.VIEWS)
def _views(s: CameraState, cx) -> tuple[c.View, ...]:
    out = [c.View(k, v.at, v.notable, v.summary_ref) for k, v in s.views.items()]
    return tuple(sorted(out, key=lambda v: (-v.at, v.device)))


_JSON = re.compile(r"\{.*\}", re.S)


def read_look(text: str) -> tuple[str, bool]:
    found = _JSON.search(text or "")
    if found:
        try:
            data = json.loads(found.group(0))
            if isinstance(data, dict):
                return inert(str(data.get("description") or ""), 600), bool(data.get("notable"))
        except ValueError:
            pass
    return inert(text or "", 600), False


def look(name: str) -> str:
    """La consigne de la description, pour celle qui ne voit pas l'image (son nom, celui de sa persona : jamais
    écrit ici)."""
    return phrase("camera.look.system", name=name)


def request(snap: Any, call_id: str, name: str) -> LLMRequest:
    image = Image(snap.mime, base64.b64encode(snap.data).decode())
    return LLMRequest(role="caption", call_id=call_id, system_stable=look(name),
                      messages=(Message("user", phrase("camera.look.ask"), images=(image,)),), max_tokens=200,
                      lane="background", priority=3)


def seen_draft(snap: Any, description: str, notable: bool) -> Any:
    level = int(Sensitivity.PERSONAL)
    return c.SEEN.draft(
        source="camera", kind=c.VIEW,
        summary=Content.of(phrase("camera.seen", device=inert(snap.device, 40), description=description), level=level),
        pertinence=0.7 if notable else 0.2, emotion="curious" if notable else "", intensity=0.15 if notable else 0.0,
        sensitivity=level, bundle=BUNDLE, device=snap.device, digest=snap.digest, notable=notable,
        dedupe_key=f"vu:{snap.device}:{snap.digest}:{snap.at}")


@CAMERA.process("camera.look", wake_on=[*body_c.ALL], lane="background", catch_up=CatchUp.SKIP, max_quantum_s=120,
                priority=80)
class Look:
    def __init__(self) -> None:
        self.absent = False  # pas de caméra dans cette installation : plus rien à regarder

    def _due(self, s: CameraState, frame: Frame, port: Any, p: CameraParams) -> list[Any]:
        out = []
        for device in port.devices():
            snap = port.latest(device)
            last = s.views.get(device)
            if snap is None or frame.now - snap.at > p.fresh_us:
                continue
            if last is not None and (last.digest == snap.digest or frame.now - last.at < p.look_every_us):
                continue
            out.append(snap)
        return out

    def next_due(self, s: CameraState, frame: Frame, last_run: int | None) -> int | None:
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
            return None
        # les images arrivent hors du journal : on regarde à cadence fixe, ``run`` décide s'il y a du neuf
        if self.absent:
            return None
        p = params(frame.env.params_of("camera", frame.root))
        return max(frame.now, (last_run or 0) + p.look_every_us)

    async def run(self, ctx: Any) -> None:
        port = ctx.ports.get("camera")
        frame: Frame = ctx.frame
        self.absent = port is None
        if port is None or frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
            return
        p = params(frame.env.params_of("camera", frame.root))
        for i, snap in enumerate(self._due(ctx.state, frame, port, p)[:2]):
            resp = await ctx.ask(request(snap, f"{ctx.run_id}#{i}", self_c.name_of(frame.get(self_c.PERSONA))))
            if resp is None:
                continue
            description, notable = read_look(resp.text)
            if description:
                await ctx.emit(seen_draft(snap, description, notable))


def _for_owner(frame: Frame) -> bool:
    """Ce que voit la caméra : pour ses propriétaires en privé (jamais devant un salon, même quand c'est
    sa propriétaire qui y parle), ou pour elle quand elle travaille."""
    ep = frame.episode
    if ep is None:
        return False
    if ep.kind in WORKING:
        return True
    audience = frame.audience
    if not ep.target or audience is None or audience.public or audience.room:
        return False
    # l'audience dit si qui écrit en a les droits : l'adresse qui parle, pas une autre adresse de la personne
    return bool(audience.owner)


def _ago(us: int) -> str:
    minutes = max(1, us // MINUTE)
    if minutes < 120:
        return phrase("projects.duration.minutes", n=minutes)
    hours = minutes // 60
    return phrase("projects.duration.hours", n=hours) if hours < 48 else phrase("projects.duration.days", n=hours // 24)


@CAMERA.enricher("views", episodes=[*CONVERSATIONAL, Kind.STEP], deadline_ms=300)
async def _texts(s: CameraState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    p = params(frame.env.params_of("camera", frame.root))
    views = [v for v in frame.get(c.VIEWS) if frame.now - v.at <= p.shown_for_us]
    if store is None or not views or not _for_owner(frame):
        return None
    return store.content([v.summary_ref for v in views[:2] if v.summary_ref])


@CAMERA.section("views", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL, Kind.STEP], trim_rank=15,
                title=phrase("camera.section.title"), untrusted=True, reads=[c.VIEWS])
def _section(s: CameraState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts = enrich.get("views") or {}
    if not texts or not _for_owner(frame):
        return None
    lines = [texts[v.summary_ref] for v in frame.get(c.VIEWS)[:2] if texts.get(v.summary_ref)]
    # une image de la pièce est personnelle : sa propriétaire la reçoit (témoin), un salon jamais
    return SectionBody("\n".join(lines), level=int(Sensitivity.PERSONAL), witness=True) if lines else None


class LookArgs(BaseModel):
    device: str = Field(default="", max_length=40, description=phrase("camera.tools.look.device"))


@CAMERA.tool("camera_look", description=phrase("camera.tools.look.description"), args=LookArgs, bundle=BUNDLE,
             episodes=[Kind.REPLY, *WORKING], max_calls_per_episode=2, owner_only=True)
async def camera_look(args: LookArgs, ctx: Any) -> Any:
    port, llm = ctx.ports.get("camera"), ctx.ports.get("llm")
    if not _for_owner(ctx.frame):
        return ToolResult(ok=False, content=phrase("camera.tools.look.private"))
    if port is None or llm is None or not port.devices():
        return ToolResult(ok=False, content=phrase("camera.tools.look.none"))
    device = args.device or port.devices()[0]
    snap = port.latest(device)
    if snap is None:
        return ToolResult(ok=False, content=phrase("camera.tools.look.nothing", device=device))
    frame: Frame = ctx.frame
    p = params(frame.env.params_of("camera", frame.root))
    if frame.now - snap.at > p.fresh_us:  # une image figée n'est pas ce qu'on voit maintenant
        return ToolResult(ok=False, content=phrase("camera.tools.look.frozen", ago=_ago(frame.now - snap.at),
                                                   device=device))
    resp = await llm.call(request(snap, f"{ctx.call_id}:look", self_c.name_of(frame.get(self_c.PERSONA))))
    description, notable = read_look(resp.text)
    if not description:
        return ToolResult(ok=False, content=phrase("camera.tools.look.unreadable"))
    await ctx.emit(seen_draft(snap, description, notable))
    return phrase("camera.tools.look.result", description=description)



# ── Inspection ────────────────────────────────────────────────────────────
#
# Jamais une image : ses appareils (reçoivent-ils encore ?), ce qu'elle voit
# en ce moment, ses derniers regards — des textes relus au journal.

#: une page de ses regards (au journal, du plus récent au plus ancien), des appareils, de ce qu'elle a vu
PAGE = 25
#: des tuiles pour les premiers appareils seulement : le tableau, lui, les montre tous
TILES_SHOWN = 8


def _said(summary: Content) -> str:
    """Ce qu'elle a vu, relu au journal ; un contenu effacé se dit tel quel."""
    return summary.text if summary.text is not None else "(oublié)"


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
        NavItem("Connecter une caméra", Ref("local", "/inspecteur/reglages/appareils", "Accès des appareils")),
        NavItem("Régler les observations", Ref("local", "/inspecteur/reglages/comportement-camera", "Réglages de la caméra")),)))
    views, shown = paginate(frame.get(c.VIEWS), ctx.pager("page_vus", size=PAGE))
    texts = ctx.store.content([v.summary_ref for v in views if v.summary_ref])
    blocks.append(Table(
        ("appareil", Column("vu", "fit"), Column("fraîcheur", "fit"), Column("notable", "fit"), "ce qu'elle a vu"),
        tuple((v.device, When(v.at),
               Badge("elle en parle encore", "ok") if frame.now - v.at <= p.shown_for_us else Badge("ancien", "muted"),
               Badge("notable", "warn") if v.notable else Badge("calme", "muted"),
               Text(texts.get(v.summary_ref, "(oublié)"), clamp=400)) for v in views),
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
                    _said(e.data.summary), tone="warn" if e.data.notable else "",
                    href=Ref("event", str(e.seq), f"#{e.seq}"),
                    meta=f"pertinence {float(e.data.pertinence or 0.0):.2f}"
                         + (" · encore frais" if frame.now - e.at <= p.shown_for_us else ""))
              for e in looks),
        title="Ses regards, du plus récent au plus ancien" + (" (plus anciens)" if before else ""),
        empty="plus rien avant" if before else "aucun regard pour l'instant",
        pager=Pager(param="avant", size=PAGE, older=older) if older or before else None))
    return blocks
