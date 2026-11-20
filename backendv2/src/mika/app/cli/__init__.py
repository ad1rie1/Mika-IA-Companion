"""Ligne de commande : ``python -m mika <commande>``.

Un module par famille de commandes (``FAMILIES``, dans l'ordre où ``mika --help`` les montre) ; chaque
sous-analyseur nomme sa fonction par ``set_defaults(run=…)``. La liste des sous-commandes, leurs options et
leurs codes de sortie sont dans ARCHITECTURE.md › Commandes ; ``FIRST_STEPS`` est l'épilogue de l'aide.

Avant tout, le ``.env`` du dossier courant entre dans l'environnement, sans rien écraser (``app/envfile.py``,
ADR 0250 : une clé d'API posée en local).

Les commandes d'opérateur, ``identity link|unlink``, ``social closeness`` et ``forge promote|demote``, disent
ce qu'un opérateur sait mieux qu'elle (serveur arrêté : une seule écriture à la fois dans ``mind.db``). Ce
sont les actions de la console, par le même chemin (``runtime/operations.py``) : mêmes refus, même garde,
même audit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mika.app import datadir, envfile
from mika.app.cli import accounts, console, journal, maps, models, plugins, sim

__all__ = ["FIRST_STEPS", "main"]

#: ce que ``mika --help`` dit à qui la lance pour la première fois
FIRST_STEPS = """Premiers pas :
  1. mika serve                 la lance (http://127.0.0.1:8001), ses données dans ./data/v2
  2. http://127.0.0.1:8001/admin/
                                la console : crée le compte opérateur (le premier compte l'est)
  3. Réglages › Modèles de texte › Fournisseurs › Ajouter
                                un modèle (Claude, Ollama…) : le premier déclaré la fait parler
  4. l'espace de tous les jours : cd frontendv2 && npm install && npm run dev, puis http://localhost:4173
                                (il vise :8001 ; VITE_BACKEND_ORIGIN pour une autre adresse)
                                en option, le client 3D (sa VRM, sa pièce) : frontend/Web/README.md

Tout se règle aussi d'ici : mika llm, mika account, mika token… (mika <commande> --help).
Démarrage local pas à pas : backendv2/README.md ; en service (systemd) : deploy/README.md."""

#: les familles de commandes, dans l'ordre où ``mika --help`` les montre
FAMILIES = (journal.add_journal, sim.add_sim, console.add_serve, journal.add_archives, models.add_models,
            accounts.add_accounts, plugins.add_plugins, console.add_console, maps.add_maps, accounts.add_forge)


def main(argv: list[str] | None = None) -> int:
    envfile.load()  # le .env du dossier courant, sans rien écraser (jamais dans les tests : MIKA_ENV_FILE vide)
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
