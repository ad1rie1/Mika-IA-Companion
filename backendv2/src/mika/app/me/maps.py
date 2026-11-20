"""Carte, lieux, itinéraires et voyages, pour qui est connecté (ADR 0193 à 0196, 0229).

- **Le fond de carte**, celui de toutes les cartes (Téléphone › Position, l'écran Carte, les miniatures du chat) : ce
  que le client en sait, ses tuiles, ses polices et ses icônes, tirées des tuiles réglées (``MeApiBase.tiles``) et
  servies par ce serveur seul, que le navigateur garde un jour sous une adresse qui porte leur version.
- **La carte** : ce qui est branché (l'index des lieux, les adresses, les itinéraires) ; chercher un lieu dans
  l'index local (rien ne sort), une adresse (seul le texte cherché part), un itinéraire (seuls ses points partent) ;
  et ce qu'elle a cherché ou montré pour toi (un regard, une carte, par leur ``seq``). Tout passe par le port de la
  carte (``kernel.ports["maps"]``, ``mika.ports.maps``) : le navigateur ne joint jamais un autre hôte que ce serveur.
- **Les fiches, les événements, les photos** (ADR 0259) : une liste filtrée et notée (ouvert, terrasse, cuisine, note,
  tri), la fiche entière d'un lieu (OpenStreetMap, l'office de tourisme, Google, les événements tout près) et
  « Actualiser », les événements autour d'un point ou dans une zone et la fiche de l'un d'eux, une photo relayée par sa
  référence — chacune avec ce qu'il faut citer (« Google Maps », l'auteur et le lien de chaque avis et de chaque
  photo, l'auteur et la date d'une fiche DATAtourisme, OpenStreetMap). « Ici » (``near=ici``) est ta dernière position,
  celle que ton téléphone a donnée, jamais celle d'une autre ; chercher autour de toi précharge les avis de ta case
  (``preload`` : une mise en file, qui ne retient pas la réponse). Ce qui peut faire appeler un service compté est
  borné par compte (``MAP_READS``, ``PHOTO_READS``, ``REFRESHES``, ``PRELOADS``).
- **Tes voyages** : les tiens seulement — un voyage d'une autre personne n'existe pas (le même 404). Ce qu'on y fait
  passe par les actions du plugin ``trips`` (``call.act``), au nom de qui est connecté : journalisées, dédoublonnées
  (``Idempotency-Key``) comme dans la console, auditées depuis son espace (``moi.<action>``). Ce qu'elle y a ajouté
  porte ``"by": "mika"``, ce que tu y as fait ``"toi"``. Le meilleur ordre des arrêts (d'un jour) et les lieux le
  long d'un trajet (ADR 0194) se demandent sur un voyage, seulement : un itinéraire en devient un d'un clic.

Le contrat, route par route : ``docs/protocole-moi.md``, § 10.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from starlette.responses import FileResponse, Response
from starlette.routing import Route

from mika.adapters.maps import NONE as NO_MAP
from mika.adapters.maps import MapUnavailable, gpx
from mika.app.me.api import PREFIX, Call, Denied, MeApiBase, done, form, missing, spend
from mika.app.me.common import millis, texts_of
from mika.contracts import trips as c
from mika.kernel.events import EventType
from mika.plugins import location as location_p
from mika.plugins import trips as trips_p
from mika.plugins.trips import Stop, Trip, TripsState, days_of, geo
from mika.plugins.trips.tools import along_points, place_items, stop_point
from mika.ports.maps import (
    AVOIDS,
    EVENT_REF,
    EVENTS_LIMIT_MAX,
    EVENTS_SPAN_MAX_DAYS,
    FEATURES,
    HIT_FIELDS,
    MODES,
    PHOTO_REF,
    PLACE_REF,
    ROUTE_POINTS_MAX,
    SORTS,
    THEMES,
    EventDetail,
    EventHit,
    MapsNotFound,
    MapsUnavailable,
    OsmFacts,
    Photo,
    PlaceDetail,
    PlaceHit,
    Review,
    ReviewFacts,
    RouteLeg,
    RouteResult,
    TourismFacts,
    extras,
)
from mika.runtime.effects import with_content
from mika.runtime.operations import SPACE, Outcome, perform

MAP_PATH = "/carte"
#: le fond de carte (ADR 0193), avec la carte (ADR 0229) : ce que le client en sait, et sous lui ses tuiles, ses
#: polices et ses icônes
BASE_MAP = MAP_PATH + "/fond"
TRIPS_PATH = "/voyages"
#: un texte cherché ; combien de lieux au plus ; d'un trajet, à quelle distance chercher (en mètres)
QUERY_MAX = 200
LIMIT_MAX = 50
CORRIDOR_MIN, CORRIDOR_MAX, CORRIDOR = 200, 50_000, 5_000
#: qui a fait un geste, pour l'écran : elle (rose), ou toi
HERS, YOURS = c.BY_HER, "toi"

NOT_PLUGGED = "La carte n'est pas branchée sur ce serveur."

# ── les fiches, les événements, les photos (ADR 0259) ──
PLACE_PATH, EVENTS_PATH, EVENT_PATH, PHOTO_PATH = (MAP_PATH + "/lieu", MAP_PATH + "/evenements",
                                                   MAP_PATH + "/evenement", MAP_PATH + "/photo")
#: « ici » : ta dernière position, celle que ton téléphone a donnée
HERE = "ici"
#: les filtres d'un lieu, dans l'ordre de l'écran (``ports.maps.FEATURES``), en mots
FEATURE_LABELS = {"terrasse": "Terrasse", "vegetarien": "Végétarien", "vegan": "Vegan", "accessible": "Accessible",
                  "emporter": "À emporter", "livraison": "Livraison"}
SORT_LABELS = {"distance": "Les plus proches", "rating": "Les mieux notés"}
#: une cuisine cherchée ; une note minimale (sur 5) ; le rayon des événements autour d'un point (en mètres)
CUISINE_MAX = 40
RADIUS_MIN, RADIUS_MAX, RADIUS = 500, 100_000, 20_000
#: ce qu'il faut citer avec chaque source (les clients le montrent tel quel)
OSM_CREDIT, OSM_LICENCE = "© les contributeurs d'OpenStreetMap", "https://www.openstreetmap.org/copyright"
TOURISM_SOURCE, TOURISM_LICENCE = "DATAtourisme", "Licence Ouverte 2.0"
TOURISM_LICENCE_URL = "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"
SOURCE_LABELS = {"google": "Google Maps"}
#: ce que le navigateur garde d'une photo relayée : pour lui seul, un jour (sa référence ne change pas d'image) ; les
#: seules sortes qu'on sert (des images qui ne portent rien d'actif : ni SVG, ni page)
PHOTO_CACHE = "private, max-age=86400"
PHOTO_MEDIA = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
PHOTO_HEADERS = {"Cache-Control": PHOTO_CACHE, "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}
NO_HERE = ("Ta position n'est pas connue ici : ton téléphone ne l'a pas donnée (Téléphone › Position, l'application "
           "ouverte), ou tu as cessé de la partager.")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
          "décembre")
#: ce qui n'est pas prêt : ce que la personne en lit, puis ce qu'une opératrice en lit. Une personne n'a pas la
#: console : ce qui manque et où le régler ne se dit qu'à qui peut le faire
NOT_READY = {
    "places": ("La recherche de lieux n'est pas encore prête sur ce serveur.",
               "L'index des lieux n'est pas construit : Réglages › Carte et téléphone › Lieux et adresses "
               "(mika carte lieux)."),
    "addresses": ("La recherche d'adresses n'est pas encore prête sur ce serveur.",
                  "Les adresses ne sont pas branchées : Réglages › Carte et téléphone › Lieux et adresses."),
    "routing": ("Les itinéraires ne sont pas encore prêts sur ce serveur.",
                "Les itinéraires ne sont pas réglés : Réglages › Carte et téléphone › Itinéraires."),
}
_DIGITS = re.compile(r"^\d{1,18}$")


def _maps(call: Call, need: str = "") -> Any:
    """Le port de la carte, et ce dont la route a besoin (``places``, ``addresses``, ``routing``) : sinon 503, dit."""
    port = call.port("maps")
    if port is None:
        raise Denied(503, NOT_PLUGGED)
    if (need == "places" and not port.places_ready()) or (need == "addresses" and not port.addresses_ready()) \
            or (need == "routing" and not port.routing_ready()):
        person, operator = NOT_READY[need]
        raise Denied(503, operator if call.me.operator else person)
    return port


def _unavailable(exc: MapsUnavailable) -> Denied:
    return Denied(503, str(exc)[:300] or NOT_PLUGGED)


def _state(call: Call) -> TripsState:
    return call.frame.state(trips_p.TRIPS.name)


# ── lire les paramètres ──


def _int(call: Call, name: str, default: int, low: int, high: int) -> int:
    """Un nombre entier, de la requête ou du corps : refusé hors de ses bornes, jamais ramené dedans."""
    raw = call.request.query_params.get(name)
    got: Any = raw if raw is not None else call.data.get(name, default)
    if isinstance(got, bool) or (isinstance(got, float) and not got.is_integer()):
        # un flottant qui n'est pas entier (2.9) est refusé, jamais tronqué ; ``Infinity`` (que json accepte) aussi
        raise Denied(400, f"« {name} » : un nombre entier.", {name: "un nombre entier"})
    try:
        value = int(got)
    except (TypeError, ValueError, OverflowError):
        raise Denied(400, f"« {name} » : un nombre entier.", {name: "un nombre entier"}) from None
    if not low <= value <= high:
        raise Denied(400, f"« {name} » : de {low} à {high}.", {name: f"de {low} à {high}"})
    return value


def _coords(text: str, name: str) -> geo.Point:
    got = geo.parse_coords(text)
    if got is None:
        raise Denied(400, f"« {name} » : latitude,longitude.", {name: "latitude,longitude"})
    return got


def _points(call: Call) -> list[geo.Point]:
    """``points=lat,lon;lat,lon…`` : de deux à ``ROUTE_POINTS_MAX`` points."""
    parts = [p for p in call.arg("points", limit=ROUTE_POINTS_MAX * 40).split(";") if p.strip()]
    if not 2 <= len(parts) <= ROUTE_POINTS_MAX:
        raise Denied(400, f"« points » : de 2 à {ROUTE_POINTS_MAX} points « latitude,longitude » séparés par « ; ».",
                     {"points": f"de 2 à {ROUTE_POINTS_MAX} points"})
    return [_coords(p, "points") for p in parts]


def _mode(call: Call) -> str:
    mode = call.arg("mode", limit=20) or c.DEFAULT_MODE
    if mode not in MODES:
        raise Denied(400, f"« mode » : {', '.join(MODES)}.", {"mode": ", ".join(MODES)})
    return mode


def _avoid(call: Call) -> list[str]:
    """Ce qu'un trajet évite : ``avoid=peages,autoroutes`` dans la requête, une liste dans un corps."""
    raw = call.data.get("avoid") if call.request.query_params.get("avoid") is None else None
    if isinstance(raw, list):
        got = call.strings("avoid", limit=len(AVOIDS), size=20)
    else:
        got = [a.strip() for a in call.arg("avoid", limit=60).split(",") if a.strip()]
    bad = [a for a in got if a not in AVOIDS]
    if bad:
        raise Denied(400, f"« avoid » : {', '.join(AVOIDS)}.", {"avoid": ", ".join(AVOIDS)})
    return [a for a in AVOIDS if a in got]


