"""La synchronisation des données touristiques (ADR 0245), contre une fausse API de DATAtourisme : paginée par ``next``
(son curseur suivi tel quel, la clé jamais dans l'adresse), reprise là où elle s'est arrêtée, incrémentale par
``lastUpdate``, complète qui efface ce qu'elle ne voit plus, cadencée (par heure, comptée dans la base, et par
seconde), ses erreurs dites en mots, la clé jamais écrite ; un verrou ; ce qui est dû, et quand."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import httpx
import pytest

from mika.adapters.maps import datatourisme as dt
from mika.adapters.maps import desk as desk_module
from mika.adapters.maps.config import DEPARTMENTS, TOURISM_FILE, PlacesConfig, RoutingConfig, TourismConfig
from mika.adapters.maps.desk import MapsDesk
from mika.adapters.maps.tourism_sync import ALL_PARTS, COMPLETE, INCREMENTAL, SyncBusy, SyncLock, last_slot
from mika.app import cli
from mika.app.domains.maps import cli as cli_maps
from mika.ports.maps import MapsUnavailable
from tests.fixtures import tourism as tf

BOTH = lambda: {dt.EVENTS: tf.events(), dt.PLACES: tf.restaurants()}  # noqa: E731


def rows(data, sql: str, *args):
    conn = sqlite3.connect(data / TOURISM_FILE)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def uuids(data, kind: str) -> set[str]:
    return {r[0] for r in rows(data, "SELECT uuid FROM fiche WHERE kind = ?", kind)}


async def test_a_complete_sync_follows_every_next_page_and_writes_every_fiche(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, tourism, _clock, _cfg = tf.make_sync(tmp_path, api)
    report = await sync.run()
    assert report.kind == COMPLETE and report.fiches == len(tf.events()) + len(tf.restaurants())
    assert report.pages > 4 and report.unread == 0
    assert len(uuids(tmp_path, "event")) == len(tf.events()) and len(uuids(tmp_path, "place")) == 8
    # chaque page suivante, telle que l'API l'a donnée — mais en https, et sans la clé qu'elle y avait mise
    followed = [u for u in api.urls() if "crs=" in u]
    assert followed and all(u.startswith("https://api.datatourisme.fr/v1/") and "api_key" not in u for u in followed)
    # la clé dans l'en-tête, jamais dans une adresse
    assert all(r.headers["x-api-key"] == tf.KEY and tf.KEY not in str(r.url) for r in api.requests)
    first = [dict(r.url.params) for r in api.requests if "crs" not in r.url.params]
    assert first[0]["page_size"] == "100" and first[0]["lang"] == "fr" and "takesPlaceAt" in first[0]["fields"]
    # un département à la fois, les événements pas finis et commencés avant l'horizon
    assert first[0]["filters"] == ("isLocatedAt.address.hasAddressCity.isPartOfDepartment.insee[eq]=59 AND "
                                   "takesPlaceAt.endDate[gte]=2026-11-18 AND takesPlaceAt.startDate[lte]=2027-02-16")
    assert first[1]["filters"] == "isLocatedAt.address.hasAddressCity.isPartOfDepartment.insee[eq]=59"
    info = tourism.info()
    assert info.ready and info.last_kind == COMPLETE and info.last_full and not info.run


async def test_all_of_france_goes_department_by_department_then_those_without_one(tmp_path):
    api = tf.FakeApi({dt.EVENTS: [], dt.PLACES: tf.restaurants()})
    sync, _tourism, _clock, _cfg = tf.make_sync(tmp_path, api, cfg=TourismConfig(api_key=tf.KEY, zones=("France",)))
    await sync.run()
    asked = api.filters()
    assert len(asked) == 2 * len(ALL_PARTS) == 2 * (len(DEPARTMENTS) + 1)  # chacun, puis « sans département »
    assert asked[0].startswith(f"{dt.DEPARTMENT_FIELD}[eq]=01") and f"{dt.DEPARTMENT_FIELD}[eq]=2A" in asked
    assert asked[len(DEPARTMENTS)].startswith(f"{dt.DEPARTMENT_FIELD}[exists]=false")
    assert len(uuids(tmp_path, "place")) == 8


async def test_an_interrupted_complete_sync_resumes_where_it_stopped(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, tourism, _clock, _cfg = tf.make_sync(tmp_path, api)
    api.statuses = [None, None, 503]  # la troisième page : le serveur en panne
    with pytest.raises(dt.TourismUnavailable) as caught:
        await sync.run()
    assert caught.value.kind == dt.SERVER and "HTTP 503" in str(caught.value)
    kept = uuids(tmp_path, "event")
    assert len(kept) == 6 and tourism.info().run  # deux pages écrites, la synchronisation à reprendre
    assert "HTTP 503" in tourism.info().last_error
    before = len(api.requests)
    report = await sync.run()
    assert report.resumed and report.kind == COMPLETE
    resumed = api.requests[before]
    assert "crs=" in str(resumed.url)  # reprise à la page suivante, pas au début
    assert len(uuids(tmp_path, "event")) == len(tf.events()) and not tourism.info().run
    assert not tourism.info().last_error


async def test_a_cursor_the_api_no_longer_knows_restarts_its_department(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, _tourism, _clock, _cfg = tf.make_sync(tmp_path, api)
    api.statuses = [None, 502]
    with pytest.raises(dt.TourismUnavailable):
        await sync.run()
    api.cursors.clear()  # le curseur a expiré entre-temps
    before = len(api.requests)
    await sync.run()
    assert "crs=" in str(api.requests[before].url) and "crs=" not in str(api.requests[before + 1].url)
    assert len(uuids(tmp_path, "event")) == len(tf.events())


async def test_an_incremental_sync_asks_only_what_changed_since_the_day_before(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, tourism, clock, _cfg = tf.make_sync(tmp_path, api)
    await sync.run()
    clock.advance(days=1)
    changed = [dict(o) for o in tf.restaurants()[:1]]
    changed[0]["label"] = {"@fr": "Resort Barrière Lille (rénové)"}
    changed[0]["lastUpdate"] = "2026-11-19"
    api.fiches[dt.PLACES] = changed + tf.restaurants()[1:]
    before = len(api.requests)
    report = await sync.run()
    assert report.kind == INCREMENTAL
    asked = [dict(r.url.params)["filters"] for r in api.requests[before:] if "crs" not in r.url.params]
    assert asked[1] == f"{dt.DEPARTMENT_FIELD}[in]=59 AND lastUpdate[gte]=2026-11-17"
    assert "lastUpdate[gte]=2026-11-17" in asked[0] and "takesPlaceAt.endDate[gte]=2026-11-19" in asked[0]
    assert rows(tmp_path, "SELECT name FROM fiche WHERE uuid = ?", tf.RESORT) == [("Resort Barrière Lille (rénové)",)]
    assert tourism.info().last_kind == INCREMENTAL


async def test_a_complete_sync_removes_what_it_no_longer_sees_and_events_that_are_over(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, _tourism, clock, _cfg = tf.make_sync(tmp_path, api)
    await sync.run()
    api.fiches[dt.PLACES] = [o for o in tf.restaurants() if o["uuid"] != tf.HILTON]
    clock.advance(days=8)
    report = await sync.run()
    assert report.kind == COMPLETE and report.removed >= 1
    assert tf.HILTON not in uuids(tmp_path, "place")
    # le 26 novembre : Julien Clerc (le 22) est passé, ses dates aussi
    assert tf.JULIEN_CLERC not in uuids(tmp_path, "event")
    assert rows(tmp_path, "SELECT COUNT(*) FROM occurrence WHERE day1 < '2026-11-26'") == [(0,)]


async def test_the_hourly_cap_holds_a_complete_sync_which_waits_and_goes_on(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, _tourism, clock, cfg = tf.make_sync(tmp_path, api)
    cfg[0] = TourismConfig(api_key=tf.KEY, zones=("59",), per_hour=4, reserve_pct=25)
    await sync.run()
    assert [s for s in clock.slept if s > 1000], "la quatrième demande de fond de l'heure attend"
    assert len(uuids(tmp_path, "event")) == len(tf.events())
    # la synchronisation est un travail de fond : la réserve (une demande sur quatre) reste au direct
    assert sync.client.limiter.status().windows[0].kept == 1


@pytest.mark.parametrize(("status", "kind", "words"), [
    (401, dt.AUTH, "refuse la clé"), (403, dt.AUTH, "refuse la clé"), (429, dt.BUSY, "demande d'attendre"),
    (500, dt.SERVER, "en panne"), (503, dt.SERVER, "en panne"), ("broken", dt.BROKEN, "illisible"),
    (400, dt.REFUSED, "refuse la demande"),
])
async def test_every_error_is_said_in_words_and_never_carries_the_key(tmp_path, caplog, status, kind, words):
    caplog.set_level(logging.DEBUG)
    api = tf.FakeApi(BOTH(), statuses=[status])
    sync, tourism, clock, _cfg = tf.make_sync(tmp_path, api)
    with pytest.raises(dt.TourismUnavailable) as caught:
        await sync.run()
    assert caught.value.kind == kind and words in str(caught.value)
    sync.failed(caught.value, clock())
    assert sync.retry_at is not None and sync.retry_at > clock()
    said = caplog.text + str(caught.value) + json.dumps(rows(tmp_path, "SELECT key, value FROM meta"))
    assert tf.KEY not in said
    assert tf.KEY not in (tmp_path / TOURISM_FILE).read_bytes().decode("utf-8", "replace")


async def test_a_page_beyond_the_api_or_a_page_already_read_is_refused(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, _tourism, _clock, _cfg = tf.make_sync(tmp_path, api)
    with pytest.raises(dt.TourismUnavailable) as caught:
        await sync.client.follow("https://ailleurs.exemple/v1/placeOfInterest?crs=x")
    assert caught.value.kind == dt.BROKEN
    assert sync.client.next_url("http://api.datatourisme.fr/v1/catalog?crs=a&api_key=k") == \
        "https://api.datatourisme.fr/v1/catalog?crs=a"


async def test_without_a_key_nothing_is_asked(tmp_path, monkeypatch):
    api = tf.FakeApi(BOTH())
    sync, _tourism, clock, cfg = tf.make_sync(tmp_path, api, cfg=TourismConfig(zones=("59",)))
    with pytest.raises(dt.TourismUnavailable) as caught:
        await sync.run()
    assert caught.value.kind == dt.AUTH and api.requests == []
    assert sync.due(clock()) is None and sync.wake()[0] == "danger"
    # la variable d'environnement prend le relais d'un réglage vide
    monkeypatch.setenv("MIKA_DATATOURISME_API_KEY", tf.KEY)
    await sync.run()
    assert api.requests and api.requests[0].headers["x-api-key"] == tf.KEY


async def test_two_syncs_never_write_at_the_same_time(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, tourism, _clock, _cfg = tf.make_sync(tmp_path, api)
    held = SyncLock(tourism.path.with_name("tourisme.lock"))
    assert held.acquire()
    try:
        with pytest.raises(SyncBusy):
            await sync.run()
        assert api.requests == []
    finally:
        held.release()
    await sync.run()


async def test_what_is_due_and_when(tmp_path):
    api = tf.FakeApi(BOTH())
    sync, _tourism, clock, cfg = tf.make_sync(tmp_path, api, cfg=TourismConfig(api_key=tf.KEY))
    assert sync.due(clock()) is None and sync.next_at(clock()) is None  # aucun département : le cache par cases
    assert sync.wake()[0] == "info"
    with pytest.raises(ValueError):
        await sync.run()
    cfg[0] = TourismConfig(api_key=tf.KEY, zones=("59",))
    assert sync.due(clock()) == COMPLETE  # jamais synchronisés
    await sync.run()
    assert sync.due(clock()) is None
    upcoming = sync.next_at(clock())
    assert upcoming is not None and upcoming.astimezone(tf.PARIS).hour == 4 and upcoming.day == 19
    clock.advance(hours=18, minutes=30)  # le 19 à 04:30 : la nuit
    assert sync.due(clock()) == INCREMENTAL
    clock.advance(days=7)  # une semaine après la dernière complète : la nuit, une complète
    assert sync.due(clock()) == COMPLETE
    clock.advance(days=-7)
    cfg[0] = TourismConfig(api_key=tf.KEY, zones=("59", "62"))  # d'autres zones : une complète, tout de suite
    assert sync.due(clock()) == COMPLETE


async def test_after_an_error_it_waits_then_a_new_key_or_a_button_tries_again(tmp_path):
    api = tf.FakeApi(BOTH(), statuses=[401])
    sync, _tourism, clock, cfg = tf.make_sync(tmp_path, api)
    with pytest.raises(dt.TourismUnavailable) as caught:
        await sync.run()
    sync.failed(caught.value, clock())
    assert sync.due(clock()) is None and sync.next_at(clock()) == sync.retry_at
    cfg[0] = TourismConfig(api_key="une-autre-cle", zones=("59",))
    assert sync.due(clock()) == COMPLETE  # une autre clé : on réessaie
    api.statuses = [429]
    with pytest.raises(dt.TourismUnavailable) as caught:
        await sync.run()
    sync.failed(caught.value, clock())
    assert sync.retry_at == clock() + timedelta(seconds=900)
    sync._worker = asyncio.get_running_loop().create_future()  # comme lancée par le serveur
    try:
        assert sync.wake()[0] == "ok" and sync.due(clock()) == COMPLETE
    finally:
        sync._worker.cancel()
        sync._worker = None


def test_the_night_slot_is_in_paris_time():
    assert last_slot(tf.NOW, 4).hour == 4 and last_slot(tf.NOW, 4).day == 18
    assert last_slot(tf.NOW, 23).day == 17


@pytest.mark.parametrize(("status", "gone"), [(400, False), (403, False), (500, False), (404, True), (410, True)])
async def test_a_fiche_refused_is_kept_only_a_vanished_one_is_forgotten(tmp_path, status, gone):
    """R1-14 : un 400 de ``/catalog/{uuid}`` (un ``fields`` qu'elle refuse depuis un changement de son API) était pris
    pour « elle n'existe plus », et la fiche s'effaçait avec ses photos. Seuls 404 et 410 disent qu'elle est partie ;
    le reste est un refus, en mots, et la fiche reste."""
    api = tf.FakeApi(BOTH())
    sync, _tourism, _clock, _cfg = tf.make_sync(tmp_path, api)
    await sync.run()
    assert await sync.refresh(tf.KREVETTE)  # la vraie : relue
    api.statuses = [status]
    if gone:
        assert await sync.refresh(tf.KREVETTE) is False
    else:
        with pytest.raises(dt.TourismUnavailable):
            await sync.refresh(tf.KREVETTE)
    assert (tf.KREVETTE in uuids(tmp_path, "place")) is not gone


@dataclass
class Reshaped(tf.FakeApi):
    """La fausse API, dont un ``/catalog/{uuid}`` en 200 rend autre chose que la fiche nue (``shape`` : ce qu'il rend
    à la place)."""

    shape: Callable[[dict], object] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        got = super().__call__(request)
        if self.shape is not None and "/catalog/" in request.url.path and got.status_code == 200:
            return httpx.Response(200, json=self.shape(got.json()))
        return got


@pytest.mark.parametrize("shape", [lambda o: {"objects": [o]}, lambda o: {}, lambda o: [o],
                                   lambda o: {**{k: v for k, v in o.items() if k != "uuid"}, "id": o["uuid"]},
                                   lambda o: {**o, "uuid": "00000000-0000-0000-0000-000000000000"}],
                         ids=["enveloppe", "vide", "liste", "uuid-renomme", "autre-fiche"])
async def test_a_fiche_answered_but_unreadable_is_kept_not_forgotten(tmp_path, shape):
    """R3-09 : un 200 de ``/catalog/{uuid}`` sans la fiche demandée (enveloppée comme une liste, un champ renommé, un
    corps vide) se lisait « elle n'existe plus » — la fiche s'effaçait avec ses photos et ses occurrences, et
    « Actualiser » disait « Fiche relue. ». Seuls 404 et 410 disent qu'elle est partie : ceci est une réponse
    illisible, en mots, et la fiche reste."""
    api = Reshaped(BOTH())
    sync, _tourism, _clock, _cfg = tf.make_sync(tmp_path, api)
    await sync.run()
    assert await sync.refresh(tf.KREVETTE)  # la vraie : relue
    api.shape = shape
    with pytest.raises(dt.TourismUnavailable) as caught:
        await sync.refresh(tf.KREVETTE)
    assert "illisible" in str(caught.value)
    assert tf.KREVETTE in uuids(tmp_path, "place")


async def test_a_fiche_read_a_moment_ago_is_not_asked_again_at_datatourisme(tmp_path):
    """R1-05 : « Actualiser » relisait la fiche DATAtourisme à chaque clic. Lue il y a moins de dix minutes, elle ne
    repart pas ; au-delà, oui."""
    index = tf.write_index(tmp_path / "cartes" / "lieux.db")
    api = tf.FakeApi(BOTH())
    sync, _tourism, clock, config = tf.make_sync(tmp_path, api, index=index)
    await sync.run()
    desk = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, tourism=lambda: config[0], clock=clock,
                    transport=httpx.MockTransport(api), quota_now=clock.stamp, quota_sleep=clock.sleep)
    try:
        def catalog() -> int:
            return sum("/catalog/" in u for u in api.urls())

        got = await desk.place_refresh("n101")  # Krevette : sa fiche vient d'être lue par la synchronisation
        assert got.detail.tourism.id == f"t:{tf.KREVETTE}" and got.said.startswith("Relue à l'instant")
        assert catalog() == 0
        clock.advance(minutes=11)
        assert (await desk.place_refresh("n101")).said == "Fiche relue." and catalog() == 1
        clock.advance(minutes=3)
        assert (await desk.place_refresh("n101")).said.startswith("Relue il y a 3 min") and catalog() == 1
    finally:
        await desk.close()


async def test_a_refresh_held_by_datatourisme_does_not_take_a_server_turn(tmp_path, monkeypatch):
    """R3-01 : DATAtourisme a demandé d'attendre (son recul après un 429) — « Actualiser » ne part pas, le dit, et ne
    prend pas un des tours de tout le serveur."""
    monkeypatch.setattr(desk_module, "REFRESHES_PER_DAY", 1)
    index = tf.write_index(tmp_path / "cartes" / "lieux.db")
    api = tf.FakeApi(BOTH())
    sync, _tourism, clock, config = tf.make_sync(tmp_path, api, index=index)
    await sync.run()
    desk = MapsDesk(tmp_path, PlacesConfig, RoutingConfig, tourism=lambda: config[0], clock=clock,
                    transport=httpx.MockTransport(api), quota_now=clock.stamp, quota_sleep=clock.sleep)
    try:
        def catalog() -> int:
            return sum("/catalog/" in u for u in api.urls())

        assert (await desk.place_refresh("n101")).said.startswith("Relue à l'instant")  # sa case lue, à jour
        clock.advance(minutes=11)
        desk.tourism_limiter.back_off(600)
        for _ in range(2):
            with pytest.raises(MapsUnavailable) as caught:
                await desk.place_refresh("n101")
            assert "DATAtourisme a demandé d'attendre" in str(caught.value)
            assert "ce serveur" not in str(caught.value)
        assert catalog() == 0
        clock.advance(minutes=11)
        assert (await desk.place_refresh("n101")).said == "Fiche relue." and catalog() == 1
    finally:
        await desk.close()


async def test_a_base_of_another_version_is_remade_not_converted(tmp_path):
    path = tmp_path / TOURISM_FILE
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('version', '0')")
    conn.commit()
    conn.close()
    sync, tourism, _clock, _cfg = tf.make_sync(tmp_path, tf.FakeApi(BOTH()))
    assert not tourism.ready()
    await sync.run()
    assert tourism.ready() and tourism.info().events


def test_the_command_syncs_a_folder_without_a_mika_with_the_key_of_the_environment(tmp_path, capsys, monkeypatch):
    api = tf.FakeApi(BOTH())
    real = cli_maps.DataTourismeClient
    monkeypatch.setattr(cli_maps, "DataTourismeClient",
                        lambda config, limiter: real(config, limiter, transport=httpx.MockTransport(api)))
    assert cli.main(["--data", str(tmp_path), "carte", "tourisme", "--zones", "59"]) == 1  # aucune clé
    said = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert said["ok"] is False and "MIKA_DATATOURISME_API_KEY" in said["erreur"] and api.requests == []
    monkeypatch.setenv("MIKA_DATATOURISME_API_KEY", tf.KEY)
    assert cli.main(["--data", str(tmp_path), "carte", "tourisme"]) == 1  # aucun département
    said = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "Aucun département" in said["erreur"] and api.requests == []
    assert cli.main(["--data", str(tmp_path), "carte", "tourisme", "--zones", "59", "--horizon", "60"]) == 0
    out = capsys.readouterr().out
    said = json.loads(out.strip().splitlines()[-1])
    assert said["ok"] is True and said["sorte"] == "complète" and said["clé"] == "variable d'environnement"
    assert said["événements"] > 10 and said["lieux"] == 8 and said["zones"] == ["59"]
    assert tf.KEY not in out
    assert "takesPlaceAt.startDate[lte]=" in api.filters()[0]
    assert not (tmp_path / "mind.db").exists() and not (tmp_path / "secret.key").exists()  # rien d'autre n'est né
