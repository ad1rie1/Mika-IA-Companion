"""Préemption : sur un modèle local à un seul créneau, quelqu'un qui écrit
n'attend pas la fin d'une longue génération de fond — elle est interrompue
(``preempted``), la réponse part, et le travail de fond sera reproposé."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mika.app import composition
from mika.contracts.runtime import UTTERANCE
from mika.kernel.clock import US
from mika.kernel.episode import EpisodePolicy, Outcome
from mika.kernel.events import Content
from mika.ports.llm import LLMRequest, LLMResponse, MissingPersona
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import run_virtual
from tests.fixtures.harness import events_of
from tests.fixtures.mika import boot, build, connect, said

STEP = EpisodePolicy(kind="STEP", role="step", priority=1, lane="background", delivered=False, visible=False,
                     persona_depth="compact")


def respond(req):
    return LLMResponse("fait. [EMOTION:determined:0.4]" if req.role == "step" else "je suis là ! [EMOTION:happy:0.5]")


def latency(req):
    return 120.0 if req.role == "step" else 2.0


def test_a_message_preempts_a_long_background_generation(tmp_path):
    kernel, clock, llm, out = build(tmp_path, respond, latency=latency,
                                    policies={**composition.policies(), "STEP": STEP})

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        step = kernel.lanes.submit(EpisodeRequest(kind="STEP", reason="travail de fond"))
        await asyncio.sleep(5)
        t_msg = clock.now()
        p = await kernel.perceive(said("user_1", "t'es là ?"))
        reply = await p.reply
        t_reply = clock.now()
        report = await step
        await kernel.stop()
        return t_msg, t_reply, reply, report

    t_msg, t_reply, reply, step_report = run_virtual(clock, main)
    assert reply.outcome is Outcome.DONE
    assert (t_reply - t_msg) / US < 10, "la réponse n'attend pas les 120 s du fond"
    assert step_report.outcome is Outcome.PREEMPTED
    ended = [e.data for e in events_of(kernel, "episode.ended") if e.data.kind == "STEP"]
    assert ended and ended[0].outcome == "preempted"


def test_no_voice_without_persona_and_no_authored_event_without_provenance(tmp_path):
    kernel, clock, llm, out = build(tmp_path, respond)

    async def main():
        await boot(kernel)
        with pytest.raises(MissingPersona):
            await kernel.deps.gateway.call(LLMRequest(role="reply", call_id="x", system_stable="sans persona"))
        p = await kernel.perceive(said("user_1", "coucou"))
        await p.reply
        await kernel.stop()

    run_virtual(clock, main)
    utt = events_of(kernel, "episode.utterance")
    assert utt and all(u.data.voice.persona_hash and u.data.voice.call_id for u in utt)
    with pytest.raises(ValidationError):  # un énoncé sans provenance de voix ne se construit même pas
        UTTERANCE.draft(kind="REPLY", text=Content.of("x"))
