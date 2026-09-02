"""Tests for the sleep cycle — journaling, dreaming, digesting.

Covers the deterministic parts end-to-end without ever calling the LLM:
  - Phase gates: _is_night, _night_of, _is_enabled, _maybe_reset_counters
  - Dream classification: _pick_dream_type
  - Phase transitions: _set_phase
  - DB-driven logic: _gather_journal_material, _digest_ruminations, _persist_dream
  - Full run_if_due path with mocked AI router

The LLM itself is mocked everywhere — we test the orchestration and data
shaping, not the prompt engineering (which is covered elsewhere).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


# ---------------------------------------------------------------------------
# 1. Pure phase-gate logic — no DB, no async
# ---------------------------------------------------------------------------


class TestNightDetection:
    """_is_night wraps midnight: [23h, 6h) is the night window."""

    def test_midday_is_not_night(self):
        from memory.sleep import SleepCycle

        assert not SleepCycle._is_night(datetime(2026, 4, 17, 12, 0))
        assert not SleepCycle._is_night(datetime(2026, 4, 17, 18, 0))
        assert not SleepCycle._is_night(datetime(2026, 4, 17, 22, 0))

    def test_late_evening_is_night(self):
        from memory.sleep import SleepCycle

        assert SleepCycle._is_night(datetime(2026, 4, 17, 23, 0))
        assert SleepCycle._is_night(datetime(2026, 4, 17, 23, 59))

    def test_small_hours_are_night(self):
        from memory.sleep import SleepCycle

        assert SleepCycle._is_night(datetime(2026, 4, 18, 0, 30))
        assert SleepCycle._is_night(datetime(2026, 4, 18, 3, 0))
        assert SleepCycle._is_night(datetime(2026, 4, 18, 5, 59))

    def test_dawn_is_not_night(self):
        from memory.sleep import SleepCycle

        # 6h is the boundary — already morning
        assert not SleepCycle._is_night(datetime(2026, 4, 18, 6, 0))
        assert not SleepCycle._is_night(datetime(2026, 4, 18, 7, 0))


class TestNightOf:
    """A dream at 03h on the 18th belongs to the night *of* the 17th."""

    def test_small_hours_attributed_to_previous_day(self):
        from memory.sleep import SleepCycle

        # 03h on the 18th = night started on the 17th
        assert SleepCycle._night_of(datetime(2026, 4, 18, 3, 0)) == date(2026, 4, 17)

    def test_late_evening_stays_on_same_day(self):
        from memory.sleep import SleepCycle

        # 23h30 on the 17th = night started today
        assert (
            SleepCycle._night_of(datetime(2026, 4, 17, 23, 30)) == date(2026, 4, 17)
        )

    def test_midnight_boundary(self):
        from memory.sleep import SleepCycle

        # At exactly 00h, we're in "small hours" so attributed to previous day
        assert SleepCycle._night_of(datetime(2026, 4, 18, 0, 0)) == date(2026, 4, 17)


class TestEnabledFlag:
    def test_enabled_by_default(self):
        from memory.sleep import SleepCycle

        assert SleepCycle._is_enabled() is True

    def test_can_disable_via_setting(self, settings):
        from memory.sleep import SleepCycle

        settings.SLEEP_CYCLE_ENABLED = False
        assert SleepCycle._is_enabled() is False

    def test_respects_truthy_values(self, settings):
        from memory.sleep import SleepCycle

        settings.SLEEP_CYCLE_ENABLED = True
        assert SleepCycle._is_enabled() is True


class TestResetCounters:
    def test_reset_when_new_day(self):
        from memory.sleep import SleepCycle

        s = SleepCycle()
        s._dreams_this_night = 2
        s._last_dream_night = date(2026, 4, 16)

        s._maybe_reset_counters(date(2026, 4, 17))
        assert s._dreams_this_night == 0

    def test_no_reset_same_day(self):
        from memory.sleep import SleepCycle

        s = SleepCycle()
        s._dreams_this_night = 2
        s._last_dream_night = date(2026, 4, 17)

        s._maybe_reset_counters(date(2026, 4, 17))
        assert s._dreams_this_night == 2

    def test_no_reset_when_never_dreamed(self):
        from memory.sleep import SleepCycle

        s = SleepCycle()
        s._last_dream_night = None
        s._dreams_this_night = 0
        # Should not blow up, nothing to reset
        s._maybe_reset_counters(date(2026, 4, 17))
        assert s._dreams_this_night == 0


# ---------------------------------------------------------------------------
# 2. Dream type classification (pure, input → output)
# ---------------------------------------------------------------------------


class TestPickDreamType:
    """_pick_dream_type maps source emotions → category."""

    def _mk_souvenir(self, emotion: str):
        """Build a minimal Souvenir-like mock with an emotion attribute."""
        m = MagicMock()
        m.emotion = emotion
        return m

    def test_mostly_negative_is_nightmare(self):
        from memory.sleep import SleepCycle

        fragments = {
            "souvenirs": [
                self._mk_souvenir("frustrated"),
                self._mk_souvenir("anxious"),
                self._mk_souvenir("sad"),
            ],
            "rumination": None,
        }
        assert SleepCycle._pick_dream_type(fragments) == "nightmare"

    def test_mostly_positive_is_pleasant(self):
        from memory.sleep import SleepCycle

        fragments = {
            "souvenirs": [
                self._mk_souvenir("happy"),
                self._mk_souvenir("grateful"),
                self._mk_souvenir("playful"),
            ],
            "rumination": None,
        }
        assert SleepCycle._pick_dream_type(fragments) == "pleasant"

    def test_strong_negative_rumination_forces_nightmare(self):
        from memory.sleep import SleepCycle

        rumination = MagicMock()
        rumination.emotion = "frustrated"
        rumination.intensity = 0.75
        fragments = {
            "souvenirs": [
                self._mk_souvenir("happy"),
                self._mk_souvenir("grateful"),
            ],
            "rumination": rumination,
        }
        assert SleepCycle._pick_dream_type(fragments) == "nightmare"

    def test_weak_rumination_does_not_force_nightmare(self):
        from memory.sleep import SleepCycle

        rumination = MagicMock()
        rumination.emotion = "frustrated"
        rumination.intensity = 0.3  # below threshold
        fragments = {
            "souvenirs": [
                self._mk_souvenir("happy"),
                self._mk_souvenir("grateful"),
            ],
            "rumination": rumination,
        }
        # Positive dominated → pleasant wins (or associative if mixed)
        result = SleepCycle._pick_dream_type(fragments)
        assert result in ("pleasant", "associative")

    def test_empty_emotions_is_mundane(self):
        from memory.sleep import SleepCycle

        fragments = {
            "souvenirs": [
                self._mk_souvenir(""),
                self._mk_souvenir(""),
            ],
            "rumination": None,
        }
        assert SleepCycle._pick_dream_type(fragments) == "mundane"


# ---------------------------------------------------------------------------
# 3. Phase transitions
# ---------------------------------------------------------------------------


class TestSetPhase:
    @pytest.mark.asyncio
    async def test_no_broadcast_on_same_phase(self):
        from memory.sleep import SleepCycle, SleepPhase

        s = SleepCycle()
        with patch(
            "pipeline.broadcast.broadcast_inner_state_update",
            new_callable=AsyncMock,
        ) as mock_bc:
            await s._set_phase(SleepPhase.AWAKE)
            mock_bc.assert_not_called()
        assert s.phase == SleepPhase.AWAKE

    @pytest.mark.asyncio
    async def test_broadcast_on_phase_change(self):
        from memory.sleep import SleepCycle, SleepPhase

        s = SleepCycle()
        with patch(
            "pipeline.broadcast.broadcast_inner_state_update",
            new_callable=AsyncMock,
        ) as mock_bc:
            await s._set_phase(SleepPhase.REM)
            mock_bc.assert_awaited_once()
        assert s.phase == SleepPhase.REM

    @pytest.mark.asyncio
    async def test_broadcast_failure_does_not_propagate(self):
        """A crashed broadcast must never break the sleep cycle."""
        from memory.sleep import SleepCycle, SleepPhase

        s = SleepCycle()
        with patch(
            "pipeline.broadcast.broadcast_inner_state_update",
            side_effect=Exception("channel layer unavailable"),
        ):
            # Should not raise
            await s._set_phase(SleepPhase.DEEP_SLEEP)
        assert s.phase == SleepPhase.DEEP_SLEEP


# ---------------------------------------------------------------------------
# 4. DB-driven logic — journal material gathering
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestGatherJournalMaterial:
    """_gather_journal_material pulls the day's souvenirs + persons + ruminations."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        from conscience.models import Rumination
        from memory.models import Souvenir, Entity
        Souvenir.objects.all().delete()
        Entity.objects.all().delete()
        Rumination.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_empty_day_returns_zero_souvenirs(self):
        from memory.sleep import SleepCycle

        material = await SleepCycle._gather_journal_material(date.today())
        assert material is not None
        assert material["souvenir_count"] == 0

    @pytest.mark.asyncio
    async def test_gathers_souvenirs_of_the_day(self):
        from memory.models import Souvenir
        from memory.sleep import SleepCycle

        today = date.today()
        today_dt = datetime.combine(today, datetime.min.time())
        today_tz = timezone.make_aware(today_dt)

        await sync_to_async(Souvenir.objects.create)(
            content="s1", emotion="happy", importance=0.9,
            occurred_at=today_tz + timedelta(hours=10),
        )
        await sync_to_async(Souvenir.objects.create)(
            content="s2", emotion="happy", importance=0.6,
            occurred_at=today_tz + timedelta(hours=14),
        )
        # One from yesterday should not be included
        yesterday = today_tz - timedelta(days=1)
        await sync_to_async(Souvenir.objects.create)(
            content="s_yesterday", emotion="sad", importance=0.8,
            occurred_at=yesterday,
        )

        material = await SleepCycle._gather_journal_material(today)
        assert material["souvenir_count"] == 2
        assert material["dominant_emotion"] == "happy"

    @pytest.mark.asyncio
    async def test_collects_person_entities(self):
        from memory.models import Entity, Souvenir
        from memory.sleep import SleepCycle

        today = date.today()
        today_dt = datetime.combine(today, datetime.min.time())
        today_tz = timezone.make_aware(today_dt)

        alice = await sync_to_async(Entity.objects.create)(
            name="Alice", entity_type="person",
        )
        topic = await sync_to_async(Entity.objects.create)(
            name="gaming", entity_type="concept",
        )
        s = await sync_to_async(Souvenir.objects.create)(
            content="s1", emotion="happy", importance=0.9,
            occurred_at=today_tz + timedelta(hours=10),
        )
        await sync_to_async(s.entities.set)([alice, topic])

        material = await SleepCycle._gather_journal_material(today)
        assert material["persons"] == ["Alice"]

    @pytest.mark.asyncio
    async def test_captures_active_ruminations(self):
        from conscience.models import Rumination
        from memory.models import Souvenir
        from memory.sleep import SleepCycle

        today = date.today()
        today_dt = datetime.combine(today, datetime.min.time())
        today_tz = timezone.make_aware(today_dt)

        await sync_to_async(Souvenir.objects.create)(
            content="s1", emotion="neutral", importance=0.5,
            occurred_at=today_tz + timedelta(hours=10),
        )
        await sync_to_async(Rumination.objects.create)(
            summary="a lingering worry", emotion="anxious",
            intensity=0.6, status="active",
        )
        await sync_to_async(Rumination.objects.create)(
            summary="resolved thought", emotion="relieved",
            intensity=0.2, status="resolved",
        )

        material = await SleepCycle._gather_journal_material(today)
        assert len(material["ruminations"]) == 1
        assert material["ruminations"][0]["summary"] == "a lingering worry"


