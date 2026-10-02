"""L'affect sur la durée : ce qu'une relation installe, ce qu'une journée laisse,
ce que l'horloge ne doit jamais inventer (ADR 0032).

Cibles d'intention : ce qu'une personne ferait, une bande, et un contre-exemple
qui doit échouer. Tout ce qui le peut passe par le vrai noyau (elle répond avec
la balise qu'on lui dicte) ; le reste lit les mêmes fonctions que les faits.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.contracts import social as social_c
from mika.faculties import affect as F
from mika.faculties.affect import physics as ph
from mika.faculties.affect import prose
from mika.faculties.affect.params import DEFAULT
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab import affect as A
from mika.vocab import circadian
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import Kind
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, said

#: des soirées entre amies, telles qu'un modèle les balise
WARM_MIX = [("happy", 0.6), ("amused", 0.5), ("curious", 0.5), ("playful", 0.6), ("thinking", 0.4),
            ("grateful", 0.5), ("happy", 0.5), ("amused", 0.6), ("love", 0.4), ("curious", 0.6)]
#: les mêmes soirées, sans rien de chaleureux
FLAT_MIX = [("thinking", 0.4), ("curious", 0.3), ("thinking", 0.3), ("surprised", 0.3), ("thinking", 0.5)]


class Script:
    def __init__(self) -> None:
        self.tag = ""

    def __call__(self, req):
        return LLMResponse(f"d'accord {self.tag}".strip())


def run(tmp_path, scenario, *, start):
    script = Script()
    kernel, clock, _llm, _out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, script)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def turn(kernel, script, handle, emotion, intensity, text="…"):
    script.tag = f"[EMOTION:{emotion}:{intensity}]" if emotion else ""
    p = await kernel.perceive(said(handle, text))
    await p.reply


def fact(kernel, key):
    return kernel.mind.frame().get(key)


async def evenings(kernel, script, handle, mix, n, *, per=10, gap_s=120):
    """``n`` soirées : ``per`` tours vers 20 h, puis le reste de la journée."""
    for day in range(n):
        for k in range(per):
            emotion, intensity = mix[(day * per + k) % len(mix)]
            await turn(kernel, script, handle, emotion, intensity)
            await asyncio.sleep(gap_s)
        await asyncio.sleep((DAY - per * gap_s * US) / US)


# ── PSY-1 : une émotion ordinaire va dans son sens, à toute heure ─────────


@pytest.mark.parametrize("hour", [9, 15, 20])
def test_a_little_joy_lifts_her_and_a_little_sadness_lowers_her_alike(tmp_path, hour):
    """« Un peu contente » se lit contente, « un peu triste » se lit triste — à
    la même intensité. Mesurée depuis l'origine, la cible d'une joie légère
    tombait sous un repos déjà positif : happy:0.3 se lisait « lasse »."""
    async def scenario(kernel, script):
        await befriend(kernel, "user_1")
        await befriend(kernel, "user_2")
        await turn(kernel, script, "user_1", "happy", 0.3)
        await turn(kernel, script, "user_2", "sad", 0.3)
        return fact(kernel, affect_c.STANCE("user_1")), fact(kernel, affect_c.STANCE("user_2"))

    joy, sorrow = run(tmp_path, scenario, start=at_paris(2026, 9, 28, hour, 0))
    # sa posture, une fois la balise effacée : ce que dit la position seule
    assert joy.felt is Emotion.HAPPY and A.valence(joy.felt) > 0, joy
    assert sorrow.felt is Emotion.SAD, sorrow
    assert 0.6 < joy.felt_intensity / sorrow.felt_intensity < 1.6
    assert joy.position[0] > joy.home[0] and sorrow.position[0] < sorrow.home[0]


def test_ordinary_warm_evenings_make_a_close_friend(tmp_path):
    """Dix soirées d'échanges chaleureux ordinaires installent un regard
    nettement positif — assez pour devenir proches avant la « longue histoire ».
    Contre-exemple : les mêmes soirées sans chaleur n'installent rien."""
    async def scenario(kernel, script):
        await asyncio.sleep(6 * HOUR / US)  # 20 h
        await evenings(kernel, script, "user_1", WARM_MIX, 10)
        await evenings(kernel, script, "user_2", FLAT_MIX, 0)
        warm = (fact(kernel, affect_c.REGARD("user_1")), fact(kernel, social_c.CLOSENESS("user_1")),
                fact(kernel, affect_c.BOND("user_1")))
        return warm

    regard, closeness, bond = run(tmp_path / "chaleur", scenario, start=at_paris(2026, 9, 28, 14, 0))
    assert 0.15 <= regard <= 0.8, regard
    assert closeness == social_c.CLOSE, closeness
    assert bond > 0.1

    async def flat(kernel, script):
        await asyncio.sleep(6 * HOUR / US)
        await evenings(kernel, script, "user_1", FLAT_MIX, 10)
        return fact(kernel, affect_c.REGARD("user_1")), fact(kernel, social_c.CLOSENESS("user_1"))

    regard, closeness = run(tmp_path / "plat", flat, start=at_paris(2026, 9, 28, 14, 0))
    assert regard < 0.1 and closeness == social_c.FRIEND, (regard, closeness)


