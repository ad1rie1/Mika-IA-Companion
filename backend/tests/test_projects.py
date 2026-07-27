"""Tests for the Project management system.

Covered:
- Schedule parser (interval / cron fallback / idle / event / manual)
- Model basics (Project, ProjectTask, ProjectPendingAction)
- Project detection from a user message (keyword / title matching)
- Prompt injection: `project_context` in system prompt + emotion suppression
- ProjectRunner _extract_json_tail + _apply_structured happy path
- HTTP endpoints: create / list / detail / approve / reject
- Tools MCP: create_project handler produces a real DB row
"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from django.test import Client
from django.utils import timezone


def _patched_history_size(size: int):
    """Force the runner's rolling-buffer size via ``config_service``.

    The runner reads ``projects.prompt_history_size`` from the config store,
    not from Django settings, so overriding the setting is a no-op.
    """
    from configs.service import config_service
    real_get = config_service.get

    def _fake_get(key, default=None):
        if key == "projects.prompt_history_size":
            return size
        return real_get(key, default=default)

    return patch.object(config_service, "get", side_effect=_fake_get)


# ---------------------------------------------------------------------------
# 1. Schedule parser — pure functions
# ---------------------------------------------------------------------------


class TestScheduleParser:
    def test_empty_is_none(self):
        from projects.schedule import parse_rule
        assert parse_rule("").kind == "none"
        assert parse_rule("manual").kind == "none"
        assert parse_rule("   ").kind == "none"

    def test_interval_minutes(self):
        from projects.schedule import parse_rule
        r = parse_rule("interval:5m")
        assert r.kind == "interval"
        assert r.value == 300

    def test_interval_seconds(self):
        from projects.schedule import parse_rule
        r = parse_rule("interval:30s")
        assert r.kind == "interval"
        assert r.value == 30

    def test_interval_floor_at_5s(self):
        from projects.schedule import parse_rule
        # "interval:0s" should clamp to minimum 5s
        r = parse_rule("interval:0s")
        assert r.value >= 5

    def test_interval_hours(self):
        from projects.schedule import parse_rule
        r = parse_rule("interval:2h")
        assert r.value == 7200

    def test_cron_preserved(self):
        from projects.schedule import parse_rule
        r = parse_rule("cron:0 9 * * MON-FRI")
        assert r.kind == "cron"
        assert r.value == "0 9 * * MON-FRI"

    def test_idle(self):
        from projects.schedule import parse_rule
        r = parse_rule("idle:30m")
        assert r.kind == "idle"
        assert r.value == 1800

    def test_event(self):
        from projects.schedule import parse_rule
        r = parse_rule("event:email.new")
        assert r.kind == "event"
        assert r.value == "email.new"

    def test_garbage_falls_to_none(self):
        from projects.schedule import parse_rule
        assert parse_rule("nonsense").kind == "none"
        assert parse_rule("interval:abc").kind == "none"

    def test_compute_next_run_interval(self):
        from projects.schedule import compute_next_run
        base = timezone.now()
        nxt = compute_next_run("interval:10m", base)
        assert nxt is not None
        assert abs((nxt - base).total_seconds() - 600) < 2

    def test_compute_next_run_no_rule(self):
        from projects.schedule import compute_next_run
        assert compute_next_run("", timezone.now()) is None


# ---------------------------------------------------------------------------
# 2. Model basics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProjectModels:
    def test_project_defaults_have_emotion_off(self):
        """Core requirement: projects have emotions OFF unless told otherwise."""
        from projects.models import Project
        p = Project.objects.create(title="Test")
        assert p.emotion_policy == Project.EmotionPolicy.OFF
        assert p.is_emotion_off is True

    def test_project_status_active(self):
        from projects.models import Project
        p = Project.objects.create(title="Test")
        assert p.status == Project.Status.ACTIVE
        assert p.is_active is True

    def test_task_default_status(self):
        from projects.models import Project, ProjectTask
        p = Project.objects.create(title="Test")
        t = ProjectTask.objects.create(project=p, description="Do X")
        assert t.status == ProjectTask.Status.TODO

    def test_pending_action_default_status(self):
        from projects.models import Project, ProjectPendingAction
        p = Project.objects.create(title="Test")
        a = ProjectPendingAction.objects.create(
            project=p, proposal="send email", payload={"kind": "send_email"},
        )
        assert a.status == ProjectPendingAction.Status.PENDING


# ---------------------------------------------------------------------------
# 3. Project detection
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestProjectDetection:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from projects.models import Project
        Project.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_empty_message_no_match(self):
        from projects.detection import detect_project_for_message
        assert await detect_project_for_message("") is None
        assert await detect_project_for_message("  ") is None

    @pytest.mark.asyncio
    async def test_no_projects_no_match(self):
        from projects.detection import detect_project_for_message
        assert await detect_project_for_message("bonjour") is None

    @pytest.mark.asyncio
    async def test_title_match(self):
        from projects.models import Project
        await sync_to_async(Project.objects.create)(
            title="Mails pro", keywords=[],
        )
        from projects.detection import detect_project_for_message
        m = await detect_project_for_message("t'en es où sur les mails pro ?")
        assert m is not None
        assert m.title == "Mails pro"
        assert m.confidence > 0.4

    @pytest.mark.asyncio
    async def test_keyword_match(self):
        from projects.models import Project
        await sync_to_async(Project.objects.create)(
            title="Dossier client Alpha",
            keywords=["alpha", "facture", "relance"],
        )
        from projects.detection import detect_project_for_message
        m = await detect_project_for_message("je relance sur la facture")
        assert m is not None
        assert m.confidence >= 0.4

    @pytest.mark.asyncio
    async def test_no_signal_no_match(self):
        from projects.models import Project
        await sync_to_async(Project.objects.create)(
            title="Mails pro", keywords=["dubois"],
        )
        from projects.detection import detect_project_for_message
        # Completely unrelated message should not match
        m = await detect_project_for_message("ce documentaire sur les fourmis était top")
        assert m is None

    @pytest.mark.asyncio
    async def test_inactive_project_not_matched(self):
        from projects.models import Project
        await sync_to_async(Project.objects.create)(
            title="Mails pro",
            status=Project.Status.PAUSED,
        )
        from projects.detection import detect_project_for_message
        m = await detect_project_for_message("mails pro")
        assert m is None


# ---------------------------------------------------------------------------
# 4. Prompt injection
# ---------------------------------------------------------------------------


class TestPromptInjection:
    def test_no_project_no_block(self):
        from pipeline.prompt import build_system_prompt
        out = build_system_prompt()
        assert "PROJET EN COURS" not in out

    def test_project_bloc_appears(self):
        from pipeline.prompt import build_system_prompt
        out = build_system_prompt(project_context="Titre : test\nTon : neutre")
        assert "--- PROJET EN COURS ---" in out
        assert "Titre : test" in out

    def test_project_suppresses_emotion_block(self):
        from pipeline.prompt import build_system_prompt
        out_emit = build_system_prompt(
            emotion_context="You feel happy",
            project_context="Titre : test",
            project_suppresses_emotion=True,
        )
        assert "TON ETAT EMOTIONNEL" not in out_emit
        assert "PROJET EN COURS" in out_emit

    def test_project_muted_keeps_emotion(self):
        from pipeline.prompt import build_system_prompt
        out = build_system_prompt(
            emotion_context="You feel happy",
            project_context="Titre : test",
            project_suppresses_emotion=False,
        )
        assert "TON ETAT EMOTIONNEL" in out

    def test_personality_drops_emotion_tag_when_project_off(self):
        from config.personality import personality
        out = personality.to_system_prompt(
            project_active=True, project_suppresses_emotion=True,
        )
        # Mandatory [EMOTION:...] instruction should be absent
        assert "DOIS inclure une balise d'émotion" not in out
        # VARIABILITÉ block should be absent
        assert "VARIABILITÉ NATURELLE" not in out
        # But the professional-mode reminder should be present
        assert "projet professionnel" in out.lower()


# ---------------------------------------------------------------------------
# 5. Runner — JSON extraction
# ---------------------------------------------------------------------------


class TestRunnerParsing:
    def test_extract_json_tail_fenced(self):
        from projects.runner import _extract_json_tail
        raw = 'blah blah\n```json\n{"summary": "ok"}\n```\n'
        data = _extract_json_tail(raw)
        assert data == {"summary": "ok"}

    def test_extract_json_tail_bare(self):
        from projects.runner import _extract_json_tail
        raw = 'I did X.\nFinally:\n{"summary": "X done", "task_updates": []}'
        data = _extract_json_tail(raw)
        assert data["summary"] == "X done"

    def test_extract_json_tail_no_json(self):
        from projects.runner import _extract_json_tail
        assert _extract_json_tail("just plain text") is None

    def test_extract_json_tail_malformed(self):
        from projects.runner import _extract_json_tail
        assert _extract_json_tail("{broken: json") is None


# ---------------------------------------------------------------------------
# 6. HTTP endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProjectEndpoints:
    def test_create_then_list(self, client: Client):
        resp = client.post(
            "/api/projects/create",
            data=json.dumps({
                "title": "Mails pro",
                "schedule_rule": "interval:5m",
                "emotion_policy": "off",
                "requires_approval": True,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        pid = resp.json()["project"]["id"]
        resp = client.get("/api/projects/")
        assert resp.status_code == 200
        projects = resp.json()["projects"]
        assert any(p["id"] == pid for p in projects)

    def test_create_requires_title(self, client: Client):
        resp = client.post(
            "/api/projects/create",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_detail_with_tasks(self, client: Client):
        from projects.models import Project, ProjectTask
        p = Project.objects.create(title="X")
        ProjectTask.objects.create(project=p, description="task A")
        resp = client.get(f"/api/projects/{p.pk}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "X"
        assert len(body["tasks"]) == 1

    def test_patch_project(self, client: Client):
        from projects.models import Project
        p = Project.objects.create(title="X", status="active")
        resp = client.patch(
            f"/api/projects/{p.pk}",
            data=json.dumps({"status": "paused", "priority": "high"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        p.refresh_from_db()
        assert p.status == "paused"
        assert p.priority == "high"

    def test_add_and_update_task(self, client: Client):
        from projects.models import Project, ProjectTask
        p = Project.objects.create(title="X")
        resp = client.post(
            f"/api/projects/{p.pk}/tasks",
            data=json.dumps({"description": "do A"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        tid = resp.json()["task"]["id"]

        resp = client.patch(
            f"/api/projects/{p.pk}/tasks/{tid}",
            data=json.dumps({"status": "done", "result": "A done"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        t = ProjectTask.objects.get(pk=tid)
        assert t.status == "done"
        assert t.completed_at is not None


@pytest.mark.django_db(transaction=True)
class TestPendingEndpoints:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from projects.models import Project, ProjectPendingAction
        ProjectPendingAction.objects.all().delete()
        Project.objects.all().delete()
        yield

    def test_list_pending(self, client: Client):
        from projects.models import Project, ProjectPendingAction
        p = Project.objects.create(title="X")
        ProjectPendingAction.objects.create(
            project=p, proposal="send email", payload={"kind": "send_email"},
        )
        resp = client.get("/api/projects/pending/")
        assert resp.status_code == 200
        pending = resp.json()["pending"]
        assert len(pending) == 1
        assert pending[0]["proposal"] == "send email"

    def test_approve_unknown_payload_kind(self, client: Client):
        """Approval of an unknown-kind payload should succeed in audit mode."""
        from projects.models import Project, ProjectPendingAction
        p = Project.objects.create(title="X")
        a = ProjectPendingAction.objects.create(
            project=p, proposal="do thing",
            payload={"kind": "unsupported_xyz"},
        )
        # Patch the broadcast so it's a no-op (no channel layer in tests)
        with patch(
            "pipeline.broadcast.broadcast_inner_state_update"
        ) as mock_bc:
            async def _noop(*_a, **_k): return None
            mock_bc.side_effect = _noop
            resp = client.post(f"/api/projects/pending/{a.pk}/approve",
                               data="{}", content_type="application/json")
        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.EXECUTED
        assert "unsupported" in a.execution_result

    def test_reject(self, client: Client):
        from projects.models import Project, ProjectLog, ProjectPendingAction
        p = Project.objects.create(title="X")
        a = ProjectPendingAction.objects.create(
            project=p, proposal="do thing", payload={"kind": "send_email"},
        )
        with patch(
            "pipeline.broadcast.broadcast_inner_state_update"
        ) as mock_bc:
            async def _noop(*_a, **_k): return None
            mock_bc.side_effect = _noop
            resp = client.post(
                f"/api/projects/pending/{a.pk}/reject",
                data=json.dumps({"note": "pas le bon moment"}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.REJECTED
        assert a.user_note == "pas le bon moment"
        # A ProjectLog entry should record the rejection
        log = ProjectLog.objects.filter(project=p).first()
        assert log is not None
        assert "ejet" in log.summary.lower()

    def _approve(self, client: Client, action_id: int):
        with patch(
            "pipeline.broadcast.broadcast_inner_state_update"
        ) as mock_bc:
            async def _noop(*_a, **_k): return None
            mock_bc.side_effect = _noop
            return client.post(
                f"/api/projects/pending/{action_id}/approve",
                data="{}", content_type="application/json",
            )

    def test_approve_send_email_executes_real_send(self, client: Client):
        """An approved send_email must reach the email module's send path."""
        from projects.models import Project, ProjectPendingAction
        p = Project.objects.create(title="X")
        a = ProjectPendingAction.objects.create(
            project=p, proposal="send email",
            payload={"kind": "send_email", "to": "a@b.c",
                     "subject": "Rapport", "body": "Voici."},
        )

        sent = {}

        class _FakeEmailModule:
            async def send_email(self, *, to, subject, body, account_id=None):
                sent.update(to=to, subject=subject, body=body)
                return True, f"Email sent to {to} from Test."

        with patch("modules.manager.module_manager") as mm:
            mm.get_module.return_value = _FakeEmailModule()
            resp = self._approve(client, a.pk)

        assert resp.status_code == 200
        assert sent == {"to": "a@b.c", "subject": "Rapport", "body": "Voici."}
        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.EXECUTED
        assert "sent" in a.execution_result

    def test_approve_send_email_failure_marks_failed(self, client: Client):
        """A send failure must yield FAILED — never a green 'executed'."""
        from projects.models import Project, ProjectPendingAction
        p = Project.objects.create(title="X")
        a = ProjectPendingAction.objects.create(
            project=p, proposal="send email",
            payload={"kind": "send_email", "to": "a@b.c",
                     "subject": "S", "body": "B"},
        )

        class _BrokenEmailModule:
            async def send_email(self, **kw):
                return False, "No SMTP-configured account available."

        with patch("modules.manager.module_manager") as mm:
            mm.get_module.return_value = _BrokenEmailModule()
            resp = self._approve(client, a.pk)

        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.FAILED
        assert "SMTP" in a.execution_result

    def test_approve_send_email_without_module_marks_failed(self, client: Client):
        from projects.models import Project, ProjectPendingAction
        p = Project.objects.create(title="X")
        a = ProjectPendingAction.objects.create(
            project=p, proposal="send email",
            payload={"kind": "send_email", "to": "a@b.c",
                     "subject": "S", "body": "B"},
        )
        with patch("modules.manager.module_manager") as mm:
            mm.get_module.return_value = None
            resp = self._approve(client, a.pk)

        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.FAILED


