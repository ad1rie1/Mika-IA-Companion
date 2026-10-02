"""Son estime, par ses intentions.

- mener quelque chose à bout redonne confiance selon ce que ça lui a demandé :
  dix petites choses faites en une séance ne font pas une semaine de fierté
  (au plus tant par jour), un vrai travail compte plus qu'une formalité ;
- elle est aussi un sociomètre : un merci ou un compliment d'une amie la
  relève un peu, une insulte qui la vise la blesse un peu — moins venant d'une
  inconnue, et un troll qui insiste ne la démolit pas ; ce qui ne la vise pas
  (« ce film est nul ») n'y change rien ;
- quand elle doute, la phrase dit la vraie cause (et seulement « tu doutes un
  peu de toi » quand aucune ne domine).
"""

from __future__ import annotations

import asyncio

from mika.contracts import goals as goals_c
from mika.contracts import self_ as self_c
from mika.faculties.self import (
    IGNORED,
    STUCK,
    SelfParams,
    SelfState,
    doubt_cause,
)
from mika.faculties.self.records import Knock
from mika.faculties.self.worth import touched
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said

P = SelfParams()


def script(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    if req.role in ("journal", "dream", "murmur", "narrative"):
        return LLMResponse("hmm")
    return LLMResponse("d'accord [EMOTION:happy:0.5]")


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 9, 0)):
    kernel, clock, llm, _ = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main), llm


def esteem(kernel) -> float:
    return kernel.mind.frame().get(self_c.ESTEEM)


async def goal(kernel, gid: int, steps: int, status: str = goals_c.ACHIEVED) -> None:
    """Un but qu'elle a mené (ou pas) au bout de tant de séances."""
    title = Content.of(f"chose n°{gid}", level=1)
    drafts = [goals_c.GOAL_OPENED.draft(kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=title)]
    drafts += [goals_c.STEP_REPORTED.draft(goal=gid, verdict=goals_c.CONTINUE, summary=Content.of("j'avance", level=1),
                                          tools=("web_read",)) for _ in range(steps - 1)]
    drafts.append(goals_c.STEP_REPORTED.draft(goal=gid, verdict=goals_c.DONE, summary=Content.of("fini", level=1),
                                              proven=status == goals_c.ACHIEVED, tools=("web_read",)))
    drafts.append(goals_c.GOAL_CLOSED.draft(goal=gid, status=status, kind=goals_c.EXPLORATION,
                                            authority=goals_c.SELF, title=title))
    await kernel.mind.append(drafts, emitter="goals", correlation=f"but:{gid}", origin=Origin.GENESIS)


def test_ten_small_things_in_a_day_do_not_make_a_week_of_pride(tmp_path):
    async def scenario(kernel):
        for i in range(10):
            await goal(kernel, i + 1, steps=1)
            await asyncio.sleep(30 * MINUTE / US)
        return esteem(kernel)

    after, _ = run(tmp_path, scenario)
    assert 0.5 < after <= 0.5 + P.achieved_daily_cap + 1e-6  # avant : 0,5 + 10 × 0,05 = 0,95 (plafond)


def test_real_work_counts_more_than_a_formality(tmp_path):
    async def scenario(kernel):
        await goal(kernel, 1, steps=1)
        quick = esteem(kernel) - 0.5
        await asyncio.sleep(3 * 24 * HOUR / US)  # un autre jour, l'estime revenue presque au repos
        before = esteem(kernel)
        await goal(kernel, 2, steps=5)
        return quick, esteem(kernel) - before

    (quick, worked), _ = run(tmp_path, scenario)
    assert 0.005 < quick < 0.025  # une chose faite en une séance : un petit plus
    assert worked > 2 * quick  # cinq séances de travail : nettement plus


