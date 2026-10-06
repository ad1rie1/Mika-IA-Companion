"""Les outils de la mémoire : chercher délibérément (même ce qui dort), et
dire qu'une promesse est tenue ou abandonnée.

Relire ses promesses n'est pas un outil : elles sont déjà dans « ce que tu
lui as promis » — un outil qui relit ce qui est sous ses yeux l'invite à dire
« attends, je vérifie » au lieu de parler."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.faculties.memory.faculty import MEMORY, params
from mika.faculties.memory.life import kept_too_early
from mika.faculties.memory.recall import (
    about_us,
    between_us,
    items_by_id,
    names_of,
    relevance,
    topic,
    verdict_of,
    when_words,
)
from mika.faculties.memory.salience import age_words, tag
from mika.vocab.episodes import CONVERSATIONAL, WORKING
from mika.vocab.phrasebook import phrase


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300, description=phrase("memory.tools.search.query"))
    limit: int = Field(default=5, ge=1, le=10)


class PromiseArgs(BaseModel):
    promise: int = Field(description=phrase("memory.tools.promise_done.promise"))
    status: Literal["honored", "dropped"] = Field(description=phrase("memory.tools.promise_done.status"))


MEMORY.bundle("memory", phrase("memory.tools.bundle"))


@MEMORY.tool("memory_search", description=phrase("memory.tools.search.description"), args=SearchArgs, bundle="memory",
             episodes=[*CONVERSATIONAL, *WORKING])
async def memory_search(args: SearchArgs, ctx: Any) -> str:
    vectors, store = ctx.ports.get("vectors"), ctx.ports.get("store")
    frame, aud = ctx.frame, ctx.frame.audience
    if vectors is None or store is None or aud is None:
        return phrase("memory.tools.search.unavailable")
    p = params(frame.env.params_of("memory", frame.root))
    ep = frame.episode
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    hits = dict(await vectors.search(args.query, 30, kinds={c.SOUVENIR, c.BELIEF}))
    wanted = topic(args.query)
    items = items_by_id(store, list(hits))
    scores = {i: relevance(hits[i], wanted, it.text) for i, it in items.items()}
    memo: dict[str, str] = {}
    # « comment je t'appelle ? » : ce qui n'appartient qu'à vous, que les vecteurs ne rapprochent pas (ADR 0055)
    found = between_us(frame, store, person, aud, memo) if person and about_us(args.query) else []
    for item in sorted((it for it in items.values() if scores[it.id] >= p.recall_floor * 0.8),
                       key=lambda it: (-scores[it.id], it.id)):
        if item.status != "active" or any(it.id == item.id for it, _v in found):
            continue
        verdict = verdict_of(frame, item, person, aud, memo, store)
        if verdict.ok:
            found.append((item, verdict))
        if len(found) >= args.limit:
            break
    if not found:
        return phrase("memory.tools.search.nothing")
    names = names_of(frame, {o for it, v in found for o in (*v.others, *it.about)})
    return "\n".join(f"- {age_words(it.born_at, frame.now)} : {it.text}{tag(v, names)}" for it, v in found)


@MEMORY.tool("memory_promise_done", description=phrase("memory.tools.promise_done.description"), args=PromiseArgs,
             bundle="memory", episodes=CONVERSATIONAL)
async def memory_promise_done(args: PromiseArgs, ctx: Any) -> str:
    state = ctx.frame.state("memory")
    promise = state.promises.get(args.promise)
    ep = ctx.frame.episode
    person = ctx.frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    # une promesse faite à une adresse reliée depuis à cette personne lui a été faite
    if promise is None or (person is not None and (ctx.frame.get(identity_c.PERSON(promise.to)) or promise.to) != person):
        return phrase("memory.tools.promise_done.not_found")
    if args.status == c.HONORED and promise.due is not None and kept_too_early(promise, ctx.frame.now, ctx.frame):
        # la règle de la consolidation (ADR 0052) : la veille, « je te le rappellerai » n'est pas la tenir
        return phrase("memory.tools.promise_done.too_early", when=when_words(promise.due, ctx.frame))
    await ctx.emit(c.PROMISE_RESOLVED.draft(promise=args.promise, status=args.status, by="tool"))
    if args.status == c.HONORED:
        return phrase("memory.tools.promise_done.honored")
    return phrase("memory.tools.promise_done.dropped")
