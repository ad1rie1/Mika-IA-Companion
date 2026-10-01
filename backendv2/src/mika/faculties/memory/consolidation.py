"""Les processus de la mémoire.

**Consolider.** Une fenêtre se relit quand elle est mûre (assez de messages
de personnes) ou calme (plus rien depuis quelques minutes) — jamais en
coupant une question de sa réponse : une question récente sans réponse est
gardée pour la fois suivante. Le modèle (rôle ``extract``) dit ce qu'elle en
garde ; ce qui ressemble de très près à ce qu'elle sait déjà le **renforce**
au lieu de faire un doublon. Tout part en un seul ajout gardé par le point de
contrôle, qui n'avance que sur un succès — ou, après plusieurs échecs sur la
même fenêtre, en le disant (``failed``) plutôt que de bloquer pour toujours.

**Indexer.** L'index des vecteurs est un cache : ce processus y ajoute ce
qui manque (éléments retenus, extraits d'échanges).
"""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.faculty import MEMORY, MemoryState, params
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.llm import LLMRequest, Message
from mika.ports.vectors import VectorItem
from mika.vocab.affect import emotion_of
from mika.vocab.people import fold

BATCH = 64


def _rows(store: Any, sql: str, params_: tuple[Any, ...], columns: tuple[str, ...]) -> list[dict[str, Any]]:
    return [dict(zip(columns, r, strict=True)) for r in store.query_mind(sql, params_)]


