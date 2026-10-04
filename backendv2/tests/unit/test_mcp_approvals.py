"""Les appels qui demandent un accord (ADR 0064), dans un vrai noyau avec un faux port ``mcp``.

Dans la conversation : l'outil propose l'appel et rien ne part ; la carte n'existe que pour la personne de
l'épisode, qui seule en décide, et seulement sur ce qui lui a été montré (l'empreinte) ; accepté, l'appel part, ce
qu'il rend revient comme un contenu (effaçable, jamais le champ brut de l'effet) que son prompt suivant lui montre —
une fois dit, il ne l'est plus ; un outil qui change avant l'accord bloque l'accord ; une carte sans réponse expire
et elle le sait. De l'opérateur : pas de carte, la console décide. L'initiative due part vers la personne quand
elle n'a pas écrit entre-temps."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from mika.app.mindport import KernelPort
from mika.contracts import mcp as c
from mika.contracts import runtime as rt
from mika.kernel.clock import MINUTE, US
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.mcp import ANSWERED, EXPIRED, prompt
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.mika import boot, build, connect, said
from tests.unit.test_mcp_plugin import NAME, FakePort, offered_tool

SECRET_ANSWER = "Grand soleil sur Lyon, 24 degrés."


class AnsweringPort(FakePort):
    def __init__(self, *tools):
        super().__init__(*tools)
        self.kept: dict[str, str] = {}

    async def call(self, server, remote, args, *, timeout_s=None):
        got = await super().call(server, remote, args, timeout_s=timeout_s)
        return replace(got, text=SECRET_ANSWER)

    def keep(self, request, text):
        self.kept[request] = text

    def take(self, request):
        return self.kept.pop(request, None)


def scripted(req: LLMRequest) -> LLMResponse:
    if req.role == "reply":
        asking = req.messages[-1].content.endswith("demain ?")
        if asking and not any(m.role == "tool" for m in req.messages):
            return LLMResponse("", tool_calls=(ToolCall("t1", NAME, {"ville": "Lyon"}),), stop="tool_use")
        return LLMResponse("Je te dis ça. [EMOTION:happy:0.4]")
    return LLMResponse("{}")


def live(tmp_path, scenario, port, respond=scripted):
    kernel, clock, llm, deliveries = build(tmp_path, respond, ports={"mcp": port}, arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            return await scenario(kernel, llm)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def ask(kernel, text="quel temps à Lyon demain ?"):
    perceived = await kernel.perceive(said("user_1", text, display_name="Adrien"))
    report = await perceived.reply
    await kernel.traces.flush()
    return report


def pending(kernel):
    effects = kernel.mind.frame().state("runtime").effects
    return {p.proposal: json.loads(effects[p.proposal].args_json) for p in kernel.mind.frame().get(rt.PENDING_EFFECTS)}


def test_in_the_conversation_only_she_decides_on_what_she_was_shown(tmp_path):
    port = AnsweringPort(offered_tool(approval="conversation", fingerprint="f1"))

    async def scenario(kernel, llm):
        mind_port = KernelPort(kernel)
        report = await ask(kernel)
        trace = kernel.traces.get(report.id)
        waiting = pending(kernel)
        (proposal,) = waiting
        cards = await mind_port.approval_cards("user_1")
        others = await mind_port.approval_cards("user_2")
        forbidden = await mind_port.decide_card("user_2", proposal, True, cards[0]["digest"])
        blind = await mind_port.decide_card("user_1", proposal, True, "")
        wrong = await mind_port.decide_card("user_1", proposal, True, "0" * 32)
        calls_before = list(port.calls)
        approved = await mind_port.decide_card("user_1", proposal, True, cards[0]["digest"])
        await asyncio.sleep(5)  # l'effet part sur sa voie, puis la réponse revient
        state = kernel.mind.frame().state("mcp")
        answered = kernel.mind.store.latest([c.ANSWERED.name, rt.EFFECT_EXECUTED.name], 5)
        untold = kernel.mind.frame().get(c.UNTOLD(proposal))
        # elle reparle à la personne : son prompt lui montre ce qui est revenu, et c'est alors dit
        await ask(kernel, "merci !")
        told = kernel.mind.frame().get(c.UNTOLD(proposal))
        replies = [r for r in llm.calls if r.role == "reply"]
        return (trace, waiting[proposal], cards, others, forbidden, blind, wrong, calls_before, approved, state,
                answered, untold, told, replies[-1])

    (trace, args, cards, others, forbidden, blind, wrong, calls_before, approved, state, answered, untold, told,
     last) = live(tmp_path, scenario, port)
    # rien n'est parti : l'outil a proposé l'appel et l'a dit
    assert calls_before == [] and "rien n'est encore parti" in trace["tool_calls"][0]["result"]
    assert args[rt.DECIDER] == "user_1" and args["args"] == {"ville": "Lyon"} and args["fingerprint"] == "f1"
    # la carte : à elle seule, exactement ce qui partira
    assert others == [] and len(cards) == 1
    assert '"ville": "Lyon"' in cards[0]["text"] and cards[0]["blocked"] == "" and cards[0]["expires_at"]
    assert (forbidden, blind, wrong) == ("forbidden", "changed", "changed")
    assert approved == "approved"
    # l'appel est parti avec ce qui était montré ; la réponse revient comme un contenu, pas dans l'effet
    assert port.calls == [("meteo", "prevision", {"ville": "Lyon"})]
    (req,) = state.requests.values()
    assert req.status == ANSWERED and req.text_ref and untold is True
    assert {e.type for e in answered} == {c.ANSWERED.name, rt.EFFECT_EXECUTED.name}
    assert all(SECRET_ANSWER not in str(e.data) for e in answered)  # le journal ne porte qu'une référence
    assert "CE QUE TES SERVICES T'ONT RENDU" in last.messages[-1].content
    assert SECRET_ANSWER in last.messages[-1].content and told is False


def test_a_tool_changed_before_approval_blocks_it(tmp_path):
    port = AnsweringPort(offered_tool(approval="conversation", fingerprint="f1"))

    async def scenario(kernel, llm):
        mind_port = KernelPort(kernel)
        await ask(kernel)
        (proposal,) = pending(kernel)
        digest = (await mind_port.approval_cards("user_1"))[0]["digest"]
        port.tools = [offered_tool(approval="conversation", fingerprint="f2")]
        kernel.refresh_tools()
        cards = await mind_port.approval_cards("user_1")
        return cards, await mind_port.decide_card("user_1", proposal, True, digest), port.calls

    cards, status, calls = live(tmp_path, scenario, port)
    assert "changé" in cards[0]["blocked"] and status == "blocked" and calls == []


def test_a_card_left_unanswered_expires_and_she_is_told(tmp_path):
    port = AnsweringPort(offered_tool(approval="conversation", fingerprint="f1"))

    async def scenario(kernel, llm):
        await ask(kernel)
        (proposal,) = pending(kernel)
        await asyncio.sleep(11 * MINUTE / US)
        frame = kernel.mind.frame()
        req = frame.state("mcp").requests[proposal]
        owed = prompt._owed(frame.state("mcp"), frame)
        return req, pending(kernel), owed, port.calls

    req, still, owed, calls = live(tmp_path, scenario, port)
    assert req.status == EXPIRED and still == {} and calls == []
    assert [x.reason for x in owed] == [c.ANSWERED_REASON] and owed[0].target == "user_1"
    assert "expiré" in owed[0].args["brief:mcp"]


def test_an_operator_approval_has_no_card_and_is_decided_in_the_console(tmp_path):
    port = AnsweringPort(offered_tool(approval="operateur", fingerprint="f1"))

    async def scenario(kernel, llm):
        mind_port = KernelPort(kernel)
        await ask(kernel)
        (proposal,) = pending(kernel)
        cards = await mind_port.approval_cards("user_1")
        shown = await mind_port.effect_preview(proposal)
        status = await mind_port.resolve_effect(proposal, True, by="user_1", seen=shown.digest)
        await asyncio.sleep(5)
        return cards, status, port.calls

    cards, status, calls = live(tmp_path, scenario, port)
    assert cards == [] and status == "approved" and calls == [("meteo", "prevision", {"ville": "Lyon"})]


def test_a_conversation_approval_tool_is_offered_only_where_someone_can_accept(tmp_path):
    port = AnsweringPort(offered_tool(approval="conversation", audience="comptes",
                                      episodes=frozenset({"conversation", "initiative", "travail"})))

    async def scenario(kernel, llm):
        from tests.unit.test_mcp_plugin import _offers

        return _offers(kernel), kernel.registry.tools[NAME].episodes

    offers, episodes = live(tmp_path, scenario, port)
    assert offers == {"propriétaire": {NAME}, "compte": {NAME}, "salon": set(), "inconnue": set()}
    assert episodes == frozenset({"REPLY"})  # en initiative ou en travail, personne pour accepter
