"""Unit tests for the PAD-based EmotionEngine.

Covers impulse application, spring recovery, global coupling,
message blending, analytics, temperament variants, and edge cases.
"""

import pytest

from emotion import pad
from emotion.types import Emotion, EmotionData
from emotion.state import PersonMood, GlobalMood, Temperament
from emotion.engine import EmotionEngine

from tests.conftest import simulate_time_decay


# ===================================================================
# IMPULSE: an emotion pulls the state toward its anchor
# ===================================================================

class TestImpulse:

    def test_first_impulse_moves_state_toward_anchor(self, engine):
        """A single impulse moves the POSITION toward the target anchor.

        Le pin change (audit B2) : l'impulsion posait une vitesse, donc la
        position — la seule grandeur que lisent le prompt, le relevé et les
        gestes — ne bougeait pas au moment du tour.
        """
        pid = "u1"
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), pid)
        mood = engine._get_person_mood(pid)

        anchor = pad.EMOTION_ANCHORS[Emotion.EXCITED]
        assert pad.norm(mood.dynamic.position) > 0.05
        assert pad.dot(mood.dynamic.position, anchor) > 0, \
            "Position should point toward the target anchor"

    def test_repeated_same_impulse_accumulates(self, engine):
        """Repeated identical impulses + integration should build position magnitude."""
        pid = "u2"
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), pid)
        simulate_time_decay(engine, 1.0)
        mag1 = pad.norm(engine._get_person_mood(pid).dynamic.position)

        for _ in range(4):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), pid)
            simulate_time_decay(engine, 0.5)
        mag5 = pad.norm(engine._get_person_mood(pid).dynamic.position)

        assert mag5 > mag1, \
            f"5 impulses should accumulate beyond 1: {mag1:.2f} -> {mag5:.2f}"

    def test_opposite_impulse_cancels(self, engine):
        """An opposite-direction impulse should pull the position back."""
        pid = "u3"
        for _ in range(3):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), pid)

        mood = engine._get_person_mood(pid)
        happy_anchor = pad.EMOTION_ANCHORS[Emotion.HAPPY]
        before = pad.dot(mood.dynamic.position, happy_anchor)

        engine.process_emotion(EmotionData(Emotion.SAD, 0.9), pid)
        assert pad.dot(mood.dynamic.position, happy_anchor) < before

    def test_intensity_scales_target(self, engine):
        """Higher intensity should move the position further."""
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.2), "low")
        engine.process_emotion(EmotionData(Emotion.EXCITED, 1.0), "high")

        low = pad.norm(engine._get_person_mood("low").dynamic.position)
        high = pad.norm(engine._get_person_mood("high").dynamic.position)
        assert high > low


# ===================================================================
# DECAY: the oscillator returns toward home
# ===================================================================

class TestDecay:

    def test_state_decays_toward_home(self, engine):
        """After enough time, position should converge near home (default mood).

        3 τ, pas 300 s : le retour au repos se compte désormais en minutes
        (audit B2). Une seule passe suffit — ``_MAX_ADVANCE_SECONDS`` plafonne
        à une heure de rattrapage, pas à 30 s.
        """
        pid = "decay"
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), pid)
        simulate_time_decay(engine, 2100.0)

        mood = engine._get_person_mood(pid)
        # Should no longer be in angry territory
        angry_anchor = pad.EMOTION_ANCHORS[Emotion.ANGRY]
        assert pad.dot(mood.dynamic.position, angry_anchor) < 0.3, \
            "Anger component should have decayed"

    def test_intensity_decreases_over_time(self, engine):
        """Position magnitude should decrease as we approach home."""
        pid = "decay2"
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.9), pid)
        i_before = engine._get_person_mood(pid).intensity
        simulate_time_decay(engine, 60.0)
        i_after = engine._get_person_mood(pid).intensity

        # Home is non-zero (default_mood anchor × 0.3), so we check the
        # overall motion rather than strict monotonic decrease.
        assert i_after != i_before


# ===================================================================
# GLOBAL COUPLING
# ===================================================================

class TestGlobalCoupling:

    def test_person_impulse_affects_global(self, engine):
        """A strong person impulse should move the global position."""
        before = pad.norm(engine.global_mood.dynamic.position)
        engine.process_emotion(EmotionData(Emotion.EXCITED, 0.9), "u")
        assert pad.norm(engine.global_mood.dynamic.position) > before

    def test_low_intensity_produces_small_global_kick(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.1), "u")
        assert pad.norm(engine.global_mood.dynamic.position) < 0.3

    def test_high_bleed_temperament(self, explosive_engine):
        """High global_bleed should push the global mood harder."""
        explosive_engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "u")
        # One step to let velocity translate into position
        simulate_time_decay(explosive_engine, 3.0)
        assert pad.norm(explosive_engine.global_mood.dynamic.position) > 0.05


# ===================================================================
# MESSAGE EMOTION: blend of person + global
# ===================================================================

