"""Faculté jouet à effet externe, et le processus enfant qu'on tue."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from mika.adapters.store_sqlite import SqliteStore
from mika.kernel.clock import ManualClock
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.kernel.ids import SeededIdGen
from mika.kernel.registry import Registry
from mika.runtime.effects import EffectExecutor
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME


@dataclass(frozen=True, slots=True)
class SenderState:
    queued: int = 0


class Queued(Payload):
    to: str
    body: str


SENDER = Faculty("sender", state=SenderState, init=lambda p: SenderState())
QUEUED = SENDER.event("queued", Queued)


@SENDER.reducer(QUEUED)
def _queued(s: SenderState, e, cx) -> SenderState:
    return SenderState(s.queued + 1)


def sink_path(root: Path) -> Path:
    return root / "sink.db"


@SENDER.effect(QUEUED)
async def deliver(ev, ports) -> None:
    root = Path(ports["root"])
    conn = sqlite3.connect(sink_path(root))
    conn.execute("CREATE TABLE IF NOT EXISTS sent(event_id TEXT PRIMARY KEY, body TEXT)")
    conn.execute("INSERT OR IGNORE INTO sent(event_id, body) VALUES(?, ?)", (ev.id, ev.data.body))
    conn.commit()
    conn.close()
    if os.environ.get("CRASH_IN_EFFECT") == "1":
        os._exit(9)


def make(root: Path) -> tuple[Mind, EffectExecutor]:
    store = SqliteStore(root / "mind.db", root / "views.db", threaded=False)
    mind = Mind(Registry([RUNTIME, SENDER]), store, ManualClock(1_790_000_000_000_000), SeededIdGen(root.name))
    return mind, EffectExecutor(mind, {"root": str(root)})


async def child(root: Path, mode: str) -> None:
    mind, executor = make(root)
    await mind.boot()
    if mode == "before_commit":
        mind.store.seal()  # type: ignore[attr-defined]
        try:
            await mind.append([QUEUED.draft(to="alice", body="bonjour")], emitter="sender", correlation="c")
        except Exception:
            pass
        os._exit(9)
    await mind.append([QUEUED.draft(to="alice", body="bonjour")], emitter="sender", correlation="c")
    if mode == "after_commit":
        os._exit(9)  # tué entre le commit et l'effet
    if mode == "during_effect":
        await executor.drain()  # l'effet écrit puis le processus meurt avant d'être marqué
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(child(Path(sys.argv[1]), sys.argv[2]))
