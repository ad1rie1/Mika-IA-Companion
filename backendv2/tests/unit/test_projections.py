"""Preuve M0 — projections : un événement empoisonné est réessayé puis mis en
quarantaine, la projection continue ; une reconstruction bleu/vert donne la
même table. La quarantaine garde la cause (sans les données de l'événement), se
relit au redémarrage et suit la bascule bleu/vert (audit du 2026-11-05, C8-03)."""

from __future__ import annotations

import asyncio

from sqlalchemy import Column, insert, inspect

from mika.kernel.codec import digest
from mika.kernel.faculty import Tier
from mika.ports.journal import ProjectorQuarantine
from mika.ports.sql import HANDLE_MAX, Key, LongText, projection_table, upsert
from mika.runtime.projections import ProjectionWorker
from tests.conftest import make_mind
from tests.fixtures.projectors import with_projectors
from tests.fixtures.toys import BUMPED


def table(mind, name: str) -> list[tuple]:
    return [tuple(r) for r in mind.store.query_views(f"SELECT * FROM {name} ORDER BY 1")]


def quarantine(mind) -> list[tuple]:
    return [tuple(r) for r in mind.store.query_views("SELECT name, seq, error FROM projector_quarantine ORDER BY seq")]


async def poisoned(tmp_path, version: int = 1):
    """Un Mind dont la projection ``tally`` a sauté l'événement « poison » ; rend le Mind, le moteur et son n°."""
    mind = make_mind(tmp_path, [with_projectors(t1=version)])
    await mind.boot()
    worker = ProjectionWorker(mind)
    for who in ["alice", "bob", "poison", "alice", "carol"]:
        await mind.append([BUMPED.draft(by=1, who=who)], emitter="counter", correlation="t")
    await worker.catch_up(mind.registry.projectors["tally"])
    (seq,) = [s for name, s, _err in worker.quarantined if name == "tally"]
    return mind, worker, seq


async def test_poison_is_quarantined_and_projection_continues(tmp_path):
    mind = make_mind(tmp_path, [with_projectors(t1=1)])
    await mind.boot()
    worker = ProjectionWorker(mind)
    for who in ["alice", "bob", "poison", "alice", "carol"]:
        await mind.append([BUMPED.draft(by=1, who=who)], emitter="counter", correlation="t")
    await worker.catch_up(mind.registry.projectors["tally"])
    assert worker.quarantined and worker.quarantined[0][0] == "tally"
    rows = dict(table(mind, "tally_v1"))
    assert rows == {"alice": 2, "bob": 1, "carol": 1}
    assert worker.lag()["tally"] == 0
    q = mind.store.query_views("SELECT name, seq FROM projector_quarantine")
    assert len(q) == 1
    # l'erreur gardée dit la cause réelle, en mémoire comme dans la table — pas seulement « échec après 3 essais »
    assert "événement empoisonné" in worker.quarantined[0][2]
    assert worker.quarantined[0][2].startswith("après 3 essais : ")
    assert "événement empoisonné" in quarantine(mind)[0][2]
    await mind.close()


async def test_quarantine_is_reloaded_by_a_new_worker(tmp_path):
    mind, worker, seq = await poisoned(tmp_path)
    # la ligne d'une projection disparue du registre ne revient pas
    await mind.store.run_views(lambda sql: upsert(
        sql, ProjectorQuarantine, {"name": "disparue", "seq": 1, "error": "ancienne"}, keys=["name", "seq"]))
    restarted = ProjectionWorker(mind)
    await restarted.catch_up(mind.registry.projectors["tally"])
    assert restarted.quarantined == worker.quarantined == [("tally", seq, worker.quarantined[0][2])]
    assert "événement empoisonné" in restarted.quarantined[0][2]
    await mind.close()


