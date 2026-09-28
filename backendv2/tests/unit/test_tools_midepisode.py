"""Preuve M0 — outils en cours d'épisode : A émet, B voit l'effet ; l'épisode
dépasse son délai → l'événement de A reste et ``episode.ended{timeout}`` est
écrit ; le même identifiant d'appel renvoyé est dédoublonné."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic import BaseModel

from mika.kernel.episode import EpisodePolicy, Outcome
from mika.kernel.events import Payload
from mika.kernel.faculty import EffectClass, Faculty
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.pipeline import EpisodeRequest
from mika.runtime.tools import ToolResult
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build, events_of


@dataclass(frozen=True, slots=True)
class NotesState:
    count: int = 0


class Added(Payload):
    what: str


class AddArgs(BaseModel):
    what: str


class NoArgs(BaseModel):
    pass


NOTES = Faculty("notes", state=NotesState, init=lambda p: NotesState())
ADDED = NOTES.event("added", Added, public=True)


@NOTES.reducer(ADDED)
def _added(s: NotesState, e, cx) -> NotesState:
    return replace(s, count=s.count + 1)


@NOTES.tool("note_add", description="Ajoute une note.", args=AddArgs, bundle="atelier", episodes=["STEP"],
            effect=EffectClass.INTERNAL)
async def note_add(args: AddArgs, ctx) -> ToolResult:
    await ctx.emit(ADDED.draft(what=args.what))
    return ToolResult(content="noté")


@NOTES.tool("note_count", description="Compte les notes.", args=NoArgs, bundle="atelier", episodes=["STEP"])
async def note_count(args: NoArgs, ctx) -> ToolResult:
    return ToolResult(content=str(ctx.state.count))


POLICIES = {
    "STEP": EpisodePolicy(kind="STEP", role="step", priority=1, lane="background", delivered=False,
                          visible=False, tool_bundles=frozenset({"atelier"}), deadline_s=30.0),
}


def scripted(req: LLMRequest) -> LLMResponse:
    n_tool = sum(1 for m in req.messages if m.role == "tool")
    if n_tool == 0:
        return LLMResponse("", (ToolCall("c1", "note_add", {"what": "idée"}),), stop="tool_use")
    if n_tool == 1:
        return LLMResponse("", (ToolCall("c2", "note_count", {}),), stop="tool_use")
    return LLMResponse("fini")


def latency(req: LLMRequest) -> float:
    n_tool = sum(1 for m in req.messages if m.role == "tool")
    return 120.0 if n_tool >= 2 else 1.0  # le troisième appel dépasse le délai de 30 s


def test_tools_emit_midepisode_timeout_and_dedupe(tmp_path):
    kernel, clock, llm = build(tmp_path, [NOTES], respond=scripted, latency=latency, policies=POLICIES)

    async def main():
        await kernel.start()
        first = await kernel.lanes.submit(EpisodeRequest(kind="STEP", target=None))
        second = await kernel.lanes.submit(EpisodeRequest(kind="STEP", target=None))
        count = kernel.mind.root.slices["notes"].count
        await kernel.stop()
        return first, second, count

    first, second, count = run_virtual(kernel.deps.clock, main)

    assert first.outcome is Outcome.TIMEOUT
    # B a vu l'effet de A (lecture de ses propres écritures)
    seen = [m.content for m in llm.calls[2].messages if m.role == "tool"]
    assert seen == ["noté", "1"]
    # le même identifiant d'appel « c1 » dans le second épisode est dédoublonné
    assert count == 1
    assert second.outcome is Outcome.TIMEOUT

    k2, _, _ = build(tmp_path, [NOTES], policies=POLICIES)

    async def read():
        await k2.mind.boot(append_boot=False)
        added = events_of(k2, "notes.added")
        ended = events_of(k2, "episode.ended")
        await k2.mind.close()
        return added, ended

    added, ended = run_virtual(k2.deps.clock, read)
    assert len(added) == 1
    assert [e.data.outcome for e in ended] == ["timeout", "timeout"]
