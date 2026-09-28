"""M1 — bout en bout sur temps virtuel : elle salue qui arrive, répond, et
sa posture suit ce qu'elle déclare."""

from __future__ import annotations

import asyncio

from mika.contracts import affect as affect_c
from mika.kernel.episode import Outcome
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.affect import Emotion
from tests.fixtures.harness import events_of
from tests.fixtures.mika import boot, build, connect, said


def respond(req):
    if req.role == "initiative":
        return LLMResponse("Coucou Adrien ! Content·e de te voir [EMOTION:happy:0.6]")
    return LLMResponse("Ça va super, et toi ? [LAUGH] [EMOTION:excited:0.7]")


def test_greets_on_arrival_then_replies(tmp_path):
    kernel, clock, llm, out = build(tmp_path, respond, latency=2.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(120)  # temps virtuel : la salutation part en secondes
        greeted = list(out.items)
        perceived = await kernel.perceive(said("user_1", "salut ça va ?", display_name="Adrien"))
        report = await perceived.reply
        await asyncio.sleep(1)
        stance = kernel.mind.frame().get(affect_c.STANCE("user_1"))
        await kernel.stop()
        return greeted, report, stance

    greeted, report, stance = run_virtual(clock, main)
    assert len(greeted) == 1 and greeted[0].target == "user_1"
    assert "[EMOTION" not in greeted[0].text
    assert report.outcome is Outcome.DONE
    assert out.items[-1].text.startswith("Ça va super") and "[LAUGH]" in out.items[-1].text
    assert out.items[-1].emotion.emotion == "excited" and out.items[-1].emotion.declared
    assert stance.declared is not None and stance.declared.emotion is Emotion.EXCITED
    # l'initiative a reçu sa consigne ; la réponse, le message de la personne
    initiative = next(c for c in llm.calls if c.role == "initiative")
    assert "vient d'arriver" in initiative.messages[-1].content
    assert "« Adrien »" in initiative.messages[-1].content
    reply_call = next(c for c in llm.calls if c.role == "reply")
    assert reply_call.messages[-1].content.endswith("salut ça va ?")
    assert "QUI TU AS EN FACE" in reply_call.messages[-1].content
    assert "Tu es Mika" in reply_call.system_stable


def test_reply_history_is_the_persons_own_thread(tmp_path):
    kernel, clock, llm, out = build(tmp_path, lambda req: LLMResponse("ok [EMOTION:neutral:0.2]"))

    async def main():
        await boot(kernel)
        for who, text in (("user_1", "je m'appelle Adrien"), ("user_2", "secret de Bea"), ("user_1", "et toi ?")):
            p = await kernel.perceive(said(who, text))
            await p.reply
        await kernel.stop()

    run_virtual(clock, main)
    last = [c for c in llm.calls if c.role == "reply"][-1]
    contents = " ".join(m.content for m in last.messages)
    assert "je m'appelle Adrien" in contents
    assert "secret de Bea" not in contents  # le fil de Bea n'est pas celui d'Adrien


def test_no_tag_no_impulse(tmp_path):
    kernel, clock, llm, out = build(tmp_path, lambda req: LLMResponse("réponse sans balise"))

    async def main():
        await boot(kernel)
        before = kernel.mind.root.slices["affect"]
        p = await kernel.perceive(said("user_1", "hello"))
        await p.reply
        after = kernel.mind.root.slices["affect"]
        await kernel.stop()
        return before, after

    before, after = run_virtual(clock, main)
    assert before == after
    utt = events_of(kernel, "episode.utterance")
    assert utt and dict(utt[-1].data.annotations) == {}