# ── PSY-3 / ajout B : une dispute n'efface pas un mois d'amitié ───────────


def test_a_fight_does_not_erase_a_long_friendship(tmp_path):
    """Une amie de trois semaines s'emporte quinze fois : ça se sent, mais ni la
    rancune ni le froid ne s'installent comme envers une inconnue (l'histoire
    ralentit l'ancre, l'attachement amortit l'hostilité)."""
    async def scenario(kernel, script):
        await asyncio.sleep(6 * HOUR / US)
        await evenings(kernel, script, "user_1", [("happy", 0.8), ("love", 0.7)], 21)
        for _ in range(15):
            await turn(kernel, script, "user_1", "angry", 0.7)
            await turn(kernel, script, "user_9", "angry", 0.7)
            await asyncio.sleep(120)
        out = {h: (fact(kernel, affect_c.HOSTILITY(h)), fact(kernel, affect_c.REGARD(h))) for h in ("user_1", "user_9")}
        await asyncio.sleep(DAY / US)
        out["next"] = fact(kernel, affect_c.HOSTILITY("user_1"))
        return out

    got = run(tmp_path, scenario, start=at_paris(2026, 9, 1, 14, 0))
    friend_hostility, friend_regard = got["user_1"]
    stranger_hostility, stranger_regard = got["user_9"]
    assert friend_hostility < 0.2 and friend_regard > 0.0, got  # ni rancune, ni froid
    assert stranger_hostility >= 0.3 and stranger_regard < -0.2, got  # contre-exemple : une inconnue, si
    assert got["next"] <= friend_hostility


# ── PSY-4 : consoler rapproche ────────────────────────────────────────────


def test_consoling_a_close_friend_brings_her_closer(tmp_path):
    """Une proche en deuil : être triste avec elle ne la refroidit pas — le
    lendemain, rien de « froid » ni de « seule » n'est installé envers elle.
    Contre-exemple : six colères, elles, refroidissent."""
    async def scenario(kernel, script, emotion):
        await befriend(kernel, "user_1", social_c.CLOSE)
        for _ in range(5):
            await turn(kernel, script, "user_1", "happy", 0.6)
            await asyncio.sleep(120)
        before = fact(kernel, affect_c.REGARD("user_1"))
        for _ in range(6):
            await turn(kernel, script, "user_1", emotion, 0.8)
            await asyncio.sleep(60)
        await asyncio.sleep(DAY / US)
        frame = kernel.mind.frame()
        line = prose.stance(frame.get(affect_c.STANCE("user_1")), DEFAULT, name="Alice", now=frame.now)
        return before, frame.get(affect_c.REGARD("user_1")), line

    before, after, line = run(tmp_path / "deuil", lambda k, s: scenario(k, s, "sad"), start=at_paris(2026, 9, 28, 15))
    assert after >= before, (before, after)
    assert not any(A.FR[e] in line for e in Emotion if A.valence(e) < 0), line
    before, after, _ = run(tmp_path / "colere", lambda k, s: scenario(k, s, "angry"), start=at_paris(2026, 9, 28, 15))
    assert after < before - 0.05


# ── PSY-10 : l'affection dure, la rancune envers un troll aussi ───────────


