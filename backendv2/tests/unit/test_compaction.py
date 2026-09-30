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


def test_a_backlog_folds_oldest_first_in_bounded_batches(tmp_path):
    """Un retard de repli se rattrape par lots, les plus anciens d'abord :
    chaque résumé ne couvre que ce qu'il a réellement lu, et aucun appel ne
    reçoit un prompt démesuré."""
    clock = SimClock(AFTERNOON)
    llm = PersonaSimLLM(clock, seed=1, latency=1.0, abstain_rate=0.0)
    kernel, clock, _, out = build(tmp_path, lambda req: None, clock=clock, llm=llm)

    async def main():
        await boot(kernel)
        await kernel.set_params("transcript", TranscriptParams(compact_after=10, keep=4, compact_batch=6,
                                                               compact_min_fold=3))
        await connect(kernel, "user_2", "Alice")
        for i in range(14):
            p = await kernel.perceive(said("user_2", f"message numéro {i} sur les champignons"))
            await p.reply
            await asyncio.sleep(60)
        await asyncio.sleep(40 * 60)
        ids = [r[0] for r in kernel.mind.store.query_mind("SELECT id FROM thread WHERE person='user_2' ORDER BY id")]
        await kernel.stop()
        return ids

    ids = run_virtual(clock, main)
    compacted = [e.data for e in events_of(kernel, "transcript.compacted")]
    assert len(compacted) >= 2, "le retard se rattrape en plusieurs passages"
    assert all(c.count <= 6 for c in compacted), [c.count for c in compacted]
    assert compacted[0].upto == ids[compacted[0].count - 1], "le premier lot replie les plus anciens"
    covered = sum(c.count for c in compacted)
    assert compacted[-1].upto == ids[covered - 1], "chaque résumé couvre exactement ce qu'il a lu"
    prompts = [r for r in llm.calls if r.role == "compact"]
    assert all(r.messages[-1].content.count("\n") <= 6 + 3 for r in prompts)
