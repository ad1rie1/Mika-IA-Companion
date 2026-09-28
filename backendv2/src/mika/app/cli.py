"""Ligne de commande : ``python -m mika <commande>``.

- ``replay --verify`` : reconstruit tout depuis la genèse et compare à l'état
  obtenu par instantané + queue ;
- ``rebuild <propriétaire>…`` : reconstruction par clôture ;
- ``forget <sujet>`` : oubli (contenus et projections) ;
- ``sim selftest`` : auto-test du simulateur ;
- ``serve`` : le serveur (à partir de M1).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.app.composition import faculties
from mika.app.server import serve
from mika.kernel.codec import digest
from mika.kernel.registry import Registry
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME
from mika.sim.selftest import run as sim_selftest


def _mind(data: Path, *, snapshot_every: int = 500) -> Mind:
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    return Mind(Registry([RUNTIME, *faculties()]), store, RealClock(), RandomIdGen(), snapshot_every=snapshot_every)


def _state(mind: Mind) -> str:
    return digest({o: mind.root.slices[o] for o in mind.registry.persisted_owners()})


async def replay_verify(data: Path) -> dict[str, object]:
    fast = _mind(data)
    r1 = await fast.boot(append_boot=False)
    d1 = _state(fast)
    await fast.close()

    full = _mind(data)
    await full.store.open()
    snaps = full.store.query_mind("SELECT seq, at, data FROM snapshots")
    await full.store.run_mind(lambda sql: sql.execute("DELETE FROM snapshots"))
    await full.store.close()
    r2 = await full.boot(append_boot=False)
    d2 = _state(full)

    async def restore(sql_rows=snaps) -> None:
        def put(sql) -> None:
            for seq, at, payload in sql_rows:
                sql.execute("INSERT OR REPLACE INTO snapshots(seq, at, data) VALUES(?,?,?)", (seq, at, payload))

        await full.store.run_mind(put)

    await restore()
    await full.close()
    return {"identiques": d1 == d2, "instantané": r1.snapshot_seq, "rejoués_depuis_genèse": r2.replayed,
            "tête": r2.head}


async def rebuild(data: Path, owners: list[str]) -> dict[str, object]:
    mind = _mind(data)
    await mind.boot(append_boot=False)
    report = await mind.rebuild(owners)
    await mind.close()
    return report


async def forget(data: Path, subject: str) -> dict[str, object]:
    mind = _mind(data)
    await mind.boot(append_boot=False)
    n = await mind.forget(subject)
    await mind.close()
    return {"sujet": subject, "contenus_effacés": n}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mika")
    p.add_argument("--data", type=Path, default=Path("data/v2"), help="dossier des bases (mind.db, views.db)")
    sub = p.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay")
    rp.add_argument("--verify", action="store_true")
    rb = sub.add_parser("rebuild")
    rb.add_argument("owners", nargs="+")
    fg = sub.add_parser("forget")
    fg.add_argument("subject")
    sm = sub.add_parser("sim")
    sm.add_argument("action", choices=["selftest"])
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8001)
    sv.add_argument("--host", default="127.0.0.1")
    args = p.parse_args(argv)

    if args.cmd == "replay":
        out = asyncio.run(replay_verify(args.data))
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["identiques"] else 1
    if args.cmd == "rebuild":
        print(json.dumps(asyncio.run(rebuild(args.data, args.owners)), ensure_ascii=False))
        return 0
    if args.cmd == "forget":
        print(json.dumps(asyncio.run(forget(args.data, args.subject)), ensure_ascii=False))
        return 0
    if args.cmd == "sim":
        out = sim_selftest()
        print(json.dumps(out, ensure_ascii=False))
        return 0 if all(out.values()) else 1
    if args.cmd == "serve":
        serve(host=args.host, port=args.port, data=args.data)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
