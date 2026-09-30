"""Le rappel : ce qui lui revient pendant qu'elle parle à quelqu'un.

L'enrichisseur cherche dans l'index ce qui ressemble au message, garde ce qui
ne dort pas et ce qui peut se dire devant cette audience, le classe
(pertinence × ce qu'il en reste × lien avec la personne × humeur × pas redit
à l'instant), et rend :

- ses souvenirs et ce qu'elle sait (``CE QUI TE REVIENT``) — ce qui touche
  d'autres personnes porte une étiquette au-delà de l'anodin ;
- ce qui concerne aussi l'interlocuteur, jugé au niveau « témoin » ;
- des extraits d'échanges passés **avec cette personne** ;
- les promesses qu'elle lui a faites (sa fiche, donc seulement si elle est ouverte).

Toute panne → rien (le tour part sans mémoire, jamais avec trop).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.faculty import MEMORY, MemoryState, params
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.faculties.memory.salience import Item, Verdict, admissible, age_words, dormant, rank, tag
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab import affect as A
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import stems

ORIGIN_FR = {"told": "on te l'a dit", "observed": "tu l'as vu", "inferred": "tu le déduis"}


@dataclass(frozen=True, slots=True)
class Recalled:
    item: Item
    verdict: Verdict
    label: str  # le texte à montrer, étiquette comprise


@dataclass(frozen=True, slots=True)
class Exchange:
    id: int
    at: int
    user_text: str
    reply_text: str


@dataclass(slots=True)
class Recall:
    souvenirs: list[Recalled] = field(default_factory=list)
    beliefs: list[Recalled] = field(default_factory=list)
    exchanges: list[Exchange] = field(default_factory=list)
    promises: list[tuple[int, str, int | None]] = field(default_factory=list)
    name: str = ""


def names_of(frame: Frame, keys: set[str]) -> dict[str, str]:
    out = {}
    for k in keys:
        if k.startswith("name:"):
            out[k] = k[5:].title()
        else:
            out[k] = frame.get(identity_c.IDENTITY(k)).name or k
    return out


def query_of(frame: Frame, store: Any) -> str:
    ep = frame.episode
    if ep is None:
        return ""
    reply_to = ep.attrs.get("reply_to")
    if reply_to is not None:
        rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id=?", (reply_to,))
        if rows:
            return str(rows[0][0])
    args = ep.attrs.get("args") or {}
    return " ".join(str(v) for k, v in args.items() if str(k).startswith("brief:"))


def touches(text: str, topics: tuple[str, ...]) -> bool:
    """Le texte touche-t-il un de ces sujets (radicaux communs) ?"""
    if not topics:
        return False
    have = stems(text)
    return any(stems(topic) & have for topic in topics)


def sensitivity_of(frame: Frame, item: Item, interlocutor: str | None) -> int:
    """Un souvenir qui touche un sujet délicat d'une autre personne concernée
    devient une confidence, quoi qu'en ait dit la consolidation."""
    level = item.sensitivity
    for other in item.about:
        if other == interlocutor or other.startswith("name:"):
            continue
        if touches(item.text, frame.get(social_c.SENSITIVE(other))):
            return max(level, int(Sensitivity.CONFIDENCE))
    return level


def items_by_id(store: Any, ids: list[int]) -> dict[int, Item]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = store.query_mind(f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE id IN ({marks})",
                            tuple(ids))
    return {int(r[0]): Item.of(dict(zip(ITEM_COLUMNS, r, strict=True))) for r in rows}


def promises_to(frame: Frame, store: Any, person: str) -> list[tuple[int, str, int | None]]:
    """Les promesses en cours faites à cette personne, avec leur texte. Ne
    vérifie pas la porte de sa fiche (``private_ok``) : à l'appelant de le faire."""
    pending = frame.get(c.PROMISES_TO(person))
    if not pending:
        return []
    texts = {i: it.text for i, it in items_by_id(store, [pr.id for pr in pending]).items()}
    return [(pr.id, texts.get(pr.id, ""), pr.due) for pr in pending if texts.get(pr.id)]


