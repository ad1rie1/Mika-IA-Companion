"""Preuve M0 — oubli : une chaîne témoin passe par ``forget`` et devient
introuvable dans ``mind.db``, ``views.db``, les WAL et les instantanés ; le
rejeu fonctionne encore."""

from __future__ import annotations

import asyncio
from pathlib import Path

from mika.kernel.events import Content
from mika.runtime.projections import ensure_t0
from tests.conftest import make_mind
from tests.fixtures.projectors import with_projectors
from tests.fixtures.toys import BUMPED

CANARY = "Léa-part-à-Reykjavik-7f3a9c"


def files_containing(root: Path, needle: bytes) -> list[str]:
    hits = []
    for p in root.iterdir():
        if p.is_file() and needle in p.read_bytes():
            hits.append(p.name)
    return hits


async def test_forget_removes_canary_everywhere_and_replay_survives(tmp_path):
    fac = with_projectors(t0=True)
    mind = make_mind(tmp_path, [fac], snapshot_every=2)
    await mind.boot(append_boot=False)
    await ensure_t0(mind)
    await mind.append([BUMPED.draft(by=1, note=Content.of(f"confidence : {CANARY}", level=2), who="lea")],
                      emitter="counter", correlation="t")
    for i in range(5):
        await mind.append([BUMPED.draft(by=1, note=Content.of(f"banal {i}"), who="bob")],
                          emitter="counter", correlation="t")
    needle = CANARY.encode()
    assert files_containing(tmp_path, needle), "le témoin doit d'abord être présent"
    removed = await mind.forget("lea")
    assert removed == 1
    await mind.close()
    assert files_containing(tmp_path, needle) == []
    # l'enveloppe survit : le rejeu fonctionne, le compteur est intact
    mind2 = make_mind(tmp_path, [fac], snapshot_every=10**9)
    await mind2.boot(append_boot=False)
    assert mind2.root.slices["counter"].n == 6
    assert mind2.root.slices["counter"].notes == 6
    rows = mind2.store.query_mind("SELECT who, body FROM textlog ORDER BY seq")
    assert [r[0] for r in rows] == ["bob"] * 5
    await mind2.close()


def test_forgetting_a_person_takes_the_files_she_was_sent(tmp_path):
    """ADR 0062 : oublier quelqu'un efface les fichiers qu'elle lui a envoyés — leurs octets (hors du journal),
    leurs lignes et leur nom ; reconstruire la projection ne les fait pas revenir. Ceux d'une autre restent."""
    from mika.contracts import shares as shares_c
    from mika.faculties.shares import rows
    from mika.runtime.effects import with_content
    from tests.unit.test_shares import call, live

    async def scenario(kernel, store, llm, deliveries):
        gone = await call(kernel, "share_text", "user_2", name="secret-de-bea.md", content=CANARY)
        kept = await call(kernel, "share_text", "user_3", name="pour-chloe.md", content="banal")
        [g], [k] = gone.attach, kept.attach
        await kernel.forget("user_2")
        read = kernel.mind.store
        after = [r.id for r in rows(read, [g, k])]
        events = [with_content(kernel.mind, kernel.mind.decode(e)) for e in read.read()
                  if e.type == shares_c.SHARED.name]
        names = {e.data.file: e.data.name.text for e in events}
        await read.run_mind(lambda sql: sql.execute(f"UPDATE meta SET value='0' WHERE key='t0:{shares_c.TABLE}'"))
        rebuilt = await ensure_t0(kernel.mind)
        return g, k, store.files(), after, names, rebuilt, [r.id for r in rows(read, [g, k])]

    g, k, files, after, names, rebuilt, after_rebuild = live(tmp_path, scenario)
    assert files == [k] and after == [k]
    assert names[g] is None and names[k] == "pour-chloe.md"  # le nom oublié : sa référence reste, plus son texte
    assert "shared_files" in rebuilt and after_rebuild == [k]
    assert files_containing(tmp_path, CANARY.encode()) == []


def test_the_command_line_forgets_her_files_too(tmp_path):
    """``mika forget`` (serveur arrêté) passe par le même port que la console : les octets s'effacent du disque."""
    from mika.adapters.shares import DiskShares
    from mika.app import cli
    from mika.kernel.registry import ArbitrationPolicy
    from mika.sim.clock import run_virtual
    from tests.fixtures.mika import boot, build, connect, reply
    from tests.unit.test_shares import call

    folder = tmp_path / "partages"
    kernel, clock, _, _ = build(tmp_path, reply("D'accord."), ports={"shares": DiskShares(folder)},
                                arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Béa")
        out = await call(kernel, "share_text", "user_2", name="pour-bea.md", content=CANARY)
        await kernel.stop()
        return out

    out = run_virtual(clock, main)
    assert out.ok and DiskShares(folder).files() == list(out.attach)
    report = asyncio.run(cli.forget(tmp_path, "user_2"))
    assert report["fichiers_effacés"] == 1 and DiskShares(folder).files() == []
    assert files_containing(folder, CANARY.encode()) == []
