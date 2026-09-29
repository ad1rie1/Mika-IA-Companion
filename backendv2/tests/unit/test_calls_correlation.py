"""Les appels de modèle d'un épisode se retrouvent après un redémarrage : la
passerelle note la corrélation de chaque appel, le registre durable la garde
(et complète en place un registre créé avant la colonne)."""

from __future__ import annotations

from mika.adapters.llm.calls import TABLE, CallLog
from mika.adapters.llm.gateway import Gateway
from mika.adapters.store_sqlite import SqliteStore
from mika.kernel.clock import ManualClock
from mika.ports.llm import LLMRequest, LLMResponse, Usage
from mika.sim.llm.scripted import ScriptedLLM

OLD_COLUMNS = ("at", "role", "backend", "model", "lane", "priority", "latency_us", "wait_us", "input_tokens",
               "output_tokens", "cache_read", "cache_write", "cost_usd", "outcome", "call_id")


def store_at(tmp_path) -> SqliteStore:
    return SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)


async def test_a_restarted_log_finds_an_episodes_calls(tmp_path):
    clock = ManualClock(1_000_000)
    store = store_at(tmp_path)
    await store.open()
    calls = CallLog(store)
    await calls.open()
    turns = iter([LLMResponse("", model="m", usage=Usage(10, 1)), LLMResponse("fini", model="m", usage=Usage(12, 3)),
                  LLMResponse("{}", model="m")])
    llm = ScriptedLLM(clock, lambda req: next(turns))
    gateway = Gateway({"fake": llm}, {"reply": "fake", "extract": "fake"}, clock=clock, on_trace=calls.record)
    reply = LLMRequest(role="reply", call_id="ep-1#0", system_stable="Tu es Mika.",
                       meta={"episode": "ep-1", "kind": "REPLY"})
    await gateway.call(reply)
    clock.advance(1_000_000)
    await gateway.call(reply)  # un second tour de la boucle d'outils : même identifiant
    await gateway.call(LLMRequest(role="extract", call_id="memory.consolidate:xyz#0", system_stable="Extrais."))
    assert [t.correlation for t in gateway.traces] == ["ep-1", "ep-1", "memory.consolidate:xyz"]
    await calls.flush()
    await store.close()

    # un redémarrage : un autre registre sur la même base
    store2 = store_at(tmp_path)
    await store2.open()
    again = CallLog(store2)
    await again.open()
    episode = again.for_correlation("ep-1")
    assert [(t.call_id, t.input_tokens) for t in episode] == [("ep-1#0", 10), ("ep-1#0", 12)]
    last = again.by_call_id("ep-1#0")
    assert last is not None and last.output_tokens == 3, "le dernier tour : celui qui a écrit le texte"
    process = again.for_correlation("memory.consolidate:xyz")
    assert len(process) == 1 and process[0].role == "extract"
    assert again.by_call_id("absent") is None and again.for_correlation("absent") == []
    await store2.close()


async def test_a_log_created_before_the_column_is_completed_in_place(tmp_path):
    store = store_at(tmp_path)
    await store.open()
    cols = ", ".join(f"{c} {'TEXT' if c in ('role', 'backend', 'model', 'lane', 'outcome', 'call_id') else 'INTEGER'}"
                     for c in OLD_COLUMNS)

    def old_schema(sql):
        sql.execute(f"CREATE TABLE {TABLE}(id INTEGER PRIMARY KEY, {cols})")
        sql.execute(f"INSERT INTO {TABLE}({', '.join(OLD_COLUMNS)}) VALUES({', '.join('?' * len(OLD_COLUMNS))})",
                    (5, "reply", "fake", "m", "conversation", 0, 1, 0, 7, 2, 0, 0, 0.0, "ok", "ancien#0"))

    await store.run_views(old_schema)
    calls = CallLog(store)
    await calls.open()
    await calls.open()  # idempotent
    columns = {r[1] for r in store.query_views(f"PRAGMA table_info({TABLE})")}
    indexes = {r[1] for r in store.query_views(f"PRAGMA index_list({TABLE})")}
    assert "correlation" in columns and f"{TABLE}_correlation" in indexes
    (old,) = calls.recent()
    assert old.call_id == "ancien#0" and old.correlation == ""
    assert calls.by_call_id("ancien#0") is not None
    clock = ManualClock(10)
    gateway = Gateway({"fake": ScriptedLLM(clock, lambda req: LLMResponse("ok"))}, {"reply": "fake"}, clock=clock,
                      on_trace=calls.record)
    await gateway.call(LLMRequest(role="reply", call_id="neuf#0", system_stable="Tu es Mika."))
    await calls.flush()
    assert [t.call_id for t in calls.for_correlation("neuf")] == ["neuf#0"]
    await store.close()
