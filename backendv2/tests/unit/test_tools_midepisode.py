"""Preuve M0 — outils en cours d'épisode : A émet, B voit l'effet ; l'épisode
dépasse son délai → l'événement de A reste et ``episode.ended{timeout}`` est
écrit. Deux épisodes distincts qui font le même appel écrivent chacun : une
écriture d'outil se dédoublonne par ce qu'elle est dans son épisode (son tour),
jamais par l'identifiant d'appel du fournisseur, qui revient d'un épisode à
l'autre (``call_0``, « c1 » ici — ADR 0040, KER-23)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic import BaseModel

from mika.kernel.episode import EpisodePolicy, Outcome
from mika.kernel.events import Payload
from mika.kernel.faculty import EffectClass, Faculty, Zone
from mika.kernel.prompt import ChatTurn, SectionBody
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
    # le même identifiant d'appel « c1 » dans un second épisode, indépendant, n'efface pas sa note
    assert count == 2
    assert second.outcome is Outcome.TIMEOUT

    k2, _, _ = build(tmp_path, [NOTES], policies=POLICIES)

    async def read():
        await k2.mind.boot(append_boot=False)
        added = events_of(k2, "notes.added")
        ended = events_of(k2, "episode.ended")
        await k2.mind.close()
        return added, ended

    added, ended = run_virtual(k2.deps.clock, read)
    assert len(added) == 2
    assert [e.data.outcome for e in ended] == ["timeout", "timeout"]


# ── Ce que ses outils posent part avec le message (ADR 0062) ──────────────
# Un outil qui réussit peut poser des références opaques (``ToolResult.attach``) : la boucle les recueille (sans
# doublon, dans l'ordre, jamais celles d'un outil refusé), l'énoncé les porte. Et un message qui emporte un
# fichier n'est pas une redite, même quand sa phrase redit le dernier message du fil.

LAST = "Je t'ai préparé la liste complète des courses pour samedi midi."


@dataclass(frozen=True, slots=True)
class DeskState:
    n: int = 0


class FileArgs(BaseModel):
    ref: str
    ok: bool = True


DESK = Faculty("desk", state=DeskState, init=lambda p: DeskState())


@DESK.tool("attach_file", description="Joint un fichier.", args=FileArgs, bundle="bureau", episodes=["REPLY"])
async def attach_file(args: FileArgs, ctx) -> ToolResult:
    return ToolResult(ok=args.ok, content="joint" if args.ok else "refusé", attach=(args.ref,))


@DESK.section("history", zone=Zone.HISTORY, episodes=["REPLY"])
def _thread(s: DeskState, frame, enrich) -> SectionBody:
    """Le fil : son dernier message, celui qu'elle s'apprête à redire."""
    return SectionBody((ChatTurn("user", "tu peux me faire la liste ?", id=1), ChatTurn("assistant", LAST, id=2)),
                       thread="private:user_1")


REPLY_POLICIES = {"REPLY": EpisodePolicy(kind="REPLY", role="reply", priority=0, lane="conversation",
                                         tool_bundles=frozenset({"bureau"}))}


def attaching(calls: list[dict]):
    """Le modèle appelle ``attach_file`` avec chacun de ``calls`` (un tour), puis redit son dernier message."""
    def respond(req: LLMRequest) -> LLMResponse:
        n_tool = sum(1 for m in req.messages if m.role == "tool")
        if n_tool == 0 and calls:
            return LLMResponse("", tuple(ToolCall(f"c{i}", "attach_file", a) for i, a in enumerate(calls)),
                               stop="tool_use")
        return LLMResponse(LAST)
    return respond


def _reply(tmp_path, calls: list[dict]):
    kernel, clock, llm = build(tmp_path, [DESK], respond=attaching(calls), policies=REPLY_POLICIES)

    async def main():
        await kernel.start()
        report = await kernel.lanes.submit(EpisodeRequest(kind="REPLY", target="user_1", message="re"))
        uttered = events_of(kernel, "episode.utterance")
        await kernel.stop()
        return report, uttered

    return run_virtual(kernel.deps.clock, main)


def test_what_her_tools_attach_leaves_with_the_message(tmp_path):
    report, uttered = _reply(tmp_path, [{"ref": "f1"}, {"ref": "f2"}, {"ref": "f1"}, {"ref": "f3", "ok": False}])
    assert report.outcome is Outcome.DONE
    [e] = uttered
    assert e.data.attachments == ("f1", "f2")  # sans doublon, dans l'ordre ; rien d'un outil refusé


def test_a_message_with_a_file_is_not_a_repeat(tmp_path):
    report, uttered = _reply(tmp_path, [{"ref": "f1"}])
    assert report.outcome is Outcome.DONE and [e.data.attachments for e in uttered] == [("f1",)]


def test_without_a_file_the_same_words_are_still_a_repeat(tmp_path):
    """Le contre-exemple : la même phrase, sans fichier, ne part pas (ADR 0054)."""
    report, uttered = _reply(tmp_path, [{"ref": "f9", "ok": False}])
    assert report.outcome is Outcome.ABSTAINED and uttered == []
