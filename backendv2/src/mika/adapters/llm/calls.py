"""Le registre des appels de modèle, dans ``views.db`` (jetable) : ce qu'ils
ont coûté par jour et par rôle, et les derniers en détail. Rétention bornée.

La passerelle garde en mémoire les derniers appels ; ce registre survit aux
redémarrages, pour qu'on voie ce que coûte une semaine.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from mika.adapters.llm.gateway import LLMTrace
from mika.kernel.clock import DAY

log = logging.getLogger("mika.llm")

TABLE = "llm_calls"
KEEP_DAYS = 30
_PRUNE_EVERY = 500
_COLUMNS = ("at", "role", "backend", "model", "lane", "priority", "latency_us", "wait_us", "input_tokens",
            "output_tokens", "cache_read", "cache_write", "cost_usd", "outcome", "call_id")
_TEXT = frozenset({"role", "backend", "model", "lane", "outcome", "call_id"})


@dataclass(frozen=True, slots=True)
class Usage:
    """Un agrégat (un jour, un rôle)."""

    key: str
    calls: int
    failures: int
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_write: int
    cost_usd: float
    latency_avg_s: float

    @property
    def cache_ratio(self) -> float:
        """Part de l'entrée lue depuis le cache (ce qui ne coûte presque rien)."""
        total = self.input_tokens + self.cache_read + self.cache_write
        return self.cache_read / total if total else 0.0


class CallLog:
    def __init__(self, store: Any, *, keep_days: int = KEEP_DAYS) -> None:
        self.store = store
        self.keep_us = keep_days * DAY
        self._pending: set[asyncio.Task[Any]] = set()
        self._since_prune = 0
        self._ready = False

    async def open(self) -> None:
        cols = ", ".join(f"{c} {'TEXT' if c in _TEXT else 'REAL' if c == 'cost_usd' else 'INTEGER'}" for c in _COLUMNS)

        def create(sql: Any) -> None:
            sql.execute(f"CREATE TABLE IF NOT EXISTS {TABLE}(id INTEGER PRIMARY KEY, {cols})")
            sql.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_at ON {TABLE}(at)")

        await self.store.run_views(create)
        self._ready = True

    def record(self, tr: LLMTrace) -> None:
        """Appelé par la passerelle à chaque appel (synchrone) : l'écriture part
        en tâche, sans retenir l'appel."""
        if not self._ready:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        values = tuple(getattr(tr, c) for c in _COLUMNS)
        self._since_prune += 1
        prune_before = tr.at - self.keep_us if self._since_prune >= _PRUNE_EVERY else None
        if prune_before is not None:
            self._since_prune = 0

        def write(sql: Any) -> None:
            sql.execute(f"INSERT INTO {TABLE}({', '.join(_COLUMNS)}) VALUES({', '.join('?' * len(_COLUMNS))})", values)
            if prune_before is not None:
                sql.execute(f"DELETE FROM {TABLE} WHERE at < ?", (prune_before,))

        task = loop.create_task(self.store.run_views(write))
        self._pending.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._pending.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.warning("registre des appels : écriture perdue (%r)", task.exception())

    async def flush(self) -> None:
        while self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def prune(self, now: int) -> int:
        def run(sql: Any) -> int:
            return int(sql.execute(f"DELETE FROM {TABLE} WHERE at < ?", (now - self.keep_us,)).rowcount or 0)

        return int(await self.store.run_views(run))

    def recent(self, limit: int = 100, *, role: str = "") -> list[LLMTrace]:
        if not self._ready:
            return []
        where, args = ("WHERE role=?", (role,)) if role else ("", ())
        rows = self.store.query_views(f"SELECT {', '.join(_COLUMNS)} FROM {TABLE} {where} ORDER BY at DESC LIMIT ?",
                                      (*args, max(1, min(limit, 1000))))
        return [LLMTrace(**dict(zip(_COLUMNS, r, strict=True))) for r in rows]

    def usage(self, since: int, *, by: str = "role", day_of: Any = None) -> list[Usage]:
        """Agrégats depuis ``since``, par ``role``, ``backend`` ou jour (``by="day"``,
        ``day_of(at) -> str`` donne le jour local)."""
        if not self._ready:
            return []
        rows = self.store.query_views(
            f"SELECT at, role, backend, outcome, input_tokens, output_tokens, cache_read, cache_write, cost_usd, "
            f"latency_us FROM {TABLE} WHERE at >= ? ORDER BY at", (since,))
        acc: dict[str, list[float]] = {}
        for at, role, backend, outcome, i, o, cr, cw, cost, lat in rows:
            key = day_of(at) if by == "day" and day_of is not None else backend if by == "backend" else role
            a = acc.setdefault(key, [0, 0, 0, 0, 0, 0, 0.0, 0])
            a[0] += 1
            a[1] += 0 if outcome == "ok" else 1
            a[2] += i
            a[3] += o
            a[4] += cr
            a[5] += cw
            a[6] += cost or 0.0
            a[7] += lat
        return [Usage(k, int(a[0]), int(a[1]), int(a[2]), int(a[3]), int(a[4]), int(a[5]), float(a[6]),
                      a[7] / a[0] / 1e6 if a[0] else 0.0) for k, a in sorted(acc.items())]
