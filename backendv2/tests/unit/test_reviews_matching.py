"""Le rapprochement d'un lieu de Google avec le sien (ADR 0250, 0256) : le lieu de l'index (OpenStreetMap) à moins de
100 m dont le nom se ressemble — la règle des données touristiques, sans accents, casse, articles ni mots de sorte
(« La Bellezza Lille » et « La Bellezza », « Maison Méert » et « Méert ») —, sinon le lieu DATAtourisme sans pendant
(``t:<uuid>``) ; un autre nom tout près, ou le même nom trop loin, n'est pas lui. Tout se rejuge quand l'index a été
reconstruit, et un lieu qui a bougé, ou qu'on n'avait rapproché de rien, à sa relecture."""

from __future__ import annotations

from datetime import date

from mika.adapters.maps.cells import cell_of
from mika.adapters.maps.datatourisme import PLACE, Fiche
from mika.adapters.maps.google_places import read_place
from mika.adapters.maps.reviews import ReviewsBase
from mika.adapters.maps.tourism import TourismBase
from tests.fixtures import google_places as gp
from tests.fixtures.tourism import write_index

ESTAMINET = "0ace7ea5-f85e-3dca-b899-c05e1cdfd16d"
MEERT_AT, BELLEZZA_AT = (50.6377202, 3.0619917), (50.6389756, 3.058805)


async def twins(rig) -> dict[str, str]:  # noqa: ANN001
    return await rig.reviews.read(lambda c: {r[0]: r[1] for r in c.execute("SELECT id, twin FROM spot")}, {})


async def load_both(rig) -> None:  # noqa: ANN001
    """Les deux cases où sont Méert et La Bellezza (la Grand-Place est au bord de la sienne)."""
    for at in (MEERT_AT, BELLEZZA_AT):
        await rig.cells.load(cell_of(*at, 3), "manger", background=True)


async def test_the_same_name_close_by_is_the_same_place(tmp_path):
    index = write_index(tmp_path / "cartes" / "lieux.db", gp.GRAND_PLACE_PLACES)
    rig = gp.rig(tmp_path, index=index)
    await load_both(rig)
    assert await twins(rig) == {gp.MEERT: "n302", gp.BELLEZZA: "n301"}


async def test_another_name_close_by_or_the_same_name_too_far_is_not(tmp_path):
    index = write_index(tmp_path / "cartes" / "lieux.db", gp.GRAND_PLACE_PLACES)
    api = gp.FakeGoogle(places=[gp.place("ChIJchezmomo1", "Chez Momo", 50.63722, 3.06333),       # 2 m de « La Chicorée »
                                gp.place("ChIJchicoree2", "La Chicorée", 50.63855, 3.06330),     # 150 m plus loin
                                gp.place("ChIJchicoree3", "Brasserie La Chicorée", 50.63760, 3.06330)])  # 45 m : elle
    rig = gp.rig(tmp_path, api, index=index)
    await rig.cells.load(rig.cells.cell(50.63720, 3.06330), "manger", background=True)
    assert await twins(rig) == {"ChIJchezmomo1": "", "ChIJchicoree2": "", "ChIJchicoree3": "n304"}


async def test_a_tourism_place_without_twin_gets_the_rating(tmp_path):
    index = write_index(tmp_path / "cartes" / "lieux.db", gp.GRAND_PLACE_PLACES)
    tourism = tmp_path / "cartes" / "tourisme.db"
    conn = TourismBase(tourism).open()
    fiche = Fiche(uuid=ESTAMINET, kind=PLACE, name="Estaminet Chez la Vieille", lat=50.6405, lon=3.0650,
                  town="Lille", category="manger", sort="restaurant", sort_fr="Restaurant")
    TourismBase.write_page(conn, [fiche], run=None, synced="2026-11-18T09:00:00Z", today=date(2026, 11, 18))
    TourismBase.match(conn, index, everything=True)
    conn.close()
    api = gp.FakeGoogle(places=[*gp.nearby(), gp.place("ChIJlavieille7", "Chez la Vieille", 50.64052, 3.06505,
                                                       rating=4.5)])
    maps, _outside, _clock, _config = gp.desk(tmp_path, api)
    await maps.review_cells.load(maps.review_cells.cell(50.64052, 3.06505), "manger", background=True)
    rows = await maps.reviews.read(lambda c: c.execute("SELECT twin FROM spot WHERE id = 'ChIJlavieille7'")
                                   .fetchone()[0], "")
    assert rows == f"t:{ESTAMINET}"
    hits = {h.id: h for h in await maps.around(*gp.GRAND_PLACE, 800)}
    assert hits[f"t:{ESTAMINET}"].rating == 4.5
    assert (await maps.place(f"t:{ESTAMINET}")).reviews.id == "ChIJlavieille7"


async def test_a_rebuilt_index_judges_everything_again(tmp_path):
    index = write_index(tmp_path / "cartes" / "lieux.db", gp.GRAND_PLACE_PLACES[3:])
    rig = gp.rig(tmp_path, index=index)
    await load_both(rig)
    assert set((await twins(rig)).values()) == {""}
    write_index(index, gp.GRAND_PLACE_PLACES, built="2026-11-18T12:00:00Z")
    conn = rig.reviews.base.open()
    rig.cells._match(conn)
    conn.close()
    assert await twins(rig) == {gp.MEERT: "n302", gp.BELLEZZA: "n301"}


async def test_a_place_that_moved_or_was_alone_is_judged_again_when_read_again(tmp_path):
    index = write_index(tmp_path / "cartes" / "lieux.db", gp.GRAND_PLACE_PLACES)
    rig = gp.rig(tmp_path, index=index)
    await load_both(rig)
    conn = rig.reviews.base.open()
    moved = next(p for p in gp.nearby() if p["id"] == gp.BELLEZZA)
    moved["location"] = {"latitude": 50.6450, "longitude": 3.0800}  # ailleurs
    ReviewsBase.write_spots(conn, [read_place(moved, "manger")], "2026-11-18T10:00:00Z")
    rig.cells._match(conn)
    conn.close()
    assert (await twins(rig))[gp.BELLEZZA] == ""
