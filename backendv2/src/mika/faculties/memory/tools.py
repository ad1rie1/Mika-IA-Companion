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
    concerned_name,
    doubted,
    feelings,
    items_by_id,
    knowledge_label,
    names_of,
    relevance,
    topic,
    verdict_of,
    when_words,
)
from mika.faculties.memory.salience import age_words, tag
from mika.vocab.affect import facets
from mika.vocab.episodes import CONVERSATIONAL, WORKING
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase

#: une recherche délibérée lit d'abord tant de candidats, puis quatre fois plus tant que ce qui peut se dire manque
SEARCH_FIRST, SEARCH_MAX = 30, 480


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300, description=phrase("memory.tools.search.query"))
    limit: int = Field(default=5, ge=1, le=10)
    #: chercher par ce que ça fait ressentir (ADR 0083) : « ce qui t'énerve » — les émotions, et de qui
    ressenti: list[str] = Field(default_factory=list, max_length=6, description=phrase("memory.tools.search.ressenti"))
    de_qui: Literal["moi", "la_personne", "les_deux"] = Field(default="moi",
                                                              description=phrase("memory.tools.search.de_qui"))


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
    wanted = topic(args.query)
    memo: dict[str, str] = {}
    # « comment je t'appelle ? » : ce qui n'appartient qu'à vous, que les vecteurs ne rapprochent pas (ADR 0055)
    found = between_us(frame, store, person, aud, memo) if person and about_us(args.query) else []
    # ce qu'elle a vécu ou appris avec la personne, cherché à part ; et tant que ce qui peut se dire ici manque, plus
    # loin : trente secrets d'un autre, plus proches de la question, ne font pas « rien trouvé » (audit du 2026-10-08)
    own = tuple(sorted({person, ep.target, *frame.get(identity_c.HANDLES(person))})) \
        if person and ep is not None and is_identifiable(person) else ()
    emotions = [e for e, _x in facets(args.ressenti)]
    if emotions:
        found += await _by_feeling(args, emotions, ctx, person, own, wanted, memo, found)
    seen: set[int] = set()
    k = SEARCH_FIRST
    while not emotions:
        hits = dict(await vectors.search(args.query, k, kinds={c.SOUVENIR, c.BELIEF}))
        if own:
            for key, sim in await vectors.search(args.query, k, kinds={c.SOUVENIR, c.BELIEF}, persons=own):
                hits[key] = max(sim, hits.get(key, sim))
        items = items_by_id(store, [i for i in hits if i not in seen])
        seen |= set(hits)
        scores = {i: relevance(hits[i], wanted, it.text) for i, it in items.items()}
        for item in sorted((it for it in items.values() if scores[it.id] >= p.recall_floor * 0.8),
                           key=lambda it: (-scores[it.id], it.id)):
            if item.status != "active" or any(it.id == item.id for it, _v in found):
                continue
            verdict = verdict_of(frame, item, person, aud, memo, store)
            if verdict.ok:
                found.append((item, verdict))
            if len(found) >= args.limit:
                break
        if len(found) >= args.limit or len(hits) < k or k >= SEARCH_MAX:
            break
        k *= 4
    if not found:
        return phrase("memory.tools.search.nothing")
    names = names_of(frame, {o for it, v in found for o in (*v.others, *it.about, it.holder) if o})
    return "\n".join(f"- {age_words(it.born_at, frame.now)} : {it.text}{tag(v, names)}{doubted(frame, it, memo, person, v)}"
                     + (f" ({knowledge_label(it, names)})" if it.kind == c.BELIEF else "")
                     + feelings(it.felt, it.empathy, concerned_name(frame, it.about, names, memo)) for it, v in found)


#: par émotion, au plus tant d'éléments relus avant le verdict
FEELING_CANDIDATES = 200


async def _by_feeling(args: SearchArgs, emotions: list[str], ctx: Any, person: str | None, own: tuple[str, ...],
                      wanted: set[str], memo: dict[str, str], found: list[Any]) -> list[Any]:
    """Ce qui lui fait (ou fait à la personne concernée) ressentir ces émotions, le plus fort d'abord, la question
    départageant à intensité proche (ADR 0083) : « qu'est-ce qui t'énerve ? » — c'est le modèle qui choisit de
    chercher par ressenti, et lesquels ; rien ici ne devine une émotion dans les mots. Le verdict de chaque élément,
    comme toujours."""
    vectors, store, frame = ctx.ports.get("vectors"), ctx.ports.get("store"), ctx.frame
    whose = {"moi": (c.HERS,), "la_personne": (c.THEIRS,)}.get(args.de_qui, (c.HERS, c.THEIRS))
    marks_w, marks_e = ",".join("?" * len(whose)), ",".join("?" * len(emotions))
    rows = store.query_mind(
        f"SELECT f.item, MAX(f.intensity) FROM {c.FEELINGS_TABLE} f JOIN {c.ITEMS_TABLE} i ON i.id = f.item "
        f"WHERE f.whose IN ({marks_w}) AND f.emotion IN ({marks_e}) AND i.status='active' AND i.kind IN (?, ?) "
        f"GROUP BY f.item ORDER BY MAX(f.intensity) DESC, f.item LIMIT ?",
        (*whose, *emotions, c.SOUVENIR, c.BELIEF, FEELING_CANDIDATES))
    strength = {int(i): float(x) for i, x in rows}
    if not strength:
        return []
    near = dict(await vectors.search(args.query, len(strength), keys=list(strength))) if vectors is not None else {}
    items = items_by_id(store, list(strength))
    score = {i: strength[i] + 0.5 * relevance(near.get(i, 0.0), wanted, it.text) for i, it in items.items()}
    taken = {it.id for it, _v in found}
    out: list[Any] = []
    aud = frame.audience
    for item in sorted(items.values(), key=lambda it: (-score[it.id], it.id)):
        if item.id in taken:
            continue
        verdict = verdict_of(frame, item, person, aud, memo, store)
        if verdict.ok:
            out.append((item, verdict))
        if len(found) + len(out) >= args.limit:
            break
    return out


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
