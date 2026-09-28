"""Projections : modèles de lecture matérialisés depuis le journal.

- T0 : tables dans ``mind.db``, appliquées dans la transaction d'ajout
  (versionnées dans ``meta`` ; reconstruites au démarrage si la version change).
- T1/T2 : tables dans ``views.db``, rattrapées par lots ; le point de contrôle
  est écrit dans la même transaction que les lignes (exactement une fois). Un
  événement qui échoue est réessayé puis mis en quarantaine — la projection
  continue. Une nouvelle version est construite à côté puis basculée
  (bleu/vert). T2 : la partie coûteuse (``prepare``) tourne hors de l'écrivain.

Protocole d'une projection : ``create(sql, suffixe)``, ``drop(sql, suffixe)``,
``apply(sql, événements, suffixe[, préparé])``, et en option ``prepare(événements)``
et ``forget(sql, sujet, suffixe)``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Sequence
from itertools import islice
from typing import TYPE_CHECKING, Any

from mika.kernel.events import Event
from mika.kernel.faculty import ProjectorSpec, Tier
from mika.kernel.state import Root
from mika.ports.store import Sql
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.effects import with_content

if TYPE_CHECKING:
    from mika.runtime.mind import Mind


def suffix(version: int) -> str:
    return f"_v{version}"


async def ensure_t0(mind: Mind) -> list[str]:
    """Crée (ou reconstruit si leur version a changé) les projections T0."""
    rebuilt: list[str] = []
    for spec in mind.registry.projectors.values():
        if spec.tier is not Tier.T0:
            continue
        key = f"t0:{spec.name}"
        rows = mind.store.query_mind("SELECT value FROM meta WHERE key=?", (key,))
        current = int(rows[0][0]) if rows else None
        if current == spec.version:
            continue
        events = [with_content(mind, mind.decode(s)) for s in mind.store.read(after=0, types=spec.types)]

        def rebuild(sql: Sql, spec: ProjectorSpec = spec, events: list[Event[Any]] = events, current=current) -> None:
            if current is not None:
                spec.projector.drop(sql, "")
            spec.projector.create(sql, "")
            if events:
                spec.projector.apply(sql, events, "")
            sql.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (f"t0:{spec.name}", str(spec.version)))

        await mind.store.run_mind(rebuild)
        rebuilt.append(spec.name)
    return rebuilt


class ProjectionWorker:
    def __init__(self, mind: Mind, *, batch: int = 256, retries: int = 3) -> None:
        self.mind = mind
        self.batch = batch
        self.retries = retries
        self._wake = asyncio.Event()
        self._stopping = False
        self._pool: concurrent.futures.ProcessPoolExecutor | None = None
        self.quarantined: list[tuple[str, int, str]] = []
        mind.subscribe(self._on_events)

    @property
    def specs(self) -> list[ProjectorSpec]:
        return [p for p in self.mind.registry.projectors.values() if p.tier in (Tier.T1, Tier.T2)]

    def _on_events(self, events: Sequence[Event[Any]], root: Root) -> None:
        types = {t for s in self.specs for t in s.types}
        if any(e.type.name in types for e in events):
            self._wake.set()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    async def run(self) -> None:
        try:
            while not self._stopping:
                self._wake.clear()
                for spec in self.specs:
                    await self.catch_up(spec)
                if self._stopping:
                    break
                await self._wake.wait()
        finally:
            self.close()

    def lag(self) -> dict[str, int]:
        out = {}
        for spec in self.specs:
            st = self.mind.store.projector_state(spec.name)
            out[spec.name] = self.mind.head - (st[1] if st else 0)
        return out

    async def catch_up(self, spec: ProjectorSpec) -> None:
        st = self.mind.store.projector_state(spec.name)
        if st is None:
            await self.mind.store.run_views(lambda sql: self._create(sql, spec.name, spec, spec.version))
        elif st[0] != spec.version:
            await self._blue_green(spec, st[0])
        await self._follow(spec, spec.name, suffix(spec.version))

    def _create(self, sql: Sql, name: str, spec: ProjectorSpec, version: int) -> None:
        spec.projector.create(sql, suffix(version))
        sql.execute("INSERT OR REPLACE INTO projector_state(name, version, applied_seq) VALUES(?,?,0)",
                    (name, version))

    async def _follow(self, spec: ProjectorSpec, name: str, sfx: str) -> None:
        while True:
            st = self.mind.store.projector_state(name)
            applied = st[1] if st else 0
            stored = list(islice(self.mind.store.read(after=applied, types=spec.types), self.batch))
            if not stored:
                return
            events = [with_content(self.mind, self.mind.decode(s)) for s in stored]
            last = stored[-1].seq
            ok = await self._apply(spec, name, sfx, events, last)
            if not ok:
                for ev in events:
                    await self._apply_one(spec, name, sfx, ev)
            await asyncio.sleep(0)

    async def _prepared(self, spec: ProjectorSpec, events: Sequence[Event[Any]]) -> Any:
        """La partie coûteuse d'une projection. En T2, elle tourne dans un
        **processus** : dans un fil, un calcul Python garde le verrou global et
        retarde chaque ajout du Mind. Elle reçoit des lignes simples
        (``seq``, ``type``, ``at``, ``data``), transportables d'un processus à
        l'autre. Sous la boucle simulée, l'exécuteur est en ligne."""
        prepare = getattr(spec.projector, "prepare", None)
        if prepare is None:
            return None
        rows = [{"seq": e.seq, "type": e.type.name, "at": e.at, "data": e.data.model_dump(mode="json")}
                for e in events]
        if spec.tier is Tier.T2:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor(), prepare, rows)
        return prepare(rows)

    def _executor(self) -> Any:
        if self._pool is None:
            self._pool = concurrent.futures.ProcessPoolExecutor(max_workers=1)
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    async def _apply(self, spec: ProjectorSpec, name: str, sfx: str, events: Sequence[Event[Any]], last: int) -> bool:
        prep = await acall(self._prepared, spec, events, label=f"préparation {name}")
        if isinstance(prep, Failed):
            return False

        def fn(sql: Sql) -> None:
            if prep is None:
                spec.projector.apply(sql, events, sfx)
            else:
                spec.projector.apply(sql, events, sfx, prep)
            sql.execute("UPDATE projector_state SET applied_seq=? WHERE name=?", (last, name))

        out = await acall(self.mind.store.run_views, fn, label=f"projection {name}")
        return not isinstance(out, Failed)

    async def _apply_one(self, spec: ProjectorSpec, name: str, sfx: str, ev: Event[Any]) -> None:
        for attempt in range(self.retries):
            if await self._apply(spec, name, sfx, [ev], ev.seq):
                return
            await asyncio.sleep(0.01 * (attempt + 1))
        error = f"échec après {self.retries} essais"
        self.quarantined.append((name, ev.seq, error))

        def fn(sql: Sql) -> None:
            sql.execute("INSERT OR REPLACE INTO projector_quarantine(name, seq, error) VALUES(?,?,?)",
                        (name, ev.seq, error))
            sql.execute("UPDATE projector_state SET applied_seq=? WHERE name=?", (ev.seq, name))

        await self.mind.store.run_views(fn)

    async def _blue_green(self, spec: ProjectorSpec, old_version: int) -> None:
        building = f"{spec.name}@{spec.version}"
        if self.mind.store.projector_state(building) is None:
            await self.mind.store.run_views(lambda sql: self._create(sql, building, spec, spec.version))
        await self._follow(spec, building, suffix(spec.version))
        applied = self.mind.store.projector_state(building)[1]  # type: ignore[index]

        def switch(sql: Sql) -> None:
            sql.execute("UPDATE projector_state SET version=?, applied_seq=? WHERE name=?",
                        (spec.version, applied, spec.name))
            sql.execute("DELETE FROM projector_state WHERE name=?", (building,))
            call(spec.projector.drop, sql, suffix(old_version), label="abandon de l'ancienne version")

        await self.mind.store.run_views(switch)
