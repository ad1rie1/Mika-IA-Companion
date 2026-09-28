"""La compaction : un long fil se replie en résumé — ce que voit le modèle
change, le journal et l'historique non."""

from __future__ import annotations

import asyncio

from mika.faculties.transcript import TranscriptParams
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.harness import events_of
from tests.fixtures.mika import AFTERNOON, boot, build, connect, said


def test_a_long_thread_folds_into_a_summary(tmp_path):
    clock = SimClock(AFTERNOON)
    llm = PersonaSimLLM(clock, seed=1, latency=1.0, abstain_rate=0.0)
    kernel, clock, _, out = build(tmp_path, lambda req: None, clock=clock, llm=llm)

    async def main():
        await boot(kernel)
        await kernel.set_params("transcript", TranscriptParams(compact_after=10, keep=4))
        await connect(kernel, "user_2", "Alice")
        for i in range(12):
            p = await kernel.perceive(said("user_2", f"message numéro {i} sur le jardinage et les tomates"))
            await p.reply
            await asyncio.sleep(60)
        await asyncio.sleep(15 * 60)
        p = await kernel.perceive(said("user_2", "bon, on en était où ?"))
        await p.reply
        history = kernel.mind.store.query_mind("SELECT COUNT(*) FROM thread WHERE person='user_2'")[0][0]
        await kernel.stop()
        return history

    history = run_virtual(clock, main)
    compacted = [e.data for e in events_of(kernel, "transcript.compacted")]
    assert compacted, "le fil a été replié"
    last = [r for r in llm.calls if r.role == "reply"][-1]
    first = last.messages[0].content
    assert first.startswith("(Plus tôt, entre vous — en résumé :"), first[:80]
    shown = " ".join(m.content for m in last.messages[1:])  # après le tour de résumé
    assert "message numéro 0 " not in shown, "le début du fil n'est plus montré tel quel"
    assert "message numéro 11 " in shown, "les derniers échanges, si"
    assert history == 26, "le verbatim reste dans l'historique"
    assert all(c.upto <= kernel.mind.root.slices["memory"].checkpoint for c in compacted), \
        "on ne replie que ce que la mémoire a déjà relu"
