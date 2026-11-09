"""La carte de sa position (``carte``, ADR 0193, 0194)."""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
from pathlib import Path

from pydantic import ValidationError

from mika.adapters.maps import FILE as MAP_FILE
from mika.adapters.maps import MapConfig, PlacesConfig
from mika.adapters.maps import extract as maps_extract
from mika.adapters.maps import places as maps_places
from mika.kernel import forms


def _said(text: str) -> None:
    print(text, flush=True)  # au fil de l'eau, même dans un fichier


def _places_index(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """``mika carte lieux`` (ADR 0194) : l'index des lieux tiré des tuiles d'une archive du dossier de données."""
    source = data / MapConfig(source=MAP_FILE, file=args.depuis).file  # sous cartes/, comme le réglage le veut
    rel = PlacesConfig(index=args.sortie).index
    out = data / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    got = maps_places.build(source, out, say=_said)
    return {"ok": True, "fichier": str(got.path), "lieux": got.count, "tuiles": got.tiles, "zoom": got.zoom,
            "illisibles": got.broken, "par_catégorie": got.categories,
            "laissés_de_côté": [[kind, n] for kind, n in got.skipped[:15]], "secondes": got.seconds,
            "mémoire_max_mo": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
            "ensuite": f"Réglages › Carte et téléphone › Lieux et adresses : l'index {rel}"}


def maps_command(data: Path, args: argparse.Namespace) -> int:
    """La carte de sa position (ADR 0193), serveur en marche sans risque : l'archive neuve ne remplace l'ancienne
    qu'entière, et le serveur la rouvre de lui-même ; de même l'index des lieux (ADR 0194)."""
    if args.carte_cmd == "lieux":
        try:
            out = _places_index(data, args)
        except maps_places.BuildFailed as exc:
            print(json.dumps({"ok": False, "erreur": str(exc)}, ensure_ascii=False))
            return 1
        except ValidationError as exc:
            print(json.dumps({"ok": False, "erreur": _invalid(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps(out, ensure_ascii=False))
        return 0

    async def run() -> dict[str, object]:
        async with maps_extract.client() as client:
            if args.carte_cmd == "polices":
                folder = data / "cartes" / "assets"
                count = await maps_extract.assets(client, folder, say=_said)
                return {"ok": True, "fichiers": count, "dossier": str(folder)}
            rel = MapConfig(source=MAP_FILE, file=args.sortie).file  # sous cartes/, comme le réglage le veut
            out = data / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            url = args.depuis or await maps_extract.latest_build(client)
            print(f"depuis {url}")
            got = await maps_extract.extract(maps_extract.ranges(client, url), out, maps_extract.zone(args.zone),
                                             args.zoom, say=_said)
            return {"ok": True, "fichier": str(got.path), "tuiles": got.tiles, "octets": got.size,
                    "zooms": [got.minzoom, got.maxzoom], "zone": [round(v, 4) for v in got.bounds],
                    "ensuite": f"Réglages › Carte et téléphone › Carte de sa position : « Un fichier », {rel}"}

    try:
        out = asyncio.run(run())
    except maps_extract.ExtractFailed as exc:
        print(json.dumps({"ok": False, "erreur": str(exc).splitlines()[-1]}, ensure_ascii=False))
        return 1
    except ValidationError as exc:
        print(json.dumps({"ok": False, "erreur": _invalid(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _invalid(exc: ValidationError) -> str:
    """Un réglage refusé, en mots : le champ et ce qu'il demande — jamais l'adresse de la documentation de pydantic
    (la dernière ligne de son message)."""
    return " ; ".join(f"{path} : {message}" if path else message for path, message in forms.errors_fr(exc).items())


def _run_maps(args: argparse.Namespace) -> int:
    return maps_command(args.data, args)


def add_maps(sub) -> None:  # type: ignore[no-untyped-def]
    ca = sub.add_parser("carte", help="la carte de sa position (ADR 0193) : une zone extraite, ses polices")
    casub = ca.add_subparsers(dest="carte_cmd", required=True)
    cx = casub.add_parser("extraire", help="extraire une zone de la carte Protomaps de la planète, sous cartes/")
    cx.add_argument("--depuis", default="", help="une archive PMTiles servie par plages (défaut : la dernière carte "
                                                  "de la planète de Protomaps)")
    cx.add_argument("--zone", default="france", help="france, ou ouest,sud,est,nord en degrés")
    cx.add_argument("--zoom", type=int, default=15, help="le zoom le plus fin (15 : la rue ; chaque zoom de moins "
                                                         "divise la taille par quatre environ)")
    cx.add_argument("--sortie", default="cartes/france.pmtiles", help="sous cartes/ du dossier de données")
    casub.add_parser("polices", help="ses polices et ses icônes (protomaps/basemaps-assets), sous cartes/assets")
    cl = casub.add_parser("lieux", help="l'index des lieux (points d'intérêt, villes et lieux-dits) tiré des tuiles "
                                        "d'une archive, sous cartes/ (ADR 0194)")
    cl.add_argument("--depuis", default="cartes/france.pmtiles", help="l'archive PMTiles (vectorielle), sous cartes/ "
                                                                      "du dossier de données")
    cl.add_argument("--sortie", default="cartes/lieux.db", help="sous cartes/ du dossier de données")
    ca.set_defaults(run=_run_maps)
