import logging

from django.conf import settings

from modules.base import BaseModule

logger = logging.getLogger(__name__)


class EmailModule(BaseModule):
    """IMAP/SMTP module that checks for new emails on each cron tick."""

    def __init__(self):
        super().__init__("email")
        self._chat_handler = None
        self._imap = None
        self._smtp = None
        self._analyzer = None

    def set_chat_handler(self, handler):
        self._chat_handler = handler

    async def on_start(self):
        if not getattr(settings, "IMAP_HOST", ""):
            self.logger.warning("No IMAP settings configured, email module disabled")
            self._running = False
            return

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

    async def on_stop(self):
        if self._imap:
            await self._imap.disconnect()
        self.logger.info("Email module stopped")

    async def on_message(self, message: str, source: str) -> str | None:
        return None

    async def on_tick(self):
        """Called every cron tick. Check IMAP for new emails."""
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

        for email_msg in emails:
            await self._process_email(email_msg)

    async def _process_email(self, email_msg):
        """Process a single email: check if already processed, analyze, act."""
        from asgiref.sync import sync_to_async

        from modules.models import ProcessedEmail

        # Deduplicate by message_id
        exists = await sync_to_async(
            ProcessedEmail.objects.filter(message_id=email_msg.message_id).exists
        )()
        if exists:
            return

        self.logger.info(
            "New email from %s: %s", email_msg.from_addr, email_msg.subject
        )

        # AI analysis
        analysis = await self._analyzer.analyze_email(
            from_addr=email_msg.from_addr,
            subject=email_msg.subject,
            body=email_msg.body_text,
        )

        # Persist as processed
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

        # Store memories if the AI extracted any
        if analysis.memories:
            await self._store_memories(analysis.memories)

        # Notify user via WebSocket if AI says so
        if analysis.should_notify:
            await self._broadcast_notification(email_msg, analysis)

        # Send reply if AI says so
        if analysis.should_reply and analysis.reply_text:
            await self._send_reply(email_msg, analysis)

        # Mark as seen in IMAP
        await self._imap.mark_as_seen(email_msg.uid)

    async def _store_memories(self, memories: list[dict]):
        """Store AI-extracted memories from email into the memory system."""
        from asgiref.sync import sync_to_async
        from django.utils import timezone

        from memory.models import Connaissance, Entity, Souvenir, Theme

        now = timezone.now()

        for mem in memories:
            try:
                # Resolve themes
                theme_objs = []
                for theme_name in mem.get("themes", []):
                    theme, _ = await sync_to_async(Theme.objects.get_or_create)(
                        name=theme_name.lower().strip()
                    )
                    theme_objs.append(theme)

                # Resolve entities
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

    async def _broadcast_notification(self, email_msg, analysis):
        """Send notification to all connected WebSocket clients."""
        from channels.layers import get_channel_layer

        from chat.consumers import BROADCAST_GROUP

        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            BROADCAST_GROUP,
            {
                "type": "chat.broadcast",
                "data": {
                    "type": "email_notification",
                    "text": analysis.notification_text,
                    "emotion": analysis.notification_emotion,
                    "source": "email",
                    "metadata": {
                        "from": email_msg.from_addr,
                        "subject": email_msg.subject,
                        "priority": analysis.priority,
                    },
                },
            },
        )

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