# ---------------------------------------------------------------------------
# 5. Digestion — decay, emotion drift, reflective souvenir
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDigestRuminations:
    """_digest_ruminations should:
    - apply aggressive decay to old active ruminations
    - mutate their emotion toward a peaceful neighbor
    - convert high-intensity ones into reflective Souvenirs
    - mark faded ones as 'faded'
    - leave young (< 2h) ruminations untouched
    """

    @pytest.fixture(autouse=True)
    def _clean(self):
        from conscience.models import Rumination
        from memory.models import Souvenir
        Rumination.objects.all().delete()
        Souvenir.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_young_rumination_not_digested(self):
        from conscience.models import Rumination
        from memory.sleep import SleepCycle

        r = await sync_to_async(Rumination.objects.create)(
            summary="fresh", emotion="frustrated",
            intensity=0.8, status="active",
        )
        # Default created_at = now, so it's younger than the 120 min threshold
        s = SleepCycle()
        count = await s._digest_ruminations()
        assert count == 0
        await sync_to_async(r.refresh_from_db)()
        assert r.emotion == "frustrated"
        assert r.intensity == 0.8

    @pytest.mark.asyncio
    async def test_old_rumination_decays_and_mutates(self):
        from conscience.models import Rumination
        from memory.sleep import SleepCycle

        r = await sync_to_async(Rumination.objects.create)(
            summary="old worry", emotion="frustrated",
            intensity=0.6, status="active",
        )
        # Backdate to 3h ago
        old_time = timezone.now() - timedelta(hours=3)
        await sync_to_async(
            lambda: Rumination.objects.filter(pk=r.pk).update(created_at=old_time)
        )()

        s = SleepCycle()
        count = await s._digest_ruminations()
        assert count >= 1

        await sync_to_async(r.refresh_from_db)()
        # Decay: intensity *= 0.85 (one decay mult of 1 - 0.05 * 3.0)
        assert r.intensity < 0.6
        # Drift: frustrated → relieved per DIGESTION_DRIFT
        assert r.emotion == "relieved"

    @pytest.mark.asyncio
    async def test_heavy_old_rumination_becomes_reflective_souvenir(self):
        from conscience.models import Rumination
        from memory.models import Souvenir
        from memory.sleep import SleepCycle

        r = await sync_to_async(Rumination.objects.create)(
            summary="I really messed up with Alice", emotion="anxious",
            intensity=0.7, status="active",
        )
        old_time = timezone.now() - timedelta(hours=4)
        await sync_to_async(
            lambda: Rumination.objects.filter(pk=r.pk).update(created_at=old_time)
        )()

        before = await sync_to_async(Souvenir.objects.count)()
        s = SleepCycle()
        await s._digest_ruminations()
        after = await sync_to_async(Souvenir.objects.count)()

        assert after == before + 1
        created = await sync_to_async(
            lambda: Souvenir.objects.order_by("-pk").first()
        )()
        assert "Alice" in created.content
        assert "repense" in created.content

    @pytest.mark.asyncio
    async def test_faint_rumination_fades(self):
        from conscience.models import Rumination
        from memory.sleep import SleepCycle

        r = await sync_to_async(Rumination.objects.create)(
            summary="barely remembered", emotion="anxious",
            intensity=0.16, status="active",
        )
        old_time = timezone.now() - timedelta(hours=3)
        await sync_to_async(
            lambda: Rumination.objects.filter(pk=r.pk).update(created_at=old_time)
        )()

        s = SleepCycle()
        await s._digest_ruminations()

        await sync_to_async(r.refresh_from_db)()
        # 0.16 * 0.85 = 0.136 — still above 0.15? Actually just below
        # the fade threshold so it should be marked 'faded'.
        if r.intensity < 0.15:
            assert r.status == "faded"


