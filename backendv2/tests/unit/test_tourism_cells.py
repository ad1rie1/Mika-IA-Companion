"""Le cache des données touristiques par cases et le réchauffage du soir (ADR 0245) : une case s'interroge par ses
bords (jamais la position de la personne), se garde avec sa date, efface ce qu'elle ne rend plus ; une case jamais vue
qu'on ouvre se lit en direct (quelques pages, puis elle reprend), et quand le quota manque on montre ce qu'on a en
le disant ; le soir, autour des personnes et des points fixes, les cases à elles d'abord, les événements avant les
lieux, les plus vieilles d'abord, sur le budget de fond — qui attend son quota s'il revient avant le matin."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from mika.adapters.maps import tourism_cells
from mika.adapters.maps.cells import cell_of
from mika.adapters.maps.config import PlacesConfig, RoutingConfig, TourismConfig, WarmConfig
from mika.adapters.maps.datatourisme import EVENTS, PLACES, DataTourismeClient
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.quota import HOUR, QuotaExceeded
from mika.adapters.maps.tourism import Tourism
from mika.adapters.maps.tourism_cells import LIVE_PAGES, LIVE_READS_MAX, TourismCells
from mika.adapters.maps.warm import ERRORS_MAX, Warmer, WarmTask
from mika.app.domains.maps.warm_points import last_positions
from tests.fixtures import tourism as tf

LILLE = (50.6365, 3.0635)
ROUBAIX = (50.6900, 3.1630)
BOTH = lambda: {EVENTS: tf.events(), PLACES: tf.restaurants()}  # noqa: E731


def bounding(request: httpx.Request) -> str:
    return dict(request.url.params).get("geo_bounding", "")


async def test_a_cell_is_asked_by_its_bounds_never_by_the_position(tmp_path):
    api = tf.FakeApi(BOTH(), page_size=100)
    cells, tourism, _clock, _cfg = tf.make_cells(tmp_path, api)
    cell = cells.cell(*LILLE)
    count, done = await cells.load(cell, EVENTS, background=False, pages_max=5)
    assert done and count > 0
    [asked] = api.requests
    n, w, s, e = (float(v) for v in bounding(asked).split(","))
    assert (s, w, n, e) == (pytest.approx(cell.south), pytest.approx(cell.west), pytest.approx(cell.north),
                            pytest.approx(cell.east))
    assert f"{LILLE[0]}" not in str(asked.url) and "geo_distance" not in str(asked.url)
    assert "takesPlaceAt.endDate[gte]=2026-11-18" in dict(asked.url.params)["filters"]
    state = tourism.cell_states([cell.key])[(cell.key, EVENTS)]
    assert state.fetched and not state.reading and state.count == count


async def test_a_cell_read_again_drops_what_it_no_longer_gives(tmp_path):
    api = tf.FakeApi(BOTH(), page_size=100)
    cells, tourism, clock, _cfg = tf.make_cells(tmp_path, api)
    cell = cells.cell(*LILLE)
    await cells.load(cell, PLACES, background=True, pages_max=5)
    inside = [o for o in tf.restaurants() if tf._inside(o, f"{cell.north},{cell.west},{cell.south},{cell.east}")]
    assert tf.HILTON in {o["uuid"] for o in inside} and tourism.info().places == len(inside)
    api.fiches[PLACES] = [o for o in tf.restaurants() if o["uuid"] != tf.HILTON]
    clock.advance(days=8)
    await cells.load(cell, PLACES, background=True, pages_max=5)
    states = tourism.cell_states([cell.key])
    assert tourism.info().places == len(inside) - 1
    assert states[(cell.key, PLACES)].fetched.startswith("2026-11-26")


async def test_a_live_read_stops_after_a_few_pages_and_resumes_from_its_next_page(tmp_path):
    api = tf.FakeApi(BOTH(), page_size=1)
    cells, tourism, _clock, _cfg = tf.make_cells(tmp_path, api)
    cell = cells.cell(50.6377, 3.1487)  # Villeneuve-d'Ascq : Obsession, Mercredi tout est permis, Ça capte…
    await cells.ensure([cell], (EVENTS,))
    assert len(api.requests) == LIVE_PAGES[EVENTS]
    assert tourism.cell_states([cell.key])[(cell.key, EVENTS)].reading
    assert "nombreux" in cells.coverage([cell]).note
    before = len(api.requests)
    await cells.ensure([cell], (EVENTS,))
    assert "crs=" in str(api.requests[before].url)  # elle reprend à sa page suivante
    assert tourism.info().events == LIVE_PAGES[EVENTS] * 2


@pytest.fixture
async def desk(tmp_path):
    api = tf.FakeApi(BOTH(), page_size=100)
    clock = tf.Clock()
    config = [TourismConfig(api_key=tf.KEY, per_hour=50)]
    tf.write_index(tmp_path / "cartes" / "lieux.db")
    got = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, tourism=lambda: config[0], clock=clock,
                   transport=httpx.MockTransport(api), quota_now=clock.stamp, quota_sleep=clock.sleep)
    yield got, api, clock, config
    await got.close()


async def test_events_in_a_radius_load_the_cells_it_touches_nearest_first_and_once(desk):
    """La sonde réelle de L2 : à douze kilomètres de Lille, seule la case du point se lisait — Roubaix, Tourcoing et le
    LaM manquaient tant que le réchauffage n'était pas passé (ADR 0259)."""
    maps, api, _clock, _config = desk
    hits = await maps.events(near=LILLE, radius_m=12_000, limit=50)
    touched = maps.cells.area(LILLE, None, 12_000)
    assert len(touched) > 1 and touched[0] == cell_of(*LILLE, 10)  # la sienne d'abord
    assert len(api.requests) == len(touched) <= LIVE_READS_MAX  # une page par case, chacune une fois
    first = bounding(api.requests[0])
    assert first.startswith(f"{touched[0].north}")  # la case du point d'abord
    names = {h.name for h in hits}
    assert {"Julien Clerc", "Quatuor Poulenc", "Obsession"} <= names  # Roubaix, le LaM
    coverage = maps.tourism_coverage(near=LILLE, radius_m=12_000)
    assert coverage.ready and coverage.cells == coverage.loaded == len(touched) and coverage.note == ""
    assert maps.tourism_coverage(near=LILLE).cells == 1  # sans rayon : sa case
    await maps.events(near=LILLE, radius_m=12_000)
    assert len(api.requests) == len(touched)  # déjà lues : rien ne repart


