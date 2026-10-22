"""Le registre des appels de modèle, dans ``views.db`` (jetable) : ce qu'ils
ont coûté par jour et par rôle, et les derniers en détail. Rétention bornée.

La passerelle garde en mémoire les derniers appels ; ce registre survit aux
redémarrages, pour qu'on voie ce que coûte une semaine — et, par la
corrélation, quels appels a faits un épisode (« pourquoi a-t-elle dit ça ? »).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Index, delete, func, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from mika.adapters.llm.gateway import LLMTrace
from mika.kernel.clock import DAY
from mika.ports.sql import Id, Key, LongText, ViewsBase, table_args

log = logging.getLogger("mika.llm")

TABLE = "llm_calls"
KEEP_DAYS = 30
_PRUNE_EVERY = 500
_COLUMNS = ("at", "role", "backend", "model", "lane", "priority", "latency_us", "wait_us", "input_tokens",
            "output_tokens", "cache_read", "cache_write", "cost_usd", "outcome", "call_id", "correlation")


class CallRow(ViewsBase):
    """Un appel de modèle : quand, pour quel rôle, chez qui, ce qu'il a coûté, comment il a fini."""

    __tablename__ = TABLE
    __table_args__ = table_args(Index(f"{TABLE}_at", "at"), Index(f"{TABLE}_correlation", "correlation"),
                                Index(f"{TABLE}_call_id", "call_id"))
    id: Mapped[int] = mapped_column(Id, primary_key=True)
    at: Mapped[int]
    role: Mapped[str] = mapped_column(LongText)
    backend: Mapped[str] = mapped_column(LongText)
    model: Mapped[str] = mapped_column(LongText)
    lane: Mapped[str] = mapped_column(LongText)
    priority: Mapped[int]
    latency_us: Mapped[int]
    wait_us: Mapped[int]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    cache_read: Mapped[int]
    cache_write: Mapped[int]
    cost_usd: Mapped[float]
    outcome: Mapped[str] = mapped_column(LongText)
    call_id: Mapped[str] = mapped_column(Key(255))
    correlation: Mapped[str] = mapped_column(Key(255), default="")


_FIELDS = tuple(getattr(CallRow, c) for c in _COLUMNS)


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


@dataclass(frozen=True, slots=True)
class Profile:
    """Ce qu'un fournisseur a fait depuis un instant : le tout, rôle par rôle, et ses temps de réponse (sur ses
    appels réussis : médiane et 95 % — un appel sur vingt a été plus lent), l'attente d'un créneau, son dernier
    échec."""

    total: Usage
    by_role: tuple[Usage, ...]
    median_s: float
    slow_s: float
    wait_avg_s: float
    last_failure_at: int = 0
    last_failure_role: str = ""


def _usage(key: str, rows: list[tuple[Any, ...]]) -> Usage:
    """Un agrégat de lignes (rôle, issue, entrée, sortie, cache lu, cache écrit, coût, durée)."""
    n = len(rows)
    return Usage(key, n, sum(1 for r in rows if r[1] != "ok"), sum(r[2] for r in rows), sum(r[3] for r in rows),
                 sum(r[4] for r in rows), sum(r[5] for r in rows), float(sum(r[6] or 0.0 for r in rows)),
                 sum(r[7] for r in rows) / n / 1e6 if n else 0.0)


def _quantile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))] / 1e6


