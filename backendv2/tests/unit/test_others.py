"""Ce qu'elle devine des autres, par ses intentions.

- le ton d'un message se lit dans sa forme (« pas mal » n'est pas lourd) ;
- ce qu'elle attend de quelqu'un vient de son histoire : un message lourd d'une
  amie d'humeur légère la surprend et l'inquiète ; le même, de quelqu'un qui
  râle toujours, non ; d'une inconnue, non plus (elle ne la connaît pas) ;
- ce qui tranche avec le ton habituel se dit dans le prompt, jamais un nombre ;
- une amie qui n'avait pas l'air bien et qui est repartie : quelques heures
  plus tard, elle prend de ses nouvelles — pas si le dernier message allait ;
- elle apprend qu'une amie met deux heures à répondre, et cesse de se croire
  ignorée au bout d'une ;
- elle apprend à quelles heures on lui répond ;
- une promesse datée non tenue ne s'oublie pas en silence ; tenue, elle s'apaise.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.attention.faculty import AttentionParams, reply_window
from mika.faculties.others.faculty import Model, OthersParams, OthersState, current, learn, receptivity
from mika.faculties.others.tone import measure
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, disconnect, said

P = OthersParams()

LIGHT = ["haha trop bien", "super journée, trop cool", "j'ai hâte de te raconter haha", "trop bien ce film !",
         "génial, merci !", "haha j'adore", "c'était trop cool", "super, à demain !", "trop bien haha",
         "incroyable, j'adore"]
HEAVY = ["j'en ai marre, je suis épuisée", "encore une journée nulle, j'en ai marre", "je suis épuisée, ras le bol",
         "tout est nul, marre", "j'en peux plus, épuisée et triste"]


class Script:
    def __init__(self, tag="[EMOTION:happy:0.5]"):
        self.tag = tag

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens, et si je lui écrivais")
        if req.role == "narrative":
            return LLMResponse("Je suis quelqu'un qui aime les petites choses du quotidien.")
        return LLMResponse(f"d'accord {self.tag}")


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 14, 0), with_llm=False):
    script = Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, script, out)
        finally:
            await kernel.stop()

    got = run_virtual(clock, main)
    return (got, llm) if with_llm else got


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


async def chat(kernel, handle, texts, *, channel="web", gap=60):
    for text in texts:
        p = await kernel.perceive(said(handle, text, channel=channel))
        await p.reply
        await asyncio.sleep(gap)


def person_of(kernel, handle):
    return kernel.mind.frame().get(identity_c.PERSON(handle))


# ── Le ton, pur ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,sign", [
    ("j'en ai marre, je suis épuisée", -1),
    ("trop bien, j'ai hâte !", +1),
    ("je suis pas contente du tout", -1),  # l'entrain nié
    ("c'est pas mal du tout", +1),  # « pas mal » n'est pas lourd
    ("ça m'énerve, c'est insupportable", -1),
    ("On se voit demain à la bibliothèque pour réviser ?", 0),
])
def test_the_tone_of_a_message_is_read_in_its_form(text, sign):
    v = measure(text).valence
    assert (v > 0.05) - (v < -0.05) == sign, (text, v)


def test_anger_is_agitated_sadness_is_not():
    assert measure("ça m'énerve, c'est insupportable !!").arousal > measure("je suis triste").arousal


def test_three_sad_first_messages_do_not_make_a_sad_person():
    """Avant de connaître quelqu'un, elle lui prête de la neutralité : ses
    premiers messages pèsent, sans faire un caractère."""
    m = Model()
    for i in range(3):
        m = learn(m, -1.0, 0.3, i, (), i * MINUTE, P)
    assert -0.7 < m.usual_valence < -0.4
    for i in range(3, 40):
        m = learn(m, -1.0, 0.3, i, (), i * MINUTE, P)
    assert m.usual_valence < -0.9  # contrôle : une longue histoire, si


def test_the_mood_of_the_moment_fades_back_to_the_usual_tone():
    m = Model()
    for i in range(20):
        m = learn(m, 0.8, 0.3, i, (), i * MINUTE, P)
    m = learn(m, -1.0, 0.3, 21, (), HOUR, P)
    right_after = current(m, HOUR, P)[0]
    a_day_later = current(m, HOUR + DAY, P)[0]
    assert right_after < 0.0 < a_day_later and abs(a_day_later - m.usual_valence) < 0.01


# ── Surprise et inquiétude, de bout en bout ───────────────────────────────


def test_a_heavy_message_from_a_light_friend_surprises_and_worries_her_not_from_a_complainer(tmp_path):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await befriend(kernel, "user_2", social_c.FRIEND)
        await connect(kernel, "user_1", "Alice")
        await connect(kernel, "user_2", "Bea")
        await connect(kernel, "user_3", "Chloé")
        await chat(kernel, "user_1", LIGHT)
        await chat(kernel, "user_2", HEAVY * 2)
        await chat(kernel, "user_3", ["salut"])
        for handle in ("user_1", "user_2", "user_3"):
            await chat(kernel, handle, ["j'en ai marre, je suis épuisée"])

    _, llm = run(tmp_path, scenario, with_llm=True)
    # chaque réponse a vu la lecture de son message (journalisée avant qu'elle réponde)
    replies = [r for r in llm.calls if r.role == "reply"]
    to_alice, to_bea, to_chloe = replies[-3], replies[-2], replies[-1]
    assert to_alice.meta["target"] == "user_1" and to_bea.meta["target"] == "user_2"
    alice_prompt = to_alice.messages[-1].content
    assert "Ça ne ressemble pas à « Alice »" in alice_prompt, alice_prompt[-1500:]
    assert "Dans son message : " in alice_prompt
    assert "Ça ne ressemble pas" not in to_bea.messages[-1].content  # elle râle toujours : rien d'étonnant
    assert "Ça ne ressemble pas" not in to_chloe.messages[-1].content  # une inconnue : elle ne la connaît pas


def test_surprise_and_worry_are_recorded_judgements(tmp_path):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await befriend(kernel, "user_2", social_c.FRIEND)
        await connect(kernel, "user_1", "Alice")
        await connect(kernel, "user_2", "Bea")
        await connect(kernel, "user_3", "Chloé")
        await chat(kernel, "user_1", LIGHT)
        await chat(kernel, "user_2", HEAVY * 2)
        await chat(kernel, "user_3", LIGHT[:9])  # une inconnue bavarde : des messages, pas encore un lien
        for handle in ("user_1", "user_2", "user_3"):
            await chat(kernel, handle, ["j'en ai marre, je suis épuisée"])
        await asyncio.sleep(30)
        reads = {e.data.handle: e.data for e in events(kernel, others_c.READ.name)}
        thoughts = kernel.mind.frame().get(attention_c.THOUGHTS)
        return reads, thoughts, {h: person_of(kernel, h) for h in ("user_1", "user_2", "user_3")}

    reads, thoughts, persons = run(tmp_path, scenario)
    alice, bea, chloe = reads["user_1"], reads["user_2"], reads["user_3"]
    assert alice.surprise >= P.surprise_from and alice.concern
    assert bea.surprise < P.surprise_from and not bea.concern
    assert not chloe.concern and chloe.surprise == 0.0  # on ne s'étonne pas d'une inconnue
    concerns = [t for t in thoughts if t.origin == attention_c.CONCERN]
    assert [t.about for t in concerns] == [(persons["user_1"],)]


def test_what_she_guesses_replays_to_the_same_model(tmp_path):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Alice")
        await chat(kernel, "user_1", LIGHT + ["j'en ai marre, je suis épuisée"])
        live = kernel.mind.root.slices["others"]
        await kernel.mind.rebuild(["others"])
        return live, kernel.mind.root.slices["others"]

    live, rebuilt = run(tmp_path, scenario)
    assert live.people and digest(live) == digest(rebuilt)


# ── Prendre de ses nouvelles ──────────────────────────────────────────────


def _check_ins(kernel, handle):
    """Ses messages pour prendre de ses nouvelles : la prise de nouvelles (``check_in``), ou la pensée inquiète
    qui la pousse à lui en reparler (``thought``) — deux chemins vers le même geste, et c'est le hasard de
    l'arbitre (dérivé du journal) qui décide lequel passe le premier."""
    return [e for e in events(kernel, rt.EPISODE_STARTED.name)
            if e.data.kind == "INITIATIVE" and e.data.target == handle
            and {others_c.CHECK_IN, attention_c.THOUGHT} & set(e.data.reason.split(","))]


