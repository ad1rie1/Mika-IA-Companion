"""Le fil et le graphe des liens, écrits et relus par SQLAlchemy (ADR 0101) : ce que des requêtes propres à SQLite
faisaient (des fenêtres sur une table dérivée sans nom, ``LIKE``, ``json_set``, ``json_each``, une borne négative),
refait pareil sur les deux moteurs — et ce qui dépasse une borne de colonne ne fait jamais échouer une projection.

- ses entrées en matière se comptent en Python : un silence ouvre une conversation, le tout début du fil aussi
  quand on l'a relu en entier, jamais le début d'une fenêtre coupée ;
- la console cherche dans le texte replié : la casse et les accents n'y comptent pas ;
- garder plus de messages qu'il n'en faut pour replier ne replie rien (SQLite lisait la borne négative « sans
  borne » et repliait tout) ;
- un lien dont la clé dépasse sa colonne est gardé, et relu avec sa clé exacte ; l'oubli d'un témoin l'efface.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from typing import Any

from sqlalchemy import insert, select

from mika.contracts import memory as mc
from mika.contracts import social as sc
from mika.contracts import transcript as tc
from mika.faculties.expression import _own_openings
from mika.faculties.social.archive import Relations, recall_relations
from mika.faculties.transcript import Compact, Thread, TranscriptParams, TranscriptState
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content
from mika.kernel.inspect import Table
from mika.ports.llm import LLMResponse
from mika.ports.paging import fold_text
from mika.runtime.inspection import find, run_view
from mika.sim.clock import run_virtual
from tests.fixtures.mika import boot, build, connect, said
from tests.fixtures.sqldb import SqlDB


def _thread(rows: list[tuple[int, int, str, str]]) -> SqlDB:
    db = SqlDB()
    Thread().create(db, "")
    db.execute(insert(tc.thread_table()), [
        {"id": i, "at": at, "role": role, "person": "user_2", "text": text, "folded": fold_text(text)}
        for i, at, role, text in rows])
    return db


def _openings(db: SqlDB) -> Any:
    frame = NS(episode=NS(target="user_2", attrs={}), env=NS(params_of=lambda *a: None), root=None)
    return asyncio.run(_own_openings(None, frame, {"store": db}))


def test_her_openings_are_the_first_thing_she_says_after_each_silence():
    gap = 5 * HOUR  # plus que le silence qui ouvre une conversation (3 h par défaut)
    rows = [(1, 0, "user", "salut"), (2, MINUTE, "assistant", "Coucou toi !"), (3, 2 * MINUTE, "assistant", "ça va ?"),
            (4, gap, "user", "re"), (5, gap + MINUTE, "assistant", "Te revoilà !"),
            (6, 2 * gap, "user", "hello")]
    got = _openings(_thread(rows))
    assert got.said == ("Coucou toi !", "Te revoilà !") and got.opens  # la dernière attend encore son premier mot
    got = _openings(_thread([*rows, (7, 2 * gap + MINUTE, "assistant", "Hey !")]))
    assert got.said == ("Coucou toi !", "Te revoilà !", "Hey !") and not got.opens
    # au plus ses trois dernières, sur les quatre dernières conversations
    many = [(i, i * gap, "assistant", f"ouverture {i}") for i in range(1, 6)]
    assert _openings(_thread(many)).said == ("ouverture 3", "ouverture 4", "ouverture 5")


def test_a_cut_window_does_not_open_a_conversation_at_its_first_message():
    """510 messages : la fenêtre (les 500 derniers) commence au milieu d'une conversation, qui ne compte pas ; le
    silence d'après en ouvre une. Contre-exemple : relu en entier, le tout début du fil en ouvre une."""
    rows = [(i, i * MINUTE + (10 * HOUR if i >= 400 else 0), "assistant" if i % 2 == 0 else "user", f"m{i}")
            for i in range(1, 511)]
    got = _openings(_thread(rows))
    assert got.said == ("m400",) and not got.opens
    whole = _openings(_thread(rows[-450:]))  # du n° 61 au n° 510 : tout le fil relu
    assert whole.said == ("m62", "m400")


