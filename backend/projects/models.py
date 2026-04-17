"""Project management — Mika as agent with explicit work engagements.

A Project is a unit of work with a *frame of execution*: tone, allowed
tools, instructions, forbidden territory, schedule rules. It changes:
  - how Mika uses her idle time (she advances projects, doesn't idle)
  - how she replies when the topic is project-related (tone override)
  - what modules/resources she can touch (scope)
  - what requires user approval before execution

**Emotional policy**: the default is `off` — no [EMOTION:] tag, neutral
tone, no variability block. Projects are professional engagements. The
emotional layer only kicks in if the project was explicitly created with
`emotion_policy="full"` or `"muted"`.

Models:
  - Project          — the engagement itself
  - ProjectTask      — granular unit of work ("respond to Dubois mail")
  - ProjectLog       — audit trail of each advance tick
  - ProjectPendingAction — queue of actions waiting for user approval
"""
from __future__ import annotations

from django.db import models


class Project(models.Model):
    """A unit of work Mika has taken on, either self-initiated or user-confided.

    The fields below are *policy* — the ProjectRunner reads them every
    cycle so changes are picked up live without restart.
    """

    class Origin(models.TextChoices):
        USER = "user", "User-confided"
        SELF = "self", "Self-initiated"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        ABANDONED = "abandoned", "Abandoned"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class EmotionPolicy(models.TextChoices):
        # The default for projects is "off": no emotion tags, no variability
        # block — professional mode. Only flip this up if the project is
        # creative / social by nature and the user asks for it.
        OFF = "off", "No emotions (neutral professional)"
        MUTED = "muted", "Muted (emotions allowed but dampened)"
        FULL = "full", "Full emotional expression"

    # ── Identity ─────────────────────────────────────────────────
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    # Short keyword list for conversation matching (what the project is
    # "about" lexically). Optional — the system falls back to matching on
    # title + description.
    keywords = models.JSONField(default=list, blank=True)
    origin = models.CharField(
        max_length=10, choices=Origin.choices, default=Origin.USER,
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE,
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.NORMAL,
    )

    # Who confided the project (user or contact). Null for self-initiated.
    owner = models.ForeignKey(
        "memory.Entity",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_projects",
        limit_choices_to={"entity_type": "person"},
    )

    # ── Execution frame — the policy Mika must follow ────────────
    tone_directive = models.TextField(
        blank=True, default="",
        help_text="How to write/respond while working on this project "
                  "(e.g. 'Langage soutenu, factuel, pas d'abréviations').",
    )
    emotion_policy = models.CharField(
        max_length=10, choices=EmotionPolicy.choices,
        default=EmotionPolicy.OFF,
        help_text="Emotional layer to apply during project work. Default 'off'.",
    )
    instructions = models.JSONField(
        default=list, blank=True,
        help_text="List of positive directives. "
                  "e.g. ['Toujours demander accord avant envoi']",
    )
    out_of_scope = models.JSONField(
        default=list, blank=True,
        help_text="Explicit no-go topics/actions for this project.",
    )
    requires_approval = models.BooleanField(
        default=False,
        help_text="When True, any action with side-effects queues as "
                  "ProjectPendingAction instead of executing immediately.",
    )

    # ── Resource scope — strict allowlist ────────────────────────
    allowed_modules = models.JSONField(
        default=list, blank=True,
        help_text="Module names the ProjectRunner may invoke "
                  "(e.g. ['email', 'files']). Empty = no tools at all.",
    )
    resource_paths = models.JSONField(
        default=list, blank=True,
        help_text="Filesystem / logical paths relevant to this project.",
    )
    contacts = models.JSONField(
        default=list, blank=True,
        help_text="Email addresses / handles in scope for this project.",
    )

    # ── Scheduling ───────────────────────────────────────────────
    schedule_rule = models.CharField(
        max_length=120, blank=True, default="",
        help_text=(
            "When the runner should advance the project. Supported forms:\n"
            "  ''                 (manual only — advance via admin or user msg)\n"
            "  'interval:5m'      (every 5 minutes; s/m/h units)\n"
            "  'cron:0 9 * * MON-FRI' (cron expression)\n"
            "  'idle:30m'         (when Mika idle for >= 30 minutes)\n"
            "  'event:email.new'  (reacted to a module event)\n"
        ),
    )
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    # Number of consecutive runs without user intervention. Safety gauge —
    # forces a cooldown if it grows too large.
    runs_since_user_input = models.IntegerField(default=0)

    # ── Quota / budget ───────────────────────────────────────────
    # Monthly token cap for this project's LLM calls (sum of prompt +
    # completion tokens across all calls tagged with this project_id
    # via ``ai.quota.current_project_id``). 0 = unlimited.
    # When exceeded, ``ai.router`` raises ``QuotaExceeded`` and the
    # runner logs a `quota_exceeded` outcome + defers next_run.
    monthly_token_budget = models.IntegerField(default=0)

    # ── Meta ─────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "-updated_at"]
        indexes = [
            models.Index(fields=["status", "-priority"]),
            models.Index(fields=["status", "next_run_at"]),
        ]

    def __str__(self):
        return f"[{self.status}/{self.priority}] {self.title}"

    @property
    def is_emotion_off(self) -> bool:
        return self.emotion_policy == self.EmotionPolicy.OFF

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class ProjectTask(models.Model):
    """A granular unit of work inside a project.

    Projects may start with zero tasks (Mika's first advance tick will
    likely create them) or a pre-seeded backlog. Order preserves the
    user's desired sequencing.
    """

    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"
        BLOCKED = "blocked", "Blocked"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="tasks",
    )
    description = models.TextField()
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.TODO,
    )
    blocked_reason = models.TextField(blank=True, default="")
    # What Mika actually did (for audit + human review after the fact)
    result = models.TextField(blank=True, default="")
    order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["project_id", "order", "created_at"]
        indexes = [
            models.Index(fields=["project", "status", "order"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.description[:60]}"


class ProjectLog(models.Model):
    """Audit trail of project activity. One row per tick/advance/action."""

    class Action(models.TextChoices):
        ADVANCED = "advanced", "Advanced (one tick done)"
        WAITED = "waited", "Waited (no tick needed)"
        REPORTED = "reported", "Reported to user"
        BLOCKED = "blocked", "Blocked"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting user approval"
        ERROR = "error", "Error during run"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    summary = models.TextField()
    tools_used = models.JSONField(default=list, blank=True)
    task = models.ForeignKey(
        ProjectTask, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.action}] {self.project_id}: {self.summary[:60]}"


class ProjectPromptHistory(models.Model):
    """Rolling buffer of LLM prompt/response pairs for a project.

    The runner appends one row per advance tick. A background prune keeps
    only the last ``settings.PROJECT_PROMPT_HISTORY_SIZE`` entries per
    project (default 30) so the table doesn't grow unbounded.

    Purpose: audit + debug. You can read the exact prompt Mika received
    and what she produced, and see the structured JSON we extracted vs.
    what the runner actually persisted. Never exposed to Mika herself.
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="prompt_history",
    )
    # The assembled system prompt passed to the LLM (build from the
    # ProjectRunContext). Can be multi-kB so we use TextField.
    system_prompt = models.TextField()
    # The user_prompt (typically a short "fais avancer le projet" cue).
    user_prompt = models.TextField(blank=True, default="")
    # Raw LLM response before parsing.
    raw_response = models.TextField(blank=True, default="")
    # Parsed JSON (what the runner actually applied). Null if the LLM
    # output didn't contain a parseable JSON tail.
    parsed_output = models.JSONField(null=True, blank=True)
    # How the runner interpreted this tick — success / timeout / json_miss
    outcome = models.CharField(max_length=20, default="ok")
    # Wall-clock latency of the LLM call, for performance tracking.
    duration_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.project_id}] {self.outcome} @ {self.created_at:%Y-%m-%d %H:%M}"


class ProjectPendingAction(models.Model):
    """An action Mika wants to perform but needs user approval first.

    Created when `Project.requires_approval=True` and the runner has
    prepared something with side effects (sending an email, writing a
    file, etc.). The user reviews + approves/rejects via UI.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXECUTED = "executed", "Executed"
        FAILED = "failed", "Failed to execute"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="pending_actions",
    )
    task = models.ForeignKey(
        ProjectTask, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pending_actions",
    )
    proposal = models.TextField(
        help_text="Human-readable description of what Mika wants to do.",
    )
    # Serialized action payload — the runner uses this to actually execute
    # once approved. Structure is action-specific, e.g.:
    #   {"kind": "send_email", "to": "...", "subject": "...", "body": "..."}
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
    )
    user_note = models.TextField(
        blank=True, default="",
        help_text="Optional note from the user on approve/reject.",
    )
    execution_result = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["project", "status"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.proposal[:60]}"