async def test_beyond_its_live_bound_a_radius_is_said_read_in_part_and_read_on(desk, monkeypatch):
    maps, api, _clock, _config = desk
    monkeypatch.setattr(tourism_cells, "LIVE_READS_MAX", 3)
    await maps.events(near=LILLE, radius_m=12_000)
    touched = maps.cells.area(LILLE, None, 12_000)
    assert len(api.requests) == 3
    coverage = maps.tourism_coverage(near=LILLE, radius_m=12_000)
    assert coverage.loaded == 3 and coverage.cells == len(touched)
    assert coverage.note == f"Cette zone n'est lue qu'en partie (cases lues : 3 sur {len(touched)}) : la suite se lit " \
                            "à la prochaine recherche, ou ce soir."
    await maps.events(near=LILLE, radius_m=12_000)
    assert len(api.requests) == 6 and maps.tourism_coverage(near=LILLE, radius_m=12_000).loaded == 6  # la suite
    wide = maps.tourism_coverage(near=LILLE, radius_m=200_000)
    assert wide.cells == 0 and "trop grande" in wide.note


async def test_a_list_reads_only_the_cache_and_its_coverage_says_the_zone_is_read_in_part(desk):
    """Une liste de lieux (``around``, ``search``) ne lit que les caches : rien ne part, même sur un grand rayon ; ce
    que la base sait des lieux de ce rayon se dit (``places=True``)."""
    maps, api, _clock, _config = desk
    await maps.around(LILLE[0], LILLE[1], 12_000, limit=50)
    await maps.search("", near=LILLE, bbox=(2.9, 50.55, 3.25, 50.75), limit=50)
    assert api.requests == []
    before = maps.tourism_coverage(near=LILLE, radius_m=12_000, places=True)
    assert before.loaded == 0 and before.cells > 1 and "en partie" in before.note
    await maps.place("w100")  # sa fiche lit sa case : ses lieux et ses événements
    after = maps.tourism_coverage(near=LILLE, radius_m=12_000, places=True)
    assert after.loaded == 1 and f"(cases lues : 1 sur {after.cells})" in after.note
    ids = [h.id for h in await maps.around(LILLE[0], LILLE[1], 12_000, limit=50)]
    assert f"t:{tf.HILTON}" in ids  # ce que la case lue en a


