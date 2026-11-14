"""L'index des plongements (``adapters.vectors.SqliteVectorIndex``) : les versions remplacées n'occupent pas les
résultats, la recherche sur disque rend ce que rend la mémoire vive et n'efface que les lignes remplacées, et ses
lectures sur disque passent par le fil du magasin."""

from __future__ import annotations

import pytest

from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.contracts import memory as mc
from mika.faculties.memory.consolidation import Index
from mika.faculties.memory.projections import Chunks, Items
from mika.kernel.events import Content
from mika.ports.vectors import VectorItem
from tests.fixtures.memory import event
from tests.fixtures.sqldb import SqlDB as DB


@pytest.fixture
def db():
    db = DB()
    Items().create(db, "")
    Chunks().create(db, "")
    yield db
    db.conn.close()


async def test_superseded_versions_cannot_fill_all_search_results(db):
    Items().apply(db, [event(mc.BELIEVED.draft(text=Content.of("Alice habite à Lyon"), about=("user_2",),
        replaces=i - 1 if i > 1 else None), i) for i in range(1, 102)], "")
    vectors = SqliteVectorIndex(db, HashEmbedder())
    await vectors.open()
    todo, _ = Index()._fresh(db)
    await vectors.upsert(todo)
    assert [k for k, _ in await vectors.search("Alice habite à Lyon", 40)] == [101]


async def test_disk_search_matches_ram_and_removes_only_replaced_rows(db):
    ram = SqliteVectorIndex(db, HashEmbedder(), table="ram_vectors")
    disk = SqliteVectorIndex(db, HashEmbedder(), table="disk_vectors", max_resident_vectors=10)
    for index in (ram, disk):
        await index.open()
        await index.upsert([VectorItem(i, "belief", f"Alice cultive des roses numéro {i}", (f"user_{i % 3}",))
                            for i in range(1, 2061)])  # trois blocs sur disque, avec des ex æquo entre blocs
    assert disk._spilled and disk._mat.size == 0
    for filters in ({}, {"persons": ["user_2"]}, {"keys": [1, 4, 10, 1024, 2048]}, {"kinds": ["souvenir"]}):
        left = await ram.search("roses numéro 10", 8, **filters)
        right = await disk.search("roses numéro 10", 8, **filters)
        assert [i for i, _ in left] == [i for i, _ in right]
        assert [s for _, s in left] == pytest.approx([s for _, s in right], abs=1e-6)
    assert ram.digest() == disk.digest()
    for index in (ram, disk):
        await index.remove([1, 3, 59])
        await index.forget("user_2")
    assert ram.indexed() == disk.indexed() and ram.digest() == disk.digest()
    loaded = SqliteVectorIndex(db, HashEmbedder(), table="disk_vectors", max_resident_vectors=10)
    await loaded.open()
    assert loaded._spilled and loaded._mat.size == 0 and loaded.digest() == disk.digest()


async def test_spilled_vector_reads_use_the_store_worker(tmp_path):
    import threading

    from mika.adapters.store_sql.store import SqlStore
    from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
    from mika.ports.vectors import VectorItem
    store = SqlStore(tmp_path / 'mind.db', tmp_path / 'views.db')
    await store.open()
    try:
        index = SqliteVectorIndex(store, HashEmbedder(), max_resident_vectors=1)
        await index.open()
        await index.upsert([VectorItem(i, 'belief', f'roses {i}', ('user_2',)) for i in range(3)])
        threads = []
        run = store.run_views
        async def tracked(fn):
            def execute(sql):
                threads.append(threading.get_ident())
                return fn(sql)
            return await run(execute)
        store.run_views = tracked
        assert await index.search('roses', 2)
        assert threads and all(thread != threading.get_ident() for thread in threads)
    finally:
        await store.close()