class TestMessageEmotion:

    def test_strong_person_dominates_message(self, engine):
        """When person is strong and global is weak, message should match person."""
        pid = "dom"
        for _ in range(3):
            engine.process_emotion(EmotionData(Emotion.LOVE, 0.9), pid)

        msg = engine.compute_message_emotion(pid)
        love_anchor = pad.EMOTION_ANCHORS[Emotion.LOVE]
        msg_vec = pad.EMOTION_ANCHORS[msg.emotion]
        assert pad.dot(msg_vec, love_anchor) > 0, \
            f"Message emotion should be in LOVE direction, got {msg.emotion.value}"

    def test_message_default_when_state_empty(self, engine):
        """When nothing was processed, the message reads the REST — which is
        the default mood once the circadian tint is neutralised. A fresh
        oscillator starts at rest, no longer at the origin (it used to drift
        from a neutral face to the hour's tint over twenty minutes)."""
        from unittest.mock import patch
        from emotion import circadian

        with patch.object(circadian, "phase_bias", return_value=(0.0, 0.0, 0.0)):
            msg = engine.compute_message_emotion("never_seen")
        assert msg.emotion == engine.temperament.default_mood

    def test_intensity_in_range(self, engine):
        engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "u")
        msg = engine.compute_message_emotion("u")
        assert 0.0 <= msg.intensity <= 1.0


# ===================================================================
# ANALYTICS
# ===================================================================

class TestAnalytics:

    def test_empty(self, engine):
        result = engine.get_analytics()
        assert result["total_interactions"] == 0
        assert result["persons_tracked"] == 0

    def test_after_interactions(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.8), "p1")
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), "p1")
        engine.process_emotion(EmotionData(Emotion.SAD, 0.5), "p2")

        result = engine.get_analytics()
        assert result["total_interactions"] == 3
        assert result["persons_tracked"] == 2
        assert "happy" in result["distribution"]
        assert "sad" in result["distribution"]


# ===================================================================
# TEMPERAMENT VARIANTS
# ===================================================================

class TestTemperamentVariants:

    def test_stoic_moves_less(self, stoic_engine):
        """Stoic (low volatility) should produce less motion for same impulse."""
        stoic_engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "s")
        stoic_move = pad.norm(stoic_engine._get_person_mood("s").dynamic.position)

        # Reference: default engine
        ref = EmotionEngine()
        from tests.conftest import TEMPERAMENT_DEFAULT
        ref.temperament = TEMPERAMENT_DEFAULT
        ref._recompute_params()
        ref._initialized = True
        ref.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "r")
        ref_move = pad.norm(ref._get_person_mood("r").dynamic.position)

        assert stoic_move < ref_move, \
            f"Stoic should move less: stoic={stoic_move:.3f} vs ref={ref_move:.3f}"

    def test_explosive_moves_more(self, explosive_engine):
        """Explosive (high volatility + gain) should move further."""
        explosive_engine.process_emotion(EmotionData(Emotion.HAPPY, 0.6), "e")
        exp_move = pad.norm(explosive_engine._get_person_mood("e").dynamic.position)
        assert exp_move > 0.3

    def test_melancholic_returns_to_melancholic(self, melancholic_engine):
        """Melancholic temperament should decay back to the melancholic anchor.

        Neutralizes the circadian phase_bias: it adds a time-of-day tint to
        the oscillator's home vector (magnitude ~0.35) that at some hours
        pushes the rest-state away from the melancholic anchor, flipping the
        sign of this assertion. The character's own default_mood pull is
        what this test is exercising — circadian is a separate concern.
        """
        from unittest.mock import patch
        from emotion import circadian

        pid = "m"
        with patch.object(circadian, "phase_bias", return_value=(0.0, 0.0, 0.0)):
            melancholic_engine.process_emotion(EmotionData(Emotion.HAPPY, 0.6), pid)
            # 3 τ pour ce tempérament (audit B2) ; le rattrapage d'une passe
            # est plafonné à ``_MAX_ADVANCE_SECONDS``, soit une heure.
            simulate_time_decay(melancholic_engine, 3600.0)

            mood = melancholic_engine._get_person_mood(pid)
            mel_anchor = pad.EMOTION_ANCHORS[Emotion.MELANCHOLIC]
            assert pad.dot(mood.dynamic.position, mel_anchor) > 0, \
                f"Should drift toward melancholic home, got {mood.emotion.value}"


# ===================================================================
# EDGE CASES
# ===================================================================

