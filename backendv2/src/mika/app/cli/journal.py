"""Sa vie gardée : la rejouer, la reconstruire, oublier quelqu'un (``replay``, ``rebuild``, ``forget``) ;
l'archiver et la restaurer (``backup``, ``verify``, ``restore``)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import delete, select

from mika.adapters.store_sql import SqlStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.app import backup, datadir, schema
from mika.app.cli.common import CLI_BY, _close, _offline
from mika.app.composition import READING, faculties
from mika.kernel.codec import digest
from mika.kernel.inspect import Head
from mika.kernel.registry import Registry
from mika.ports.journal import JournalSnapshot
from mika.ports.sql import upsert
from mika.runtime import operations
from mika.runtime.inspection import Inspection
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME


def _mind(data: Path, *, snapshot_every: int = 500) -> Mind:
    datadir.hold(data)  # le journal ne s'écrit qu'à un seul à la fois (serveur arrêté)
    bases = schema.targets(data)
    schema.migrate_data(data, bases)
    store = SqlStore(bases["mind"], bases["views"], threaded=False)
    return Mind(Registry([RUNTIME, *faculties()], reading=READING), store, RealClock(), RandomIdGen(),
                snapshot_every=snapshot_every)


def _state(mind: Mind) -> str:
    return digest({o: mind.root.slices[o] for o in mind.registry.persisted_owners()})


async def replay_verify(data: Path) -> dict[str, object]:
    fast = _mind(data)
    r1 = await fast.boot(append_boot=False)
    d1 = _state(fast)
    await fast.close()

    full = _mind(data)
    await full.store.open()
    snaps = full.store.query_mind(select(JournalSnapshot.seq, JournalSnapshot.at, JournalSnapshot.data))
    await full.store.run_mind(lambda sql: sql.execute(delete(JournalSnapshot)))
    await full.store.close()
    r2 = await full.boot(append_boot=False)
    d2 = _state(full)

    async def restore(sql_rows=snaps) -> None:
        def put(sql) -> None:
            for seq, at, payload in sql_rows:
                upsert(sql, JournalSnapshot, {"seq": seq, "at": at, "data": payload}, keys=["seq"])

        await full.store.run_mind(put)

    await restore()
    await full.close()
    # un ``seq`` qui saute : des événements ont disparu (audit du 2026-10-26) — le rejeu depuis la genèse les voit tous
    return {"identiques": d1 == d2, "instantané": r1.snapshot_seq, "rejoués_depuis_genèse": r2.replayed,
            "tête": r2.head, "contigu": not r2.gaps,
            "trous": [f"{a}–{b - 1}" if b - 1 > a else str(a) for a, b in r2.gaps]}


async def rebuild(data: Path, owners: list[str]) -> dict[str, object]:
    mind = _mind(data)
    await mind.boot(append_boot=False)
    report = await mind.rebuild(owners)
    # sans instantané, le prochain démarrage relirait l'ancien : la reconstruction ne durerait pas
    root = mind.root
    data_json = mind.snapshot_data(root)
    await mind.store.run_mind(lambda sql: upsert(sql, JournalSnapshot, {"seq": root.seq, "at": root.at,
                                                                         "data": data_json}, keys=["seq"]))
    await mind.close()
    return report


async def forget(data: Path, subject: str) -> dict[str, object]:
    """L'oubli, comme la console le fait (``operations.forget_subject``) : la clé et tout ce qui
    la désigne — pour une personne, ses autres adresses et les noms qui ne désignent qu'elle —,
    contenus et projections, traces d'épisode, et tout port qui garde une trace dérivée (l'index
    des vecteurs). Audité. Rien ne démarre : aucun processus, aucun modèle."""
    kernel = await _offline(data, vectors=True)
    try:
        await kernel.deps.ports["vectors"].open()
        await kernel.traces.open()
        kinds = sorted(k for k, spec in kernel.registry.subjects.items() if spec.forgettable)
        ins = Inspection(kernel)
        kind = next((k for k in kinds if isinstance(ins.head(k, subject), Head)), "")
        gone = await operations.forget_subject(kernel, kind, subject, by=CLI_BY, action=f"cli.oublier.{kind or 'cle'}")
    finally:
        await _close(kernel, data)
    return {"sujet": subject, "clés": list(gone.keys), "contenus_effacés": gone.counts.get("contents", 0),
            "traces_effacées": gone.counts.get("traces", 0), "vecteurs_effacés": gone.counts.get("vectors", 0),
            "fichiers_effacés": gone.counts.get("shares", 0)}


def _run_replay(args: argparse.Namespace) -> int:
    out = asyncio.run(replay_verify(args.data))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["identiques"] and out["contigu"] else 1


def _run_rebuild(args: argparse.Namespace) -> int:
    print(json.dumps(asyncio.run(rebuild(args.data, args.owners)), ensure_ascii=False))
    return 0


def _run_forget(args: argparse.Namespace) -> int:
    print(json.dumps(asyncio.run(forget(args.data, args.subject)), ensure_ascii=False))
    return 0


def _run_archive(args: argparse.Namespace) -> int:
    try:
        if args.cmd == "backup":
            done = backup.backup(args.data, args.dest, keep=args.keep)
        elif args.cmd == "verify":
            ours = (args.data / "mind.db").exists() or (schema.server_url() and args.data.is_dir())
            done = backup.verify(args.archive, record=args.data if ours else None)
        else:
            done = backup.restore(args.archive, args.data, force=args.force)
    except backup.BackupError as exc:
        print(json.dumps({"ok": False, "erreur": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "archive": str(done.archive), "tête": done.head, "empreinte": done.state,
                      "fichiers": done.files, "octets": done.size, "remarques": list(done.warnings)},
                     ensure_ascii=False))
    return 0


def add_journal(sub) -> None:  # type: ignore[no-untyped-def]
    rp = sub.add_parser("replay", help="rejouer sa vie depuis la genèse (--verify : comparer à l'état sauvegardé)")
    rp.add_argument("--verify", action="store_true", help="comparer le rejeu complet à instantané + queue")
    rb = sub.add_parser("rebuild", help="reconstruire des tranches depuis le journal (diagnostic, serveur arrêté)")
    rb.add_argument("owners", nargs="+", help="les facultés à reconstruire (memory, social…)")
    fg = sub.add_parser("forget", help="oublier quelqu'un (serveur arrêté), comme la console")
    fg.add_argument("subject", help="sa clé ou l'une de ses adresses : elle est oubliée avec toutes ses adresses "
                                    "et les noms qui ne désignent qu'elle")
    rp.set_defaults(run=_run_replay)
    rb.set_defaults(run=_run_rebuild)
    fg.set_defaults(run=_run_forget)


def add_archives(sub) -> None:  # type: ignore[no-untyped-def]
    bk = sub.add_parser("backup", help="archiver ce qui ne se reconstruit pas (serveur en marche : sans risque)")
    bk.add_argument("dest", type=Path, help="dossier des archives")
    bk.add_argument("--keep", type=int, default=0, help="n'en garder que les N plus récentes (0 : toutes)")
    vf = sub.add_parser("verify", help="vérifier une archive (sommes, rejeu, empreinte) sans rien restaurer")
    vf.add_argument("archive", type=Path)
    rt_ = sub.add_parser("restore", help="restaurer une archive dans --data (serveur arrêté)")
    rt_.add_argument("archive", type=Path)
    rt_.add_argument("--force", action="store_true", help="remplacer un dossier non vide (mis de côté, pas effacé)")
    for parser in (bk, vf, rt_):
        parser.set_defaults(run=_run_archive)