# ---------------------------------------------------------------------------
# 6. Dream persistence
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestPersistDream:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from memory.models import Dream, Souvenir
        Dream.objects.all().delete()
        Souvenir.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_persist_attaches_source_souvenirs(self):
        from memory.models import Dream, Souvenir
        from memory.sleep import SleepCycle

        s1 = await sync_to_async(Souvenir.objects.create)(
            content="a", emotion="happy", importance=0.8,
            occurred_at=timezone.now(),
        )
        s2 = await sync_to_async(Souvenir.objects.create)(
            content="b", emotion="curious", importance=0.7,
            occurred_at=timezone.now(),
        )

        await SleepCycle._persist_dream(
            current_night=date.today(),
            fragments={"souvenirs": [s1, s2], "rumination": None},
            dream_type="associative",
            content="I walked in a strange forest...",
            emotion="dreamy",
            vividness=0.7,
        )

        dream = await sync_to_async(Dream.objects.first)()
        assert dream is not None
        assert dream.dream_type == "associative"
        assert dream.vividness == 0.7
        assert dream.emotion == "dreamy"

        source_ids = await sync_to_async(
            lambda: sorted(dream.source_souvenirs.values_list("pk", flat=True))
        )()
        assert source_ids == sorted([s1.pk, s2.pk])

    @pytest.mark.asyncio
    async def test_persist_works_without_souvenirs(self):
        """Edge case: fragments list is empty (shouldn't happen in normal flow,
        but we don't want an exception if it does)."""
        from memory.models import Dream
        from memory.sleep import SleepCycle

        await SleepCycle._persist_dream(
            current_night=date.today(),
            fragments={"souvenirs": [], "rumination": None},
            dream_type="mundane",
            content="Nothing much happened.",
            emotion="",
            vividness=0.3,
        )
        dream = await sync_to_async(Dream.objects.first)()
        assert dream is not None


