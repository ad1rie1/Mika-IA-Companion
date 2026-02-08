"""Email module — IMAP/SMTP integration with AI triage."""

from __future__ import annotations

import logging

from django.conf import settings

from modules.base import BaseModule
from modules.types import (
    ModuleNotification,
    ModuleStatus,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)

logger = logging.getLogger(__name__)


class EmailModule(BaseModule):
    """IMAP/SMTP module that checks for new emails on each cron tick."""

    CRON_INTERVAL = 60  # Check every 60 seconds

    def __init__(self):
        super().__init__("email")
        self._imap = None
        self._smtp = None
        self._analyzer = None
        self._unread_count = 0

    # ── Lifecycle ─────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(getattr(settings, "IMAP_HOST", ""))

    async def instantiate(self) -> None:
        from modules.email.analyzer import EmailAnalyzer
        from modules.email.imap_client import IMAPClient
        from modules.email.smtp_client import SMTPClient

        self._imap = IMAPClient()
        self._smtp = SMTPClient()
        self._analyzer = EmailAnalyzer()

        try:
            await self._imap.connect()
            self.logger.info("Email module started (IMAP connected)")
        except Exception:
            self.logger.exception("Failed to connect to IMAP")
            self._running = False

    async def shutdown(self) -> None:
        if self._imap:
            await self._imap.disconnect()
        self.logger.info("Email module stopped")

    # ── Cron ──────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        """Check IMAP for new emails."""
        if not self._imap or not self._analyzer:
            return

        try:
            emails = await self._imap.fetch_unread()
        except Exception:
            self.logger.exception("IMAP fetch error, attempting reconnect")
            try:
                await self._imap.disconnect()
                await self._imap.connect()
            except Exception:
                self.logger.exception("IMAP reconnect failed")
            return

        self._unread_count = len(emails)
        for email_msg in emails:
            await self._process_email(email_msg)

    async def _process_email(self, email_msg):
        """Process a single email: deduplicate, analyze, act."""
        from asgiref.sync import sync_to_async

        from modules.email.models import ProcessedEmail

        exists = await sync_to_async(
            ProcessedEmail.objects.filter(message_id=email_msg.message_id).exists
        )()
        if exists:
            return

        self.logger.info(
            "New email from %s: %s", email_msg.from_addr, email_msg.subject
        )

        analysis = await self._analyzer.analyze_email(
            from_addr=email_msg.from_addr,
            subject=email_msg.subject,
            body=email_msg.body_text,
        )

        await sync_to_async(ProcessedEmail.objects.create)(
            message_id=email_msg.message_id,
            uid=email_msg.uid,
            from_addr=email_msg.from_addr,
            subject=email_msg.subject,
            body_preview=email_msg.body_text[:500],
            priority=analysis.priority,
            notified=analysis.should_notify,
            replied=analysis.should_reply,
        )

        if analysis.memories:
            await self._store_memories(analysis.memories)

        # Notify AI for important emails (replaces direct broadcast)
        if analysis.should_notify and self._notify_ai:
            await self._notify_ai(
                ModuleNotification(
                    source_module=self.name,
                    summary=f"Email from {email_msg.from_addr}: {email_msg.subject}",
                    details=(
                        f"De: {email_msg.from_addr}\n"
                        f"Objet: {email_msg.subject}\n"
                        f"Priorite: {analysis.priority}\n"
                        f"Contenu: {email_msg.body_text[:500]}"
                    ),
                    urgency="high" if analysis.priority in ("high", "urgent") else "normal",
                    suggested_action=analysis.notification_text,
                    metadata={"email_from": email_msg.from_addr},
                )
            )

        if analysis.should_reply and analysis.reply_text:
            await self._send_reply(email_msg, analysis)

        await self._imap.mark_as_seen(email_msg.uid)

    async def _store_memories(self, memories: list[dict]):
        """Store AI-extracted memories from email into the memory system."""
        from asgiref.sync import sync_to_async
        from django.utils import timezone

        from memory.models import Connaissance, Entity, Souvenir, Theme

        now = timezone.now()

        for mem in memories:
            try:
                theme_objs = []
                for theme_name in mem.get("themes", []):
                    theme, _ = await sync_to_async(Theme.objects.get_or_create)(
                        name=theme_name.lower().strip()
                    )
                    theme_objs.append(theme)

                entity_objs = []
                for ent in mem.get("entities", []):
                    entity, _ = await sync_to_async(Entity.objects.get_or_create)(
                        name=ent["name"].strip(),
                        entity_type=ent.get("type", "concept"),
                    )
                    entity_objs.append(entity)

                if mem["type"] == "souvenir":
                    souvenir = await sync_to_async(Souvenir.objects.create)(
                        content=mem["content"],
                        emotion=mem.get("emotion", "neutral"),
                        importance=1.0,
                        occurred_at=now,
                    )
                    if theme_objs:
                        await sync_to_async(souvenir.themes.set)(theme_objs)
                    if entity_objs:
                        await sync_to_async(souvenir.entities.set)(entity_objs)

                elif mem["type"] == "connaissance":
                    connaissance = await sync_to_async(Connaissance.objects.create)(
                        content=mem["content"],
                        confidence=1.0,
                        is_valid=True,
                    )
                    if theme_objs:
                        await sync_to_async(connaissance.themes.set)(theme_objs)
                    if entity_objs:
                        await sync_to_async(connaissance.entities.set)(entity_objs)

                self.logger.info("Stored email memory: %s", mem["type"])
            except Exception:
                self.logger.exception("Failed to store email memory: %s", mem)

    async def _send_reply(self, email_msg, analysis):
        """Send an email reply via SMTP."""
        if not self._smtp:
            return
        try:
            subject = email_msg.subject
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            await self._smtp.send_reply(
                to_addr=email_msg.from_addr,
                subject=subject,
                body=analysis.reply_text,
                in_reply_to=email_msg.message_id,
            )
        except Exception:
            self.logger.exception("Failed to send email reply")

    # ── Tools ─────────────────────────────────────────────────────

    def return_tools(self) -> list[ModuleTool]:
        tools = [
            ModuleTool(
                name="list_recent_emails",
                description="List recent processed emails with sender, subject, and priority",
                parameters=[
                    ToolParameter(
                        name="limit",
                        type=ToolParameterType.INTEGER,
                        description="Max emails to return (default 5)",
                        required=False,
                    ),
                ],
                handler=self._tool_list_emails,
            ),
        ]

        if self._smtp:
            tools.append(
                ModuleTool(
                    name="send_email",
                    description="Send an email",
                    parameters=[
                        ToolParameter(
                            name="to",
                            type=ToolParameterType.STRING,
                            description="Recipient email address",
                        ),
                        ToolParameter(
                            name="subject",
                            type=ToolParameterType.STRING,
                            description="Email subject line",
                        ),
                        ToolParameter(
                            name="body",
                            type=ToolParameterType.STRING,
                            description="Email body text",
                        ),
                    ],
                    handler=self._tool_send_email,
                )
            )

        return tools

    async def _tool_list_emails(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async

        from modules.email.models import ProcessedEmail

        limit = args.get("limit", 5)
        emails = await sync_to_async(
            lambda: list(
                ProcessedEmail.objects.order_by("-processed_at")[:limit].values(
                    "from_addr", "subject", "priority", "processed_at"
                )
            )
        )()

        if not emails:
            return {"content": [{"type": "text", "text": "No processed emails found."}]}

        lines = []
        for e in emails:
            lines.append(
                f"- [{e['priority']}] {e['from_addr']}: {e['subject']} "
                f"({e['processed_at'].strftime('%Y-%m-%d %H:%M')})"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def _tool_send_email(self, args: dict) -> dict:
        if not self._smtp:
            return {
                "content": [{"type": "text", "text": "SMTP not configured."}],
                "isError": True,
            }
        try:
            await self._smtp.send_reply(
                to_addr=args["to"],
                subject=args["subject"],
                body=args["body"],
            )
            return {
                "content": [
                    {"type": "text", "text": f"Email sent to {args['to']}."}
                ]
            }
        except Exception as e:
            return {
                "content": [
                    {"type": "text", "text": f"Failed to send email: {e}"}
                ],
                "isError": True,
            }

    # ── Context ───────────────────────────────────────────────────

    def get_context(self) -> str:
        if self._unread_count > 0:
            return f"Tu as {self._unread_count} email(s) non lu(s)."
        return ""

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        status.details = {
            "imap_connected": self._imap is not None,
            "smtp_available": self._smtp is not None,
            "unread_count": self._unread_count,
        }
        return status
