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

    # Repli de ``wake.check_interval_s``. Réaffecté depuis la configuration à
    # chaque tour (voir ``worker_cron``), comme le module RSS : le
    # planificateur relit l'attribut entre deux ticks, donc le réglage vaut à
    # chaud sans redémarrage.
    CRON_INTERVAL = 30
    # Chaque requete traitee = un tour de pipeline complet, en serie. Un
    # backlog non borne monopoliserait le provider pendant N appels LLM
    # (jusqu'a 120s chacun) au detriment de la conversation en cours. Le
    # reste du lot repart au tick suivant : rien n'est perdu.
    MAX_WAKES_PER_TICK = 3

    def __init__(self):
        super().__init__("wake")

    def config_schema(self):
        from modules.plugins.wake.config_schema import CONFIG_SCHEMA
        return CONFIG_SCHEMA

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
        from configs.runtime import cfg_int

        # Relu à chaque tour : le planificateur consulte l'attribut entre deux
        # ticks, donc la cadence vaut à chaud (même schéma que le module RSS).
        self.CRON_INTERVAL = cfg_int("wake.check_interval_s", 30,
                                     mini=5, maxi=3600)
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
                        # Un reveil, c'est Mika qui parle seule : l'id reserve a
                        # cela est `conscience_mika`, comme dans
                        # ConscienceEngine._act(). Un id derive de la source
                        # (`wake_api`, `wake_cron`) serait vu comme une personne
                        # identifiable : aucun consumer ne s'enregistre sous ce
                        # nom, donc broadcast_to_websocket se tait au lieu de
                        # diffuser au groupe global, et l'historique par curseur
                        # (filtre sur person_id) ne rattrape rien non plus. Le
                        # message etait genere, paye, puis jete. La source reste
                        # une metadonnee, pas une identite d'interlocuteur.
                        metadata={
                            "person_id": "conscience_mika",
                            "wake_source": req.source,
                        },
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
        # Plus aucune capacité déclarée : elle nommerait `trigger_wake`, qui
        # n'est plus servi. Annoncer un outil qu'on ne fournit pas est le
        # défaut même que la trousse répare.
        return []

    def return_tools(self) -> list[ModuleTool]:
        """Aucun outil — et c'est une fermeture délibérée.

        `trigger_wake` était le seul chemin par lequel le modèle pouvait
        rentrer dans le pipeline complet depuis l'intérieur d'une boucle
        d'outils : `trigger_wake` → `WakeRequest` → cron 30 s → `notify_ai` →
        `perceive()` → `gather_context(include_tools=True)`, c'est-à-dire la
        trousse entière — celle que la conscience venait précisément de borner.
        Personne n'avait conçu ce chemin et aucun test ne le couvrait.

        Il faisait par ailleurs doublon : programmer un réveil pour plus tard,
        c'est `schedule_action`, et tout le cycle de vie des actions différées
        a déjà déménagé du wake vers `conscience_tools` — arrêter cet
        accessoire retirait autrefois la moitié du cycle en laissant l'autre
        tourner.

        Ce qui NE bouge pas : la route HTTP, le cron, `WakeRequest` et
        `trigger_wake()` en Python. Le module continue de réveiller Mika ;
        c'est la surface *appelable par le modèle* qui se ferme.
        """
        return []

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
        from modules.plugins.wake.models import WakeRequest

        body = json.loads(request.body) if request.body else {}
        wake_id = await self.trigger_wake(
            source=body.get("source", "api"),
            prompt=body.get("prompt"),
        )
        # Seulement la requete qu'on vient de creer : traiter tout le backlog
        # ici bloquerait la reponse HTTP pendant N appels LLM. Le reste reste
        # PENDING et part au prochain tick cron.
        req = await WakeRequest.objects.aget(pk=wake_id)
        claimed = await self._process_request(req)
        return JsonResponse({
            "status": "processed" if claimed else "already_processed",
            "wake_id": wake_id,
        })

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        status.details = {"cron_interval": self.CRON_INTERVAL}
        return status
