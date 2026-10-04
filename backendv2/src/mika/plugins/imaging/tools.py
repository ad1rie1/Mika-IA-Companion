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
from mika.vocab.privacy import Sensitivity

DRAW_TOOL, SHOW_TOOL = "draw", "show_drawing"
#: ce qu'elle annonce comme durée, par qualité (serveur local ; un service hébergé va plus vite)
LASTS = {"draft": "deux ou trois minutes", "normal": "cinq minutes environ", "high": "une dizaine de minutes"}

NOT_HERE = ("Tu ne dessines qu'en tête-à-tête, pour ta propriétaire ou quelqu'un qui a un compte : ici, dis-le "
            "simplement.")
NO_PORT = "Tu ne peux pas dessiner en ce moment : rien n'est branché pour ça. Dis-le simplement."


class DrawArgs(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000, description=(
        "Le prompt pour le modèle d'images, EN ANGLAIS et détaillé : le décor ou la scène d'abord, puis le sujet et "
        "sa place dans le cadre (« small in the lower right of the frame, seen from behind », « close-up "
        "portrait », « wide shot »…), le style (illustration, photo, aquarelle, anime…), la lumière, l'ambiance. "
        "Jamais le nom d'une personne réelle."))
    aspect: Literal["square", "portrait", "landscape", "wide"] = Field(default="landscape", description=(
        "La proportion : landscape (3:2) pour une scène ou un paysage, wide (16:9) pour un panorama, portrait (2:3) "
        "pour une personne en pied ou un visage, square sinon."))
    quality: Literal["default", "draft", "normal", "high"] = Field(default="default", description=(
        "« default » sauf si la personne demande expressément plus de soin (high : beaucoup plus long) ou juste "
        "un aperçu rapide (draft)."))
    adult: bool = Field(default=False, description="Vrai si l'image demandée est un contenu pour adultes "
                                                   "(nudité, sexualité).")
    real_person: bool = Field(default=False, description="Vrai si l'image représente une personne réelle "
                                                         "(quelqu'un que tu connais, une célébrité).")


def _recipient(ctx: Any) -> tuple[str, str] | ToolResult:
    """(adresse, personne) pour qui elle dessine — ou le refus, dit."""
    ep, aud = ctx.frame.episode, ctx.frame.audience
    target = ep.target if ep is not None else None
    if not target or is_work_target(target) or not offered(aud) or target not in aud.persons:
        return ToolResult(ok=False, content=NOT_HERE)
    return target, ctx.frame.get(identity_c.PERSON(target)) or target


def _job_id(ctx: Any, target: str) -> str:
    """Le même appel, dans la même portée (le tour d'une réponse, recomposée ou non) : le même dessin."""
    return digest(("dessin", ctx.dedupe_scope or ctx.episode_id, ctx.call_key or ctx.call_id, target))


def _quality(asked: str, default: str, allow_high: bool) -> str:
    quality = default if asked == "default" else asked
    return "normal" if quality == "high" and not allow_high else quality


@IMAGING.tool(DRAW_TOOL, description=(
    "Dessiner une image pour la personne (quand elle te demande un dessin, une illustration, une image). Ça prend "
    "quelques minutes : l'outil répond tout de suite, tu lui dis que tu t'y mets, et tu la lui montreras quand "
    "elle sera prête — ne décris pas une image que tu n'as pas encore vue."),
    args=DrawArgs, bundle=c.BUNDLE, episodes=CONVERSATIONAL, max_calls_per_episode=2, when=offered)
