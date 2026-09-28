"""L'affect, par ses intentions — pas par parité avec une version antérieure.

Chaque test dit ce qu'une personne ferait, et pourquoi ; les chiffres sont des
bandes, pas des valeurs épinglées. Tout passe par le vrai noyau : elle répond
avec une balise, la posture et l'humeur en tirent les conséquences.
"""

from __future__ import annotations

import asyncio

import pytest

from mika.contracts import affect as affect_c
from mika.faculties.affect import physics as ph
from mika.faculties.affect import prose
from mika.faculties.affect.params import DEFAULT, derive
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab import affect as A
from mika.vocab import circadian
from mika.vocab.affect import Emotion
from mika.vocab.temperament import Temperament
from tests.fixtures.mika import AFTERNOON, PARIS, at_paris, boot, build, said

GATE = 0.6  # la porte de débordement de l'humeur (conscience, M4)


class Script:
    """Le modèle factice répond avec la balise qu'on lui dicte."""

    def __init__(self) -> None:
        self.tag = ""

    def __call__(self, req):
        return LLMResponse(f"d'accord {self.tag}".strip())


def run(tmp_path, scenario, *, start=AFTERNOON, doc=None):
    script = Script()
    kernel, clock, _llm, _out = build(tmp_path, script, start=start)

    async def main():
        await (boot(kernel) if doc is None else boot(kernel, doc))
        try:
            return await scenario(kernel, script)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def turn(kernel, script, handle, emotion, intensity, text="…"):
    script.tag = f"[EMOTION:{emotion}:{intensity}]" if emotion else ""
    p = await kernel.perceive(said(handle, text))
    await p.reply


def stance_prose(kernel, handle) -> str:
    frame = kernel.mind.frame()
    return prose.stance(frame.get(affect_c.STANCE(handle)), frame.get(affect_c.MOOD).home, DEFAULT)


def overflow(kernel) -> float:
    return kernel.mind.frame().get(affect_c.MOOD).overflow


def stance(kernel, handle):
    return kernel.mind.frame().get(affect_c.STANCE(handle))


async def sustained(kernel, script, emotion, n=8, gap_s=90, handle="user_1"):
    readings = []
    for _ in range(n):
        await turn(kernel, script, handle, emotion, 0.8)
        readings.append(overflow(kernel))
        await asyncio.sleep(gap_s)
    return readings


# ── Débordement : la tristesse de quelqu'un finit par la déborder ─────────


@pytest.mark.parametrize("hour", [8, 14, 23])
def test_sustained_sadness_overflows_within_a_handful_of_turns(tmp_path, hour):
    """Quelqu'un qui va mal, tour après tour : au bout de quelques échanges,
    elle en est elle-même remuée — quelle que soit l'heure."""
    readings = run(tmp_path, lambda k, s: sustained(k, s, "sad"), start=at_paris(2026, 9, 28, hour, 30))
    first = next((i + 1 for i, v in enumerate(readings) if v > GATE), None)
    assert first is not None and first <= 6, readings
    assert readings[0] < GATE  # un seul tour ne suffit pas


def test_sustained_anger_overflows_too(tmp_path):
    readings = run(tmp_path, lambda k, s: sustained(k, s, "angry"))
    assert max(readings) > GATE and readings[0] < GATE


def test_ordinary_joy_is_not_an_overflow(tmp_path):
    """La joie est son état normal : huit tours contents ne la « débordent » pas."""
    readings = run(tmp_path, lambda k, s: sustained(k, s, "happy"))
    assert max(readings) < 0.45, readings


def test_an_hour_of_banal_chat_never_overflows(tmp_path):
    cycle = [("curious", 0.5), ("amused", 0.6), ("thinking", 0.4), ("frustrated", 0.5), ("happy", 0.7),
             ("surprised", 0.5), ("nostalgic", 0.4), ("sad", 0.5), ("hopeful", 0.6), ("playful", 0.7)]

    async def scenario(kernel, script):
        peak = 0.0
        for i in range(60):
            emotion, force = cycle[i % len(cycle)]
            await turn(kernel, script, "user_1", emotion, force)
            peak = max(peak, overflow(kernel))
            await asyncio.sleep(60)
        return peak

    assert run(tmp_path, scenario) < GATE


