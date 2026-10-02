"""La vie intérieure (M4), par ses intentions.

- elle dort la nuit (vers 23 h – 7 h), plus tard après une longue soirée ; le
  message d'une amie la réveille, et elle se rendort ensuite ; jamais
  d'initiative en dormant ;
- ses besoins montent et retombent ; deux heures sans rien, elle s'ennuie ;
- ce que les événements font ressentir est déclaré par leur propriétaire et
  reçu par l'affect — et le rejeu retombe exactement sur le même état ;
- une pensée née d'un échange s'allège quand elle en parle et ne se montre
  qu'à qui peut l'entendre ; une croyance révisée laisse une pensée ;
- ignorée, son estime baisse ; une réponse, même tardive, la répare ;
- elle se murmure ce qu'elle s'apprête à faire, pas plus d'une fois par heure ;
- son récit d'elle-même est écrit par sa voix, à partir de souvenirs anodins.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as needs_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.body.sleep import Sleep, SleepParams, phase, transitions
from mika.kernel.clock import DAY, HOUR, MINUTE, US, instant, local
from mika.kernel.codec import digest
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said

TZ = ZoneInfo("Europe/Paris")
P = SleepParams()


def _hm(t: int) -> float:
    d = local(t, TZ)
    return d.hour + d.minute / 60


# ── Le sommeil, pur ───────────────────────────────────────────────────────


def test_left_alone_she_sleeps_around_eleven_and_wakes_around_seven():
    t0 = instant(datetime(2026, 9, 28, 9, 0, tzinfo=TZ))
    steps = transitions(Sleep(), t0, t0 + 5 * DAY, P, TZ)
    onsets = [_hm(at) for kind, at, _ in steps if kind == "fell_asleep"][2:]
    wakes = [_hm(at) for kind, at, _ in steps if kind == "woke"][2:]
    assert all(22.5 <= h <= 23.75 for h in onsets), onsets
    assert all(6.25 <= h <= 7.5 for h in wakes), wakes  # vers 7 h, pas à la minute près (une gigue par nuit)


def test_a_late_evening_pushes_sleep_and_waking_later():
    busy = Sleep(active_at=instant(datetime(2026, 9, 29, 1, 30, tzinfo=TZ)))
    t0 = instant(datetime(2026, 9, 28, 9, 0, tzinfo=TZ))
    steps = transitions(busy, t0, t0 + DAY + 12 * HOUR, P, TZ)
    onset = next(at for kind, at, _ in steps if kind == "fell_asleep")
    wake = next(at for kind, at, _ in steps if kind == "woke")
    assert _hm(onset) >= 1.5 and 8.0 <= _hm(wake) <= 10.0  # elle dort, mais pas moins pour autant


def test_the_night_has_cycles_deep_first_dreams_later():
    s = Sleep(asleep=True, since=instant(datetime(2026, 9, 28, 23, 0, tzinfo=TZ)), pressure=0.7)
    first_hour = {phase(s, s.since + m * MINUTE, P) for m in range(0, 60, 5)}
    last_cycle = [phase(s, s.since + 6 * HOUR + m * MINUTE, P) for m in range(0, 90, 5)]
    assert body_c.SleepPhase.DEEP_SLEEP in first_hour
    assert last_cycle.count(body_c.SleepPhase.REM) > last_cycle.count(body_c.SleepPhase.DEEP_SLEEP)


# ── De bout en bout ───────────────────────────────────────────────────────


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


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 14, 0), script=None, with_llm=False):
    script = script or Script()
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


def test_a_friends_message_at_three_in_the_morning_wakes_her_and_she_goes_back_to_sleep(tmp_path):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", "friend")
        await asyncio.sleep((at_paris(2026, 9, 29, 3, 0) - kernel.mind.clock.now()) / US)
        asleep = kernel.mind.frame().get(body_c.SLEEP)
        p = await kernel.perceive(said("user_1", "tu dors ?"))
        await p.reply
        awake = kernel.mind.frame().get(body_c.SLEEP)
        await asyncio.sleep(HOUR / US)
        again = kernel.mind.frame().get(body_c.SLEEP)
        return asleep, awake, again

    asleep, awake, again = run(tmp_path, scenario)
    assert asleep is not body_c.SleepPhase.AWAKE
    assert awake is body_c.SleepPhase.AWAKE
    assert again is not body_c.SleepPhase.AWAKE  # un quart d'heure de calme, et elle se rendort


def test_no_initiative_while_she_sleeps(tmp_path):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")
        await asyncio.sleep((at_paris(2026, 9, 29, 2, 0) - kernel.mind.clock.now()) / US)
        rows = kernel.arbiter.rows(kernel.mind.frame())
        return [r.vetoes for r in rows]

    vetoes = run(tmp_path, scenario)
    assert vetoes and all(any(v[1] == body_c.ASLEEP for v in vs) for vs in vetoes)


def test_needs_rise_with_time_and_fall_when_met(tmp_path):
    async def scenario(kernel, script, out):
        p = await kernel.perceive(said("user_1", "coucou"))
        await p.reply
        after = kernel.mind.frame().get(needs_c.NEEDS)
        await asyncio.sleep(3 * HOUR / US)
        later = kernel.mind.frame().get(needs_c.NEEDS)
        p = await kernel.perceive(said("user_1", "re !"))
        await p.reply
        met = kernel.mind.frame().get(needs_c.NEEDS)
        return after, later, met

    after, later, met = run(tmp_path, scenario)
    assert later.social > after.social + 0.2
    assert met.social < later.social / 2


def test_two_empty_hours_feel_like_boredom(tmp_path):
    async def scenario(kernel, script, out):
        p = await kernel.perceive(said("user_1", "bon, à plus"))
        await p.reply
        await asyncio.sleep(3 * HOUR / US)
        return events(kernel, needs_c.FELT.name)

    felt = run(tmp_path, scenario)
    assert felt and all(e.data.feeling in (needs_c.BORED, needs_c.LONELY) for e in felt)
    assert len(felt) <= 7  # une fois toutes les dix minutes, pas plus


def test_what_events_make_her_feel_replays_to_the_same_state(tmp_path):
    async def scenario(kernel, script, out):
        p = await kernel.perceive(said("user_1", "bon, à plus"))
        await p.reply
        await asyncio.sleep(4 * HOUR / US)
        live = digest(kernel.mind.root.slices["affect"])
        moved = kernel.mind.root.slices["affect"].mood is not None
        await kernel.mind.rebuild(["affect"])
        return live, digest(kernel.mind.root.slices["affect"]), moved

    live, rebuilt, moved = run(tmp_path, scenario)
    assert moved and live == rebuilt


def test_a_charged_exchange_leaves_one_thought_that_eases_when_she_talks(tmp_path):
    script = Script("[EMOTION:sad:0.85]")

    async def scenario(kernel, script, out):
        await connect(kernel, "user_1", "Alice")
        for text in ["mon chat est mort ce matin", "je suis dévastée", "je sais pas quoi faire"]:
            p = await kernel.perceive(said("user_1", text))
            await p.reply
            await asyncio.sleep(60)
        await asyncio.sleep(11 * MINUTE / US)  # l'échange se pose : la pensée naît
        born = kernel.mind.frame().get(attention_c.THOUGHTS)
        await asyncio.sleep(40 * MINUTE / US)
        before = kernel.mind.frame().get(attention_c.THOUGHTS)
        script.tag = "[EMOTION:happy:0.5]"
        p = await kernel.perceive(said("user_1", "merci d'être là, ça va un peu mieux"))
        await p.reply
        eased = kernel.mind.frame().get(attention_c.THOUGHTS)
        return born, before, eased

    born, before, eased = run(tmp_path, scenario, script=script)
    assert len(born) == 1 and born[0].about == ("user_1",) and born[0].emotion == "sad"
    # y revenir plus tard avec elle soulage (l'échange même ne l'avait pas éteinte)
    assert eased[0].intensity < before[0].intensity * 0.6


def test_the_thought_of_an_exchange_is_born_of_what_marked_most_once_it_settles(tmp_path):
    """« bon ben voilà » (un peu lourd), puis « je crois que j'ai tout raté » (très lourd) : la pensée qui lui
    reste naît quand l'échange s'est posé, et cite ce qui l'a le plus marquée — pas le premier message un peu
    chargé (sonde réelle du 2026-10-02 : « Adrien m'a dit : « bon ben voilà » »). Pendant l'échange, rien n'est
    encore né (contre-exemple : l'ancienne pensée naissait au premier message)."""
    script = Script("[EMOTION:sad:0.55]")

    async def scenario(kernel, script, out):
        await connect(kernel, "user_1", "Alice")
        await (await kernel.perceive(said("user_1", "bon ben voilà"))).reply
        await asyncio.sleep(60)
        script.tag = "[EMOTION:sad:0.9]"
        await (await kernel.perceive(said("user_1", "je crois que j'ai tout raté à mon entretien"))).reply
        await asyncio.sleep(60)
        script.tag = "[EMOTION:sad:0.5]"
        await (await kernel.perceive(said("user_1", "bref"))).reply
        during = kernel.mind.frame().get(attention_c.THOUGHTS)
        await asyncio.sleep(11 * MINUTE / US)
        born = kernel.mind.frame().get(attention_c.THOUGHTS)
        return during, born, kernel.mind.store.content([t.text_ref for t in born])

    during, born, texts = run(tmp_path, scenario, script=script)
    assert during == ()
    assert len(born) == 1 and "tout raté" in next(iter(texts.values()))


def test_a_thought_about_alice_is_not_shown_to_bob(tmp_path):
    script = Script("[EMOTION:sad:0.85]")

    async def scenario(kernel, script, out):
        await connect(kernel, "user_1", "Alice")
        p = await kernel.perceive(said("user_1", "CANARI-PENSEE ma mère est à l'hôpital"))
        await p.reply
        await asyncio.sleep(11 * MINUTE / US)  # l'échange se pose : la pensée naît
        script.tag = "[EMOTION:happy:0.5]"
        await connect(kernel, "user_2", "Bob")
        p = await kernel.perceive(said("user_2", "ça va toi ?"))
        await p.reply
        p = await kernel.perceive(said("user_1", "ça va mieux un peu"))
        await p.reply

    _, llm = run(tmp_path, scenario, script=script, with_llm=True)
    to_bob = [c.messages[-1].content for c in llm.calls if c.meta.get("target") == "user_2"]
    to_alice = [c.messages[-1].content for c in llm.calls if c.meta.get("target") == "user_1"]
    assert to_bob and not any("CANARI-PENSEE" in m for m in to_bob)
    assert any("CANARI-PENSEE" in m and "TROTTE" in m for m in to_alice[-1:])  # contrôle : elle, oui


def test_revising_a_belief_leaves_a_thought(tmp_path):
    async def scenario(kernel, script, out):
        old = await kernel.mind.append([memory_c.BELIEVED.draft(text=Content.of("Alice habite Lyon", level=1),
                                                                about=("user_1",), sensitivity=1)],
                                       emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await kernel.mind.append([memory_c.BELIEVED.draft(text=Content.of("Alice habite Nantes", level=1),
                                                          about=("user_1",), sensitivity=1, replaces=old.seqs[-1])],
                                 emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await asyncio.sleep(5)
        return kernel.mind.frame().get(attention_c.THOUGHTS), kernel.mind.store.content(
            [t.text_ref for t in kernel.mind.frame().get(attention_c.THOUGHTS)])

    thoughts, texts = run(tmp_path, scenario)
    assert [t.origin for t in thoughts] == [attention_c.REVISION]
    assert "Lyon" in next(iter(texts.values())) and "Nantes" in next(iter(texts.values()))


@pytest.mark.parametrize("late, counts", [(20 * MINUTE, True), (DAY, False)])
def test_ignored_she_doubts_a_little_and_a_late_reply_repairs_it_only_if_not_too_late(tmp_path, late, counts):
    """Ignorée, elle doute un peu ; une réponse tardive compte encore — dans trois
    fois le délai attendu (vingt minutes à l'écran : une heure). Le « salut » du
    lendemain n'est plus une réponse à son initiative : il ne répare rien
    (PSY-14)."""
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")
        p = await kernel.perceive(said("user_1", "coucou"))
        await p.reply
        for _ in range(120):  # elle finit par lui écrire d'elle-même…
            await asyncio.sleep(10 * MINUTE / US)
            if any(e.data.kind == "INITIATIVE" for e in events(kernel, rt.UTTERANCE.name)):
                break
        await asyncio.sleep(25 * MINUTE / US)  # … et personne ne répond à temps
        ignored = kernel.mind.frame().get(attention_c.IGNORED)
        low = kernel.mind.frame().get(self_c.ESTEEM)
        await asyncio.sleep((late - 5 * MINUTE) / US)
        before = kernel.mind.frame().get(self_c.ESTEEM)  # le temps, lui, a pu la ramener vers son équilibre
        p = await kernel.perceive(said("user_1", "oh pardon, je viens de voir ton message !"))
        await p.reply
        await asyncio.sleep(5)
        return (ignored, low, before, kernel.mind.frame().get(attention_c.IGNORED),
                kernel.mind.frame().get(self_c.ESTEEM))

    ignored, low, before, after, repaired = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    assert ignored >= 1 and low < 0.5
    if counts:
        assert after == 0 and repaired > before  # une réponse tardive compte encore
    else:
        assert after >= 1 and repaired <= before + 1e-3  # trop tard : elle écrit, ce n'est plus une réponse


def test_she_murmurs_before_speaking_up_but_not_every_time(tmp_path):
    """Une amie là, qui lui répond à chaque fois : elle prend souvent la parole,
    et se murmure parfois quelque chose avant — pas à chaque fois (PSY-21), pas
    plus d'une fois par heure ; le murmure n'est jamais un message, et ne se
    montre que sur les écrans de la personne à qui elle allait écrire."""
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")
        seen = 0
        for _ in range(2 * 24 * 6):
            await asyncio.sleep(10 * MINUTE / US)
            said_ = [e for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE"]
            if len(said_) > seen:
                seen = len(said_)
                await asyncio.sleep(5 * MINUTE / US)
                p = await kernel.perceive(said("user_1", "oui ça va, et toi ?"))
                await p.reply
        murmurs = [e for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "MURMUR"]
        initiatives = [e for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE"]
        return murmurs, initiatives, [d for d in out.items if d.persona == "inner" and d.kind == "speech"]

    murmurs, initiatives, inner = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    assert murmurs and len(murmurs) < len(initiatives)
    gaps = [b.at - a.at for a, b in zip(murmurs, murmurs[1:], strict=False)]
    assert all(g >= HOUR for g in gaps)
    assert all(not m.data.visible and m.data.target is None for m in murmurs)  # une pensée, pas un message
    assert inner and all(d.target == "user_1" for d in inner)  # sur ses écrans à elle, jamais à tout le monde


def test_her_story_is_written_by_her_own_voice_from_anodyne_memories(tmp_path):
    async def scenario(kernel, script, out):
        for i, (text, sens) in enumerate([("J'ai parlé de cuisine avec quelqu'un", 1),
                                          ("J'ai appris à reconnaître les oiseaux", 1),
                                          ("J'ai ri d'une blague sur les chats", 1),
                                          ("CANARI-RECIT Alice m'a confié sa rechute", 3),
                                          ("J'ai regardé la pluie tomber", 1)]):
            await kernel.mind.append([memory_c.REMEMBERED.draft(text=Content.of(text, level=sens),
                                                                about=("user_1",) if sens > 1 else (),
                                                                sensitivity=sens)],
                                     emitter="memory", correlation=f"genese{i}", origin=Origin.GENESIS)
        await asyncio.sleep(60)
        return events(kernel, self_c.NARRATED.name)

    narrated, llm = run(tmp_path, scenario, with_llm=True)
    assert len(narrated) == 1 and narrated[0].data.voice.role == "narrative"
    request = next(c for c in llm.calls if c.role == "narrative")
    shown = request.messages[-1].content
    assert "oiseaux" in shown and "CANARI-RECIT" not in shown
    assert request.persona is not None


@pytest.mark.parametrize("hour", [3, 14])
def test_her_rhythm_section_says_when_a_message_woke_her(tmp_path, hour):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", "friend")
        target = at_paris(2026, 9, 29, hour, 30)
        await asyncio.sleep((target - kernel.mind.clock.now()) / US)
        p = await kernel.perceive(said("user_1", "hello ?"))
        await p.reply

    _, llm = run(tmp_path, scenario, with_llm=True)
    last = llm.calls[-1].messages[-1].content
    woke = "ce message vient de te réveiller" in last
    assert woke == (hour == 3), last[:400]



def test_never_two_messages_in_a_row_to_an_absent_friend_whatever_the_reason(tmp_path):
    """Une amie absente, qui lui a confié un souci puis ne répond plus : une
    inquiétude, l'envie de discuter, le manque — un seul message, pas trois."""
    from mika.contracts import social as social_c

    async def scenario(kernel, script, out):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        script.tag = "[EMOTION:sad:0.85]"
        for text in ["ça va pas trop en ce moment", "mon père est malade", "j'ai peur"]:
            p = await kernel.perceive(said("tg_1", text, channel="telegram"))
            await p.reply
            await asyncio.sleep(60)
        script.tag = "[EMOTION:happy:0.5]"
        await asyncio.sleep(2 * DAY / US)
        return [e for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE" and e.data.target == "tg_1"]

    sent = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 11, 0))
    assert len(sent) == 1, [local(e.at, TZ).strftime("%a %H:%M") for e in sent]


def test_she_does_not_speak_the_moment_she_wakes_up(tmp_path):
    async def scenario(kernel, script, out):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")  # là, silencieuse, jusqu'au lendemain
        await asyncio.sleep((at_paris(2026, 9, 29, 12, 0) - kernel.mind.clock.now()) / US)
        woke = [e.data.at for e in events(kernel, body_c.WOKE.name)]
        spoke = [e.at for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE"]
        return woke, spoke

    woke, spoke = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 20, 0))
    assert woke
    first = woke[0]
    assert not [t for t in spoke if first <= t < first + 30 * MINUTE]
    assert [t for t in spoke if first + 30 * MINUTE <= t < first + 5 * HOUR]  # contrôle : elle parle ensuite
