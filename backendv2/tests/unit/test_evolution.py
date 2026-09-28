"""Preuve M0 — évolution : un upcaster lit une charge utile ancienne ; une
montée de version de tranche se reconstruit par clôture dans une racine
fantôme, sans arrêter les ajouts ; les tranches inchangées sont identiques."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

from mika.kernel.codec import digest
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.kernel.registry import Registry
from mika.ports.store import StoredEvent
from tests.conftest import make_mind
from tests.fixtures.toys import BUMPED, COUNTER, ECHO, VALUE, CounterState


class GreetV2(Payload):
    who: str
    warmth: float = 0.5


@dataclass(frozen=True, slots=True)
class GreetState:
    names: tuple[str, ...] = ()


def rename(raw: dict) -> dict:
    raw = dict(raw)
    raw["who"] = raw.pop("name")
    return raw


GREETER = Faculty("greeter", state=GreetState, init=lambda p: GreetState())
GREETED = GREETER.event("greeted", GreetV2, version=2, upcasters={1: rename})


@GREETER.reducer(GREETED)
def _greeted(s: GreetState, e, cx) -> GreetState:
    return replace(s, names=s.names + (e.data.who,))


async def test_upcaster_reads_old_payload(tmp_path):
    mind = make_mind(tmp_path, [GREETER])
    await mind.store.open()
    mind.store.bulk_load([StoredEvent(1, "01OLD", "greeter.greeted", 1, 1, None, "old", 0, "genesis",
                                      '{"name": "Alice"}')])
    await mind.store.close()
    await mind.boot(append_boot=False)
    assert mind.root.slices["greeter"].names == ("Alice",)
    await mind.close()


def counter_v2() -> Faculty:
    """La même faculté, nouveau code : chaque incrément compte double."""
    fac = Faculty("counter", state=CounterState, init=lambda p: CounterState(), state_version=2,
                  params=COUNTER.params)
    fac.declare(BUMPED)

    @fac.reducer(BUMPED)
    def _bump_v2(s: CounterState, e, cx) -> CounterState:
        return replace(s, n=s.n + 2 * e.data.by, notes=s.notes + (e.data.note is not None))

    fac.fact(VALUE)(lambda s, cx: s.n)
    return fac


async def test_online_rebuild_by_closure_without_stopping_appends(tmp_path):
    mind = make_mind(tmp_path, [COUNTER, ECHO])
    await mind.boot()
    for i in range(3000):
        await mind.append([BUMPED.draft(by=1)], emitter="counter", correlation="t")
    echo_before = mind.root.slices["echo"]
    new_registry = Registry([counter_v2(), ECHO])

    appended = 0

    async def keep_appending():
        nonlocal appended
        for _ in range(50):
            await mind.append([BUMPED.draft(by=1)], emitter="counter", correlation="concurrent")
            appended += 1
            await asyncio.sleep(0)

    rebuild = asyncio.create_task(mind.rebuild(["counter"], registry=new_registry))
    writer = asyncio.create_task(keep_appending())
    report, _ = await asyncio.gather(rebuild, writer)

    assert appended == 50
    assert report["mismatches"] == []
    assert "kernel" in report["closure"] and "counter" in report["closure"]
    # la nouvelle logique a revécu toute la vie de la tranche
    assert mind.root.slices["counter"].n == 2 * 3050
    # echo, qui lit counter, garde son passé (calculé avec l'ancienne logique)
    assert digest(mind.root.slices["echo"].seen[:3000]) == digest(echo_before.seen[:3000])
    await mind.close()


async def test_boot_rebuilds_stale_slice_from_snapshot(tmp_path):
    mind = make_mind(tmp_path, [COUNTER, ECHO], snapshot_every=100)
    await mind.boot()
    for _ in range(250):
        await mind.append([BUMPED.draft(by=1)], emitter="counter", correlation="t")
    await mind.close()

    from mika.adapters.store_sqlite import SqliteStore
    from mika.kernel.clock import ManualClock
    from mika.kernel.ids import SeededIdGen
    from mika.runtime.mind import Mind
    from tests.conftest import START

    store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    mind2 = Mind(Registry([counter_v2(), ECHO]), store, ManualClock(START), SeededIdGen(0), snapshot_every=100)
    report = await mind2.boot(append_boot=False)
    assert report.stale == ("counter",)
    assert mind2.root.slices["counter"].n == 500
    await mind2.close()
