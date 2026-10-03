"""Le récit qu'elle fait d'elle-même (« QUI TU ES DEVENUE », ADR 0053), par ses intentions.

Sonde réelle du 2026-10-03 : la semaine où le chat de Sam est mort, son récit a été réécrit à partir de « Sam est
parti en disant 'allez j'y vais' » et « je vais essayer de dormir » — les deux seuls souvenirs anodins, les plus
récents. Ce qui l'avait marquée (une perte chez quelqu'un qui compte, sa confiance) était personnel, donc absent.

- le récit choisit ses matériaux par saillance (importance, émotion), pas par ordre d'arrivée ;
- ce qui l'a marquée sans pouvoir se raconter y entre par ce que ça lui a fait — jamais qui, ni quoi.
"""

from __future__ import annotations

import asyncio

from mika.contracts import memory as memory_c
from mika.faculties.self import SelfParams
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build

MARKING = "J'ai appris à rester là, sans rien dire, quand quelqu'un a de la peine"
BANAL = ["Quelqu'un est parti en disant « allez j'y vais »", "On m'a dit « je vais essayer de dormir »",
         "On m'a dit bonjour ce matin", "Quelqu'un a dit « bon, à plus »", "On m'a demandé l'heure",
         "Quelqu'un a dit « ok »"]


def respond(req):
    if req.role == "narrative":
        return LLMResponse("Je suis quelqu'un qui apprend à rester là.")
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    return LLMResponse("d'accord [EMOTION:happy:0.5]")


def souvenir(text, *, importance, emotion=None, about=(), sensitivity=1):
    return memory_c.REMEMBERED.draft(text=Content.of(text, level=sensitivity), about=about, sensitivity=sensitivity,
                                     importance=importance, emotion=emotion)


def narrated_from(tmp_path):
    kernel, clock, llm, _ = build(tmp_path, respond, start=at_paris(2026, 10, 6, 21, 0))

    async def main():
        await boot(kernel)
        try:
            await kernel.set_params("self", SelfParams(narrative_max_souvenirs=5))
            await befriend(kernel, "user_1", "close")
            # le plus marquant est le plus ancien ; la confidence ne se raconte pas ; puis des banalités récentes
            drafts = [souvenir(MARKING, importance=0.9, emotion="sad"),
                      souvenir("CANARI-CONFIDENCE Pixel, le chat de Sam, est mort", importance=0.95, emotion="sad",
                               about=("user_1",), sensitivity=3),
                      *(souvenir(t, importance=0.2) for t in BANAL)]
            await kernel.mind.append(drafts, emitter="memory", correlation="genese", origin=Origin.GENESIS)
            await asyncio.sleep(10 * MINUTE / US)
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    return [c.messages[-1].content for c in llm.calls if c.role == "narrative"]


def test_her_story_starts_from_what_marked_her_not_from_the_latest_trifles(tmp_path):
    shown = narrated_from(tmp_path)
    assert shown, "elle a réécrit son récit"
    told = shown[-1].split("Ce que tu as vécu, du plus marquant au moins marquant :\n", 1)[1].splitlines()
    assert told[0] == f"- {MARKING}"  # avant : les cinq plus récents — des banalités, et pas lui
    assert len(told) == 5 and sum(1 for t in told if t[2:] in BANAL) == 4


def test_what_marked_her_but_cannot_be_told_enters_only_as_what_it_did_to_her(tmp_path):
    shown = narrated_from(tmp_path)[-1]
    assert "tu t'es sentie triste, avec quelqu'un qui compte pour toi" in shown
    assert "CANARI-CONFIDENCE" not in shown and "Pixel" not in shown and "Sam" not in shown
