"""Les séries mesurées pour les courbes de la console (``@f.series``).

Un processus échantillonne chaque mesure déclarée à son rythme (dix minutes
par défaut) dans ``views.db`` — jetable : les courbes recommencent si la base
est reconstruite. Rétention bornée ; au-delà d'une semaine, une mesure par
heure suffit. Lire rend des moyennes par tranches, prêtes à tracer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.orm import Mapped, mapped_column

from mika.kernel.clock import DAY, HOUR
from mika.kernel.faculty import CatchUp, ProcessSpec, SeriesSpec
from mika.ports.sql import Key, ViewsBase, upsert
from mika.runtime.boundary import Failed, call

log = logging.getLogger("mika.series")

TABLE = "series"
KEEP_DAYS = 60
THIN_AFTER_DAYS = 7


class SeriesRow(ViewsBase):
    """Une mesure : sa série, son instant, sa valeur."""

    __tablename__ = TABLE
    key: Mapped[str] = mapped_column(Key(200), primary_key=True)
    at: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    value: Mapped[float]


class SeriesStore:
    def __init__(self, store: Any, *, keep_days: int = KEEP_DAYS) -> None:
        self.store = store
        self.keep_us = keep_days * DAY
        self._ready = False
        self._pruned_at = 0

    async def open(self) -> None:
        await self.store.run_views(lambda sql: sql.create(SeriesRow))
        self._ready = True

    async def write(self, rows: Sequence[tuple[str, int, float]], now: int) -> None:
        if not self._ready or not rows:
            return
        prune = now - self._pruned_at > DAY

        def put(sql: Any) -> None:
            upsert(sql, SeriesRow, [{"key": k, "at": at, "value": v} for k, at, v in rows], keys=["key", "at"])
            if prune:
                sql.execute(delete(SeriesRow).where(SeriesRow.at < now - self.keep_us))
                # au-delà d'une semaine : la première mesure de chaque heure. L'heure d'une mesure est
                # ``at - at % HOUR`` (``at / HOUR`` serait une division entière sous SQLite, décimale sous MariaDB) ;
                # les mesures gardées passent par une table dérivée : MariaDB ne supprime pas d'une table relue
                cut = now - THIN_AFTER_DAYS * DAY
                first = (select(SeriesRow.key.label("k"), func.min(SeriesRow.at).label("m"))
                         .where(SeriesRow.at < cut).group_by(SeriesRow.key, SeriesRow.at - SeriesRow.at % HOUR)
                         .subquery())
                sql.execute(delete(SeriesRow).where(SeriesRow.at < cut, tuple_(SeriesRow.key, SeriesRow.at).not_in(
                    select(first.c.k, first.c.m))))

        await self.store.run_views(put)
        if prune:
            self._pruned_at = now

    def read(self, key: str, since: int, until: int, points: int = 240) -> list[tuple[int, float]]:
        """Des moyennes par tranches égales entre ``since`` et ``until`` (au plus ``points``)."""
        if not self._ready or until <= since:
            return []
        rows = self.store.query_views(select(SeriesRow.at, SeriesRow.value)
                                      .where(SeriesRow.key == key, SeriesRow.at.between(since, until))
                                      .order_by(SeriesRow.at))
        if len(rows) <= points:
            return [(int(at), float(v)) for at, v in rows]
        width = (until - since) / points
        buckets: dict[int, list[tuple[int, float]]] = {}
        for at, v in rows:
            buckets.setdefault(int((at - since) // width), []).append((int(at), float(v)))
        return [(sum(a for a, _ in b) // len(b), sum(v for _, v in b) / len(b)) for _, b in sorted(buckets.items())]


class Sampler:
    """Le processus : chaque mesure à son rythme, au plus une écriture par passage."""

    def __init__(self, store: SeriesStore, specs: Sequence[SeriesSpec]) -> None:
        self.store = store
        self.specs = list(specs)
        self.last: dict[str, int] = {}

    def next_due(self, state: Any, frame: Any, last_run: int | None) -> int | None:
        """Une mesure jamais prise est due tout de suite (pas « en retard » : l'ordonnanceur
        sauterait un retard qu'il n'a pas à rattraper)."""
        if not self.specs:
            return None
        return min(frame.now if s.key not in self.last else self.last[s.key] + s.every_us for s in self.specs)

    async def run(self, ctx: Any) -> None:
        frame = ctx.frame
        now = frame.now
        rows = []
        for s in self.specs:
            if now < self.last.get(s.key, 0) + s.every_us:
                continue
            self.last[s.key] = now
            got: Any = call(s.fn, frame.state(s.owner), frame, label=f"série {s.key}")
            if isinstance(got, Failed) or got is None:
                continue
            try:
                value = float(got)
            except (TypeError, ValueError):
                continue
            if value == value and abs(value) != float("inf"):  # fini
                rows.append((s.key, now, value))
        if rows:
            await self.store.write(rows, now)
        await asyncio.sleep(0)


def sampler_spec(sampler: Sampler) -> ProcessSpec:
    return ProcessSpec(owner="kernel", name="séries", process=sampler, priority=90, catch_up=CatchUp.SKIP,
                       max_quantum_us=HOUR, lane="background")
