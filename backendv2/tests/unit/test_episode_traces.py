"""Les traces d'épisode : ce qu'elle avait sous les yeux quand elle a parlé.

Après une vraie conversation, la trace de la réponse garde le préfixe stable
(sa persona), le message de la personne, les sections incluses avec leur
taille, et chaque appel d'outil avec ses arguments et son résultat ; les
durées viennent de l'horloge injectée. Bornée (jours, lignes, taille), le
préfixe partagé rangé une fois, et l'oubli efface tout."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from types import SimpleNamespace

from pydantic import BaseModel

from mika.adapters.store_sqlite import SqliteStore
from mika.kernel.clock import DAY, HOUR
from mika.kernel.episode import EpisodePolicy, Outcome
from mika.kernel.events import Payload
from mika.kernel.faculty import EffectClass, Faculty
from mika.ports.llm import LLMResponse, ToolCall
from mika.runtime.lanes import REPORTS_KEPT, Lanes
from mika.runtime.pipeline import EpisodeReport, EpisodeRequest
from mika.runtime.tools import RECORD_MAX_CHARS, ToolResult
from mika.runtime.traces import BLOBS, MAX_BLOB, MAX_TEXT, TABLE, TRUNCATION_MARK, EpisodeTraces
from mika.sim.clock import run_virtual
from tests.fixtures import harness
from tests.fixtures.mika import boot, build, connect, said

# ── une vraie conversation, un appel d'outil scripté ──────────────────────


def scripted(req):
    if req.role == "reply":
        if not any(m.role == "tool" for m in req.messages):
            return LLMResponse("", tool_calls=(
                ToolCall("t1", "identity_whoami_with", {}),
                ToolCall("t2", "identity_doubt", {"reason": "elle hésite sur son prénom"}),
                ToolCall("t3", "outil_imaginaire", {"x": 1}),
            ), stop="tool_use")
        return LLMResponse("Tu es Adrien, je crois. [EMOTION:happy:0.5]")
    if req.role in ("extract", "profile"):
        return LLMResponse("{}")
    return LLMResponse("Coucou ! [EMOTION:happy:0.4]")


def test_the_reply_trace_holds_what_she_saw_and_what_her_tools_did(tmp_path):
    kernel, clock, llm, out = build(tmp_path, scripted, latency=2.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(120)  # la salutation (une initiative) part
        perceived = await kernel.perceive(said("user_1", "dis-moi qui je suis", display_name="Adrien"))
        report = await perceived.reply
        await kernel.traces.flush()
        trace = kernel.traces.get(report.id)
        heads = kernel.traces.recent()
        llm_traces = [t for t in kernel.deps.gateway.traces if t.call_id.startswith(report.id)]
        await kernel.stop()
        return report, trace, heads, llm_traces

    report, trace, heads, llm_traces = run_virtual(clock, main)
    assert report.outcome is Outcome.DONE and trace is not None
    assert trace["kind"] == "REPLY" and trace["target"] == "user_1" and trace["outcome"] == "done"
    assert trace["utterance_seq"] == report.utterance_seq
    # ce qui est parti au modèle : sa persona, le message de la personne, ses outils
    reply_calls = [c for c in llm.calls if c.role == "reply"]
    first = reply_calls[0]
    assert "Tu es Mika" in trace["system_stable"] and trace["system_stable"] == first.system_stable
    assert trace["messages"] == [{"role": m.role, "content": m.content} for m in first.messages]
    assert trace["messages"][-1]["content"].endswith("dis-moi qui je suis")
    assert "QUI TU AS EN FACE" in trace["messages"][-1]["content"]
    assert {"identity_whoami_with", "identity_doubt"} <= set(trace["tools"])
    # la composition : chaque section incluse avec sa taille
    compose = trace["compose"]
    assert [k for k, _ in compose["sizes"]] == list(compose["included"])
    assert all(isinstance(n, int) and n >= 0 for _, n in compose["sizes"])
    assert max(n for _, n in compose["sizes"]) > 0
    # les outils : arguments et résultats, tels que le modèle les a reçus
    seen = [m.content for m in reply_calls[1].messages if m.role == "tool"]
    tools = trace["tool_calls"]
    assert [t["name"] for t in tools] == ["identity_whoami_with", "identity_doubt", "outil_imaginaire"]
    assert [t["result"] for t in tools] == seen
    assert tools[1]["args"] == '{"reason": "elle hésite sur son prénom"}' and tools[0]["args"] == "{}"
    assert [t["executed"] for t in tools] == [True, True, False]
    assert tools[2]["ok"] is False and tools[2]["result"] == "outil inconnu : outil_imaginaire"
    # les appels de modèle, reliés à l'épisode
    assert trace["llm_calls"] == [f"{report.id}#0"]
    assert [r["stop"] for r in trace["responses"]] == ["tool_use", "end"]
    assert trace["reply"].startswith("Tu es Adrien")
    assert len(llm_traces) == 2 and all(t.correlation == report.id for t in llm_traces)
    # la salutation aussi a sa trace : chaque type d'épisode en laisse une
    assert {h.kind for h in heads} >= {"REPLY", "INITIATIVE"}


# ── les durées viennent de l'horloge injectée ─────────────────────────────


@dataclass(frozen=True, slots=True)
class SlowState:
    n: int = 0


class Did(Payload):
    what: str


class DoArgs(BaseModel):
    what: str


SLOW = Faculty("slow", state=SlowState, init=lambda p: SlowState())
DID = SLOW.event("did", Did, public=True)


@SLOW.reducer(DID)
def _did(s: SlowState, e, cx) -> SlowState:
    return replace(s, n=s.n + 1)


@SLOW.tool("slow_do", description="Fait quelque chose, lentement.", args=DoArgs, bundle="atelier",
           episodes=["STEP"], effect=EffectClass.INTERNAL)
async def slow_do(args: DoArgs, ctx) -> ToolResult:
    await asyncio.sleep(2.5)  # temps virtuel
    await ctx.emit(DID.draft(what=args.what))
    return ToolResult(content="x" * (RECORD_MAX_CHARS * 2))


STEP_POLICY = {"STEP": EpisodePolicy(kind="STEP", role="step", priority=1, lane="background", delivered=False,
                                     visible=False, tool_bundles=frozenset({"atelier"}), deadline_s=30.0)}


def step_script(req):
    if not any(m.role == "tool" for m in req.messages):
        return LLMResponse("", (ToolCall("s1", "slow_do", {"what": "y" * (RECORD_MAX_CHARS * 2)}),),
                           stop="tool_use")
    return LLMResponse("fini")


def test_a_step_trace_times_its_tools_on_the_injected_clock_and_bounds_them(tmp_path):
    kernel, clock, llm = harness.build(tmp_path, [SLOW], respond=step_script, policies=STEP_POLICY)

    async def main():
        await kernel.start()
        report = await kernel.lanes.submit(EpisodeRequest(kind="STEP", target=None))
        await kernel.traces.flush()
        trace = kernel.traces.get(report.id)
        await kernel.stop()
        return report, trace

    report, trace = run_virtual(clock, main)
    assert report.outcome is Outcome.DONE and trace["kind"] == "STEP" and trace["target"] is None
    (tool,) = trace["tool_calls"]
    assert tool["duration_us"] == 2_500_000
    assert len(tool["args"]) == RECORD_MAX_CHARS and len(tool["result"]) == RECORD_MAX_CHARS
    assert tool["result"].endswith("[coupé]")
    assert trace["reply"] == "fini" and trace["system_stable"].startswith("Tu es Mika.")


# ── rétention, préfixe partagé, oubli, bornes ─────────────────────────────


def data(system: str, message: str = "salut") -> dict:
    return {"system_stable": system, "messages": [{"role": "user", "content": message}], "tools": []}


async def opened(tmp_path, **kw) -> tuple[SqliteStore, EpisodeTraces]:
    store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await store.open()
    traces = EpisodeTraces(store, **kw)
    await traces.open()
    return store, traces


async def test_the_shared_stable_prefix_is_stored_once(tmp_path):
    store, traces = await opened(tmp_path)
    persona = "Tu es Mika. " * 500
    traces.record("e1", 10, "REPLY", "user_1", data(persona, "un"))
    traces.record("e2", 20, "REPLY", "user_2", data(persona, "deux"))
    traces.record("e3", 30, "MURMUR", None, data("Tu es Mika, en bref."))
    await traces.flush()
    assert store.query_views(f"SELECT COUNT(*) FROM {BLOBS}")[0][0] == 2
    one, two = traces.get("e1"), traces.get("e2")
    assert one["system_stable"] == two["system_stable"] == persona
    assert one["system_stable_hash"] == two["system_stable_hash"]
    assert one["messages"][0]["content"] == "un" and two["messages"][0]["content"] == "deux"
    assert traces.get("e3")["target"] is None and traces.get("absent") is None
    # le règlement remplace la trace de la composition, sans doublon
    traces.record("e1", 10, "REPLY", "user_1", {**data(persona, "un"), "outcome": "done"})
    await traces.flush()
    assert traces.count() == 3 and traces.get("e1")["outcome"] == "done"
    await store.close()


async def test_prune_removes_old_rows_extra_rows_and_orphan_prefixes(tmp_path):
    store, traces = await opened(tmp_path, keep_days=14, max_rows=3)
    now = 100 * DAY
    traces.record("old", now - 15 * DAY, "REPLY", "user_1", data("persona d'autrefois"))
    for i in range(4):
        traces.record(f"e{i}", now - (4 - i) * HOUR, "REPLY", "user_1", data("persona du jour"))
    await traces.flush()
    assert traces.count() == 5
    removed = await traces.prune(now)
    assert removed == 2 and traces.count() == 3
    assert [h.correlation for h in traces.recent()] == ["e3", "e2", "e1"]
    assert traces.get("old") is None and traces.get("e0") is None
    blobs = store.query_views(f"SELECT COUNT(*) FROM {BLOBS}")[0][0]
    assert blobs == 1, "le préfixe que plus rien ne cite est retiré"
    await store.close()


async def test_forget_clears_every_trace_and_in_flight_episodes_stay_forgotten(tmp_path):
    store, traces = await opened(tmp_path)
    traces.record("e1", 10, "REPLY", "user_1", data("persona", "Léa part à Reykjavik"))
    traces.record("e2", 20, "REPLY", "user_2", data("persona", "autre chose"))
    assert await traces.forget("user_1") == 2
    assert traces.count() == 0 and store.query_views(f"SELECT COUNT(*) FROM {BLOBS}")[0][0] == 0
    # un épisode en vol au moment de l'oubli ne réécrit pas sa trace à son règlement
    traces.record("e1", 10, "REPLY", "user_1", {**data("persona", "Léa part à Reykjavik"), "outcome": "done"})
    traces.record("e9", 30, "REPLY", "user_2", data("persona", "après l'oubli"))
    await traces.flush()
    assert traces.get("e1") is None and traces.get("e9") is not None
    await store.close()


async def test_oversized_content_is_truncated_with_an_explicit_mark(tmp_path):
    store, traces = await opened(tmp_path)
    huge_system = "S" * (MAX_TEXT + 5000)
    big = {"system_stable": huge_system,
           "messages": [{"role": "user", "content": "M" * (MAX_TEXT + 10)}],
           "tools": []}
    traces.record("big", 1, "REPLY", "user_1", big)
    many = {"system_stable": "persona", "tools": [],
            "messages": [{"role": "user", "content": f"{i}" * 150_000} for i in range(10)]}
    traces.record("many", 2, "REPLY", "user_1", many)
    await traces.flush()
    got = traces.get("big")
    assert got["system_stable"].startswith("S" * 1000) and TRUNCATION_MARK in got["system_stable"]
    assert got["system_stable_truncated"] is True
    assert len(got["messages"][0]["content"]) < MAX_TEXT + 100
    assert TRUNCATION_MARK in got["messages"][0]["content"] and got["truncated"] is True
    lots = traces.get("many")
    assert lots["truncated"] is True and len(lots["messages"]) == 10
    assert all(TRUNCATION_MARK in m["content"] for m in lots["messages"])
    raw = store.query_views(f"SELECT blob FROM {TABLE} WHERE correlation='many'")[0][0]
    assert len(raw) < MAX_BLOB
    total = sum(len(m["content"].encode()) for m in lots["messages"])
    assert total <= MAX_BLOB, "la trace entière reste sous le plafond"
    await store.close()


def test_the_kernel_forgets_its_traces_with_the_person(tmp_path):
    kernel, clock, llm, out = build(tmp_path, scripted)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        perceived = await kernel.perceive(said("user_1", "dis-moi qui je suis", display_name="Adrien"))
        await perceived.reply
        await kernel.traces.flush()
        before = kernel.traces.count()
        report = await kernel.forget("user_1")
        after = kernel.traces.count()
        await kernel.stop()
        return before, report, after

    before, report, after = run_virtual(clock, main)
    assert before >= 1 and report["traces"] == before and after == 0


# ── les comptes rendus des voies restent bornés ───────────────────────────


async def test_lane_reports_stay_bounded():
    async def run(req):
        return EpisodeReport(req.trigger, req.kind, Outcome.DONE)

    runner = SimpleNamespace(policies={"X": SimpleNamespace(lane="background")}, run=run)
    lanes = Lanes(runner, capacities={"background": 1}, max_pending=1000)  # type: ignore[arg-type]
    lanes.start()
    for i in range(REPORTS_KEPT + 44):
        lanes.submit(EpisodeRequest(kind="X", trigger=str(i)))
    await lanes.join()
    await lanes.stop()
    assert len(lanes.reports) == REPORTS_KEPT
    assert lanes.reports[-1].id == str(REPORTS_KEPT + 43) and lanes.reports[0].id == "44"
