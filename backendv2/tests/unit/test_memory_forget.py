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
    assert json.loads(row[1]) == ["name:carol"] and json.loads(row[2]) == ["user_3"]
    assert left == 0, "ce que Bob a confié s'oublie avec lui"
    assert stale and pruned, "le cache perd ce que la mémoire a perdu"
