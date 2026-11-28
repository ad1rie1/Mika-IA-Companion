"""``mika forge promote|demote`` (ADR 0104, 0310) : ce qu'un opérateur décide de ses apps — offrir (ou retirer) les
outils d'une app en conversation. C'est l'action de la console, par le même chemin (``app/cli/accounts.py::operate``) :
mêmes refus, même garde, même audit. Serveur arrêté : une seule écriture à la fois dans ``mind.db``."""

from __future__ import annotations

import argparse
import asyncio
import json

from mika.app.cli.accounts import operate


def _run_forge(args: argparse.Namespace) -> int:
    action = "forge.promouvoir" if args.forge_cmd == "promote" else "forge.retrograder"
    out = asyncio.run(operate(args.data, action, args.app, {}))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


def add(sub) -> None:  # type: ignore[no-untyped-def]
    fo = sub.add_parser("forge", help="ce qu'un opérateur décide de ses apps (serveur arrêté)")
    fsub = fo.add_subparsers(dest="forge_cmd", required=True)
    for name in ("promote", "demote"):
        f = fsub.add_parser(name, help="offrir (ou retirer) ses outils en conversation")
        f.add_argument("app")
    fo.set_defaults(run=_run_forge)
