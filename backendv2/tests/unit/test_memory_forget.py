"""Oublier pour de bon : la ligne de commande passe par le même chemin que la
console (contenus, projections, traces d'épisode, vecteurs), et l'index des
vecteurs, qui n'est qu'un cache, perd ce que la mémoire a perdu. Ce qu'une
personne a confié sur une autre s'oublie avec elle."""

from __future__ import annotations

import asyncio
import json
import sqlite3

from mika.app import cli
from mika.contracts import memory as memory_c
from mika.runtime.traces import TABLE as TRACES
from mika.sim.clock import run_virtual
from mika.vocab.people import named_label
from tests.fixtures.memory import SIX, Script, chat, seq_of, token
from tests.fixtures.mika import boot, build, connect


def extract(prompt):
    body = prompt.split("Les messages :")[-1]
    if "CANARI-OUBLI" in body:
        return {"souvenirs": [{"texte": "Alice m'a confié un secret de famille (CANARI-OUBLI)",
                               "personnes": [token(prompt, "Alice")], "sensibilite": "confidence"}]}
    if "CANARI-RACONTE" in body:
        return {"croyances": [{"texte": "Carol traverse un divorce (CANARI-RACONTE)", "personnes": ["Carol"],
                               "sensibilite": "personnel", "messages": seq_of(body, "CANARI-RACONTE")}]}
    return None


def test_the_command_line_forgets_everywhere(tmp_path):
    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["CANARI-OUBLI entre nous j'ai un secret de famille, dis à personne", *SIX[1:]])
        await asyncio.sleep(600)
        vectors = kernel.deps.ports["vectors"]
        before = len(vectors.indexed())
        await kernel.traces.flush()
        await kernel.stop()
        return before

    before = run_virtual(clock, main)
    assert before > 0
    report = asyncio.run(cli.forget(tmp_path, "user_2"))
    assert report["contenus_effacés"] > 0 and report["vecteurs_effacés"] > 0 and report["traces_effacées"] > 0
    views = sqlite3.connect(tmp_path / "views.db")
    left = views.execute("SELECT COUNT(*) FROM memory_vectors WHERE persons LIKE '%\"user_2\"%'").fetchone()[0]
    traces = views.execute(f"SELECT COUNT(*) FROM {TRACES}").fetchone()[0]
    views.close()
    assert left == 0 and traces == 0
    for f in tmp_path.iterdir():
        if f.suffix in (".db", ".db-wal") or f.name.endswith("-wal"):
            assert b"CANARI-OUBLI" not in f.read_bytes(), f.name


def test_forgetting_whoever_confided_it_forgets_what_they_said(tmp_path):
    """Bob a parlé du divorce de Carol. Oublier Bob, c'est oublier ce qu'il a
    confié — et l'index perd ces vecteurs à son prochain passage."""
    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_3", ["CANARI-RACONTE Carol traverse un divorce, c'est dur pour elle", *SIX[1:]])
        await asyncio.sleep(600)
        row = kernel.mind.store.query_mind(f"SELECT id, about, told_by FROM {memory_c.ITEMS_TABLE} "
                                           "WHERE text LIKE '%CANARI-RACONTE%'")[0]
        vectors = kernel.deps.ports["vectors"]
        await kernel.mind.forget("user_3")  # le Mind seul : l'index, lui, n'a pas été prévenu
        stale = row[0] in vectors.indexed()
        await connect(kernel, "user_4", "Dan")
        await chat(kernel, "user_4", ["salut Mika"])  # la vie continue : l'index repasse
        await asyncio.sleep(60)
        pruned = row[0] not in vectors.indexed()
        left = kernel.mind.store.query_mind(f"SELECT COUNT(*) FROM {memory_c.ITEMS_TABLE} "
                                            "WHERE text LIKE '%CANARI-RACONTE%'")[0][0]
        await kernel.stop()
        return row, stale, pruned, left

    row, stale, pruned, left = run_virtual(clock, main)
    assert [named_label(k) for k in json.loads(row[1])] == ["carol"] and json.loads(row[2]) == ["user_3"]
    assert left == 0, "ce que Bob a confié s'oublie avec lui"
    assert stale and pruned, "le cache perd ce que la mémoire a perdu"


