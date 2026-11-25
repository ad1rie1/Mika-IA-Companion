"""``mika mcp`` (ADR 0064, 0310) : les serveurs MCP branchés et leurs réglages, sans secret (``serveurs``) ; joindre
un serveur et lister ce qu'il propose, rien n'étant approuvé (``essai``) ; et le jeton du point MCP de la console
(``token`` : ``/mcp/console``, lecture seule), que tiennent les réglages du serveur. Serveur arrêté : une seule
écriture à la fois dans ``mind.db``."""

from __future__ import annotations

import argparse
import asyncio
import json

from mika.adapters.mcp.hub import McpHub
from mika.app.cli.common import _with_settings
from mika.app.domains.tools.settings import ToolsSettings
from mika.app.settings import Settings


async def mcp_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """``mika mcp serveurs`` / ``mika mcp essai <serveur>`` : ce qui est branché, et ce qu'un serveur propose
    maintenant (avec, pour chaque outil, ce que l'opérateur en a décidé). Aucun secret n'est rendu."""
    own = settings.of(ToolsSettings)
    hub = McpHub(own.mcp, own.mcp_tools, own.save_mcp_tools, local_root=args.data / "mcp")
    try:
        if args.mcp_cmd == "serveurs":
            return {"ok": True, "serveurs": [
                {"nom": n, "ou": s.transport, "actif": s.enabled, "a_quoi": s.purpose,
                 "adresse": s.url if not s.local else s.command,
                 "acces": [{"qui": a.who, "quand": list(a.when) or "toujours", "lecture": a.read, "action": a.act, "garde": a.keep,
                            "outils": list(a.tools) or "tous"} for a in s.access],
                 "par_defaut": {"lecture": s.default_read, "action": s.default_act, "garde": s.default_keep},
                 "manque": s.problems()}
                for n, s in sorted(own.mcp().servers.items())]}
        ok, message = await hub.test(args.serveur)
        status = hub.status(args.serveur)
        tools = []
        for t in status.live if status is not None else ():
            review = status.reviews.get(t.remote) if status is not None else None
            state = ("à regarder" if review is None else "suspendu (changé)" if review.enabled
                     and review.fingerprint != t.fingerprint else "approuvé" if review.enabled else "désactivé")
            tools.append({"outil": t.remote, "description": t.description, "lecture_seule": t.read_only_hint,
                          "etat": state})
        return {"ok": ok, "message": message, "outils": tools}
    finally:
        await hub.aclose()


def _run_mcp(args: argparse.Namespace) -> int:
    if args.mcp_cmd in ("serveurs", "essai"):
        out = asyncio.run(_with_settings(args.data, lambda settings, _store: mcp_command(settings, args)))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok", True) else 1

    async def mcp_token(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        token = await settings.new_console_mcp_token()
        return {"token": token, "usage": "claude mcp add --transport http mika http://127.0.0.1:8001/mcp/console/ "
                                          f"--header \"Authorization: Bearer {token}\""}

    print(json.dumps(asyncio.run(_with_settings(args.data, mcp_token)), ensure_ascii=False, indent=2))
    return 0


def add(sub) -> None:  # type: ignore[no-untyped-def]
    """Sa commande et ses sous-commandes, dans l'analyseur de ``mika``."""
    mc = sub.add_parser("mcp", help="la lire depuis ton Claude Code (point /mcp/console, lecture seule)")
    mcsub = mc.add_subparsers(dest="mcp_cmd", required=True)
    mcsub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    mcsub.add_parser("serveurs", help="les serveurs MCP branchés (ADR 0064) et leurs réglages, sans secret")
    mce = mcsub.add_parser("essai", help="joindre un serveur MCP branché et lister ses outils (rien n'est approuvé)")
    mce.add_argument("serveur")
    mc.set_defaults(run=_run_mcp)
