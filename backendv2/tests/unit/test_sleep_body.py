"""Son corps la nuit et le soir, par ses intentions.

- elle ne s'endort pas à la minute près chaque soir (une gigue tirée de la
  date : le rejeu retombe sur les mêmes nuits) ;
- elle n'est pas « fatiguée dès 22 h » : la fatigue vient dans l'heure qui
  précède le moment où elle s'endormirait, et se creuse si on la tient
  éveillée au-delà ;
- la nuit, seule une amie, une proche ou quelque chose d'urgent la réveille ;
  les autres messages attendent son réveil, et elle y répond le matin en
  sachant qu'elle dormait (une seule réponse pour plusieurs messages) ;
- son rythme dit la date et l'heure en clair, sans pourcentage ; « ce message
  t'a réveillée » se dit au premier tour, puis « tu émerges encore ».
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.body import FOG, BodyParams, BodyState, energy, fog
from mika.faculties.body import sleep as sl
from mika.kernel.clock import DAY, HOUR, MINUTE, US, instant, local
from mika.kernel.inspect import Timeline
from mika.ports.llm import LLMResponse
from mika.runtime.inspection import find, run_view
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from mika.vocab import circadian
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said

TZ = ZoneInfo("Europe/Paris")
P = BodyParams()


def _hm(t: int) -> float:
    d = local(t, TZ)
    return d.hour + d.minute / 60


def _nights(p: sl.SleepParams, days: int = 8) -> list[tuple[str, int, sl.Sleep]]:
    t0 = instant(datetime(2026, 9, 28, 9, 0, tzinfo=TZ))
    return sl.transitions(sl.Sleep(), t0, t0 + days * DAY, p, TZ, limit=4 * days)


# ── Le sommeil, pur ───────────────────────────────────────────────────────


def test_she_does_not_fall_asleep_at_the_same_minute_every_night():
    steps = _nights(P.sleep)
    onsets = [_hm(at) for kind, at, _ in steps if kind == "fell_asleep"][1:]
    wakes = [_hm(at) for kind, at, _ in steps if kind == "woke"][1:]
    assert len(onsets) >= 6
    assert all(22.5 <= h <= 23.75 for h in onsets), onsets  # vers 23 h…
    assert all(6.25 <= h <= 7.5 for h in wakes), wakes  # … et vers 7 h
    assert max(onsets) - min(onsets) >= 0.25 and len({round(h * 60) for h in onsets}) >= len(onsets) - 1  # pas pile
    assert _nights(P.sleep) == steps  # la gigue est tirée de la date : rejouable
    still = [_hm(at) for kind, at, _ in _nights(sl.SleepParams(jitter=0.0)) if kind == "fell_asleep"][2:]
    assert max(still) - min(still) < 0.05  # contrôle : sans gigue, à la minute près (l'ancien défaut)


def _evening(day: int, hour: int, minute: int = 0) -> int:
    return instant(datetime(2026, 9, day, hour, minute, tzinfo=TZ))


def test_she_is_not_tired_at_ten_every_evening_only_close_to_sleep():
    steps = _nights(P.sleep, days=7)
    for (k1, woke, morning), (k2, onset, _) in zip(steps, steps[1:], strict=False):
        if k1 != "woke" or k2 != "fell_asleep":
            continue
        s = BodyState(sleep=morning)
        d = local(woke, TZ)
        at = lambda h, m=0, d=d: _evening(d.day, h, m)  # noqa: E731
        assert energy(s, at(21), P, TZ) >= 0.5  # 21 h : en forme, chaque soir
        assert energy(s, onset - 2 * HOUR, P, TZ) > P.tired_below  # deux heures avant : pas fatiguée
        assert energy(s, onset - 5 * MINUTE, P, TZ) < 0.3  # tout près de s'endormir : fatiguée
        tired = [t for t in range(at(19), onset, 5 * MINUTE) if energy(s, t, P, TZ) < P.tired_below]
        assert tired and onset - tired[0] <= 75 * MINUTE  # la fatigue vient dans l'heure qui précède


def test_kept_awake_past_her_bedtime_she_ends_up_falling_asleep_on_her_feet():
    onset = next(at for kind, at, _ in _nights(P.sleep) if kind == "fell_asleep" and _hm(at) > 22)
    s = BodyState(sleep=sl.Sleep(since=onset - 16 * HOUR, pressure=0.17, active_at=onset + 3 * HOUR))
    near, past, late = (energy(s, onset - 10 * MINUTE, P, TZ), energy(s, onset + HOUR, P, TZ),
                        energy(s, onset + 2 * HOUR + 30 * MINUTE, P, TZ))
    assert near > past > late
    assert late < FOG[0][0]  # « tu tombes de sommeil »


def test_her_rhythm_says_the_date_and_hour_plainly():
    profile = circadian.DEFAULT
    late = circadian.describe(datetime(2026, 9, 28, 23, 23, tzinfo=TZ), profile, 0.15)
    assert late.startswith("Nous sommes lundi 28 septembre 2026, il est 23h23 — c'est la nuit, et tu es épuisée.")
    noon = circadian.describe(datetime(2026, 9, 29, 14, 5, tzinfo=TZ), profile, 0.62)
    for text in (late, noon):
        assert "%" not in text and "phase" not in text and "mode" not in text  # ni pourcentage ni jargon
    assert "tu as la pêche" not in noon and "tu es en forme" in noon
    assert all("gentille" not in (fog(limit - 0.01) or "") for limit, _ in FOG)  # fatiguée, elle n'est pas tenue d'être gentille


# ── La nuit, de bout en bout ──────────────────────────────────────────────


def script(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    if req.role in ("journal", "dream", "murmur", "narrative"):
        return LLMResponse("hmm")
    return LLMResponse("d'accord [EMOTION:happy:0.5]")


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 20, 0)):
    kernel, clock, llm, _ = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main), llm


async def until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


def of(kernel, event):
    return [kernel.mind.decode(e) for e in kernel.mind.store.read() if e.type == event.name]


def replies_to(llm, handle):
    return [c for c in llm.calls if c.role == "reply" and c.meta.get("target") == handle]


def test_at_three_a_stranger_waits_for_morning_a_close_friend_wakes_her(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "user_1", "close")
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        held = await kernel.perceive(said("user_2", "tu dors ?"))
        await asyncio.sleep(60)
        still = kernel.mind.frame().get(body_c.SLEEP)
        await asyncio.sleep(10 * MINUTE / US)
        p = await kernel.perceive(said("user_1", "tu dors ?"))
        await p.reply
        woken = kernel.mind.frame().get(body_c.SLEEP)
        await asyncio.sleep(2 * MINUTE / US)
        p = await kernel.perceive(said("user_1", "désolée de te réveiller"))
        await p.reply
        await asyncio.sleep(HOUR / US)
        again = kernel.mind.frame().get(body_c.SLEEP)
        await until(kernel, at_paris(2026, 9, 29, 9, 0))
        woke = [e.data.at for e in of(kernel, body_c.WOKE)]
        to_bob = [e.at for e in of(kernel, rt.UTTERANCE) if e.data.target == "user_2"]
        return held.reply, still, woken, again, of(kernel, body_c.ROUSED), of(kernel, body_c.WAITED), woke, to_bob

    (held, still, woken, again, roused, waited, woke, to_bob), llm = run(tmp_path, scenario)
    assert held is None and still is not body_c.SleepPhase.AWAKE  # un inconnu à 3 h : elle dort encore
    assert woken is body_c.SleepPhase.AWAKE and again is not body_c.SleepPhase.AWAKE  # Alice la réveille, puis elle se rendort
    assert [r.data.handle for r in roused] == ["user_1"] and [w.data.handle for w in waited] == ["user_2"]
    to_alice = [c.messages[-1].content for c in replies_to(llm, "user_1")]
    assert "Tu dormais : ce message vient de te réveiller." in to_alice[0]
    assert "ce message vient de te réveiller" not in to_alice[1] and "tu émerges encore" in to_alice[1]
    assert len(to_bob) == 1 and woke and to_bob[0] >= woke[-1] and _hm(to_bob[0]) < 12  # au réveil, elle lui répond
    morning = replies_to(llm, "user_2")[0].messages[-1].content
    assert "pendant que tu dormais" in morning  # et elle sait qu'elle dormait
    assert "tu ne le lis que maintenant" in morning.rsplit("--- FIN ETAT INTERNE ---", 1)[1], \
        "…et le message lui-même dit qu'elle le lit au réveil, pas à 3 h"
    assert "tu ne le lis que maintenant" not in to_alice[0], "contre-exemple : réveillée par lui, elle le lit aussitôt"


def test_on_a_fresh_install_her_owner_wakes_her_at_three_a_stranger_waits(tmp_path):
    """Sa propriétaire n'a encore aucune histoire avec elle : une amie d'office (``social.owner_floor``), donc
    son message de 3 h la réveille ; un inconnu, lui, attend le matin. Pas « proche » pour autant."""
    async def scenario(kernel):
        await connect(kernel, "user_9", "Adrien", operator=True)
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        held = await kernel.perceive(said("user_2", "tu dors ?"))
        await asyncio.sleep(10 * MINUTE / US)
        p = await kernel.perceive(said("user_9", "tu dors ?"))
        answered = p.reply is not None and bool(await p.reply)
        frame = kernel.mind.frame()
        owner = frame.get(identity_c.PERSON("user_9"))
        return held.reply, answered, frame.get(social_c.CLOSENESS(owner)), of(kernel, body_c.ROUSED)

    (held, answered, level, roused), _ = run(tmp_path, scenario)
    assert held is None  # l'inconnu attend son réveil
    assert answered and [r.data.handle for r in roused] == ["user_9"]  # sa propriétaire la réveille
    assert level == social_c.FRIEND  # une amie d'office, pas une proche


def test_something_urgent_wakes_her_whoever_writes(tmp_path):
    async def scenario(kernel):
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        p = await kernel.perceive(said("user_2", "c'est urgent, réponds-moi s'il te plaît"))
        await p.reply
        return of(kernel, body_c.ROUSED)

    roused, llm = run(tmp_path, scenario)
    assert [r.data.reason for r in roused] == [body_c.URGENT] and replies_to(llm, "user_2")


def test_several_messages_in_the_night_get_one_answer_in_the_morning(tmp_path):
    async def scenario(kernel):
        await until(kernel, at_paris(2026, 9, 29, 2, 0))
        for text in ["coucou", "t'es là ?", "bon, je te raconte demain"]:
            await kernel.perceive(said("user_2", text))
            await asyncio.sleep(5 * MINUTE / US)
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        ended = [e for e in of(kernel, rt.EPISODE_ENDED) if e.data.target == "user_2"]
        said_ = [e for e in of(kernel, rt.UTTERANCE) if e.data.target == "user_2"]
        return ended, said_

    (ended, said_), llm = run(tmp_path, scenario)
    assert len(said_) == 1 and _hm(said_[0].at) >= 6  # une réponse, le matin
    # elle répond au dernier, et sa réponse règle les trois (son tour : ADR 0040) — aucun « sans réponse »
    assert len(said_[0].data.answers) == 3 and said_[0].data.reply_to == max(said_[0].data.answers)
    assert not [e for e in ended if e.data.unanswered]
    shown = replies_to(llm, "user_2")[0].messages[-1].content
    assert "Ses messages de la nuit" in shown


def test_when_the_one_who_waited_wakes_her_she_answers_once(tmp_path):
    """Quelqu'un écrit à 2 h (ça attend), puis insiste, urgent, à 2 h 30 : elle
    se réveille et lui répond une fois — ses messages de la nuit lus avec."""

    async def scenario(kernel):
        await until(kernel, at_paris(2026, 9, 29, 2, 0))
        await kernel.perceive(said("user_2", "t'es là ?"))
        await asyncio.sleep(30 * MINUTE / US)
        await (await kernel.perceive(said("user_2", "c'est urgent, réponds-moi"))).reply
        await asyncio.sleep(5 * MINUTE / US)
        return [e for e in of(kernel, rt.UTTERANCE) if e.data.target == "user_2"], \
            [e.data.outcome for e in of(kernel, rt.EPISODE_ENDED) if e.data.target == "user_2"]

    (said_, outcomes), _ = run(tmp_path, scenario)
    # une seule réponse, au message urgent, qui règle aussi celui de 2 h (le tour : ADR 0040)
    assert len(said_) == 1 and len(said_[0].data.answers) == 2, ([(e.data.reply_to, e.data.answers) for e in said_],
                                                                 outcomes)
    assert outcomes == ["done"]


def test_a_message_waiting_for_her_survives_a_restart_and_is_answered(tmp_path):
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 20, 0))

    async def first():
        await boot(kernel)
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        await kernel.perceive(said("user_2", "tu dors ?"))
        await asyncio.sleep(MINUTE / US)
        await kernel.stop()

    run_virtual(clock, first)
    clock.advance_to(at_paris(2026, 9, 29, 9, 30))  # le serveur repart au matin, bien après sa réponse « due »
    kernel2, _, _, _ = build(tmp_path, script, clock=clock, llm=llm)

    async def second():
        await boot(kernel2)
        await asyncio.sleep(10 * MINUTE / US)
        out = [e for e in of(kernel2, rt.UTTERANCE) if e.data.target == "user_2"]
        await kernel2.stop()
        return out

    answered = run_virtual(clock, second)
    assert len(answered) == 1  # pas abandonnée comme « trop tard » : elle dormait


def test_a_restart_right_after_her_waking_counts_the_question_from_her_waking(tmp_path):
    """Le serveur tombe pendant qu'elle compose sa réponse du matin : au
    redémarrage, la question de 3 h n'est pas « trop vieille » — elle compte
    depuis son réveil."""
    # sa réponse prend plus d'une minute et demie (sous le délai d'un tour de conversation, 120 s : ADR 0038)
    slow = lambda req: 100.0 if req.role == "reply" else 0.0  # noqa: E731
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 20, 0), latency=slow)

    async def first():
        await boot(kernel)
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        await kernel.perceive(said("user_2", "tu dors ?"))
        while not of(kernel, body_c.WOKE):  # elle se réveille vers 7 h…
            await asyncio.sleep(20)
        await asyncio.sleep(30)  # … sa réponse est en route…
        woke = of(kernel, body_c.WOKE)[-1].data.at
        await kernel.stop()  # … et le serveur s'arrête
        return woke

    woke = run_virtual(clock, first)
    clock.advance_to(woke + 8 * MINUTE)
    kernel2, _, _, _ = build(tmp_path, script, clock=clock, llm=llm)

    async def second():
        await boot(kernel2)
        await asyncio.sleep(30 * MINUTE / US)
        ended = [e for e in of(kernel2, rt.EPISODE_ENDED) if e.data.target == "user_2"]
        said_ = [e for e in of(kernel2, rt.UTTERANCE) if e.data.target == "user_2"]
        await kernel2.stop()
        return ended, said_

    ended, said_ = run_virtual(clock, second)
    assert not [e for e in ended if "trop tard" in (e.data.detail or "")]  # elle dormait : pas « trop tard »
    assert [e.data.outcome for e in ended] == ["cancelled", "done"] and len(said_) == 1  # la reprise lui répond


def test_a_woken_night_shows_in_her_last_transitions(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "user_1", "friend")
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        await (await kernel.perceive(said("user_1", "tu dors ?"))).reply
        await kernel.perceive(said("user_3", "hello"))
        return run_view(kernel, find(kernel, "body", "rythme"), {})

    blocks, _ = run(tmp_path, scenario)
    timeline = next(b for b in blocks if isinstance(b, Timeline))
    titles = [e.title for e in timeline.entries]
    assert "tirée du sommeil par un message" in titles and "un message attend son réveil" in titles


def test_a_connected_friend_does_not_get_a_reply_at_night_from_others(tmp_path):
    """Réveillée par une amie, elle lui répond — pas aux autres, qui attendent
    son vrai réveil."""

    async def scenario(kernel):
        await befriend(kernel, "user_1", "friend")
        await connect(kernel, "user_1", "Alice")
        await until(kernel, at_paris(2026, 9, 29, 3, 0))
        await (await kernel.perceive(said("user_1", "t'es là ?"))).reply
        held = await kernel.perceive(said("user_2", "et moi ?"))
        await asyncio.sleep(5 * MINUTE / US)
        night = [e for e in of(kernel, rt.UTTERANCE) if e.data.target == "user_2"]
        return held.reply, night

    (held, night), _ = run(tmp_path, scenario)
    assert held is None and night == []


def test_her_rhythm_follows_her_into_her_work_sessions(tmp_path):
    """Une séance de travail (un pas) n'est pas hors-sol : elle sait la date,
    l'heure, le moment, sa fatigue."""
    clock = SimClock(at_paris(2026, 9, 28, 14, 0))
    llm = PersonaSimLLM(clock, seed=1, abstain_rate=0.0, latency=2.0)
    kernel, clock, _, _ = build(tmp_path, None, clock=clock, llm=llm)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "j'ai peur, je stresse pour mon examen de demain"))).reply
            await asyncio.sleep(3 * HOUR / US)
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    steps = [c for c in llm.calls if c.role == "step"]
    assert steps
    shown = "\n".join(m.content for m in steps[0].messages)
    assert "TON RYTHME" in shown and "Nous sommes lundi 28 septembre 2026" in shown and "%" not in shown