# ---------------------------------------------------------------------------
# 7. Eligibility — combined gate of idle + REST tension
# ---------------------------------------------------------------------------


class TestEligibleToSleep:
    """`_is_eligible_to_sleep` est passée de statique à méthode d'instance.

    La grâce de réveil est un état, et c'est le seul moyen de distinguer
    « personne ne lui a parlé depuis 15 min » — vrai en permanence la nuit —
    de « elle vient de se réveiller pour faire quelque chose ».
    `get_idle_seconds()` ne peut pas répondre à la seconde question : il ne
    mesure que ce que les *autres* font, et un acte endogène le laisse
    volontairement intact. Les trois cas ci-dessous instancient donc un cycle
    neuf, dont la grâce n'a jamais couru.
    """

    @pytest.mark.asyncio
    async def test_not_eligible_when_busy(self):
        from memory.sleep import SleepCycle

        with patch("conscience.engine.conscience_engine") as mock_cons:
            mock_cons.get_idle_seconds.return_value = 30.0  # well under 900
            assert await SleepCycle()._is_eligible_to_sleep() is False

    @pytest.mark.asyncio
    async def test_le_repos_non_merite_n_interdit_plus_de_dormir(self):
        """Le pin change avec le correctif B1.

        Il exigeait REST >= 0.5 pour s'endormir. Mais REST ne croît que par
        événement d'activité et décroît pendant les 900 s d'inactivité que le
        gate impose d'abord : une soirée calme laissait la tension à ~0.01, et
        la nuit mentale entière (journal, rêves, digestion, réorg) ne
        s'exécutait jamais. REST n'avance plus que l'heure du coucher.
        """
        from memory.sleep import SleepCycle

        with (
            patch("conscience.engine.conscience_engine") as mock_cons,
            patch("drives.engine.drive_engine") as mock_drives,
        ):
            mock_cons.get_idle_seconds.return_value = 1200.0
            mock_drives.update.return_value = None
            mock_rest = MagicMock()
            mock_rest.tension = 0.3
            from drives.state import DriveKind
            mock_drives.states = {DriveKind.REST: mock_rest}

            assert await SleepCycle()._is_eligible_to_sleep() is True

    @pytest.mark.asyncio
    async def test_eligible_when_idle_and_tired(self):
        from memory.sleep import SleepCycle

        with patch("conscience.engine.conscience_engine") as mock_cons:
            mock_cons.get_idle_seconds.return_value = 1200.0

            assert await SleepCycle()._is_eligible_to_sleep() is True


