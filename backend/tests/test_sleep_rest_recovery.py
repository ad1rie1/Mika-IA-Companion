"""Tests for sleep restoring the REST drive.

Before this, REST was write-only: it grew with activity, gated falling
asleep, but nothing ever relieved it — Mika woke up as tired as she fell
asleep. Sleep now drains it, with entry/stay hysteresis so the draining
doesn't bounce her awake mid-night.
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest

from memory.sleep import SLEEP_REST_RECOVERY, SleepCycle


@pytest.mark.asyncio
class TestEligibilityHysteresis:

    async def test_entry_requires_rest_tension(self):
        """Falling asleep still requires having earned the rest."""
        from drives.engine import drive_engine
        from drives.state import DriveKind

        drive_engine.reset()
        drive_engine.states[DriveKind.REST].tension = 0.1  # fresh Mika

        with patch("conscience.engine.conscience_engine") as ce:
            ce.get_idle_seconds.return_value = 99999
            eligible = await SleepCycle._is_eligible_to_sleep(already_asleep=False)
        assert eligible is False

    async def test_staying_asleep_ignores_rest_gate(self):
        """Once asleep, a drained REST drive must not wake her up."""
        from drives.engine import drive_engine
        from drives.state import DriveKind

        drive_engine.reset()
        drive_engine.states[DriveKind.REST].tension = 0.05  # already drained

        with patch("conscience.engine.conscience_engine") as ce:
            ce.get_idle_seconds.return_value = 99999
            eligible = await SleepCycle._is_eligible_to_sleep(already_asleep=True)
        assert eligible is True

    async def test_interaction_always_wakes(self):
        """Idle gate applies even mid-sleep: someone talking wakes her."""
        with patch("conscience.engine.conscience_engine") as ce:
            ce.get_idle_seconds.return_value = 10.0
            eligible = await SleepCycle._is_eligible_to_sleep(already_asleep=True)
        assert eligible is False


@pytest.mark.asyncio
class TestRestRecoveryTick:

    async def test_sleeping_tick_relieves_rest(self):
        """A full asleep tick ends by satisfying REST, and marks the night."""
        from drives.engine import drive_engine
        from drives.state import DriveKind

        drive_engine.reset()
        drive_engine.states[DriveKind.REST].tension = 0.8

        cycle = SleepCycle()
        # Pretend the phases already ran tonight so the tick goes straight
        # through to the settle+recover tail.
        night = date(2026, 7, 26)
        cycle._last_journal_date = night
        cycle._last_dream_night = night
        cycle._dreams_this_night = 99
        cycle._last_digestion_night = night

        fake_now = datetime(2026, 7, 27, 2, 0, 0)

        class _FakeDateTime:
            @staticmethod
            def now():
                return fake_now

        with patch("memory.sleep.datetime", _FakeDateTime), \
             patch.object(SleepCycle, "_is_eligible_to_sleep",
                          new=AsyncMock(return_value=True)), \
             patch.object(SleepCycle, "_set_phase", new=AsyncMock()):
            await cycle.run_if_due()

        after = drive_engine.states[DriveKind.REST].tension
        assert after < 0.8
        assert after == pytest.approx(0.8 * (1 - 0.3 * SLEEP_REST_RECOVERY), rel=0.05)
        assert cycle._asleep_night == night

    async def test_daytime_tick_does_not_touch_rest(self):
        from drives.engine import drive_engine
        from drives.state import DriveKind

        drive_engine.reset()
        drive_engine.states[DriveKind.REST].tension = 0.8

        cycle = SleepCycle()
        fake_now = datetime(2026, 7, 27, 14, 0, 0)

        class _FakeDateTime:
            @staticmethod
            def now():
                return fake_now

        with patch("memory.sleep.datetime", _FakeDateTime), \
             patch.object(SleepCycle, "_set_phase", new=AsyncMock()):
            await cycle.run_if_due()

        # No sleep → no recovery (only natural decay applies, negligible here)
        assert drive_engine.states[DriveKind.REST].tension == pytest.approx(0.8, abs=0.01)