async def test_a_place_fiche_loads_its_cell_and_finds_its_tourism_part(desk):
    maps, api, _clock, _config = desk
    resort = await maps.place("w100")
    assert resort.tourism is not None and resort.tourism.id == f"t:{tf.RESORT}"
    parts = {dict(r.url.params).get("fields", "").count("takesPlaceAt") for r in api.requests}
    assert parts == {0, 1}  # ses lieux et ses événements


async def test_the_summary_says_when_the_base_was_last_read_its_cells_included(desk):
    """R3-04 : ``GET /carte`` dit ``tourism.synced``, la dernière lecture de la base ; seule la synchronisation des
    départements la marquait — avec le cache par cases (le défaut), elle disait « jamais lue ». La plus récente des
    lectures, d'une case comme d'un département."""
    maps, _api, clock, _config = desk
    assert maps.tourism_summary()["synced"] == ""
    cell = maps.cells.cell(*LILLE)
    await maps.cells.ensure([cell], (EVENTS,))
    first = maps.tourism.cell_states([cell.key])[(cell.key, EVENTS)].fetched
    assert first and maps.tourism_summary()["synced"] == first
    clock.advance(days=2)
    await maps.cells.load(cell, EVENTS, background=True, pages_max=5)  # relue le soir
    again = maps.tourism.cell_states([cell.key])[(cell.key, EVENTS)].fetched
    assert again > first and maps.tourism_summary()["synced"] == again


async def test_without_quota_the_desk_shows_what_it_has_and_says_when_it_comes_back(desk):
    maps, api, clock, config = desk
    config[0] = TourismConfig(api_key=tf.KEY, per_hour=1)
    await maps.tourism_limiter.take()  # la seule demande de l'heure est prise
    hits = await maps.events(near=ROUBAIX, radius_m=5_000)
    assert hits == [] and api.requests == []
    note = maps.tourism_coverage(near=ROUBAIX).note
    assert "quota de l'heure de DATAtourisme est atteint : il revient à 11:00" in note
    assert "On montre ce qu'on avait" in note


async def test_the_plan_puts_their_own_cells_first_events_before_places_the_oldest_first(tmp_path):
    api = tf.FakeApi(BOTH(), page_size=100)
    cells, _tourism, clock, _cfg = tf.make_cells(tmp_path, api)
    own = cells.cell(*LILLE)
    await cells.load(own, PLACES, background=True, pages_max=5)  # ses lieux sont frais
    tasks = cells.plan([LILLE], clock())
    assert tasks[0] == WarmTask(own, EVENTS, "")
    assert all(t.cell.key != own.key or t.part != PLACES for t in tasks)  # frais : rien à faire
    ring = tasks[1:]
    assert len(ring) == 16 and [t.part for t in ring] == [EVENTS] * 8 + [PLACES] * 8
    clock.advance(days=8)
    later = cells.plan([LILLE], clock())
    assert later[0].part == EVENTS and any(t.cell.key == own.key and t.part == PLACES for t in later)


class Source:
    """Une source du réchauffage jouée : ses tâches, et ce que son quota dit à la n-ième."""

    name, label = "essai", "Essai"

    def __init__(self, tasks: int, refuse: dict[int, QuotaExceeded]) -> None:
        self.tasks = [WarmTask(cell_of(50 + k / 10, 3, 10), "lieux") for k in range(tasks)]
        self.refuse = refuse
        self.done: list[WarmTask] = []
        self.seen: list[tuple[float, float]] = []

    def ready(self) -> bool:
        return True

    def plan(self, points, now):
        self.seen = list(points)
        return list(self.tasks)

    async def warm(self, task):
        n = len(self.done)
        if n in self.refuse:
            raise self.refuse.pop(n)
        self.done.append(task)
        return 3

    def budget(self) -> str:
        return "1 demande dans l'heure sur 10"


