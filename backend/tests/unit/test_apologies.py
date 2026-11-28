"""Des excuses, et un pardon gradué (ADR 0047, HUM-14), par ses intentions.

- une amie l'insulte trois fois, puis s'excuse sincèrement (« pardon, j'étais à cran, je le pensais pas ») : ce que
  la relation avait installé d'hostile baisse nettement dans l'heure, sa posture le dit (« … t'a présenté ses
  excuses »), et ce que ces mots avaient coûté à son estime s'adoucit ;
- un troll qui écrit « pardon mdr » dix fois n'obtient rien ; des excuses sincères d'une inconnue comptent moins
  qu'une amie, et sa méfiance reste ;
- des excuses ne comptent qu'une fois par jour et par personne, et seulement s'il y a de quoi pardonner :
  « pardon de te déranger », « pardon ? », des condoléances ne sont pas des excuses.
"""

from __future__ import annotations

import asyncio

from mika.contracts import affect as affect_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.prompt import CONTEXT_FOOTER
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said
from tests.fixtures.reading import Reads

INSULTS = ("t'es nulle", "t'es vraiment conne", "ta gueule, tu sers à rien")
SINCERE = "pardon, j'étais à cran, je le pensais pas"


#: ce que le modèle lit de chaque message et du geste envers elle (ADR 0093 : c'est lui qui juge — une excuse qui
#: rit, « pardon mdr », il la lit amusée, sans geste ; le banc ``tools/banc_lecture`` le vérifie sur un vrai modèle)
READS = Reads({**{text: "angry 0.7 | geste : blessant" for text in INSULTS},
               SINCERE: "embarrassed 0.5, sad 0.3 | geste : excuses",
               "je m'excuse vraiment": "embarrassed 0.5 | geste : excuses",
               "désolée, j'ai été trop dure": "embarrassed 0.5 | geste : excuses",
               "pardon mdr": "amused 0.5"})


def script(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    if req.role in ("journal", "dream", "murmur", "narrative"):
        return LLMResponse("hmm")
    said_ = req.messages[-1].content.split(CONTEXT_FOOTER)[-1]
    reading = READS.tag(req) if req.role == "reply" else ""
    if said_.strip() in INSULTS:
        return LLMResponse(f"wow. ok. [EMOTION:angry:0.8]{reading}")
    return LLMResponse(f"hm.{reading}")


def after_three_insults(tmp_path, handle: str, closeness: str | None, then: tuple[str, ...]):
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 14, 0))

    async def main():
        await boot(kernel)
        try:
            if closeness:
                await befriend(kernel, handle, closeness)
            await connect(kernel, handle, "Alice")
            for text in INSULTS:
                await (await kernel.perceive(said(handle, text))).reply
                await asyncio.sleep(10 * MINUTE / US)
            frame = kernel.mind.frame()
            hurt, esteem_hurt = frame.get(affect_c.HOSTILITY(handle)), frame.get(self_c.ESTEEM)
            for text in then:
                await (await kernel.perceive(said(handle, text))).reply
                await asyncio.sleep(2 * MINUTE / US)
            await asyncio.sleep(HOUR / US)
            frame = kernel.mind.frame()
            kinds = [kernel.mind.decode(e).data.kind for e in kernel.mind.store.read()
                     if e.type == self_c.TOUCHED.name]
            prompt = [c for c in llm.calls if c.role == "reply"][-1].messages[-1].content
            return (hurt, frame.get(affect_c.HOSTILITY(handle)), esteem_hurt, frame.get(self_c.ESTEEM), kinds,
                    prompt)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_a_friends_sincere_apology_softens_what_the_insults_installed(tmp_path):
    hurt, healed, esteem_hurt, esteem_after, kinds, prompt = after_three_insults(
        tmp_path / "pardon", "user_1", social_c.FRIEND, (SINCERE, "bon"))
    still, kept, *_ = after_three_insults(tmp_path / "rien", "user_1", social_c.FRIEND, ("bon", "bon"))
    assert hurt > 0.05 and abs(still - hurt) < 0.01  # trois insultes ont installé de l'hostilité, qui tient l'heure
    assert kinds.count(self_c.APOLOGIZED) == 1
    assert healed < 0.6 * hurt and healed < 0.6 * kept  # nettement moins, dans l'heure
    # sa posture le dit ensuite : les excuses, c'est le modèle qui les lit dans le message auquel il répond (ADR 0093)
    assert "t'a présenté ses excuses" in prompt
    assert esteem_after > esteem_hurt  # ce que ces mots avaient coûté s'adoucit


def test_a_troll_laughing_sorry_ten_times_gets_nothing(tmp_path):
    hurt, after, _e0, _e1, kinds, _p = after_three_insults(tmp_path, "user_9", None, ("pardon mdr",) * 10)
    assert hurt > 0.05
    assert self_c.APOLOGIZED not in kinds
    assert after >= hurt - 0.01


def test_a_strangers_sincere_apology_counts_less_than_a_friends(tmp_path):
    hurt, after, *_ = after_three_insults(tmp_path / "inconnue", "user_9", None, (SINCERE,))
    f_hurt, f_after, *_ = after_three_insults(tmp_path / "amie", "user_1", social_c.FRIEND, (SINCERE,))
    assert after < hurt  # un peu
    assert after / hurt > f_after / f_hurt + 0.2  # mais bien moins qu'une amie


def test_an_apology_counts_once_a_day(tmp_path):
    *_, kinds, _p = after_three_insults(tmp_path, "user_1", social_c.FRIEND, (SINCERE, "je m'excuse vraiment",
                                                                              "désolée, j'ai été trop dure"))
    assert kinds.count(self_c.APOLOGIZED) == 1


def test_with_nothing_to_forgive_an_apology_falls_flat_and_spends_nothing(tmp_path):
    """« Pardon, j'étais à cran » d'une amie avec qui tout va bien : rien à pardonner, rien n'est consommé — des
    excuses le même jour, après des insultes, comptent encore."""
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 14, 0))

    async def main():
        await boot(kernel)
        try:
            await befriend(kernel, "user_1", social_c.FRIEND)
            await (await kernel.perceive(said("user_1", SINCERE))).reply
            early = [e for e in kernel.mind.store.read() if e.type == self_c.TOUCHED.name]
            for text in INSULTS:
                await (await kernel.perceive(said("user_1", text))).reply
                await asyncio.sleep(10 * MINUTE / US)
            await (await kernel.perceive(said("user_1", SINCERE))).reply
            kinds = [kernel.mind.decode(e).data.kind for e in kernel.mind.store.read()
                     if e.type == self_c.TOUCHED.name]
            return early, kinds
        finally:
            await kernel.stop()

    early, kinds = run_virtual(clock, main)
    assert not early
    assert kinds.count(self_c.APOLOGIZED) == 1


