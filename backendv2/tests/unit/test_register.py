"""Le ton selon le lien (ADR 0046, audit HUM-15) : rien ne traduisait la proximité en manière d'être — elle
taquinait une inconnue dès son premier message. Une inconnue : chaleureuse, sans taquinerie ; une proche : la
complicité, la taquinerie permise."""

from __future__ import annotations

import pytest

from mika.contracts import social as social_c
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.memory import section
from tests.fixtures.mika import befriend, boot, build, connect, said

TONE = "LE TON ENTRE VOUS"


@pytest.mark.parametrize("level", [None, social_c.CLOSE])
def test_she_does_not_tease_a_stranger_but_may_tease_a_close_friend(tmp_path, level):
    calls = []

    def script(req):
        calls.append(req)
        return LLMResponse("{}" if req.role in ("extract", "profile", "compact") else "salut ! [EMOTION:happy:0.5]")

    kernel, clock, _llm, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        if level:
            await befriend(kernel, "user_1", level)
        await connect(kernel, "user_1", "Chloé")
        p = await kernel.perceive(said("user_1", "salut, je découvre l'appli"))
        await p.reply
        await kernel.stop()

    run_virtual(clock, main)
    reply = next(r for r in calls if r.role == "reply")
    tone = section("\n".join(m.content for m in reply.messages), TONE)
    if level is None:
        assert "ne la taquine pas" in tone, tone
    else:
        assert "tu peux la taquiner" in tone and "ne la taquine pas" not in tone, tone
