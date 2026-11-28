"""Le monde en 3D est retiré (ADR 0319) : la faculté ``world``, la vue ``place``, leur contrat, le protocole
``mika.world/1`` et sa route ``/ws/world``.

Les vies déjà écrites gardent leurs événements ``world.*`` et ``place.*``, et leurs instantanés portent les tranches
``world`` et ``place`` : elles se relisent sans effet (des événements retirés, ``decode_or_retired``), et le démarrage
ne bloque pas. Les besoins, qui gardaient l'occupation de sa chambre, ont changé de forme : leur tranche se reconstruit
depuis la genèse, sans upcast. Rien du code ne nomme plus le monde.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from sqlalchemy import delete, update

from mika.adapters.store_sql import SqlStore
from mika.app import composition
from mika.faculties.needs import NEEDS, NeedsState
from mika.kernel.clock import DAY
from mika.kernel.events import Origin, Payload
from mika.kernel.faculty import Faculty
from mika.ports.journal import JournalSnapshot
from mika.sim.clock import run_virtual
from tests.fixtures import backend
from tests.fixtures.mika import AFTERNOON, DOC, build

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"


# ── une vie d'avant : ses facultés telles que le journal les a connues ────


class Gesture(Payload):
    what: str = ""


@dataclass(frozen=True, slots=True)
class Done:
    count: int = 0


OLD_WORLD = Faculty("world", state=Done, init=lambda p: Done(), state_version=8)
INTENDED = OLD_WORLD.event("world.intended", Gesture, public=True)
ENDED = OLD_WORLD.event("world.ended", Gesture, public=True)
OLD_PLACE = Faculty("place", state=Done, init=lambda p: Done(), state_version=2)
MOVED = OLD_PLACE.event("place.moved", Gesture, public=True)


@OLD_WORLD.reducer(INTENDED, ENDED)
def _gestured(s: Done, e, cx) -> Done:
    return replace(s, count=s.count + 1)


@OLD_PLACE.reducer(MOVED)
def _moved(s: Done, e, cx) -> Done:
    return replace(s, count=s.count + 1)


def _her_old_life(tmp_path: Path, *, snapshot: bool) -> int:
    """Une vie où elle allait à la fenêtre et dessinait : ses gestes au journal ; puis, selon ``snapshot``, un
    instantané qui porte ses tranches ``world`` et ``place`` et des besoins d'avant (v7, avec ce qu'elle faisait de
    ses mains), ou aucun instantané (tout se relit depuis la genèse)."""
    kernel, clock, _, _ = build(tmp_path, None, faculties=[*composition.faculties(), OLD_WORLD, OLD_PLACE],
                                snapshot_every=1)

    async def main() -> int:
        await kernel.boot(configure=lambda k: composition.configure(k, DOC))
        await kernel.mind.append([MOVED.draft(what="fenêtre")], emitter="place", correlation="chambre",
                                 origin=Origin.EXTERNAL)
        await kernel.mind.append([INTENDED.draft(what="dessiner")], emitter="world", correlation="chambre",
                                 origin=Origin.EXTERNAL)
        await kernel.mind.append([ENDED.draft(what="dessiner")], emitter="world", correlation="chambre",
                                 origin=Origin.EXTERNAL)
        await kernel.stop()
        store = SqlStore(*backend.store_targets(tmp_path), threaded=False)
        await store.open()
        last = store.latest_snapshot()
        data = json.loads(last.data)
        assert {"world", "place"} <= set(data["slices"]), "l'instantané d'avant porte ses tranches"
        if snapshot:
            needs = data["slices"]["needs"]
            needs["v"] = 7
            needs["data"].update(occupied={"name": "draw", "since": 1, "until": None, "nourishes": ["expression"],
                                           "void_from": 0, "noted": 1}, nourished=None)
            changed = update(JournalSnapshot).where(JournalSnapshot.seq == last.seq).values(data=json.dumps(data))
        else:
            changed = delete(JournalSnapshot)
        await store.run_mind(lambda sql: sql.execute(changed))
        head = store.head()
        await store.close()
        return head

    return run_virtual(clock, main)


@pytest.mark.parametrize("snapshot", [True, False], ids=["instantané", "genèse"])
def test_a_life_with_her_world_still_boots_and_replays_it_without_effect(tmp_path, snapshot):
    head = _her_old_life(tmp_path, snapshot=snapshot)
    # la composition d'aujourd'hui, ni monde ni place, le lendemain
    kernel, clock, _, _ = build(tmp_path, None, start=AFTERNOON + DAY, seed=1)

    async def main():
        report = await kernel.boot(configure=lambda k: composition.configure(k, DOC))
        try:
            retired = set(kernel.mind.retired)
            old = [kernel.mind.decode(s) for s in kernel.mind.store.read()]
            return report, retired, old, kernel.mind.root, kernel.mind.head
        finally:
            await kernel.stop()

    report, retired, old, root, now = run_virtual(clock, main)
    assert report.head == head and now > head  # tout relu, et la vie a repris (son démarrage journalisé)
    assert {"world", "place"}.isdisjoint(root.slices), "les tranches retirées ne reviennent pas"
    gone = {"world.intended", "world.ended", "place.moved"}
    assert gone <= {e.type.name for e in old}
    assert {e.type.owner for e in old if e.type.name in gone} == {"retired"}  # relus sans effet
    assert isinstance(root.slices["needs"], NeedsState) and NEEDS.state_version == 8
    if snapshot:
        # elle repart de l'instantané qui portait ses tranches retirées ; ses besoins d'avant (v7) ne s'y relisent
        # pas : reconstruits depuis la genèse, sans upcast
        assert report.snapshot_seq > 0 and "needs" in report.stale
    else:
        assert report.snapshot_seq == 0 and gone <= retired  # le rejeu complet les a croisés


def test_no_module_imports_the_world_or_place():
    """Sur l'arbre syntaxique : un commentaire qui rappelle ce qui a été retiré ne compte pas."""
    gone = ("mika.faculties.world", "mika.faculties.place", "mika.contracts.world", "mika.contracts.place",
            "mika.adapters.world")
    found = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [f"{node.module}.{a.name}" for a in node.names] if isinstance(node, ast.ImportFrom) else [])
            found += [f"{path.relative_to(SRC)} : {n}" for n in names if n.startswith(gone)]
    assert found == []


def test_no_route_serves_the_world():
    found = [str(path.relative_to(SRC)) for path in sorted(SRC.rglob("*.py"))
             for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/ws/world")]
    assert found == []


def test_her_composition_has_neither_world_nor_place():
    names = {f.name for f in composition.faculties()}
    assert {"world", "place"}.isdisjoint(names)
    assert "world" not in composition.REPLY_IN_HAND | composition.INITIATIVE_IN_HAND