def test_what_people_say_of_her_touches_her_a_little(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")
        await (await kernel.perceive(said("user_1", "merci Mika, t'es géniale"))).reply
        thanked = esteem(kernel)
        await (await kernel.perceive(said("user_1", "ce film est nul, j'ai détesté"))).reply
        unmoved = esteem(kernel)
        await connect(kernel, "user_9", "Troll")
        await (await kernel.perceive(said("user_9", "t'es nulle"))).reply
        stung = esteem(kernel)
        for _ in range(15):
            await (await kernel.perceive(said("user_9", "t'es vraiment nulle, tu sers à rien"))).reply
        trolled = esteem(kernel)
        touches = [kernel.mind.decode(e).data.kind for e in kernel.mind.store.read() if e.type == self_c.TOUCHED.name]
        return thanked, unmoved, stung, trolled, touches

    (thanked, unmoved, stung, trolled, touches), _ = run(tmp_path, scenario)
    assert 0.51 < thanked <= 0.5 + P.thanked_knock + 1e-6  # un merci d'une proche : un peu
    assert abs(unmoved - thanked) < 1e-3  # ce qui ne la vise pas n'y change rien
    assert thanked - stung < -P.insulted_knock  # une inconnue blesse moins qu'une amie ne le ferait
    assert stung < thanked
    assert trolled >= thanked - P.social_daily_cap - 1e-3  # un troll qui insiste ne la démolit pas
    assert touches[0] == self_c.COMPLIMENTED and touches.count(self_c.INSULTED) == 16


def test_teasing_and_politeness_are_not_insults_or_thanks():
    assert touched("t'es nulle mdr") is None  # une moquerie qui rit
    assert touched("t'es pas nulle du tout") is None
    assert touched("non merci, ça ira") is None
    assert touched("ce jeu est nul") is None
    assert touched("je t'aime pas, ce film") is None and touched("je te déteste plus, va") is None  # nié aussitôt
    assert touched("je te déteste") == self_c.INSULTED and touched("je t'aime") == self_c.COMPLIMENTED  # contrôles
    assert touched("t'es nulle") == self_c.INSULTED  # contrôle
    assert touched("merci beaucoup !") == self_c.THANKED
    assert touched("je t'adore") == self_c.COMPLIMENTED


def test_her_doubt_says_its_real_cause():
    now = at_paris(2026, 9, 30, 12, 0)
    stuck = SelfState(knocks=tuple(Knock(now - i * HOUR, STUCK, -0.04) for i in range(4)))
    assert "bloqué" in doubt_cause(stuck, now, P) and "répondu" not in doubt_cause(stuck, now, P)
    ignored = SelfState(knocks=(Knock(now - HOUR, IGNORED, -0.03), Knock(now - 2 * HOUR, IGNORED, -0.03)))
    assert "personne n'a répondu" in doubt_cause(ignored, now, P)
    once = SelfState(knocks=(Knock(now - HOUR, IGNORED, -0.03),))
    assert doubt_cause(once, now, P) == "tu as écrit et on ne t'a pas répondu"
    mixed = SelfState(knocks=(Knock(now - HOUR, IGNORED, -0.03), Knock(now - HOUR, STUCK, -0.04),
                              Knock(now - HOUR, self_c.INSULTED, -0.02), Knock(now - HOUR, "promise", -0.03)))
    assert doubt_cause(mixed, now, P) == ""  # rien ne domine : elle doute, sans cause à dire


def test_blocked_she_doubts_and_her_prompt_says_why(tmp_path):
    async def scenario(kernel):
        for i in range(4):
            await goal(kernel, i + 1, steps=2, status=goals_c.STUCK)
        low = esteem(kernel)
        await (await kernel.perceive(said("user_1", "salut, ça va ?"))).reply
        return low

    low, llm = run(tmp_path, scenario)
    assert low < P.doubt_below
    shown = [c.messages[-1].content for c in llm.calls if c.role == "reply"][-1]
    assert "Tu doutes un peu de toi en ce moment : tu as bloqué" in shown
    assert "personne n'a répondu" not in shown  # avant : la même cause, quelle que soit la vraie
