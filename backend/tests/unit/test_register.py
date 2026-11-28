"""Ce qui vous lie (ADR 0046, audit HUM-15) : rien ne disait la proximité — elle taquinait une inconnue dès son
premier message. Le code le lui dit, une fois (« CE QUI VOUS LIE ») : une inconnue, une proche — le lien, jamais la
conduite (taquiner ou non est à elle, à son caractère et à la conversation)."""

from __future__ import annotations

import pytest

from mika.contracts import social as social_c
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.memory import section
from tests.fixtures.mika import befriend, boot, build, connect, said

TIE = "CE QUI VOUS LIE"


@pytest.mark.parametrize("level, said_", [(None, "Tu ne connais pas encore cette personne."),
                                          (social_c.CLOSE, "Cette personne compte parmi tes proches.")])
def test_she_knows_what_ties_her_to_the_person_never_how_to_behave(tmp_path, level, said_):
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
    state = "\n".join(m.content for m in reply.messages)
    tie = section(state, TIE)
    assert said_ in tie, tie
    assert "taquin" not in tie and "charri" not in tie and "plaisant" not in tie, tie  # le lien, pas la conduite
    assert state.count(said_) == 1  # une seule maison : ni sa fiche, ni « QUI TU AS EN FACE » ne le redisent
