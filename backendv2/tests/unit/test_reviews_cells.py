"""Le cache des avis par cases (ADR 0256) : une case se demande par le cercle qui la couvre (son centre, la moitié de
sa diagonale — jamais la position de la personne), par sorte, les vingt plus connus ; pleine, ses quatre quarts se
demandent à leur tour, jusqu'au découpage réglé ; coupée par un quota, elle reprend à son cercle suivant ; gardée sept
jours (le réglage), elle ne repart pas d'ici là, puis se relit ; ce qui n'a pas été relu depuis quatre fois cette durée
s'efface. Le préchargement met en file la case d'une position et ses voisines ; le réchauffage du soir prend les
restaurants, puis ce qui est à voir, puis les hébergements, les cases des points puis leurs voisines, les plus vieilles
d'abord, puis la fiche des lieux ouverts depuis peu — sur le budget de fond."""

from __future__ import annotations

import pytest

from mika.adapters.maps.cells import cell_of, neighbours
from mika.adapters.maps.config import ReviewsConfig, WarmConfig
from mika.adapters.maps.google_places import PRIMARY_TYPES
from mika.adapters.maps.quota import MONTH, QuotaExceeded
from mika.adapters.maps.reviews_cells import AVIS, _distance_m, circle
from mika.adapters.maps.warm import Warmer
from tests.fixtures import google_places as gp

LILLE = gp.GRAND_PLACE


def centers(api: gp.FakeGoogle) -> list[tuple[float, float, float]]:
    out = []
    for body in api.bodies():
        c = body["locationRestriction"]["circle"]
        out.append((c["center"]["latitude"], c["center"]["longitude"], c["radius"]))
    return out


def warmer(tmp_path, source, clock) -> Warmer:  # noqa: ANN001
    return Warmer(tmp_path, lambda: WarmConfig(points=("50.637, 3.063",), people=False), sources=(source,),
                  clock=clock, sleep=clock.sleep)


def test_the_circle_of_a_cell_covers_its_corners_and_its_quarters_split_it():
    cell = cell_of(*LILLE, 3)
    lat, lon, radius = circle(cell)
    assert (lat, lon) == (pytest.approx(cell.center[0]), pytest.approx(cell.center[1]))
    assert radius >= _distance_m(lat, lon, cell.south, cell.west) and 2100 < radius < 2200  # ~3 km × √2 / 2
    qlat, qlon, qradius = circle(cell, "3")  # le quart nord-est
    assert qlat > lat and qlon > lon and qradius == pytest.approx(radius / 2, rel=0.01)
    slat, slon, _r = circle(cell, "03")  # le quart nord-est de son quart sud-ouest
    assert cell.south < slat < lat and cell.west < slon < lon


async def test_a_cell_is_asked_by_its_circle_never_by_a_position(tmp_path):
    api = gp.FakeGoogle()
    rig = gp.rig(tmp_path, api)
    cell = rig.cells.cell(*LILLE)
    count, done = await rig.cells.load(cell, "manger", background=True)
    # Méert, dans le cercle ; le centre commercial n'y remonte pas, et La Bellezza est dans la case d'à côté
    assert done and count == 1 and api.calls(gp.NEARBY) == 1
    [(lat, lon, radius)] = centers(api)
    assert (lat, lon, radius) == circle(cell)
    [body] = api.bodies()
    assert body["includedPrimaryTypes"] == list(PRIMARY_TYPES["manger"]) and body["rankPreference"] == "POPULARITY"
    state = rig.reviews.cell_states([cell.key])[(cell.key, "manger")]
    assert state.fetched and not state.reading and (state.count, state.circles) == (1, 1)


@pytest.mark.parametrize(("depth", "calls"), [(0, 1), (1, 5)])
async def test_a_dense_cell_asks_its_four_quarters(tmp_path, depth, calls):
    api = gp.FakeGoogle(places=gp.many(90))
    rig = gp.rig(tmp_path, api, cfg=ReviewsConfig(api_key=gp.KEY, split_depth=depth))
    cell = rig.cells.cell(*LILLE)
    count, _done = await rig.cells.load(cell, "manger", background=True)
    assert api.calls(gp.NEARBY) == calls
    asked = centers(api)
    assert asked[0] == circle(cell) and asked[1:] == [circle(cell, q) for q in "0123"][:calls - 1]
    kept = await rig.reviews.read(lambda c: c.execute("SELECT COUNT(*) FROM spot").fetchone()[0], 0)
    # un lieu rendu par deux cercles ne se garde qu'une fois ; découpée, la case en garde plus que vingt
    assert count >= 20 and (kept == 20 if depth == 0 else 20 < kept <= count)


