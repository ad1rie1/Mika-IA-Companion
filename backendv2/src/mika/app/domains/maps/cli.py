"""La carte de sa position (``carte``, ADR 0193, 0194, 0244, 0245)."""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
from pathlib import Path

from pydantic import ValidationError

from mika.adapters.maps import FILE as MAP_FILE
from mika.adapters.maps import MapConfig, PlacesConfig, TourismConfig
from mika.adapters.maps import extract as maps_extract
from mika.adapters.maps import osm as maps_osm
from mika.adapters.maps import places as maps_places
from mika.adapters.maps.config import KEY_ENV, TOURISM_KEY_ENV, tourism_key
from mika.adapters.maps.datatourisme import DataTourismeClient, TourismUnavailable, tourism_limits
from mika.adapters.maps.quota import QUOTAS_FILE, Limiter, QuotaStore
from mika.adapters.maps.tourism import Tourism, match_stamp
from mika.adapters.maps.tourism_sync import KIND_FR, NO_ZONES, SyncBusy, TourismSync
from mika.app import schema
from mika.app.cli.common import _with_settings
from mika.app.domains.maps.settings import MapsSettings
from mika.kernel import forms

#: d'où se tire l'index des lieux sans ``--depuis`` : l'extrait OpenStreetMap s'il est là (ADR 0244), sinon les tuiles
OSM_EXTRACT = "cartes/france-latest.osm.pbf"
TILES_ARCHIVE = "cartes/france.pmtiles"


def _said(text: str) -> None:
    print(text, flush=True)  # au fil de l'eau, même dans un fichier


def _places_index(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """``mika carte lieux`` (ADR 0194, 0244) : l'index des lieux tiré de l'extrait OpenStreetMap (``.osm.pbf``, le
    schéma 2, avec les détails d'une fiche) ou des tuiles d'une archive (``.pmtiles``, sans détails) du dossier de
    données — le format se lit à l'extension."""
    wanted = args.depuis or (OSM_EXTRACT if (data / OSM_EXTRACT).is_file() else TILES_ARCHIVE)
    source = data / MapConfig(source=MAP_FILE, file=wanted).file  # sous cartes/, comme le réglage le veut
    rel = PlacesConfig(index=args.sortie).index
    out = data / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    then = f"Réglages › Carte et téléphone › Lieux et adresses : l'index {rel}"
    if source.name.endswith(".pbf"):
        osm = maps_osm.build(source, out, say=_said)
        return {"ok": True, "fichier": str(osm.path), "source": source.name, "extrait": osm.extract,
                "lieux": osm.count, "nœuds": osm.nodes, "voies": osm.ways, "relations": osm.relations,
                "sans_nom": osm.unnamed, "sans_position": osm.unplaced, "doublons": osm.twins,
                "nœuds_placés": osm.needed, "tranches": osm.slices, "par_catégorie": osm.categories,
                "secondes": osm.seconds, "mémoire_max_mo": _peak_mb(), "ensuite": then}
    if not source.name.endswith(".pmtiles"):
        raise maps_places.BuildFailed(f"{source.name} : un extrait OpenStreetMap (.osm.pbf) ou une archive de "
                                      "tuiles (.pmtiles)")
    got = maps_places.build(source, out, say=_said)
    return {"ok": True, "fichier": str(got.path), "lieux": got.count, "tuiles": got.tiles, "zoom": got.zoom,
            "illisibles": got.broken, "par_catégorie": got.categories,
            "laissés_de_côté": [[kind, n] for kind, n in got.skipped[:15]], "secondes": got.seconds,
            "mémoire_max_mo": _peak_mb(), "ensuite": then}


def _peak_mb() -> int:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


async def _tourism_settings(data: Path) -> tuple[TourismConfig, PlacesConfig]:
    """Les réglages des données touristiques et des lieux du dossier de données ; un dossier sans Mika (celui de la
    carte, sur le PC) : les défauts — la clé vient alors de ``MIKA_DATATOURISME_API_KEY``."""
    mind = schema.targets(data)["mind"]
    if mind.path is not None and not mind.path.exists():
        return TourismConfig(), PlacesConfig()

    async def read(settings, _store):  # type: ignore[no-untyped-def]
        own = settings.of(MapsSettings)
        return own.tourism_config(), own.places_config()

    return await _with_settings(data, read)


def _tourism(data: Path, args: argparse.Namespace) -> int:
    """``mika carte tourisme`` (ADR 0245) : une synchronisation des départements tenus en entier (le réglage, ou
    ``--zones`` ; « France » : tous) dans ``cartes/tourisme.db`` — ce qui est dû (complète la première fois, ou à
    reprendre), ou complète (``--complete``). Interrompue, la même commande reprend une complète là où elle s'est
    arrêtée. Ses demandes passent par le même limiteur que le serveur (``cartes/quotas.db``)."""

    async def run() -> dict[str, object]:
        cfg, places_cfg = await _tourism_settings(data)
        changed: dict[str, object] = {}
        if args.zones is not None:
            changed["zones"] = args.zones
        if args.horizon is not None:
            changed["horizon_days"] = args.horizon
        if changed:
            cfg = TourismConfig.model_validate({**cfg.model_dump(), **changed})
        key, origin = tourism_key(cfg)
        if not key:
            return {"ok": False, "erreur": f"Aucune clé DATAtourisme : règle-la dans la console (Réglages › Carte et "
                                           f"téléphone › Données touristiques) ou pose-la dans {TOURISM_KEY_ENV} "
                                           "(read -rs, puis export : jamais sur la ligne de commande)."}
        if not cfg.zones:
            return {"ok": False, "erreur": NO_ZONES}
        tourism = Tourism(data)
        limiter = Limiter("datatourisme", QuotaStore(data / QUOTAS_FILE), lambda: tourism_limits(cfg),
                          label="DATAtourisme")
        client = DataTourismeClient(lambda: cfg, limiter)
        places = maps_places.Places(data, lambda: places_cfg)

        def index() -> tuple[Path, str] | None:
            info = places.info()
            return (data / places_cfg.index, match_stamp(info.built)) if info.ready else None

        sync = TourismSync(tourism, lambda: cfg, client, index=index, say=_said)
        try:
            report = await sync.run(full=True if args.complete else None)
        finally:
            await client.close()
        info = tourism.info()
        return {"ok": True, "fichier": str(tourism.path), "sorte": KIND_FR[report.kind], "reprise": report.resumed,
                "zones": "toute la France" if cfg.everywhere else list(cfg.zones), "pages": report.pages,
                "fiches": report.fiches,
                "illisibles": report.unread, "effacées": report.removed + report.passed, "lieux": info.places,
                "événements": info.events, "rapprochés": info.twins, "situés": info.venues,
                "demandes": report.requests, "clé": "variable d'environnement" if origin == KEY_ENV else "réglage",
                "secondes": report.seconds, "mémoire_max_mo": _peak_mb(),
                "ensuite": "Réglages › Carte et téléphone › Données touristiques (DATAtourisme) : la base, sa "
                           "dernière synchronisation"}

    try:
        out = asyncio.run(run())
    except (TourismUnavailable, SyncBusy) as exc:
        print(json.dumps({"ok": False, "erreur": str(exc), "ensuite": "relance la même commande : une complète "
                                                                       "reprend là où elle s'est arrêtée"},
                         ensure_ascii=False))
        return 1
    except ValidationError as exc:
        print(json.dumps({"ok": False, "erreur": _invalid(exc)}, ensure_ascii=False))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "erreur": "interrompue", "ensuite": "relance la même commande : une complète "
                                                                          "reprend là où elle s'est arrêtée"},
                         ensure_ascii=False))
        return 130
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


