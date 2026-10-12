"""Les deux moteurs disent la même chose (ADR 0101, point 11) : une même vie simulée — même scénario, même graine,
même horloge — vécue une fois sur SQLite, une fois sur MariaDB, laisse les mêmes lignes dans chaque table du journal
et de chaque projection (``mind`` et ``views``).

C'est le test qui attrape ce qui se trompe sans erreur : un champ JSON lu entre guillemets, une collation qui
confond deux clés, une colonne nue à côté d'un agrégat, un tri qui départage autrement, une division qui ne tombe
pas juste. Il ne tourne qu'avec ``--mariadb``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect

import mika.sim.world as sim_world
from mika.adapters.store_sql import SqlStore
from mika.app.composition import for_simulation
from mika.sim.catalog import QUICK
from mika.sim.lane import Plan, run_plan
from tests.fixtures import backend

pytestmark = [pytest.mark.slow]

#: des vies riches en mémoire, en secrets, en conversation, en vie intérieure et en courrier (pas S16 : l'empreinte
#: d'un commit de l'atelier dépend de l'heure réelle, elle change d'une vie à l'autre quel que soit le moteur)
WANTED = ("S01 longue", "S04", "S07", "S08", "S12", "S15", "S17", "S19", "S20")


def _plans() -> list[Plan]:
    return [next(p for p in QUICK if p.name.startswith(w)) for w in WANTED]


def _value(v: Any) -> Any:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, memoryview):
        return bytes(v)
    return v


def _dump(mind: Any, views: Any) -> dict[str, list[tuple[Any, ...]]]:
    """Chaque table de ``mind`` et de ``views``, ses lignes triées (l'ordre de rangement n'est pas une différence)."""

    async def read() -> dict[str, list[tuple[Any, ...]]]:
        store = SqlStore(mind, views, threaded=False)
        await store.open()
        try:
            out: dict[str, list[tuple[Any, ...]]] = {}
            for side, reader, query in (("mind", store.read_mind, store.query_mind),
                                        ("views", store.read_views, store.query_views)):
                for name in sorted(reader(lambda sql: inspect(sql.conn).get_table_names())):
                    if name == "alembic_version":
                        continue
                    rows = [tuple(_value(v) for v in r) for r in query(f"SELECT * FROM {name}")]
                    out[f"{side}.{name}"] = sorted(rows, key=repr)
            return out
        finally:
            await store.close()

    return asyncio.run(read())


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


@pytest.mark.parametrize("plan", _plans(), ids=lambda p: p.name.split(" ")[0])
def test_the_same_life_leaves_the_same_tables_on_both_engines(tmp_path: Path, plan: Plan, monkeypatch) -> None:
    if not backend.active():
        pytest.skip("la voie MariaDB (--mariadb)")
    composition, seed = for_simulation(), plan.seeds[0]

    lite = tmp_path / "sqlite"
    lite.mkdir()
    monkeypatch.setattr(sim_world, "STORES", lambda root: (root / "mind.db", root / "views.db"))
    first = run_plan(plan, composition, lite, seed)

    maria = tmp_path / "mariadb"
    maria.mkdir()
    monkeypatch.setattr(sim_world, "STORES", backend.store_targets)
    second = run_plan(plan, composition, maria, seed)

    assert [c.name for c in first.checks if not c.ok] == [c.name for c in second.checks if not c.ok]
    a = _dump(lite / "mind.db", lite / "views.db")
    b = _dump(*backend.store_targets(maria))
    assert sorted(a) == sorted(b), "les mêmes tables"
    differing = {name: (len(a[name]), len(b[name])) for name in a if a[name] != b[name]}
    if differing:
        name = next(iter(differing))
        only_a = [r for r in a[name] if r not in b[name]][:3]
        only_b = [r for r in b[name] if r not in a[name]][:3]
        pytest.fail(f"{len(differing)} table(s) diffèrent : {differing}\n{name} — seulement SQLite : {only_a}\n"
                    f"{name} — seulement MariaDB : {only_b}")