# ── Balise : ce qu'elle déclare, et seulement ce qu'elle déclare ──────────


def test_no_tag_moves_nothing_and_explicit_neutral_does(tmp_path):
    async def scenario(kernel, script):
        await turn(kernel, script, "user_1", "angry", 0.8)
        angry = stance(kernel, "user_1").position
        await turn(kernel, script, "user_1", None, 0)  # pas de balise
        untouched = stance(kernel, "user_1").position
        await turn(kernel, script, "user_1", "neutral", 0.8)
        calmed = stance(kernel, "user_1").position
        return angry, untouched, calmed

    angry, untouched, calmed = run(tmp_path, scenario)
    # seul le temps a passé entre les deux premières lectures (quelques ms)
    assert A.distance(angry, untouched) < 1e-3
    assert A.norm(calmed) < A.norm(angry) - 0.1  # une impulsion vers l'origine


def test_unknown_emotion_name_is_no_impulse(tmp_path):
    async def scenario(kernel, script):
        before = kernel.mind.root.slices["affect"]
        script.tag = "[EMOTION:hangry:0.9]"
        p = await kernel.perceive(said("user_1", "hmm"))
        await p.reply
        return before, kernel.mind.root.slices["affect"]

    before, after = run(tmp_path, scenario)
    assert before == after


def test_what_she_just_declared_is_what_the_prompt_says(tmp_path):
    """La position n'a fait qu'une partie du chemin : son plus proche voisin
    serait souvent une troisième émotion. Le prompt dit la balise."""
    async def scenario(kernel, script):
        await turn(kernel, script, "user_1", "embarrassed", 0.8)
        return stance(kernel, "user_1")

    s = run(tmp_path, scenario)
    assert s.declared is not None and s.declared.emotion is Emotion.EMBARRASSED


def test_escalation_saturates_below_the_anchor(tmp_path):
    async def scenario(kernel, script):
        norms = []
        for _ in range(12):
            await turn(kernel, script, "user_1", "angry", 0.8)
            norms.append(A.norm(stance(kernel, "user_1").position))
            await asyncio.sleep(30)
        return norms

    norms = run(tmp_path, scenario)
    assert norms[3] > norms[0]
    assert max(norms) <= A.norm(A.ANCHORS[Emotion.ANGRY]) + 1e-9


# ── Retour au calme : lisible à 5 min, presque effacé à 30 min ─────────────


def test_a_flare_is_still_readable_at_5_min_and_mostly_gone_at_30(tmp_path):
    async def scenario(kernel, script):
        await turn(kernel, script, "user_1", "angry", 0.8)
        s0 = stance(kernel, "user_1")
        start = A.distance(s0.position, s0.home)
        out = {}
        for minutes in (5, 30):
            await asyncio.sleep(minutes * 60 - sum(m * 60 for m in out))
            s = stance(kernel, "user_1")
            out[minutes] = A.distance(s.position, s.home) / start
        return out

    residual = run(tmp_path, scenario)
    assert residual[5] >= 0.5, residual
    assert residual[30] <= 0.10, residual


def test_warmth_comes_back_on_the_next_turn(tmp_path):
    """Après une dispute, une réconciliation se dit dès le tour suivant."""
    async def scenario(kernel, script):
        for _ in range(3):
            await turn(kernel, script, "user_1", "angry", 0.8)
            await asyncio.sleep(60)
        await turn(kernel, script, "user_1", "happy", 0.8)
        return stance_prose(kernel, "user_1")

    line = run(tmp_path, scenario)
    assert line.startswith("Envers cette personne, tu te sens") and "contente" in line.splitlines()[0]


# ── Une posture par personne ──────────────────────────────────────────────


