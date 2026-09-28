"""Ligne de commande : ``python -m mika <commande>``.

- ``replay --verify`` : reconstruit tout depuis la genèse et compare à l'état
  obtenu par instantané + queue ;
- ``rebuild <propriétaire>…`` : reconstruction par clôture ;
- ``forget <sujet>`` : oubli (contenus et projections) ;
- ``sim selftest`` : auto-test du simulateur ;
- ``serve`` : le serveur ;
- ``llm show|backend|route|remove|context`` : les modèles (clés chiffrées) ;
- ``account <nom> <mot de passe> [--operator]`` : un compte.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.web.accounts import Accounts, password_problems
from mika.app.composition import faculties, for_simulation
from mika.app.server import serve
from mika.app.settings import SecretBox, Settings
from mika.kernel.codec import digest
from mika.kernel.registry import Registry
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME
from mika.sim.report import write as write_report
from mika.sim.scenarios import run_lane
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


async def _with_settings(data: Path, fn):  # type: ignore[no-untyped-def]
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(data))
        await settings.open()
        return await fn(settings, store)
    finally:
        await store.close()


async def llm_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.llm()
        backends = dict(cfg.backends)
        routes = dict(cfg.routes)
        context = cfg.context_tokens
        if args.llm_cmd == "backend":
            previous = backends.get(args.name)
            key = args.api_key if args.api_key is not None else (previous.api_key if previous else "")
            backends[args.name] = BackendSpec(
                kind=args.kind, model=args.model, api_key=key, base_url=args.base_url or "", host=args.host or "",
                slots=args.slots, temperature=args.temperature, think=args.think,
            )
        elif args.llm_cmd == "route":
            for role in args.roles:
                routes[role] = args.name
        elif args.llm_cmd == "remove":
            backends.pop(args.name, None)
            routes = {r: b for r, b in routes.items() if b != args.name}
        elif args.llm_cmd == "context":
            context = args.tokens
        cfg = LLMConfig(backends=backends, routes=routes, context_tokens=context)
        if args.llm_cmd != "show":
            await settings.save_llm(cfg)
        return {"backends": {n: b.redacted() for n, b in cfg.backends.items()}, "routes": cfg.routes,
                "context_tokens": cfg.context_tokens, "problems": cfg.problems()}

    return await _with_settings(data, run)


async def account_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        accounts = Accounts(store)
        await accounts.open()
        problems = password_problems(args.password, args.username)
        if problems:
            return {"ok": False, "error": " ".join(problems)}
        acc = await accounts.create(args.username, args.password, operator=args.operator,
                                    full_name=args.full_name or "")
        return {"ok": True, "person_id": acc.handle, "operator": acc.operator}

    return await _with_settings(data, run)


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
    sm.add_argument("action", choices=["selftest", "run"])
    sm.add_argument("--lane", default="quick", choices=["quick"])
    sm.add_argument("--report", type=Path, default=Path("sim-reports"))
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8001)
    sv.add_argument("--host", default="127.0.0.1")
    lm = sub.add_parser("llm", help="fournisseurs de modèles et rôles")
    lsub = lm.add_subparsers(dest="llm_cmd", required=True)
    lsub.add_parser("show")
    lb = lsub.add_parser("backend", help="déclarer ou modifier un fournisseur")
    lb.add_argument("name")
    lb.add_argument("--kind", required=True, choices=["claude", "openai", "ollama", "ollama_cloud"])
    lb.add_argument("--model", required=True)
    lb.add_argument("--api-key", default=None, help="laissé vide : la clé actuelle est gardée")
    lb.add_argument("--base-url", default="")
    lb.add_argument("--host", default="")
    lb.add_argument("--slots", type=int, default=0)
    lb.add_argument("--temperature", type=float, default=None)
    lb.add_argument("--think", action="store_true")
    lr = lsub.add_parser("route", help="associer des rôles à un fournisseur")
    lr.add_argument("name")
    lr.add_argument("roles", nargs="+")
    lx = lsub.add_parser("remove")
    lx.add_argument("name")
    lc = lsub.add_parser("context", help="taille du contexte (jetons)")
    lc.add_argument("tokens", type=int)
    ac = sub.add_parser("account", help="créer un compte")
    ac.add_argument("username")
    ac.add_argument("password")
    ac.add_argument("--operator", action="store_true")
    ac.add_argument("--full-name", default="")
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
    if args.cmd == "sim" and args.action == "run":
        with tempfile.TemporaryDirectory() as tmp:
            results = run_lane(for_simulation(), Path(tmp))
        path = write_report(results, args.report)
        for r in results:
            print(f"{'✔' if r.ok else '✘'} {r.name} (graine {r.seed}, {r.seconds:.1f} s)")
            for c in r.checks:
                if not c.ok:
                    print(f"    ✘ {c.name} : {c.detail}")
        print(f"rapport : {path}")
        return 0 if all(r.ok for r in results) else 1
    if args.cmd == "sim":
        out = sim_selftest()
        print(json.dumps(out, ensure_ascii=False))
        return 0 if all(out.values()) else 1
    if args.cmd == "serve":
        serve(host=args.host, port=args.port, data=args.data)
        return 0
    if args.cmd == "llm":
        out = asyncio.run(llm_command(args.data, args))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if not out["problems"] else 1
    if args.cmd == "account":
        out = asyncio.run(account_command(args.data, args))
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["ok"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
