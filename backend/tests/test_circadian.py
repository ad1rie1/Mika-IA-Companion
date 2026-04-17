"""Tests for the circadian rhythm module.

Circadian functions are pure (no state, no IO) so we can pass any
datetime to check phase/bias/energy at arbitrary hours. No mocking of
wall clock needed — we just construct `datetime(...)` inline.

Also covers:
  - Integration with EmotionEngine._home_vector (bias added to home)
  - DriveEngine.energy_level() aggregation (circadian + REST)
  - Conscience scoring Factor 11 (fatigue penalty)
  - System prompt block injection
  - personality.yaml → CircadianProfile parsing
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from emotion import circadian, pad
from emotion.circadian import (
    CircadianPhase, CircadianProfile, current_phase, current_state,
    energy_level, phase_bias, phase_description_fr, profile_from_yaml,
)
from emotion.types import Emotion


# ─────────────────────────────────────────────────────────────────
# current_phase
# ─────────────────────────────────────────────────────────────────

class TestCurrentPhase:

    def test_morning_starts_at_default_hour(self):
        assert current_phase(datetime(2026, 4, 17, 6, 0)) is CircadianPhase.MORNING
        assert current_phase(datetime(2026, 4, 17, 10, 30)) is CircadianPhase.MORNING

    def test_afternoon(self):
        assert current_phase(datetime(2026, 4, 17, 12, 0)) is CircadianPhase.AFTERNOON
        assert current_phase(datetime(2026, 4, 17, 17, 59)) is CircadianPhase.AFTERNOON

    def test_evening(self):
        assert current_phase(datetime(2026, 4, 17, 18, 0)) is CircadianPhase.EVENING
        assert current_phase(datetime(2026, 4, 17, 22, 45)) is CircadianPhase.EVENING

    def test_night_including_pre_dawn(self):
        assert current_phase(datetime(2026, 4, 17, 23, 15)) is CircadianPhase.NIGHT
        assert current_phase(datetime(2026, 4, 17, 2, 0)) is CircadianPhase.NIGHT
        assert current_phase(datetime(2026, 4, 17, 5, 59)) is CircadianPhase.NIGHT

    def test_profile_override_shifts_phases(self):
        """A nocturnal character: night starts early, morning starts at 10h."""
        noctambule = CircadianProfile(
            phase_hours={
                CircadianPhase.MORNING: 10,
                CircadianPhase.AFTERNOON: 14,
                CircadianPhase.EVENING: 20,
                CircadianPhase.NIGHT: 0,
            }
        )
        assert current_phase(datetime(2026, 4, 17, 6, 0), noctambule) is CircadianPhase.NIGHT
        assert current_phase(datetime(2026, 4, 17, 10, 0), noctambule) is CircadianPhase.MORNING


# ─────────────────────────────────────────────────────────────────
# phase_bias
# ─────────────────────────────────────────────────────────────────

class TestPhaseBias:

    def test_default_morning_bias_is_hopeful(self):
        bias = phase_bias(CircadianPhase.MORNING)
        expected = pad.label_to_pad(Emotion.HOPEFUL, 0.35)
        assert bias == expected

    def test_custom_anchor_overrides(self):
        grumpy_morning = CircadianProfile(
            phase_anchors={
                CircadianPhase.MORNING: Emotion.BORED,
                CircadianPhase.AFTERNOON: Emotion.PLAYFUL,
                CircadianPhase.EVENING: Emotion.RELIEVED,
                CircadianPhase.NIGHT: Emotion.DREAMY,
            }
        )
        bias = phase_bias(CircadianPhase.MORNING, grumpy_morning)
        assert bias == pad.label_to_pad(Emotion.BORED, 0.35)

    def test_bias_magnitude_bounded(self):
        """Bias must stay small so it doesn't override default_mood."""
        for phase in CircadianPhase:
            bias = phase_bias(phase)
            magnitude = pad.norm(bias)
            # anchor × 0.35 — always ≤ 0.35 × ~1.3 (furthest anchor)
            assert magnitude <= 0.5


