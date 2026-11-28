"""Preuve M0 — course : une initiative composée pendant 60 s est supplantée si
la personne écrit entre-temps ; rien n'est livré ; la réponse, elle, l'est."""

from __future__ import annotations

import asyncio

from mika.kernel.clock import US
from mika.kernel.episode import Outcome
from mika.kernel.guards import Guard
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import run_virtual
from tests.fixtures.harness import CONTACTS, LAST_SEEN, build, events_of, said


def test_initiative_superseded_by_inbound_message(tmp_path):
    def latency(req):
        return 60.0 if req.role == "initiative" else 2.0

    kernel, clock, llm = build(tmp_path, [CONTACTS], latency=latency)

    async def main():
        await kernel.start()
        t0 = clock.now()
        initiative = kernel.lanes.submit(EpisodeRequest(
            kind="INITIATIVE", target="alice", reason="manque",
            extra_guard=Guard("toujours_silencieuse", reads=(LAST_SEEN("alice"),)),
        ))
        await asyncio.sleep(10)  # temps virtuel
        perceived = await kernel.perceive(said("alice", "coucou !"))
        report_i = await initiative
        report_r = await perceived.reply
        await kernel.stop()
        return t0, report_i, report_r

    t0, report_i, report_r = run_virtual(kernel.deps.clock, main)

    assert report_i.outcome is Outcome.SUPERSEDED
    assert "contacts.last_inbound('alice')" in report_i.detail
    assert report_r.outcome is Outcome.DONE and report_r.text

    # Journal : aucune énonciation d'initiative, une réponse liée à la perception.
    kernel2, _, _ = build(tmp_path, [CONTACTS])

    async def read():
        await kernel2.mind.boot(append_boot=False)
        utt = events_of(kernel2, "episode.utterance")
        ended = events_of(kernel2, "episode.ended")
        await kernel2.mind.close()
        return utt, ended

    utt, ended = run_virtual(kernel2.deps.clock, read)
    assert [u.data.kind for u in utt] == ["REPLY"]
    assert utt[0].data.reply_to is not None
    sup = [e for e in ended if e.data.kind == "INITIATIVE"]
    assert sup and sup[0].data.outcome == "superseded"
    assert sup[0].data.guard and "toujours_silencieuse" in sup[0].data.guard
    assert any("last_inbound" in c for c in sup[0].data.changed)
    # la réponse est partie bien avant les 60 s de l'initiative
    assert utt[0].at - t0 < 60 * US
