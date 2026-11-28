"""Une initiative choisie puis restée en file est jugée sur l'état du moment
où elle a été choisie : si la personne écrit pendant l'attente, elle est
devancée — et l'arbitre ne choisit pas deux fois la même ligne en attente."""

from __future__ import annotations

import asyncio

from mika.kernel.episode import Outcome
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.harness import events_of
from tests.fixtures.mika import boot, build, connect, said


def respond(req):
    return LLMResponse("ok [EMOTION:happy:0.5]")


def latency(req):
    return 40.0 if req.role == "reply" else 2.0


def test_a_queued_greeting_is_superseded_when_the_person_writes_while_it_waits(tmp_path):
    kernel, clock, llm, out = build(tmp_path, respond, latency=latency)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        p1 = await kernel.perceive(said("user_1", "une longue question"))  # occupe la voie 40 s
        await asyncio.sleep(1)
        await connect(kernel, "user_2", "Bea")  # sa salutation sera choisie puis attendra
        await asyncio.sleep(25)
        p2 = await kernel.perceive(said("user_2", "coucou, j'arrive"))  # elle écrit pendant l'attente
        await p1.reply
        await p2.reply
        await asyncio.sleep(120)
        await kernel.stop()

    run_virtual(clock, main)
    started = [e.data for e in events_of(kernel, "episode.started") if e.data.kind == "INITIATIVE"
               and e.data.target == "user_2"]
    said_to_bea = [u.data for u in events_of(kernel, "episode.utterance") if u.data.target == "user_2"]
    assert all(u.kind == "REPLY" for u in said_to_bea), "on ne salue pas quelqu'un qui vient d'écrire"
    ended = [e.data for e in events_of(kernel, "episode.ended") if e.data.kind == "INITIATIVE"
             and e.data.target == "user_2"]
    assert len(started) <= 1 and all(e.outcome == Outcome.SUPERSEDED for e in ended)
    selected = [e.data for e in events_of(kernel, "kernel.selected") if "INITIATIVE:user_2" in e.data.fired]
    assert len(selected) <= 1, "une ligne en attente n'est pas choisie deux fois"