async def test_a_cell_cut_by_its_quota_resumes_at_its_next_circle(tmp_path):
    api = gp.FakeGoogle(places=gp.many(90))
    rig = gp.rig(tmp_path, api, cfg=ReviewsConfig(api_key=gp.KEY, searches_per_month=3, reserve_pct=0))
    cell = rig.cells.cell(*LILLE)
    with pytest.raises(QuotaExceeded) as caught:
        await rig.cells.load(cell, "manger", background=True)
    assert caught.value.window == MONTH
    state = rig.reviews.cell_states([cell.key])[(cell.key, "manger")]
    assert state.reading and not state.fetched and state.circles == 3
    rig.config[0] = ReviewsConfig(api_key=gp.KEY, searches_per_month=100, reserve_pct=0)
    _count, done = await rig.cells.load(cell, "manger", background=True)
    assert done and centers(api) == [circle(cell), *(circle(cell, q) for q in "0123")]  # sans relire les premiers


async def test_seven_days_without_asking_again_then_read_again(tmp_path):
    api = gp.FakeGoogle()
    rig = gp.rig(tmp_path, api)
    cell = rig.cells.cell(*LILLE)
    await rig.cells.load(cell, "manger", background=True)
    rig.clock.advance(days=6, hours=23)
    assert cell.key not in {t.cell.key for t in rig.cells.plan([LILLE], rig.clock()) if t.part == "manger"}
    rig.cells.preload(*LILLE)
    await rig.cells.drain()
    own = [c for b, c in zip(api.bodies(), centers(api), strict=True) if b["includedPrimaryTypes"][0] == "restaurant"
           and c == circle(cell)]
    assert len(own) == 1  # sa case, fraîche, n'est pas repartie au préchargement
    rig.clock.advance(hours=2)  # sept jours : elle est vieille
    first = rig.cells.plan([LILLE], rig.clock())[0]
    assert (first.cell.key, first.part) == (cell.key, "manger") and first.fetched
    rig.config[0] = ReviewsConfig(api_key=gp.KEY, cache_days=30)  # relu : elle redevient fraîche
    assert cell.key not in {t.cell.key for t in rig.cells.plan([LILLE], rig.clock()) if t.part == "manger"}


async def test_what_is_not_read_again_for_four_times_its_life_is_dropped(tmp_path):
    roubaix = (50.70, 3.16)
    api = gp.FakeGoogle(places=[*gp.nearby(), *gp.many(3, start=7000, near=roubaix)])
    rig = gp.rig(tmp_path, api)
    await rig.cells.load(rig.cells.cell(*roubaix), "manger", background=True)
    ref = await rig.reviews.read(lambda c: c.execute("SELECT photo FROM spot WHERE name = 'Lieu restaurant 0'")
                                 .fetchone()[0], "")
    assert ref.startswith("p:") and rig.reviews.photo_row(ref) is not None
    rig.clock.advance(days=29)
    await rig.cells.load(rig.cells.cell(*LILLE), "manger", background=True)
    ids = await rig.reviews.read(lambda c: sorted(r[0] for r in c.execute("SELECT id FROM spot")), [])
    assert ids == [gp.MEERT]
    assert rig.reviews.photo_row(ref) is None


async def test_preload_queues_the_cell_and_its_neighbours_never_the_position(tmp_path):
    api = gp.FakeGoogle()
    rig = gp.rig(tmp_path, api)
    here = (50.63711, 3.06322)
    assert rig.cells.preload(*here) == 27  # neuf cases, trois sortes
    assert rig.cells.preload(*here) == 0  # déjà en file
    assert await rig.cells.drain() == 27
    cell = cell_of(*here, 3)
    keys = [cell.key, *(c.key for c in neighbours(cell, 3))]
    states = rig.reviews.cell_states(keys)
    assert len(states) == 27 and all(s.fetched for s in states.values())
    sent = " ".join(r.content.decode() for r in api.requests)
    assert "50.63711" not in sent and "3.06322" not in sent
    assert [b["includedPrimaryTypes"][0] for b in api.bodies()[:9]] == ["restaurant"] * 9  # les restaurants d'abord
    assert rig.cells.preload(*here) == 27 and await rig.cells.drain() == 0  # frais : rien ne repart
    rig.config[0] = ReviewsConfig(api_key=gp.KEY, preload=False)
    assert rig.cells.preload(*here) == 0
    assert gp.rig(tmp_path / "sans-cle", cfg=ReviewsConfig()).cells.preload(*here) == 0