async def test_the_warmer_goes_around_people_and_fixed_points_and_waits_for_a_quota_back_before_morning(tmp_path):
    clock = tf.Clock(datetime(2026, 11, 18, 22, 0, tzinfo=tf.PARIS))
    source = Source(4, {1: QuotaExceeded("le quota de l'heure de Essai est atteint", clock() + timedelta(hours=1),
                                         HOUR)})

    async def town(name):
        return ROUBAIX if name == "Roubaix" else None

    warmer = Warmer(tmp_path, lambda: WarmConfig(points=("Roubaix", "45.90, 6.13", "Nulle-part")),
                    points=lambda: [(50.6366, 3.0636), (50.63661, 3.06362)], resolve=town, sources=[source],
                    clock=clock,
                    sleep=clock.sleep)
    assert warmer.due(clock())
    run = await warmer.run()
    assert source.seen == [(50.637, 3.064), ROUBAIX, (45.9, 6.13)]  # Lille une fois, à cent mètres près
    assert len(source.done) == 4 and clock.slept == [3600.0]
    assert (run.sources[0].done, run.sources[0].planned, run.sources[0].fiches, run.sources[0].stopped) == (4, 4, 12, "")
    assert not warmer.due(clock())
    again = Warmer(tmp_path, lambda: WarmConfig(), sources=[source], clock=clock)  # un redémarrage
    assert again.last is not None and again.last.started == run.started and not again.due(clock())
    facts = dict(again.describe(lambda iso: iso))
    assert facts["Essai"].startswith("4 case(s) rafraîchie(s) sur 4") and "Budget de Essai" in facts
    assert facts["Prochain passage"].startswith("2026-11-19T21:00:00Z")  # 22:00 de Paris


class Locked(Source):
    """Une source dont le cache ne s'écrit pas : chaque tâche lève ``database is locked``."""

    name, label = "tenue", "Tenue"

    async def warm(self, task):
        raise sqlite3.OperationalError("database is locked")


class Buggy(Source):
    """Une source qui tombe sur une erreur imprévue."""

    name, label = "bogue", "Bogue"

    async def warm(self, task):
        raise RuntimeError("imprévu")


async def test_a_source_whose_cache_does_not_write_stops_saying_it_and_the_other_finishes(tmp_path):
    """R3-02 : une erreur de la base pendant le passage (``database is locked``, un disque plein) sortait du
    réchauffage — l'autre source continuait seule, le compte rendu s'effaçait (« autour de 0 point(s) », sans ligne par
    source). La source en panne s'arrête en le disant, comptée en erreurs ; l'autre finit ; le compte rendu des deux se
    garde. Une erreur imprévue d'une source ne fait pas tomber les autres non plus."""
    clock = tf.Clock(datetime(2026, 11, 18, 22, 0, tzinfo=tf.PARIS))
    locked, buggy, good = Locked(ERRORS_MAX + 2, {}), Buggy(2, {}), Source(3, {})
    warmer = Warmer(tmp_path, lambda: WarmConfig(), points=lambda: [LILLE], sources=[locked, buggy, good],
                    clock=clock, sleep=clock.sleep)
    run = await warmer.run()
    tenue, bogue, essai = run.sources
    assert tenue.errors == ERRORS_MAX and tenue.done == 0
    assert "ne s'écrit pas" in tenue.stopped and "database is locked" in tenue.stopped
    assert bogue.stopped and "RuntimeError" in bogue.stopped
    assert (essai.done, essai.planned, essai.stopped) == (3, 3, "") and len(good.done) == 3
    assert run.ended and not warmer.running
    again = Warmer(tmp_path, lambda: WarmConfig(), sources=[good], clock=clock)  # un redémarrage : il se relit
    assert [r.label for r in again.last.sources] == ["Tenue", "Bogue", "Essai"] and again.last.points == 1
    facts = dict(again.describe(lambda iso: iso))
    assert "arrêté : le cache ne s'écrit pas" in facts["Tenue"]


async def test_the_warmer_stops_a_source_whose_quota_comes_back_after_morning(tmp_path):
    clock = tf.Clock(datetime(2026, 11, 18, 22, 0, tzinfo=tf.PARIS))
    source = Source(3, {1: QuotaExceeded("le quota du jour de Essai est atteint : il revient demain à 21:00.",
                                         clock() + timedelta(hours=23), "jour")})
    warmer = Warmer(tmp_path, lambda: WarmConfig(), points=lambda: [LILLE], sources=[source], clock=clock,
                    sleep=clock.sleep)
    run = await warmer.run()
    assert len(source.done) == 1 and clock.slept == []
    assert "quota du jour" in run.sources[0].stopped


async def test_the_desk_warms_its_cells_on_the_background_budget(desk):
    maps, api, _clock, config = desk
    config[0] = TourismConfig(api_key=tf.KEY, per_hour=50, reserve_pct=50)
    maps.warmer.points = lambda: [LILLE]
    run = await maps.warmer.run()
    [report] = run.sources
    assert report.label == "DATAtourisme" and report.done >= 1
    assert "la part de fond du quota" in report.stopped or report.done == report.planned
    used = maps.tourism_limiter.status().windows[0].used
    assert used <= 25  # la moitié gardée au direct


