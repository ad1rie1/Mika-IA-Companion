"""Le port ``maps`` du noyau (ADR 0194, ``mika.ports.maps.MapsPort``) : les lieux de l'index local, les adresses de la
Géoplateforme, les itinéraires de Valhalla, les données touristiques et les événements de DATAtourisme — ce que
l'écran Carte montre (l'API par personne) et ce dont elle se sert en parlant (le plugin des voyages). Les réglages
sont relus à chaque usage : la console les change sans redémarrer.

Les erreurs : ``MapsUnavailable`` dit en mots ce qui manque (rien de réglé, un serveur qui ne répond pas, aucun
chemin) ; ``ValueError``, des arguments hors des bornes du port (un mode inconnu, un point hors du monde, un filtre
inconnu) — les appelants les vérifient avant.

La fiche d'un lieu (``place``, ADR 0244) : sa partie OpenStreetMap vient de l'index ; sa partie DATAtourisme et les
événements proches, de la base des données touristiques (ADR 0245), un cache par cases — la case du lieu jamais vue se
lit en direct, celles autour des personnes chaque soir (``warm.Warmer``) ; sa partie « avis », du cache de Google
Places (ADR 0250, 0256, ``reviews_cells``) — ce qui lui manque ou est vieux se lit en direct, et ce que Google dit de
la fiche complète ce qu'OpenStreetMap ne dit pas, jamais à sa place. Un lieu des données touristiques qu'OpenStreetMap
n'a pas se trouve avec les autres (``t:<uuid>``), sans jamais doubler un lieu de l'index ; un lieu de Google ne se
trouve jamais seul : il prête sa note, ses avis, son prix et sa photo au lieu qui est le sien. Une liste (``search``,
``around``) ne lit que les caches : rien n'en sort.

Les photos (``photo``) passent par le relais (``photos.PhotoRelay``), qui n'en connaît que les sources branchées : la
base des données touristiques et le cache des avis. Le limiteur (``quota.Limiter``, ses compteurs dans
``cartes/quotas.db``) et le réchauffage du soir (``warmer``) se partagent de même : DATAtourisme et Google y ont
chacun leurs instances et leur source."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from mika.adapters.maps.config import (
    FOSSGIS,
    KEY_ENV,
    MAPS_DIR,
    NO_ROUTING,
    PlacesConfig,
    ReviewsConfig,
    RoutingConfig,
    TourismConfig,
    WarmConfig,
    reviews_key,
    tourism_key,
)
from mika.adapters.maps.datatourisme import EVENTS, PLACES, DataTourismeClient, tourism_limits
from mika.adapters.maps.geocode import Geocoder
from mika.adapters.maps.google_places import (
    FOR_CATEGORY,
    GOOGLE_MONTH,
    PRICES_CHECKED,
    SKUS,
    PlacesClient,
    reviews_limits,
    sku_limits,
)
from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.pace import Pace
from mika.adapters.maps.photos import PhotoRelay
from mika.adapters.maps.places import LABELS, LIMIT_MAX, Places, _box, _when_fr, _words, utc_now
from mika.adapters.maps.quota import QUOTAS_FILE, Limiter, Limits, QuotaStore, counting_sent
from mika.adapters.maps.reviews import Reviews
from mika.adapters.maps.reviews_cells import ReviewsCells
from mika.adapters.maps.routing import Router
from mika.adapters.maps.tourism import Tourism, match_stamp, merge_places, paris_today
from mika.adapters.maps.tourism_cells import TourismCells
from mika.adapters.maps.tourism_sync import KIND_FR, TourismSync
from mika.adapters.maps.warm import Warmer
from mika.ports.maps import (
    EVENTS_LIMIT_MAX,
    EVENTS_SPAN_MAX_DAYS,
    SORTS,
    THEMES,
    EventDetail,
    EventHit,
    MapsUnavailable,
    PlaceDetail,
    PlaceHit,
    PlaceRefresh,
    ReviewsCoverage,
    RouteResult,
    TourismCoverage,
)

#: les données touristiques et les avis sans réglage (des tests, une commande) : aucune clé, rien ne part
_NO_TOURISM = TourismConfig()
_NO_REVIEWS = ReviewsConfig()
_WARM = WarmConfig()
_THEME_BITS = {theme: 1 << k for k, (theme, _label) in enumerate(THEMES)}
#: les lieux des données touristiques autour d'un point, sans texte ni zone : à moins de tant de mètres (sans quoi on
#: lirait toute la base pour trier par la distance)
TOURISM_NEAR_M = 25_000
#: un tri par note autour d'un point, sans zone ni rayon : les mieux notés du cache des avis à moins de tant de mètres
#: rejoignent les plus proches
RATED_NEAR_M = 2_000
#: « Actualiser » (ADR 0269) : une source relue il y a moins de tant ne repart pas (ni Google, ni DATAtourisme) — un
#: clic répété, un client qui boucle ne refont pas l'appel compté
REFRESH_AFTER = timedelta(minutes=10)
#: … et, pour tout ce serveur, au plus tant d'« Actualiser » qui partent sur 24 heures glissantes : un compte ne vide
#: pas le mois des fiches de Google (mille offertes : vingt par jour en prennent six cent vingt au plus)
REFRESHES_PER_DAY = 20
REFRESHED = "Fiche relue."
NOTHING_TO_READ = "Rien à relire pour ce lieu : ni avis à aller chercher chez Google, ni fiche de l'office de tourisme."
NOTHING_SET = ("Rien ne peut se relire ici : ni les avis (Google) ni les données touristiques (DATAtourisme) ne sont "
               "réglés.")


def _rated(hits: list[PlaceHit], min_rating: float | None, sort: str) -> list[PlaceHit]:
    """La note (ADR 0250) : ``min_rating`` écarte les lieux sans note et ceux notés en dessous ; ``sort="rating"`` met
    les mieux notés d'abord, puis ceux qui ont le plus d'avis (à égalité, l'ordre d'avant), ceux sans note à la fin."""
    if sort not in SORTS:
        raise ValueError(f"un ordre inconnu : {sort} ({', '.join(SORTS)})")
    if min_rating is not None:
        if not 0.0 <= float(min_rating) <= 5.0:
            raise ValueError("une note de 0 à 5")
        hits = [h for h in hits if h.rating is not None and h.rating >= min_rating]
    if sort == "rating":
        hits = sorted(hits, key=lambda h: (h.rating is None, -(h.rating or 0.0), -(h.reviews or 0)))
    return hits


def _events_radius(radius_m: float) -> float:
    """Le rayon d'une recherche d'événements, ramené à ses bornes (de 100 m à 200 km)."""
    return max(100.0, min(200_000.0, float(radius_m)))


def _keys(hit: PlaceHit) -> list[str]:
    """Les identifiants d'un lieu sous lesquels le cache des avis le rapproche : le durable d'abord."""
    return [k for k in (hit.osm, hit.id) if k]


def _count_fr(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _usd_fr(amount: float) -> str:
    """« 1,23 $ »."""
    return f"{amount:,.2f} $".replace(",", " ").replace(".", ",")


def _price_fr(price: float) -> str:
    """« 35 $ » : le prix des mille, sans décimales quand il n'en a pas."""
    return (f"{price:g} $" if price == int(price) else f"{price:.2f} $").replace(".", ",")


