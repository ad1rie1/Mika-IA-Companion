"""Les itinéraires (ADR 0194) : un serveur Valhalla — le public de FOSSGIS, au plus une demande par seconde pour tout
le processus, ou le tien —, relayé par ce serveur. Seuls les points du trajet partent ; un trajet redemandé ne repart
pas ; ce qui ne va pas se dit en mots ; le GPX d'un voyage. Les réponses ont la forme de celles du vrai service
(``valhalla1.openstreetmap.de/route``, le 2026-11-05). Et le port ``maps`` que le noyau reçoit (``MapsDesk``)."""

from __future__ import annotations

import asyncio
import inspect
import json
import xml.etree.ElementTree as ET

import httpx
import pytest

from mika.adapters.maps import routing as rt
from mika.adapters.maps.config import FOSSGIS, GEOPLATEFORME, VALHALLA, PlacesConfig, RoutingConfig
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.pace import Pace
from mika.adapters.maps.tiles import USER_AGENT
from mika.ports.maps import MapsPort, MapsUnavailable, decode_polyline6, encode_polyline6

ANNECY, CHAMBERY = (45.8992, 6.1294), (45.5646, 5.9178)
SHAPE = [(45.899543, 6.128952), (45.8, 6.05), (45.564275, 5.91769)]


def trip(legs: int = 1) -> dict:
    """Un trajet de Valhalla, de la forme du vrai : longueurs en km, durées en secondes, tracé en polyline6."""
    leg = {"summary": {"has_toll": False, "has_highway": False, "has_ferry": False, "time": 5386.289,
                       "length": 58.015, "cost": 7813.57},
           "shape": encode_polyline6(SHAPE),
           "maneuvers": [{"type": 1, "instruction": "Conduisez vers l'ouest.", "time": 44.6, "length": 0.03},
                         {"type": 26, "instruction": "Entrez dans le rond-point et prenez la 2e sortie​ dans "
                                                     "Rue des Marquisats/D 1508.", "time": 5.323, "length": 0.026},
                         {"type": 4, "instruction": "Votre destination est sur la gauche.", "time": 0.0,
                          "length": 0.0}]}
    return {"trip": {"locations": [{"type": "break", "lat": 45.8992, "lon": 6.1294, "original_index": 0},
                                   {"type": "break", "lat": 45.5646, "lon": 5.9178, "original_index": 1}],
                     "legs": [leg] * legs,
                     "summary": {"has_toll": True, "has_highway": False, "has_ferry": False, "time": 5386.289 * legs,
                                 "length": 58.015 * legs},
                     "status_message": "Found route between points", "status": 0, "units": "kilometers",
                     "language": "fr-FR"}}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.t += seconds


def router(handler, source: str = FOSSGIS, **cfg: object) -> tuple[rt.Router, Clock]:
    clock = Clock()
    pace = Pace(1.0, wait_max=20.0, now=clock.now, sleep=clock.sleep)
    r = rt.Router(lambda: RoutingConfig(source=source, **cfg), transport=httpx.MockTransport(handler), pace=pace,
                  now=clock.now)
    return r, clock


async def test_a_route_sends_its_points_only_and_reads_valhalla_s_answer():
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=trip(), headers={"set-cookie": "suivi=1"})

    r, _clock = router(serve)
    got = await r.route([ANNECY, (45.56461234567, 5.91781234567)], avoid=frozenset({"peages", "ferries"}))
    request = seen[0]
    assert str(request.url) == "https://valhalla1.openstreetmap.de/route" and request.method == "POST"
    assert request.headers["user-agent"] == USER_AGENT and "cookie" not in request.headers
    body = json.loads(request.content)
    assert body == {"locations": [{"lat": 45.8992, "lon": 6.1294, "type": "break"},
                                  {"lat": 45.564612, "lon": 5.917812, "type": "break"}],
                    "costing": "auto", "costing_options": {"auto": {"use_tolls": 0, "use_ferry": 0}},
                    "directions_options": {"units": "kilometers", "language": "fr-FR"}}
    assert (got.distance_m, got.duration_s, got.has_toll) == (58015, 5386, True)
    assert got.provider == "Valhalla, serveur public de FOSSGIS" and len(got.legs) == 1
    leg = got.legs[0]
    assert decode_polyline6(leg.shape) == SHAPE and (leg.distance_m, leg.duration_s) == (58015, 5386)
    assert [s.text for s in leg.steps][0] == "Conduisez vers l'ouest." and leg.steps[0].distance_m == 30
    assert "​" not in leg.steps[1].text  # un texte du dehors, rendu inerte
    await r.close()