@MEMORY.enricher("recall", episodes=CONVERSATIONAL, deadline_ms=2500)
async def _recall(s: MemoryState, frame: Frame, ports: Mapping[str, Any]) -> Recall | None:
    vectors, store = ports.get("vectors"), ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or aud is None or not ep.target:
        return None
    p = params(frame.env.params_of("memory", frame.root))
    person = frame.get(identity_c.PERSON(ep.target))
    out = Recall(name=frame.get(identity_c.IDENTITY(ep.target)).name)
    if aud.private_ok:
        out.promises = promises_to(frame, store, person)
    query = query_of(frame, store)
    if vectors is None or not query.strip():
        return out
    hits = [(k, sim) for k, sim in await vectors.search(query, p.recall_k) if sim >= p.recall_floor]
    if not hits:
        return out
    sims = dict(hits)
    items = items_by_id(store, [k for k, _ in hits])
    mood = frame.get(affect_c.MOOD)
    mood_valence = A.valence(mood.felt) * mood.felt_intensity if mood.felt_intensity >= 0.1 else 0.0
    now = frame.now
    ranked: list[tuple[float, Item, Verdict]] = []
    for item in items.values():
        if item.status != "active" or item.kind not in (c.SOUVENIR, c.BELIEF) or dormant(item, now, p):
            continue
        verdict = admissible(item.about, sensitivity_of(frame, item, person), person, aud)
        if not verdict.ok:
            continue
        ranked.append((rank(item, sims[item.id], now, p, interlocutor=person, mood_valence=mood_valence), item,
                       verdict))
    ranked.sort(key=lambda r: (-r[0], r[1].id))
    names = names_of(frame, {o for _, it, _ in ranked for o in it.about})
    for _score, item, verdict in ranked:
        bucket, cap = (out.souvenirs, p.max_souvenirs) if item.kind == c.SOUVENIR else (out.beliefs, p.max_beliefs)
        if len(bucket) < cap:
            bucket.append(Recalled(item, verdict, item.text + tag(verdict, names)))
    chunk_ids = [k for k, _ in hits if k not in items]
    if chunk_ids:
        marks = ",".join("?" * len(chunk_ids))
        room = ep.attrs.get("room") or aud.room
        if room:
            # dans un salon : seulement ce qui s'y est dit (public pour ce salon)
            rows = store.query_mind(f"SELECT id, at, user_text, reply_text FROM {c.CHUNKS_TABLE} "
                                    f"WHERE id IN ({marks}) AND room=?", (*chunk_ids, room))
        else:
            # en privé : ses échanges privés — sur ses autres poignées seulement si sa fiche est ouverte
            handles = tuple(frame.get(identity_c.HANDLES(person))) if aud.private_ok else ()
            handles = tuple(sorted({ep.target, *handles}))
            hmarks = ",".join("?" * len(handles))
            rows = store.query_mind(f"SELECT id, at, user_text, reply_text FROM {c.CHUNKS_TABLE} "
                                    f"WHERE id IN ({marks}) AND room IS NULL AND person IN ({hmarks})",
                                    (*chunk_ids, *handles))
        before = ep.attrs.get("reply_to") or now
        exchanges = [Exchange(int(i), int(at), u, r) for i, at, u, r in rows]
        # les échanges encore dans le fil montré ne se répètent pas ; les plus pertinents d'abord
        exchanges = [e for e in exchanges if now - e.at > 10 * 60 * 1_000_000 or e.id < before]
        exchanges.sort(key=lambda e: (-sims.get(e.id, 0.0), e.id))
        out.exchanges = exchanges[: p.max_chunks]
    return out


def _lines(recalled: list[Recalled], now: int, *, beliefs: bool) -> list[str]:
    lines = []
    for r in recalled:
        if beliefs:
            how = ORIGIN_FR.get(r.item.origin or "", "")
            lines.append(f"- {r.label}" + (f" ({how})" if how else ""))
        else:
            lines.append(f"- {age_words(r.item.born_at, now)} : {r.label}")
    return lines


def _body(recall: Recall, frame: Frame, *, witness: bool) -> SectionBody | None:
    souvenirs = [r for r in recall.souvenirs if r.verdict.witness == witness]
    beliefs = [r for r in recall.beliefs if r.verdict.witness == witness]
    if not souvenirs and not beliefs:
        return None
    lines: list[str] = []
    if souvenirs:
        lines += ["Des souvenirs :", *_lines(souvenirs, frame.now, beliefs=False)]
    if beliefs:
        lines += ["Ce que tu sais :", *_lines(beliefs, frame.now, beliefs=True)]
    lines.append("Sers-t'en seulement si ça vient naturellement ; ce qui est étiqueté, c'est à toi de juger.")
    shown = souvenirs + beliefs
    return SectionBody("\n".join(lines), level=max((r.verdict.level for r in shown), default=0),
                       provenance=tuple(f"memory:{r.item.id}" for r in shown), witness=witness)


@MEMORY.section("memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=30,
                title="CE QUI TE REVIENT")
def _memories(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=False) if recall else None


@MEMORY.section("shared_memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=31,
                title="CE QUE VOUS AVEZ VÉCU AVEC D'AUTRES")
def _shared(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=True) if recall else None


@MEMORY.section("past_exchanges", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=20,
                title="VOS ÉCHANGES PASSÉS")
def _exchanges(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.exchanges:
        return None
    who = recall.name or "la personne"
    lines = [f"- {age_words(e.at, frame.now)}, {who} : « {e.user_text[:240]} » — toi : « {e.reply_text[:240]} »"
             for e in recall.exchanges]
    return SectionBody("\n".join(lines), provenance=tuple(f"chunk:{e.id}" for e in recall.exchanges))


@MEMORY.section("promises", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=60,
                title="CE QUE TU LUI AS PROMIS")
def _promises(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.promises:
        return None
    lines = []
    for pid, text, due in recall.promises:
        when = f" (pour le {frame.local(due):%d/%m})" if due else ""
        lines.append(f"- [#{pid}] {text}{when}")
    lines.append("Quand une promesse est tenue ou abandonnée, dis-le avec l'outil memory_promise_done.")
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{pid}" for pid, _, _ in recall.promises))