def _fresh_fr(age: timedelta) -> str:
    """« Relue il y a 4 min : elle est à jour. » — ce que dit « Actualiser » d'une fiche relue tout à l'heure."""
    minutes = int(age.total_seconds() // 60)
    when = "à l'instant" if minutes < 1 else f"il y a {minutes} min"
    return f"Relue {when} : elle est à jour (une fiche se relit au plus une fois toutes les " \
           f"{int(REFRESH_AFTER.total_seconds() // 60)} minutes)."


def _at_fr(iso: str) -> str:
    """« le 17 novembre 2026 à 04:12 » (heure de Paris)."""
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PARIS)
    except ValueError:
        return iso or "jamais"
    return f"{_when_fr(at.isoformat())} à {at:%H:%M}"


def _with_photo(hit: PlaceHit, ref: str, *, credit: str, credit_url: str, licence: str = "",
                source: str = "google") -> PlaceHit:
    """Un lieu et la première photo des avis (Google), avec ce qu'il faut en citer (ADR 0269) — sauf s'il a déjà la
    sienne : elle garde alors son crédit."""
    if hit.photo or not ref:
        return hit
    return replace(hit, photo=ref, photo_source=source, photo_credit=credit, photo_credit_url=credit_url,
                   photo_licence=licence)


class MapsDesk:
    """Les lieux, les adresses, les itinéraires, les données touristiques et les avis, réglés dans la console
    (Réglages › Carte et téléphone : « Lieux et adresses », « Itinéraires », « Données touristiques (DATAtourisme) »,
    « Avis (Google) », « Réchauffage des caches »)."""

    def __init__(self, data: Path, places: Callable[[], PlacesConfig], routing: Callable[[], RoutingConfig], *,
                 tourism: Callable[[], TourismConfig] = lambda: _NO_TOURISM,
                 reviews: Callable[[], ReviewsConfig] = lambda: _NO_REVIEWS,
                 warm: Callable[[], WarmConfig] = lambda: _WARM,
                 warm_points: Callable[[], Sequence[tuple[float, float]]] = lambda: (),
                 transport: httpx.AsyncBaseTransport | None = None, routing_pace: Pace | None = None,
                 address_pace: Pace | None = None, now: Callable[[], float] = time.monotonic,
                 clock: Callable[[], datetime] = utc_now, quota_now: Callable[[], float] = time.time,
                 quota_sleep: Callable[[float], Awaitable[object]] = asyncio.sleep, tourism_api: str = "",
                 google_api: str = "") -> None:
        self.clock = clock
        self.places = Places(data, places, now=clock)
        self.geocoder = Geocoder(places, transport=transport, pace=address_pace)
        self.router = Router(routing, transport=transport, pace=routing_pace, now=now)
        self.tourism_config = tourism
        self.tourism = Tourism(data, now=clock)
        #: les compteurs des services de la carte, partagés (le serveur, la commande ; Google aussi)
        self.quotas = QuotaStore(data / QUOTAS_FILE)
        self.tourism_limiter = Limiter("datatourisme", self.quotas, lambda: tourism_limits(tourism()),
                                       label="DATAtourisme", now=quota_now, sleep=quota_sleep)
        self.datatourisme = DataTourismeClient(tourism, self.tourism_limiter, transport=transport,
                                               **({"base": tourism_api} if tourism_api else {}))
        self.cells = TourismCells(self.tourism, tourism, self.datatourisme, index=self.places_index, clock=clock)
        self.tourism_sync = TourismSync(self.tourism, tourism, self.datatourisme, index=self.places_index,
                                        clock=clock)
        # les avis (Google Places, ADR 0256) : le limiteur de tous ses appels (par seconde, sur 24 heures), celui du
        # mois de chaque SKU (recherches, fiches, photos : le mois de Google), le client, le cache par cases
        self.reviews_config = reviews
        self.reviews_limiter = Limiter("google", self.quotas, lambda: reviews_limits(reviews()), label="Google",
                                       unit="appels", now=quota_now, sleep=quota_sleep)
        self.sku_limiters = {sku.service: Limiter(sku.service, self.quotas, lambda sku=sku: sku_limits(reviews(), sku),
                                                  label=f"Google ({sku.label})", unit=sku.unit, now=quota_now,
                                                  sleep=quota_sleep, month_zone=GOOGLE_MONTH) for sku in SKUS}
        self.google = PlacesClient(reviews, self.reviews_limiter, self.sku_limiters, transport=transport,
                                   **({"base": google_api} if google_api else {}))
        self.reviews = Reviews(data)
        self.review_cells = ReviewsCells(self.reviews, reviews, self.google, index=self.places_index,
                                         tourism=lambda: self.tourism.path, clock=clock)
        #: le réchauffage du soir, partagé par les caches de la carte (DATAtourisme, Google)
        self.warmer = Warmer(data, warm, points=warm_points, resolve=self._town,
                             sources=(self.cells, self.review_cells), clock=clock)
        self.photos = PhotoRelay(data / MAPS_DIR / "photos", sources=(self.tourism, self.review_cells),
                                 transport=transport, today=lambda: paris_today(self.clock()))
        #: « Actualiser », pour tout ce serveur (``REFRESHES_PER_DAY``), dans la base des compteurs
        self.refreshes = Limiter("actualiser", self.quotas, lambda: Limits(per_day=REFRESHES_PER_DAY),
                                 label="ce serveur (« Actualiser »)", unit="fiches", now=quota_now, sleep=quota_sleep)

    async def _town(self, name: str) -> tuple[float, float] | None:
        """Un point fixe du réchauffage nommé (« Lille ») : la ville de l'index des lieux."""
        if not self.places.ready():
            return None
        hits = await self.places.search(name, category="villes", limit=1)
        return (hits[0].lat, hits[0].lon) if hits else None

    def places_index(self) -> tuple[Path, str] | None:
        """L'index des lieux, s'il est prêt : son chemin et ce que le rapprochement suit — quand il a été construit, et
        la règle du rapprochement (``tourism.match_stamp``) : l'un ou l'autre changé, tout se rejuge."""
        info = self.places.info()
        return (self.places.data / self.places.config().index, match_stamp(info.built)) if info.ready else None

    def start(self) -> None:
        """Les travaux de fond (le serveur) : le réchauffage du soir, la synchronisation des départements tenus en
        entier (et le rapprochement quand l'index des lieux change), le préchargement des avis."""
        self.tourism_sync.start()
        self.warmer.start()
        self.review_cells.start()

    async def stop(self) -> None:
        await self.review_cells.stop()
        await self.warmer.stop()
        await self.tourism_sync.stop()

    async def close(self) -> None:
        await self.geocoder.close()
        await self.router.close()
        await self.datatourisme.close()
        await self.google.close()
        await self.photos.close()

    # ── le port ──
    def categories(self) -> tuple[tuple[str, str], ...]:
        return LABELS

    def places_ready(self) -> bool:
        return self.places.ready()

    def addresses_ready(self) -> bool:
        return self.geocoder.ready()

    def routing_ready(self) -> bool:
        return self.router.ready()

    def routing_provider(self) -> str:
        return self.router.provider()

    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     bbox: tuple[float, float, float, float] | None = None, category: str = "",
                     limit: int = 20, open_now: bool = False, features: frozenset[str] = frozenset(),
                     cuisine: str = "", min_rating: float | None = None, sort: str = "distance") -> list[PlaceHit]:
        _rated([], min_rating, sort)  # les bornes, avant de chercher
        limit = max(1, min(LIMIT_MAX, int(limit)))
        rated = min_rating is not None or sort == "rating"
        # par la note : plus de candidats, qu'on note puis qu'on coupe
        asked = LIMIT_MAX if rated else limit
        hits = await self.places.search(text, near=near, bbox=bbox, category=category, limit=asked,
                                        open_now=open_now, features=features, cuisine=cuisine)
        words = _words(text or "")
        if not (open_now or features or cuisine.strip()):  # un lieu DATAtourisme ne sait rien de ces filtres
            radius = TOURISM_NEAR_M if near is not None and bbox is None and not words else None
            more = await self.tourism.places(words, near=near, bbox=bbox, radius_m=radius, category=category,
                                             limit=asked)
            hits = merge_places(hits, more, near=near is not None, limit=asked)
        if rated and not words and (bbox is not None or near is not None):
            area = bbox if bbox is not None else _box(near[0], near[1], RATED_NEAR_M)  # type: ignore[index]
            hits = await self._best_rated(hits, area, near=near, radius_m=None if bbox is not None else
                                          RATED_NEAR_M, category=category, min_rating=min_rating,
                                          open_now=open_now, features=features, cuisine=cuisine)
        return _rated(await self._noted(hits), min_rating, sort)[:limit]

    async def _noted(self, hits: list[PlaceHit]) -> list[PlaceHit]:
        """Les lieux d'une liste, avec ce qu'en dit le cache des avis quand ils y sont rapprochés : leur note, le
        nombre de leurs avis, leur prix, leur première photo. Rien ne sort."""
        if not hits:
            return hits
        noted = await self.reviews.noted([k for h in hits for k in _keys(h)])
        if not noted:
            return hits
        out = []
        for hit in hits:
            found = next((noted[k] for k in _keys(hit) if k in noted), None)
            if found is None:
                out.append(hit)
                continue
            out.append(replace(_with_photo(hit, found.photo, credit=found.credit, credit_url=found.credit_url),
                               rating=found.rating, reviews=found.count, price=found.price or hit.price))
        return out

    async def _best_rated(self, hits: list[PlaceHit], area: tuple[float, float, float, float], *,
                          near: tuple[float, float] | None, radius_m: float | None, category: str,
                          min_rating: float | None, open_now: bool, features: frozenset[str],
                          cuisine: str) -> list[PlaceHit]:
        """Une liste triée ou filtrée par la note : les lieux les mieux notés du cache dans la zone (``area``, et à
        moins de ``radius_m`` du point) la rejoignent, aux mêmes filtres — le meilleur ne manque pas parce qu'il n'est
        pas parmi les plus proches."""
        sorts = [FOR_CATEGORY[category]] if category in FOR_CATEGORY else []
        if category and not sorts:
            return hits  # une catégorie dont on ne lit pas les avis
        twins = await self.reviews.rated_near(area, min_rating=min_rating, categories=sorts, limit=LIMIT_MAX)
        known = {k for h in hits for k in _keys(h)}
        wanted = [t for t in twins if t not in known and not t.startswith("t:")]
        if not wanted:
            return hits
        more = await self.places.hits(wanted, near=near, category=category, open_now=open_now, features=features,
                                      cuisine=cuisine)
        if radius_m is not None:
            more = [h for h in more if h.distance_m is not None and h.distance_m <= radius_m]
        return [*hits, *more]

    async def place(self, place_id: str) -> PlaceDetail | None:
        found = await self._resolve(place_id)
        if found is None:
            return None
        detail, keys = found
        return await self._reviewed(detail, keys, refresh=False)

    async def _resolve(self, place_id: str) -> tuple[PlaceDetail, list[str]] | None:
        """La fiche d'un lieu sans sa partie « avis », et les identifiants sous lesquels le cache des avis le
        rapproche (son objet d'OpenStreetMap, sa ligne, sa fiche DATAtourisme)."""
        key = str(place_id or "").strip()
        if key.startswith("t:"):
            found = await self.tourism.place(key[2:])
            if found is None:
                return None
            hit, facts, twin = found
            if twin:  # rapproché depuis : la fiche de son pendant d'OpenStreetMap
                resolved = await self._resolve(twin)
                if resolved is not None:
                    return resolved
            events = await self.tourism.near_events(hit.lat, hit.lon, ())
            return PlaceDetail(hit, tourism=facts, events=tuple(events)), [hit.id]
        detail = await self.places.place(key)
        if detail is None:
            return None
        # sa case jamais vue : lue en direct, si le quota le permet (la case, jamais le lieu ni la personne)
        await self.cells.ensure([self.cells.cell(detail.hit.lat, detail.hit.lon)], (PLACES, EVENTS))
        ids = _keys(detail.hit)
        facts, uuid = await self.tourism.facts_for(ids)
        events = await self.tourism.near_events(detail.hit.lat, detail.hit.lon, ids)
        return replace(detail, tourism=facts, events=tuple(events)), [*ids, *([f"t:{uuid}"] if uuid else [])]

    async def _reviewed(self, detail: PlaceDetail, keys: list[str], *, refresh: bool) -> PlaceDetail:
        """La fiche et sa partie « avis » (Google) : ce qui manque ou est vieux lu en direct ; le lieu porte alors sa
        note comme dans une liste. Ce que Google dit de la fiche (ce qu'il sert, ses horaires) ne garde que ce
        qu'OpenStreetMap ne dit pas : il le complète, jamais à sa place."""
        hit = detail.hit
        facts = await self.review_cells.facts(hit.category, hit.kind, hit.lat, hit.lon, keys, refresh=refresh)
        if facts is None:
            return detail
        if facts.facts and detail.osm is not None:
            said = {label for label, _value in detail.osm.facts}
            facts = replace(facts, facts=tuple(f for f in facts.facts if f[0] not in said))
        if facts.id:
            first = facts.photos[0] if facts.photos else None
            if first is not None:
                hit = _with_photo(hit, first.ref, credit=first.credit, credit_url=first.credit_url,
                                  licence=first.licence, source=first.source or "google")
            hit = replace(hit, rating=facts.rating, reviews=facts.count, price=facts.price or hit.price)
        return replace(detail, hit=hit, reviews=facts)

    async def place_refresh(self, place_id: str) -> PlaceRefresh | None:
        """« Actualiser » : chaque source qui a de quoi relire ce lieu, et ne l'a pas fait depuis ``REFRESH_AFTER`` —
        sous la borne de tout le serveur (``refreshes``), dont un tour ne compte que si un appel est vraiment parti
        (retenu par le mois de Google, un recul, le quota de l'heure de DATAtourisme : il est rendu, et le refus dit
        cette cause) ; ce qui n'a pas pu se relire lève, en mots (ce qui l'a pu est gardé) ; aucune source réglée :
        ``NOTHING_SET``."""
        found = await self._resolve(place_id)
        if found is None:
            return None
        detail, keys = found
        now = self.clock()
        uuid = next((k[2:] for k in keys if k.startswith("t:")), "")
        latest: list[datetime] = []
        tourism_due = google_due = False
        if uuid and self.datatourisme.ready():
            synced = await self.tourism.synced_at(uuid)
            tourism_due = synced is None or now - synced >= REFRESH_AFTER
            latest += [] if tourism_due or synced is None else [synced]
        if self.google.ready():
            reads, read = await self.review_cells.read_at(detail.hit.category, detail.hit.kind, keys)
            google_due = reads and (read is None or now - read >= REFRESH_AFTER)
            latest += [read] if reads and not google_due and read is not None else []
        if not tourism_due and not google_due:
            if not self.google.ready() and not self.datatourisme.ready():
                raise MapsUnavailable(NOTHING_SET)
            fiche = await self.place(place_id)
            if fiche is None:
                return None
            return PlaceRefresh(fiche, _fresh_fr(now - min(latest)) if latest else NOTHING_TO_READ)
        turn = await self.refreshes.take(wait_max=0.0)  # tout ce serveur : ``QuotaExceeded``, en mots
        failed: list[str] = []
        refreshed = None
        with counting_sent() as sent:
            if tourism_due:
                try:
                    await self.tourism_sync.refresh(uuid)
                except MapsUnavailable as exc:
                    failed.append(str(exc))
            if google_due:
                try:
                    refreshed = await self._reviewed(detail, keys, refresh=True)
                except MapsUnavailable as exc:
                    failed.append(str(exc))
        if not sent[0]:  # rien n'est parti (le mois de Google, un recul, la base…) : ce tour ne coûte rien (R3-01)
            await self.refreshes.forget(turn)
        if failed:
            raise MapsUnavailable(" ".join(failed))
        again = await self._resolve(place_id)
        if refreshed is None:
            fiche = await self.place(place_id)
        else:
            fiche = refreshed if again is None else replace(again[0], hit=refreshed.hit, reviews=refreshed.reviews)
        return PlaceRefresh(fiche, REFRESHED) if fiche is not None else None

    def preload(self, lat: float, lon: float) -> int:
        return self.review_cells.preload(lat, lon)

    def reviews_coverage(self, *, near: tuple[float, float] | None = None,
                         bbox: tuple[float, float, float, float] | None = None) -> ReviewsCoverage:
        return self.review_cells.coverage(near, bbox)

    async def along(self, line: Sequence[tuple[float, float]], *, corridor_m: int = 10_000, category: str = "",
                    limit: int = 20) -> list[PlaceHit]:
        return await self.places.along(line, corridor_m=corridor_m, category=category, limit=limit)

    async def addresses(self, text: str, *, limit: int = 5) -> list[PlaceHit]:
        return await self.geocoder.search(text, limit=limit)

    async def route(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture",
                    avoid: frozenset[str] = frozenset()) -> RouteResult:
        return await self.router.route(points, mode=mode, avoid=avoid)

    async def optimize(self, points: Sequence[tuple[float, float]], *, mode: str = "voiture") -> list[int]:
        return await self.router.optimize(points, mode=mode)

    def tourism_summary(self) -> dict[str, object]:
        info = self.tourism.info()
        return {"ready": info.ready, "places": info.places, "events": info.events, "synced": info.read_at}

    async def events(self, *, near: tuple[float, float] | None = None,
                     bbox: tuple[float, float, float, float] | None = None, radius_m: int = 20_000,
                     start: date | None = None, end: date | None = None, themes: frozenset[str] = frozenset(),
                     text: str = "", free: bool = False, limit: int = 30) -> list[EventHit]:
        unknown = set(themes) - set(_THEME_BITS)
        if unknown:
            raise ValueError(f"un thème inconnu : {', '.join(sorted(unknown))} ({', '.join(_THEME_BITS)})")
        today = paris_today(self.clock())
        start = start or today
        end = end or max(start, today) + timedelta(days=30)
        if end < start:
            raise ValueError("une période : son début avant sa fin")
        if (end - start).days > EVENTS_SPAN_MAX_DAYS:
            raise ValueError(f"une période d'au plus {EVENTS_SPAN_MAX_DAYS} jours")
        if bbox is not None:
            w, s, e, n = bbox
            if not (w < e and s < n):
                raise ValueError("une zone : ouest < est, sud < nord")
        bits = 0
        for theme in themes:
            bits |= _THEME_BITS[theme]
        radius = _events_radius(radius_m)
        # les cases jamais vues que le rayon touche (ou celles de la zone), les plus proches d'abord : lues en direct,
        # en nombre borné, si le quota le permet (ADR 0259) — ``tourism_coverage`` dit le reste
        await self.cells.ensure(self.cells.area(near, bbox, radius), (EVENTS,))
        if not self.tourism.ready():
            if not self.datatourisme.ready():
                raise MapsUnavailable("Les données touristiques ne sont pas réglées.")
            return []  # rien de lu encore : ``tourism_coverage`` dit pourquoi
        return await self.tourism.events(near=near, bbox=bbox, radius_m=radius, start=start, end=end, themes=bits,
                                         words=_words(text or ""), free=bool(free),
                                         limit=max(1, min(EVENTS_LIMIT_MAX, int(limit))))

    async def event(self, event_id: str) -> EventDetail | None:
        key = str(event_id or "").strip()
        return await self.tourism.event(key[2:]) if key.startswith("e:") else None

    async def photo(self, ref: str) -> tuple[bytes, str]:
        return await self.photos.get(ref)

    def tourism_coverage(self, *, near: tuple[float, float] | None = None,
                         bbox: tuple[float, float, float, float] | None = None, radius_m: int | None = None,
                         places: bool = False) -> TourismCoverage:
        radius = _events_radius(radius_m) if radius_m is not None else None
        return self.cells.coverage(self.cells.area(near, bbox, radius), (PLACES,) if places else (EVENTS,))

    # ── en plus du port ──
    async def around(self, lat: float, lon: float, radius_m: float, category: str = "",
                     limit: int = 20, *, open_now: bool = False, features: frozenset[str] = frozenset(),
                     cuisine: str = "", min_rating: float | None = None, sort: str = "distance") -> list[PlaceHit]:
        """Dans l'index local : à moins de ``radius_m`` de ce point, les plus proches d'abord ; les filtres de
        ``search`` (la note : du cache des avis, sans rien demander) ; et les lieux des données touristiques
        qu'OpenStreetMap n'a pas, de toutes les cases déjà lues que le rayon touche. Une liste ne lit que les caches :
        rien ne part ; ``tourism_coverage(near=…, radius_m=…, places=True)`` dit si la zone n'est lue qu'en partie
        (ADR 0259)."""
        _rated([], min_rating, sort)
        limit = max(1, min(LIMIT_MAX, int(limit)))
        rated = min_rating is not None or sort == "rating"
        asked = LIMIT_MAX if rated else limit
        radius = max(1.0, min(500_000.0, float(radius_m)))
        hits = await self.places.around(lat, lon, radius, category, asked, open_now=open_now, features=features,
                                        cuisine=cuisine)
        if not (open_now or features or cuisine.strip()):
            more = await self.tourism.places([], near=(lat, lon), bbox=None, radius_m=radius, category=category,
                                             limit=asked)
            hits = merge_places(hits, more, near=True, limit=asked)
        if rated:
            hits = await self._best_rated(hits, _box(lat, lon, radius), near=(lat, lon), radius_m=radius,
                                          category=category, min_rating=min_rating, open_now=open_now,
                                          features=features, cuisine=cuisine)
        return _rated(await self._noted(hits), min_rating, sort)[:limit]

    def places_summary(self) -> dict[str, object]:
        """L'index pour l'écran : ``{"ready", "count", "built"}`` (``built`` : ISO 8601, vide sans index)."""
        return self.places.summary()

    async def sync_now(self) -> tuple[str, str]:
        """« Synchroniser maintenant » (la console) : les départements tenus en entier s'il y en a, et un passage du
        réchauffage autour des personnes : (ton, message)."""
        if not self.datatourisme.ready():
            return "danger", "Aucune clé DATAtourisme : rien ne part."
        said = [self.warmer.wake()]
        if self.tourism_config().zones:
            said.append(self.tourism_sync.wake())
        tone = "ok" if any(t == "ok" for t, _m in said) else said[0][0]
        return tone, " ".join(m for _t, m in said)

    # ── ce que la console en dit ──
    def describe_places(self) -> list[tuple[str, str]]:
        facts = self.places.describe()
        cfg = self.places.config()
        if not self.geocoder.ready():
            facts.append(("Adresses", "aucune : rien ne sort"))
            return facts
        host = urlsplit(cfg.addresses_url).hostname or cfg.addresses_url
        facts.append(("Adresses", f"la Géoplateforme de l'IGN ({host}) : seul le texte cherché part, jamais la "
                                  "position de la personne"))
        if self.geocoder.asked:
            facts.append(("Depuis le démarrage", f"{self.geocoder.asked} recherche(s) d'adresse, "
                                                 f"{self.geocoder.failed} en échec"))
        if self.geocoder.last_error:
            facts.append(("Dernière erreur", self.geocoder.last_error))
        return facts

    def describe_routing(self) -> list[tuple[str, str]]:
        cfg = self.router.config()
        if cfg.source == NO_ROUTING:
            return [("Itinéraires", "aucun : l'écran Carte le dit, rien ne sort")]
        if cfg.source == FOSSGIS:
            facts = [("Itinéraires", "le Valhalla public de FOSSGIS : au plus une demande par seconde pour tout ce "
                                     "serveur, sans garantie qu'il réponde ; seuls les points du trajet partent")]
        else:
            host = urlsplit(cfg.url).netloc or cfg.url
            rate = f"{cfg.per_second:g}".replace(".", ",")
            facts = [("Itinéraires", f"ton Valhalla ({host}) : au plus {rate} demande(s) par seconde ; seuls les "
                                     "points du trajet partent")]
        router = self.router
        if router.asked or router.cached:
            facts.append(("Depuis le démarrage", f"{router.asked} trajet(s) demandé(s), {router.cached} repris du "
                                                 f"cache, {router.failed} en échec"))
        if router.last_error:
            facts.append(("Dernière erreur", router.last_error))
        return facts

    def describe_tourism(self) -> list[tuple[str, str]]:
        """Les données touristiques : d'où vient la clé (jamais elle), le limiteur, ce que le cache tient, les
        départements tenus en entier et leur synchronisation, les rapprochements, les photos."""
        cfg = self.tourism_config()
        key, origin = tourism_key(cfg)
        sync = self.tourism_sync
        info = self.tourism.info()
        now = self.clock()
        facts = [("Clé", "aucune : rien ne part (règle-la ici, ou pose MIKA_DATATOURISME_API_KEY dans "
                         "l'environnement du serveur)" if not key else
                  "variable d'environnement MIKA_DATATOURISME_API_KEY" if origin == KEY_ENV else "réglée ici")]
        facts.append(("Demandes", self.tourism_limiter.describe()))
        rel = self.tourism.path.relative_to(self.tourism.data) if self.tourism.path.is_relative_to(self.tourism.data) \
            else self.tourism.path
        if info.ready:
            facts.append(("Base", f"{rel} : {_count_fr(info.places)} lieux et {_count_fr(info.events)} événements "
                                  f"à venir ({max(1, round(info.size / 1e6))} Mo)"))
        else:
            facts.append(("Base", f"{rel} : vide pour l'instant"))
        facts.append(("Cache", f"des cases d'environ {cfg.cell_km} km, gardées {cfg.places_days} jour(s) pour les "
                               f"lieux, {cfg.events_days} pour les événements ; "
                               + (f"{_count_fr(info.cells)} lues, la plus ancienne {_at_fr(info.oldest_cell)}"
                                  if info.cells else "aucune lue encore")))
        if cfg.zones:
            facts.append(("Départements tenus en entier", "toute la France" if cfg.everywhere else
                          ", ".join(cfg.zones)))
            if info.last_sync:
                facts.append(("Dernière synchronisation", f"{KIND_FR.get(info.last_kind, info.last_kind)}, "
                                                          f"{_at_fr(info.last_sync)}"))
            if info.last_full:
                facts.append(("Dernière complète", _at_fr(info.last_full) + " (ce qu'elle n'a plus vu s'est effacé)"))
            if sync.running:
                facts.append(("En ce moment", sync.doing or "la synchronisation commence"))
            elif info.run:
                facts.append(("À reprendre", f"une complète commencée {_at_fr(info.run)} : {info.run_done} parties "
                                             f"sur {info.run_parts}, {_count_fr(info.run_fiches)} fiches"))
            upcoming = sync.next_at(now)
            if upcoming is not None:
                when = "maintenant" if upcoming <= now else _at_fr(upcoming.isoformat())
                facts.append(("Prochaine synchronisation", when + (" (après une erreur)" if sync.retry_at and
                                                                   upcoming == sync.retry_at else "")))
        else:
            facts.append(("Départements tenus en entier", "aucun : le cache par cases suffit"))
        error, error_at = sync.last_error or info.last_error, info.last_error_at
        if error:
            facts.append(("Dernière erreur", error + (f" ({_at_fr(error_at)})" if error_at else "")))
        if info.ready:
            facts.append(("Rapprochés d'OpenStreetMap", f"{_count_fr(info.twins)} lieux sur "
                                                        f"{_count_fr(info.places)} ; {_count_fr(info.venues)} "
                                                        "événements dans un lieu nommé"))
        count, size = self.photos.size()
        facts.append(("Photos relayées", f"{_count_fr(count)} gardées dans {MAPS_DIR}/photos "
                                         f"({round(size / 1e6)} Mo sur {round(self.photos.cache_max / 1e6)})"))
        facts.append(("Licence", "Licence Ouverte 2.0 : chaque fiche cite son auteur et sa date ; chaque photo, son "
                                 "crédit et sa licence, et ne se montre plus après la fin de ses droits"))
        return facts

    def describe_reviews(self) -> list[tuple[str, str]]:
        """Les avis (Google) : d'où vient la clé (jamais elle), les appels du jour et ceux du mois de chaque SKU sur
        son plafond et son quota offert, ce qui serait facturé au-delà, ce que le cache tient, les cases et ce qu'en
        coûte une, le préchargement et le réchauffage, la dernière erreur, les conditions de Google et ce qu'on en a
        décidé, et le conseil de restreindre la clé."""
        cfg = self.reviews_config()
        key, origin = reviews_key(cfg)
        info = self.reviews.info()
        cells = self.review_cells
        facts = [("Clé", "aucune : rien ne part (règle-la ici, ou pose MIKA_GOOGLE_PLACES_API_KEY dans "
                         "l'environnement du serveur)" if not key else
                  "variable d'environnement MIKA_GOOGLE_PLACES_API_KEY" if origin == KEY_ENV else "réglée ici")]
        facts.append(("Appels", self.reviews_limiter.describe()))
        billed = 0.0
        for sku in SKUS:
            limiter = self.sku_limiters[sku.service]
            used = next((w.used for w in limiter.status().windows if w.name == "mois"), 0)
            billed += sku.billed(used)
            facts.append((f"{sku.label[0].upper()}{sku.label[1:]} ({sku.name})",
                          f"{limiter.describe()} — {_count_fr(sku.free)} offertes chaque mois, puis "
                          f"{_price_fr(sku.price)} les 1 000"))
        said = "rien : tout tient dans les quotas offerts" if not billed else \
            f"environ {_usd_fr(billed)} au-delà des quotas offerts"
        facts.append(("Facturé ce mois", f"{said} (d'après les comptes de ce dossier de données : la même clé ailleurs "
                                         "puise dans le même quota offert, sans qu'ils le voient ; le mois de Google "
                                         "commence à minuit, heure du Pacifique ; prix vérifiés "
                                         f"{_when_fr(PRICES_CHECKED)})"))
        rel = self.reviews.path.relative_to(self.reviews.data) if self.reviews.path.is_relative_to(self.reviews.data) \
            else self.reviews.path
        if info.ready:
            facts.append(("Cache", f"{rel} : {_count_fr(info.spots)} lieux ({_count_fr(info.twins)} rapprochés d'un "
                                   f"lieu de l'index), {_count_fr(info.detailed)} fiches lues avec "
                                   f"{_count_fr(info.reviews)} avis, {_count_fr(info.photos)} photos connues "
                                   f"({max(1, round(info.size / 1e6))} Mo)"))
        else:
            facts.append(("Cache", f"{rel} : vide pour l'instant"))
        most = 1 + sum(4 ** k for k in range(1, cfg.split_depth + 1))
        cost = "une recherche (le cercle qui la couvre)" if most == 1 else \
            f"de 1 à {most} recherches (un cercle, puis ses quarts s'il est plein)"
        facts.append(("Cases", f"d'environ {cfg.cell_km} km, gardées {cfg.cache_days} jour(s) ; une case coûte, par "
                               f"sorte, {cost} ; "
                               + (f"{_count_fr(info.cells)} lues (une case et une sorte), la plus ancienne "
                                  f"{_at_fr(info.oldest_cell)}" if info.cells else "aucune lue encore")))
        facts.append(("Préchargement", ("oui : la case d'une position et ses voisines, en fond"
                                        + (f" ({cells.preloaded} lue(s) depuis le démarrage)" if cells.preloaded
                                           else "")) if cfg.preload else "non"))
        facts.append(("Réchauffage du soir", "oui : restaurants, puis à voir, puis hébergements, puis la fiche des "
                                             "lieux ouverts depuis un mois" if cfg.warm else "non"))
        error = self.google.last_error or cells.note
        if error:
            facts.append(("Dernière erreur", error))
        facts.append(("Conditions de Google", "elles ne permettent de garder que l'identifiant d'un lieu (et ses "
                                              "coordonnées trente jours) ; l'opérateur a choisi le 20 novembre 2026 "
                                              "de garder ce cache sept jours et de le lui faire lire, sous sa "
                                              "responsabilité (ADR 0256). La mention « Google Maps », le lien vers "
                                              "la page du lieu et le nom et le lien de l'auteur de chaque avis et de "
                                              "chaque photo se montrent toujours avec"))
        facts.append(("Ta clé", "dans Google Cloud, restreins-la à « Places API (New) » (restrictions d'API) et, si "
                                "tu peux, à l'adresse IP de ce serveur"))
        return facts

    def describe_warm(self) -> list[tuple[str, str]]:
        """Le réchauffage du soir : quand, autour de quoi, le dernier passage, le budget de chaque source."""
        return self.warmer.describe(_at_fr)