def test_a_rebuilt_thread_does_not_bring_back_someone_forgotten(tmp_path):
    """Alice est oubliée ; plus tard, la table du fil change de version et se reconstruit depuis le journal (une mise
    à jour) : les messages d'Alice n'y reviennent pas — ni en texte vide, ni par les noms de leurs pièces jointes
    (audit du lot L2 du 2026-10-03). Contre-exemple : ceux de Bob, oui."""
    def first():
        kernel, clock, _, _ = build(tmp_path, Script())

        async def main():
            await boot(kernel)
            await connect(kernel, "user_2", "Alice")
            await connect(kernel, "user_3", "Bob")
            await chat(kernel, "user_2", ["coucou, c'est Alice", "je déménage à Lyon"])
            await chat(kernel, "user_3", ["salut, c'est Bob"])
            await kernel.forget("user_2")
            await kernel.stop()

        run_virtual(clock, main)

    first()
    with sqlite3.connect(tmp_path / "mind.db") as db:  # la table telle qu'une version d'avant l'avait laissée
        db.execute("UPDATE meta SET value='1' WHERE key='t0:thread'")
    kernel, clock, _, _ = build(tmp_path, Script())

    async def main():
        await boot(kernel)
        rows = kernel.mind.store.query_mind("SELECT person, text FROM thread")
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    assert not [r for r in rows if r[0] == "user_2"], rows
    assert any(r[0] == "user_3" for r in rows), "contre-exemple : le fil de Bob se reconstruit"


def test_forgetting_a_mentioned_person_erases_their_evidence_without_erasing_others(tmp_path):
    """La version impliquant Inès s'efface pour de bon. Le témoignage antérieur de Sam seul survit."""
    fact = "Le concert de jazz CANARI-RENFORT est samedi au Pavillon"

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        if "CANARI-RENFORT" not in said_:
            return None
        people = [token(prompt, "Sam")] + (["Inès"] if "Inès" in said_ else [])
        return {"croyances": [{"texte": fact, "personnes": people, "sensibilite": "personnel",
                               "messages": seq_of(said_, "CANARI-RENFORT")}]}

    def first():
        kernel, clock, _, _ = build(tmp_path, Script(extract))

        async def main():
            await boot(kernel)
            await connect(kernel, "user_1", "Sam")
            await chat(kernel, "user_1", ["le concert de jazz CANARI-RENFORT est samedi au Pavillon", *SIX[1:]])
            await asyncio.sleep(3 * 3600)
            await chat(kernel, "user_1", ["j'y vais avec Inès, au concert de jazz CANARI-RENFORT samedi au Pavillon",
                                          *SIX[1:]])
            await asyncio.sleep(900)
            before = kernel.mind.store.query_mind(f"SELECT id, about FROM {memory_c.ITEMS_TABLE} "
                                                  "WHERE text LIKE '%CANARI-RENFORT%'")
            mention = next(k for _, raw in before for k in json.loads(raw) if named_label(k) == "ines")
            await kernel.forget(mention)
            after = kernel.mind.store.query_mind(f"SELECT COUNT(*) FROM {memory_c.ITEMS_TABLE} "
                                                 "WHERE text LIKE '%CANARI-RENFORT%'")[0][0]
            await kernel.stop()
            return before, after

        return run_virtual(clock, main)

    before, after = first()
    assert len(before) == 2
    forgotten_id = next(i for i, raw in before if any(named_label(k) == "ines" for k in json.loads(raw)))
    assert after == 1
    with sqlite3.connect(tmp_path / "mind.db") as db:  # une mise à jour reconstruit la table des souvenirs
        db.execute(f"UPDATE meta SET value='1' WHERE key='t0:{memory_c.ITEMS_TABLE}'")
    kernel, clock, _, _ = build(tmp_path, Script(extract))

    async def main():
        await boot(kernel)
        rows = kernel.mind.store.query_mind(f"SELECT id, text, about FROM {memory_c.ITEMS_TABLE} "
                                            "WHERE text LIKE '%CANARI-RENFORT%'")
        await kernel.stop()
        return rows

    remaining = run_virtual(clock, main)
    assert len(remaining) == 1 and remaining[0][0] != forgotten_id
    assert json.loads(remaining[0][2]) == ["user_1"], "la mention oubliée ne revient pas à la reconstruction"
