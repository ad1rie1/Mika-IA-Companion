"""Les sujets délicats, à la porte de la mémoire (lot I du chantier « émotions, conscience, mémoire », ADR 0099).

Ce qu'elle sait d'une personne et qui touche un de ses sujets délicats (son portrait : « sa rupture ») est une
confidence. Le rappel seul le recalculait ; ses pensées (une croyance révisée), ses buts, son journal lisaient la porte
(``KNOWLEDGE_VIEW``) à la sensibilité notée par la consolidation (« personnel ») et pouvaient la redire à une amie.
Désormais la mémoire le pose elle-même (``memory.delicate``) : un nouvel élément à son arrivée, tous ceux d'une personne
quand son portrait change ; jamais abaissé.
"""

from __future__ import annotations

import asyncio

from mika.contracts import memory as memory_c
from mika.contracts import social as social_c
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Content, Origin
from mika.sim.clock import run_virtual
from mika.vocab.knowledge import knowns
from tests.fixtures.mika import at_paris, boot, build
from tests.unit.test_bonds_over_time import Script

ALICE = "user_2"


def belief(text):
    return memory_c.BELIEVED.draft(text=Content.of(text, level=2), about=(ALICE,), told_by=(ALICE,),
                                   heard_by=(ALICE,), sensitivity=2)


def profile(*sensitive):
    return social_c.PROFILE_REVISED.draft(
        person=ALICE, summary=Content.of("Quelqu'un de drôle.", level=2), tone=Content.of("taquin", level=2),
        interests=Content.of("montagne", level=2),
        sensitive=Content.of("\n".join(sensitive), level=2) if sensitive else None)


def run(tmp_path, scenario):
    kernel, clock, _llm, _out = build(tmp_path, Script(), start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def door(kernel) -> dict[str, int]:
    """Ce que les autres facultés lisent : la sensibilité de chaque élément, par son texte."""
    rows = kernel.mind.store.query_mind(memory_c.select_known().where(memory_c.KNOWLEDGE.c.kind == memory_c.BELIEF))
    return {k.text: k.sensitivity for k in knowns(rows, memory_c.KNOWN_COLUMNS)}


async def genesis(kernel, draft, emitter):
    await kernel.mind.append([draft], emitter=emitter, correlation="genese", origin=Origin.GENESIS)
    await asyncio.sleep(MINUTE / US)


def test_what_touches_a_delicate_subject_is_a_confidence_for_everyone(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, profile("sa rupture avec Marc"), "social")
        await genesis(kernel, belief("Alice vit mal sa rupture avec Marc"), "memory")
        await genesis(kernel, belief("Alice adore la montagne"), "memory")
        return door(kernel)

    seen = run(tmp_path, scenario)
    assert seen["Alice vit mal sa rupture avec Marc"] == 3  # une confidence, à la porte
    assert seen["Alice adore la montagne"] == 2  # le reste ne bouge pas


def test_a_portrait_that_changes_reaches_what_she_already_knew_and_never_lowers_it(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, belief("Alice cherche un nouveau travail"), "memory")
        before = door(kernel)
        await genesis(kernel, profile("son travail"), "social")
        during = door(kernel)
        await genesis(kernel, profile(), "social")  # le portrait ne le dit plus : rien ne se rouvre
        return before, during, door(kernel)

    before, during, after = run(tmp_path, scenario)
    text = "Alice cherche un nouveau travail"
    assert (before[text], during[text], after[text]) == (2, 3, 3)
