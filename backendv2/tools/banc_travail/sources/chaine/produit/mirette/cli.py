"""La commande : ``mirette facture fichier.json --format html|texte``."""

import argparse
import json
import sys

from . import __version__
from .export import en_html, en_texte
from .facture import lire


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mirette", description="Des factures en une commande.")
    ap.add_argument("--version", action="version", version=f"mirette {__version__}")
    sub = ap.add_subparsers(dest="commande", required=True)
    facture = sub.add_parser("facture", help="écrire une facture")
    facture.add_argument("fichier")
    facture.add_argument("--format", choices=["html", "texte"], default="texte")
    args = ap.parse_args(argv)
    try:
        with open(args.fichier, encoding="utf-8") as f:
            donnees = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"mirette : fichier de facture illisible ({exc})", file=sys.stderr)
        return 2
    sortie = en_html if args.format == "html" else en_texte
    sys.stdout.write(sortie(lire(donnees)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