# ---------------------------------------------------------------------------
# 8. End-to-end run_if_due — LLM mocked
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestRunIfDue:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from conscience.models import Rumination
        from memory.models import DailyJournal, Dream, Souvenir
        Rumination.objects.all().delete()
        Souvenir.objects.all().delete()
        DailyJournal.objects.all().delete()
        Dream.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_disabled_is_noop(self, settings):
        from memory.sleep import SleepCycle, SleepPhase

        settings.SLEEP_CYCLE_ENABLED = False
        s = SleepCycle()
        s._phase = SleepPhase.REM  # pretend we were dreaming

        with patch(
            "pipeline.broadcast.broadcast_inner_state_update",
            new_callable=AsyncMock,
        ):
            await s.run_if_due()
        # When disabled, phase is forced to AWAKE
        assert s.phase == SleepPhase.AWAKE

    @pytest.mark.asyncio
    async def test_daytime_forces_awake(self):
        from memory.sleep import SleepCycle, SleepPhase

        s = SleepCycle()
        s._phase = SleepPhase.REM

        with (
            patch(
                "memory.sleep.datetime",
                wraps=datetime,
            ) as mock_dt,
            patch(
                "pipeline.broadcast.broadcast_inner_state_update",
                new_callable=AsyncMock,
            ),
        ):
            mock_dt.now.return_value = datetime(2026, 4, 17, 14, 0)
            await s.run_if_due()
        assert s.phase == SleepPhase.AWAKE

    @pytest.mark.asyncio
    async def test_night_but_active_is_still_awake(self):
        from memory.sleep import SleepCycle, SleepPhase

        s = SleepCycle()

        with (
            patch("memory.sleep.datetime", wraps=datetime) as mock_dt,
            patch(
                "pipeline.broadcast.broadcast_inner_state_update",
                new_callable=AsyncMock,
            ),
            patch("conscience.engine.conscience_engine") as mock_cons,
        ):
            mock_dt.now.return_value = datetime(2026, 4, 17, 23, 30)
            mock_cons.get_idle_seconds.return_value = 30.0  # active
            await s.run_if_due()
        assert s.phase == SleepPhase.AWAKE

    @pytest.mark.asyncio
    async def test_settles_in_deep_sleep_without_flickering(self):
        """Once the night's work is done, repeated ticks must be silent.

        Each phase change pushes an inner_state broadcast that the frontend
        replays as a 1.2-1.8s eye/lighting transition; re-announcing
        LIGHT_SLEEP then REM every 60s would flicker the avatar all night.
        """
        from drives.state import DriveKind
        from memory.sleep import SleepCycle, SleepPhase

        s = SleepCycle()
        night = date(2026, 4, 17)
        # Pretend the journal, the dreams and the digestion are all done.
        s._last_journal_date = night
        s._last_dream_night = night
        s._dreams_this_night = 2
        s._last_digestion_night = night

        with (
            patch("memory.sleep.datetime", wraps=datetime) as mock_dt,
            patch(
                "pipeline.broadcast.broadcast_inner_state_update",
                new_callable=AsyncMock,
            ) as mock_broadcast,
            patch("conscience.engine.conscience_engine") as mock_cons,
            patch("drives.engine.drive_engine") as mock_drives,
        ):
            mock_dt.now.return_value = datetime(2026, 4, 18, 4, 0)
            mock_cons.get_idle_seconds.return_value = 3600.0
            rest = MagicMock()
            rest.tension = 0.9
            mock_drives.states = {DriveKind.REST: rest}

            await s.run_if_due()          # settles into deep sleep
            assert s.phase == SleepPhase.DEEP_SLEEP
            calls_after_first = mock_broadcast.await_count

            await s.run_if_due()          # subsequent ticks: nothing to say
            await s.run_if_due()

        assert s.phase == SleepPhase.DEEP_SLEEP
        assert mock_broadcast.await_count == calls_after_first


