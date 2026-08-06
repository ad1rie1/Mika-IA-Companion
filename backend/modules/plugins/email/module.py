"""Email module — multi-account IMAP/SMTP with AI triage, contact DB, and email storage."""

from __future__ import annotations

import asyncio
import logging
from email.utils import parseaddr

from django.conf import settings
from django.db.models import F, Q

from modules.base import BaseModule
from modules.types import (
    ModuleCapability,
    ModuleEvent,
    ModuleNotification,
    ModuleStatus,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)
from utils.degradation import degradations

logger = logging.getLogger(__name__)

MAX_EMAILS_PER_ACCOUNT = 200

# Ceiling on one account's fetch+process pass. Generous: an initial sync
# imports a whole inbox and each new mail costs a triage call. The point is
# not to be tight, it is to have a bound at all — aioimaplib has none.
IMAP_TICK_TIMEOUT = 180

# Messages traités par tour et par compte, à défaut de réglage. Un message
# neuf coûte deux appels LLM en série (triage puis interprétation par la
# conscience) : au-delà d'une quinzaine, le tour dépasse IMAP_TICK_TIMEOUT.
DEFAULT_MAX_PER_TICK = 15


class EmailModule(BaseModule):
    """Multi-account IMAP/SMTP module with email storage, contacts, and AI triage."""

    CRON_INTERVAL = 60

    def __init__(self):
        super().__init__("email")
        self._accounts: dict[int, dict] = {}  # account_id -> {imap, smtp, account}
        self._analyzer = None
        self._unread_counts: dict[str, int] = {}  # account_name -> count
        # Comptes actifs déclarés en base, connectés ou non : c'est ce
        # compteur qui décide si le module se déclare au modèle. On ne compte
        # pas les connexions IMAP vivantes, sinon un serveur momentanément
        # injoignable retirerait aussi la lecture des mails déjà stockés.
        self._accounts_configured = 0

    # ── Lifecycle ─────────────────────────────────────────────────

    def is_available(self) -> bool:
        return True

    def config_schema(self):
        from modules.plugins.email.config_schema import CONFIG_SCHEMA
        return CONFIG_SCHEMA

    def get_panels(self) -> list:
        # Rendu serveur, cellules typées, sélecteur de compte. Pas de panneau
        # « Comptes » : ils s'éditent dans l'onglet Configuration de l'espace,
        # qui écrit dans la même table.
        from modules.plugins.email.panels import get_panels
        return get_panels()

    def get_models(self) -> list:
        from modules.plugins.email.models import Contact, Email, EmailAccount
        return [EmailAccount, Contact, Email]

    async def instantiate(self) -> None:
        from asgiref.sync import sync_to_async

        from modules.plugins.email.analyzer import EmailAnalyzer
        from modules.plugins.email.imap_client import IMAPClient
        from modules.plugins.email.models import EmailAccount
        from modules.plugins.email.smtp_client import SMTPClient

        self._analyzer = EmailAnalyzer()

        await self._migrate_env_account()

        accounts = await sync_to_async(
            lambda: list(EmailAccount.objects.filter(is_active=True))
        )()
        self._accounts_configured = len(accounts)

        for account in accounts:
            imap = IMAPClient.from_account(account)
            smtp = SMTPClient.from_account(account) if account.smtp_configured else None

            try:
                await imap.connect()
                self.logger.info("IMAP connected for account %s", account.name)
            except Exception:
                self.logger.exception("Failed to connect IMAP for %s", account.name)
                continue

            self._accounts[account.pk] = {
                "imap": imap,
                "smtp": smtp,
                "account": account,
            }

        self.logger.info("Email module started (%d account(s))", len(self._accounts))

    async def shutdown(self) -> None:
        for entry in self._accounts.values():
            imap = entry["imap"]
            if imap:
                await imap.disconnect()
        self._accounts.clear()
        self._accounts_configured = 0
        self.logger.info("Email module stopped")

    # ── Env migration ──────────────────────────────────────────────

    async def _migrate_env_account(self) -> None:
        """If no accounts in DB and env vars are set, create one automatically."""
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import EmailAccount

        count = await sync_to_async(EmailAccount.objects.count)()
        if count > 0:
            return

        imap_host = getattr(settings, "IMAP_HOST", "")
        if not imap_host:
            return

        self.logger.info("Migrating email account from env vars")
        await sync_to_async(EmailAccount.objects.create)(
            name="Default",
            email_address=getattr(settings, "IMAP_USER", ""),
            imap_host=imap_host,
            imap_port=getattr(settings, "IMAP_PORT", 993),
            imap_user=getattr(settings, "IMAP_USER", ""),
            imap_password=getattr(settings, "IMAP_PASSWORD", ""),
            smtp_host=getattr(settings, "SMTP_HOST", ""),
            smtp_port=getattr(settings, "SMTP_PORT", 587),
            smtp_user=getattr(settings, "SMTP_USER", ""),
            smtp_password=getattr(settings, "SMTP_PASSWORD", ""),
        )

    # ── Cron ──────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        """Check all accounts for new emails.

        Each account is bounded by ``IMAP_TICK_TIMEOUT``. ``aioimaplib`` has
        no timeout of its own, so a server that accepts the TCP connection
        and then goes quiet (a half-open socket, a firewall dropping the
        flow) left the fetch awaiting forever. Nothing above would have
        recovered it: the tick never returned, and this module never polled
        again for the lifetime of the process.
        """
        self.logger.debug("Email cron tick — checking %d account(s)", len(self._accounts))
        for account_id, entry in list(self._accounts.items()):
            try:
                await asyncio.wait_for(
                    self._check_account(account_id, entry),
                    timeout=IMAP_TICK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                # Drop the connection so the next tick reconnects rather than
                # awaiting the same dead socket again.
                self.logger.warning(
                    "IMAP tick timed out after %ss for account %s — "
                    "reconnecting next tick", IMAP_TICK_TIMEOUT, account_id,
                )
                try:
                    await asyncio.wait_for(entry["imap"].disconnect(), timeout=5)
                except Exception as exc:
                    degradations.record("modules.plugins.email.module.worker_cron", exc)
                    self.logger.debug("IMAP disconnect after timeout failed",
                                      exc_info=True)

    @staticmethod
    def _max_per_tick() -> int:
        """Plafond de messages traités par tour et par compte.

        Lecture ORM : appelée sous ``sync_to_async`` uniquement. Depuis une
        coroutine, ``config_service.get`` avale l'erreur d'accès synchrone et
        rend silencieusement la valeur d'usine — le réglage de l'utilisateur
        serait ignoré sans que rien ne le dise.
        """
        from configs.service import config_service

        try:
            value = config_service.get("email.max_per_tick", default=DEFAULT_MAX_PER_TICK)
            return max(1, int(value))
        except Exception as exc:
            degradations.record("modules.plugins.email.module._max_per_tick", exc)
            return DEFAULT_MAX_PER_TICK

    async def _check_account(self, account_id: int, entry: dict) -> None:
        """Relève un compte, par lots bornés et reprenables.

        Le tour est borné par ``IMAP_TICK_TIMEOUT`` en amont, et ``wait_for``
        annule la coroutine sans rien exécuter de ce qui suit la boucle. Un
        marqueur de progression écrit *après* la boucle était donc perdu à
        chaque dépassement : une boîte de cinq mille messages était
        retéléchargée intégralement toutes les soixante secondes, sans que
        ``initial_sync_done`` passe jamais à ``True`` — donc sans qu'aucun
        email ne soit jamais analysé ni signalé.

        Deux choses le rendent reprenable, dans cet ordre :

        1. **Le curseur, c'est la base elle-même.** Chaque message importé est
           une ligne ``Email``, donc le travail déjà fait est acquis au
           message près, y compris au milieu d'un lot annulé. Le filtre est
           posé *avant* le FETCH — c'est le téléchargement qui coûte, pas la
           déduplication par ``message_id`` qui, elle, arrive après.
        2. **Le lot est plafonné** (``email.max_per_tick``), le reste étant
           repris au tour suivant, comme le module RSS borne ses articles.
        """
        from asgiref.sync import sync_to_async
        from django.utils import timezone
        from modules.plugins.email.models import Email, EmailAccount

        imap = entry["imap"]
        account = entry["account"]

        is_initial_sync = not account.initial_sync_done
        max_per_tick = await sync_to_async(self._max_per_tick)()
        known = await sync_to_async(
            lambda: set(
                Email.objects.filter(account=account)
                .exclude(uid="")
                .values_list("uid", flat=True)
            )
        )()

        try:
            if is_initial_sync or not account.last_fetch:
                uids = await imap.list_uids("ALL")
            else:
                uids = await imap.list_uids_since(account.last_fetch)

            pending = [uid for uid in uids if uid not in known]
            batch = pending[:max_per_tick]
            emails = await imap.fetch_uids(batch)
        except Exception:
            self.logger.exception("IMAP fetch error for %s, attempting reconnect", account.name)
            try:
                await imap.disconnect()
                await imap.connect()
                self.logger.info("IMAP reconnected for %s", account.name)
            except Exception:
                self.logger.exception("IMAP reconnect failed for %s", account.name)
            return

        # Compté sur le lot demandé, pas sur ce que le FETCH a rendu : un
        # message illisible resterait sinon éternellement « en attente » et
        # la synchro initiale ne s'achèverait jamais.
        remaining = len(pending) - len(batch)

        if is_initial_sync:
            self.logger.info(
                "[%s] Initial sync — importing %d email(s), %d left after this tick "
                "(replies/notifications disabled)",
                account.name, len(emails), remaining,
            )
        else:
            self.logger.debug(
                "[%s] Fetched %d email(s) since last sync, %d left after this tick",
                account.name, len(emails), remaining,
            )

        new_count = 0
        errors = 0
        for email_msg in emails:
            try:
                was_new = await self._process_email(email_msg, account, entry, allow_actions=not is_initial_sync)
                if was_new:
                    new_count += 1
            except Exception:
                errors += 1
                self.logger.exception("[%s] Failed to process email: %s", account.name, email_msg.subject)

        now = timezone.now()
        update_fields = {"last_fetch": now}

        if is_initial_sync and remaining <= 0:
            # Achevée dès que la boîte a été parcourue, échecs compris. La
            # subordonner à `errors == 0` la laissait inachevée pour toujours
            # sur un seul message qui échoue de façon déterministe : la boîte
            # repartait de zéro à chaque tour et, `allow_actions` restant
            # faux, plus rien n'était jamais signalé. Ce qui a échoué reste
            # journalisé et repasse par le relevé incrémental.
            update_fields["initial_sync_done"] = True
            account.initial_sync_done = True
            self.logger.info(
                "[%s] Initial sync complete — %d email(s) imported this tick, "
                "%d error(s), replies now enabled",
                account.name, new_count, errors,
            )

        await sync_to_async(
            EmailAccount.objects.filter(pk=account_id).update
        )(**update_fields)
        account.last_fetch = now

        self._unread_counts[account.name] = new_count

        if new_count > 0:
            self.logger.info("[%s] %d new email(s) processed", account.name, new_count)
            # Jamais pendant la synchro initiale : l'élagage supprimerait les
            # lignes qui servent de curseur, et tout ce qui dépasse les 200
            # plus récents reviendrait au tour suivant comme « nouveau » —
            # une boucle d'écriture/suppression permanente sur SQLite.
            if account.initial_sync_done:
                await self._prune_emails(account)
        else:
            self.logger.debug("[%s] No new emails", account.name)

    async def _process_email(self, email_msg, account, entry, *, allow_actions: bool = True) -> bool:
        """Process a single email. Returns True if it was new.

        When allow_actions is False (initial sync), emails are stored but
        notifications and auto-replies are skipped.
        """
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import Email

        exists = await sync_to_async(
            Email.objects.filter(account=account, message_id=email_msg.message_id).exists
        )()
        if exists:
            self.logger.debug("[%s] Skipping already-known email: %s", account.name, email_msg.subject)
            return False

        self.logger.info(
            "[%s] New email from %s: %s", account.name, email_msg.from_addr, email_msg.subject
        )

        email_date = self._parse_email_date(email_msg.date)

        if allow_actions:
            self.logger.debug("[%s] Analyzing email: %s", account.name, email_msg.subject)
            analysis = await self._analyzer.analyze_email(
                from_addr=email_msg.from_addr,
                subject=email_msg.subject,
                body=email_msg.body_text,
            )
            self.logger.info(
                "[%s] Analysis result — priority=%s, notify=%s, reply=%s",
                account.name, analysis.priority, analysis.should_notify, analysis.should_reply,
            )
            priority = analysis.priority
        else:
            analysis = None
            priority = "low"

        await sync_to_async(Email.objects.create)(
            account=account,
            message_id=email_msg.message_id,
            uid=email_msg.uid,
            in_reply_to=email_msg.in_reply_to,
            references=email_msg.references,
            from_address=email_msg.from_addr,
            to_addresses=email_msg.to_addr,
            cc_addresses=email_msg.cc,
            subject=email_msg.subject,
            body_text=email_msg.body_text,
            body_html=email_msg.body_html,
            has_attachments=email_msg.has_attachments,
            direction="inbound",
            priority=priority,
            is_read=False,
            notified=False,
            replied=False,
            email_date=email_date,
        )

        # Upsert contacts
        _, from_email = parseaddr(email_msg.from_addr)
        if from_email:
            await self._upsert_contact(from_email, email_msg.from_addr, account, "inbound")

        for addr_str in (email_msg.to_addr or "").split(","):
            _, addr = parseaddr(addr_str.strip())
            if addr:
                await self._upsert_contact(addr, addr_str.strip(), account, "outbound")

        if analysis and analysis.memories:
            await self._store_memories(analysis.memories)

        if analysis and analysis.should_notify:
            # Emit event for the Conscience to observe, interpret, and decide
            from modules.manager import module_manager

            await module_manager.emit_event(
                ModuleEvent(
                    event_type="email.received",
                    source_module=self.name,
                    data={
                        "from": email_msg.from_addr,
                        "subject": email_msg.subject,
                        "body_preview": (email_msg.body_text or "")[:500],
                        "priority": analysis.priority,
                        "account": account.name,
                        "notification_text": analysis.notification_text,
                        "should_reply": analysis.should_reply,
                    },
                )
            )

        if analysis and analysis.should_reply and analysis.reply_text:
            smtp = entry.get("smtp")
            if smtp:
                await self._send_reply(smtp, email_msg, analysis, account)

        await entry["imap"].mark_as_seen(email_msg.uid)
        return True

    def _parse_email_date(self, date_str: str):
        """Parse RFC email date string to datetime."""
        from email.utils import parsedate_to_datetime

        if not date_str:
            return None
        try:
            return parsedate_to_datetime(date_str)
        except Exception as exc:
            degradations.record("modules.plugins.email.module._parse_email_date", exc)
            return None

    async def _upsert_contact(self, email_address: str, display_raw: str, account, direction: str):
        """Create or update a contact from email traffic."""
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import Contact

        email_address = email_address.lower().strip()
        if not email_address or "@" not in email_address:
            return

        # Extract display name from "Name <email>" format
        name, _ = parseaddr(display_raw)

        contact, created = await sync_to_async(Contact.objects.get_or_create)(
            email_address=email_address,
            defaults={"display_name": name},
        )

        if not created and name and not contact.display_name:
            contact.display_name = name

        if direction == "inbound":
            contact.emails_received = F("emails_received") + 1
        else:
            contact.emails_sent = F("emails_sent") + 1

        await sync_to_async(contact.save)()
        await sync_to_async(contact.accounts.add)(account)

    async def _prune_emails(self, account, keep: int = MAX_EMAILS_PER_ACCOUNT):
        """Keep only the most recent emails per account."""
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import Email

        total = await sync_to_async(Email.objects.filter(account=account).count)()
        if total <= keep:
            return

        ids_to_keep = await sync_to_async(
            lambda: list(
                Email.objects.filter(account=account)
                .order_by("-email_date")[:keep]
                .values_list("id", flat=True)
            )
        )()

        deleted, _ = await sync_to_async(
            Email.objects.filter(account=account).exclude(id__in=ids_to_keep).delete
        )()

        if deleted:
            self.logger.info("Pruned %d old emails from %s", deleted, account.name)

    async def _store_memories(self, memories: list[dict]):
        """Store AI-extracted memories from email into the memory system."""
        from asgiref.sync import sync_to_async

        from memory.manager import memory_manager
        from memory.models import Entity, Theme

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

                # Passe par le manager : il cree *et* indexe dans ChromaDB.
                # Ecrite directement en base, la memoire issue du triage
                # d'e-mails serait inerte — la remémoration part du vectoriel.
                if mem["type"] == "souvenir":
                    souvenir = await memory_manager.create_souvenir(
                        content=mem["content"],
                        emotion=mem.get("emotion", "neutral"),
                        importance=1.0,
                    )
                    if souvenir and theme_objs:
                        await sync_to_async(souvenir.themes.set)(theme_objs)
                    if souvenir and entity_objs:
                        await sync_to_async(souvenir.entities.set)(entity_objs)

                elif mem["type"] == "connaissance":
                    connaissance = await memory_manager.create_connaissance(
                        content=mem["content"],
                        confidence=1.0,
                    )
                    if connaissance and theme_objs:
                        await sync_to_async(connaissance.themes.set)(theme_objs)
                    if connaissance and entity_objs:
                        await sync_to_async(connaissance.entities.set)(entity_objs)

                self.logger.info("Stored email memory: %s", mem["type"])
            except Exception:
                self.logger.exception("Failed to store email memory: %s", mem)

    async def _send_reply(self, smtp, email_msg, analysis, account):
        """Send an email reply via SMTP."""
        try:
            subject = email_msg.subject
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            await smtp.send_reply(
                to_addr=email_msg.from_addr,
                subject=subject,
                body=analysis.reply_text,
                in_reply_to=email_msg.message_id,
            )

            # Store outbound email
            from asgiref.sync import sync_to_async

            from modules.plugins.email.models import Email

            await sync_to_async(Email.objects.create)(
                account=account,
                message_id=f"<reply-{email_msg.uid}@{account.email_address}>",
                from_address=account.email_address,
                to_addresses=email_msg.from_addr,
                subject=subject,
                body_text=analysis.reply_text,
                direction="outbound",
                email_date=None,
            )
        except Exception:
            self.logger.exception("Failed to send email reply")

    # ── Capabilities & Tools ────────────────────────────────────────

    def get_capabilities(self) -> list[ModuleCapability]:
        if not self._accounts_configured:
            return []
        return [
            ModuleCapability(
                description="Lire, lister et chercher dans les emails recus",
                tool_names=["list_recent_emails", "read_email", "search_emails"],
            ),
            ModuleCapability(
                description="Envoyer des emails",
                tool_names=["send_email"],
            ),
            ModuleCapability(
                description="Gerer les contacts email (lister, chercher)",
                tool_names=["list_contacts"],
            ),
            ModuleCapability(
                description="Voir les comptes email configures",
                tool_names=["list_email_accounts"],
            ),
        ]

    def return_tools(self) -> list[ModuleTool]:
        # Sans aucun compte, ces six outils ne peuvent que répondre « aucun
        # compte configuré » : leur déclaration est du prompt ré-émis à chaque
        # itération de la boucle d'outils, pour rien. `is_available()` ne peut
        # pas trancher (elle s'exécute depuis `AppConfig.ready()`, hors ORM),
        # mais ici oui — et le cache d'outils est invalidé après
        # `instantiate()`, donc la déclaration suit l'état réel du module.
        if not self._accounts_configured:
            return []
        return [
            ModuleTool(
                name="list_recent_emails",
                description="List recent emails with sender, subject, priority, and date",
                parameters=[
                    ToolParameter(
                        name="limit",
                        type=ToolParameterType.INTEGER,
                        description="Max emails to return (default 10)",
                        required=False,
                    ),
                    ToolParameter(
                        name="account_id",
                        type=ToolParameterType.INTEGER,
                        description="Filter by account ID (optional, omit for all accounts)",
                        required=False,
                    ),
                ],
                handler=self._tool_list_emails,
            ),
            ModuleTool(
                name="read_email",
                description="Read the full content of a specific email by its ID",
                parameters=[
                    ToolParameter(
                        name="email_id",
                        type=ToolParameterType.INTEGER,
                        description="The database ID of the email to read",
                    ),
                ],
                handler=self._tool_read_email,
            ),
            ModuleTool(
                name="search_emails",
                description="Search emails by keyword in sender, subject, or body",
                parameters=[
                    ToolParameter(
                        name="query",
                        type=ToolParameterType.STRING,
                        description="Search query",
                    ),
                    ToolParameter(
                        name="limit",
                        type=ToolParameterType.INTEGER,
                        description="Max results (default 10)",
                        required=False,
                    ),
                ],
                handler=self._tool_search_emails,
            ),
            ModuleTool(
                name="list_contacts",
                description="List known email contacts",
                parameters=[
                    ToolParameter(
                        name="limit",
                        type=ToolParameterType.INTEGER,
                        description="Max contacts to return (default 20)",
                        required=False,
                    ),
                    ToolParameter(
                        name="search",
                        type=ToolParameterType.STRING,
                        description="Filter by name or email address",
                        required=False,
                    ),
                ],
                handler=self._tool_list_contacts,
            ),
            ModuleTool(
                name="list_email_accounts",
                description="List all configured email accounts",
                parameters=[],
                handler=self._tool_list_accounts,
            ),
            ModuleTool(
                name="send_email",
                description="Send an email from one of the configured accounts",
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
                    ToolParameter(
                        name="account_id",
                        type=ToolParameterType.INTEGER,
                        description="Account ID to send from (uses first available if omitted)",
                        required=False,
                    ),
                ],
                handler=self._tool_send_email,
            ),
        ]

    async def _tool_list_emails(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import Email

        limit = args.get("limit", 10)
        account_id = args.get("account_id")

        qs = Email.objects.select_related("account").order_by("-email_date")
        if account_id:
            qs = qs.filter(account_id=account_id)

        emails = await sync_to_async(
            lambda: list(qs[:limit].values(
                "id", "from_address", "subject", "priority", "direction",
                "email_date", "account__name",
            ))
        )()

        if not emails:
            return {"content": [{"type": "text", "text": "No emails found."}]}

        lines = []
        for e in emails:
            date_str = e["email_date"].strftime("%Y-%m-%d %H:%M") if e["email_date"] else "?"
            lines.append(
                f"- [#{e['id']}] [{e['priority']}] [{e['direction']}] "
                f"{e['from_address']}: {e['subject']} ({date_str}) "
                f"[{e['account__name']}]"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def _tool_read_email(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import Email

        email_id = args["email_id"]
        try:
            email = await sync_to_async(
                Email.objects.select_related("account").get
            )(pk=email_id)
        except Email.DoesNotExist:
            return {
                "content": [{"type": "text", "text": f"Email #{email_id} not found."}],
                "isError": True,
            }

        text = (
            f"Account: {email.account.name}\n"
            f"From: {email.from_address}\n"
            f"To: {email.to_addresses}\n"
            f"Cc: {email.cc_addresses}\n"
            f"Subject: {email.subject}\n"
            f"Date: {email.email_date}\n"
            f"Direction: {email.direction}\n"
            f"Priority: {email.priority}\n"
            f"Has attachments: {email.has_attachments}\n"
            f"\n--- Body ---\n{email.body_text}"
        )
        return {"content": [{"type": "text", "text": text}]}

    async def _tool_search_emails(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import Email

        query = args["query"]
        limit = args.get("limit", 10)

        emails = await sync_to_async(
            lambda: list(
                Email.objects.filter(
                    Q(from_address__icontains=query)
                    | Q(subject__icontains=query)
                    | Q(body_text__icontains=query)
                )
                .order_by("-email_date")[:limit]
                .values("id", "from_address", "subject", "email_date", "account__name")
            )
        )()

        if not emails:
            return {"content": [{"type": "text", "text": f"No emails matching '{query}'."}]}

        lines = []
        for e in emails:
            date_str = e["email_date"].strftime("%Y-%m-%d %H:%M") if e["email_date"] else "?"
            lines.append(
                f"- [#{e['id']}] {e['from_address']}: {e['subject']} ({date_str}) [{e['account__name']}]"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def _tool_list_contacts(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import Contact

        limit = args.get("limit", 20)
        search = args.get("search", "")

        qs = Contact.objects.all()
        if search:
            qs = qs.filter(
                Q(email_address__icontains=search) | Q(display_name__icontains=search)
            )

        contacts = await sync_to_async(
            lambda: list(
                qs.order_by("-last_seen")[:limit].values(
                    "email_address", "display_name", "emails_received", "emails_sent", "last_seen",
                )
            )
        )()

        if not contacts:
            return {"content": [{"type": "text", "text": "No contacts found."}]}

        lines = []
        for c in contacts:
            name = c["display_name"] or c["email_address"]
            lines.append(
                f"- {name} <{c['email_address']}> "
                f"(recv: {c['emails_received']}, sent: {c['emails_sent']}, "
                f"last: {c['last_seen'].strftime('%Y-%m-%d')})"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def _tool_list_accounts(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async

        from modules.plugins.email.models import EmailAccount

        accounts = await sync_to_async(
            lambda: list(
                EmailAccount.objects.filter(is_active=True).values(
                    "id", "name", "email_address", "initial_sync_done", "last_fetch",
                )
            )
        )()

        if not accounts:
            return {"content": [{"type": "text", "text": "No email accounts configured."}]}

        lines = []
        for a in accounts:
            connected = a["id"] in self._accounts
            status = "connected" if connected else "disconnected"
            synced = "synced" if a["initial_sync_done"] else "pending initial sync"
            last = a["last_fetch"].strftime("%Y-%m-%d %H:%M") if a["last_fetch"] else "never"
            lines.append(
                f"- [#{a['id']}] {a['name']} ({a['email_address']}) "
                f"- {status}, {synced}, last fetch: {last}"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def send_email(
        self, *, to: str, subject: str, body: str, account_id=None,
    ) -> tuple[bool, str]:
        """Public façade for out-of-band senders (project approvals, …).

        Same path as the MCP tool, unwrapped into (ok, message) so callers
        outside the tool protocol don't have to parse MCP content blocks.
        """
        result = await self._tool_send_email({
            "to": to, "subject": subject, "body": body,
            "account_id": account_id,
        })
        text = "; ".join(
            c.get("text", "") for c in result.get("content", [])
            if isinstance(c, dict)
        ).strip()
        return (not result.get("isError", False), text)

    async def _tool_send_email(self, args: dict) -> dict:
        account_id = args.get("account_id")

        # Find the right account/smtp
        if account_id:
            entry = self._accounts.get(account_id)
            if not entry:
                return {
                    "content": [{"type": "text", "text": f"Account #{account_id} not connected."}],
                    "isError": True,
                }
        else:
            # Use first account with SMTP
            entry = None
            for e in self._accounts.values():
                if e.get("smtp"):
                    entry = e
                    break

        if not entry or not entry.get("smtp"):
            return {
                "content": [{"type": "text", "text": "No SMTP-configured account available."}],
                "isError": True,
            }

        smtp = entry["smtp"]
        account = entry["account"]

        try:
            await smtp.send_reply(
                to_addr=args["to"],
                subject=args["subject"],
                body=args["body"],
            )

            # Store outbound email
            from asgiref.sync import sync_to_async

            from modules.plugins.email.models import Email

            await sync_to_async(Email.objects.create)(
                account=account,
                message_id=f"<sent-{args['to']}-{args['subject'][:20]}@{account.email_address}>",
                from_address=account.email_address,
                to_addresses=args["to"],
                subject=args["subject"],
                body_text=args["body"],
                direction="outbound",
            )

            return {
                "content": [
                    {"type": "text", "text": f"Email sent to {args['to']} from {account.name}."}
                ]
            }
        except Exception as e:
            degradations.record("modules.plugins.email.module._tool_send_email", e)
            return {
                "content": [{"type": "text", "text": f"Failed to send email: {e}"}],
                "isError": True,
            }

    # ── Context ───────────────────────────────────────────────────

    def get_context(self, person_id: str = "") -> str:
        parts = []
        for account_name, count in self._unread_counts.items():
            if count > 0:
                parts.append(f"{account_name}: {count} nouveau(x) email(s)")
        return "\n".join(parts) if parts else ""

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        status.details = {
            "accounts_connected": len(self._accounts),
            "accounts": {name: count for name, count in self._unread_counts.items()},
        }
        return status