@pytest.mark.django_db(transaction=True)
class TestEventScheduleWiring:
    """`event:<name>` schedule rules fire via the module bus.

    notify_event existed but had no caller — every event-scheduled
    project was dead. emit_event now wakes matching projects.
    """

    @pytest.fixture(autouse=True)
    def _clean(self):
        from projects.models import Project
        Project.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_emit_event_wakes_matching_project(self):
        from asgiref.sync import sync_to_async
        from django.utils import timezone
        from modules.manager import ModuleManager
        from modules.types import ModuleEvent
        from projects.models import Project

        p = await sync_to_async(Project.objects.create)(
            title="Veille email", schedule_rule="event:email.received",
            next_run_at=None,
        )

        manager = ModuleManager()
        before = timezone.now()
        await manager.emit_event(ModuleEvent(
            event_type="email.received", source_module="email", data={},
        ))

        refreshed = await sync_to_async(Project.objects.get)(pk=p.pk)
        assert refreshed.next_run_at is not None
        assert refreshed.next_run_at >= before

    @pytest.mark.asyncio
    async def test_non_matching_event_leaves_project_alone(self):
        from asgiref.sync import sync_to_async
        from modules.manager import ModuleManager
        from modules.types import ModuleEvent
        from projects.models import Project

        p = await sync_to_async(Project.objects.create)(
            title="Veille email", schedule_rule="event:email.received",
            next_run_at=None,
        )
        manager = ModuleManager()
        await manager.emit_event(ModuleEvent(
            event_type="rss.new_entry", source_module="rss", data={},
        ))
        refreshed = await sync_to_async(Project.objects.get)(pk=p.pk)
        assert refreshed.next_run_at is None