# ─────────────────────────────────────────────────────────────────
# energy_level
# ─────────────────────────────────────────────────────────────────

class TestEnergyLevel:

    def test_peak_hour_produces_maximum(self):
        """At 14h (default peak), energy must be at its highest."""
        peak = energy_level(datetime(2026, 4, 17, 14, 0))
        noon = energy_level(datetime(2026, 4, 17, 12, 0))
        morning = energy_level(datetime(2026, 4, 17, 8, 0))
        assert peak > noon >= morning

    def test_trough_at_opposite_of_peak(self):
        """Trough is 12h after the peak — default 14h peak ⇒ 2h trough."""
        peak = energy_level(datetime(2026, 4, 17, 14, 0))
        trough = energy_level(datetime(2026, 4, 18, 2, 0))
        assert trough < peak
        # With default amplitude 0.7, trough should be close to 0.2
        assert trough < 0.3

    def test_clamped_to_unit(self):
        """No pathological profile should push energy outside [0, 1]."""
        extreme = CircadianProfile(
            energy_amplitude=3.0,
            energy_baseline=0.5,
        )
        for hour in range(24):
            e = energy_level(datetime(2026, 4, 17, hour, 0), extreme)
            assert 0.0 <= e <= 1.0

    def test_custom_peak_hour_shifts_curve(self):
        """A nocturnal character peaks late evening."""
        night_owl = CircadianProfile(energy_peak_hour=22.0)
        at_peak = energy_level(datetime(2026, 4, 17, 22, 0), night_owl)
        at_morning = energy_level(datetime(2026, 4, 17, 8, 0), night_owl)
        assert at_peak > at_morning

    def test_fractional_hour_smooth(self):
        """Energy is continuous: 14:00 and 14:30 differ but slightly."""
        e14 = energy_level(datetime(2026, 4, 17, 14, 0))
        e1430 = energy_level(datetime(2026, 4, 17, 14, 30))
        assert abs(e14 - e1430) < 0.05


# ─────────────────────────────────────────────────────────────────
# current_state + description
# ─────────────────────────────────────────────────────────────────

class TestCurrentState:

    def test_state_bundles_all_info(self):
        state = current_state(datetime(2026, 4, 17, 14, 0))
        assert state.phase is CircadianPhase.AFTERNOON
        assert state.hour == 14
        assert 0.0 <= state.energy <= 1.0
        assert state.bias_anchor is Emotion.PLAYFUL


class TestPhaseDescription:

    def test_french_description_mentions_hour_and_phase(self):
        state = current_state(datetime(2026, 4, 17, 23, 30))
        text = phase_description_fr(state)
        assert "23h" in text
        assert "nuit" in text

    def test_energy_descriptor_matches_level(self):
        high = current_state(datetime(2026, 4, 17, 14, 0))
        low = current_state(datetime(2026, 4, 17, 3, 0))
        assert "%" in phase_description_fr(high)
        assert "%" in phase_description_fr(low)
        # High should carry a stronger descriptor than low
        high_text = phase_description_fr(high).lower()
        low_text = phase_description_fr(low).lower()
        assert "haute" in high_text or "bonne" in high_text
        assert "basse" in low_text or "moyenne" in low_text


# ─────────────────────────────────────────────────────────────────
# YAML parsing
# ─────────────────────────────────────────────────────────────────

class TestProfileFromYaml:

    def test_empty_dict_gives_default_profile(self):
        p = profile_from_yaml({})
        assert p.phase_anchors[CircadianPhase.MORNING] is Emotion.HOPEFUL
        assert p.energy_peak_hour == 14.0

    def test_partial_override(self):
        p = profile_from_yaml({
            "energy_peak_hour": 22.0,
            "phase_anchors": {"morning": "bored"},
        })
        assert p.energy_peak_hour == 22.0
        assert p.phase_anchors[CircadianPhase.MORNING] is Emotion.BORED
        # Other anchors kept at defaults
        assert p.phase_anchors[CircadianPhase.AFTERNOON] is Emotion.PLAYFUL

    def test_invalid_emotion_is_ignored(self):
        p = profile_from_yaml({"phase_anchors": {"morning": "not_an_emotion"}})
        assert p.phase_anchors[CircadianPhase.MORNING] is Emotion.HOPEFUL

    def test_phase_hours_clamped_mod_24(self):
        p = profile_from_yaml({"phase_hours": {"morning": 30}})
        assert p.phase_hours[CircadianPhase.MORNING] == 6  # 30 % 24