def test_warmth_lasts_weeks_and_a_trolls_grudge_lasts_days(tmp_path):
    async def scenario(kernel, script):
        for _ in range(10):
            await turn(kernel, script, "user_1", "love", 0.8)
            await asyncio.sleep(120)
        for _ in range(12):
            await turn(kernel, script, "user_9", "angry", 0.8, "t'es nulle")
            await asyncio.sleep(60)
        out = {"warm": fact(kernel, affect_c.REGARD("user_1")), "troll": fact(kernel, affect_c.HOSTILITY("user_9"))}
        await asyncio.sleep(DAY / US)
        out["troll+1"] = fact(kernel, affect_c.HOSTILITY("user_9"))
        await asyncio.sleep(6 * DAY / US)
        out["warm+7"] = fact(kernel, affect_c.REGARD("user_1"))
        await asyncio.sleep(3 * DAY / US)
        out["troll+10"] = fact(kernel, affect_c.HOSTILITY("user_9"))
        await asyncio.sleep(15 * DAY / US)
        out["troll+25"] = fact(kernel, affect_c.HOSTILITY("user_9"))
        return out

    got = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    assert got["warm+7"] >= 0.6 * got["warm"], got  # une semaine sans nouvelles ne l'efface pas
    assert got["troll+1"] >= 0.2, got  # le lendemain, elle lui en veut encore
    assert got["troll+10"] >= 0.1 - 1e-9, got  # dix jours après, une méfiance demeure
    assert got["troll+25"] < 0.1, got  # mais elle finit par passer


# ── PSY-9 : une rancune ne varie pas avec l'heure ─────────────────────────


def test_a_grudge_does_not_change_with_the_time_of_day(tmp_path):
    async def scenario(kernel, script):
        for _ in range(12):
            await turn(kernel, script, "user_9", "angry", 0.8)
            await asyncio.sleep(60)
        afternoon = fact(kernel, affect_c.HOSTILITY("user_9"))
        await asyncio.sleep(5 * HOUR / US)  # 19 h passées : une autre teinte du repos
        return afternoon, fact(kernel, affect_c.HOSTILITY("user_9"))

    afternoon, evening = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    assert abs(afternoon - evening) < 0.02, (afternoon, evening)


# ── PSY-5 : l'horloge n'invente rien ──────────────────────────────────────


@pytest.mark.parametrize("hm", [(6, 10), (12, 10), (18, 1), (18, 5), (18, 20), (23, 10)])
def test_the_clock_invents_no_emotion(hm):
    """Au repos depuis la nuit, rien ne se passe : aux changements de phase, elle
    ne ressent ni nostalgie ni curiosité (lues contre un repos qui avait sauté,
    elles dépassaient le seuil de débordement à 18 h)."""
    cw = ph.Clockwork(PARIS, circadian.DEFAULT)
    s = F.AffectState(mood=ph.advance_mood(None, at_paris(2026, 9, 28, 4, 0), DEFAULT, cw))
    m = F.mood_reading(s, at_paris(2026, 9, 28, *hm), DEFAULT, cw)
    assert m.felt_intensity < 0.05 and m.overflow < 0.05, m
    assert prose.mood(m, DEFAULT).endswith("comme d'habitude.")


# ── PSY-6 / ajout A : une après-midi triste colore la soirée ──────────────


def test_a_sad_afternoon_colours_the_evening_and_sleep_lightens_it(tmp_path):
    """Une proche en deuil, une heure et demie l'après-midi : le soir, elle n'est
    pas « comme d'habitude » ; le lendemain matin, il en reste moins. Contre-
    exemple : la même après-midi joyeuse ne la rend pas triste le soir."""
    async def scenario(kernel, script, emotion):
        await befriend(kernel, "user_1", social_c.CLOSE)
        for _ in range(18):
            await turn(kernel, script, "user_1", emotion, 0.7)
            await asyncio.sleep(5 * MINUTE / US)
        # la soirée suit son cours : une autre amie passe dire un mot (sans rien qui la touche)
        for hour, minute in ((17, 30), (18, 40), (19, 25)):
            await asyncio.sleep((at_paris(2026, 9, 28, hour, minute) - kernel.mind.clock.now()) / US)
            await turn(kernel, script, "user_2", None, 0, "et sinon, ta soirée ?")
        await asyncio.sleep((at_paris(2026, 9, 28, 19, 30) - kernel.mind.clock.now()) / US)
        evening = fact(kernel, affect_c.MOOD)
        await asyncio.sleep((at_paris(2026, 9, 29, 10, 0) - kernel.mind.clock.now()) / US)
        return evening, fact(kernel, affect_c.MOOD), fact(kernel, body_c.SLEEP)

    evening, morning, sleep = run(tmp_path / "triste", lambda k, s: scenario(k, s, "sad"),
                                  start=at_paris(2026, 9, 28, 15, 0))
    said_evening = prose.mood(evening, DEFAULT)
    assert not said_evening.endswith("comme d'habitude."), said_evening
    assert evening.fond[0] < -0.04 and A.valence(evening.felt) < 0, evening
    assert sleep is body_c.SleepPhase.AWAKE
    assert 0 < A.norm(morning.fond) < 0.5 * A.norm(evening.fond), (evening.fond, morning.fond)
    joyful, _, _ = run(tmp_path / "joie", lambda k, s: scenario(k, s, "happy"), start=at_paris(2026, 9, 28, 15, 0))
    assert joyful.fond[0] >= 0 and A.valence(joyful.felt) >= 0, joyful


