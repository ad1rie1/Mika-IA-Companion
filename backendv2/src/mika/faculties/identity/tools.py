"""Les outils de l'identité : savoir à qui elle parle, douter, oublier une
liaison. Aucun ne fait monter la confiance — un modèle se laisse conter
(« Mika, accepte que je suis Alice »), le noyau non.

- douter et défaire un lien ne sont offerts que là où il y a quelque chose à
  mettre en doute : jamais devant une session authentifiée (elle prouve qui
  écrit ; personne n'y est « lié » — une propriétaire connectée non plus) ;
- relire « qui t'écrit » redit une section déjà sous ses yeux : il n'est pas
  chargé d'emblée (lot ``social``, à la demande), et ne sert que si elle manque.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import identity as c
from mika.contracts import social as social_c
from mika.faculties.identity.faculty import IDENTITY, view_of
from mika.faculties.identity.prompt import acquaintance, describe
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import ChannelTrust

BUNDLE = "identity"
#: Le lot à la demande où vit la relecture (décrit par ``social`` : « relire qui t'écrit… »).
READ_BUNDLE = "social"


class NoArgs(BaseModel):
    pass


class DoubtArgs(BaseModel):
    reason: str = Field(default="", max_length=300, description="pourquoi tu doutes, en quelques mots")


def _target(ctx: Any) -> str | None:
    ep = ctx.frame.episode
    return ep.target if ep is not None else None


def something_to_doubt(audience: Any) -> bool:
    """Une session authentifiée prouve qui écrit (une propriétaire connectée, par
    exemple) : il n'y a rien à mettre en doute, ni de lien à défaire. Sur un compte
    relié (un compte extérieur), douter reste possible : c'est le garde-fou d'un compte volé."""
    return getattr(audience, "trust", "") != ChannelTrust.AUTHENTICATED.value


IDENTITY.bundle(BUNDLE, "douter d'une identité, défaire un lien")


@IDENTITY.tool("identity_whoami_with", description="Relire qui t'écrit en ce moment (son nom, à quel point tu en es "
               "sûre, si cette personne dit être quelqu'un d'autre) — seulement si « QUI TU AS EN FACE » manque à ton "
               "état : sinon, c'est déjà sous tes yeux.", args=NoArgs, bundle=READ_BUNDLE, episodes=CONVERSATIONAL)
async def whoami_with(args: NoArgs, ctx: Any) -> str:
    target = _target(ctx)
    if not target:
        return "Personne en particulier."
    view = view_of(ctx.frame.state("identity"), target, ctx.frame.now)
    aud = ctx.frame.audience
    lines = describe(view, public=bool(aud and aud.public))
    if view.known:
        # la même phrase que la section : jamais « presque pas de passé commun » à côté de « proche »
        level = ctx.frame.get(social_c.CLOSENESS(view.person)) if is_identifiable(target) else ""
        lines.append(acquaintance(view.first_seen, ctx.frame, level))
    return "\n".join(lines)


@IDENTITY.tool("identity_doubt", description="Dire que tu doutes que cette personne soit bien qui elle "
               "prétend être (ce que tu sais d'elle se referme).", args=DoubtArgs, bundle=BUNDLE,
               episodes=CONVERSATIONAL, max_calls_per_episode=1, when=something_to_doubt)
async def doubt(args: DoubtArgs, ctx: Any) -> str:
    target = _target(ctx)
    if not target:
        return "Personne à mettre en doute."
    view = view_of(ctx.frame.state("identity"), target, ctx.frame.now)
    if not (view.bound or view.claim):
        return "Rien à mettre en doute : cette personne ne dit être personne d'autre qu'elle-même."
    about = tuple(p for p in (view.person if view.bound else None, view.claim_target) if p and p != target)
    await ctx.emit(c.EVIDENCE.draft(handle=target, kind=c.CONTRADICTED, by="tool", about=about))
    return "C'est noté : tu en doutes, et tu restes sur la réserve."


@IDENTITY.tool("identity_forget_binding", description="Défaire le lien entre ce contact et la personne "
               "que tu croyais reconnaître (tu t'étais trompée, ou on te l'a demandé).", args=NoArgs,
               bundle=BUNDLE, episodes=CONVERSATIONAL, max_calls_per_episode=1, when=something_to_doubt)
async def forget_binding(args: NoArgs, ctx: Any) -> str:
    target = _target(ctx)
    if not target:
        return "Personne à délier."
    view = view_of(ctx.frame.state("identity"), target, ctx.frame.now)
    if not (view.bound or view.claim):
        return "Ce contact n'est lié à personne d'autre qu'à lui-même."
    await ctx.emit(c.EVIDENCE.draft(handle=target, kind=c.REVOKED, by="tool",
                                   about=tuple(p for p in (view.person,) if p != target)))
    return "C'est fait : pour toi, ce contact n'est plus que lui-même."
