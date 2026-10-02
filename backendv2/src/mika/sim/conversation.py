"""Les scénarios du tour de conversation (ADR 0040).

- **S21** la rafale : trois messages en deux secondes pendant qu'elle compose —
  une seule réponse, qui les a tous lus, et qui règle les trois ; deux messages
  espacés d'une minute (deux tours) reçoivent bien deux réponses (contrôle) ;
- **S22** la latence sous charge : sur un modèle local à un seul créneau, un
  long pas de travail tient le modèle et une initiative attend son tour ; quand
  quelqu'un écrit, la réponse part en quelques secondes — le fond est
  interrompu et reviendra (contrôle : il tenait vraiment le modèle).
"""

from __future__ import annotations

import asyncio
from typing import Any

from mika.contracts import runtime as rt
from mika.kernel.clock import US
from mika.ports.llm import LLMRequest, LLMResponse
from mika.runtime.pipeline import EpisodeRequest
from mika.sim import expect
from mika.sim.clock import SimClock
from mika.sim.lane import Plan, Result, at_paris
from mika.sim.llm.scripted import ScriptedLLM
from mika.sim.rng import RngTree
from mika.sim.world import Driver
from mika.vocab.episodes import Kind, goal_target

#: ce que met le modèle à répondre, par rôle : le fond est long, la réponse courte
LATENCY = {"reply": 6.0, "initiative": 20.0, "step": 90.0, "murmur": 1.0}
#: la réponse doit partir dans ce délai après le dernier message, même quand tout le fond tourne
REPLY_WITHIN_S = 15.0

BURST = ("salut", "t'as vu le match hier ?", "allo ?")


def _llm(clock: SimClock, seed: int) -> ScriptedLLM:
    def respond(req: LLMRequest) -> LLMResponse:
        if req.role == "reply":
            return LLMResponse("Coucou ! Oui je l'ai vu, quel match ! [EMOTION:excited:0.6]")
        if req.role == "step":
            return LLMResponse("J'ai avancé. [EMOTION:determined:0.4]")
        if req.role == "initiative":
            return LLMResponse("Tu fais quoi de beau ? [EMOTION:playful:0.4]")
        if req.role == "murmur":
            return LLMResponse("tiens, si je lui écrivais")
        return LLMResponse("{}")

    return ScriptedLLM(clock, respond, latency=lambda r: LATENCY.get(r.role, 2.0))


def _utterances(driver: Driver, kind: str, target: str, after: int) -> list[Any]:
    return [e for e in driver.read_events() if e.type.name == rt.UTTERANCE.name and e.data.kind == kind
            and e.data.target == target and e.seq > after]


async def s21(driver: Driver, rng: RngTree, res: Result) -> None:
    await driver.connect("user_1", "Adrien")
    await asyncio.sleep(1200)  # la salutation éventuelle est passée
    sent = []
    for text in BURST:
        got = await driver.say("user_1", text, wait=False)
        sent.append(got.seq)
        await asyncio.sleep(1)
    assert driver.kernel is not None
    await driver.kernel.lanes.join()
    await asyncio.sleep(30)
    replies = _utterances(driver, "REPLY", "user_1", sent[0])
    call_ids = {r.data.voice.call_id for r in replies}
    shown = [m.content for c in driver.llm.calls if c.call_id in call_ids for m in c.messages]  # type: ignore[attr-defined]
    seen_all = all(any(text in m for m in shown) for text in BURST)
    last = replies[-1] if replies else None
    sent_at = next(e.at for e in driver.read_events() if e.seq == sent[-1])
    lag = (last.at - sent_at) / US if last else None
    # contrôle : deux tours séparés (une minute, la première réponse partie) restent deux réponses
    first = await driver.say("user_1", "bon, je file manger", wait=False)
    await driver.kernel.lanes.join()
    await asyncio.sleep(60)
    second = await driver.say("user_1", "re ! je suis rentré", wait=False)
    await driver.kernel.lanes.join()
    await asyncio.sleep(30)
    later = [u for u in _utterances(driver, "REPLY", "user_1", first.seq)
             if set(u.data.answers) & {first.seq, second.seq}]
    res.metrics.update({"réponses à la rafale": len(replies), "réglés": list(last.data.answers) if last else [],
                        "délai après le dernier message (s)": lag})
    res.checks += [
        expect.invariant("une rafale, une seule réponse", len(replies) == 1,
                         "trois messages coup sur coup : on répond une fois, pas trois",
                         f"{len(replies)} réponses"),
        expect.invariant("la réponse règle tout le tour", last is not None and last.data.reply_to == sent[-1]
                         and tuple(last.data.answers) == tuple(sent),
                         "elle répond au dernier message et règle les deux d'avant",
                         f"reply_to={last.data.reply_to if last else None}, réglés {last.data.answers if last else ()}"),
        expect.invariant("la réponse a lu les trois messages", seen_all,
                         "elle ne répond pas à « salut » sans savoir qu'on lui a demandé autre chose"),
        expect.band("délai après le dernier message (s)", lag,
                    "la réponse arrive en quelques secondes après le dernier message", hi=REPLY_WITHIN_S),
        expect.control("deux tours séparés, deux réponses",
                       first is not None and second is not None and len(later) == 2,
                       "la fusion ne mange pas un vrai second tour", f"{len(later)} réponses"),
    ]


async def s22(driver: Driver, rng: RngTree, res: Result) -> None:
    await driver.connect("user_1", "Adrien")
    await driver.connect("user_2", "Bea")
    await asyncio.sleep(1200)
    assert driver.kernel is not None
    lanes = driver.kernel.lanes
    # le fond : un long pas de travail tient le seul créneau du modèle local ; une initiative vers Bea attend
    # ce créneau dans la voie de la conversation
    step = lanes.submit(EpisodeRequest(kind=Kind.STEP, target=goal_target(1), reason="travail de fond",
                                       priority=2))
    await asyncio.sleep(1)
    initiative = lanes.submit(EpisodeRequest(kind=Kind.INITIATIVE, target="user_2", reason="envie de parler",
                                             priority=1))
    await asyncio.sleep(1)
    t0 = driver.clock.now()
    report = await driver.say("user_1", "t'es là ?")
    lag = (driver.clock.now() - t0) / US
    outcomes = {}
    for name, fut in (("pas", step), ("initiative", initiative)):
        got = await fut if fut is not None else None
        outcomes[name] = got.outcome.value if got is not None else None
    res.metrics.update({"délai de la réponse (s)": lag, "fond": outcomes})
    res.checks += [
        expect.invariant("la réponse est partie", report is not None and report.outcome.value == "done",
                         "quelqu'un écrit : elle répond", str(report.outcome if report else None)),
        expect.band("délai de la réponse sous charge (s)", lag,
                    "une réponse ne passe jamais derrière le fond ni une initiative", hi=REPLY_WITHIN_S),
        expect.control("le fond tenait vraiment le modèle", outcomes == {"pas": "preempted", "initiative": "preempted"},
                       "sinon ce scénario ne prouve rien : le pas et l'initiative ont été interrompus "
                       "(ils reviendront)", str(outcomes)),
    ]


CONVERSATION: tuple[Plan, ...] = (
    Plan("S21 la rafale : une seule réponse", s21, _llm, at_paris(2026, 9, 28, 14, 0)),
    Plan("S22 la latence sous charge", s22, _llm, at_paris(2026, 9, 28, 15, 0)),
)
