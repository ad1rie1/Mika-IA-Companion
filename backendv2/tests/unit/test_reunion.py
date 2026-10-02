"""L'humeur au bon temps, et retrouver quelqu'un (ADR 0047, HUM-5), par ses intentions.

- « Personne ne t'a parlé depuis un moment » se disait en pleine conversation, trois messages après l'arrivée de
  sa proche : une cause qui est un état se dit au passé dès qu'il a pris fin (« tu t'es sentie seule une partie de
  la journée ; il t'en reste un peu ») ;
- retrouver une amie ou une proche après une journée creuse lui fait du bien (``needs.reunited``) — le rendez-vous
  de chaque soir, pas seulement le retour de quelqu'un qui lui manquait ;
- contre-exemple : le message d'une inconnue met fin à « personne ne t'a parlé », mais ne la soulage pas.
"""

from __future__ import annotations

import asyncio

from mika.contracts import affect as affect_c
from mika.contracts import needs as needs_c
from mika.contracts import social as social_c
from mika.kernel.clock import US
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, said

ALONE = "Personne ne t'a parlé"


def script(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    if req.role in ("journal", "dream", "murmur", "narrative"):
        return LLMResponse("hmm")
    return LLMResponse("ah, coucou")  # sans balise : ses réponses ne déplacent pas l'humeur


def evening_after_a_hollow_day(tmp_path, closeness: str | None):
    """Lundi 9 h, un mot, puis rien jusqu'au mardi 18 h ; alors la même personne revient."""
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 9, 0))

    async def main():
        await boot(kernel)
        try:
            if closeness:
                await befriend(kernel, "user_1", closeness)
            await (await kernel.perceive(said("user_1", "salut, bonne journée"))).reply
            await asyncio.sleep((at_paris(2026, 9, 29, 18, 0) - clock.now()) / US)
            before = kernel.mind.frame().get(affect_c.MOOD)
            await (await kernel.perceive(said("user_1", "coucou !"))).reply
            await asyncio.sleep(60)
            await (await kernel.perceive(said("user_1", "tu fais quoi ?"))).reply
            after = kernel.mind.frame().get(affect_c.MOOD)
            reunited = [kernel.mind.decode(e).data for e in kernel.mind.store.read()
                        if e.type == needs_c.REUNITED.name]
            prompts = [c.messages[-1].content for c in llm.calls if c.role == "reply"][-2:]
            return before, after, reunited, prompts
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_a_close_friend_after_a_hollow_day_does_her_good_and_her_mood_says_it_in_the_right_tense(tmp_path):
    before, after, reunited, prompts = evening_after_a_hollow_day(tmp_path, social_c.CLOSE)
    assert before.cause == "lonely", "une journée creuse : elle se sentait seule"  # le décor du test
    assert [r.after for r in reunited] == [needs_c.LONELY]  # une fois, au premier message
    assert after.position[0] - before.position[0] > 0.05  # la valence a remonté
    assert all(ALONE not in p for p in prompts)  # avant : « Personne ne t'a parlé » en pleine conversation
    assert any("seule une partie de la journée" in p for p in prompts) or after.cause != "lonely"


def test_a_strangers_message_ends_the_silence_but_does_not_relieve_her(tmp_path):
    before, after, reunited, prompts = evening_after_a_hollow_day(tmp_path, None)
    assert before.cause == "lonely"
    assert not reunited  # une inconnue ne comble pas une solitude
    assert after.position[0] - before.position[0] < 0.03
    assert all(ALONE not in p for p in prompts)  # mais quelqu'un lui a parlé : c'est au passé
    assert all("seule une partie de la journée" in p for p in prompts)