async def test_blue_green_switch_carries_the_new_version_quarantine(tmp_path):
    mind, _worker, seq = await poisoned(tmp_path, version=1)
    # un échec propre à l'ancienne version (sur un événement que la nouvelle applique) : il ne lui survit pas
    await mind.store.run_views(lambda sql: upsert(
        sql, ProjectorQuarantine, {"name": "tally", "seq": seq - 1, "error": "ancienne version"},
        keys=["name", "seq"]))
    await mind.close()

    mind2 = make_mind(tmp_path, [with_projectors(t1=2)])
    await mind2.boot(append_boot=False)
    worker = ProjectionWorker(mind2)
    await worker.catch_up(mind2.registry.projectors["tally"])
    assert mind2.store.projector_state("tally") == (2, mind2.head)
    rows = quarantine(mind2)
    assert [(name, s) for name, s, _err in rows] == [("tally", seq)]  # sous son nom, pas « tally@2 »
    assert "événement empoisonné" in rows[0][2]
    assert worker.quarantined == rows
    await mind2.close()


def _doubles(sfx: str):
    return projection_table(f"doubles{sfx}", Column("who", Key(HANDLE_MAX), primary_key=True),
                            Column("body", LongText))


class Doubles:
    """T1 : une ligne par personne, insérée sans repli : le deuxième événement d'une même personne heurte la clé,
    et l'erreur de la base porte la ligne refusée dans ses paramètres liés."""

    def create(self, sql, sfx: str) -> None:
        sql.create(_doubles(sfx))

    def drop(self, sql, sfx: str) -> None:
        sql.drop(_doubles(sfx))

    def apply(self, sql, events, sfx: str) -> None:
        for e in events:
            sql.execute(insert(_doubles(sfx)).values(who=e.data.who, body=f"secret de {e.data.who}"))


async def test_quarantine_keeps_no_event_data_from_a_database_error(tmp_path):
    # la cause gardée se garde sans limite de durée et l'oubli ne la parcourt pas : rien de l'événement n'y entre
    fac = with_projectors()
    fac.projector("doubles", version=1, tier=Tier.T1, types=[BUMPED])(Doubles)
    mind = make_mind(tmp_path, [fac])
    await mind.boot()
    worker = ProjectionWorker(mind)
    for _ in range(2):
        await mind.append([BUMPED.draft(by=1, who="bob")], emitter="counter", correlation="t")
    await worker.catch_up(mind.registry.projectors["doubles"])
    rows = quarantine(mind)
    assert [(name, s) for name, s, _err in rows] == [("doubles", mind.head)]
    assert worker.quarantined == rows
    error = rows[0][2]
    assert error.startswith("après 3 essais : erreur de la base (IntegrityError")  # la nature de la panne reste dite
    assert "bob" not in error and "secret" not in error and "[SQL" not in error, error
    await mind.close()


async def test_blue_green_rebuild_gives_the_same_table(tmp_path):
    v1 = with_projectors(t1=1)
    mind = make_mind(tmp_path, [v1])
    await mind.boot()
    for i in range(40):
        await mind.append([BUMPED.draft(by=i % 3 + 1, who=f"p{i % 5}")], emitter="counter", correlation="t")
    await ProjectionWorker(mind).catch_up(mind.registry.projectors["tally"])
    before = digest(table(mind, "tally_v1"))
    await mind.close()

    mind2 = make_mind(tmp_path, [with_projectors(t1=2)])
    await mind2.boot(append_boot=False)
    worker = ProjectionWorker(mind2)
    await worker.catch_up(mind2.registry.projectors["tally"])
    assert mind2.store.projector_state("tally") == (2, mind2.head)
    assert digest(table(mind2, "tally_v2")) == before
    tables = set(mind2.store.read_views(lambda sql: inspect(sql.conn).get_table_names()))
    assert "tally_v1" not in tables  # l'ancienne version est abandonnée après bascule
    await mind2.close()


async def test_t2_runs_prepare_outside_writer(tmp_path):
    mind = make_mind(tmp_path, [with_projectors(t2=True)])
    await mind.boot()
    for i in range(5):
        await mind.append([BUMPED.draft(by=1, who="x")], emitter="counter", correlation="t")
    worker = ProjectionWorker(mind)
    await asyncio.wait_for(worker.catch_up(mind.registry.projectors["heavy"]), timeout=30)
    assert len(table(mind, "heavy_v1")) == 5
    await mind.close()