class CallLog:
    def __init__(self, store: Any, *, keep_days: int = KEEP_DAYS) -> None:
        self.store = store
        self.keep_us = keep_days * DAY
        self._pending: set[asyncio.Task[Any]] = set()
        self._since_prune = 0
        self._ready = False

    async def open(self) -> None:
        await self.store.run_views(lambda sql: sql.create(CallRow))
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
        values = {c: getattr(tr, c) for c in _COLUMNS}
        self._since_prune += 1
        prune_before = tr.at - self.keep_us if self._since_prune >= _PRUNE_EVERY else None
        if prune_before is not None:
            self._since_prune = 0

        def write(sql: Any) -> None:
            sql.execute(insert(CallRow).values(**values))
            if prune_before is not None:
                sql.execute(delete(CallRow).where(CallRow.at < prune_before))

        task = loop.create_task(self.store.run_views(write))
        self._pending.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._pending.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.warning("registre des appels : écriture perdue (%r)", task.exception())

    async def flush(self) -> None:
        while self._pending:
            batch = list(self._pending)
            await asyncio.gather(*batch, return_exceptions=True)
            # attendre des tâches déjà finies ne rend pas la main à la boucle : leurs
            # rappels (qui les retirent) n'ont pas encore tourné — on les retire ici
            self._pending.difference_update(batch)

    async def prune(self, now: int) -> int:
        def run(sql: Any) -> int:
            return int(sql.execute(delete(CallRow).where(CallRow.at < now - self.keep_us)).rowcount or 0)

        return int(await self.store.run_views(run))

    def recent(self, limit: int = 100, *, role: str = "", offset: int = 0) -> list[LLMTrace]:
        if not self._ready:
            return []
        query = select(*_FIELDS)
        if role:
            query = query.where(CallRow.role == role)
        rows = self.store.query_views(query.order_by(CallRow.at.desc(), CallRow.id.desc())
                                      .limit(max(1, min(limit, 1000))).offset(max(0, offset)))
        return [_trace(r) for r in rows]

    def count(self, *, role: str = "", correlation: str = "") -> int:
        """Combien d'appels le registre garde (pour paginer)."""
        if not self._ready:
            return 0
        query = select(func.count()).select_from(CallRow)
        if role:
            query = query.where(CallRow.role == role)
        if correlation:
            query = query.where(CallRow.correlation == correlation)
        rows = self.store.query_views(query)
        return int(rows[0][0]) if rows else 0

    def for_correlation(self, correlation: str, *, limit: int = 200, offset: int = 0) -> list[LLMTrace]:
        """Les appels d'un épisode (ou d'un passage de processus), dans l'ordre où
        ils ont eu lieu."""
        if not self._ready or not correlation:
            return []
        rows = self.store.query_views(
            select(*_FIELDS).where(CallRow.correlation == correlation).order_by(CallRow.at, CallRow.id)
            .limit(max(1, min(limit, 1000))).offset(max(0, offset)))
        return [_trace(r) for r in rows]

    def by_call_id(self, call_id: str) -> LLMTrace | None:
        """L'appel qui porte cet identifiant — le dernier s'il y en a plusieurs :
        une boucle d'outils le réutilise d'un tour à l'autre, et le dernier tour
        est celui qui a écrit le texte (``VoiceProvenance.call_id``)."""
        if not self._ready or not call_id:
            return None
        rows = self.store.query_views(
            select(*_FIELDS).where(CallRow.call_id == call_id).order_by(CallRow.at.desc(), CallRow.id.desc()).limit(1))
        return _trace(rows[0]) if rows else None

    def usage(self, since: int, *, by: str = "role", day_of: Any = None) -> list[Usage]:
        """Agrégats depuis ``since``, par ``role``, ``backend``, ``model`` ou jour
        (``by="day"``, ``day_of(at) -> str`` donne le jour local)."""
        if not self._ready:
            return []
        rows = self.store.query_views(
            select(CallRow.at, CallRow.role, CallRow.backend, CallRow.outcome, CallRow.input_tokens,
                   CallRow.output_tokens, CallRow.cache_read, CallRow.cache_write, CallRow.cost_usd, CallRow.latency_us,
                   CallRow.model).where(CallRow.at >= since).order_by(CallRow.at))
        acc: dict[str, list[float]] = {}
        for at, role, backend, outcome, i, o, cr, cw, cost, lat, model in rows:
            key = day_of(at) if by == "day" and day_of is not None else backend if by == "backend" else \
                f"{backend} · {model}" if by == "model" else role
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


    def profile(self, backend: str, since: int) -> Profile | None:
        """Ce que ce fournisseur a fait depuis ``since`` (``None`` : aucun appel, ou le registre n'est pas ouvert)."""
        if not self._ready:
            return None
        rows = self.store.query_views(
            select(CallRow.role, CallRow.outcome, CallRow.input_tokens, CallRow.output_tokens, CallRow.cache_read,
                   CallRow.cache_write, CallRow.cost_usd, CallRow.latency_us, CallRow.wait_us, CallRow.at)
            .where(CallRow.backend == backend, CallRow.at >= since).order_by(CallRow.at))
        rows = [tuple(r) for r in rows]
        if not rows:
            return None
        roles: dict[str, list[tuple[Any, ...]]] = {}
        for r in rows:
            roles.setdefault(r[0], []).append(r)
        by_role = sorted((_usage(k, v) for k, v in roles.items()), key=lambda u: -u.calls)
        answered = [r[7] for r in rows if r[1] == "ok"] or [r[7] for r in rows]
        failed = [r for r in rows if r[1] != "ok"]
        return Profile(_usage(backend, rows), tuple(by_role), _quantile(answered, 0.5), _quantile(answered, 0.95),
                       sum(r[8] for r in rows) / len(rows) / 1e6, failed[-1][9] if failed else 0,
                       failed[-1][0] if failed else "")


def _trace(row: tuple[Any, ...]) -> LLMTrace:
    return LLMTrace(**dict(zip(_COLUMNS, row, strict=True)))
