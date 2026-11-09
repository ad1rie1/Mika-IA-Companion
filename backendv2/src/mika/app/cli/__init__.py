"""Ligne de commande : ``python -m mika <commande>``.

- ``replay --verify`` : reconstruit tout depuis la genèse et compare à l'état
  obtenu par instantané + queue ;
- ``rebuild <propriétaire>…`` : reconstruction par clôture ;
- ``forget <sujet>`` : oubli (contenus et projections) ;
- ``sim selftest`` : auto-test du simulateur ;
- ``serve`` : le serveur ;
- ``backup DEST`` / ``verify ARCHIVE`` / ``restore ARCHIVE`` : sauvegarde
  (sans risque serveur en marche), vérification, restauration (serveur
  arrêté ; l'ancien dossier est mis de côté) ;
- ``llm show|backend|route|remove|context`` : les modèles (clés chiffrées) ;
- ``account <nom> [<mot de passe>] [--operator]`` : un compte (sans mot de passe : demandé sans écho) ;
- ``token create <compte> [--label …] [--client screen|mobile]`` / ``token list [<compte>]`` / ``token revoke <id>`` :
  les jetons d'un client natif (un moteur de jeu sur ``/ws/world``, ADR 0051 ; l'application du téléphone, ADR
  0062, qui obtient d'ordinaire le sien par ``POST /auth/token``) — montrés une seule fois, gardés en empreinte ;
  serveur en marche, une révocation ferme ses connexions au plus tard dix secondes après ;
- ``serve --origin URL --cookie-secure --behind-proxy`` : derrière un mandataire TLS ;
- ``console apercu --out DOSSIER`` : chaque page de la console, exportée ;
- ``identity link|unlink``, ``social closeness`` et ``forge promote|demote`` : ce
  qu'un opérateur sait mieux qu'elle (serveur arrêté : une seule écriture à la fois
  dans ``mind.db``). Ce sont les actions de la console, par le même chemin
  (``runtime/operations.py``) : mêmes refus, même garde, même audit.
"""

from __future__ import annotations

import argparse
import getpass  # noqa: F401 — un test remplace ``cli.getpass.getpass`` (le mot de passe demandé sans écho)
import sys
from pathlib import Path

from mika.app import datadir
from mika.app.cli import accounts, console, journal, maps, models, plugins, sim
from mika.app.cli.accounts import ask_password, identity_command, operate
from mika.app.cli.common import CLI_BY, _close, _offline, _with_settings
from mika.app.cli.journal import forget, rebuild, replay_verify
from mika.app.cli.plugins import teams_command, wakeup_command
from mika.app.cli.sim import profile_command

__all__ = ["CLI_BY", "_close", "_offline", "_with_settings", "ask_password", "forget", "identity_command", "main",
           "operate", "profile_command", "rebuild", "replay_verify", "teams_command", "wakeup_command"]

#: ce que ``mika --help`` dit à qui la lance pour la première fois
FIRST_STEPS = """Premiers pas :
  1. mika serve                 la lance (http://127.0.0.1:8001), ses données dans ./data/v2
  2. http://127.0.0.1:8001/inspecteur/
                                la console : crée le compte opérateur (le premier compte l'est)
  3. Réglages › Intelligence › Fournisseurs › Ajouter
                                un modèle (Claude, Ollama…) : le premier déclaré la fait parler
  4. le frontend : cd frontend/Web && npm install && npm run dev, puis http://localhost:3000
                                (il vise :8001 ; VITE_BACKEND_ORIGIN pour une autre adresse)

Tout se règle aussi d'ici : mika llm, mika account, mika token… (mika <commande> --help).
Démarrage local pas à pas : backendv2/README.md ; en service (systemd) : deploy/README.md."""

#: les familles de commandes, dans l'ordre où ``mika --help`` les montre
FAMILIES = (journal.add_journal, sim.add_sim, console.add_serve, journal.add_archives, models.add_models,
            accounts.add_accounts, plugins.add_plugins, console.add_console, maps.add_maps, accounts.add_forge)


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except datadir.DataDirBusy as exc:  # un autre Mika tient le dossier : refusé, en le disant
        print(f"Refusé : {exc}", file=sys.stderr)
        return 3


def _run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(prog="mika", description="Le serveur, sa console, et ce qu'un opérateur "
                                                         "règle sans elle.",
                                epilog=FIRST_STEPS, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=Path("data/v2"), help="dossier des bases (mind.db, views.db)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="commande")
    for family in FAMILIES:
        family(sub)
    args = p.parse_args(argv)
    return args.run(args)
