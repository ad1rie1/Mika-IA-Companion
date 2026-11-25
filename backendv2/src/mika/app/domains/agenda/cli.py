"""Sa commande (ADR 0309, 0310) : ``mika agenda google``, l'application Google du serveur, hors ligne."""

from __future__ import annotations

import argparse
import asyncio
import json

from mika.adapters.agenda.oauth import RETURN_PATH
from mika.app.cli.common import _with_settings
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.settings import Settings


async def agenda_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """``mika agenda google`` (ADR 0309, lot 2) : l'application Google du serveur — un client OAuth d'un projet Google
    Cloud, « Application de bureau » (ou « Application Web » avec ``--web``) —, la poser, l'effacer (``--defaut``) ou
    la montrer, jamais son secret. En changer demande de reconnecter les comptes Google."""
    if args.defaut:
        await settings.of(AgendaSettings).save_google_application("")
    elif args.client_id is not None:
        try:
            await settings.of(AgendaSettings).save_google_application(args.client_id, args.secret or "", web=args.web)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    app = settings.of(AgendaSettings).google_application()
    if app is None:
        return {"ok": True, "application": None,
                "usage": "mika agenda google <identifiant>.apps.googleusercontent.com --secret GOCSPX-…"}
    return {"ok": True, "application": app.client_id, "secret": "…", "type": "web" if app.web else "bureau",
            "retour": f"https://<origine du serveur>{RETURN_PATH}" if app.web else "http://127.0.0.1:<port>/ (on colle "
                                                                                 "l'adresse)"}


def _run_agenda(args: argparse.Namespace) -> int:
    out = asyncio.run(_with_settings(args.data, lambda settings, _store: agenda_command(settings, args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1


def add(sub) -> None:  # type: ignore[no-untyped-def]
    """Sa commande et ses sous-commandes, dans l'analyseur de ``mika``."""
    ag = sub.add_parser("agenda", help="les agendas branchés (ADR 0309) : l'application Google du serveur")
    agsub = ag.add_subparsers(dest="agenda_cmd", required=True)
    agg = agsub.add_parser("google", help="l'application Google par laquelle se branchent les comptes Google Agenda "
                                          "(un client OAuth d'un projet Google Cloud) ; sans argument, la montre")
    agg.add_argument("client_id", nargs="?", help="l'identifiant du client (….apps.googleusercontent.com)")
    agg.add_argument("--secret", help="le secret du client (GOCSPX-…), scellé ; omis, celui de la même application "
                                      "reste")
    agg.add_argument("--web", action="store_true",
                     help=f"un client « Application Web » : il revient seul à l'origine HTTPS du serveur ({RETURN_PATH}) "
                          "au lieu qu'on colle l'adresse")
    agg.add_argument("--defaut", action="store_true", help="l'efface : brancher Google est alors refusé")
    ag.set_defaults(run=_run_agenda)