# ─────────────────────────────────────────────────────────────────
# EmotionEngine._home_vector integration
# ─────────────────────────────────────────────────────────────────

class TestHomeVectorBias:

    def test_home_shifts_between_morning_and_night(self, engine):
        """_home_vector must differ across phases because the bias does."""
        # Morning → hopeful bias (positive valence + mid arousal)
        with patch("emotion.circadian.current_state") as cs, \
             patch("emotion.circadian.phase_bias") as pb:
            cs.return_value = circadian.CircadianState(
                phase=CircadianPhase.MORNING, hour=8,
                energy=0.7, bias_anchor=Emotion.HOPEFUL,
            )
            pb.return_value = pad.label_to_pad(Emotion.HOPEFUL, 0.35)
            morning_home = engine._home_vector()

        # Night → dreamy bias (negative arousal)
        with patch("emotion.circadian.current_state") as cs, \
             patch("emotion.circadian.phase_bias") as pb:
            cs.return_value = circadian.CircadianState(
                phase=CircadianPhase.NIGHT, hour=2,
                energy=0.25, bias_anchor=Emotion.DREAMY,
            )
            pb.return_value = pad.label_to_pad(Emotion.DREAMY, 0.35)
            night_home = engine._home_vector()

        assert morning_home != night_home
        # Valence or arousal should differ meaningfully
        assert abs(morning_home[1] - night_home[1]) > 0.1 or \
               abs(morning_home[0] - night_home[0]) > 0.1

    def test_home_still_carries_default_mood(self, engine):
        """Bias is a nudge, not a replacement — default_mood must influence home."""
        default_contribution = pad.label_to_pad(engine.temperament.default_mood, 0.15)
        with patch("emotion.circadian.current_state") as cs, \
             patch("emotion.circadian.phase_bias") as pb:
            cs.return_value = circadian.CircadianState(
                phase=CircadianPhase.AFTERNOON, hour=14,
                energy=0.8, bias_anchor=Emotion.PLAYFUL,
            )
            pb.return_value = (0.0, 0.0, 0.0)  # zero bias → home = pure default
            home = engine._home_vector()

        assert home == default_contribution


# ─────────────────────────────────────────────────────────────────
# DriveEngine.energy_level integration
# ─────────────────────────────────────────────────────────────────

class TestDriveEnergy:

    def test_energy_in_unit_range(self):
        from drives.engine import DriveEngine
        e = DriveEngine()
        for _ in range(3):
            level = e.energy_level()
            assert 0.0 <= level <= 1.0

    def test_high_rest_tension_lowers_energy(self):
        """REST tension = fatigue. Two engines at the same hour must differ
        when one has accumulated fatigue."""
        from drives.engine import DriveEngine
        from drives.state import DriveKind

        fresh = DriveEngine()
        tired = DriveEngine()
        tired.states[DriveKind.REST].tension = 0.9

        # Patch circadian to a fixed value so only REST differs.
        with patch("emotion.circadian.energy_level", return_value=0.6):
            fresh_e = fresh.energy_level()
            tired_e = tired.energy_level()

        assert fresh_e > tired_e

    def test_circadian_night_lowers_energy(self):
        """At a low-circadian moment energy should drop even without REST."""
        from drives.engine import DriveEngine

        e = DriveEngine()
        with patch("emotion.circadian.energy_level", return_value=0.9):
            daytime = e.energy_level()
        with patch("emotion.circadian.energy_level", return_value=0.15):
            nighttime = e.energy_level()
        assert nighttime < daytime


# ─────────────────────────────────────────────────────────────────
# Conscience scoring: fatigue penalty
# ─────────────────────────────────────────────────────────────────