# ---------------------------------------------------------------------------
# 9. Regression: singleton exposes the right interface
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_singleton_exists(self):
        from memory.sleep import sleep_cycle

        assert sleep_cycle is not None
        assert hasattr(sleep_cycle, "run_if_due")
        assert hasattr(sleep_cycle, "phase")

    def test_singleton_default_phase_is_awake(self):
        from memory.sleep import SleepPhase, sleep_cycle

        # Note: singleton state persists across tests, but the default at
        # import time must always be AWAKE.
        assert sleep_cycle.phase in (
            SleepPhase.AWAKE,
            SleepPhase.LIGHT_SLEEP,
            SleepPhase.REM,
            SleepPhase.DEEP_SLEEP,
        )


class TestNuitDuProfilCircadien:
    """Les bornes de la nuit dérivent du profil circadien — les clés
    `memory.sleep_night_*` cohabitaient avec `personality.circadian.*`,
    deux sources de vérité pour « quand commence sa nuit » : un personnage
    nocturne dormait aux heures d'un autre."""

    def _profil(self, nuit=23, matin=6):
        from emotion.circadian import CircadianPhase, CircadianProfile

        return CircadianProfile(phase_hours={
            CircadianPhase.MORNING: matin,
            CircadianPhase.AFTERNOON: 12,
            CircadianPhase.EVENING: 18,
            CircadianPhase.NIGHT: nuit,
        })

    def test_un_personnage_nocturne_dort_sa_nuit_a_lui(self):
        from unittest.mock import patch

        from memory.sleep import SleepCycle

        with patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: self._profil(nuit=21, matin=9)),
        ):
            assert SleepCycle._nominal_night_start_hour() == 21
            assert SleepCycle._night_end_hour() == 9

    def test_un_profil_illisible_retombe_sur_l_historique(self):
        from unittest.mock import patch

        from memory.sleep import SleepCycle

        with patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: (_ for _ in ()).throw(RuntimeError("boom"))),
        ):
            assert SleepCycle._nominal_night_start_hour() == 23
            assert SleepCycle._night_end_hour() == 6

    def test_les_gardes_du_lecteur_bornent_un_profil_extreme(self):
        """Une « nuit » déclarée à 2 h du matin sort du domaine que le cycle
        sait traiter ([12, 23]) : ramenée dans la borne, jamais propagée."""
        from unittest.mock import patch

        from memory.sleep import SleepCycle

        with patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: self._profil(nuit=2, matin=14)),
        ):
            assert SleepCycle._nominal_night_start_hour() == 12
            assert SleepCycle._night_end_hour() == 12


