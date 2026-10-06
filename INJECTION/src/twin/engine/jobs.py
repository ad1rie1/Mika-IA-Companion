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
les ouvriers attendent la réinitialisation de la fenêtre la plus chargée. Un appel **refusé**
pour quota ne compte pas comme un essai : tout le monde attend la réinitialisation, puis il
repart. On ne mange pas l'abonnement de sa propriétaire, ni celui de Mika qui vit à côté.

**Échecs** : une tâche ratée repart après un délai qui double à chaque essai (30 s, 1 min,
2 min… au plus 15 min). Au dernier essai, une passe qui sait **couper** une tâche en deux
(``split``, un lot de séances trop gros pour une réponse) la remplace par ses moitiés ;
sinon elle est « échouée », et ``retry_failed`` (``--reprendre-echecs``) la remet en file.
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
BACKOFF_S, BACKOFF_MAX_S = 30.0, 900.0


class Pass(Protocol):
    name: str
    version: int

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]: ...

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec: ...

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None: ...

    # facultatif : ``split(payload) -> list[(unit, payload)]`` coupe une tâche qui échoue sans cesse


Caller = Callable[[CallSpec], Awaitable[CallResult]]


@dataclass
class RunReport:
    done: int = 0
    failed: int = 0
    retried: int = 0
    split: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    paused_s: float = 0.0
    errors: list[str] = field(default_factory=list)


def ensure_schema(corpus: Corpus) -> None:
    corpus.db.executescript(JOBS_SCHEMA)
    columns = {r["name"] for r in corpus.db.execute("PRAGMA table_info(jobs)")}
    if "retry_after" not in columns:  # une file d'avant les délais entre essais
        corpus.db.execute("ALTER TABLE jobs ADD COLUMN retry_after REAL DEFAULT 0")
        corpus.db.commit()


def retry_failed(corpus: Corpus, p: Pass) -> int:
    """Remet en file les tâches échouées de la passe (version courante), essais remis à zéro."""
    ensure_schema(corpus)
    n = corpus.db.execute("UPDATE jobs SET status = 'todo', attempts = 0, retry_after = 0, error = '' "
                          "WHERE pass = ? AND version = ? AND status = 'failed'", (p.name, p.version)).rowcount
    corpus.db.commit()
    return n


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

    def refused(self, resets_at: int) -> None:
        """Le quota est atteint : tout le monde attend sa réinitialisation (une demi-heure si elle est inconnue)."""
        self.until = max(self.until, float(resets_at) + 60 if resets_at > self.clock() else self.clock() + 1800)

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

    def claim() -> tuple[int, str, dict[str, Any]] | float | None:
        """Une tâche ; sinon le délai avant la prochaine tâche en attente d'un nouvel essai ; sinon rien."""
        if budget[0] == 0:
            return None
        row = db.execute(
            "UPDATE jobs SET status = 'running', started_at = ?, attempts = attempts + 1 WHERE id = (SELECT id FROM "
            "jobs WHERE pass = ? AND version = ? AND status = 'todo' AND COALESCE(retry_after, 0) <= ? "
            "ORDER BY id LIMIT 1) RETURNING id, unit, payload",
            (_now(), p.name, p.version, clock())).fetchone()
        db.commit()
        if row is None:
            later = db.execute("SELECT MIN(retry_after) FROM jobs WHERE pass = ? AND version = ? AND status = 'todo'",
                               (p.name, p.version)).fetchone()[0]
            return max(1.0, later - clock()) if later is not None else None
        budget[0] -= 1
        return row["id"], row["unit"], json.loads(row["payload"])

    async def worker(n: int) -> None:
        while True:
            pause = quota.wait_s()
            if pause > 0:
                if progress:
                    progress(f"quota de l'abonnement atteint ou au-delà de {quota_ceiling:.0%} : "
                             f"pause de {pause / 60:.0f} min")
                report.paused_s += pause
                await sleep(pause)
                continue
            job = claim()
            if job is None:
                return
            if isinstance(job, float):
                await sleep(job)  # une tâche attend son prochain essai
                continue
            jid, unit, payload = job
            try:
                result = await caller(p.build(corpus, payload))
                quota.note(result.quota)
                error = p.accept(corpus, unit, payload, result)
            except ClaudeError as exc:
                quota.note(exc.quota)
                if exc.limited:  # refusé pour quota : pas un essai, on attend la réinitialisation
                    quota.refused(exc.resets_at)
                    db.execute("UPDATE jobs SET status = 'todo', attempts = attempts - 1 WHERE id = ?", (jid,))
                    db.commit()
                    budget[0] += 1 if budget[0] >= 0 else 0
                    continue
                result, error = None, f"ClaudeError: {exc}"
            except (TimeoutError, ValueError) as exc:  # ValueError : une réponse invalide (pydantic)
                result, error = None, f"{type(exc).__name__}: {exc}"
            _finish(db, p, jid, payload, result, error, max_attempts, report, clock())
            if progress:
                state = "fait" if error is None else f"à refaire ({error[:120]})"
                progress(f"[{n}] {p.name} {unit} : {state}")

    await asyncio.gather(*(worker(i + 1) for i in range(max(1, workers))))
    return report


def _finish(db: Any, p: Pass, jid: int, payload: dict[str, Any], result: CallResult | None, error: str | None,
            max_attempts: int, report: RunReport, now: float) -> None:
    usage = result.usage if result else {}
    tokens_in = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) \
        + int(usage.get("cache_creation_input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    report.input_tokens += tokens_in
    report.output_tokens += tokens_out
    retry_after = 0.0
    if error is None:
        status = "done"
        report.done += 1
    else:
        attempts = db.execute("SELECT attempts FROM jobs WHERE id = ?", (jid,)).fetchone()["attempts"]
        status = "failed" if attempts >= max_attempts else "todo"
        halves = _split(p, payload) if status == "failed" else []
        if halves:
            for unit, part in halves:
                db.execute("INSERT OR IGNORE INTO jobs (pass, unit, version, payload) VALUES (?, ?, ?, ?)",
                           (p.name, unit, p.version, json.dumps(part, ensure_ascii=False)))
            status = "split"
            report.split += 1
        elif status == "failed":
            report.failed += 1
            report.errors.append(error)
        else:
            report.retried += 1
            retry_after = now + min(BACKOFF_MAX_S, BACKOFF_S * 2 ** max(0, attempts - 1))
    db.execute("UPDATE jobs SET status = ?, error = ?, finished_at = ?, duration_s = ?, input_tokens = ?, "
               "output_tokens = ?, cost_usd = ?, model = ?, retry_after = ? WHERE id = ?",
               (status, error or "", _now(), result.duration_s if result else None, tokens_in, tokens_out,
                result.cost_usd if result else None, result.model if result else None, retry_after, jid))
    db.commit()


def _split(p: Pass, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    split = getattr(p, "split", None)
    if split is None:
        return []
    parts = list(split(payload))
    return parts if len(parts) >= 2 else []


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
