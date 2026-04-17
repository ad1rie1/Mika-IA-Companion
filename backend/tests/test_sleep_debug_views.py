"""Tests for the sleep-cycle debug endpoints.

Covers:
- 403 when DEBUG=False (production safety)
- Force phase with valid / invalid body
- Wake shortcut
- Status snapshot (no LLM)
- Digest endpoint

We do NOT exercise the LLM-backed endpoints (journal, dream) — they are
covered by unit tests in test_sleep.py where the LLM is mocked. The
endpoint wrapping is thin so we trust the views to call through.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone


@pytest.fixture
def client():
    return Client()


class TestDebugGate:
    def test_force_phase_forbidden_in_production(self, client, settings):
        settings.DEBUG = False
        resp = client.post(
            "/api/dev/sleep/phase",
            data='{"phase":"rem"}',
            content_type="application/json",
        )
        assert resp.status_code == 403
        body = resp.json()
        assert "disabled" in body["error"].lower()

    def test_status_forbidden_in_production(self, client, settings):
        settings.DEBUG = False
        resp = client.get("/api/dev/sleep/status")
        assert resp.status_code == 403


class TestForcePhase:
    def test_valid_phase_sets_and_broadcasts(self, client, settings):
        settings.DEBUG = True
        from memory.sleep import sleep_cycle

        with patch(
            "pipeline.broadcast.broadcast_inner_state_update"
        ) as mock_bc:
            # The broadcast is async — we mock it to a no-op that returns
            # a truthy awaitable.
            async def _noop(*args, **kwargs):
                return None

            mock_bc.side_effect = _noop
            resp = client.post(
                "/api/dev/sleep/phase",
                data='{"phase":"rem"}',
                content_type="application/json",
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["phase"] == "rem"
        assert sleep_cycle.phase == "rem"

    def test_invalid_phase_rejected(self, client, settings):
        settings.DEBUG = True
        resp = client.post(
            "/api/dev/sleep/phase",
            data='{"phase":"confused"}',
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "valid" in body

    def test_missing_body_rejected(self, client, settings):
        settings.DEBUG = True
        resp = client.post(
            "/api/dev/sleep/phase",
            data="",
            content_type="application/json",
        )
        # Empty body parses to {} then phase missing → 400
        assert resp.status_code == 400

    def test_malformed_json_rejected(self, client, settings):
        settings.DEBUG = True
        resp = client.post(
            "/api/dev/sleep/phase",
            data="{not json",
            content_type="application/json",
        )
        assert resp.status_code == 400


class TestWakeEndpoint:
    def test_wake_returns_awake(self, client, settings):
        settings.DEBUG = True
        from memory.sleep import SleepPhase, sleep_cycle

        # Put her to sleep first so the transition is a meaningful test
        with patch(
            "pipeline.broadcast.broadcast_inner_state_update"
        ) as mock_bc:
            async def _noop(*args, **kwargs):
                return None
            mock_bc.side_effect = _noop

            # Directly seed a non-awake state to verify wake actually changes it
            import asyncio
            asyncio.run(sleep_cycle._set_phase(SleepPhase.DEEP_SLEEP))
            assert sleep_cycle.phase == "deep_sleep"

            resp = client.post("/api/dev/sleep/wake")
        assert resp.status_code == 200
        assert resp.json()["phase"] == "awake"
        assert sleep_cycle.phase == "awake"


@pytest.mark.django_db
class TestStatusEndpoint:
    def test_status_with_empty_db(self, client, settings):
        settings.DEBUG = True
        resp = client.get("/api/dev/sleep/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "phase" in body
        assert body["today_journal"] is None
        assert body["last_dream"] is None

    def test_status_reports_today_journal(self, client, settings):
        settings.DEBUG = True
        from memory.models import DailyJournal

        DailyJournal.objects.create(
            date=date.today(),
            narrative="Une journée calme et posée.",
            dominant_emotion="relieved",
        )

        resp = client.get("/api/dev/sleep/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["today_journal"]["dominant_emotion"] == "relieved"
        assert "calme" in body["today_journal"]["narrative"]

    def test_status_reports_last_night_dream(self, client, settings):
        settings.DEBUG = True
        from memory.models import Dream

        last_night = date.today() - timedelta(days=1)
        Dream.objects.create(
            night_of=last_night,
            content="I wandered in a library of cookies.",
            dream_type="associative",
            vividness=0.8,
            emotion="dreamy",
        )

        resp = client.get("/api/dev/sleep/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_dream"]["type"] == "associative"
        assert body["last_dream"]["vividness"] == 0.8
        assert body["last_dream"]["recalled"] is False


@pytest.mark.django_db(transaction=True)
class TestDigestEndpoint:
    def test_digest_processes_old_rumination(self, client, settings):
        settings.DEBUG = True
        from conscience.models import Rumination

        # Clear any leaked state
        Rumination.objects.all().delete()

        r = Rumination.objects.create(
            summary="an old worry", emotion="frustrated",
            intensity=0.6, status="active",
        )
        # Backdate
        Rumination.objects.filter(pk=r.pk).update(
            created_at=timezone.now() - timedelta(hours=3)
        )

        resp = client.post("/api/dev/sleep/digest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] >= 1

        r.refresh_from_db()
        assert r.emotion == "relieved"  # drifted from frustrated
