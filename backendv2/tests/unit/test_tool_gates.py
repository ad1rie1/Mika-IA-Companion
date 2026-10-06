"""Qui a quels outils, et ce qu'un outil a le droit d'écrire — par leurs intentions.

- devant une inconnue, les outils réservés à ses propriétaires ne sont même pas
  offerts (le modèle n'en voit pas le schéma) ; devant sa propriétaire, si ;
  les outils ordinaires restent offerts aux deux (le filtre ne ferme pas tout) ;
- un outil qui propose un effet extérieur passe par la vraie boucle d'outils
  et la proposition est bien écrite — au nom du runtime, corrélée à l'épisode ;
- un outil ne peut proposer que les capacités de sa propre faculté ;
- en conversation, le socle (mémoire, identité, buts) est en main ; le reste est
  à la demande, et le prompt stable dit, lot par lot, ce qu'elle peut aller
  chercher — le contrat v1 des capacités chargées paresseusement ; un fournisseur
  qui ne sait pas différer (Ollama) les reçoit tous et n'entend parler d'aucune
  recherche, y compris à travers la passerelle en service ;
- quand elle parle, ses outils sont ses mains : faire avant d'annoncer, ne rien
  raconter qu'un outil ne lui a pas rendu, et ne la renvoyer à la Forge que si
  elle lui est offerte ; sans flux suivi, ses flux ne disent pas « rien de neuf ».
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.effects import with_content
from mika.runtime.tools import ToolContext, acting, run_tool_loop
from mika.sim.clock import run_virtual
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said

ACTING = phrase("runtime.tools.acting")
CATALOGUE_HEADER = phrase("runtime.tools.catalogue_header")

RESERVED = {"forge_write", "forge_list", "forge_call", "camera_look", "create_project"}


def test_a_stranger_is_not_offered_the_tools_reserved_to_her_owners(tmp_path):
    offered: dict[str, set[str]] = {}

    def respond(req: LLMRequest) -> LLMResponse:
        target = req.meta.get("target")
        if target:
            offered[target] = {t.name for t in req.tools}
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    kernel, clock, _, _ = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_5", "Inconnue")
            await (await kernel.perceive(said("user_5", "Salut, tu fais quoi ?"))).reply
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "Salut, tu fais quoi ?"))).reply
            await kernel.lanes.join()
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    stranger, owner = offered["user_5"], offered["user_1"]
    assert not stranger & RESERVED
    assert RESERVED <= owner
    assert "memory_search" in stranger and "memory_search" in owner  # l'ordinaire reste offert
    assert "forge_help" in stranger  # le mode d'emploi n'est pas un secret


class _Once:
    """Une passerelle qui demande un outil, puis se tait."""

    def __init__(self, tool: ToolCall) -> None:
        self.tool = tool

    def is_voice(self, role: str) -> bool:
        return False

    async def call(self, req: LLMRequest) -> LLMResponse:
        if any(m.role == "tool" for m in req.messages):
            return LLMResponse("fait")
        return LLMResponse("", (self.tool,), stop="tool_use")


async def _open_project(kernel, *, approval: bool) -> int:
    commit = await kernel.mind.append([projects_c.PROJECT_CREATED.draft(
        title=Content.of("Un site", level=2), authority=projects_c.USER, owner="user_1", about=("user_1",),
        source="operator", sensitivity=2, approval=approval)], emitter="projects", correlation="genese",
        origin=Origin.GENESIS)
    return commit.seqs[-1]


def _context(kernel, name: str, project: int, episode: str) -> ToolContext:
    mind = kernel.mind
    base = mind.frame()
    frame = Frame(base.root, mind.clock.now(), mind.registry, Audience(owner=True),
                  EpisodeRef(episode, Kind.WORK, target=project_target(project)))
    return ToolContext(mind, mind.registry.tools[name], "appel-1", episode, frame)


def test_a_workshop_command_needing_the_network_is_proposed_through_the_tool_loop(tmp_path):
    kernel, clock, _, _ = build(tmp_path, lambda req: LLMResponse("[SILENCE]"), start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        try:
            project = await _open_project(kernel, approval=True)
            call = ToolCall("t1", "ws_network", {"argv": ["npm", "install"], "why": "installer les dépendances"})
            loop = await run_tool_loop(
                _Once(call), LLMRequest(role="project", call_id="ep-1#0", system_stable="", messages=()),
                {"ws_network": kernel.mind.registry.tools["ws_network"]},
                lambda spec, cid: _context(kernel, spec.name, project, "ep-1"), max_turns=3)
            evs = [with_content(kernel.mind, kernel.mind.decode(e)) for e in kernel.mind.store.read()]
            return loop, evs, project
        finally:
            await kernel.stop()

    loop, evs, project = run_virtual(clock, main)
    assert loop.calls == [("ws_network", True)], loop.records
    proposed = [e for e in evs if e.type.name == rt.EFFECT_PROPOSED.name]
    assert len(proposed) == 1
    p = proposed[0]
    assert p.type.owner == rt.OWNER and p.correlation == "ep-1" and p.origin == Origin.TOOL
    assert p.data.capability == "projects.networked" and p.data.approval is True
    assert p.data.context == project_target(project)
    assert kernel.mind.frame().get(rt.PENDING_EFFECTS)  # elle attend l'accord d'un opérateur


def test_a_tool_can_only_propose_the_capabilities_of_its_own_faculty(tmp_path):
    kernel, clock, _, _ = build(tmp_path, lambda req: LLMResponse("[SILENCE]"), start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        try:
            project = await _open_project(kernel, approval=True)
            ctx = _context(kernel, "ws_network", project, "ep-2")
            foreign = rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email", args_json="{}",
                                               summary=Content.of("un mail", level=0), approval=True)
            with pytest.raises(PermissionError):
                await ctx.propose(foreign)
            with pytest.raises(TypeError):
                await ctx.propose(rt.EFFECT_EXECUTED.draft(proposal=1, ok=True, result="x"))
            own = rt.EFFECT_PROPOSED.draft(capability="projects.networked", owner="projects", args_json="{}",
                                           summary=Content.of("réseau", level=0), approval=True)
            with pytest.raises(PermissionError):  # ce que faisaient les outils : émettre au nom du runtime
                await ctx.emit(own)
        finally:
            await kernel.stop()

    run_virtual(clock, main)


def test_in_conversation_the_core_is_in_hand_and_the_rest_is_fetched_on_demand(tmp_path):
    seen: list[LLMRequest] = []

    def respond(req: LLMRequest) -> LLMResponse:
        if req.meta.get("target") == "user_1":
            seen.append(req)
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    kernel, clock, _, _ = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "Salut !"))).reply
            await kernel.lanes.join()
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    req = seen[0]
    deferred = {t.name for t in req.tools if t.deferred}
    in_hand = {t.name for t in req.tools if not t.deferred}
    # en main, ce qu'une conversation sert vraiment (chercher dans sa mémoire, poser un rappel) ; le reste,
    # l'identité comprise, à la demande — une réponse ordinaire ne porte pas trente outils d'emblée
    assert {"memory_search", "goal_remind"} <= in_hand and len(in_hand) <= 6
    assert {"identity_whoami_with", "social_about"} <= deferred  # relire une section présente : à la demande
    assert {"forge_write", "rss_list", "camera_look", "forge_call"} <= deferred
    catalogue = req.system_stable.split(CATALOGUE_HEADER, 1)[1]
    assert "- forge : la Forge" in catalogue and "- rss : les flux" in catalogue
    assert "- social" in catalogue  # relire ce que ses sections disent déjà : à la demande
    assert "- memory" not in catalogue  # ce qui est en main n'est pas à chercher


def test_a_provider_that_cannot_defer_tools_gets_them_all_and_no_catalogue(tmp_path):
    """Ollama et les compatibles OpenAI ignorent ``deferred`` et reçoivent tous les outils : leur dire « ces outils
    ne sont pas chargés, cherche-les » était faux (sonde réelle du 2026-10-03, nemotron). Contre-exemple : le test
    précédent, où le fournisseur sait différer."""
    seen: list[LLMRequest] = []

    def respond(req: LLMRequest) -> LLMResponse:
        if req.meta.get("target") == "user_1":
            seen.append(req)
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    kernel, clock, llm, _ = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0))
    llm.defers_tools = False

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "Salut !"))).reply
            await kernel.lanes.join()
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    req = seen[0]
    assert not any(t.deferred for t in req.tools) and {"forge_write", "memory_search"} <= {t.name for t in req.tools}
    assert CATALOGUE_HEADER not in req.system_stable


class _Silent:
    """Un fournisseur qui ne dit rien de ce qu'il sait différer."""

    name = "muet"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return LLMResponse("")


