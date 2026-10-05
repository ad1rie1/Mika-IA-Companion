"""La nuit de la mémoire.

- **Réfléchir** : une pensée restée forte, digérée pendant la nuit, devient un
  souvenir (« Après y avoir repensé cette nuit : … ») — une fois. Ce qu'on lui
  a demandé de taire, ou ce qui laisse deviner un secret qu'elle garde déjà,
  reste un secret : la nuit ne le blanchit pas.
- **Trier** : après trois heures de sommeil, une fois par nuit, un souvenir du
  jour presque identique à un souvenir plus ancien s'y fond (sans modèle) :
  un seul souvenir, qui garde la plus haute des deux importances et des deux
  sensibilités, et les personnes de l'un et de l'autre (la projection).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.consolidation import kept_secrets
from mika.faculties.memory.faculty import MEMORY, MemoryState, Reflection, params
from mika.kernel.clock import instant, local_date_of_night
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.vocab.words import stems


@MEMORY.process("memory.reflect", wake_on=[attention_c.DIGESTED, c.REMEMBERED], lane="background",
                catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Reflect:
    def __init__(self) -> None:
        self.skipped: set[int] = set()

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if any(r.thought not in self.skipped for r in state.reflections) else None

    async def run(self, ctx: Any) -> None:
        state: MemoryState = ctx.state
        store = ctx.ports.get("store")
        if store is None:
            return
        pending = [r for r in state.reflections if r.thought not in self.skipped]
        texts = store.content([r.text_ref for r in pending])
        drafts = []
        for r in pending:
            text = texts.get(r.text_ref)
            if not text:
                self.skipped.add(r.thought)  # effacée (oubli) : rien à repenser
                continue
            mark = f"réflexion:{r.thought}"
            # une pensée sur quelqu'un vient de ce qu'il ou elle lui a dit : c'est son confident, pas un autre
            drafts.append(c.REMEMBERED.draft(
                text=Content.of(f"Après y avoir repensé cette nuit : {text}", level=r.sensitivity), about=r.about,
                sensitivity=r.sensitivity, importance=0.5, emotion=r.emotion, call_id=mark, dedupe_key=mark,
                told_by=r.about, heard_by=r.about, secret=self._secret(ctx.frame, store, r, text)))
        if drafts:
            await ctx.emit(*drafts)

    @staticmethod
    def _secret(frame: Frame, store: Any, r: Reflection, text: str) -> bool:
        """Comme à la consolidation : la pensée cite qu'on lui a demandé de le taire, ou laisse deviner un secret
        qu'elle garde déjà sur ces personnes (une confidence du soir cite le message même que la consolidation a
        rangé en secret — repensée la nuit, elle ne doit pas devenir un souvenir dicible aux amies)."""
        if x.says_secret([text]):
            return True
        names = {st for person in r.about for st in stems(frame.get(identity_c.IDENTITY(person)).name or "")}
        return x.echoes(text, kept_secrets(store, r.about), names | {"mika"})


@MEMORY.process("memory.night", wake_on=[*body_c.ALL], lane="night", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Sort:
    def _night(self, state: MemoryState, frame: Frame) -> str | None:
        since = frame.get(body_c.ASLEEP_SINCE)
        if not since:
            return None
        night = local_date_of_night(since, frame.env.tz_of(frame.root), 5).isoformat()
        return None if night == state.sorted_night else night

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if self._night(state, frame) is None:
            return None
        p = params(frame.env.params_of("memory", frame.root))
        return max(frame.now, frame.get(body_c.ASLEEP_SINCE) + p.night_after_sleep_us)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        night = self._night(ctx.state, frame)
        if night is None:
            return
        p = params(frame.env.params_of("memory", frame.root))
        store, vectors = ctx.ports.get("store"), ctx.ports.get("vectors")
        merges: list[tuple[int, int]] = []
        if store is not None and vectors is not None:
            merges = await self._merges(store, vectors, frame, night, p)
        await ctx.emit(c.NIGHT_SORTED.draft(night=night, merges=tuple(merges), dedupe_key=f"tri:{night}"))

    async def _merges(self, store: Any, vectors: Any, frame: Frame, night: str, p: Any) -> list[tuple[int, int]]:
        tz = frame.env.tz_of(frame.root)
        day = date.fromisoformat(night)
        start = instant(datetime.combine(day, time(5), tzinfo=tz))
        end = instant(datetime.combine(day + timedelta(days=1), time(5), tzinfo=tz))
        rows = store.query_mind(f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE kind=? AND status='active' AND "
                                "born_at >= ? AND born_at < ? ORDER BY id DESC", (c.SOUVENIR, start, end))
        merged: set[int] = set()
        out: list[tuple[int, int]] = []
        for item_id, text in rows:
            if len(out) >= p.night_max_merges or item_id in merged:
                continue
            for hit, sim in await vectors.search(text, 4, kinds={c.SOUVENIR}):
                if hit == item_id or hit in merged or sim < p.night_merge_similarity or hit > item_id:
                    continue
                alive = store.query_mind(f"SELECT status FROM {c.ITEMS_TABLE} WHERE id=?", (hit,))
                if alive and alive[0][0] == "active":
                    out.append((hit, item_id))
                    merged |= {hit, item_id}
                    break
        return out
