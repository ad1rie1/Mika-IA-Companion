"""La nuit (M5), par ses intentions.

- un journal par journée vécue ; une nuit manquée (serveur arrêté) se
  rattrape au matin ;
- le fil d'hier nomme les autres seulement pour qui peut entendre ce qui les
  concerne ;
- le rêve revient le matin, une fois, et seulement à qui peut l'entendre ;
- la nuit fond les souvenirs du jour presque identiques ;
- rejouer la nuit redonne exactement le même état.
"""

from __future__ import annotations

import asyncio

from mika.contracts import memory as memory_c
from mika.contracts import self_ as self_c
from mika.kernel.clock import DAY, MINUTE, US
from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said


class Script:
    def __init__(self) -> None:
        self.journal = "J'ai parlé avec Alice de son chagrin, et avec Bob de cuisine."
        self.dream = "Je vole au-dessus d'un marché où Alice vend des nuages."

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role == "journal":
            return LLMResponse(self.journal)
        if req.role == "dream":
            return LLMResponse(self.dream)
        if req.role in ("murmur", "narrative"):
            return LLMResponse("hmm")
        return LLMResponse("d'accord [EMOTION:happy:0.5]")


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


async def until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


def souvenir(text, about=(), sensitivity=1, importance=0.6):
    return memory_c.REMEMBERED.draft(text=Content.of(text, level=sensitivity), about=about, sensitivity=sensitivity,
                                     importance=importance, emotion="happy")


async def genesis(kernel, *drafts):
    await kernel.mind.append(list(drafts), emitter="memory", correlation="genese", origin=Origin.GENESIS)


def build_run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 17, 0)):
    script = Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main), llm


def test_one_journal_per_lived_day(tmp_path):
    async def scenario(kernel):
        for d in range(3):
            await until(kernel, at_paris(2026, 9, 28, 18, 0) + d * DAY)
            p = await kernel.perceive(said("user_1", "coucou, bonne soirée"))
            await p.reply
        await until(kernel, at_paris(2026, 10, 1, 10, 0))
        return [e.data.day for e in events(kernel, self_c.JOURNALED.name)]

    days, _ = build_run(tmp_path, scenario)
    assert days == ["2026-09-28", "2026-09-29", "2026-09-30"]


def test_a_night_missed_with_the_server_off_is_written_in_the_morning(tmp_path):
    script = Script()
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 17, 0))

    async def first():
        await boot(kernel)
        p = await kernel.perceive(said("user_1", "coucou"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 18, 0))
        p = await kernel.perceive(said("user_1", "re-coucou"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 21, 0))
        await kernel.stop()  # le serveur s'arrête avant la nuit…

    run_virtual(clock, first)
    clock.advance_to(at_paris(2026, 9, 30, 9, 0))  # … et redémarre le lendemain matin
    kernel2, _, _, _ = build(tmp_path, script, clock=clock)

    async def second():
        await boot(kernel2)
        await asyncio.sleep(10 * MINUTE / US)
        days = [e.data.day for e in events(kernel2, self_c.JOURNALED.name)]
        await kernel2.stop()
        return days

    assert run_virtual(clock, second) == ["2026-09-28", "2026-09-29"]


def test_yesterdays_thread_names_others_only_for_those_who_may_hear(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_1", "Alice")
        p = await kernel.perceive(said("user_1", "je suis triste ce soir"))
        await p.reply
        await connect(kernel, "user_2", "Bob")
        p = await kernel.perceive(said("user_2", "tu cuisines quoi ?"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        for handle in ("user_1", "user_3"):
            p = await kernel.perceive(said(handle, "salut, bien dormi ?"))
            await p.reply

    _, llm = build_run(tmp_path, scenario)
    last = {c.meta.get("target"): c.messages[-1].content for c in llm.calls if c.role == "reply"}
    assert "Alice de son chagrin" in last["user_1"]  # elle-même : son nom
    stranger = last["user_3"]
    assert "TON FIL D'HIER" in stranger and "Alice" not in stranger and "quelqu'un de son chagrin" in stranger


def test_a_vivid_dream_comes_back_once_in_the_morning(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, souvenir("J'ai ri avec quelqu'un d'une histoire de nuages"),
                      souvenir("J'ai appris qu'il existe des marchés flottants"))
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        dreams = events(kernel, self_c.DREAMT.name)
        shown = []
        for text in ["salut !", "tu fais quoi ?"]:
            p = await kernel.perceive(said("user_1", text))
            await p.reply
        await until(kernel, at_paris(2026, 9, 29, 15, 0))
        p = await kernel.perceive(said("user_1", "et cet après-midi ?"))
        await p.reply
        return dreams, shown

    (dreams, _), llm = build_run(tmp_path, scenario)
    replies = [c.messages[-1].content for c in llm.calls if c.role == "reply"]
    vivid = [d for d in dreams if d.data.vividness >= 0.6]
    assert dreams and len(dreams) <= 2
    if vivid:
        assert "RÊVÉ CETTE NUIT" in replies[0]  # le matin, il revient
        assert "RÊVÉ CETTE NUIT" not in replies[1]  # une fois : il s'est effacé en revenant
    assert "RÊVÉ CETTE NUIT" not in replies[-1]  # l'après-midi, c'est passé


def test_a_dream_made_of_a_confidence_is_not_told_to_someone_else(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, souvenir("CANARI-REVE Alice m'a confié sa rechute", about=("user_9",), sensitivity=3,
                                       importance=0.9))
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        p = await kernel.perceive(said("user_2", "bien dormi ?"))
        await p.reply
        return events(kernel, self_c.DREAMT.name)

    dreams, llm = build_run(tmp_path, scenario)
    assert dreams and all(d.data.sensitivity == 3 for d in dreams)
    to_bob = [c.messages[-1].content for c in llm.calls if c.role == "reply"]
    assert to_bob and "RÊVÉ" not in to_bob[-1]


def test_the_night_merges_near_duplicate_memories_of_the_day(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, souvenir("Alice m'a appris une recette de soupe au potiron", importance=0.4))
        await until(kernel, at_paris(2026, 9, 28, 19, 0))
        await genesis(kernel, souvenir("Alice m'a appris une recette de soupe au potiron", importance=0.8),
                      souvenir("Bob m'a parlé de son voyage au Japon"))
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        rows = kernel.mind.store.query_mind(f"SELECT text, status, importance FROM {memory_c.ITEMS_TABLE}")
        return rows, events(kernel, memory_c.NIGHT_SORTED.name)

    (rows, sorted_), _ = build_run(tmp_path, scenario)
    soup = [(status, importance) for text, status, importance in rows if "potiron" in text]
    assert sorted(soup) == [("active", 0.8), ("merged", 0.8)]
    assert len(sorted_) == 1 and len(sorted_[0].data.merges) == 1


def test_the_night_replays_to_the_same_state(tmp_path):
    async def scenario(kernel):
        await genesis(kernel, souvenir("J'ai ri d'une histoire de chats"))
        p = await kernel.perceive(said("user_1", "je suis triste ce soir, vraiment"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        owners = ["self", "attention", "affect", "memory"]
        live = digest({o: kernel.mind.root.slices[o] for o in owners})
        await kernel.mind.rebuild(owners)
        return live, digest({o: kernel.mind.root.slices[o] for o in owners})

    (live, rebuilt), _ = build_run(tmp_path, scenario)
    assert live == rebuilt



