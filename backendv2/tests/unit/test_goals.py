"""Les buts et le travail (M6), par leurs intentions.

- une inquiétude qui insiste devient une exploration ; elle y avance par un
  pas silencieux, la mène à bout avec une preuve, en est fière, son estime
  monte, et elle le raconte à qui ça concerne — à la mesure du lien ;
- « fini » sans rien avoir fait n'est pas fini : aucune fierté ; à bout de
  pas, elle bloque — frustration, estime en baisse, « Je bloque sur… » — et
  ne rouvre pas la même chose sous 24 h ;
- un rappel ordinaire attend son réveil ; un rappel urgent la réveille à
  l'heure, puis elle se rendort ; un rappel que le modèle ne peut pas dire est
  retenté trois fois, espacé, puis abandonné ;
- elle ne travaille pas en dormant ; un pas n'est jamais livré à personne ;
- rejouer la vie redonne exactement le même état.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

from mika.adapters.workshop import BwrapWorkshop
from mika.app.mindport import KernelPort
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.kernel import schedule
from mika.kernel.clock import DAY, HOUR, MINUTE, US, local
from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin
from mika.runtime.effects import with_content
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, disconnect, said

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")


def events(kernel):
    mind = kernel.mind
    return [with_content(mind, mind.decode(e)) for e in mind.store.read()]


async def until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


async def when(kernel, predicate, *, every=MINUTE, limit=6 * HOUR):
    """Attend (en temps virtuel) que le prédicat soit vrai sur le journal."""
    end = kernel.mind.clock.now() + limit
    while kernel.mind.clock.now() < end:
        if predicate(events(kernel)):
            return True
        await asyncio.sleep(every / US)
    return False


def closed_now(evs):
    return any(e.type.name == goals_c.GOAL_CLOSED.name for e in evs)


class Run:
    def __init__(self, result, llm, out, evs, frame):
        self.result, self.llm, self.out, self.events, self.frame = result, llm, out, evs, frame

    def of(self, event_type):
        return [e for e in self.events if e.type.name == event_type.name]


def run(tmp_path, scenario, *, start, mode="honest", workshop=False):
    clock = SimClock(start)
    llm = PersonaSimLLM(clock, seed=1, abstain_rate=0.0, latency=2.0)
    llm.step_mode = mode
    ports = {"workshop": BwrapWorkshop(tmp_path / "ateliers")} if workshop else {}
    kernel, clock, _, out = build(tmp_path, None, clock=clock, llm=llm, ports=ports)

    async def main():
        await boot(kernel)
        try:
            result = await scenario(kernel, llm)
            await kernel.lanes.join()
            return result, events(kernel), kernel.mind.frame()
        finally:
            await kernel.stop()

    result, evs, frame = run_virtual(clock, main)
    return Run(result, llm, out, evs, frame)


def _shares(llm):
    return [(c.meta["target"], c.messages[-1].content) for c in llm.calls
            if c.role == "initiative" and "MENÉ À BOUT" in c.messages[-1].content]


def _asleep(evs):
    spans, start = [], None
    for e in evs:
        if e.type.name == body_c.FELL_ASLEEP.name:
            start = e.data.at
        elif e.type.name == body_c.WOKE.name and start is not None:
            spans.append((start, e.data.at))
            start = None
        elif e.type.name == rt.PERCEPTION_RECEIVED.name and start is not None and e.data.addressed:
            spans.append((start, e.at))
            start = None
    if start is not None:
        spans.append((start, start + DAY))
    return spans


# ── Une inquiétude devient un but, mené à bout, raconté ───────────────────


def test_a_worry_becomes_a_goal_then_pride_then_she_tells_the_person_it_concerns(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await (await kernel.perceive(said("user_1", "j'ai peur, je stresse pour mon examen de demain"))).reply
        esteem0 = kernel.mind.frame().get(self_c.ESTEEM)
        assert await when(kernel, closed_now)
        esteem1 = kernel.mind.frame().get(self_c.ESTEEM)
        await asyncio.sleep(2 * HOUR / US)
        return esteem0, esteem1

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    esteem0, esteem1 = r.result
    opened, closed = r.of(goals_c.GOAL_OPENED), r.of(goals_c.GOAL_CLOSED)
    assert len(opened) == 1 and opened[0].data.source.startswith("thought:")
    assert opened[0].data.kind == goals_c.EXPLORATION and "examen" in opened[0].data.title.text
    assert [c.data.status for c in closed] == [goals_c.ACHIEVED]
    steps = r.of(goals_c.STEP_REPORTED)
    assert steps and steps[-1].data.proven and "memory_search" in steps[-1].data.tools
    assert esteem1 > esteem0 + 0.02  # elle a mené quelque chose à bout
    # un pas n'est jamais livré à personne, ni écrit dans le fil
    step_utterances = [e for e in r.of(rt.UTTERANCE) if e.data.kind == "STEP"]
    assert step_utterances and all(not u.data.visible for u in step_utterances)
    assert not [d for d in r.out.items if d.key in {u.id for u in step_utterances}]
    # elle le raconte à Adrien : il est concerné, et c'est son propriétaire — tout
    shares = _shares(r.llm)
    assert shares and shares[0][0] == "user_1" and "Ce que tu en as tiré" in shares[0][1]
    # la pensée d'où c'était venu s'est apaisée : elle a fait la chose
    source = int(opened[0].data.source.split(":")[1])
    assert source not in {t.id for t in r.frame.get(attention_c.THOUGHTS)}


def test_a_friend_hears_a_mention_and_a_stranger_nothing(tmp_path):
    async def scenario(kernel, llm):
        await befriend(kernel, "user_2", "friend")
        await connect(kernel, "user_2", "Bea")
        await (await kernel.perceive(said("user_2", "je suis triste, ma grand-mère est à l'hôpital"))).reply
        await asyncio.sleep(3 * HOUR / US)
        await connect(kernel, "user_3", "Zoé")
        await (await kernel.perceive(said("user_3", "j'ai peur de rater mon permis demain"))).reply
        await asyncio.sleep(4 * HOUR / US)

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 10, 0))
    assert {o.data.owner for o in r.of(goals_c.GOAL_OPENED)} >= {"user_2", "user_3"}
    shares = _shares(r.llm)
    to_bea = [text.split("MENÉ À BOUT ---\n", 1)[1].split("\n---", 1)[0].strip() for who, text in shares if who == "user_2"]
    assert to_bea == ["quelque chose qui te tenait à cœur"]  # une amie : une mention, pas le détail
    assert not [who for who, _ in shares if who == "user_3"]  # une inconnue : rien


# ── « Fini » sans preuve ──────────────────────────────────────────────────


def test_done_without_proof_is_no_pride_then_she_blocks_and_does_not_reopen(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien")
        await (await kernel.perceive(said("user_1", "j'angoisse pour mon entretien demain"))).reply
        esteem0 = kernel.mind.frame().get(self_c.ESTEEM)
        await asyncio.sleep(5 * HOUR / US)
        mid = kernel.mind.frame()
        await asyncio.sleep(15 * HOUR / US)
        return esteem0, mid.get(self_c.ESTEEM), mid.get(attention_c.THOUGHTS)

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 10, 0), mode="liar")
    esteem0, esteem1, thoughts = r.result
    reports = r.of(goals_c.STEP_REPORTED)
    closed = [c for c in r.of(goals_c.GOAL_CLOSED) if c.data.source.startswith("thought:")]
    assert reports and all(x.data.verdict == "done" and not x.data.proven for x in reports)
    assert [c.data.status for c in closed] == [goals_c.STUCK]  # jamais « abouti » : aucune fierté
    assert not [c for c in r.of(goals_c.GOAL_CLOSED) if c.data.status == goals_c.ACHIEVED]
    assert esteem1 < esteem0  # bloquer lui coûte
    assert any(t.origin == attention_c.BLOCKED and t.emotion == "frustrated" for t in thoughts)
    sources = [o.data.source for o in r.of(goals_c.GOAL_OPENED)]
    assert sources.count(closed[0].data.source) == 1  # pas rouvert sous 24 h
    assert not [s for s in sources if s.startswith("thought:") and s != closed[0].data.source
                and "bloque" in s]  # sa frustration ne devient pas un nouveau chantier


# ── Les rappels ───────────────────────────────────────────────────────────


def test_an_ordinary_reminder_waits_for_her_waking_and_an_urgent_one_wakes_her(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien")
        await (await kernel.perceive(said("user_1", "rappelle-moi à 3h de sortir le linge"))).reply
        await (await kernel.perceive(said("user_1", "rappelle-moi à 3h30 de prendre mon médicament, c'est urgent"))).reply
        await disconnect(kernel, "user_1")
        await until(kernel, at_paris(2026, 9, 29, 11, 0))

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 21, 0))
    said_ = [e for e in r.of(rt.UTTERANCE) if e.data.kind == "INITIATIVE" and "rappel" in (e.data.text.text or "")]
    by = {("linge" if "linge" in (e.data.text.text or "") else "médicament"): e.at for e in said_}
    assert set(by) == {"linge", "médicament"}
    urgent = local(by["médicament"], PARIS)
    assert (urgent.day, urgent.hour) == (29, 3) and 30 <= urgent.minute <= 40  # à l'heure, en pleine nuit
    assert any(e.data.at > by["médicament"] for e in r.of(body_c.FELL_ASLEEP))  # puis elle se rendort
    natural = [e.data.at for e in r.of(body_c.WOKE) if local(e.data.at, PARIS).hour >= 5]
    assert natural and by["linge"] > natural[0]  # l'ordinaire attend son réveil
    reminders = [c.data.status for c in r.of(goals_c.GOAL_CLOSED) if c.data.kind == goals_c.REMINDER]
    assert reminders == [goals_c.ACHIEVED, goals_c.ACHIEVED]


def test_a_reminder_the_model_cannot_say_is_tried_three_times_spaced_then_dropped(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien")
        await (await kernel.perceive(said("user_1", "rappelle-moi dans 20 minutes de rappeler Paul"))).reply
        llm.fail["initiative"] = 10
        await asyncio.sleep(2 * HOUR / US)

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 15, 0))
    started = [e.at for e in r.of(rt.EPISODE_STARTED) if e.data.kind == "INITIATIVE"
               and goals_c.REMIND in e.data.reason.split(",")]
    assert len(started) == 3
    gaps = [(b - a) / MINUTE for a, b in zip(started, started[1:], strict=False)]
    assert gaps[0] >= 5 and gaps[1] >= 10
    assert [c.data.status for c in r.of(goals_c.GOAL_CLOSED)] == [goals_c.FAILED]


# ── Les projets ───────────────────────────────────────────────────────────

# ── Le sommeil, le rejeu, l'agenda ────────────────────────────────────────


def _explore(title, desire=1.0):
    return goals_c.GOAL_OPENED.draft(
        kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of(title, level=0), bundles=("goals",),
        max_steps=8, source="genese", sensitivity=0, desire=desire)


def test_she_does_not_work_while_asleep_and_resumes_in_the_morning(tmp_path):
    async def scenario(kernel, llm):
        await kernel.mind.append([_explore("Explorer : les jeux rétro")], emitter="goals", correlation="genese",
                                 origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 29, 12, 0))

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 21, 30), mode="liar")
    spans = _asleep(r.events)
    steps = [e.at for e in r.of(rt.EPISODE_STARTED) if e.data.kind == "STEP"]
    assert spans and steps
    assert not [local(t, PARIS).strftime("%H:%M") for t in steps if any(a <= t < b for a, b in spans)]
    assert any(t < spans[0][0] for t in steps) and any(t >= spans[0][1] for t in steps)  # le soir, puis le matin


def test_a_nominative_wait_lifts_as_soon_as_the_person_writes(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await (await kernel.perceive(said("user_1", "j'ai peur, je stresse pour mon oral de demain"))).reply
        await asyncio.sleep(2 * HOUR / US)
        waiting = [g.status for g in kernel.mind.frame().get(goals_c.LIVE)]
        await (await kernel.perceive(said("user_1", "au fait, c'est à 10h demain"))).reply
        await asyncio.sleep(HOUR / US)
        return waiting

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0), mode="waits")
    assert r.result == [goals_c.WAITING]  # elle attend sa réponse (un jour au plus)…
    waits = [x for x in r.of(goals_c.STEP_REPORTED) if x.data.verdict == "wait"]
    assert waits and waits[0].data.wait_for == "user_1"
    lifted = [e for e in r.events if e.type.name == "goals.awaited"]
    answer = [e.at for e in r.of(rt.PERCEPTION_RECEIVED) if "10h" in (e.data.text.text or "")]
    assert lifted and lifted[0].at >= answer[0] and lifted[0].at - answer[0] < 10 * MINUTE  # …et reprend aussitôt
    assert [c.data.status for c in r.of(goals_c.GOAL_CLOSED)] == [goals_c.ACHIEVED]


def test_after_a_failure_a_new_worry_waits_before_becoming_a_goal(tmp_path):
    async def scenario(kernel, llm):
        opened = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of("Explorer : les échecs", level=0),
            bundles=("goals",), max_steps=2, source="genese", sensitivity=0, desire=1.0)],
            emitter="goals", correlation="genese", origin=Origin.GENESIS)
        assert await when(kernel, closed_now)
        await connect(kernel, "user_1", "Adrien")
        await (await kernel.perceive(said("user_1", "j'ai peur, je stresse pour mon oral"))).reply
        await asyncio.sleep(10 * HOUR / US)
        return opened.seqs[-1]

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0), mode="liar")
    blocked = [c.at for c in r.of(goals_c.GOAL_CLOSED) if c.data.status == goals_c.STUCK]
    later = [o.at for o in r.of(goals_c.GOAL_OPENED) if o.data.authority == goals_c.SELF and o.seq != r.result]
    assert blocked and later and later[0] - blocked[0] >= 4 * HOUR  # découragée, elle ne se relance pas aussitôt


def test_replay_gives_the_same_state(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien")
        await (await kernel.perceive(said("user_1", "j'ai peur, je stresse pour demain"))).reply
        await asyncio.sleep(4 * HOUR / US)
        owners = ["goals", "attention", "self", "affect", "needs"]
        live = digest({o: kernel.mind.root.slices[o] for o in owners})
        await kernel.mind.rebuild(owners)
        return live, digest({o: kernel.mind.root.slices[o] for o in owners})

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    live, rebuilt = r.result
    assert r.of(goals_c.GOAL_CLOSED) and live == rebuilt


def test_two_decisions_on_one_action_only_one_counts(tmp_path):
    async def scenario(kernel, llm):
        port = KernelPort(kernel)
        opened = await kernel.mind.append([_explore("Explorer : un projet")], emitter="goals", correlation="g",
                                          origin=Origin.GENESIS)
        proposed = await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="projects.networked", owner="projects", args_json="{}", summary=Content.of("réseau"),
            approval=True, context=f"project:{opened.seqs[-1]}")], emitter="runtime", correlation="g",
            origin=Origin.TOOL)
        n = proposed.seqs[-1]
        both = await asyncio.gather(port.resolve_effect(n, True, by="user_1"),
                                    port.resolve_effect(n, False, by="user_9", note="non"))
        return both

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    assert sorted(r.result) == ["approved", "unknown"]
    assert len(r.of(rt.EFFECT_RESOLVED)) == 1


def test_schedule_rules():
    rule = schedule.parse("cron:0 9 * * MON-FRI")
    nxt = schedule.next_after(rule, at_paris(2026, 9, 28, 8, 0), PARIS)
    assert (local(nxt, PARIS).hour, local(nxt, PARIS).weekday()) == (9, 0)
    assert local(schedule.next_after(rule, at_paris(2026, 10, 2, 10, 0), PARIS), PARIS).weekday() == 0
    assert schedule.next_after(schedule.parse("interval:1m"), 0, PARIS) == 5 * MINUTE  # au moins cinq minutes
    assert schedule.parse("manual").kind == "manual"
    for bad in ("tous les jours", "cron:0 25 * * *", "cron:* * *"):
        with pytest.raises(ValueError):
            schedule.parse(bad)


def test_a_goal_opened_by_hand_needs_its_owner_frame(tmp_path):
    """Un cadre confié (autorité de la personne) ne s'abandonne pas d'elle-même."""
    async def scenario(kernel, llm):
        await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.USER, title=Content.of("Ranger les notes", level=2),
            owner="user_1", about=("user_1",), bundles=("goals",), max_steps=3, source="operator", sensitivity=2)],
            emitter="goals", correlation="genese", origin=Origin.GENESIS)
        return kernel.mind.frame().get(goals_c.LIVE)

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 15, 0))
    assert [g.authority for g in r.result] == [goals_c.USER]
