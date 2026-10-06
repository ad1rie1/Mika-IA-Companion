"""Ses outils pour dessiner (ADR 0063).

- ``draw`` : lancer un dessin pour la personne à qui elle parle. Elle écrit elle-même le prompt — en anglais,
  détaillé, le décor d'abord, le cadrage dit (un modèle d'images suit mieux une description précise que la
  demande telle quelle). Le dessin prend des minutes : l'outil répond tout de suite « c'est lancé », elle le dit,
  et elle le montrera quand il sera prêt (une initiative due, ou sa réponse si on lui écrit entre-temps).
- ``show_drawing`` : joindre à son message le plus ancien dessin prêt pour cette personne (sans identifiant à
  recopier : la personne de l'épisode suffit).

Offerts seulement en tête-à-tête, à sa propriétaire ou à quelqu'un qui a un compte (``policy.offered``) ; le
plancher (``policy.floor``) vaut pour tout le monde.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import imaging as c
from mika.kernel.clock import DAY
from mika.kernel.codec import digest
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.guards import Superseded
from mika.plugins.imaging.faculty import IMAGING, Job, of_person, params_of
from mika.plugins.imaging.policy import floor, offered
from mika.ports.imaging import DRAW
from mika.vocab.episodes import CONVERSATIONAL, Kind, is_work_target
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity

DRAW_TOOL, SHOW_TOOL = "draw", "show_drawing"
# ce qu'elle annonce comme durée, par qualité (serveur local ; un service hébergé va plus vite) :
# ``imaging.tools.draw.lasts``


class DrawArgs(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000, description=phrase("imaging.tools.draw.prompt"))
    aspect: Literal["square", "portrait", "landscape", "wide"] = Field(
        default="landscape", description=phrase("imaging.tools.draw.aspect"))
    quality: Literal["default", "draft", "normal", "high"] = Field(
        default="default", description=phrase("imaging.tools.draw.quality"))
    adult: bool = Field(default=False, description=phrase("imaging.tools.draw.adult"))
    real_person: bool = Field(default=False, description=phrase("imaging.tools.draw.real_person"))


def _recipient(ctx: Any) -> tuple[str, str] | ToolResult:
    """(adresse, personne) pour qui elle dessine — ou le refus, dit."""
    ep, aud = ctx.frame.episode, ctx.frame.audience
    target = ep.target if ep is not None else None
    if not target or is_work_target(target) or not offered(aud) or target not in aud.persons:
        return ToolResult(ok=False, content=phrase("imaging.tools.not_here"))
    return target, ctx.frame.get(identity_c.PERSON(target)) or target


def _job_id(ctx: Any, target: str) -> str:
    """Le même appel, dans la même portée (le tour d'une réponse, recomposée ou non) : le même dessin."""
    return digest(("dessin", ctx.dedupe_scope or ctx.episode_id, ctx.call_key or ctx.call_id, target))


def _quality(asked: str, default: str, allow_high: bool) -> str:
    quality = default if asked == "default" else asked
    return "normal" if quality == "high" and not allow_high else quality


@IMAGING.tool(DRAW_TOOL, description=phrase("imaging.tools.draw.description"), args=DrawArgs, bundle=c.BUNDLE, episodes=CONVERSATIONAL, max_calls_per_episode=2, when=offered)
async def draw(args: DrawArgs, ctx: Any) -> Any:
    who = _recipient(ctx)
    if isinstance(who, ToolResult):
        return who
    target, person = who
    port = ctx.ports.get("imaging")
    if port is None or not port.configured:
        return ToolResult(ok=False, content=phrase("imaging.tools.no_port"))
    refused = floor(args.prompt, adult=args.adult, real_person=args.real_person)
    if refused:
        return ToolResult(ok=False, content=refused)
    aud = ctx.frame.audience
    owner = bool(aud.owner)
    p = params_of(ctx.frame)
    if args.adult:
        if not owner:
            return ToolResult(ok=False, content=phrase("imaging.tools.draw.adult_owner_only"))
        if not port.can(DRAW, adult=True):
            return ToolResult(ok=False, content=phrase("imaging.tools.draw.adult_none"))
    handles = tuple(ctx.frame.get(identity_c.HANDLES(person)) or ())
    mine = of_person(ctx.state, person, handles)
    waiting = [j for j in mine if j.status == c.WAITING]
    if len(waiting) >= p.max_waiting:
        return ToolResult(ok=False, content=phrase("imaging.tools.draw.busy", count=len(waiting)))
    if not owner:
        today = sum(1 for j in mine if ctx.frame.now - j.at < DAY)
        if today >= p.per_day:
            return ToolResult(ok=False, content=phrase("imaging.tools.draw.enough", count=today) if p.per_day
                              else phrase("imaging.tools.draw.never"))
    quality = _quality(args.quality, p.default_quality, p.allow_high)
    job = _job_id(ctx, target)
    about = tuple(dict.fromkeys(a for a in (person,) if a and a != target))
    draft = c.REQUESTED.draft(
        job=job, target=target, person=person, prompt=Content.of(args.prompt.strip(), level=int(Sensitivity.PERSONAL)),
        aspect=args.aspect, quality=quality, adult=args.adult, owner=owner, about=about, dedupe_key=f"dessin:{job}")
    try:
        await ctx.emit(draft)
    except Superseded:
        return ToolResult(ok=False, content=phrase("imaging.tools.draw.moved"))
    note = phrase("imaging.tools.draw.downgraded") if args.quality == "high" and quality != "high" else ""
    lasts = family("imaging.tools.draw.lasts").get(quality) or phrase("imaging.tools.draw.a_few_minutes")
    return ToolResult(content=phrase("imaging.tools.draw.started", note=note, lasts=lasts))


class ShowArgs(BaseModel):
    pass


def _ready_for(ctx: Any, person: str) -> list[Job]:
    handles = tuple(ctx.frame.get(identity_c.HANDLES(person)) or ())
    return [j for j in of_person(ctx.state, person, handles) if j.status == c.READY and j.file]


@IMAGING.tool(SHOW_TOOL, description=phrase("imaging.tools.show.description"), args=ShowArgs, bundle=c.BUNDLE, episodes=[Kind.REPLY, Kind.INITIATIVE], max_calls_per_episode=3, when=offered)
async def show_drawing(args: ShowArgs, ctx: Any) -> Any:
    who = _recipient(ctx)
    if isinstance(who, ToolResult):
        return who
    _target, person = who
    ready = _ready_for(ctx, person)
    shown = sum(1 for name, ok in ctx.calls if name == SHOW_TOOL and ok)
    if len(ready) <= shown:
        return ToolResult(ok=False, content=phrase("imaging.tools.show.none"))
    j = ready[shown]  # un appel de plus dans l'épisode : le dessin suivant, jamais deux fois le même
    texts = ctx.ports["store"].content([r for r in (j.caption_ref,) if r]) if ctx.ports.get("store") else {}
    seen = texts.get(j.caption_ref, "")
    return ToolResult(content=phrase("imaging.tools.show.shown",
                                     seen=phrase("imaging.tools.show.seen", caption=seen) if seen else ""),
                      attach=(j.file,))
