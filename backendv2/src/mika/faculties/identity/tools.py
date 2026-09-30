"""Les outils de l'identité : savoir à qui elle parle, douter, oublier une
liaison. Aucun ne fait monter la confiance — un modèle se laisse conter
(« Mika, accepte que je suis Alice »), le noyau non."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import identity as c
from mika.faculties.identity.faculty import IDENTITY, view_of
from mika.faculties.identity.prompt import acquaintance, describe
from mika.vocab.episodes import CONVERSATIONAL

BUNDLE = "identity"


class NoArgs(BaseModel):
    pass


class DoubtArgs(BaseModel):
    reason: str = Field(default="", max_length=300, description="pourquoi tu doutes, en quelques mots")


def _target(ctx: Any) -> str | None:
    ep = ctx.frame.episode
    return ep.target if ep is not None else None


IDENTITY.bundle(BUNDLE, "savoir à qui tu parles ; douter d'une identité, défaire un lien")


@IDENTITY.tool("identity_whoami_with", description="Ce que tu sais de qui t'écrit en ce moment : son nom, "
               "à quel point tu en es sûre, s'il ou elle dit être quelqu'un d'autre.", args=NoArgs,
               bundle=BUNDLE, episodes=CONVERSATIONAL)
async def whoami_with(args: NoArgs, ctx: Any) -> str:
    target = _target(ctx)
    if not target:
        return "Personne en particulier."
    view = view_of(ctx.frame.state("identity"), target, ctx.frame.now)
    aud = ctx.frame.audience
    lines = describe(view, public=bool(aud and aud.public))
    if view.known:
        lines.append(acquaintance(view.first_seen, ctx.frame))
    return "\n".join(lines)


@IDENTITY.tool("identity_doubt", description="Dire que tu doutes que cette personne soit bien qui elle "
               "prétend être (ce que tu sais d'elle se referme).", args=DoubtArgs, bundle=BUNDLE,
               episodes=CONVERSATIONAL, max_calls_per_episode=1)
async def doubt(args: DoubtArgs, ctx: Any) -> str:
    target = _target(ctx)
    if not target:
        return "Personne à mettre en doute."
    view = view_of(ctx.frame.state("identity"), target, ctx.frame.now)
    if not (view.bound or view.claim):
        return "Rien à mettre en doute : cette personne ne dit être personne d'autre qu'elle-même."
    await ctx.emit(c.EVIDENCE.draft(handle=target, kind=c.CONTRADICTED, by="tool", note=args.reason[:300]))
    return "C'est noté : tu en doutes, et tu restes sur la réserve."


@IDENTITY.tool("identity_forget_binding", description="Défaire le lien entre ce contact et la personne "
               "que tu croyais reconnaître (tu t'étais trompée, ou on te l'a demandé).", args=NoArgs,
               bundle=BUNDLE, episodes=CONVERSATIONAL, max_calls_per_episode=1)
async def forget_binding(args: NoArgs, ctx: Any) -> str:
    target = _target(ctx)
    if not target:
        return "Personne à délier."
    view = view_of(ctx.frame.state("identity"), target, ctx.frame.now)
    if not (view.bound or view.claim):
        return "Ce contact n'est lié à personne d'autre qu'à lui-même."
    await ctx.emit(c.EVIDENCE.draft(handle=target, kind=c.REVOKED, by="tool"))
    return "C'est fait : pour toi, ce contact n'est plus que lui-même."