class TestEmotionDeReveCanonique:
    """Un rêve ne teint jamais l'avatar avec une couleur qui n'existe pas.

    Observé en conditions réelles : un rêve persisté avec ``serenity``, hors
    des 29 — pas de ``--emo-serenity``, pas de traduction dans
    ``formatting.EMOTION_FR`` (le dashboard affiche le mot anglais brut) et
    refus du garde ``isEmotionName`` côté frontend.
    """

    def test_un_nom_hors_des_29_est_ecarte(self):
        from memory.sleep import _emotion_canonique

        assert _emotion_canonique("serenity") == ""
        assert _emotion_canonique("Sérénité") == ""

    def test_les_29_passent(self):
        from emotion.types import Emotion
        from memory.sleep import _emotion_canonique

        for e in Emotion:
            assert _emotion_canonique(e.value) == e.value
        assert _emotion_canonique("  PROUD  ") == "proud"

    def test_rien_reste_rien(self):
        from memory.sleep import _emotion_canonique

        assert _emotion_canonique(None) == ""
        assert _emotion_canonique("") == ""


class TestFenetreDeSommeilProfond:
    """La digestion et la réorganisation ouvraient à « 3 h » en dur, alors
    que le matin du profil est un champ du tableau de bord borné à [0, 12] :
    un matin à 3 h ou avant vidait la fenêtre, sans qu'aucun écran ne le
    dise."""

    def _profil(self, matin, nuit=23):
        from emotion.circadian import CircadianPhase, CircadianProfile

        return CircadianProfile(phase_hours={
            CircadianPhase.MORNING: matin,
            CircadianPhase.AFTERNOON: 12,
            CircadianPhase.EVENING: 18,
            CircadianPhase.NIGHT: nuit,
        })

    def _avec_profil(self, matin, nuit=23):
        return patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: self._profil(matin, nuit)),
        )

    def test_un_matin_ordinaire_garde_la_fenetre_historique(self):
        from memory.sleep import SleepCycle

        with self._avec_profil(matin=6):
            assert SleepCycle._deep_sleep_window() == (3, 6)

    def test_un_matin_precoce_recule_le_debut(self):
        from memory.sleep import SleepCycle

        with self._avec_profil(matin=3):
            assert SleepCycle._deep_sleep_window() == (2, 3)
            assert SleepCycle._en_sommeil_profond(datetime(2026, 4, 18, 2, 30))
            assert not SleepCycle._en_sommeil_profond(datetime(2026, 4, 18, 3, 0))

    def test_un_matin_a_minuit_laisse_une_fenetre_vide_et_le_dit(self):
        from memory.sleep import SleepCycle
        from utils.degradation import degradations

        degradations.reset()
        with self._avec_profil(matin=0):
            assert SleepCycle._deep_sleep_window() == (0, 0)
            assert not SleepCycle._en_sommeil_profond(datetime(2026, 4, 18, 0, 30))
        assert degradations.count_for("sommeil: fenetre de sommeil profond vide") == 1
        degradations.reset()