@pytest.mark.parametrize(("mode", "avoid", "costing", "options"), [
    ("voiture", {"autoroutes"}, "auto", {"auto": {"use_highways": 0}}),
    ("velo", {"peages", "autoroutes"}, "bicycle", None),  # à vélo, ni péage ni autoroute
    ("velo", {"ferries"}, "bicycle", {"bicycle": {"use_ferry": 0}}),
    ("pied", set(), "pedestrian", None),
])
async def test_each_mode_is_its_valhalla_costing(mode, avoid, costing, options):
    seen: list[dict] = []
    r, _clock = router(lambda request: seen.append(json.loads(request.content)) or httpx.Response(200, json=trip()))
    await r.route([ANNECY, CHAMBERY], mode=mode, avoid=frozenset(avoid))
    assert seen[0]["costing"] == costing and seen[0].get("costing_options") == options


async def test_a_route_asked_again_does_not_leave_again():
    calls: list[dict] = []
    r, clock = router(lambda request: calls.append(json.loads(request.content)) or httpx.Response(200, json=trip()))
    first = await r.route([ANNECY, CHAMBERY])
    assert await r.route([ANNECY, CHAMBERY]) == first and len(calls) == 1 and r.cached == 1
    await r.route([ANNECY, CHAMBERY], avoid=frozenset({"peages"}))  # un autre trajet
    assert len(calls) == 2
    clock.t += rt.CACHE_TTL_S + 1  # gardé un jour
    await r.route([ANNECY, CHAMBERY])
    assert len(calls) == 3


async def test_the_cache_keeps_the_last_routes_only(monkeypatch):
    monkeypatch.setattr(rt, "CACHE_SIZE", 2)
    calls: list[int] = []
    r, _clock = router(lambda request: calls.append(1) or httpx.Response(200, json=trip()))
    for lat in (45.1, 45.2, 45.3):
        await r.route([(lat, 6.0), CHAMBERY])
    await r.route([(45.1, 6.0), CHAMBERY])  # le plus ancien est parti
    await r.route([(45.3, 6.0), CHAMBERY])  # le plus récent est là
    assert len(calls) == 4 and len(r._cache) == 2


async def test_the_same_route_asked_at_once_leaves_once():
    calls: list[int] = []

    async def serve(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=trip())

    r, _clock = router(serve)
    got = await asyncio.gather(*(r.route([ANNECY, CHAMBERY]) for _ in range(4)))
    assert len(calls) == 1 and all(g == got[0] for g in got)


async def test_fossgis_is_asked_at_most_once_a_second_for_the_whole_process():
    a = rt.Router(lambda: RoutingConfig(source=FOSSGIS))
    b = rt.Router(lambda: RoutingConfig(source=FOSSGIS))
    assert a._turns(a.config()) is b._turns(b.config()) is rt.FOSSGIS_PACE and rt.FOSSGIS_PACE.rate == 1.0
    own = rt.Router(lambda: RoutingConfig(source=VALHALLA, url="http://127.0.0.1:8002", per_second=4))
    assert own._turns(own.config()).rate == 4 and own._turns(own.config()) is not rt.FOSSGIS_PACE
    # deux trajets différents : le second attend son tour
    r, clock = router(lambda request: httpx.Response(200, json=trip()))
    await r.route([ANNECY, CHAMBERY])
    await r.route([CHAMBERY, ANNECY])
    await r.route([ANNECY, (45.7, 6.0)])
    assert clock.slept == [1.0, 1.0]


async def test_a_queue_too_long_is_refused_in_words():
    clock = Clock()

    async def still(seconds: float) -> None:  # l'horloge ne bouge pas : la file s'allonge
        return None

    pace = Pace(1.0, wait_max=2.0, busy="très demandé", now=clock.now, sleep=still)
    for _ in range(3):
        await pace.turn()  # 0, 1 et 2 s d'attente : ça passe
    with pytest.raises(MapsUnavailable, match="très demandé"):
        await pace.turn()


