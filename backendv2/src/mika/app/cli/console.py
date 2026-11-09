"""Le serveur et sa console : ``serve``, ``console apercu``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mika.app.server import serve


def _run_serve(args: argparse.Namespace) -> int:
    serve(host=args.host, port=args.port, data=args.data, reports=args.reports, origins=args.origins,
          cookie_secure=args.cookie_secure, behind_proxy=args.behind_proxy)
    return 0


def _run_console(args: argparse.Namespace) -> int:
    from mika.app import apercu  # noqa: PLC0415 — le client de test n'est chargé que pour l'aperçu

    try:
        pages = apercu.export(args.out)
    except apercu.ExportFailed as exc:
        print(f"Aperçu exporté, sauf : {exc}", file=sys.stderr)
        return 1
    print(f"{len(pages)} pages exportées : {args.out / 'index.html'}")
    return 0


def add_serve(sub) -> None:  # type: ignore[no-untyped-def]
    sv = sub.add_parser("serve", help="la lancer : le serveur du chat et sa console (http://127.0.0.1:8001/"
                                      "inspecteur/)")
    sv.add_argument("--port", type=int, default=8001, help="le port (défaut : 8001)")
    sv.add_argument("--host", default="127.0.0.1", help="l'adresse d'écoute (défaut : cette machine seulement)")
    sv.add_argument("--reports", type=Path, default=None, help="dossier des rapports de simulation (inspecteur)")
    sv.add_argument("--origin", action="append", default=[], dest="origins",
                    help="une origine admise du frontend (répétable, ex. https://mika.example) ; remplace celles "
                         "du développement")
    sv.add_argument("--cookie-secure", action="store_true", help="cookies « Secure » (servi en HTTPS)")
    sv.add_argument("--behind-proxy", action="store_true",
                    help="derrière un mandataire TLS local : l'adresse du client vient de ses en-têtes, cookies "
                         "« Secure », et les points MCP refusent toute requête relayée")
    sv.set_defaults(run=_run_serve)


def add_console(sub) -> None:  # type: ignore[no-untyped-def]
    co = sub.add_parser("console", help="la console d'exploitation")
    csub = co.add_subparsers(dest="console_cmd", required=True)
    cap = csub.add_parser("apercu", help="exporter chaque page (clair et sombre) d'une vie neuve, sans serveur")
    cap.add_argument("--out", type=Path, required=True)
    co.set_defaults(run=_run_console)
