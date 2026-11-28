"""Les fils de travail du mode pro (ADR 0164) : chacun son contexte, chacun son tour.

En mode pro, un message porte son fil de travail (``strand``). Elle n'y relit que les messages de ce fil, sous ce que
son opératrice en a écrit (un titre, une petite description) ; le fil avec elle ne relit plus les fils de travail. Deux
fils sont deux tours : une question dans l'un ne supplante pas la réponse qui s'écrit dans l'autre. Le contre-exemple
de chaque règle : le fil ordinaire, inchangé, relit ce qu'on y a dit.
"""

from __future__ import annotations

import asyncio

from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties import transcript
from mika.faculties.transcript import strand_about
from mika.kernel.clock import HOUR
from mika.kernel.events import Content, Origin
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, LLMResponse
from mika.runtime.pipeline import Outcome
from mika.runtime.state import Pending, RuntimeState, turn_of, turn_upto
from mika.sim.clock import run_virtual
from tests.fixtures.mika import SHIPPED, at_paris, boot, build, connect, said


def _seen(req: LLMRequest) -> str:
    return req.system_stable + "".join(m.content for m in req.messages)


def _life(tmp_path, script, *, latency: float = 0.0):
    """Une opératrice et ses messages (``script`` : une fonction qui les envoie) ; ce que chaque réponse a relu."""
    prompts: list[LLMRequest] = []

    def respond(req):
        if req.role in ("reply", "pro"):
            prompts.append(req)
            return LLMResponse("Voilà." if req.role == "pro" else "D'accord ! [EMOTION:calm:0.3]")
        return LLMResponse("{}" if req.role in ("extract", "profile") else "[SILENCE]")

    kernel, clock, _llm, deliveries = build(
        tmp_path, respond, start=at_paris(2026, 10, 31, 10, 0),
        latency=lambda r: latency if r.role == "pro" else 0.0)
    seen: dict = {}

    async def main():
        await boot(kernel, SHIPPED)
        await connect(kernel, "user_1", "Adrien", operator=True)
        await asyncio.sleep(2 * HOUR / 1e6)
        await script(kernel, seen)
        seen["store"] = kernel.mind.store
        seen["rows"] = transcript.recent(kernel.mind.store, "user_1", 50)
        seen["strands"] = transcript.strands_of(kernel.mind.store, "user_1")
        await kernel.stop()

    run_virtual(clock, main)
    return seen, prompts, [d for d in deliveries.items if d.target == "user_1" and d.text]


async def _ask(kernel, text: str, **kw):
    got = await kernel.perceive(said("user_1", text, **kw))
    return await got.reply


async def _set(kernel, strand: str, title: str, description: str, archived: bool = False) -> None:
    await kernel.mind.append(
        [transcript_c.STRAND_SET.draft(person="user_1", strand=strand, title=Content.of(title, level=1),
                                       description=Content.of(description, level=1), archived=archived)],
        emitter="transcript", correlation="test", origin=Origin.EXTERNAL)


def test_a_work_thread_reads_only_its_messages_and_the_ordinary_thread_never_reads_them(tmp_path):
    async def script(kernel, seen):
        await _ask(kernel, "bonne nuit, je file au lit")
        await _ask(kernel, "liste moi les devis", mode="pro", strand="devis")
        await _ask(kernel, "corrige ma fonction python", mode="pro", strand="code")
        await _ask(kernel, "et le devis de Paul ?", mode="pro", strand="devis")
        await _ask(kernel, "tu dors encore ?")

    seen, prompts, said_to_him = _life(tmp_path, script)
    first_ordinary, devis_1, code, devis_2, ordinary = prompts
    assert [p.role for p in prompts] == ["reply", "pro", "pro", "pro", "reply"]
    # un fil de travail : ni le fil ordinaire, ni un autre fil
    assert "bonne nuit" not in _seen(devis_1) and "bonne nuit" not in _seen(code)
    assert "liste moi les devis" not in _seen(code)
    # le même fil, si : sa question d'avant
    assert "liste moi les devis" in _seen(devis_2) and "corrige ma fonction" not in _seen(devis_2)
    # le fil ordinaire relit le sien, jamais le travail
    assert "bonne nuit" in _seen(ordinary)
    assert "liste moi les devis" not in _seen(ordinary) and "corrige ma fonction" not in _seen(ordinary)
    # chaque réponse dans son fil : au journal, dans le fil relu, à l'écran
    strands = [(r["role"], r["strand"]) for r in seen["rows"]]
    assert strands == [("user", None), ("assistant", None), ("user", "devis"), ("assistant", "devis"),
                       ("user", "code"), ("assistant", "code"), ("user", "devis"), ("assistant", "devis"),
                       ("user", None), ("assistant", None)]
    assert [d.strand for d in said_to_him] == [None, "devis", "code", "devis", None]