def test_what_lingers_keeps_the_name_of_what_caused_it():
    """Une colère de l'après-midi, le soir : il en reste « un peu de colère ».
    Lu contre le repos du soir, le même écart se nommait « pensive »."""
    cw = ph.Clockwork(PARIS, circadian.DEFAULT)
    p = DEFAULT
    t = at_paris(2026, 9, 28, 16, 0)
    afternoon = ph.common_home(t, p, cw)
    fond = A.scale(A.sub(A.ANCHORS[Emotion.ANGRY], afternoon), 0.1)
    m = ph.Mood(ph.Osc(afternoon, (0.0, 0.0, 0.0), t), fond=fond, marks=(ph.Mark(t, "angry", "talk", "user_1"),))
    evening = at_paris(2026, 9, 28, 19, 30)
    reading = F.mood_reading(F.AffectState(mood=m), evening, p, cw)
    assert reading.fond_emotion is Emotion.ANGRY
    assert "un petit reste de colère" in prose.mood(reading, p), prose.mood(reading, p)
    # contre-exemple : la lecture contre le repos de l'heure se trompait de nom
    assert A.felt(A.add(reading.home, reading.fond), reading.home)[0] is not Emotion.ANGRY


def test_sleep_freezes_the_fond_and_waking_lightens_it():
    """Pendant qu'elle dort, le fond ne bouge pas ; au réveil il perd sa part
    (60 % par défaut) — il en reste assez pour colorer le matin."""
    cw = ph.Clockwork(PARIS, circadian.DEFAULT)
    p = DEFAULT
    t = at_paris(2026, 9, 28, 23, 0)
    m = ph.Mood(ph.Osc(ph.common_home(t, p, cw), (0.0, 0.0, 0.0), t), fond=(-0.12, -0.05, -0.08))
    asleep = ph.fall_asleep(m)
    night = ph.advance_mood(asleep, t + 7 * HOUR, p, cw)
    assert night.fond == m.fond
    woke = ph.wake(night, p)
    assert A.norm(woke.fond) == pytest.approx((1 - p.sleep_relief) * A.norm(m.fond))
    awake_all_night = ph.advance_mood(m, t + 7 * HOUR, p, cw)  # contre-exemple : éveillée, il aurait décru
    assert A.norm(awake_all_night.fond) < A.norm(m.fond)


# ── PSY-8 / PRM-4 : « installé » seulement quand ça l'est ─────────────────


def test_two_ordinary_turns_are_not_an_installed_feeling(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "user_1")
        for _ in range(2):
            await turn(kernel, script, "user_1", "happy", 0.6)
            await asyncio.sleep(60)
        frame = kernel.mind.frame()
        light = prose.stance(frame.get(affect_c.STANCE("user_1")), DEFAULT, name="Alice", now=frame.now)
        for _ in range(4):
            await turn(kernel, script, "user_9", "angry", 0.8)
            await asyncio.sleep(60)
        frame = kernel.mind.frame()
        heavy = prose.stance(frame.get(affect_c.STANCE("user_9")), DEFAULT, name="Kev", now=frame.now)
        return light, heavy

    light, heavy = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 15, 0))
    assert "plusieurs échanges de suite" not in light and "bien ancrée" not in light, light
    assert "Ça fait plusieurs échanges de suite que tu te sens en colère avec « Kev »" in heavy, heavy
    assert "ça ne passera pas en deux minutes" in heavy  # l'ancre porte cette colère


# ── PSY-11 / EDG-16 : ce qu'elle a déclaré s'estompe, sans couperet ───────