def test_the_gateway_in_service_says_whether_its_provider_can_defer_tools():
    """Le test précédent pose ``defers_tools`` sur la passerelle factice ; en service, le pipeline parle à
    ``LiveGateway``, qui ne relayait pas la question : il concluait « oui », et nemotron (Ollama) recevait ses
    32 outils *et* « ils ne sont pas chargés d'emblée, cherche-les » (2026-10-04)."""
    from mika.adapters.llm.config import LiveGateway
    from mika.adapters.llm.gateway import Gateway
    from mika.adapters.llm.ollama import OllamaBackend
    from mika.adapters.system import RealClock
    from mika.runtime.pipeline import _defers

    def live(backend):
        return LiveGateway(Gateway({"m": backend}, {"reply": "m"}, clock=RealClock()))

    assert _defers(live(OllamaBackend("nemotron-3-super", client=object())), "reply") is False
    assert _defers(live(_Silent()), "reply") is True  # qui n'en dit rien sait différer (la déclaration le dit)
    assert _defers(LiveGateway(), "reply") is True  # sans configuration, l'appel échouera de toute façon


def test_when_she_speaks_her_tools_are_her_hands(tmp_path):
    """« Peux-tu regarder les nouvelles ? » — « je vais regarder », aucun appel, puis quatre tours d'actualité
    inventée (2026-10-04). Quand elle parle, le prompt stable lui dit de faire avant d'annoncer, de ne rien
    raconter qu'un outil ne lui a pas rendu, et — seulement si elle en a l'outil — qu'elle peut s'en donner les
    moyens dans sa Forge."""
    stable: dict[str, str] = {}

    def respond(req: LLMRequest) -> LLMResponse:
        target = req.meta.get("target")
        if target:
            stable[target] = req.system_stable
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    kernel, clock, _, _ = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_5", "Inconnue")
            await (await kernel.perceive(said("user_5", "Tu peux regarder les nouvelles ?"))).reply
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "Tu peux regarder les nouvelles ?"))).reply
            await kernel.lanes.join()
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    stranger, owner = stable["user_5"], stable["user_1"]
    assert ACTING in stranger and ACTING in owner

    def rule(text: str) -> str:
        return text.split(ACTING, 1)[1].split("\n", 1)[0]

    assert "ta Forge" in rule(owner)
    assert "Forge" not in rule(stranger)  # la Forge ne lui est pas offerte : elle n'y est pas renvoyée


