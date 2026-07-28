"""Wake module — triggers spontaneous AI messages via cron or API."""

from __future__ import annotations

import json
import logging

from django.http import JsonResponse

from modules.base import BaseModule
from modules.types import (
    ModuleCapability,
    ModuleNotification,
    ModuleRoute,
    ModuleStatus,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)
from utils.degradation import degradations

logger = logging.getLogger(__name__)

DEFAULT_WAKE_PROMPT = (
    "Tu viens de te réveiller ! Dis bonjour à ton audience de manière naturelle, "
    "comme si tu revenais d'une pause. Sois toi-même."
)


class WakeModule(BaseModule):
    """Polls for wake requests and triggers AI responses."""

    CRON_INTERVAL = 30  # Check every 30 seconds

    def __init__(self):
        super().__init__("wake")

    def get_models(self) -> list:
        from modules.plugins.wake.models import WakeRequest
        return [WakeRequest]

    # ── Lifecycle ─────────────────────────────────────────────────

    async def instantiate(self) -> None:
        self.logger.info("Wake module started (cron every %ds)", self.CRON_INTERVAL)

    async def shutdown(self) -> None:
        self.logger.info("Wake module stopped")

    # ── Cron ──────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        await self._process_pending()

    async def _process_pending(self) -> None:
        from django.utils import timezone

        from modules.plugins.wake.models import WakeRequest

        pending = WakeRequest.objects.filter(
            status=WakeRequest.Status.PENDING
        ).order_by("created_at")

        async for req in pending:
            prompt = req.prompt or DEFAULT_WAKE_PROMPT
            self.logger.info(
                "Processing wake request #%d from %s", req.pk, req.source
            )

            if self._notify_ai:
                try:
                    await self._notify_ai(
                        ModuleNotification(
                            source_module=self.name,
                            summary=f"Wake request from {req.source}",
                            details=prompt,
                            urgency="normal",
                            metadata={"person_id": f"wake_{req.source}"},
                        )
                    )
                except Exception:
                    self.logger.exception("Failed to process wake #%d", req.pk)

            req.status = WakeRequest.Status.PROCESSED
            req.processed_at = timezone.now()
            await req.asave()

    async def trigger_wake(
        self, source: str = "api", prompt: str | None = None
    ) -> int:
        """Create a new wake request. Returns the request PK."""
        from modules.plugins.wake.models import WakeRequest

        req = await WakeRequest.objects.acreate(source=source, prompt=prompt)
        self.logger.info("Wake request #%d created from %s", req.pk, source)
        return req.pk

    # ── Capabilities & Tools ────────────────────────────────────────

    def get_capabilities(self) -> list[ModuleCapability]:
        return [
            ModuleCapability(
                description="Programmer un reveil spontane pour parler plus tard",
                tool_names=["trigger_wake"],
            ),
            ModuleCapability(
                description="Programmer une action differee (rappel, verification, message futur)",
                tool_names=["schedule_action", "list_scheduled_actions", "cancel_scheduled_action"],
            ),
        ]

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="trigger_wake",
                description=(
                    "Trigger a wake event to make the VTuber spontaneously speak. "
                    "Useful to schedule a self-wake or initiate a new topic."
                ),
                parameters=[
                    ToolParameter(
                        name="prompt",
                        type=ToolParameterType.STRING,
                        description="Optional prompt for the wake message",
                        required=False,
                    ),
                    ToolParameter(
                        name="source",
                        type=ToolParameterType.STRING,
                        description="Source identifier (default: ai_tool)",
                        required=False,
                    ),
                ],
                handler=self._tool_trigger_wake,
            ),
            ModuleTool(
                name="schedule_action",
                description=(
                    "Schedule a deferred action to execute later. "
                    "The conscience will automatically trigger this action "
                    "when the scheduled time arrives."
                ),
                parameters=[
                    ToolParameter(
                        name="prompt",
                        type=ToolParameterType.STRING,
                        description="What to say or do when the action triggers",
                    ),
                    ToolParameter(
                        name="delay_minutes",
                        type=ToolParameterType.INTEGER,
                        description="Minutes from now to execute (1-1440)",
                    ),
                    ToolParameter(
                        name="priority",
                        type=ToolParameterType.NUMBER,
                        description="Priority 0.0-1.0 (default 0.5). Higher = more likely to trigger alone",
                        required=False,
                    ),
                ],
                handler=self._tool_schedule_action,
            ),
            ModuleTool(
                name="list_scheduled_actions",
                description="List all pending scheduled actions",
                parameters=[],
                handler=self._tool_list_scheduled,
            ),
            ModuleTool(
                name="cancel_scheduled_action",
                description="Cancel a pending scheduled action by ID",
                parameters=[
                    ToolParameter(
                        name="action_id",
                        type=ToolParameterType.INTEGER,
                        description="ID of the scheduled action to cancel",
                    ),
                ],
                handler=self._tool_cancel_scheduled,
            ),
        ]

    async def _tool_trigger_wake(self, args: dict) -> dict:
        wake_id = await self.trigger_wake(
            source=args.get("source", "ai_tool"),
            prompt=args.get("prompt"),
        )
        return {
            "content": [
                {"type": "text", "text": f"Wake request #{wake_id} created."}
            ]
        }

    async def _tool_schedule_action(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from datetime import timedelta
        from django.utils import timezone

        from conscience.models import ScheduledAction

        delay = max(1, min(1440, args["delay_minutes"]))
        priority = max(0.0, min(1.0, args.get("priority", 0.5)))
        scheduled_at = timezone.now() + timedelta(minutes=delay)

        action = await sync_to_async(ScheduledAction.objects.create)(
            scheduled_at=scheduled_at,
            prompt=args["prompt"],
            priority=priority,
            source="ai_tool",
        )

        self.logger.info(
            "Scheduled action #%d in %dmin (priority=%.1f): %s",
            action.pk, delay, priority, args["prompt"][:80],
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Action #{action.pk} programmee pour "
                        f"{scheduled_at.strftime('%H:%M')} "
                        f"(dans {delay}min, priorite {priority})."
                    ),
                }
            ]
        }

    async def _tool_list_scheduled(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from django.utils import timezone

        from conscience.models import ScheduledAction

        now = timezone.now()
        actions = await sync_to_async(
            lambda: list(
                ScheduledAction.objects.filter(status="pending")
                .order_by("scheduled_at")
                .values("id", "prompt", "scheduled_at", "priority", "source")[:20]
            )
        )()

        if not actions:
            return {"content": [{"type": "text", "text": "Aucune action programmee."}]}

        lines = []
        for a in actions:
            delta = a["scheduled_at"] - now
            mins = int(delta.total_seconds() / 60)
            status = f"dans {mins}min" if mins > 0 else "DUE"
            lines.append(
                f"- [#{a['id']}] ({status}, priorite {a['priority']}) "
                f"{a['prompt'][:80]} [source: {a['source']}]"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def _tool_cancel_scheduled(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async

        from conscience.models import ScheduledAction

        try:
            action = await sync_to_async(ScheduledAction.objects.get)(
                pk=args["action_id"], status="pending"
            )
            action.status = "cancelled"
            await sync_to_async(action.save)(update_fields=["status"])
            return {
                "content": [
                    {"type": "text", "text": f"Action #{action.pk} annulee."}
                ]
            }
        except ScheduledAction.DoesNotExist:
            return {
                "content": [
                    {"type": "text", "text": f"Action #{args['action_id']} non trouvee ou deja traitee."}
                ],
                "isError": True,
            }

    # ── Routes ────────────────────────────────────────────────────

    def get_routes(self) -> list[ModuleRoute]:
        return [
            ModuleRoute(
                path="",
                handler=self._view_wake,
                method="POST",
                name="wake",
            ),
            ModuleRoute(
                path="now",
                handler=self._view_wake_now,
                method="POST",
                name="wake_now",
            ),
        ]

    async def _view_wake(self, request):
        """Queue a wake request. Processed on next cron tick."""
        body = json.loads(request.body) if request.body else {}
        wake_id = await self.trigger_wake(
            source=body.get("source", "api"),
            prompt=body.get("prompt"),
        )
        return JsonResponse({"status": "queued", "wake_id": wake_id})

    async def _view_wake_now(self, request):
        """Create AND process a wake request immediately."""
        body = json.loads(request.body) if request.body else {}
        wake_id = await self.trigger_wake(
            source=body.get("source", "api"),
            prompt=body.get("prompt"),
        )
        await self._process_pending()
        return JsonResponse({"status": "processed", "wake_id": wake_id})

    # ── Context ───────────────────────────────────────────────────

    def get_context(self, person_id: str = "") -> str:
        from conscience.models import ScheduledAction

        try:
            count = ScheduledAction.objects.filter(status="pending").count()
            if count:
                return f"Tu as {count} action(s) programmee(s) en attente."
        except Exception as exc:
            degradations.record("modules.plugins.wake.module.get_context", exc)
            logger.debug("wake get_context query failed", exc_info=True)
        return ""

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        status.details = {"cron_interval": self.CRON_INTERVAL}
        return status
