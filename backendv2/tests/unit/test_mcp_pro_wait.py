"""En mode pro, un accord demandé s'attend dans la boucle (ADR 0165).

La personne regarde son travail : quand un outil d'un service demande son accord par une carte, Mika attend sa
décision avant de continuer — acceptée, l'appel part et elle lit ce qu'il a rendu, dans le même travail ; refusée,
elle le sait avant d'écrire. Ce qu'elle a lu ainsi est dit : aucune initiative ne le redit ensuite. Le contre-exemple :
dans la conversation ordinaire, l'outil rend la main tout de suite (« demandé, rien n'est encore parti »).
"""

from __future__ import annotations

import asyncio

from mika.app.mindport import KernelPort
from mika.contracts import mcp as c
from mika.kernel.clock import MINUTE, US
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.mika import boot, build, connect, said
from tests.unit.test_mcp_approvals import SECRET_ANSWER, AnsweringPort, pending
from tests.unit.test_mcp_plugin import NAME, ruled


def respond(req: LLMRequest) -> LLMResponse:
    if req.role in ("pro", "reply"):
        if not any(m.role == "tool" for m in req.messages):
            return LLMResponse("", tool_calls=(ToolCall("t1", NAME, {"ville": "Lyon"}),), stop="tool_use")
        return LLMResponse("C'est fait." if req.role == "pro" else "Je te dis ça. [EMOTION:happy:0.4]")
    return LLMResponse("{}")


def _life(tmp_path, decide, *, mode: str = "pro"):
    """Elle reçoit une demande (``mode``), propose l'appel ; ``decide(kernel, proposal)`` décide la carte. Rend ce
    qu'on a vu : si elle attendait encore à la décision, ses appels au modèle, ce qui est parti vers la personne, et
    si la réponse du service reste à dire."""
    port = AnsweringPort(ruled("carte", fingerprint="f1"))
    kernel, clock, llm, deliveries = build(tmp_path, respond, ports={"mcp": port}, arbitration=ArbitrationPolicy())
    seen: dict = {}

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            perceived = await kernel.perceive(said("user_1", "quel temps à Lyon demain ?", display_name="Adrien",
                                                   mode=mode))
            for _ in range(60):
                if pending(kernel) or perceived.reply.done():
                    break
                await asyncio.sleep(1)
            (proposal,) = pending(kernel)
            seen["waiting"] = not perceived.reply.done()
            await decide(kernel, proposal)
            seen["report"] = await perceived.reply
            await asyncio.sleep(20 * MINUTE / US)  # le temps qu'une initiative due parte, s'il y en avait une
            seen["untold"] = kernel.mind.frame().get(c.UNTOLD(proposal))
            seen["calls"] = list(port.calls)
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    said_to_him = [d for d in deliveries.items if d.target == "user_1" and d.text]
    return seen, [r for r in llm.calls if r.role in ("pro", "reply")], said_to_him


async def _accept(kernel, proposal):
    port = KernelPort(kernel)
    cards = await port.approval_cards("user_1")
    assert await port.decide_card("user_1", proposal, True, cards[0]["digest"]) == "approved"


async def _refuse(kernel, proposal):
    assert await KernelPort(kernel).decide_card("user_1", proposal, False, "") == "rejected"


def test_in_pro_mode_she_waits_for_the_card_and_goes_on_with_what_the_service_returned(tmp_path):
    seen, calls, said_to_him = _life(tmp_path, _accept)
    assert seen["waiting"] is True  # rien n'est écrit tant que la carte n'est pas décidée
    assert seen["calls"] == [("meteo", "prevision", {"ville": "Lyon"})]
    # le même travail continue avec ce que le service a rendu
    assert [c.role for c in calls] == ["pro", "pro"]
    assert SECRET_ANSWER in calls[1].messages[-1].content
    assert seen["report"].text == "C'est fait."
    # c'est dit : rien d'autre ne part vers lui, et la réponse du service n'est plus à dire
    assert [d.text for d in said_to_him] == ["C'est fait."] and seen["untold"] is False


def test_in_pro_mode_a_refusal_is_known_before_she_writes(tmp_path):
    seen, calls, said_to_him = _life(tmp_path, _refuse)
    assert seen["waiting"] is True and seen["calls"] == []
    assert "refusée" in calls[1].messages[-1].content and SECRET_ANSWER not in calls[1].messages[-1].content
    assert [d.text for d in said_to_him] == ["C'est fait."] and seen["untold"] is False


def test_in_the_ordinary_conversation_the_tool_hands_back_at_once(tmp_path):
    """Le contre-exemple : sans le mode pro, sa réponse part sans attendre la carte ; le résultat vient ensuite."""
    seen, calls, said_to_him = _life(tmp_path, _accept, mode="")
    assert seen["waiting"] is False
    assert "rien n'est encore parti" in calls[1].messages[-1].content
    assert said_to_him[0].text.startswith("Je te dis ça")