def _category(call: Call, port: Any) -> str:
    cat = call.arg("cat", limit=40).strip()
    if cat and cat not in {k for k, _ in port.categories()}:
        raise Denied(400, "« cat » : une des catégories de GET /api/moi/carte.", {"cat": "une catégorie connue"})
    return cat


def _bbox(text: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = (float(x) for x in text.split(","))
    except ValueError:
        raise Denied(400, "« bbox » : ouest,sud,est,nord.", {"bbox": "ouest,sud,est,nord"}) from None
    # une zone plate ou retournée (ouest ≥ est, sud ≥ nord) ne se cherche pas : refusée, comme le port le veut
    if not (geo.valid(south, west) and geo.valid(north, east)) or south >= north or west >= east:
        raise Denied(400, "« bbox » : ouest,sud,est,nord (ouest < est, sud < nord).", {"bbox": "ouest,sud,est,nord"})
    return west, south, east, north


# ── ce qu'on rend ──


def _hit(hit: PlaceHit) -> dict[str, Any]:
    """Un lieu trouvé : ses champs de toujours, et ce qu'on en sait en plus (ADR 0244 : son objet d'OpenStreetMap,
    ouvert ou fermé, sa cuisine, ses filtres…) seulement quand on le sait."""
    return {**{name: getattr(hit, name) for name in HIT_FIELDS}, **extras(hit)}


def _leg(leg: RouteLeg) -> dict[str, Any]:
    return {"distance_m": leg.distance_m, "duration_s": leg.duration_s, "shape": leg.shape,
            "steps": [{"text": s.text, "distance_m": s.distance_m, "duration_s": s.duration_s} for s in leg.steps]}


def _route(route: RouteResult) -> dict[str, Any]:
    return {"distance_m": route.distance_m, "duration_s": route.duration_s, "legs": [_leg(x) for x in route.legs],
            "has_toll": route.has_toll, "has_highway": route.has_highway, "has_ferry": route.has_ferry,
            "provider": route.provider}


def _order(got: Any, n: int) -> list[int]:
    """L'ordre rendu par le serveur d'itinéraires : chaque point une fois, le départ et l'arrivée à leur place."""
    try:
        order = [int(i) for i in got]
    except (TypeError, ValueError):
        order = []
    if sorted(order) != list(range(n)) or (n and (order[0] != 0 or order[-1] != n - 1)):
        raise Denied(502, "Le serveur d'itinéraires a rendu un ordre illisible.")
    return order


# ── la carte ──


def _index(port: Any) -> tuple[int, int]:
    """Combien de lieux a l'index, et quand il a été construit (ms) : ce que le port en dit (``places_summary``,
    ``built`` en ISO 8601) ; 0 pour ce qu'il ne dit pas lisiblement."""
    got = port.places_summary()
    if not isinstance(got, Mapping):
        return 0, 0
    try:
        count = max(0, int(got.get("count") or 0))
    except (TypeError, ValueError):
        count = 0
    try:
        built = int(datetime.fromisoformat(str(got.get("built") or "")).timestamp() * 1000)
    except ValueError:
        built = 0
    return count, max(0, built)


def _tourism_summary(port: Any) -> dict[str, Any]:
    """La base des données touristiques : prête, combien de lieux et d'événements, sa dernière lecture (ms)."""
    got = port.tourism_summary() if hasattr(port, "tourism_summary") else {}
    if not isinstance(got, Mapping):
        got = {}
    try:
        counts = max(0, int(got.get("places") or 0)), max(0, int(got.get("events") or 0))
    except (TypeError, ValueError):
        counts = 0, 0
    return {"ready": bool(got.get("ready")), "places": counts[0], "events": counts[1],
            "synced": _when_ms(str(got.get("synced") or ""))}


async def info(call: Call) -> dict[str, Any]:
    """Ce qui est branché : l'index des lieux, les adresses, les itinéraires (qui les calcule), les données
    touristiques ; les catégories, les filtres et les ordres d'une liste, les thèmes des événements."""
    port = call.port("maps")
    routing = {"modes": list(MODES), "avoid": list(AVOIDS)}
    lists = {"features": [{"id": k, "label": FEATURE_LABELS[k]} for k in FEATURES],
             "sorts": [{"id": k, "label": SORT_LABELS[k]} for k in SORTS],
             "themes": [{"id": k, "label": v} for k, v in THEMES]}
    if port is None:
        return {"places": {"ready": False, "count": 0, "built": 0}, "addresses": {"ready": False},
                "routing": {"ready": False, "provider": "", **routing}, "categories": [],
                "tourism": {"ready": False, "places": 0, "events": 0, "synced": 0}, **lists}
    count, built = _index(port)
    ready = port.routing_ready()
    return {"places": {"ready": port.places_ready(), "count": count, "built": built},
            "addresses": {"ready": port.addresses_ready()},
            "routing": {"ready": ready, "provider": port.routing_provider() if ready else "", **routing},
            "categories": [{"id": k, "label": v} for k, v in port.categories()],
            "tourism": _tourism_summary(port), **lists}


def _here(call: Call) -> dict[str, Any]:
    """« Ici » : ta dernière position, celle que ton téléphone a donnée (``location``, ADR 0119) — la tienne, jamais
    celle d'une autre (``last_for``) ; aucune (jamais donnée, effacée, oubliée) : 409, dit."""
    fix = location_p.last_for(call.frame.state(location_p.LOCATION.name), call.frame, call.me.handle)
    texts = texts_of(call, [fix.coords_ref, fix.label_ref]) if fix is not None else {}
    at = geo.parse_coords(texts.get(fix.coords_ref)) if fix is not None else None
    if fix is None or at is None:
        raise Denied(409, NO_HERE, {"near": "ta position n'est pas connue"})
    return {"lat": at[0], "lon": at[1], "label": texts.get(fix.label_ref, ""), "at": millis(fix.fixed_at)}


def _near(call: Call) -> tuple[geo.Point | None, dict[str, Any] | None]:
    """``near`` : « latitude,longitude », ou « ici » (ta dernière position : ``_here``) ; et ce qu'« ici » était."""
    text = call.arg("near", limit=60).strip()
    if not text:
        return None, None
    if text.lower() == HERE:
        here = _here(call)
        return (here["lat"], here["lon"]), here
    return _coords(text, "near"), None


def _features(call: Call) -> frozenset[str]:
    got = [f.strip() for f in call.arg("features", limit=120).split(",") if f.strip()]
    if any(f not in FEATURES for f in got):
        raise Denied(400, f"« features » : {', '.join(FEATURES)}.", {"features": ", ".join(FEATURES)})
    return frozenset(got)


def _rating(call: Call) -> float | None:
    """``min_rating`` : une note de 0 à 5 (« 4.5 ») ; absente : aucune."""
    raw = call.arg("min_rating", limit=10).strip()
    if not raw:
        return None
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or not 0.0 <= value <= 5.0:
        raise Denied(400, "« min_rating » : une note de 0 à 5.", {"min_rating": "de 0 à 5"})
    return value


def _sort(call: Call) -> str:
    got = call.arg("sort", limit=20).strip() or SORTS[0]
    if got not in SORTS:
        raise Denied(400, f"« sort » : {', '.join(SORTS)}.", {"sort": ", ".join(SORTS)})
    return got


def _map_read(call: Call) -> None:
    """Une fiche, des événements : ce qui peut faire appeler un service compté, borné par compte (429 au-delà)."""
    if not spend(call.api.map_reads, call.me.account):
        raise Denied(429, "Trop de fiches et d'événements demandés d'affilée : attends une minute.")


def _preload(call: Call, port: Any, at: geo.Point) -> None:
    """Chercher autour de soi précharge les avis de sa case (``preload`` : une mise en file, sur le budget de fond, qui
    ne retient pas la réponse) — au plus ``PRELOADS`` fois par compte ; au-delà, rien, sans le dire."""
    preload = getattr(port, "preload", None)
    if preload is not None and spend(call.api.preloads, call.me.account):
        preload(at[0], at[1])


def _when_ms(iso: str) -> int:
    """Un instant en ISO 8601 (« 2026-11-18T08:00:00Z »), en ms ; vide ou illisible : 0."""
    try:
        return int(datetime.fromisoformat(str(iso or "").replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


def _coverage(got: Any) -> dict[str, Any]:
    """Ce qu'un cache sait d'un endroit (``ReviewsCoverage``, ``TourismCoverage``) : prêt, ses cases lues, la lecture
    la plus ancienne (ms), et ce qu'il faut en dire, en mots."""
    return {"ready": bool(got.ready), "cells": got.cells, "loaded": got.loaded, "oldest": _when_ms(got.oldest),
            "note": got.note}


async def places(call: Call) -> dict[str, Any]:
    """Des lieux de l'index local : par le nom (``q``), d'une catégorie (``cat``), près d'un point (``near``, ou
    « ici »), dans une zone (``bbox``) ; filtrés (ouvert, ce qu'ils offrent, leur cuisine, leur note) et rangés (la
    distance, la note) ; avec ce que le cache des avis sait de l'endroit (``reviews``)."""
    port = _maps(call, "places")
    text = " ".join(call.arg("q", limit=QUERY_MAX).split())
    category = _category(call, port)
    near, here = _near(call)
    bbox_text = call.arg("bbox", limit=120)
    bbox = _bbox(bbox_text) if bbox_text.strip() else None
    if not text and near is None and bbox is None:
        raise Denied(400, "Cherche un nom (q), ou autour d'un point (near), ou dans une zone (bbox).")
    limit = _int(call, "limit", 20, 1, LIMIT_MAX)
    open_now, features, sort = call.flag("open_now"), _features(call), _sort(call)
    cuisine, min_rating = " ".join(call.arg("cuisine", limit=CUISINE_MAX).split()), _rating(call)
    if near is not None and (here is not None or call.flag("here")):
        _preload(call, port, near)  # « autour de moi »
    try:
        hits = await port.search(text, near=near, bbox=bbox, category=category, limit=limit, open_now=open_now,
                                 features=features, cuisine=cuisine, min_rating=min_rating, sort=sort)
    except ValueError as exc:
        raise Denied(400, str(exc)[:300]) from None
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    out: dict[str, Any] = {"places": [_hit(h) for h in hits[:limit]]}
    if (near is not None or bbox is not None) and hasattr(port, "reviews_coverage"):
        out["reviews"] = _coverage(port.reviews_coverage(near=near if bbox is None else None, bbox=bbox))
    if here is not None:
        out["here"] = here
    return out


# ── une fiche (ADR 0259) ──


def _pairs(pairs: Any) -> list[dict[str, str]]:
    return [{"label": a, "value": b} for a, b in pairs]


def _photo(p: Photo) -> dict[str, Any]:
    """Une photo : sa référence et le chemin qui la sert (``…/carte/photo/<ref>``, sur ce serveur seul), sa source, son
    crédit et son lien (à montrer avec elle), sa licence, sa légende, ses dimensions."""
    return {"ref": p.ref, "path": f"{PREFIX}{PHOTO_PATH}/{p.ref}", "source": p.source, "credit": p.credit,
            "credit_url": p.credit_url, "licence": p.licence, "caption": p.caption, "width": p.width,
            "height": p.height}


def _date_fr(iso: str) -> str:
    """« 5 décembre 2023 » ; illisible : tel quel."""
    try:
        d = date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return iso or ""
    return f"{'1er' if d.day == 1 else d.day} {MONTHS[d.month - 1]} {d.year}"


def _credit(author: str, updated: str) -> str:
    """Ce que la Licence Ouverte demande de citer : « DATAtourisme · Hello Lille, mis à jour le 5 décembre 2023 »."""
    who = f"{TOURISM_SOURCE} · {author}" if author else TOURISM_SOURCE
    return f"{who}, mis à jour le {_date_fr(updated)}" if updated else who


def _osm(o: OsmFacts | None) -> dict[str, Any] | None:
    if o is None:
        return None
    return {"id": o.id, "url": o.url, "address": o.address, "phone": o.phone, "website": o.website, "email": o.email,
            "hours": o.hours, "hours_text": o.hours_text, "facts": _pairs(o.facts), "wikidata": o.wikidata,
            "wikipedia": o.wikipedia, "extract": o.extract, "attribution": OSM_CREDIT, "licence_url": OSM_LICENCE}


def _tourism(t: TourismFacts | None) -> dict[str, Any] | None:
    if t is None:
        return None
    return {"id": t.id, "description": t.description, "labels": list(t.labels), "prices": t.prices,
            "contacts": _pairs(t.contacts), "author": t.author, "updated": t.updated, "url": t.url,
            "photos": [_photo(p) for p in t.photos], "attribution": _credit(t.author, t.updated),
            "licence": TOURISM_LICENCE, "licence_url": TOURISM_LICENCE_URL}


def _review(r: Review) -> dict[str, Any]:
    return {"rating": r.rating, "text": r.text, "author": r.author, "author_url": r.author_url, "at": _when_ms(r.date),
            "relative": r.relative, "language": r.language}


def _reviews(f: ReviewFacts | None) -> dict[str, Any] | None:
    if f is None:
        return None
    return {"source": f.source, "source_label": SOURCE_LABELS.get(f.source, f.source), "found": bool(f.id),
            "id": f.id, "rating": f.rating, "count": f.count, "price": f.price, "price_range": f.price_range,
            "summary": f.summary, "facts": _pairs(f.facts), "reviews": [_review(r) for r in f.reviews],
            "photos": [_photo(p) for p in f.photos], "url": f.url, "cached": _when_ms(f.cached), "note": f.note}


def _event_hit(e: EventHit) -> dict[str, Any]:
    """Un événement trouvé : tous ses champs, toujours (``free`` : ``null`` quand on ne sait pas ; ``photo`` : vide
    sans photo)."""
    return {"id": e.id, "name": e.name, "start": e.start, "end": e.end, "when_text": e.when_text, "place": e.place,
            "lat": e.lat, "lon": e.lon, "distance_m": e.distance_m, "themes": list(e.themes), "free": e.free,
            "price": e.price, "photo": e.photo}


def _fiche(d: PlaceDetail) -> dict[str, Any]:
    return {"place": _hit(d.hit), "osm": _osm(d.osm), "tourism": _tourism(d.tourism), "reviews": _reviews(d.reviews),
            "events": [_event_hit(e) for e in d.events]}


def _place_id(call: Call) -> str:
    """L'identifiant d'un lieu (``l<n>``, ``n123``/``w45``/``r6``, ``t:<uuid>``) ; une autre forme n'existe pas
    (404), sans rien demander au port."""
    ident = str(call.request.path_params["place"])
    if not PLACE_REF.match(ident):
        raise missing()
    return ident


async def place_read(call: Call) -> dict[str, Any]:
    """La fiche d'un lieu : sa ligne (``place``), puis ce qu'en dit chaque source — OpenStreetMap, l'office de
    tourisme (DATAtourisme), Google — et les événements tout près."""
    ident = _place_id(call)
    port = _maps(call, "places")
    _map_read(call)
    try:
        got = await port.place(ident)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    if got is None:
        raise missing()
    return _fiche(got)


async def place_refresh(call: Call) -> dict[str, Any]:
    """« Actualiser » : sa fiche relue tout de suite chez Google et à l'office de tourisme — au plus ``REFRESHES`` par
    compte. Ce qui n'a pas pu se relire : 503, en mots (ce qui l'a pu est gardé : relis la fiche)."""
    ident = _place_id(call)
    port = _maps(call, "places")
    if not spend(call.api.refreshes, call.me.account):
        raise Denied(429, "Trop de fiches actualisées d'affilée : attends une minute.")
    try:
        got = await port.place_refresh(ident)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    if got is None:
        raise missing()
    return {"ok": True, "message": "Fiche relue.", **_fiche(got)}


# ── les événements (ADR 0259) ──


def _day(call: Call, name: str) -> date | None:
    raw = call.arg(name, limit=10).strip()
    if not raw:
        return None
    try:
        got = date.fromisoformat(raw)
    except ValueError:
        got = None
    if got is None or got.year not in c.YEARS:
        raise Denied(400, f"« {name} » : une date AAAA-MM-JJ.", {name: "AAAA-MM-JJ"})
    return got


def _themes(call: Call) -> frozenset[str]:
    known = [k for k, _ in THEMES]
    got = [t.strip() for t in call.arg("themes", limit=200).split(",") if t.strip()]
    if any(t not in known for t in got):
        raise Denied(400, f"« themes » : {', '.join(known)}.", {"themes": ", ".join(known)})
    return frozenset(got)


async def events(call: Call) -> dict[str, Any]:
    """Les événements à venir (DATAtourisme) : près d'un point (``near``, ou « ici » ; dans ``radius`` mètres) ou dans
    une zone (``bbox``), du ``start`` au ``end``, de ces thèmes, dont le nom dit ``q``, gratuits seulement ; avec ce que
    la base sait de l'endroit (``coverage``)."""
    port = _maps(call)
    text = " ".join(call.arg("q", limit=QUERY_MAX).split())
    near, here = _near(call)
    bbox_text = call.arg("bbox", limit=120)
    bbox = _bbox(bbox_text) if bbox_text.strip() else None
    if not text and near is None and bbox is None:
        raise Denied(400, "Cherche autour d'un point (near), dans une zone (bbox), ou un nom (q).")
    radius = _int(call, "radius", RADIUS, RADIUS_MIN, RADIUS_MAX)
    start, end = _day(call, "start"), _day(call, "end")
    if start is not None and end is not None and end < start:
        raise Denied(400, "« end » : après « start ».", {"end": "après start"})
    if start is not None and end is not None and (end - start).days > EVENTS_SPAN_MAX_DAYS:
        raise Denied(400, f"Une période d'au plus {EVENTS_SPAN_MAX_DAYS} jours.", {"end": "trop loin de start"})
    themes, free = _themes(call), call.flag("free")
    limit = _int(call, "limit", 30, 1, EVENTS_LIMIT_MAX)
    _map_read(call)
    try:
        hits = await port.events(near=near, bbox=bbox, radius_m=radius, start=start, end=end, themes=themes,
                                 text=text, free=free, limit=limit)
    except ValueError as exc:
        raise Denied(400, str(exc)[:300]) from None
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    out: dict[str, Any] = {"events": [_event_hit(e) for e in hits[:limit]],
                           "coverage": _coverage(port.tourism_coverage(near=near if bbox is None else None,
                                                                       bbox=bbox, radius_m=radius))}
    if here is not None:
        out["here"] = here
    return out


async def event_read(call: Call) -> dict[str, Any]:
    """La fiche d'un événement : ce qu'en dit une liste (``event``), son texte, toutes ses dates à venir, ses tarifs,
    ses contacts, où (son lieu, son adresse), ses photos, et ce qu'il faut citer (son auteur et sa date)."""
    ident = str(call.request.path_params["event"])
    if not EVENT_REF.match(ident):
        raise missing()
    port = _maps(call)
    _map_read(call)
    try:
        got: EventDetail | None = await port.event(ident)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    if got is None:
        raise missing()
    return {"event": _event_hit(got.hit), "description": got.description,
            "dates": [{"start": d.start, "end": d.end, "text": d.text, "days": list(d.days)} for d in got.dates],
            "more_dates": got.more_dates, "prices": got.prices, "contacts": _pairs(got.contacts),
            "address": got.address, "town": got.town, "venue": got.venue, "venue_place": got.venue_place,
            "author": got.author, "updated": got.updated, "url": got.url, "photos": [_photo(p) for p in got.photos],
            "merged": got.merged, "attribution": _credit(got.author, got.updated), "licence": TOURISM_LICENCE,
            "licence_url": TOURISM_LICENCE_URL}


# ── une photo relayée (ADR 0259) ──


async def photo(call: Call) -> Response:
    """Une photo relayée, par sa référence (``p:<hash>``) : ses octets et son type, gardés un jour par le navigateur.
    Une référence qu'aucune source ne connaît (ou dont les droits ont pris fin) : 404 ; rien ne part jamais vers une
    adresse donnée par un client — une référence n'en est pas une."""
    ref = str(call.request.path_params["ref"])
    if not PHOTO_REF.match(ref):
        raise missing()
    port = _maps(call)
    if not spend(call.api.photo_reads, call.me.account):
        raise Denied(429, "Trop de photos demandées d'affilée : attends une minute.")
    try:
        data, media = await port.photo(ref)
    except MapsNotFound:
        raise missing() from None
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    if media not in PHOTO_MEDIA:
        raise Denied(502, "La source de cette photo n'a pas rendu une image qu'on sert.")
    return Response(data, media_type=media, headers=PHOTO_HEADERS)


async def addresses(call: Call) -> dict[str, Any]:
    """Une adresse, à la Géoplateforme : seul ce texte part."""
    port = _maps(call, "addresses")
    text = " ".join(call.arg("q", limit=QUERY_MAX).split())
    if len(text) < 3:
        raise Denied(400, "« q » : trois caractères au moins.", {"q": "trois caractères au moins"})
    limit = _int(call, "limit", 5, 1, 10)
    call.outbound(addresses=True)
    try:
        hits = await port.addresses(text, limit=limit)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return {"places": [_hit(h) for h in hits[:limit]]}


async def itinerary(call: Call) -> dict[str, Any]:
    port = _maps(call, "routing")
    points, mode, avoid = _points(call), _mode(call), frozenset(_avoid(call))
    call.outbound()
    try:
        route = await port.route(points, mode=mode, avoid=avoid)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return _route(route)


def _json(text: str | None) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


async def look(call: Call) -> dict[str, Any]:
    """Ce qu'elle a cherché (``look`` : des lieux, un trajet, des événements) ou montré (``map``) pour toi, par son
    ``seq`` : la note d'un de ses messages. Oublié, ou pour quelqu'un d'autre : 404."""
    seq = int(call.request.path_params["seq"])
    if not 0 < seq < 2 ** 63:  # au-delà, la base ne lit rien : ce n'est pas une de ses notes
        raise missing()
    mind = call.kernel.mind
    rows = mind.store.get_events([seq])
    ev = mind.decode(rows[0]) if rows else None
    if ev is None or ev.type.name not in (c.LOOKED.name, c.SHOWN.name):
        raise missing()
    d = ev.data
    if trips_p.owner_key(call.frame.get, d.person) != call.me.person and d.handle != call.me.handle:
        raise missing()
    d = with_content(mind, ev).data
    if ev.type.name == c.LOOKED.name:
        if d.query.text is None or d.found.text is None:  # oublié
            raise missing()
        found = _json(d.found.text)
        if d.what == c.LOOK_ROUTE and isinstance(found, dict):
            route = {k: found.get(k) for k in ("mode", "distance_m", "duration_s", "shape")}
            route["avoid"] = [a for a in AVOIDS if a in (found.get("avoid") or [])]  # vide pour un regard d'avant
            points = found.get("points")
            return {"kind": c.NOTE_LOOK, "title": d.query.text, "what": d.what, "route": route, "trip": "",
                    "places": [x for x in points if isinstance(x, dict)] if isinstance(points, list) else [],
                    "at": millis(ev.at)}
        if d.what == c.LOOK_EVENTS:  # des événements (ADR 0259) : ce que le regard en a gardé
            return {"kind": c.NOTE_LOOK, "title": d.query.text, "what": d.what, "places": [],
                    "events": place_items(d.found.text), "route": None, "trip": "", "at": millis(ev.at)}
        return {"kind": c.NOTE_LOOK, "title": d.query.text, "what": d.what, "places": place_items(d.found.text),
                "route": None, "trip": "", "at": millis(ev.at)}
    if d.title.text is None or d.places.text is None:
        raise missing()
    line = _json(d.line.text) if d.line is not None else None
    route = {"mode": d.mode, **({k: line.get(k) for k in ("distance_m", "duration_s", "shape")}
                                if isinstance(line, dict) else {})} if d.route else None
    trip = trips_p.trip_of(_state(call), call.frame.get, call.me.person, d.trip) if d.trip else None
    return {"kind": c.NOTE_MAP, "title": d.title.text, "what": "", "places": place_items(d.places.text),
            "route": route, "trip": trip.id if trip is not None else "", "at": millis(ev.at)}


# ── le fond de carte (ADR 0193) ──
#: ce que le navigateur garde d'une tuile, d'une police ou d'une planche d'icônes : pour lui seul, un jour — sous une
#: adresse qui porte la version de la source (``?v=``, ou ``~<version>/`` pour les icônes : MapLibre ajoute leur fin
#: au chemin), qu'une autre source change ; les routes l'acceptent et l'ignorent
MAP_CACHE = "private, max-age=86400"
#: le début du segment de version d'une adresse d'icônes (« sprites/~1a2b3c4d5e6f/v4/light.json »)
VERSION_MARK = "~"
#: d'une carte réglée qui ne se lit pas, ce qu'une personne lit : ce qui ne va pas (un fichier du serveur, une archive
#: à refaire, un serveur de carte muet) ne se dit qu'à qui peut y remédier, comme ``NOT_READY``
MAP_NOT_READY = "La carte n'est pas encore prête sur ce serveur."


def _tiles(call: Call) -> Any:
    """Les tuiles du fond de carte (``MeApiBase.tiles``), et non le port ``maps`` des lieux et des itinéraires
    (``_maps``) : aucune réglée, 404."""
    tiles = call.api.tiles
    if tiles is None or tiles.config().source == NO_MAP:
        raise Denied(404, "Aucune carte n'est réglée : le plan dessiné.")
    return tiles


def _map_trouble(call: Call, reason: str) -> str:
    return reason if call.me.operator else MAP_NOT_READY


async def map_info(call: Call) -> dict[str, Any]:
    """Ce que le client sait de la carte : prête ou non (et pourquoi), ses tuiles, sa zone, ses polices et ses icônes
    — toutes servies par ce serveur, jamais une adresse du dehors."""
    tiles = call.api.tiles
    if tiles is None:
        return {"ready": False, "reason": NOT_PLUGGED}
    got = await tiles.info()
    reason = got.reason
    if reason and tiles.config().source != NO_MAP:  # rien de réglé n'est pas une panne : tout le monde le lit tel quel
        reason = _map_trouble(call, reason)
    base = PREFIX + BASE_MAP
    # la version de la source dans chaque adresse : le navigateur ne ressert pas, d'une carte remplacée (un autre
    # fichier, des images au lieu de vecteurs), ce qu'il gardait de l'autre
    query = f"?v={got.version}" if got.version else ""
    sprites = f"{base}/sprites/{VERSION_MARK}{got.version}/v4" if got.version else f"{base}/sprites/v4"
    return {"ready": got.ready, "reason": reason, "kind": got.kind, "minzoom": got.minzoom,
            "maxzoom": got.maxzoom, "bounds": list(got.bounds) if got.bounds is not None else None,
            "attribution": got.attribution, "tiles": f"{base}/tiles/{{z}}/{{x}}/{{y}}{query}",
            "glyphs": f"{base}/fonts/{{fontstack}}/{{range}}.pbf{query}" if got.fonts else None,
            "sprite": sprites if got.sprites else None}


async def map_tile(call: Call) -> Response:
    """Une tuile, telle que l'archive la garde (compressée : le navigateur l'ouvre) ; aucune là : 204, une tuile
    vide."""
    p = call.request.path_params
    try:
        tile = await _tiles(call).tile(p["z"], p["x"], p["y"])
    except MapUnavailable as exc:
        raise Denied(503, _map_trouble(call, str(exc))) from None
    if tile is None:
        return Response(status_code=204, headers={"Cache-Control": MAP_CACHE})
    headers = {"Cache-Control": MAP_CACHE, "X-Content-Type-Options": "nosniff"}
    if tile.encoding:
        headers["Content-Encoding"] = tile.encoding
    return Response(tile.data, media_type=tile.media, headers=headers)


def _asset(path: Any, media: str) -> Response:
    if path is None:
        raise missing()
    return FileResponse(path, media_type=media, headers={"Cache-Control": MAP_CACHE, "X-Content-Type-Options": "nosniff"})


async def map_font(call: Call) -> Response:
    """Une plage de glyphes d'une police de la carte : la première de la pile qui est là."""
    p = call.request.path_params
    tiles = _tiles(call)
    found = next((got for font in str(p["fontstack"]).split(",")[:4]
                  if (got := tiles.asset("fonts", f"{font.strip()}/{p['range']}")) is not None), None)
    return _asset(found, "application/x-protobuf")


async def map_sprite(call: Call) -> Response:
    """Une planche d'icônes de la carte (son image, ou ce qu'elle range où) ; le segment de version qui la précède
    (``~<version>/``) est accepté et ignoré."""
    rel = str(call.request.path_params["path"])
    if rel.startswith(VERSION_MARK):
        rel = rel.partition("/")[2]
    media = "application/json" if rel.endswith(".json") else "image/png" if rel.endswith(".png") else ""
    return _asset(_tiles(call).asset("sprites", rel) if media else None, media)


# ── tes voyages ──


def _trip(call: Call) -> Trip:
    ident = str(call.request.path_params["trip"])
    trip = trips_p.trip_of(_state(call), call.frame.get, call.me.person, ident) if _DIGITS.match(ident) else None
    if trip is None:
        raise missing()
    return trip


def _refs(trip: Trip) -> list[str]:
    return [trip.title_ref, *(r for s in trip.stops for r in (s.name_ref, s.coords_ref, s.kind_ref, s.note_ref))]


def _start(trip: Trip) -> date | None:
    try:
        return date.fromisoformat(trip.start) if trip.start else None
    except ValueError:
        return None


def _stop(stop: Stop, texts: dict[str, str]) -> dict[str, Any]:
    at = geo.parse_coords(texts.get(stop.coords_ref))
    return {"id": stop.id, "name": texts.get(stop.name_ref, ""), "kind": texts.get(stop.kind_ref, ""),
            "lat": at[0] if at else None, "lon": at[1] if at else None, "note": texts.get(stop.note_ref, ""),
            "by": HERS if stop.by == c.BY_HER else YOURS}


async def trips_list(call: Call) -> dict[str, Any]:
    mine = trips_p.trips_of(_state(call), call.frame.get, call.me.person)
    texts = texts_of(call, [t.title_ref for t in mine])
    return {"trips": [{"id": t.id, "title": texts.get(t.title_ref, ""), "start": t.start, "mode": t.mode,
                       "avoid": list(t.avoid), "days": len(days_of(t)), "stops": len(t.stops),
                       "updated": millis(t.updated_at), "mika": t.mika_touched} for t in mine]}


async def trip_read(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    texts = texts_of(call, _refs(trip))
    first = _start(trip)
    return {"id": trip.id, "title": texts.get(trip.title_ref, ""), "start": trip.start, "mode": trip.mode,
            "avoid": list(trip.avoid), "updated": millis(trip.updated_at), "mika": trip.mika_touched,
            "days": [{"n": n, "date": (first + timedelta(days=n - 1)).isoformat() if first else "",
                      "stops": [_stop(s, texts) for s in stops]} for n, stops in days_of(trip)]}


def _created(call: Call, outcome: Outcome, kind: EventType[Any]) -> str:
    """Ce que l'action a créé (son ``seq``) — retrouvé par sa clé d'envoi quand l'envoi est redit."""
    if outcome.seqs:
        return str(outcome.seqs[0])
    nonce = call.nonce()
    seq = call.kernel.mind.store.find_dedupe(kind.name, f"op:{nonce}:0") if nonce else None
    return str(seq) if seq is not None else ""


def _settings(call: Call) -> dict[str, Any]:
    """Ce qu'un voyage reçoit de réglé : seulement ce que le corps nomme (le reste ne change pas)."""
    values: dict[str, Any] = {}
    if "title" in call.data:
        values["title"] = call.arg("title", limit=c.TITLE_MAX)
    if "start" in call.data:
        values["start"] = call.arg("start", limit=10)
    if "mode" in call.data:
        values["mode"] = _mode(call)
    if "avoid" in call.data:
        values["avoid"] = _avoid(call)
    return values


async def trip_create(call: Call) -> dict[str, Any]:
    got = await call.act("trips.creer", form(**{"title": "", **_settings(call)}))
    return {**done(got), "id": _created(call, got, c.CREATED)}


async def trip_change(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    values = _settings(call)
    if "title" in values and not values["title"].strip():
        raise Denied(400, "Un voyage a un titre.", {"title": "un titre"})
    if not values:
        raise Denied(400, "Rien à changer : title, start, mode ou avoid.")
    return done(await call.act("trips.modifier", form(fixed={"trip": trip.id}, **values)))


async def trip_remove(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    return done(await call.act("trips.supprimer", form(fixed={"trip": trip.id})))


def _number(call: Call, name: str, bound: float) -> float:
    got = call.data.get(name)
    if isinstance(got, bool) or not isinstance(got, int | float) or not math.isfinite(got) or abs(got) > bound:
        raise Denied(400, f"« {name} » : un nombre, de -{bound:g} à {bound:g}.", {name: f"de -{bound:g} à {bound:g}"})
    return float(got)


async def stop_add(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    values = {"name": call.arg("name", limit=c.NAME_MAX), "lat": _number(call, "lat", 90),
              "lon": _number(call, "lon", 180), "kind": call.arg("kind", limit=c.KIND_MAX),
              "day": _int(call, "day", 1, 1, c.DAYS_MAX), "index": _int(call, "index", -1, -1, c.STOPS_MAX),
              "note": call.arg("note", limit=c.NOTE_MAX)}
    got = await call.act("trips.ajouter_arret", form(fixed={"trip": trip.id}, **values))
    return {**done(got), "id": _created(call, got, c.STOP_ADDED)}


def _stop_of(call: Call, trip: Trip) -> Stop:
    ident = str(call.request.path_params["stop"])
    found = next((s for s in trip.stops if s.id == ident), None)
    if found is None:
        raise missing()
    return found


async def stop_change(call: Call) -> dict[str, Any]:
    """Déplacer un arrêt (``day``, ``index``), le noter (``note``), ou les deux."""
    trip = _trip(call)
    stop = _stop_of(call, trip)
    moving, noting = "day" in call.data or "index" in call.data, "note" in call.data
    if not moving and not noting:
        raise Denied(400, "« day » et « index » pour le déplacer, « note » pour le noter.")
    fixed = {"trip": trip.id, "stop": stop.id}
    # tout se lit avant le premier geste : un paramètre refusé ne laisse rien à moitié fait
    move = form(fixed=fixed, day=_int(call, "day", stop.day, 1, c.DAYS_MAX),
                index=_int(call, "index", -1, -1, c.STOPS_MAX)) if moving else None
    note = form(fixed=fixed, note=call.arg("note", limit=c.NOTE_MAX)) if noting else None
    answer: dict[str, Any] = {}
    if move is not None:
        answer = done(await call.act("trips.deplacer_arret", move))
    if note is not None:
        nonce = call.nonce()
        # deux gestes d'un même envoi : chacun sa clé, sinon le second passerait pour le premier redit ; audité comme
        # ``call.act`` le fait, depuis son espace
        answer = done(await perform(call.kernel, "trips.noter_arret", note, by=call.me.handle, via=SPACE,
                                    nonce=f"{nonce}:note" if nonce and move is not None else nonce))
    return answer


async def stop_remove(call: Call) -> dict[str, Any]:
    trip = _trip(call)
    stop = _stop_of(call, trip)
    return done(await call.act("trips.retirer_arret", form(fixed={"trip": trip.id, "stop": stop.id})))


def _stop_points(call: Call, trip: Trip) -> list[Any]:
    texts = texts_of(call, _refs(trip))
    return [stop_point(s, texts) for s in trip.stops]


async def trip_route(call: Call) -> dict[str, Any]:
    """Les tronçons d'un arrêt au suivant, rangés par le jour où l'on arrive."""
    trip = _trip(call)
    port = _maps(call, "routing")
    points = _stop_points(call, trip)
    call.outbound()
    route: RouteResult | None = None
    arriving: dict[str, tuple[str, RouteLeg]] = {}
    if len(points) >= 2 and all(p is not None for p in points):
        try:
            route = await geo.chain(port, [p.at for p in points], mode=trip.mode, avoid=frozenset(trip.avoid))
        except MapsUnavailable as exc:
            raise _unavailable(exc) from None
        arriving = {trip.stops[i + 1].id: (trip.stops[i].id, leg)
                    for i, leg in enumerate(route.legs[:len(trip.stops) - 1])}
    days = []
    for n, stops in days_of(trip):
        legs = [{"from": arriving[s.id][0], "to": s.id, **_leg(arriving[s.id][1])} for s in stops if s.id in arriving]
        days.append({"n": n, "distance_m": sum(x["distance_m"] for x in legs),
                     "duration_s": sum(x["duration_s"] for x in legs), "legs": legs})
    return {"days": days, "distance_m": route.distance_m if route else 0, "duration_s": route.duration_s if route else 0,
            "has_toll": bool(route and route.has_toll), "has_highway": bool(route and route.has_highway),
            "has_ferry": bool(route and route.has_ferry),
            "provider": route.provider if route is not None else port.routing_provider()}


async def trip_order(call: Call) -> dict[str, Any]:
    """L'ordre optimisé d'un jour, appliqué : son premier et son dernier arrêt restent à leur place."""
    trip = _trip(call)
    day = _int(call, "day", 1, 1, c.DAYS_MAX)
    stops = [s for s in trip.stops if s.day == day]
    if len(stops) < 3:
        return {"ok": True, "message": "Rien à réordonner : il faut trois arrêts ce jour-là.", "deduped": False,
                "order": [s.id for s in stops]}
    if len(stops) > ROUTE_POINTS_MAX:
        # le serveur d'itinéraires ne range pas plus de points d'un coup : refusé en mots, avant de le demander
        raise Denied(400, f"L'ordre se calcule pour {ROUTE_POINTS_MAX} arrêts au plus dans un jour : ce jour en a "
                          f"{len(stops)}. Répartis-les sur deux jours.", {"day": f"{ROUTE_POINTS_MAX} arrêts au plus"})
    port = _maps(call, "routing")
    call.outbound()
    texts = texts_of(call, _refs(trip))
    points = [stop_point(s, texts) for s in stops]
    if any(p is None for p in points):
        raise Denied(409, "Un arrêt de ce jour n'a plus ses coordonnées.")
    try:
        got = await port.optimize([p.at for p in points if p is not None], mode=trip.mode)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    order = [stops[i].id for i in _order(got, len(stops))]
    outcome = await call.act("trips.ordonner_jour", form(fixed={"trip": trip.id}, day=day, order=order))
    return {**done(outcome), "order": order}


async def trip_along(call: Call) -> dict[str, Any]:
    """Les lieux le long du trajet (d'un jour, ou de tout le voyage : ``day`` 0) ; ``route`` faux : à vol d'oiseau."""
    trip = _trip(call)
    port = _maps(call, "places")
    category = _category(call, port)
    day = _int(call, "day", 0, 0, c.DAYS_MAX)
    corridor = _int(call, "corridor", CORRIDOR, CORRIDOR_MIN, CORRIDOR_MAX)
    limit = _int(call, "limit", 20, 1, LIMIT_MAX)
    points = along_points(trip, texts_of(call, _refs(trip)), day)
    if len(points) < 2:
        return {"places": [], "route": False}
    if port.routing_ready():
        call.outbound()
    line, routed = await geo.follow(port, [p.at for p in points], mode=trip.mode, avoid=frozenset(trip.avoid))
    try:
        hits = await port.along(line, corridor_m=corridor, category=category, limit=limit)
    except MapsUnavailable as exc:
        raise _unavailable(exc) from None
    return {"places": [_hit(h) for h in hits[:limit]], "route": routed}


async def gpx_document(port: Any, trip: Trip, content: Callable[[list[str]], Mapping[str, str]],
                       outbound: Callable[[], None]) -> str:
    """Le voyage en GPX (``adapters.maps.gpx``) : ses arrêts, et le tracé quand les itinéraires le calculent (sinon,
    ou en panne, ses arrêts seuls). ``content`` lit ses textes au magasin ; ``outbound``, appelé avant de joindre le
    serveur d'itinéraires, y compte la demande dans la borne du compte qui la fait (``OUTBOUND``) et lève au-delà —
    jamais facultatif : la console sert le même document, sur la fiche de la personne, dans la même borne (ADR 0204)."""
    texts = content(_refs(trip))
    stops = [(texts.get(s.name_ref, ""), p.lat, p.lon) for s in trip.stops if (p := stop_point(s, texts)) is not None]
    track: list[geo.Point] = []
    if port is not None and port.routing_ready() and len(stops) >= 2:
        outbound()
        try:
            track = await geo.line_of_async(await geo.chain(port, [(lat, lon) for _, lat, lon in stops],
                                                            mode=trip.mode, avoid=frozenset(trip.avoid)))
        except MapsUnavailable:
            track = []  # les arrêts seuls : le GPX reste utile
    # un long tracé s'écrit hors de la boucle d'événements (des centaines de milliers de points sur un long voyage)
    title = texts.get(trip.title_ref, "")
    return gpx(title, stops, track) if len(track) <= geo.LINE_KEPT * 4 else \
        await asyncio.to_thread(gpx, title, stops, track)


def gpx_response(trip: Trip, body: str) -> Response:
    """Le GPX d'un voyage, en pièce jointe ``voyage-<id>.gpx``, jamais gardé en cache."""
    return Response(body, media_type="application/gpx+xml",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": f'attachment; filename="voyage-{trip.id}.gpx"'})


async def trip_gpx(call: Call) -> Response:
    """Le voyage en GPX : ses arrêts, et le tracé quand les itinéraires le calculent."""
    trip = _trip(call)
    return gpx_response(trip, await gpx_document(call.port("maps"), trip, lambda refs: texts_of(call, refs),
                                                 call.outbound))


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    trip, stop = TRIPS_PATH + "/{trip}", TRIPS_PATH + "/{trip}/arrets/{stop}"
    return [r(MAP_PATH, info), r(MAP_PATH + "/lieux", places), r(MAP_PATH + "/adresses", addresses),
            r(MAP_PATH + "/itineraire", itinerary), r(MAP_PATH + "/regards/{seq:int}", look),
            r(PLACE_PATH + "/{place}", place_read), r(PLACE_PATH + "/{place}/actualiser", place_refresh, write=True),
            r(EVENTS_PATH, events), r(EVENT_PATH + "/{event}", event_read),
            r(PHOTO_PATH + "/{ref}", photo, raw=True),
            r(BASE_MAP, map_info), r(BASE_MAP + "/tiles/{z:int}/{x:int}/{y:int}", map_tile, raw=True),
            r(BASE_MAP + "/fonts/{fontstack}/{range}", map_font, raw=True),
            r(BASE_MAP + "/sprites/{path:path}", map_sprite, raw=True),
            r(TRIPS_PATH, trips_list), r(TRIPS_PATH, trip_create, write=True),
            r(trip, trip_read), r(trip, trip_change, write=True), r(trip + "/supprimer", trip_remove, write=True),
            r(trip + "/arrets", stop_add, write=True), r(stop, stop_change, write=True),
            r(stop + "/retirer", stop_remove, write=True), r(trip + "/trajet", trip_route),
            r(trip + "/ordre", trip_order, write=True), r(trip + "/sur-la-route", trip_along),
            r(trip + "/gpx", trip_gpx, raw=True)]
