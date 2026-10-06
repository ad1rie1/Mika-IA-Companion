"""La file de travail : des passes, découpées en tâches, exécutées par quelques ouvriers.

Une **passe** (annoter, dater par recoupement, synthétiser…) dit quelles unités de
travail existent (``units``), comment bâtir l'appel d'une unité (``build``) et comment
accepter sa réponse (``accept`` : valider, ranger ; une erreur la fait réessayer).

La file vit dans ``corpus.db`` (table ``jobs``) : on peut l'interrompre n'importe quand
(Ctrl+C, plantage, coupure). Au redémarrage, ce qui tournait repart, et ce qui est fait
reste fait. Une tâche appartient à une **version** de sa passe : changer le prompt ou le
schéma (``version`` + 1) recrée les tâches, et les réponses de l'ancienne version restent
consultables.

**Quota** : chaque appel rend l'usage de l'abonnement. Au-delà de ``quota_ceiling``, tous
les ouvriers attendent la réinitialisation de la fenêtre la plus chargée. On ne mange pas
l'abonnement de sa propriétaire, ni celui de Mika qui vit à côté.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from twin.corpus import Corpus
from twin.engine.claude import CallResult, CallSpec, ClaudeError, QuotaReading, call

JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, pass TEXT NOT NULL, unit TEXT NOT NULL, version INTEGER NOT NULL,
    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo', attempts INTEGER DEFAULT 0, error TEXT DEFAULT '',
    started_at TEXT, finished_at TEXT, duration_s REAL, input_tokens INTEGER, output_tokens INTEGER,
    cost_usd REAL, model TEXT, UNIQUE (pass, unit, version)
);
CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs (pass, version, status, id);
"""


class Pass(Protocol):
    name: str
    version: int

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]: ...

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec: ...

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None: ...


Caller = Callable[[CallSpec], Awaitable[CallResult]]


@dataclass
class RunReport:
    done: int = 0
    failed: int = 0
    retried: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    paused_s: float = 0.0
    errors: list[str] = field(default_factory=list)


def ensure_schema(corpus: Corpus) -> None:
    corpus.db.executescript(JOBS_SCHEMA)


def enqueue(corpus: Corpus, p: Pass) -> int:
    ensure_schema(corpus)
    n = 0
    for unit, payload in p.units(corpus):
        cur = corpus.db.execute("INSERT OR IGNORE INTO jobs (pass, unit, version, payload) VALUES (?, ?, ?, ?)",
                                (p.name, unit, p.version, json.dumps(payload, ensure_ascii=False)))
        n += cur.rowcount
    corpus.db.commit()
    return n


def counts(corpus: Corpus, p: Pass) -> dict[str, int]:
    ensure_schema(corpus)
    return {r["status"]: r["n"] for r in corpus.db.execute(
        "SELECT status, COUNT(*) n FROM jobs WHERE pass = ? AND version = ? GROUP BY status", (p.name, p.version))}


class _Quota:
    def __init__(self, ceiling: float, clock: Callable[[], float]) -> None:
        self.ceiling = ceiling
        self.clock = clock
        self.until = 0.0

    def note(self, readings: list[QuotaReading]) -> None:
        if self.ceiling <= 0:
            return
        over = [q for q in readings if q.utilization >= self.ceiling]
        if over:
            resets = max((q.resets_at for q in over), default=0)
            self.until = max(self.until, float(resets) + 60 if resets else self.clock() + 1800)

    def wait_s(self) -> float:
        return max(0.0, self.until - self.clock())


async def run(corpus: Corpus, p: Pass, *, workers: int = 3, limit: int | None = None, max_attempts: int = 3,
              quota_ceiling: float = 0.8, caller: Caller = call, progress: Callable[[str], None] | None = None,
              clock: Callable[[], float] = time.time, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
              ) -> RunReport:
    """Exécute les tâches à faire de la passe (``limit`` : au plus tant de tâches cette fois)."""
    ensure_schema(corpus)
    db = corpus.db
    db.execute("UPDATE jobs SET status = 'todo' WHERE pass = ? AND status = 'running'", (p.name,))
    db.commit()
    report = RunReport()
    quota = _Quota(quota_ceiling, clock)
    budget = [limit if limit is not None else -1]

    def claim() -> tuple[int, str, dict[str, Any]] | None:
        if budget[0] == 0:
            return None
        row = db.execute(
            "UPDATE jobs SET status = 'running', started_at = ?, attempts = attempts + 1 WHERE id = (SELECT id FROM "
            "jobs WHERE pass = ? AND version = ? AND status = 'todo' ORDER BY id LIMIT 1) RETURNING id, unit, payload",
            (_now(), p.name, p.version)).fetchone()
        db.commit()
        if row is None:
            return None
        budget[0] -= 1
        return row["id"], row["unit"], json.loads(row["payload"])

    async def worker(n: int) -> None:
        while True:
            pause = quota.wait_s()
            if pause > 0:
                if progress:
                    progress(f"quota de l'abonnement au-delà de {quota_ceiling:.0%} : pause de {pause / 60:.0f} min")
                report.paused_s += pause
                await sleep(pause)
                continue
            job = claim()
            if job is None:
                return
            jid, unit, payload = job
            try:
                result = await caller(p.build(corpus, payload))
                quota.note(result.quota)
                error = p.accept(corpus, unit, payload, result)
            except (ClaudeError, TimeoutError, ValueError) as exc:  # ValueError : une réponse invalide (pydantic)
                result, error = None, f"{type(exc).__name__}: {exc}"
            _finish(db, jid, result, error, max_attempts, report)
            if progress:
                state = "fait" if error is None else f"à refaire ({error[:120]})"
                progress(f"[{n}] {p.name} {unit} : {state}")

    await asyncio.gather(*(worker(i + 1) for i in range(max(1, workers))))
    return report


def _finish(db: Any, jid: int, result: CallResult | None, error: str | None, max_attempts: int,
            report: RunReport) -> None:
    usage = result.usage if result else {}
    tokens_in = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) \
        + int(usage.get("cache_creation_input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    report.input_tokens += tokens_in
    report.output_tokens += tokens_out
    if error is None:
        status = "done"
        report.done += 1
    else:
        attempts = db.execute("SELECT attempts FROM jobs WHERE id = ?", (jid,)).fetchone()["attempts"]
        status = "failed" if attempts >= max_attempts else "todo"
        if status == "failed":
            report.failed += 1
            report.errors.append(error)
        else:
            report.retried += 1
    db.execute("UPDATE jobs SET status = ?, error = ?, finished_at = ?, duration_s = ?, input_tokens = ?, "
               "output_tokens = ?, cost_usd = ?, model = ? WHERE id = ?",
               (status, error or "", _now(), result.duration_s if result else None, tokens_in, tokens_out,
                result.cost_usd if result else None, result.model if result else None, jid))
    db.commit()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