@pytest.mark.parametrize(("answer", "said"), [
    (httpx.Response(400, json={"error_code": 442, "error": "No path could be found for input", "status_code": 400}),
     "Aucun chemin en voiture ne relie ces points."),
    (httpx.Response(400, json={"error_code": 171, "error": "No suitable edges near location"}), "trop loin"),
    (httpx.Response(400, json={"error_code": 154, "error": "Path distance exceeds the max distance limit"}),
     "trop long"),
    (httpx.Response(400, json={"error_code": 199, "error": "Quelque‮chose d'inconnu"}), "refuse ce trajet"),
    (httpx.Response(429), "demande d'attendre"),
    (httpx.Response(502), "HTTP 502"),
    (httpx.Response(200, content=b"<html>"), "illisible"),
    (httpx.Response(200, json={"trip": {"legs": []}}), "illisible"),
    ("coupure", "ne répond pas"),
])
async def test_what_goes_wrong_is_said_in_words(answer, said):
    def serve(request: httpx.Request) -> httpx.Response:
        if answer == "coupure":
            raise httpx.ReadTimeout("trop long", request=request)
        return answer

    r, _clock = router(serve)
    with pytest.raises(MapsUnavailable) as caught:
        await r.route([ANNECY, CHAMBERY])
    assert said in str(caught.value) and r.failed == 1 and r.last_error == str(caught.value)
    assert "‮" not in str(caught.value)  # ce que dit le serveur, rendu inerte
    assert not r._cache  # un échec ne se garde pas


async def test_the_best_order_keeps_both_ends_and_asks_only_when_there_is_something_to_order():
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        n = len(json.loads(request.content)["locations"])
        order = [0, 3, 1, 2, n - 1] if n == 5 else list(range(n))
        return httpx.Response(200, json={"trip": {"locations": [{"original_index": i} for i in order]}})

    r, _clock = router(serve)
    assert await r.optimize([ANNECY, (45.8, 6.0), CHAMBERY]) == [0, 1, 2] and seen == []
    points = [ANNECY, (45.8, 6.0), (45.7, 6.1), (45.6, 6.0), CHAMBERY]
    assert await r.optimize(points, mode="velo") == [0, 3, 1, 2, 4]
    assert str(seen[0].url).endswith("/optimized_route") and json.loads(seen[0].content)["costing"] == "bicycle"
    bad, _clock = router(lambda request: httpx.Response(200, json={"trip": {"locations": [
        {"original_index": i} for i in (0, 1, 1, 2, 4)]}}))
    with pytest.raises(MapsUnavailable, match="illisible"):
        await bad.optimize(points)


@pytest.mark.parametrize(("points", "mode", "avoid"), [
    ([ANNECY], "voiture", ()), ([ANNECY] * 21, "voiture", ()), ([ANNECY, CHAMBERY], "avion", ()),
    ([ANNECY, CHAMBERY], "voiture", ("montagnes",)), ([(95.0, 6.0), CHAMBERY], "voiture", ()),
    ([(float("nan"), 6.0), CHAMBERY], "voiture", ()),
])
async def test_arguments_outside_the_port_are_refused(points, mode, avoid):
    r, _clock = router(lambda request: pytest.fail("rien ne doit partir"))
    with pytest.raises(ValueError):
        await r.route(points, mode=mode, avoid=frozenset(avoid))


async def test_without_routing_nothing_leaves():
    r, _clock = router(lambda request: pytest.fail("rien ne doit partir"), source="aucun")
    assert not r.ready() and r.provider() == ""
    with pytest.raises(MapsUnavailable) as caught:
        await r.route([ANNECY, CHAMBERY])
    # ce qui manque, sans chemin de console : ce mot arrive aux personnes et au modèle
    assert str(caught.value) == "Les itinéraires ne sont pas réglés."
    with pytest.raises(MapsUnavailable):
        await r.optimize([ANNECY, CHAMBERY])
    own, _clock = router(lambda request: httpx.Response(200, json=trip()), source=VALHALLA,
                         url="http://127.0.0.1:8002/")
    got = await own.route([ANNECY, CHAMBERY])
    assert got.provider == "Valhalla" and own.config().url == "http://127.0.0.1:8002"


def test_its_setting_needs_a_complete_address_for_your_own_valhalla():
    with pytest.raises(ValueError):
        RoutingConfig(source=VALHALLA)
    for bad in ("127.0.0.1:8002", "ftp://x.example.test", "http://x.example.test/?a=1"):
        with pytest.raises(ValueError):
            RoutingConfig(source=VALHALLA, url=bad)
    for rate in (0.0, 1000.0):
        with pytest.raises(ValueError):
            RoutingConfig(source=VALHALLA, url="http://127.0.0.1:8002", per_second=rate)
    fossgis = RoutingConfig(source=FOSSGIS)
    assert fossgis.base == "https://valhalla1.openstreetmap.de" and fossgis.rate == 1.0  # ses conditions, pas un réglage
    assert RoutingConfig().source == "aucun"  # par défaut : rien ne sort