class TestScoringFatiguePenalty:

    def test_high_energy_no_penalty(self):
        from conscience.scoring import compute_decision_score
        from datetime import date
        from conscience.types import DecisionContext
        ctx = DecisionContext(
            pending_observations=[], global_mood="happy", global_intensity=0.0,
            idle_seconds=0, in_cooldown=False, max_pertinence=0.8,
            weighted_urgency=0.0, energy=0.8,
        )
        greeted = {"morning", "evening", "night"}
        score, reason, _, _ = compute_decision_score(ctx, 0.5, greeted, date.today())
        assert "fatigue" not in reason

    def test_low_energy_subtracts(self):
        from conscience.scoring import compute_decision_score
        from datetime import date
        from conscience.types import DecisionContext
        ctx_fresh = DecisionContext(
            pending_observations=[], global_mood="happy", global_intensity=0.0,
            idle_seconds=0, in_cooldown=False, max_pertinence=0.8,
            weighted_urgency=0.0, energy=0.9,
        )
        ctx_tired = DecisionContext(
            pending_observations=[], global_mood="happy", global_intensity=0.0,
            idle_seconds=0, in_cooldown=False, max_pertinence=0.8,
            weighted_urgency=0.0, energy=0.1,
        )
        greeted = {"morning", "evening", "night"}
        today = date.today()
        s_fresh, _, _, _ = compute_decision_score(ctx_fresh, 0.5, greeted, today)
        s_tired, reason_tired, _, _ = compute_decision_score(ctx_tired, 0.5, greeted, today)
        assert s_tired < s_fresh
        assert "fatigue" in reason_tired

    def test_fatigue_penalty_capped(self):
        """Even at energy=0 the fatigue penalty is capped at -0.25."""
        from conscience.scoring import compute_decision_score
        from datetime import date
        from conscience.types import DecisionContext
        ctx = DecisionContext(
            pending_observations=[], global_mood="happy", global_intensity=0.0,
            idle_seconds=0, in_cooldown=False, max_pertinence=0.0,
            weighted_urgency=0.0, energy=0.0,
        )
        greeted = {"morning", "evening", "night"}
        score, _, _, _ = compute_decision_score(ctx, 0.5, greeted, date.today())
        assert score >= -0.25 - 0.01


# ─────────────────────────────────────────────────────────────────
# System prompt block
# ─────────────────────────────────────────────────────────────────

class TestCircadianPromptBlock:

    def test_build_system_prompt_includes_block(self):
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(
            circadian_context="Il est 14h. En phase apres-midi, ton energie est haute (85%).",
        )
        assert "TON RYTHME" in prompt
        assert "14h" in prompt
        assert "apres-midi" in prompt

    def test_build_system_prompt_omits_when_empty(self):
        from pipeline.prompt import build_system_prompt
        prompt = build_system_prompt(circadian_context="")
        assert "TON RYTHME" not in prompt


# ─────────────────────────────────────────────────────────────────
# Inner state broadcast
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestInnerStateCircadian:

    async def test_circadian_block_in_snapshot(self):
        from pipeline.broadcast import _collect_inner_state
        state = await _collect_inner_state(person_id=None)
        assert "circadian" in state
        assert state["circadian"]["phase"] in (
            "morning", "afternoon", "evening", "night",
        )
        assert 0 <= state["circadian"]["hour"] <= 23
        assert 0.0 <= state["circadian"]["energy"] <= 1.0

    async def test_energy_field_at_root_of_snapshot(self):
        from pipeline.broadcast import _collect_inner_state
        state = await _collect_inner_state(person_id=None)
        assert "energy" in state
        assert 0.0 <= state["energy"] <= 1.0


# ─────────────────────────────────────────────────────────────────
# personality.yaml integration
# ─────────────────────────────────────────────────────────────────

class TestPersonalityCircadianProfile:

    def test_personality_exposes_circadian_profile(self):
        from config.personality import personality
        profile = personality.circadian_profile
        # Values come from the shipped personality.yaml — anchors match the
        # defaults we picked (hopeful/playful/relieved/dreamy).
        assert profile.phase_anchors[CircadianPhase.MORNING] is Emotion.HOPEFUL
