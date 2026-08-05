"""Wake module — triggers spontaneous AI messages via cron or API."""

from __future__ import annotations

import json

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

DEFAULT_WAKE_PROMPT = (
    "Tu viens de te réveiller ! Dis bonjour à ton audience de manière naturelle, "
    "comme si tu revenais d'une pause. Sois toi-même."
)


class WakeModule(BaseModule):
    """Polls for wake requests and triggers AI responses."""

    CRON_INTERVAL = 30  # Check every 30 seconds
    # Chaque requete traitee = un tour de pipeline complet, en serie. Un
    # backlog non borne monopoliserait le provider pendant N appels LLM
    # (jusqu'a 120s chacun) au detriment de la conversation en cours. Le
    # reste du lot repart au tick suivant : rien n'est perdu.
    MAX_WAKES_PER_TICK = 3

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
        from modules.plugins.wake.models import WakeRequest

        pending = WakeRequest.objects.filter(
            status=WakeRequest.Status.PENDING
        ).order_by("created_at")[: self.MAX_WAKES_PER_TICK]

        async for req in pending:
            await self._process_request(req)

    async def _process_request(self, req) -> bool:
        """Traite une requete de reveil. Retourne False si un autre appelant
        l'avait deja prise."""
        from django.utils import timezone

        from modules.plugins.wake.models import WakeRequest

        # Reservation atomique AVANT l'appel LLM. Le scheduler garantit qu'un
        # tick cron ne se superpose pas a lui-meme, mais /now traite en ligne
        # depuis la requete HTTP, hors de cette garantie : une ligne laissee
        # PENDING pendant l'appel serait reprise par l'autre appelant, soit
        # deux appels LLM et deux messages spontanes pour une seule requete.
        claimed = await WakeRequest.objects.filter(
            pk=req.pk, status=WakeRequest.Status.PENDING
        ).aupdate(
            status=WakeRequest.Status.PROCESSED,
            processed_at=timezone.now(),
        )
        if claimed != 1:
            return False

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

        return True

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

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        status.details = {"cron_interval": self.CRON_INTERVAL}
        return status