def test_what_she_declared_fades_instead_of_vanishing(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "user_1")
        await turn(kernel, script, "user_1", "sad", 0.8)
        out = []
        for wait_s in (3, 5 * 60, 12 * 60, 35 * 60):
            await asyncio.sleep(wait_s - (sum(w for w, _f, _s in out) if out else 0))
            frame = kernel.mind.frame()
            out.append((wait_s, frame.get(affect_c.FACE("user_1")), frame.get(affect_c.STANCE("user_1"))))
        return out

    readings = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 15, 0))
    faces = [face for _w, face, _s in readings]
    # le visage montre la balise de sa réplique, en décroissance — pas une troisième émotion effondrée à 3 s
    assert faces[0].emotion is Emotion.SAD and faces[0].intensity >= 0.75, faces[0]
    assert faces[1].emotion is Emotion.SAD and faces[2].emotion is Emotion.SAD
    assert faces[0].intensity > faces[1].intensity > faces[2].intensity
    declared = [s.declared for _w, _f, s in readings]
    assert declared[1] is not None and declared[1].intensity < 0.8  # elle s'estompe…
    assert declared[3] is None  # … et finit par laisser parler la posture


# ── PSY-23 : la joie du retour réchauffe sa posture, à toute heure ────────


class _Cx:
    def __init__(self, t):
        self.now = t
        self.params = DEFAULT
        self.tz = PARIS
        self.facts = SimpleNamespace(get=lambda ref: circadian.DEFAULT)


@pytest.mark.parametrize("hour", [9, 19, 23])
def test_a_friends_return_warms_her_stance_at_any_hour(hour):
    """L'évaluation « retour » (joie 0,4 envers la personne) : l'échelle appliquée
    deux fois visait un point sous le repos du soir — la joie se lisait froide."""
    t = at_paris(2026, 9, 28, hour, 0)
    s = F._feel(F.AffectState(), (Appraisal(Emotion.HAPPY, 0.4, toward="user_1", reason="retour"),),
                SimpleNamespace(at=t), _Cx(t))
    st = F.stance_reading(s, "user_1", t + 1, DEFAULT, ph.Clockwork(PARIS, circadian.DEFAULT))
    assert A.valence(st.felt) > 0 and st.position[0] > st.home[0], st


# ── PRM-3 / PRM-16 : ce que le prompt lui dit ─────────────────────────────


def test_the_prompt_tells_her_what_she_was_not_what_she_feels_for_them(tmp_path):
    """Sa balise dit ce qu'elle était en lui écrivant (« Envers… » est réservé à
    ce que la relation a installé) ; la cause d'une humeur se dit sans nommer
    un tiers ; jamais « une nuance de en colère » ni « mono-couleur »."""
    async def scenario(kernel, script):
        await befriend(kernel, "user_1")
        await connect(kernel, "user_1", "Alice")
        for _ in range(3):
            await turn(kernel, script, "user_1", "sad", 0.8, "ma grand-mère est à l'hôpital")
            await asyncio.sleep(60)
        await turn(kernel, script, "user_1", "proud", 0.7)
        frame = kernel.mind.frame()
        stance_line = prose.stance(frame.get(affect_c.STANCE("user_1")), DEFAULT, name="Alice", now=frame.now)
        for_bob = prose.mood(frame.get(affect_c.MOOD), DEFAULT, current="user_2")
        for_alice = prose.mood(frame.get(affect_c.MOOD), DEFAULT, current="user_1")
        return stance_line, for_bob, for_alice

    stance_line, for_bob, for_alice = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 15, 0))
    assert stance_line.startswith("À l'instant, en lui répondant, tu étais assez fière."), stance_line
    assert "Envers « Alice », tu te sens" not in stance_line
    for line in (stance_line, for_bob, for_alice):
        assert "nuance de" not in line and "mono-couleur" not in line
    assert "Alice" not in for_bob and "une autre conversation" in for_bob, for_bob
    assert "votre échange" in for_alice, for_alice


def test_a_mood_without_known_cause_says_so():
    m = affect_c.MoodReading((0.0, 0.0, 0.0), (0.3, 0.1, 0.1), Emotion.SAD, 0.4, 0.4, Emotion.SAD, 0.3)
    line = prose.mood(m, DEFAULT)
    assert "sans trop savoir pourquoi" in line and "Ça vient" not in line


def test_her_mood_follows_her_into_her_work():
    """PRM-26 : une séance de travail sur un but (STEP) ou un projet dans son mode
    à elle (WORK) n'est pas hors-sol : elle y emporte son humeur."""
    spec = next(sec for sec in F.AFFECT.sections if sec.key == "mood")
    assert {Kind.STEP, Kind.WORK} <= set(spec.episodes)
    assert Kind.JOB not in spec.episodes  # le mode impersonnel reste sans affect