async def draw(args: DrawArgs, ctx: Any) -> Any:
    who = _recipient(ctx)
    if isinstance(who, ToolResult):
        return who
    target, person = who
    port = ctx.ports.get("imaging")
    if port is None or not port.configured:
        return ToolResult(ok=False, content=NO_PORT)
    refused = floor(args.prompt, adult=args.adult, real_person=args.real_person)
    if refused:
        return ToolResult(ok=False, content=refused)
    aud = ctx.frame.audience
    owner = bool(aud.owner)
    p = params_of(ctx.frame)
    if args.adult:
        if not owner:
            return ToolResult(ok=False, content="Un contenu pour adultes, tu ne le dessines que pour ta propriétaire, "
                                                "en tête-à-tête. Refuse simplement.")
        if not port.can(DRAW, adult=True):
            return ToolResult(ok=False, content="Aucun de tes moyens de dessiner n'accepte ce contenu. Dis-le "
                                                "simplement.")
    handles = tuple(ctx.frame.get(identity_c.HANDLES(person)) or ())
    mine = of_person(ctx.state, person, handles)
    waiting = [j for j in mine if j.status == c.WAITING]
    if len(waiting) >= p.max_waiting:
        return ToolResult(ok=False, content=f"Tu as déjà {len(waiting)} dessin(s) en cours pour cette personne : "
                                            "finis-les d'abord, dis-le-lui.")
    if not owner:
        today = sum(1 for j in mine if ctx.frame.now - j.at < DAY)
        if today >= p.per_day:
            return ToolResult(ok=False, content=(
                f"Tu as déjà fait {today} dessin(s) pour cette personne aujourd'hui : c'est assez pour l'instant, "
                "dis-le-lui gentiment." if p.per_day else "Tu ne dessines pas pour cette personne. Dis-le "
                                                          "simplement."))
    quality = _quality(args.quality, p.default_quality, p.allow_high)
    job = _job_id(ctx, target)
    about = tuple(dict.fromkeys(a for a in (person,) if a and a != target))
    draft = c.REQUESTED.draft(
        job=job, target=target, person=person, prompt=Content.of(args.prompt.strip(), level=int(Sensitivity.PERSONAL)),
        aspect=args.aspect, quality=quality, adult=args.adult, owner=owner, about=about, dedupe_key=f"dessin:{job}")
    try:
        await ctx.emit(draft)
    except Superseded:
        return ToolResult(ok=False, content="La conversation a bougé entre-temps : ce dessin n'est pas lancé.")
    note = " (en qualité normale : la haute n'est pas permise)" if args.quality == "high" and quality != "high" else ""
    return ToolResult(content=(
        f"C'est lancé{note} : il te faudra {LASTS.get(quality, 'quelques minutes')}. Dis-lui que tu t'y mets ; tu "
        "le lui montreras dès qu'il sera prêt. Ne le décris pas encore : tu ne l'as pas vu."))


class ShowArgs(BaseModel):
    pass


def _ready_for(ctx: Any, person: str) -> list[Job]:
    handles = tuple(ctx.frame.get(identity_c.HANDLES(person)) or ())
    return [j for j in of_person(ctx.state, person, handles) if j.status == c.READY and j.file]


@IMAGING.tool(SHOW_TOOL, description=(
    "Joindre à ton message le dessin que tu as fini pour la personne (le plus ancien qui ne lui a pas encore été "
    "montré). Dis-en un mot à ta façon : il part avec ton message."),
    args=ShowArgs, bundle=c.BUNDLE, episodes=[Kind.REPLY, Kind.INITIATIVE], max_calls_per_episode=3, when=offered)
async def show_drawing(args: ShowArgs, ctx: Any) -> Any:
    who = _recipient(ctx)
    if isinstance(who, ToolResult):
        return who
    _target, person = who
    ready = _ready_for(ctx, person)
    shown = sum(1 for name, ok in ctx.calls if name == SHOW_TOOL and ok)
    if len(ready) <= shown:
        return ToolResult(ok=False, content="Tu n'as pas de dessin prêt pour cette personne en ce moment.")
    j = ready[shown]  # un appel de plus dans l'épisode : le dessin suivant, jamais deux fois le même
    texts = ctx.ports["store"].content([r for r in (j.caption_ref,) if r]) if ctx.ports.get("store") else {}
    seen = texts.get(j.caption_ref, "")
    return ToolResult(content=(
        "Il part avec ton message." + (f" Ce que tu y vois : {seen}" if seen else "")
        + " Dis-en un mot à ta façon, sans le décrire en détail : la personne l'a sous les yeux."),
        attach=(j.file,))