def test_her_work_thread_opens_on_what_her_operator_wrote_of_it(tmp_path):
    async def script(kernel, seen):
        await _set(kernel, "devis", "Devis Intelligent Networks", "Le commercial d'IN ; montants HT.")
        await _ask(kernel, "liste moi les devis", mode="pro", strand="devis")
        await _ask(kernel, "corrige ma fonction", mode="pro", strand="code")

    seen, prompts, _said = _life(tmp_path, script)
    devis, code = prompts
    assert "Devis Intelligent Networks" in _seen(devis) and "montants HT" in _seen(devis)
    # un fil sans réglage dit seulement qu'il est à part ; jamais le réglage d'un autre
    assert "Intelligent Networks" not in _seen(code)
    assert strand_about(None) in _seen(code)
    listed = {s["id"]: s for s in seen["strands"]}
    assert listed["devis"]["title"] == "Devis Intelligent Networks" and listed["devis"]["count"] == 2
    assert listed["code"]["title"] == "" and listed["code"]["opener"] == "corrige ma fonction"


def test_a_question_in_another_work_thread_does_not_supersede_the_answer_being_written(tmp_path):
    """Deux fils, deux tours : sa réponse dans « devis » s'écrit (cinq secondes de modèle) quand une question arrive
    dans « code » — les deux reçoivent la leur. Le contre-exemple : une seconde question dans le même fil supplante
    la première, comme d'ordinaire."""
    async def script(kernel, seen):
        first = await kernel.perceive(said("user_1", "liste moi les devis", mode="pro", strand="devis"))
        await asyncio.sleep(1.0)
        second = await kernel.perceive(said("user_1", "corrige ma fonction", mode="pro", strand="code"))
        seen["outcomes"] = [(await first.reply).outcome, (await second.reply).outcome]
        third = await kernel.perceive(said("user_1", "et Paul ?", mode="pro", strand="devis"))
        await asyncio.sleep(1.0)
        fourth = await kernel.perceive(said("user_1", "et Jean ?", mode="pro", strand="devis"))
        seen["same"] = [(await third.reply).outcome, (await fourth.reply).outcome]

    seen, _prompts, _said = _life(tmp_path, script, latency=5.0)
    assert seen["outcomes"] == [Outcome.DONE, Outcome.DONE]
    assert seen["same"] == [Outcome.SUPERSEDED, Outcome.DONE]


def test_the_turn_is_the_address_the_room_and_the_work_thread():
    s = RuntimeState(pending=FrozenDict({1: Pending("u", 0, strand="a"), 2: Pending("u", 1, strand="b"),
                                         3: Pending("u", 2), 4: Pending("u", 3, strand="a")}))
    assert turn_of(s, "u", None, "a") == (1, 4) and turn_of(s, "u", None, "b") == (2,)
    assert turn_of(s, "u", None) == (3,)
    assert turn_upto(s, 4) == (1, 4) and turn_upto(s, 3) == (3,)


def test_a_perception_without_work_thread_reads_as_before():
    """Un journal d'avant : la perception n'a pas de fil de travail, son tour est celui d'avant."""
    p = rt.PerceptionReceived.model_validate_json(
        '{"handle": "u", "channel": "web", "text": {"text": "salut", "level": 0}}')
    assert p.strand is None
