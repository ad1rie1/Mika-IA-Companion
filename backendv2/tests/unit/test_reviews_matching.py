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


#: les vrais cas de la sonde du 2026-11-20 (``sonde/data/cartes/avis.db``, R1-02) : des lieux de l'index tout près de
#: lieux de Google, aux positions réelles — (osm, nom, sorte, catégorie, lat, lon)
SONDE_PLACES = (
    ("w45895545", "BNP Paribas", "bank", "services", 50.6363932, 3.0628541),
    ("n9722004201", "Parking Grand Place", "parking", "route", 50.6370583, 3.0633047),
    ("n5761496453", "Le Beffroi", "restaurant", "manger", 50.6375022, 3.0641179),
    ("n1559451471", "Médiathèque du Vieux Lille", "library", "sortir", 50.640948, 3.064544),
    ("w40848253", "Beffroi de Lille", "attraction", "voir", 50.6306325, 3.0697915),
    ("r288199", "Maison Meert", "attraction", "voir", 50.6375645, 3.0615961),
    ("n10996980643", "Mamatte", "bakery", "courses", 50.6355377, 3.063366),
    ("n13283410235", "Magmatic", "restaurant", "manger", 50.6362561, 3.0674061),
    ("r11371717", "Opéra de Lille", "theatre", "sortir", 50.6375261, 3.0651522),
    ("w23475365", "Parc Henri Matisse", "park", "nature", 50.6405634, 3.072453),
    ("w45822366", "Théâtre du Nord", "theatre", "sortir", 50.6361486, 3.064029),
)
#: les lieux de Google de la sonde (id, nom, type premier, sorte, lat, lon) et le pendant attendu ('' : aucun)
SONDE_SPOTS = (
    ("ChIJbarparibas", "BAR PARIBAS", "bar", "manger", 50.636564, 3.063192, ""),               # pas la banque
    ("ChIJgrandplace", "Grand Place", "historical_landmark", "voir", 50.63684, 3.063501, ""),   # pas le parking
    ("ChIJbeffroicci", "Beffroi de la Chambre de Commerce de Lille", "historical_landmark", "voir", 50.637675,
     3.064511, ""),                                                                            # pas le restaurant
    ("ChIJvieuxlille", "Le Vieux Lille", "visitor_center", "voir", 50.640499, 3.064246, ""),    # pas la médiathèque
    ("ChIJbeffroihdv", "Beffroi de l'Hôtel de Ville de Lille", "historical_landmark", "voir", 50.630668, 3.069767,
     "w40848253"),
    ("ChIJmaisonmeert", "Maison Méert", "pastry_shop", "manger", 50.63772, 3.061992, "r288199"),  # le même nom
    ("ChIJmamatte", "Mamatte Lille Rihour - Café & Brunch", "brunch_restaurant", "manger", 50.63555, 3.063334,
     "n10996980643"),                                                                          # une boulangerie
    ("ChIJmagmatic", "Magmatic by Ephemera", "restaurant", "manger", 50.636288, 3.067431, "n13283410235"),
    ("ChIJopera", "Opéra de Lille", "opera_house", "voir", 50.6377, 3.065262, "r11371717"),      # une salle
    ("ChIJmatisse", "Parc Henri Matisse", "park", "voir", 50.639919, 3.072903, "w23475365"),
    ("ChIJtheatrenord", "Théâtre du Nord", "performing_arts_theater", "voir", 50.636286, 3.06398, "w45822366"),
)


async def test_a_place_of_another_sort_never_takes_the_rating_of_one_under_a_like_name(tmp_path):
    """La sonde (R1-02) : « BAR PARIBAS » avait les avis de la banque « BNP Paribas », la Grand-Place ceux du parking,
    le beffroi de la Chambre de Commerce ceux du restaurant « Le Beffroi » — un nom dans l'autre ne suffit plus : une
    banque, un parking, une gare ne sont le pendant de rien, et sous des noms qui ne sont pas les mêmes, la sorte doit
    aller (un restaurant et une boulangerie, ce qui se visite et un parc ou une salle). Les bons rapprochements
    restent."""
    index = write_index(tmp_path / "cartes" / "lieux.db", SONDE_PLACES)
    api = gp.FakeGoogle(places=[gp.place(sid, name, lat, lon, primary=primary)
                                for sid, name, primary, _sort, lat, lon, _twin in SONDE_SPOTS])
    rig = gp.rig(tmp_path, api, index=index)
    for sort in ("manger", "voir"):
        for cell in {cell_of(lat, lon, 3).key: cell_of(lat, lon, 3) for *_r, lat, lon, _t in SONDE_SPOTS}.values():
            await rig.cells.load(cell, sort, background=True)
    assert await twins(rig) == {sid: twin for sid, *_r, twin in SONDE_SPOTS}
    assert await rig.reviews.noted(["w45895545", "n9722004201", "n5761496453", "n1559451471"]) == {}


async def test_a_cache_matched_under_the_former_rule_is_judged_again(tmp_path):
    """Un cache rapproché avant la règle de la sorte (R1-02 : seule la date de l'index dans ``matched_with``) se rejuge
    en entier au prochain passage : « BAR PARIBAS » quitte la banque."""
    spot = next(s for s in SONDE_SPOTS if s[1] == "BAR PARIBAS")
    maps, _outside, _clock, _config = gp.desk(tmp_path, gp.FakeGoogle(places=[]), places=SONDE_PLACES)
    conn = maps.reviews.base.open()
    try:
        ReviewsBase.write_spots(conn, [read_place(gp.place(spot[0], spot[1], spot[4], spot[5], primary=spot[2]),
                                                  "manger")], "2026-11-20T10:00:00Z")
        conn.execute("UPDATE spot SET twin = 'w45895545', twin_m = 30")
        ReviewsBase.set_meta(conn, {"matched_with": maps.places.info().built})  # la date seule : la règle d'avant
        maps.review_cells._match(conn)
    finally:
        conn.close()
    assert await twins(maps) == {spot[0]: ""}


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