# ---------------------------------------------------------------------------
# 7. MCP tool — create_project via handler
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestPromptHistory:
    """Rolling buffer of LLM prompts/responses attached to each project."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        from projects.models import Project, ProjectPromptHistory
        ProjectPromptHistory.objects.all().delete()
        Project.objects.all().delete()
        yield

    def test_prune_keeps_last_n(self):
        from projects.models import Project, ProjectPromptHistory
        from projects.runner import _prune_history
        p = Project.objects.create(title="X")
        # Insert 5 entries
        for i in range(5):
            ProjectPromptHistory.objects.create(
                project=p, system_prompt=f"sys{i}",
                raw_response=f"resp{i}", outcome="ok",
            )
        deleted = _prune_history(project_id=p.id, keep=3)
        assert deleted == 2
        remaining = list(
            ProjectPromptHistory.objects.filter(project=p)
            .order_by("-created_at", "-id")
        )
        assert len(remaining) == 3
        # Kept entries are the 3 most recent (highest i values)
        assert remaining[0].system_prompt == "sys4"
        assert remaining[2].system_prompt == "sys2"

    def test_prune_noop_when_under_cap(self):
        from projects.models import Project, ProjectPromptHistory
        from projects.runner import _prune_history
        p = Project.objects.create(title="X")
        for i in range(2):
            ProjectPromptHistory.objects.create(
                project=p, system_prompt=f"sys{i}", outcome="ok",
            )
        deleted = _prune_history(project_id=p.id, keep=30)
        assert deleted == 0
        assert ProjectPromptHistory.objects.filter(project=p).count() == 2

    @pytest.mark.asyncio
    async def test_save_prompt_history_writes_row(self):
        from projects.models import Project, ProjectPromptHistory
        from projects.runner import ProjectRunner

        p = await sync_to_async(Project.objects.create)(title="X")

        r = ProjectRunner()
        with _patched_history_size(30):
            await r._save_prompt_history(
                project_id=p.id,
                system_prompt="the system",
                user_prompt="advance",
                raw_response='ok {"summary": "done"}',
                parsed_output={"summary": "done"},
                outcome="ok",
                duration_ms=120,
            )
        count = await sync_to_async(
            lambda: ProjectPromptHistory.objects.filter(project=p).count()
        )()
        assert count == 1

    @pytest.mark.asyncio
    async def test_save_prompt_history_disabled_when_zero(self):
        from projects.models import Project, ProjectPromptHistory
        from projects.runner import ProjectRunner

        p = await sync_to_async(Project.objects.create)(title="X")

        r = ProjectRunner()
        with _patched_history_size(0):
            await r._save_prompt_history(
                project_id=p.id,
                system_prompt="the system",
                user_prompt="advance",
                raw_response="ok",
                parsed_output=None,
                outcome="ok",
                duration_ms=1,
            )
        count = await sync_to_async(
            lambda: ProjectPromptHistory.objects.filter(project=p).count()
        )()
        assert count == 0

    @pytest.mark.asyncio
    async def test_save_prompt_history_enforces_size(self):
        from projects.models import Project, ProjectPromptHistory
        from projects.runner import ProjectRunner

        p = await sync_to_async(Project.objects.create)(title="X")

        r = ProjectRunner()
        with _patched_history_size(3):
            for i in range(5):
                await r._save_prompt_history(
                    project_id=p.id,
                    system_prompt=f"s{i}",
                    user_prompt="u",
                    raw_response=f"r{i}",
                    parsed_output=None,
                    outcome="ok",
                    duration_ms=i,
                )
        count = await sync_to_async(
            lambda: ProjectPromptHistory.objects.filter(project=p).count()
        )()
        assert count == 3


@pytest.mark.django_db
class TestPromptHistoryEndpoint:
    def test_history_endpoint_compact(self, client: Client):
        from projects.models import Project, ProjectPromptHistory
        p = Project.objects.create(title="X")
        for i in range(3):
            ProjectPromptHistory.objects.create(
                project=p, system_prompt="a" * 500,
                raw_response="b" * 500, outcome="ok",
                duration_ms=100 + i,
            )
        resp = client.get(f"/api/projects/{p.pk}/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        # Compact = excerpt only, not full text
        first = body["history"][0]
        assert "system_prompt_excerpt" in first
        assert len(first["system_prompt_excerpt"]) <= 240
        assert "system_prompt" not in first

    def test_history_endpoint_full(self, client: Client):
        from projects.models import Project, ProjectPromptHistory
        p = Project.objects.create(title="X")
        ProjectPromptHistory.objects.create(
            project=p, system_prompt="FULL",
            raw_response="RESP", outcome="ok",
        )
        resp = client.get(f"/api/projects/{p.pk}/history?full=1")
        assert resp.status_code == 200
        first = resp.json()["history"][0]
        assert first["system_prompt"] == "FULL"
        assert first["raw_response"] == "RESP"

    def test_history_limit_clamped(self, client: Client):
        from projects.models import Project, ProjectPromptHistory
        p = Project.objects.create(title="X")
        for i in range(5):
            ProjectPromptHistory.objects.create(
                project=p, system_prompt=f"s{i}", outcome="ok",
            )
        resp = client.get(f"/api/projects/{p.pk}/history?limit=2")
        assert resp.json()["count"] == 2

    def test_history_unknown_project(self, client: Client):
        resp = client.get("/api/projects/9999/history")
        assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
class TestMCPTool:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from projects.models import Project
        Project.objects.all().delete()
        yield

    @pytest.mark.asyncio
    async def test_create_project_handler(self):
        from projects.tools import ProjectToolsModule
        from projects.models import Project

        mod = ProjectToolsModule()
        out = await mod._tool_create({
            "title": "Test pro",
            "emotion_policy": "off",
            "schedule_rule": "interval:10m",
            "instructions": ["always confirm"],
        })
        # Return value has MCP content-array shape
        assert "content" in out
        # Row actually exists in DB
        p = await sync_to_async(
            lambda: Project.objects.filter(title="Test pro").first()
        )()
        assert p is not None
        assert p.emotion_policy == "off"
        assert p.schedule_rule == "interval:10m"
        assert p.next_run_at is not None
        assert "always confirm" in p.instructions