def test_anger_at_one_person_leaves_the_others_untouched(tmp_path):
    async def scenario(kernel, script):
        for _ in range(6):
            await turn(kernel, script, "user_9", "angry", 0.9, "t'es nulle")
            await asyncio.sleep(60)
        return stance(kernel, "user_9"), stance(kernel, "user_2")

    troll, alice = run(tmp_path, scenario)
    assert A.valence(troll.declared.emotion) < 0
    assert alice.at_rest and alice.declared is None and alice.anchor is None


def test_contagion_zero_means_her_mood_never_moves(tmp_path):
    doc = _doc(contagion=0.0)

    async def scenario(kernel, script):
        await sustained(kernel, script, "sad", n=6)
        return overflow(kernel)

    assert run(tmp_path, scenario, doc=doc) < 0.02


# ── Une rancune s'émousse ─────────────────────────────────────────────────


def test_a_grudge_is_still_there_the_next_day_and_gone_two_weeks_later(tmp_path):
    async def scenario(kernel, script):
        for _ in range(6):
            await turn(kernel, script, "user_1", "frustrated", 0.8)
            await asyncio.sleep(120)
        await asyncio.sleep(DAY / 1e6)
        next_day = stance_prose(kernel, "user_1")
        await asyncio.sleep(14 * DAY / 1e6)
        later = stance_prose(kernel, "user_1")
        return next_day, later

    next_day, later = run(tmp_path, scenario)
    assert "ton fond est plutôt" in next_day
    assert any(A.FR[e] in next_day for e in Emotion if A.valence(e) < 0)
    assert later == ""


# ── Physique : exacte, indépendante du moment où on la lit ────────────────


def _cw() -> ph.Clockwork:
    return ph.Clockwork(PARIS, circadian.DEFAULT)


def test_reading_in_one_jump_or_many_steps_is_the_same_across_phase_changes():
    p = DEFAULT
    cw = _cw()
    t0 = at_paris(2026, 9, 28, 17, 30)  # traverse le début du soir (18 h)
    osc = ph.Osc(A.to_pad(Emotion.SAD, 0.8), (0.0, 0.0, 0.0), t0)
    one = ph.advance_mood(osc, t0 + 2 * HOUR, p, cw)
    many = osc
    for k in range(1, 25):
        many = ph.advance_mood(many, t0 + k * 5 * MINUTE, p, cw)
    assert A.distance(one.position, many.position) < 1e-9


def test_stance_with_a_healing_anchor_is_step_independent():
    p = DEFAULT
    cw = _cw()
    t0 = at_paris(2026, 9, 28, 22, 0)
    st = ph.Stance(ph.Osc(A.to_pad(Emotion.ANGRY, 0.7), (0.0, 0.0, 0.0), t0), anchor=A.to_pad(Emotion.ANGRY, 0.4))
    one = ph.advance_stance(st, t0 + 6 * HOUR, p, cw)
    many = st
    for k in range(1, 73):
        many = ph.advance_stance(many, t0 + k * 5 * MINUTE, p, cw)
    assert A.distance(one.osc.position, many.osc.position) < 1e-9
    assert A.distance(one.anchor, many.anchor) < 1e-12


def test_resonance_amplifies_only_what_matches_the_background():
    sad = A.to_pad(Emotion.SAD, 0.8)
    happy = A.to_pad(Emotion.HAPPY, 0.8)
    melancholic = derive(Temperament(background=Emotion.MELANCHOLIC))
    neutral = derive(Temperament(background=Emotion.NEUTRAL))
    assert ph.resonant_gain(sad, melancholic) > ph.resonant_gain(sad, neutral)
    assert ph.resonant_gain(happy, melancholic) == pytest.approx(melancholic.person_gain)  # jamais d'armure
    assert ph.resonant_gain(sad, neutral) == pytest.approx(neutral.person_gain)  # un fond neutre ne résonne pas


def test_resilience_shortens_the_return_to_calm():
    slow = derive(Temperament(resilience=0.2))
    fast = derive(Temperament(resilience=0.8))
    assert fast.person.tau_s < 0.6 * slow.person.tau_s


def _doc(**temperament):
    from tests.fixtures.mika import DOC

    return DOC.model_copy(update={"temperament": DOC.temperament.model_copy(update=temperament)})