def test_a_trip_becomes_a_gpx_with_its_stops_and_its_track():
    text = rt.gpx('Les Alpes <à> & "co"', [("Annecy", 45.8992, 6.1294), ("Camping \"L'Horizon\" & <co>\x07", 45.86, 6.14)],
                  SHAPE)
    root = ET.fromstring(text)  # du XML bien formé, les noms échappés
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    assert root.get("version") == "1.1" and root.get("creator") == USER_AGENT.split(" ")[0]
    assert root.find("g:metadata/g:name", ns).text == 'Les Alpes <à> & "co"'
    stops = root.findall("g:rte/g:rtept", ns)
    assert [(s.get("lat"), s.get("lon"), s.find("g:name", ns).text) for s in stops] == [
        ("45.899200", "6.129400", "Annecy"), ("45.860000", "6.140000", "Camping \"L'Horizon\" & <co>")]
    assert len(root.findall("g:trk/g:trkseg/g:trkpt", ns)) == 3
    by_day = ET.fromstring(rt.gpx("Deux jours", [], [SHAPE[:2], SHAPE[1:], []]))
    assert len(by_day.findall("g:trk/g:trkseg", ns)) == 2 and by_day.find("g:trk/g:trkseg", ns) is not None
    assert ET.fromstring(rt.gpx("", [("Ici", 45.0, 6.0)])).find("g:trk", ns) is None  # sans tracé : les arrêts


def test_a_shape_goes_both_ways():
    assert decode_polyline6(encode_polyline6(SHAPE)) == SHAPE
    with pytest.raises(ValueError):
        decode_polyline6("_p~iF~ps|U_")  # tronqué


# ── le port ``maps`` ──

def test_the_desk_offers_every_method_of_the_port():
    """Ce que le plugin des voyages et l'API attendent du port : chaque méthode, avec ses paramètres."""
    for name, member in inspect.getmembers(MapsPort, inspect.isfunction):
        if name.startswith("_"):
            continue
        ours = getattr(MapsDesk, name)
        assert list(inspect.signature(ours).parameters) == list(inspect.signature(member).parameters), name
        assert inspect.iscoroutinefunction(ours) == inspect.iscoroutinefunction(member), name


async def test_the_desk_says_what_is_set_for_the_console(tmp_path):
    places = [PlacesConfig()]
    routing = [RoutingConfig()]
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"features": []})
        return httpx.Response(200, json=trip())

    desk = MapsDesk(tmp_path, lambda: places[0], lambda: routing[0], transport=httpx.MockTransport(serve),
                    routing_pace=Pace(1000.0), address_pace=Pace(1000.0))
    assert not desk.places_ready() and not desk.addresses_ready() and not desk.routing_ready()
    assert [key for key, _label in desk.categories()][:3] == ["manger", "dormir", "voir"]
    assert desk.places_summary()["ready"] is False
    facts = dict(desk.describe_places())
    assert "mika carte lieux" in facts["Index des lieux"] and facts["Adresses"] == "aucune : rien ne sort"
    assert dict(desk.describe_routing())["Itinéraires"].startswith("aucun")
    places[0] = PlacesConfig(addresses=GEOPLATEFORME)
    routing[0] = RoutingConfig(source=FOSSGIS)
    assert desk.addresses_ready() and desk.routing_ready() and desk.routing_provider().startswith("Valhalla")
    assert await desk.addresses("Place de la Concorde Paris") == []
    await desk.route([ANNECY, CHAMBERY])
    await desk.route([ANNECY, CHAMBERY])
    assert "data.geopf.fr" in dict(desk.describe_places())["Adresses"]
    said = dict(desk.describe_routing())
    assert "une demande par seconde" in said["Itinéraires"] and "1 repris du cache" in said["Depuis le démarrage"]
    routing[0] = RoutingConfig(source=VALHALLA, url="http://127.0.0.1:8002", per_second=2.5)
    assert "127.0.0.1:8002" in dict(desk.describe_routing())["Itinéraires"]
    assert "2,5 demande(s)" in dict(desk.describe_routing())["Itinéraires"]
    await desk.close()
    assert [r.url.host for r in seen] == ["data.geopf.fr", "valhalla1.openstreetmap.de"]