async def test_preload_stops_on_its_quota_and_says_so(tmp_path):
    api = gp.FakeGoogle()
    rig = gp.rig(tmp_path, api, cfg=ReviewsConfig(api_key=gp.KEY, searches_per_month=10, reserve_pct=20))
    rig.cells.preload(*LILLE)
    await rig.cells.drain()
    assert api.calls(gp.NEARBY) == 8 and "Le préchargement des avis s'est arrêté" in rig.cells.note
    assert "la part de fond du quota du mois de Google (recherches à proximité)" in rig.cells.note
    assert not rig.cells._queue
    coverage = rig.cells.coverage(LILLE, None)
    assert coverage.ready and coverage.cells == 1 and coverage.loaded == 0
    assert "Le préchargement des avis s'est arrêté" in coverage.note


def test_the_plan_takes_restaurants_then_sights_then_lodging_points_first(tmp_path):
    rig = gp.rig(tmp_path)
    own = cell_of(*LILLE, 3)
    ring = neighbours(own, 3)
    tasks = rig.cells.plan([LILLE], rig.clock())
    assert [t.part for t in tasks] == ["manger"] * 9 + ["voir"] * 9 + ["dormir"] * 9 + [AVIS] * 9
    assert [t.cell.key for t in tasks[:9]] == [own.key, *sorted(c.key for c in ring)]
    assert tasks[-9].cell.key == own.key  # les fiches : sa case d'abord
    rig.config[0] = ReviewsConfig(api_key=gp.KEY, warm=False)
    assert rig.cells.plan([LILLE], rig.clock()) == []
    assert "ne prennent pas part au réchauffage" in rig.cells.budget()


async def test_the_plan_puts_the_oldest_cells_first(tmp_path):
    rig = gp.rig(tmp_path, gp.FakeGoogle(places=[]))
    own = cell_of(*LILLE, 3)
    [first, second, *_rest] = sorted(neighbours(own, 3), key=lambda c: c.key)
    await rig.cells.load(second, "manger", background=True)
    rig.clock.advance(days=1)
    await rig.cells.load(first, "manger", background=True)
    rig.clock.advance(days=7)
    keys = [t.cell.key for t in rig.cells.plan([LILLE], rig.clock()) if t.part == "manger"]
    assert keys[0] == own.key and keys[-2:] == [second.key, first.key]  # jamais lues, puis la plus vieille


async def test_the_evening_pass_reads_the_fiche_of_places_opened_lately(tmp_path):
    api = gp.FakeGoogle(places=[*gp.nearby(), *gp.many(5)])
    maps, outside, clock, _config = gp.desk(tmp_path, api)
    detail = await maps.place("n301")  # « La Bellezza » : ouverte une fois
    assert detail.reviews.id == gp.BELLEZZA
    api.requests.clear()
    clock.advance(days=8)
    run = await warmer(tmp_path, maps.review_cells, clock).run()
    [report] = run.sources
    assert report.label == "Google" and not report.stopped and report.done == report.planned == 36
    fiches = [r.url.path.rsplit("/", 1)[1] for r in api.requests if gp._kind(r) == gp.DETAILS]
    # seulement les lieux qu'on a ouverts : Méert, jamais ouverte, n'est pas relue
    assert fiches == [gp.BELLEZZA]
    assert set(outside.hosts()) == {gp.HOST}


async def test_the_evening_pass_stops_on_its_budget_and_keeps_the_reserve(tmp_path):
    api = gp.FakeGoogle()
    rig = gp.rig(tmp_path, api, cfg=ReviewsConfig(api_key=gp.KEY, searches_per_month=10, reserve_pct=20))
    run = await warmer(tmp_path, rig.cells, rig.clock).run()
    [report] = run.sources
    assert api.calls(gp.NEARBY) == 8 and "la part de fond du quota du mois de Google (recherches" in report.stopped
    assert "8 recherches ce mois sur 10 (2 gardées pour le direct)" in rig.cells.budget()
    await rig.client.nearby(*LILLE, 500, "manger")  # le direct a encore sa réserve
