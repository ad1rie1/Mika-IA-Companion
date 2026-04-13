"""Tests for Conscience Django models — Observation, ConscienceLog, ScheduledAction."""

import pytest
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
class TestObservation:

    def test_create_with_defaults(self):
        from conscience.models import Observation
        obs = Observation.objects.create(source="email", event_type="email.received", summary="Un email de Thomas")
        assert obs.pk is not None
        assert obs.status == Observation.Status.PENDING
        assert obs.acted_upon is False
        assert obs.raw_data == {}

    def test_all_status_choices_valid(self):
        from conscience.models import Observation
        for status in ("pending", "acted", "skipped", "failed"):
            obs = Observation.objects.create(source="t", event_type="t", status=status)
            assert obs.status == status

    def test_all_category_choices_valid(self):
        from conscience.models import Observation
        for cat in ("communication", "emotional", "memory", "temporal", "external", "system"):
            obs = Observation.objects.create(source="t", event_type="t", category=cat)
            assert obs.category == cat

    def test_str_contains_source_and_summary(self):
        from conscience.models import Observation
        obs = Observation.objects.create(source="email", event_type="e", summary="Thomas a envoyé un message")
        s = str(obs)
        assert "email" in s
        assert "Thomas" in s

    def test_ordering_newest_first(self):
        from conscience.models import Observation
        o1 = Observation.objects.create(source="a", event_type="e1")
        o2 = Observation.objects.create(source="b", event_type="e2")
        first = Observation.objects.first()
        assert first.pk == o2.pk


@pytest.mark.django_db
class TestConscienceLog:

    def test_create_act_log(self):
        from conscience.models import ConscienceLog
        log = ConscienceLog.objects.create(decision="act", reason="mood overflow (score=0.72)")
        assert log.pk is not None
        assert log.decision == "act"
        assert log.memory_actions == []

    def test_all_decisions_valid(self):
        from conscience.models import ConscienceLog
        for d in ("act", "wait", "skip"):
            log = ConscienceLog.objects.create(decision=d)
            assert log.decision == d

    def test_str_contains_decision(self):
        from conscience.models import ConscienceLog
        log = ConscienceLog.objects.create(decision="act", reason="morning greeting")
        assert "act" in str(log)

    def test_memory_actions_persisted(self):
        from conscience.models import ConscienceLog
        actions = ["boosted 2 souvenirs", "invalidated #5"]
        log = ConscienceLog.objects.create(decision="act", memory_actions=actions)
        reloaded = ConscienceLog.objects.get(pk=log.pk)
        assert reloaded.memory_actions == actions


@pytest.mark.django_db
class TestScheduledAction:

    def test_create_pending(self):
        from conscience.models import ScheduledAction
        a = ScheduledAction.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=2),
            prompt="Envoyer un suivi à Thomas",
            priority=0.8,
            source="claude",
        )
        assert a.pk is not None
        assert a.status == ScheduledAction.Status.PENDING
        assert a.executed_at is None

    def test_all_statuses_valid(self):
        from conscience.models import ScheduledAction
        for s in ("pending", "executed", "cancelled"):
            a = ScheduledAction.objects.create(
                scheduled_at=timezone.now(), prompt="test", source="t", status=s
            )
            assert a.status == s

    def test_ordering_soonest_first(self):
        from conscience.models import ScheduledAction
        now = timezone.now()
        a1 = ScheduledAction.objects.create(scheduled_at=now + timedelta(hours=2), prompt="later", source="t")
        a2 = ScheduledAction.objects.create(scheduled_at=now + timedelta(hours=1), prompt="sooner", source="t")
        first = ScheduledAction.objects.filter(pk__in=[a1.pk, a2.pk]).first()
        assert first.pk == a2.pk

    def test_context_data_persisted(self):
        from conscience.models import ScheduledAction
        ctx = {"email_id": 42, "recipient": "thomas@example.com"}
        a = ScheduledAction.objects.create(
            scheduled_at=timezone.now(), prompt="test", source="t", context_data=ctx
        )
        assert ScheduledAction.objects.get(pk=a.pk).context_data == ctx

    def test_str_contains_prompt(self):
        from conscience.models import ScheduledAction
        a = ScheduledAction.objects.create(
            scheduled_at=timezone.now(), prompt="Dire bonjour à Alice", source="t"
        )
        assert "bonjour" in str(a).lower() or "pending" in str(a)
