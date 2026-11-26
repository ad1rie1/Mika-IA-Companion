"""``mika rss list|add|remove`` (ADR 0310) : les flux qu'elle suit, hors ligne — les lister, en ajouter, en retirer.
Serveur arrêté : une seule écriture à la fois dans ``mind.db``."""

from __future__ import annotations

import argparse
import asyncio
import json

from mika.app.cli.common import with_settings
from mika.app.domains.senses.settings import SensesSettings


async def rss_command(settings: SensesSettings, args: argparse.Namespace) -> dict[str, object]:
    """Les flux qu'elle suit, et ce qu'on y ajoute ou en retire."""
    feeds = settings.feeds()
    if args.rss_cmd == "add":
        feeds = await settings.save_feeds([*feeds, *args.urls])
    elif args.rss_cmd == "remove":
        feeds = await settings.save_feeds([f for f in feeds if f not in args.urls])
    return {"feeds": feeds}


def _run_rss(args: argparse.Namespace) -> int:
    out = asyncio.run(with_settings(args.data,
                                     lambda settings, _store: rss_command(settings.of(SensesSettings), args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def add(sub) -> None:  # type: ignore[no-untyped-def]
    """Sa commande et ses sous-commandes, dans l'analyseur de ``mika``."""
    rs = sub.add_parser("rss", help="les flux qu'elle suit")
    rsub = rs.add_subparsers(dest="rss_cmd", required=True)
    rsub.add_parser("list")
    for name in ("add", "remove"):
        r = rsub.add_parser(name)
        r.add_argument("urls", nargs="+")
    rs.set_defaults(run=_run_rss)
