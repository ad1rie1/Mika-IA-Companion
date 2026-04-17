"""RSS module — polls RSS/Atom feeds, emits events for new entries.

Configured via:
  - RSS_FEEDS env var (comma-separated "name|url" pairs for quick setup)
  - Django admin (RSSFeed model, for persistent management)

On each cron tick, fetches all active feeds, deduplicates via DB,
and emits a ModuleEvent for each new entry. The Conscience observes
these events, interprets them (via LLM path), and decides what to do.
"""

from __future__ import annotations

import hashlib
import logging
import re

from django.conf import settings

from modules.base import BaseModule
from modules.types import (
    ModuleCapability,
    ModuleEvent,
    ModuleStatus,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)

logger = logging.getLogger(__name__)


class RSSModule(BaseModule):
    """Polls RSS/Atom feeds and emits events to the event bus."""

    CRON_INTERVAL = 600  # 10 minutes by default

    def __init__(self):
        super().__init__("rss")
        self._feedparser = None
        self._new_count: int = 0  # count from last poll cycle

    # ── Lifecycle ─────────────────────────────────────────────────

    def config_schema(self):
        from modules.rss.config_schema import CONFIG_SCHEMA
        return CONFIG_SCHEMA

    def get_models(self) -> list:
        from modules.rss.models import RSSEntry, RSSFeed
        return [RSSFeed, RSSEntry]

    def is_available(self) -> bool:
        try:
            import feedparser  # noqa: F401
            return True
        except ImportError:
            return False

    async def instantiate(self) -> None:
        import feedparser
        self._feedparser = feedparser

        from configs.service import config_service
        self.CRON_INTERVAL = config_service.get("rss.poll_interval")

        # Migrate env-configured feeds to DB
        await self._migrate_env_feeds()

        from asgiref.sync import sync_to_async
        from modules.rss.models import RSSFeed
        count = await sync_to_async(RSSFeed.objects.filter(is_active=True).count)()
        self.logger.info("RSS module started (%d active feed(s), poll every %ds)", count, self.CRON_INTERVAL)

    async def shutdown(self) -> None:
        self.logger.info("RSS module stopped")

    # ── Env migration ──────────────────────────────────────────────

    async def _migrate_env_feeds(self) -> None:
        """If RSS_FEEDS env var is set and feeds don't exist in DB, create them."""
        from asgiref.sync import sync_to_async
        from modules.rss.models import RSSFeed

        feeds_config = getattr(settings, "RSS_FEEDS", [])
        if not feeds_config:
            return

        for feed_cfg in feeds_config:
            url = feed_cfg["url"]
            name = feed_cfg.get("name", url)
            exists = await sync_to_async(RSSFeed.objects.filter(url=url).exists)()
            if not exists:
                await sync_to_async(RSSFeed.objects.create)(name=name, url=url)
                self.logger.info("Migrated env feed: %s (%s)", name, url)

    # ── Cron ──────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        """Poll all active feeds for new entries."""
        import asyncio
        from functools import partial

        from asgiref.sync import sync_to_async
        from django.utils import timezone
        from modules.manager import module_manager
        from modules.rss.models import RSSEntry, RSSFeed

        feeds = await sync_to_async(
            lambda: list(RSSFeed.objects.filter(is_active=True))
        )()

        if not feeds:
            return

        loop = asyncio.get_event_loop()
        total_new = 0

        for feed in feeds:
            try:
                parsed = await loop.run_in_executor(
                    None, partial(self._feedparser.parse, feed.url)
                )

                if parsed.bozo and not parsed.entries:
                    self.logger.warning(
                        "RSS feed error for %s: %s", feed.name, parsed.bozo_exception
                    )
                    continue

                for entry in parsed.entries[:15]:
                    entry_hash = self._entry_hash(entry, feed.url)

                    # Check dedup in DB
                    exists = await sync_to_async(
                        RSSEntry.objects.filter(
                            feed=feed, entry_hash=entry_hash
                        ).exists
                    )()
                    if exists:
                        continue

                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    summary = self._clean_html(
                        entry.get("summary", entry.get("description", ""))
                    )
                    author = entry.get("author", "")
                    published = entry.get("published", "")

                    # Store in DB for dedup
                    await sync_to_async(RSSEntry.objects.create)(
                        feed=feed,
                        entry_hash=entry_hash,
                        title=title,
                        link=link,
                        summary=summary[:1000],
                        author=author,
                        published=published,
                    )

                    # Emit event to the event bus → conscience observes it
                    await module_manager.emit_event(
                        ModuleEvent(
                            source_module=self.name,
                            event_type="rss.new_entry",
                            data={
                                "feed_name": feed.name,
                                "feed_url": feed.url,
                                "title": title,
                                "link": link,
                                "summary": summary[:500],
                                "published": published,
                                "author": author,
                            },
                        )
                    )
                    total_new += 1

                # Update last_polled
                feed.last_polled = timezone.now()
                await sync_to_async(feed.save)(update_fields=["last_polled"])

            except Exception:
                self.logger.exception("RSS poll failed for %s", feed.name)

        self._new_count = total_new
        if total_new:
            self.logger.info("RSS: %d new entries across %d feeds", total_new, len(feeds))

        # Prune old entries (keep last 200 per feed)
        await self._prune_entries()

    async def _prune_entries(self, keep_per_feed: int = 200) -> None:
        """Keep only recent entries per feed to prevent unbounded growth."""
        from asgiref.sync import sync_to_async
        from modules.rss.models import RSSEntry, RSSFeed

        feeds = await sync_to_async(
            lambda: list(RSSFeed.objects.filter(is_active=True))
        )()

        for feed in feeds:
            total = await sync_to_async(RSSEntry.objects.filter(feed=feed).count)()
            if total <= keep_per_feed:
                continue

            ids_to_keep = await sync_to_async(
                lambda f=feed: list(
                    RSSEntry.objects.filter(feed=f)
                    .order_by("-seen_at")[:keep_per_feed]
                    .values_list("id", flat=True)
                )
            )()

            deleted, _ = await sync_to_async(
                RSSEntry.objects.filter(feed=feed)
                .exclude(id__in=ids_to_keep)
                .delete
            )()

            if deleted:
                self.logger.info("Pruned %d old RSS entries from %s", deleted, feed.name)

    # ── Capabilities & Tools ────────────────────────────────────────

    def get_capabilities(self) -> list[ModuleCapability]:
        return [
            ModuleCapability(
                description="Lire les derniers articles RSS/actualites",
                tool_names=["list_rss_entries", "list_rss_feeds"],
            ),
        ]

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="list_rss_entries",
                description="List recent RSS entries across all feeds or a specific feed",
                parameters=[
                    ToolParameter(
                        name="limit",
                        type=ToolParameterType.INTEGER,
                        description="Max entries to return (default 10)",
                        required=False,
                    ),
                    ToolParameter(
                        name="feed_name",
                        type=ToolParameterType.STRING,
                        description="Filter by feed name (optional)",
                        required=False,
                    ),
                ],
                handler=self._tool_list_entries,
            ),
            ModuleTool(
                name="list_rss_feeds",
                description="List all configured RSS feeds",
                parameters=[],
                handler=self._tool_list_feeds,
            ),
        ]

    async def _tool_list_entries(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from modules.rss.models import RSSEntry

        limit = args.get("limit", 10)
        feed_name = args.get("feed_name")

        qs = RSSEntry.objects.select_related("feed").order_by("-seen_at")
        if feed_name:
            qs = qs.filter(feed__name__icontains=feed_name)

        entries = await sync_to_async(
            lambda: list(qs[:limit].values(
                "title", "link", "summary", "author", "published",
                "seen_at", "feed__name",
            ))
        )()

        if not entries:
            return {"content": [{"type": "text", "text": "No RSS entries found."}]}

        lines = []
        for e in entries:
            lines.append(
                f"- [{e['feed__name']}] {e['title']}\n"
                f"  {e['link']}\n"
                f"  {e['summary'][:150]}"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def _tool_list_feeds(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from modules.rss.models import RSSFeed

        feeds = await sync_to_async(
            lambda: list(
                RSSFeed.objects.filter(is_active=True).values(
                    "id", "name", "url", "last_polled",
                )
            )
        )()

        if not feeds:
            return {"content": [{"type": "text", "text": "No RSS feeds configured."}]}

        lines = []
        for f in feeds:
            last = f["last_polled"].strftime("%Y-%m-%d %H:%M") if f["last_polled"] else "never"
            lines.append(f"- [#{f['id']}] {f['name']} — {f['url']} (last: {last})")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    # ── Context ───────────────────────────────────────────────────

    def get_context(self) -> str:
        if self._new_count > 0:
            return f"{self._new_count} nouvel(les) article(s) RSS depuis le dernier cycle"
        return ""

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        status.details = {
            "poll_interval": self.CRON_INTERVAL,
            "new_last_cycle": self._new_count,
        }
        return status

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _entry_hash(entry: dict, feed_url: str) -> str:
        raw = entry.get("id") or entry.get("link") or entry.get("title", "")
        return hashlib.md5(f"{feed_url}:{raw}".encode()).hexdigest()

    @staticmethod
    def _clean_html(html: str) -> str:
        text = re.sub(r"<[^>]+>", "", html)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        return text.strip()
