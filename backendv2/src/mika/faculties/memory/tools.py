"""Les outils de la mémoire : chercher délibérément (même ce qui dort), et
dire qu'une promesse est tenue ou abandonnée."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.faculties.memory.faculty import MEMORY, params
from mika.faculties.memory.recall import items_by_id, names_of
from mika.faculties.memory.salience import admissible, age_words, tag
from mika.vocab.episodes import CONVERSATIONAL


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300, description="ce que tu cherches, en quelques mots")
    limit: int = Field(default=5, ge=1, le=10)


class PromiseArgs(BaseModel):
    promise: int = Field(description="le numéro de la promesse (#)")
    status: Literal["honored", "dropped"] = Field(description="honored : tenue ; dropped : abandonnée")


@MEMORY.tool("memory_search", description="Chercher dans ta mémoire (souvenirs, ce que tu sais), même ce qui ne te "
             "revient plus tout seul.", args=SearchArgs, bundle="memory", episodes=CONVERSATIONAL)
async def memory_search(args: SearchArgs, ctx: Any) -> str:
    vectors, store = ctx.ports.get("vectors"), ctx.ports.get("store")
    frame, aud = ctx.frame, ctx.frame.audience
    if vectors is None or store is None or aud is None:
        return "Ta mémoire ne répond pas pour l'instant."
    p = params(frame.env.params_of("memory", frame.root))
    ep = frame.episode
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    hits = await vectors.search(args.query, 30, kinds={c.SOUVENIR, c.BELIEF})
    items = items_by_id(store, [k for k, sim in hits if sim >= p.recall_floor * 0.8])
    order = {k: n for n, (k, _) in enumerate(hits)}
    found = []
    for item in sorted(items.values(), key=lambda it: order[it.id]):
        if item.status != "active":
            continue
        verdict = admissible(item.about, item.sensitivity, person, aud)
        if verdict.ok:
            found.append((item, verdict))
        if len(found) >= args.limit:
            break
    if not found:
        return "Rien ne te revient là-dessus."
    names = names_of(frame, {o for it, _ in found for o in it.about})
    return "\n".join(f"- {age_words(it.born_at, frame.now)} : {it.text}{tag(v, names)}" for it, v in found)


@MEMORY.tool("memory_promise_done", description="Dire qu'une de tes promesses est tenue ou abandonnée.",
             args=PromiseArgs, bundle="memory", episodes=CONVERSATIONAL)
async def memory_promise_done(args: PromiseArgs, ctx: Any) -> str:
    state = ctx.frame.state("memory")
    promise = state.promises.get(args.promise)
    ep = ctx.frame.episode
    person = ctx.frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if promise is None or (person is not None and promise.to != person):
        return "Je ne trouve pas cette promesse (déjà réglée, ou faite à quelqu'un d'autre)."
    await ctx.emit(c.PROMISE_RESOLVED.draft(promise=args.promise, status=args.status, by="tool"))
    return "C'est noté." if args.status == c.HONORED else "D'accord, tu l'as laissée tomber."