@pytest.mark.parametrize("last,expected", [("j'en ai marre, je suis épuisée", True), ("bon, à plus !", False)])
def test_she_checks_on_a_friend_who_did_not_seem_well(tmp_path, last, expected):
    """Une proche d'humeur légère écrit un message lourd, puis plus rien : dans
    l'après-midi, elle prend de ses nouvelles — une fois. Contrôle : si le
    dernier message allait, rien."""
    async def scenario(kernel, script, out):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        await chat(kernel, "tg_1", LIGHT + [last], channel="telegram")
        sent_at = events(kernel, others_c.READ.name)[-1].at  # quand elle a lu le dernier message
        await asyncio.sleep(10 * HOUR / US)
        return [(e.at - sent_at, e.data.reason) for e in _check_ins(kernel, "tg_1")]

    delays = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 11, 0))
    if expected:
        assert len(delays) == 1 and delays[0][0] <= 10 * HOUR, delays
        if others_c.CHECK_IN in delays[0][1]:  # la prise de nouvelles attend quelques heures
            assert delays[0][0] >= P.checkin_after_us, delays
    else:
        assert delays == []


# ── Apprendre de l'expérience ─────────────────────────────────────────────


def test_she_learns_that_a_friend_takes_two_hours_and_stops_feeling_ignored(tmp_path):
    """Sur Telegram, une amie qui répond toujours deux heures plus tard : les
    premières fois, l'attente (une heure) est déçue puis rattrapée ; une fois
    le délai appris, elle ne l'est plus."""
    async def scenario(kernel, script, out):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        for day in range(3):  # une amie qui écrit chaque jour vers midi
            if day:
                await asyncio.sleep(DAY / US)
            await chat(kernel, "tg_1", ["coucou, ça va ?"], channel="telegram")
        rounds = []
        for _ in range(5):
            waited = 0
            seen = {e.seq for e in _initiatives(kernel)}
            while waited < 4 * DAY and not {e.seq for e in _initiatives(kernel)} - seen:
                await asyncio.sleep(10 * MINUTE / US)
                waited += 10 * MINUTE
            fresh = [e for e in _initiatives(kernel) if e.seq not in seen]
            if not fresh:
                break
            await asyncio.sleep(2 * HOUR / US)  # elle répond, deux heures plus tard
            await chat(kernel, "tg_1", ["désolée, je vois ton message que maintenant"], channel="telegram")
            await asyncio.sleep(5)
            missed = [e for e in events(kernel, attention_c.EXPECTATION_MISSED.name) if e.data.since == fresh[0].at]
            rounds.append(bool(missed))
        return rounds, kernel.mind.frame().get(others_c.REPLY_DELAY((person_of(kernel, "tg_1"), "telegram")))

    rounds, delay = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 12, 0))
    assert len(rounds) >= 5, rounds
    assert rounds[0], "avant d'apprendre, une heure sans réponse : ignorée"
    assert not any(rounds[AttentionParams().reply_learned_after:]), rounds
    assert delay.samples >= 3 and abs(delay.median_us - 2 * HOUR) < 15 * MINUTE