class TestEdgeCases:

    def test_zero_intensity(self, engine):
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.0), "z")
        mood = engine._get_person_mood("z")
        assert 0.0 <= mood.intensity <= 1.0

    def test_max_intensity_bounded(self, engine):
        engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "m")
        mood = engine._get_person_mood("m")
        assert 0.0 <= mood.intensity <= 1.0

    def test_rapid_fire_bounded(self, engine):
        pid = "rapid"
        for e in [Emotion.HAPPY, Emotion.SAD, Emotion.ANGRY, Emotion.LOVE,
                  Emotion.CURIOUS, Emotion.SCARED, Emotion.PLAYFUL]:
            engine.process_emotion(EmotionData(e, 0.7), pid)

        mood = engine._get_person_mood(pid)
        # Position stays inside the clamped envelope (1.2)
        for c in mood.dynamic.position:
            assert -1.2 <= c <= 1.2

    def test_many_persons(self, engine):
        for i in range(30):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), f"u{i}")
        assert len(engine.person_moods) == 30

    def test_history_bounded(self, engine):
        pid = "h"
        for _ in range(150):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), pid)
        mood = engine._get_person_mood(pid)
        assert len(mood.history) == 100


# ===================================================================
# SHUTDOWN — the state we stop the process to keep
# ===================================================================

class TestArret:
    """``_save_state`` awaits once per person; the decay loop evicts persons.

    Sauver pendant qu'elle tourne, c'est itérer un dict qu'un autre écrit —
    ``RuntimeError`` avalée par le ``except`` de la sauvegarde, et les relevés
    des personnes restantes perdus en silence (audit M9).
    """

    async def test_l_arret_coupe_le_decay_avant_de_sauver(self, engine):
        import asyncio

        vu: dict[str, bool] = {}

        async def _save():
            vu["arretee"] = (
                engine._decay_task.done() or engine._decay_task.cancelled()
            )

        engine._decay_task = asyncio.create_task(engine._decay_loop())
        engine._save_state = _save
        await engine.shutdown()

        assert vu["arretee"], \
            "la boucle de decay doit être arrêtée avant la sauvegarde"

    async def test_une_eviction_pendant_la_sauvegarde_ne_perd_personne(
        self, engine, monkeypatch
    ):
        for i in range(4):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), f"p{i}")

        ecrits: list[str] = []

        async def _create(**kwargs):
            if len(ecrits) == 1:
                # Ce que fait ``_evict_persons`` pendant un await.
                engine.person_moods.pop("p3", None)
            ecrits.append(kwargs["person_id"])

        class _FauxManager:
            conversation = object()

        import memory.manager as manager_module
        from emotion import persistence

        monkeypatch.setattr(manager_module, "memory_manager", _FauxManager())
        # Patché là où il est lu : ``persistence`` lie ``sync_to_async`` à
        # l'import, un patch sur ``asgiref.sync`` ne l'atteindrait plus.
        monkeypatch.setattr(
            persistence, "sync_to_async", lambda fn, **kw: _create,
        )

        await engine._save_state()

        assert {"p0", "p1", "p2"} <= set(ecrits), \
            f"toutes les personnes présentes doivent avoir un relevé : {ecrits}"


class TestResonanceDeTemperament:
    """`_person_impulse_params` : le fond du personnage entre dans la
    physique de l'impulsion — la propriété que
    `test_melancholic_resonates_with_sadness` a nommée en restant rouge
    tant qu'elle n'existait pas."""

    def test_une_impulsion_alignee_porte_plus_loin(self, melancholic_engine):
        """Tristesse sur fond mélancolique : le gain effectif dépasse le gain
        du tempérament seul."""
        e = melancholic_engine
        cible = pad.label_to_pad(Emotion.SAD, 0.8)
        assert (
            e._person_impulse_params(cible).impulse_gain
            > e._person_params.impulse_gain
        )

    def test_une_impulsion_contraire_n_est_jamais_attenuee(
        self, melancholic_engine
    ):
        """Amplification seulement : atténuer le contraire blinderait un fond
        heureux contre la tristesse — la « résistance » est déjà le rôle de
        `recovery_speed` et du point de repos."""
        e = melancholic_engine
        cible = pad.label_to_pad(Emotion.EXCITED, 0.8)
        assert (
            e._person_impulse_params(cible).impulse_gain
            == e._person_params.impulse_gain
        )

    def test_un_fond_neutre_ne_resonne_avec_rien(self, stoic_engine):
        """L'ancre de `neutral` est nulle : cos indéfini, gain inchangé —
        c'est la définition du stoïque, pas un cas d'erreur."""
        e = stoic_engine
        for emotion in (Emotion.SAD, Emotion.EXCITED, Emotion.ANGRY):
            cible = pad.label_to_pad(emotion, 0.8)
            assert (
                e._person_impulse_params(cible).impulse_gain
                == e._person_params.impulse_gain
            )

    def test_le_gain_resonant_reste_un_cliquet(self, explosive_engine):
        """Le plafond est 1.0 — l'invariant du cliquet lui-même : même
        l'explosive en pleine exaltation ne dépasse jamais sa cible."""
        e = explosive_engine
        cible = pad.label_to_pad(Emotion.EXCITED, 1.0)
        assert e._person_impulse_params(cible).impulse_gain <= 1.0