def test_the_console_finds_a_message_whatever_its_case_and_accents(tmp_path):
    def respond(req):
        if req.role in ("extract", "profile"):
            return LLMResponse("{}")
        return LLMResponse("D'accord ! [EMOTION:happy:0.4]")

    kernel, clock, _, _ = build(tmp_path, respond)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "Élodie m'a offert un CHAT roux."))).reply
            await kernel.lanes.join()
            spec = find(kernel, "transcript", "messages")
            return {q: run_view(kernel, spec, {"q": q}) for q in ("elodie", "ÉLODIE", "chat roux", "chien")}
        finally:
            await kernel.stop()

    found = run_virtual(clock, main)

    def rows(q: str) -> int:
        return len(next(b for b in found[q] if isinstance(b, Table)).rows)

    assert rows("elodie") == rows("ÉLODIE") == rows("chat roux") == 1
    assert rows("chien") == 0  # contre-exemple


def _compact(db: SqlDB, p: TranscriptParams) -> tuple[list[Any], list[Any]]:
    calls: list[Any] = []
    emitted: list[Any] = []

    async def call(req):
        calls.append(req)
        return LLMResponse("Ils ont parlé de tout et de rien.")

    async def emit(*drafts):
        emitted.extend(drafts)

    def get(key):
        if key.name == mc.CHECKPOINT.name:
            return 10**6  # tout a été relu par la mémoire
        return NS(name="Alice")

    frame = NS(get=get, env=NS(params_of=lambda *a: p, tz_of=lambda *a: None), root=None, now=DAY)
    ctx = NS(frame=frame, state=TranscriptState(), ports={"store": db}, llm=NS(call=call), run_id="r", emit=emit)
    asyncio.run(Compact().run(ctx))
    return calls, emitted


def test_keeping_more_than_the_fold_threshold_folds_nothing(monkeypatch):
    monkeypatch.setattr("mika.faculties.transcript._compact_lines", lambda frame, person, rows, *a: "…")
    rows = [(i, i * MINUTE, "user", f"message {i}") for i in range(1, 51)]
    calls, emitted = _compact(_thread(rows), TranscriptParams(compact_after=20, keep=200))
    assert calls == [] and emitted == []
    # contre-exemple : en en gardant dix, les quarante plus anciens se replient
    calls, emitted = _compact(_thread(rows), TranscriptParams(compact_after=20, keep=10))
    assert len(calls) == 1 and emitted[0].data.upto == 40 and emitted[0].data.count == 40


def _ties(db: SqlDB) -> list[tuple[Any, ...]]:
    t = sc.relations_table()
    return db.query(select(t.c.subject, t.c.key, t.c.item))


def test_a_tie_whose_key_outgrows_its_column_is_kept_recalled_exactly_and_forgotten_with_a_teller():
    db = SqlDB()
    Relations().create(db, "")
    tellers = tuple(f"ext_{'x' * 60}{i}" for i in range(8))
    relation = mc.Relation(subject="user_2", other="user_3", kind="friend", status="active")
    believed = mc.BELIEVED.draft(text=Content.of("Alice est amie avec Bob"), told_by=tellers, relations=(relation,))
    Relations().apply(db, [NS(type=believed.type, data=believed.data, seq=1, at=DAY)], "")
    key = sc.relation_key("user_3", "friend", tellers)
    assert len(key) > sc.RELATION_KEY_MAX
    assert [(s, len(k), item) for s, k, item in _ties(db)] == [("user_2", sc.RELATION_KEY_MAX, 1)]
    # une croyance jointe la nuit : le lien passe à la gardée, dans la colonne et dans sa charge utile
    joined = mc.JOINED.draft(night="2026-10-12", pairs=((5, 1),))
    Relations().apply(db, [NS(type=joined.type, data=joined.data, seq=2, at=DAY)], "")
    frame = NS(get=lambda k: () if k.name == "identity.handles" else None)
    recalled = recall_relations(NS(relations={}), frame, NS(data=NS(handle="user_3")), {"store": db})
    (subject, got, edge), = recalled[0].data.edges
    assert (subject, got, edge.item) == ("user_2", key, 5)  # la clé exacte, refaite depuis la charge utile
    Relations().forget(db, "user_9", "")
    assert len(_ties(db)) == 1  # contre-exemple : quelqu'un d'autre
    Relations().forget(db, tellers[3], "")
    assert _ties(db) == []