def _initiatives(kernel):
    return [e for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE" and e.data.target == "tg_1"]


def test_a_learned_reply_window_only_ever_lengthens():
    p = AttentionParams()

    def cx(samples, median):
        return SimpleNamespace(facts=SimpleNamespace(get=lambda ref: others_c.DelayReading(samples, median)))

    assert reply_window(cx(0, 0), "x", "telegram", p) == p.reply_window_message_us
    assert reply_window(cx(5, 2 * HOUR), "x", "telegram", p) == 4 * HOUR
    assert reply_window(cx(2, 2 * HOUR), "x", "telegram", p) == p.reply_window_message_us  # pas encore appris
    assert reply_window(cx(9, MINUTE), "x", "web", p) == p.reply_window_us  # répondre vite ne rend pas impatiente
    assert reply_window(cx(9, 3 * DAY), "x", "telegram", p) == p.reply_window_max_us


def test_she_learns_at_what_time_of_day_she_gets_answers():
    person = "user_1"
    s = OthersState(answers=FrozenDict({f"{person}|evening": (4.0, 0.0), f"{person}|morning": (0.0, 4.0),
                                        f"{person}|afternoon": (1.0, 0.0)}))
    evening, morning = receptivity(s, person, "evening", P)[3], receptivity(s, person, "morning", P)[3]
    assert 0 < evening <= P.receptivity_max_shift and -P.receptivity_max_shift <= morning < 0
    assert receptivity(s, person, "afternoon", P)[3] == 0.0  # une seule observation : rien ne change
    assert receptivity(s, person, "night", P)[3] == 0.0


def test_misses_and_late_replies_are_filed_by_the_hour_she_wrote(tmp_path):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Alice")
        await disconnect(kernel, "user_1")
        person = person_of(kernel, "user_1")
        morning, evening = at_paris(2026, 9, 28, 9, 0), at_paris(2026, 9, 28, 19, 0)
        drafts = [attention_c.EXPECTATION_MISSED.draft(kind=attention_c.REPLY, person=person, since=morning),
                  attention_c.EXPECTATION_MISSED.draft(kind=attention_c.REPLY, person=person, since=evening),
                  attention_c.EXPECTATION_MET.draft(kind=attention_c.REPLY, person=person, since=evening),
                  attention_c.EXPECTATION_MET.draft(kind=attention_c.REPLY, person=person, since=evening + DAY)]
        for i, d in enumerate(drafts):
            await kernel.mind.append([d], emitter="attention", correlation=f"genese{i}", origin=Origin.GENESIS)
        return kernel.mind.root.slices["others"].answers, person

    answers, person = run(tmp_path, scenario, start=at_paris(2026, 9, 30, 12, 0))
    assert answers[f"{person}|morning"] == (0.0, 1.0)
    late = P.receptivity_late_weight
    assert answers[f"{person}|evening"] == (1.0 + late, 1.0 - late)  # une tardive, puis une à temps


# ── Sa parole ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kept_in_time", [False, True])
def test_a_broken_promise_is_not_forgotten_in_silence(tmp_path, kept_in_time):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Alice")
        person = person_of(kernel, "user_1")
        now = kernel.mind.clock.now()
        commit = await kernel.mind.append([memory_c.PROMISE_NOTICED.draft(
            text=Content.of("t'envoyer le lien du concert", level=1), to=person, due=now + HOUR)],
            emitter="memory", correlation="promesse", origin=Origin.GENESIS)
        promise = commit.seqs[-1]
        await asyncio.sleep(20 * MINUTE / US)
        await chat(kernel, "user_1", ["au fait, tu as vu le match ?"])  # lui écrire ne tient pas la promesse
        if kept_in_time:
            await asyncio.sleep(30 * MINUTE / US)
            await kernel.mind.append([memory_c.PROMISE_RESOLVED.draft(promise=promise, status=memory_c.HONORED)],
                                     emitter="memory", correlation="tenue", origin=Origin.GENESIS)
        esteem_before = kernel.mind.frame().get(self_c.ESTEEM)
        await asyncio.sleep(4 * HOUR / US)
        missed = [e for e in events(kernel, attention_c.EXPECTATION_MISSED.name)
                  if e.data.kind == attention_c.PROMISE]
        thoughts = [t for t in kernel.mind.frame().get(attention_c.THOUGHTS) if t.origin == attention_c.PROMISE]
        texts = kernel.mind.store.content([t.text_ref for t in thoughts])
        esteem = kernel.mind.frame().get(self_c.ESTEEM)
        p = await kernel.perceive(said("user_1", "coucou !"))
        await p.reply
        await kernel.mind.append([memory_c.PROMISE_RESOLVED.draft(promise=promise, status=memory_c.HONORED)],
                                 emitter="memory", correlation="enfin", origin=Origin.GENESIS)
        await asyncio.sleep(60)
        after = [t for t in kernel.mind.frame().get(attention_c.THOUGHTS) if t.origin == attention_c.PROMISE]
        return missed, list(texts.values()), esteem_before, esteem, after

    (missed, texts, before, esteem, after), llm = run(tmp_path, scenario, with_llm=True)
    prompt = [r for r in llm.calls if r.role == "reply"][-1].messages[-1].content
    if kept_in_time:
        assert missed == [] and texts == [] and "J'avais promis" not in prompt
        return
    assert len(missed) == 1
    assert texts and "t'envoyer le lien du concert" in texts[0] and texts[0].startswith("J'avais promis à")
    assert esteem < before  # sa parole pas tenue lui coûte un peu
    assert "J'avais promis à" in prompt  # quand Alice revient, elle le sait
    assert after == []  # tenue, même en retard : la pensée s'éteint