def maps_command(data: Path, args: argparse.Namespace) -> int:
    """La carte de sa position (ADR 0193), serveur en marche sans risque : l'archive neuve ne remplace l'ancienne
    qu'entière, et le serveur la rouvre de lui-même ; de même l'index des lieux (ADR 0194). Les données touristiques
    (ADR 0245) : une synchronisation à la fois, serveur en marche ou non (un verrou)."""
    if args.carte_cmd == "tourisme":
        return _tourism(data, args)
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


def add(sub) -> None:  # type: ignore[no-untyped-def]
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
    cl = casub.add_parser("lieux", help="l'index des lieux (points d'intérêt, villes et lieux-dits) tiré de l'extrait "
                                        "OpenStreetMap ou des tuiles d'une archive, sous cartes/ (ADR 0194, 0244)")
    cl.add_argument("--depuis", default="", help=f"l'extrait OpenStreetMap (.osm.pbf de Geofabrik : les détails d'une "
                                                 f"fiche) ou une archive PMTiles vectorielle (sans détails), sous "
                                                 f"cartes/ du dossier de données (défaut : {OSM_EXTRACT} s'il est "
                                                 f"là, sinon {TILES_ARCHIVE})")
    cl.add_argument("--sortie", default="cartes/lieux.db", help="sous cartes/ du dossier de données")
    ct = casub.add_parser("tourisme", help="les départements tenus en entier des données touristiques de "
                                           "DATAtourisme, dans cartes/tourisme.db (ADR 0245) : ce qui est dû, ou "
                                           f"--complete ; la clé du réglage, sinon {TOURISM_KEY_ENV}")
    ct.add_argument("--complete", action="store_true", help="tout, département par département (sinon : ce qui a "
                                                            "changé depuis la dernière, ou tout la première fois)")
    ct.add_argument("--zones", default=None, help="les départements, séparés par des virgules (59,62), ou France : "
                                                  "tous (défaut : ceux du réglage)")
    ct.add_argument("--horizon", type=int, default=None, help="jusqu'où voir les événements, en jours (défaut : "
                                                              "celui du réglage, 90)")
    ca.set_defaults(run=_run_maps)