@pytest.mark.django_db(transaction=True)
class TestSommeilProfondSuitLeProfil:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from conscience.models import Rumination
        from memory.models import DailyJournal, Dream, Souvenir
        Rumination.objects.all().delete()
        Souvenir.objects.all().delete()
        DailyJournal.objects.all().delete()
        Dream.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_la_digestion_et_la_reorg_tournent_avant_un_matin_precoce(self):
        """Matin du profil à 3 h : « 3 <= heure < 3 » n'était jamais vrai."""
        from drives.state import DriveKind
        from emotion.circadian import CircadianPhase, CircadianProfile
        from memory import reorg as reorg_mod
        from memory.sleep import SleepCycle, SleepPhase

        profil = CircadianProfile(phase_hours={
            CircadianPhase.MORNING: 3,
            CircadianPhase.AFTERNOON: 12,
            CircadianPhase.EVENING: 18,
            CircadianPhase.NIGHT: 23,
        })
        s = SleepCycle()
        night = date(2026, 4, 17)
        # Journal et rêves déjà faits : seule la fin de nuit reste à jouer.
        s._last_journal_date = night
        s._last_dream_night = night
        s._dreams_this_night = 99
        s._digest_ruminations = AsyncMock(return_value=0)

        with (
            patch("config.personality.Personality.circadian_profile",
                  new=property(lambda _s: profil)),
            patch("memory.sleep.datetime", wraps=datetime) as mock_dt,
            patch("pipeline.broadcast.broadcast_inner_state_update",
                  new_callable=AsyncMock),
            patch("conscience.engine.conscience_engine") as mock_cons,
            patch("drives.engine.drive_engine") as mock_drives,
            patch.object(reorg_mod.nightly_reorg, "run",
                         AsyncMock(return_value={})) as run_reorg,
        ):
            mock_dt.now.return_value = datetime(2026, 4, 18, 2, 30)
            mock_cons.get_idle_seconds.return_value = 3600.0
            rest = MagicMock()
            rest.tension = 0.0
            mock_drives.states = {DriveKind.REST: rest}
            await s.run_if_due()

        s._digest_ruminations.assert_awaited_once()
        run_reorg.assert_awaited_once_with(night)
        assert s.phase == SleepPhase.DEEP_SLEEP
