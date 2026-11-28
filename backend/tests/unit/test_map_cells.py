"""La grille des caches de la carte (ADR 0245) : une position tombe toujours dans la même case, qui la contient, sous
une clé qui ne change pas ; ses voisines l'entourent ; une zone trop grande ne se découpe pas."""

from __future__ import annotations

import math

from mika.adapters.maps.cells import cell_of, cells_in, neighbours

LILLE = (50.6365, 3.0635)


def test_a_point_falls_in_one_cell_that_holds_it_under_a_stable_key():
    cell = cell_of(*LILLE, 10)
    assert cell.south <= LILLE[0] < cell.north and cell.west <= LILLE[1] < cell.east
    assert cell == cell_of(LILLE[0] + 0.001, LILLE[1] + 0.001, 10) or cell.key != cell_of(*LILLE, 5).key
    assert cell_of(*LILLE, 10).key == cell.key and cell.key.startswith("10:")
    height_km = (cell.north - cell.south) * 111.2
    width_km = (cell.east - cell.west) * 111.2 * math.cos(math.radians(cell.center[0]))
    assert 9.5 < height_km < 10.5 and 9 < width_km < 11


def test_the_neighbours_surround_the_cell():
    cell = cell_of(*LILLE, 10)
    around = neighbours(cell, 10)
    assert len(around) == 8 and cell.key not in {c.key for c in around}
    lat, lon = cell.center
    dlat, dlon = cell.north - cell.south, cell.east - cell.west
    assert {cell_of(lat + dlat, lon, 10).key, cell_of(lat, lon - dlon, 10).key} <= {c.key for c in around}


def test_a_zone_is_cut_into_its_cells_unless_it_is_too_big():
    small = cells_in((3.0, 50.6, 3.1, 50.65), 10, 4)
    assert small and len(small) <= 4 and cell_of(50.62, 3.05, 10).key in {c.key for c in small}
    assert cells_in((2.0, 49.0, 4.0, 51.0), 10, 4) is None