def test_the_rule_of_her_hands_names_only_the_means_she_is_given():
    assert acting([]) == ""  # une parole sans outil n'a rien à en dire

    def spec(name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name)

    assert acting([spec("memory_search")]) == ACTING
    both = acting([spec("forge_write"), spec("start_project")])
    assert both.startswith(ACTING) and "ta Forge" in both and "un projet à toi" in both


def test_with_no_feed_followed_she_is_not_told_there_is_nothing_new():
    """« Rien de neuf dans tes flux » quand elle n'en suit aucun lui laissait croire qu'elle en suivait."""
    from mika.plugins.rss import ListArgs, rss_list
    from mika.sim.outside import FakeFeeds

    class NoFeed(FakeFeeds):
        def configured(self) -> bool:
            return False

    async def listed(port) -> str:
        return await rss_list(ListArgs(), SimpleNamespace(ports={"feeds": port}))

    assert "aucun flux" in asyncio.run(listed(NoFeed()))
    assert asyncio.run(listed(FakeFeeds())) == "Rien de neuf dans tes flux."


# ── Relire ce qui n'était que poussé : même porte que la section ──────────


def test_a_read_tool_says_nothing_the_prompt_would_not_say():
    from mika.kernel.prompt import SectionBody, readable

    class Aud:
        level, witness_level = 1, 2

    assert readable(SectionBody("un secret d'Alice", level=2), Aud()) is None
    assert readable(SectionBody("ce que vous avez vécu ensemble", level=2, witness=True), Aud()) == \
        "ce que vous avez vécu ensemble"
    assert readable(SectionBody("   "), Aud()) is None and readable(None, Aud()) is None
    assert readable("Pour toi, c'est une amie.", None) is None  # sans audience résolue, rien ne sort


def test_her_file_on_someone_is_read_back_to_them_but_never_to_a_stranger(tmp_path):
    answers: dict[str, str] = {}

    def respond(req: LLMRequest) -> LLMResponse:
        target = req.meta.get("target")
        results = [m.content for m in req.messages if m.role == "tool"]
        if results:
            answers[target] = results[0]
            return LLMResponse("Je vois. [EMOTION:neutral:0.3]")
        if target and any(t.name == "social_about" for t in req.tools):
            return LLMResponse("", (ToolCall("s1", "social_about", {}),), stop="tool_use")
        return LLMResponse("D'accord. [EMOTION:neutral:0.3]")

    kernel, clock, _, _ = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await befriend(kernel, kernel.mind.frame().get(identity_c.PERSON("user_1")))
            await (await kernel.perceive(said("user_1", "Tu sais qui je suis ?"))).reply
            await connect(kernel, "web_inconnu", "", authenticated=False)
            await (await kernel.perceive(said("web_inconnu", "Tu sais qui je suis ?"))).reply
            await kernel.lanes.join()
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    assert answers["user_1"].startswith("« Adrien » fait partie de tes amis")
    assert "ne peux pas relire" in answers["web_inconnu"]