def test_the_people_points_come_from_their_last_fixes(tmp_path):
    us = 1_000_000
    now = 1_800_000_000 * us
    fixes = {"web:ana": SimpleNamespace(coords_ref="c1", fixed_at=now - 3600 * us),
             "web:bob": SimpleNamespace(coords_ref="c2", fixed_at=now - 40 * 86_400 * us),  # trop vieille
             "web:cyd": SimpleNamespace(coords_ref="c3", fixed_at=now)}
    frame = SimpleNamespace(state=lambda owner: SimpleNamespace(fixes=fixes))
    kernel = SimpleNamespace(mind=SimpleNamespace(frame=lambda: frame))
    store = SimpleNamespace(content=lambda refs: {"c1": "50.636500,3.063500", "c2": "45.9,6.1", "c3": "pas un point"})
    assert last_positions(kernel, store, lambda: now) == [(50.6365, 3.0635)]


async def test_a_base_matched_without_an_index_is_matched_whole_once_the_index_comes(tmp_path):
    api = tf.FakeApi(BOTH(), page_size=100)
    index = tmp_path / "cartes" / "lieux.db"
    cells, tourism, clock, _cfg = tf.make_cells(tmp_path, api, index=index)  # pas encore d'index des lieux
    await cells.load(cells.cell(*LILLE), PLACES, background=True, pages_max=5)
    assert tourism.info().matched_with == "aucun" and tourism.info().twins == 0
    tf.write_index(index)
    await cells.load(cells.cell(*ROUBAIX), PLACES, background=True, pages_max=5)
    assert tourism.info().matched_with == "aucun"  # le neuf attend : tout se refera d'un coup
    sync, *_rest = tf.make_sync(tmp_path, api, index=index, clock=clock)
    assert await sync.rematch()
    assert tourism.info().matched_with == "2026-11-17T10:00:00Z"
    facts, uuid = await tourism.facts_for(["w100"])  # le Resort, lu sans index, a retrouvé son pendant
    assert uuid == tf.RESORT and facts is not None


class Gated:
    """La fausse API, derrière une porte : chaque page attend qu'on l'ouvre (une lecture de fond longue)."""

    def __init__(self, api: tf.FakeApi) -> None:
        self.api = api
        self.gate = asyncio.Event()
        self.asked = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked += 1
        await self.gate.wait()
        return self.api(request)


async def test_a_live_read_never_waits_for_the_evening_warming_of_its_cell(tmp_path):
    """R1-11 : une fiche ouverte pendant que le réchauffage du soir lisait sa case attendait toute la lecture de
    fond (des dizaines de pages) et héritait de son quota de fond. Elle n'attend pas : la case se montre telle
    qu'elle est, et ``coverage`` dit qu'elle se lit en ce moment ; une lecture en direct de la même case, elle, se
    partage toujours."""
    gated = Gated(tf.FakeApi(BOTH(), page_size=1))
    clock = tf.Clock()
    config = [TourismConfig(api_key=tf.KEY)]
    tourism = Tourism(tmp_path, now=clock)
    client = DataTourismeClient(lambda: config[0], tf.limiter(tmp_path, config, clock),
                                transport=httpx.MockTransport(gated))
    cells = TourismCells(tourism, lambda: config[0], client, clock=clock)
    cell = cells.cell(*LILLE)
    warming = asyncio.ensure_future(cells.warm(WarmTask(cell, PLACES, "")))
    for _ in range(200):
        if gated.asked:
            break
        await asyncio.sleep(0.01)
    assert gated.asked == 1  # le réchauffage attend sa première page
    await asyncio.wait_for(cells.ensure([cell], (PLACES,)), 1.0)
    assert gated.asked == 1  # rien de plus n'est parti : la lecture du soir continue seule
    assert "se lisent en ce moment" in cells.coverage([cell], (PLACES,)).note
    gated.gate.set()
    assert await warming >= 1


async def test_two_live_reads_of_a_cell_still_make_one(tmp_path):
    api = tf.FakeApi(BOTH())
    cells, _tourism, _clock, _cfg = tf.make_cells(tmp_path, api)
    cell = cells.cell(*LILLE)
    await asyncio.gather(cells.ensure([cell], (PLACES,)), cells.ensure([cell], (PLACES,)))
    assert len([u for u in api.urls() if "placeOfInterest" in u and "crs" not in u]) == 1