@MEMORY.process("memory.consolidate", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, c.CONSOLIDATED],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=600)
class Consolidate:
    def __init__(self) -> None:
        self.retry_at = 0
        self.attempts: dict[int, int] = {}
        #: rien de consolidable à ce ``seq`` (des questions attendent) : on attend un événement
        self.stuck_at: int | None = None

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if not state.pending or self.stuck_at == frame.seq:
            return None
        if state.pending[0] in set(frame.get(rt.AWAITING)):
            return None  # la plus ancienne question attend sa réponse : réveil par l'énoncé
        p = params(frame.env.params_of("memory", frame.root))
        if self.retry_at > frame.now:
            return self.retry_at
        if len(state.pending) >= p.min_messages:
            return frame.now
        return state.last_message_at + p.quiet_us

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None or not state.pending:
            return
        p = params(frame.env.params_of("memory", frame.root))
        rows = store.query_mind(
            f"SELECT id, at, role, person, text, reply_to FROM {transcript_c.THREAD_TABLE} WHERE id>? "
            "ORDER BY id LIMIT ?", (state.checkpoint, p.max_window))
        rows = [r[:5] for r in window(rows, set(frame.get(rt.AWAITING)))]
        if not rows:
            self.stuck_at = frame.seq
            return
        self.stuck_at = None
        upto = rows[-1][0]
        threads, people = self._threads(frame, rows)
        vectors = ctx.ports.get("vectors")
        known = await self._known_beliefs(store, vectors, " ".join(r[4] for r in rows)[-2000:])
        promises = self._promises(store, state, {t.person for t in threads})
        prompt = x.render(threads, now=frame.local(), beliefs=[(i, t) for i, t, _ in known],
                          promises=[(i, frame.get(identity_c.IDENTITY(to)).name or to, t) for i, to, t in promises])
        request = LLMRequest(role="extract", call_id=f"{ctx.run_id}#0", system_stable=x.SYSTEM,
                             messages=(Message("user", prompt),), tools=(x.tool(),), max_tokens=2500,
                             lane="background", priority=2, meta={"window": (rows[0][0], upto)})
        # si l'appel lève, on ne réessaie pas avant le délai (aucune rafale)
        self.retry_at = frame.now + p.retry_us
        response = await ctx.llm.call(request)
        extraction = x.parse(response)
        if extraction is None:
            # les essais se comptent par point de départ : la fin de la fenêtre bouge avec les messages
            start = state.checkpoint
            self.attempts[start] = self.attempts.get(start, 0) + 1
            if self.attempts[start] < p.max_attempts:
                return
            drafts: list[Draft[Any]] = [c.CONSOLIDATED.draft(upto=upto, failed=True, call_id=request.call_id,
                                                             model=response.model)]
        else:
            self.retry_at = 0
            drafts = await self._drafts(extraction, frame, people, known, promises, rows, vectors, p,
                                        request.call_id)
            drafts.append(c.CONSOLIDATED.draft(upto=upto, produced=len(drafts), call_id=request.call_id,
                                               model=response.model))
        self.attempts.pop(state.checkpoint, None)
        await ctx.emit(*drafts, guard=Guard("point de contrôle", reads=(c.CHECKPOINT,)))

    # ── ce qu'on montre au modèle ──
    def _threads(self, frame: Frame, rows: list[tuple[Any, ...]]) -> tuple[list[x.Thread], dict[str, str]]:
        by_person: dict[str, list[x.Line]] = {}
        names: dict[str, str] = {}
        for seq, at, role, handle, text in rows:
            if not handle:
                continue
            if handle not in names:
                view = frame.get(identity_c.IDENTITY(handle))
                names[handle] = view.name or handle
            speaker = "Mika" if role == "assistant" else names[handle]
            by_person.setdefault(handle, []).append(x.Line(seq, at, speaker, text))
        threads = [x.Thread(h, names[h], tuple(lines)) for h, lines in sorted(by_person.items())]
        people = {fold(names[h]): frame.get(identity_c.PERSON(h)) for h in names}
        return threads, people

    async def _known_beliefs(self, store: Any, vectors: Any, text: str) -> list[tuple[int, str, str | None]]:
        if vectors is None or not text.strip():
            return []
        hits = await vectors.search(text, 8, kinds={c.BELIEF})
        if not hits:
            return []
        ids = [k for k, _ in hits]
        marks = ",".join("?" * len(ids))
        found = store.query_mind(f"SELECT id, text, source FROM {c.ITEMS_TABLE} WHERE id IN ({marks}) "
                                 "AND status='active' ORDER BY id", tuple(ids))
        return [(int(i), t, s) for i, t, s in found]

    def _promises(self, store: Any, state: MemoryState, persons: set[str]) -> list[tuple[int, str, str]]:
        pending = [pr for pr in state.promises.values() if pr.to in persons]
        if not pending:
            return []
        ids = [pr.id for pr in pending]
        marks = ",".join("?" * len(ids))
        texts = dict(store.query_mind(f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE id IN ({marks})", tuple(ids)))
        return [(pr.id, pr.to, texts.get(pr.id, "")) for pr in pending]

    # ── ce qu'on en garde ──
    async def _drafts(self, ex: x.Extraction, frame: Frame, people: dict[str, str],
                      known: list[tuple[int, str, str | None]], promises: list[tuple[int, str, str]],
                      rows: list[tuple[Any, ...]], vectors: Any, p: Any, call_id: str) -> list[Draft[Any]]:
        drafts: list[Draft[Any]] = []
        known_ids = {i for i, _, _ in known}
        sources_of = self._sources(rows, {h: frame.get(identity_c.PERSON(h)) for h in {r[3] for r in rows if r[3]}})
        participants = tuple(sorted({people[k] for k in people}))

        def concerned(names: list[str]) -> tuple[str, ...]:
            """Dans le doute, on ferme : un élément dont le modèle ne nomme
            personne concerne les personnes de la conversation — sinon il
            serait rangé comme ne concernant personne, donc dicible à tous."""
            return x.resolve(names, people) or participants
        seen: set[tuple[str, str]] = set()  # le même élément deux fois dans un lot n'en fait qu'un

        def fresh(kind: str, text: str) -> bool:
            key = (kind, " ".join(fold(text).split()))
            if key in seen:
                return False
            seen.add(key)
            return True

        for s in ex.souvenirs:
            if not fresh(c.SOUVENIR, s.texte):
                continue
            about = concerned(s.personnes)
            twin = await self._twin(vectors, s.texte, c.SOUVENIR, p)
            if twin is not None:
                drafts.append(c.REINFORCED.draft(item=twin, sources=sources_of(about)))
                continue
            e = emotion_of(s.emotion)
            sens = x.sensitivity(s.sensibilite, has_person=bool(about))
            drafts.append(c.REMEMBERED.draft(
                text=Content.of(s.texte, level=sens), about=about, sensitivity=sens,
                importance=x.IMPORTANCE.get(s.importance, 0.45), emotion=e.value if e else None,
                sources=sources_of(about), call_id=call_id))
        for b in ex.croyances:
            if not fresh(c.BELIEF, b.texte):
                continue
            about = concerned(b.personnes)
            sources = x.resolve([b.source], people) if b.source else ()
            source = sources[0] if sources else None
            twin = await self._twin(vectors, b.texte, c.BELIEF, p)
            if twin is not None and twin not in {b.remplace}:
                previous = next((s for i, _, s in known if i == twin), None)
                drafts.append(c.REINFORCED.draft(item=twin, corroborated=bool(source and previous and source != previous),
                                                 source=source, sources=sources_of(about)))
                continue
            sens = x.sensitivity(b.sensibilite, has_person=bool(about))
            drafts.append(c.BELIEVED.draft(
                text=Content.of(b.texte, level=sens), about=about, sensitivity=sens,
                importance=x.IMPORTANCE.get(b.importance, 0.45), confidence=round(b.confiance, 3),
                origin=x.ORIGIN.get(fold(b.origine), "told"), source=source,
                replaces=b.remplace if b.remplace in known_ids else None, sources=sources_of(about), call_id=call_id))
        pending_ids = {i for i, _, _ in promises}
        for pr in ex.promesses:
            if not fresh(c.PROMISE, pr.texte):
                continue
            to = x.resolve([pr.envers], people)
            if not to:
                continue
            drafts.append(c.PROMISE_NOTICED.draft(
                text=Content.of(pr.texte, level=2), to=to[0], due=x.due(pr.echeance, frame.env.tz_of(frame.root)),
                sensitivity=2, sources=sources_of(to), call_id=call_id))
        for done in ex.promesses_tenues:
            if done.id in pending_ids:
                status = c.HONORED if fold(done.statut).startswith("tenu") else c.DROPPED
                drafts.append(c.PROMISE_RESOLVED.draft(promise=done.id, status=status))
        return drafts

    async def _twin(self, vectors: Any, text: str, kind: str, p: Any) -> int | None:
        if vectors is None:
            return None
        hits = await vectors.search(text, 1, kinds={kind})
        if hits and hits[0][1] >= p.dedup_similarity:
            return hits[0][0]
        return None

    @staticmethod
    def _sources(rows: list[tuple[Any, ...]], person_of: dict[str, str]) -> Any:
        """Les messages d'où vient un élément : ceux des personnes qu'il
        concerne (toutes leurs adresses), sinon toute la fenêtre."""
        by_person: dict[str, list[int]] = {}
        for seq, _at, _role, handle, _text in rows:
            by_person.setdefault(person_of.get(handle, handle), []).append(int(seq))
        everything = tuple(int(r[0]) for r in rows)

        def of(about: tuple[str, ...]) -> tuple[int, ...]:
            seqs = sorted({s for a in about for s in by_person.get(a, [])})
            return tuple(seqs) or everything

        return of


@MEMORY.process("memory.index", wake_on=[c.REMEMBERED, c.BELIEVED, c.PROMISE_NOTICED, rt.UTTERANCE],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=600)
class Index:
    def __init__(self) -> None:
        self.done: tuple[int, int] | None = None

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if (state.items, state.chunks) != self.done else None

    async def run(self, ctx: Any) -> None:
        state: MemoryState = ctx.state
        key = (state.items, state.chunks)
        vectors, store = ctx.ports.get("vectors"), ctx.ports.get("store")
        if vectors is None or store is None:
            self.done = key
            return
        indexed = vectors.indexed()
        items = [r for r in _rows(store, f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE}", (), ITEM_COLUMNS)
                 if r["id"] not in indexed]
        chunks = [r for r in _rows(store, f"SELECT id, person, user_text, reply_text FROM {c.CHUNKS_TABLE}", (),
                                   ("id", "person", "user_text", "reply_text")) if r["id"] not in indexed]
        todo = [VectorItem(int(r["id"]), r["kind"], r["text"], tuple(_about(r["about"]))) for r in items]
        todo += [VectorItem(int(r["id"]), c.CHUNK, f"{r['user_text']}\n{r['reply_text']}", (r["person"],))
                 for r in chunks]
        for i in range(0, len(todo), BATCH):
            await vectors.upsert(todo[i:i + BATCH])
        self.done = key


def window(rows: list[tuple[Any, ...]], awaiting: set[int]) -> list[tuple[Any, ...]]:
    """La plus longue fenêtre qui ne coupe aucune paire : une question n'y
    entre qu'avec sa réponse, et jamais une question qui attend encore la
    sienne. ``rows`` : ``(id, at, role, person, text, reply_to)`` triés."""
    answers = {r[5]: r[0] for r in rows if r[2] == "assistant" and r[5] is not None}
    upto = rows[-1][0] if rows else 0
    changed = True
    while changed:
        changed = False
        for seq, _at, role, *_ in rows:
            if seq > upto or role != "user":
                continue
            answer = answers.get(seq)
            if seq in awaiting or (answer is not None and answer > upto):
                upto = seq - 1
                changed = True
                break
    return [r for r in rows if r[0] <= upto]


def _about(raw: str) -> list[str]:
    return list(json.loads(raw or "[]"))
