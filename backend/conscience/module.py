"""Conscience tools — les actions différées, chez celui qui les exécute.

Ces trois outils vivaient dans le module « wake », qui n'a jamais rien eu à
voir avec elles : ils écrivent et lisent ``conscience.models.ScheduledAction``,
dont la conscience possède le modèle, le sondage
(``_poll_scheduled_actions``), la contribution au score (facteur 6) et
l'exécution dans ``_act()``.

Le couplage était asymétrique et silencieux : arrêter le wake — un accessoire,
vu de la page Modules — retirait à Mika la capacité de programmer, lister et
annuler une action différée pendant que la conscience continuait de scorer et
d'exécuter celles déjà en base. La moitié du cycle de vie disparaissait,
l'autre continuait, et rien ne le signalait.

  - schedule_action           programmer une action différée
  - list_scheduled_actions    lister celles en attente
  - cancel_scheduled_action   en annuler une

Module SYSTEM sans modèle propre (ils vivent dans ``conscience/models.py``) ni
configuration — même greffe que ``memory_tools`` et ``identity_tools`` : la
conscience reste une app cœur, seule sa surface d'outils passe par le bus.
"""

from __future__ import annotations

from configs.runtime import cfg_int
from modules.base import BaseModule
from modules.types import (
    ModuleCapability,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)
from utils.degradation import degradations


class ConscienceToolsModule(BaseModule):
    """Façade MCP au-dessus de ``ScheduledAction``."""

    SYSTEM = True

    # Le compte des actions en attente change hors du module : la conscience
    # sonde et exécute les siennes à chaque cycle de décision. Même cadence
    # ici, sinon l'invite annonce une action déjà partie — et « même cadence »
    # se lit désormais dans la *même clé*, pas dans un commentaire demandant
    # de recopier une valeur à la main. Reste la valeur de repli du moteur.
    CRON_INTERVAL = 30

    def __init__(self) -> None:
        super().__init__("conscience_tools")
        # Attribut d'instance : il masque la constante de classe, que le
        # planificateur et la page Modules relisent par ``getattr``. Lu une
        # fois à la construction, comme l'intervalle de la boucle de décision
        # lui-même (``restart_required``).
        self.CRON_INTERVAL = cfg_int(
            "conscience.decision_interval", type(self).CRON_INTERVAL, mini=1,
        )
        # Instantané pour l'invite système. Tenu en RAM et rafraîchi par le
        # cron, pas relu en base au moment de bâtir l'invite :
        # ``collect_context`` est appelé depuis une coroutine, où toute requête
        # ORM lève ``SynchronousOnlyOperation`` — que le collecteur avale, si
        # bien que le bloc disparaissait de chaque invite sans que rien ne le
        # signale. Même raison que les compteurs des modules RSS et email.
        self._pending_actions: int = 0

    # ── Cycle de vie ──────────────────────────────────────────────

    async def instantiate(self) -> None:
        from asgiref.sync import sync_to_async

        # Sans ça, le bloc n'apparaît qu'après le premier tick de cron, soit
        # trente secondes de « aucune action programmée » au redémarrage alors
        # que la base en contient.
        await sync_to_async(self._refresh_pending_actions)()

    # ── Cron ──────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        from asgiref.sync import sync_to_async

        await sync_to_async(self._refresh_pending_actions)()

    # ── Capabilities & Tools ────────────────────────────────────────

    def get_capabilities(self) -> list[ModuleCapability]:
        return [
            ModuleCapability(
                description="Programmer une action differee (rappel, verification, message futur)",
                tool_names=["schedule_action", "list_scheduled_actions", "cancel_scheduled_action"],
            ),
        ]

    def return_tools(self) -> list[ModuleTool]:
        return [
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
                    ToolParameter(
                        name="modules",
                        type=ToolParameterType.ARRAY,
                        description=(
                            "Module names whose tools you will need when the "
                            "action fires (e.g. [\"email\"], [\"rss\"], "
                            "[\"forge\"]). They will be loaded for that turn."
                        ),
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

    # ── Handlers ──────────────────────────────────────────────────

    async def _tool_schedule_action(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from datetime import timedelta
        from django.utils import timezone

        from conscience.models import ScheduledAction

        delay = max(1, min(1440, args["delay_minutes"]))
        priority = max(0.0, min(1.0, args.get("priority", 0.5)))
        scheduled_at = timezone.now() + timedelta(minutes=delay)

        # Argument fourni par un modèle : borné et nettoyé, jamais cru sur
        # parole. Un nom qu'aucun module ne porte finira simplement dans
        # `Trousse.inconnus` au moment de l'acte — visible, pas fatal.
        brut = args.get("modules") or []
        if isinstance(brut, str):
            brut = [brut]
        modules = [
            str(m).strip() for m in list(brut)[:5] if str(m or "").strip()
        ]

        action = await sync_to_async(ScheduledAction.objects.create)(
            scheduled_at=scheduled_at,
            prompt=args["prompt"],
            priority=priority,
            source="ai_tool",
            modules=modules,
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
                .values(
                    "id", "prompt", "scheduled_at", "priority", "source",
                    "modules",
                )[:20]
            )
        )()

        if not actions:
            return {"content": [{"type": "text", "text": "Aucune action programmee."}]}

        lines = []
        for a in actions:
            delta = a["scheduled_at"] - now
            mins = int(delta.total_seconds() / 60)
            status = f"dans {mins}min" if mins > 0 else "DUE"
            # Les modules que le rendez-vous emportera : sans eux dans la
            # liste, elle ne peut pas relire ce qu'elle s'est promis d'avoir
            # en main — ni corriger un oubli en annulant/reprogrammant.
            outils = ""
            if a.get("modules"):
                outils = " [outils: " + ", ".join(
                    str(m) for m in a["modules"]
                ) + "]"
            lines.append(
                f"- [#{a['id']}] ({status}, priorite {a['priority']}) "
                f"{a['prompt'][:80]} [source: {a['source']}]{outils}"
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

    # ── Context ───────────────────────────────────────────────────

    def _refresh_pending_actions(self) -> None:
        """Recompte les actions en attente. Appelé sous ``sync_to_async``.

        Un échec garde le dernier compte connu plutôt que de remonter : au
        démarrage il ferait échouer ``instantiate()``, donc emporterait les
        trois outils — perdre ``schedule_action`` parce qu'un compteur
        d'invite n'a pas pu se lire est hors de proportion. Compté au registre
        pour que l'écart ne passe pas inaperçu.
        """
        from conscience.models import ScheduledAction

        try:
            self._pending_actions = ScheduledAction.objects.filter(
                status="pending"
            ).count()
        except Exception as exc:
            degradations.record("conscience.module._refresh_pending_actions", exc)
            self.logger.debug("conscience pending-actions refresh failed", exc_info=True)

    def get_context(self, person_id: str = "") -> str:
        """Lecture RAM uniquement (voir ``_pending_actions``)."""
        if not self._pending_actions:
            return ""
        return f"Tu as {self._pending_actions} action(s) programmee(s) en attente."
