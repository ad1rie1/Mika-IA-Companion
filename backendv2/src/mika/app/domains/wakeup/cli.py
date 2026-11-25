"""``mika wakeup`` (ADR 0068, 0310) : les réveils par API hors ligne — les lister, donner une clé à l'un d'eux, la
retirer. Serveur arrêté : une seule écriture à la fois dans ``mind.db``."""

from __future__ import annotations

import argparse
import asyncio
import json

from mika.adapters.system import RealClock
from mika.app.cli.common import _with_settings
from mika.app.domains.wakeup.desk import WakeupDesk
from mika.app.domains.wakeup.settings import WakeupSettings
from mika.app.settings import Settings


async def wakeup_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Les réveils par API (ADR 0068) hors ligne : les lister, leur donner une clé (montrée une fois), la retirer."""
    desk = WakeupDesk(settings.of(WakeupSettings), RealClock().now)
    if args.wakeup_cmd == "list":
        return {"ok": True, "endpoints": [
            {"name": ep.name, "label": ep.label, "enabled": ep.enabled, "project": ep.project or None,
             "plain": ep.plain, "tools": list(ep.bundles), "rouse": ep.rouse, "notify": ep.notify,
             "signed": ep.signed, "fields": list(ep.fields),
             "key": f"{ep.key.hint}…" if ep.key is not None else None} for ep in desk.endpoints()]}
    if args.wakeup_cmd == "key":
        try:
            key = await desk.new_key(args.name, "ligne de commande")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        usage = f"POST /api/wake/{args.name} avec l'en-tête Authorization: Bearer <clé>"
        ep = desk.endpoint(args.name)
        if ep is not None and ep.signed:
            usage += " — ou le corps signé par la clé (X-Hub-Signature-256 : le « secret » d'un webhook GitHub)"
        return {"ok": True, "name": args.name, "key": key, "usage": usage}
    if not await desk.revoke_key(args.name):
        return {"ok": False, "error": f"« {args.name} » n'a pas de clé."}
    return {"ok": True, "name": args.name, "revoked": True}


def _run_wakeup(args: argparse.Namespace) -> int:
    out = asyncio.run(_with_settings(args.data, lambda settings, _store: wakeup_command(settings, args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1


def add(sub) -> None:  # type: ignore[no-untyped-def]
    """Sa commande et ses sous-commandes, dans l'analyseur de ``mika``."""
    wk = sub.add_parser("wakeup", help="les réveils par API (POST /api/wake/<nom>, ADR 0068 ; serveur arrêté)")
    wksub = wk.add_subparsers(dest="wakeup_cmd", required=True)
    wksub.add_parser("list", help="les réveils déclarés et l'état de leur clé, sans secret")
    wkk = wksub.add_parser("key", help="une clé neuve pour un réveil (l'ancienne ne vaut plus), montrée une fois")
    wkk.add_argument("name")
    wkr = wksub.add_parser("revoke", help="retirer la clé d'un réveil (plus aucun appel ne passe)")
    wkr.add_argument("name")
    wk.set_defaults(run=_run_wakeup)
