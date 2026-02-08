"""Central plugin registry, scheduler, tool aggregator, and event bus."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from django.urls import path

from modules.base import BaseModule
from modules.types import (
    AIDecision,
    ModuleEvent,
    ModuleNotification,
    ModuleStatus,
    ModuleTool,
)

if TYPE_CHECKING:
    from claude_agent_sdk import McpSdkServerConfig

logger = logging.getLogger(__name__)

DEFAULT_TICK_INTERVAL = 60  # seconds


class ModuleManager:
    """Central plugin registry, scheduler, tool aggregator, and event bus.

    The core never imports specific modules — they register themselves
    via ``ModulesConfig.ready()``.  This manager handles:

    - Module lifecycle (start / stop)
    - Per-module cron scheduling
    - AI tool collection via MCP server
    - Context aggregation for Claude system prompt
    - Auto-mounted HTTP routes
    - Inter-module event bus
    - ``notify_ai`` callback injected into every module
    """

    def __init__(self) -> None:
        self._modules: dict[str, BaseModule] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._tick_interval: int = DEFAULT_TICK_INTERVAL
        self._tools_cache: list[ModuleTool] | None = None
        self._mcp_server: McpSdkServerConfig | None = None

    # ── Registration ──────────────────────────────────────────────

    def register(self, module: BaseModule) -> None:
        if module.name in self._modules:
            raise ValueError(f"Module '{module.name}' is already registered")

        if not module.is_available():
            logger.info(
                "Module '%s' not available (preconditions unmet), skipping",
                module.name,
            )
            return

        module.set_notify_ai(self._notify_ai)
        self._modules[module.name] = module
        self._tools_cache = None
        logger.info("Module registered: %s", module.name)

    def get_module(self, name: str) -> BaseModule | None:
        return self._modules.get(name)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start_all(self, chat_handler: Callable | None = None) -> None:
        """Start all registered modules and the cron scheduler.

        ``chat_handler`` is accepted for backward-compatibility but new
        modules should use ``self._notify_ai`` instead.
        """
        from django.conf import settings

        self._tick_interval = getattr(
            settings, "CRON_TICK_INTERVAL", DEFAULT_TICK_INTERVAL
        )

        for module in self._modules.values():
            # Legacy injection for modules still using set_chat_handler
            if chat_handler and hasattr(module, "set_chat_handler"):
                module.set_chat_handler(chat_handler)
            try:
                await module._do_start()
            except Exception:
                logger.exception("Failed to start module %s", module.name)
                module._running = False

        # Build MCP server from all module tools
        self._build_mcp_server()

        # Start the cron scheduler
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "Plugin scheduler started (default interval=%ds)", self._tick_interval
        )

    async def stop_all(self) -> None:
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            logger.info("Cron scheduler stopped")

        for module in reversed(list(self._modules.values())):
            if module.is_running:
                try:
                    await module._do_stop()
                except Exception:
                    logger.exception("Error stopping module %s", module.name)

    # ── Scheduler (per-module intervals) ──────────────────────────

    async def _scheduler_loop(self) -> None:
        """Tick every second, dispatch worker_cron() per-module interval."""
        last_tick: dict[str, float] = {}
        while True:
            try:
                await asyncio.sleep(1)
                now = time.time()
                for module in self._modules.values():
                    if not module.is_running:
                        continue
                    interval = module.CRON_INTERVAL or self._tick_interval
                    last = last_tick.get(module.name, 0.0)
                    if now - last >= interval:
                        last_tick[module.name] = now
                        try:
                            await module.worker_cron()
                        except Exception:
                            logger.exception(
                                "Error in worker_cron() for module %s",
                                module.name,
                            )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler error")

    # ── Tool Aggregation ──────────────────────────────────────────

    def collect_tools(self) -> list[ModuleTool]:
        """Aggregate ``return_tools()`` from all running modules."""
        if self._tools_cache is not None:
            return self._tools_cache
        tools: list[ModuleTool] = []
        seen_names: set[str] = set()
        for module in self._modules.values():
            if not module.is_running:
                continue
            for tool in module.return_tools():
                if tool.name in seen_names:
                    logger.warning(
                        "Duplicate tool name '%s' from module '%s', skipping",
                        tool.name,
                        module.name,
                    )
                    continue
                seen_names.add(tool.name)
                tools.append(tool)
        self._tools_cache = tools
        return tools

    def _build_mcp_server(self) -> None:
        """Build an in-process MCP server from all module tools."""
        from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

        tools = self.collect_tools()
        if not tools:
            self._mcp_server = None
            return

        sdk_tools = []
        for t in tools:
            sdk_tools.append(
                SdkMcpTool(
                    name=t.name,
                    description=t.description,
                    input_schema=t.to_json_schema(),
                    handler=t.handler,
                )
            )

        self._mcp_server = create_sdk_mcp_server(
            name="vtuber_modules",
            version="1.0.0",
            tools=sdk_tools,
        )
        logger.info(
            "MCP server built with %d tool(s) from modules", len(sdk_tools)
        )

    def get_mcp_server(self) -> McpSdkServerConfig | None:
        """Return the MCP server config for ClaudeAgentOptions."""
        return self._mcp_server

    def get_tool_names(self) -> list[str]:
        """Return all registered tool names for ``allowed_tools``."""
        return [t.name for t in self.collect_tools()]

    def invalidate_tools_cache(self) -> None:
        """Force rebuild of tool cache and MCP server on next use."""
        self._tools_cache = None
        self._mcp_server = None

    # ── Context Aggregation ───────────────────────────────────────

    def collect_context(self) -> str:
        """Collect context strings from all running modules."""
        parts: list[str] = []
        for module in self._modules.values():
            if module.is_running:
                ctx = module.get_context()
                if ctx:
                    parts.append(f"[{module.name}] {ctx}")
        return "\n".join(parts)

    # ── Route Collection ──────────────────────────────────────────

    def collect_routes(self) -> list:
        """Collect and namespace all module HTTP routes.

        Returns Django URL patterns mounted under
        ``/api/modules/{module_name}/{route.path}``.
        """
        patterns = []
        for module in self._modules.values():
            for route in module.get_routes():
                url_path = (
                    f"{module.name}/{route.path}" if route.path else module.name
                )
                url_name = route.name or f"module_{module.name}_{route.path or 'index'}"
                patterns.append(path(url_path, route.handler, name=url_name))
        return patterns

    # ── Event Bus ─────────────────────────────────────────────────

    async def emit_event(self, event: ModuleEvent) -> None:
        """Broadcast an event to all modules except the source."""
        for module in self._modules.values():
            if module.name != event.source_module and module.is_running:
                try:
                    await module.on_event(event)
                except Exception:
                    logger.exception(
                        "Error in on_event() for module %s", module.name
                    )

    # ── Notify AI ─────────────────────────────────────────────────

    async def _notify_ai(self, notification: ModuleNotification) -> AIDecision:
        """Wake Claude with a module notification and all available tools.

        This callback is injected into every module via ``set_notify_ai()``.
        """
        from ai.client import claude_client
        from ai.emotion_engine import emotion_engine
        from ai.emotion_types import Emotion, EmotionData
        from memory.manager import memory_manager

        # Build a structured prompt from the notification
        prompt = (
            f"[NOTIFICATION du module '{notification.source_module}']\n"
            f"Resume: {notification.summary}\n"
            f"Details: {notification.details}\n"
            f"Urgence: {notification.urgency}\n"
        )
        if notification.suggested_action:
            prompt += f"Action suggeree: {notification.suggested_action}\n"

        # Person ID — use metadata override if provided (e.g. Telegram user)
        person_id = notification.metadata.get(
            "person_id", f"module_{notification.source_module}"
        )

        try:
            memory_context = await memory_manager.get_memory_context(
                notification.summary
            )
            emotion_context = emotion_engine.get_emotion_context(person_id)
            module_context = self.collect_context()
            history = memory_manager.get_conversation_context()

            mcp_server = self.get_mcp_server()
            tool_names = self.get_tool_names()

            if mcp_server and tool_names:
                response_text, emotion_data, tool_calls = (
                    await claude_client.chat_with_tools(
                        message=prompt,
                        conversation_history=history,
                        memory_context=memory_context,
                        emotion_context=emotion_context,
                        module_context=module_context,
                        mcp_server=mcp_server,
                        tool_names=tool_names,
                    )
                )
            else:
                response_text, emotion_data = await claude_client.chat(
                    message=prompt,
                    conversation_history=history,
                    memory_context=memory_context,
                    emotion_context=emotion_context,
                )
                tool_calls = []

            emotion_engine.process_emotion(emotion_data, person_id)

        except Exception:
            logger.exception("notify_ai error for module %s", notification.source_module)
            response_text = "Oups, j'ai eu un petit bug..."
            emotion_data = EmotionData(emotion=Emotion.SAD, intensity=0.6)
            emotion_engine.process_emotion(emotion_data, person_id)
            tool_calls = []

        # Store in memory
        await memory_manager.add_message(
            "user", prompt, source=notification.source_module
        )
        await memory_manager.add_message("assistant", response_text)

        # Broadcast to WebSocket
        from channels.layers import get_channel_layer

        from chat.consumers import BROADCAST_GROUP

        msg_emotion = emotion_engine.compute_message_emotion(person_id)
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            BROADCAST_GROUP,
            {
                "type": "chat.broadcast",
                "data": {
                    "type": "speech",
                    "text": response_text,
                    "emotion": msg_emotion.emotion.value,
                    "emotion_intensity": msg_emotion.intensity,
                    "emotion_state": emotion_engine.get_state_dict(person_id),
                    "source": notification.source_module,
                },
            },
        )

        return AIDecision(
            response_text=response_text,
            emotion=emotion_data,
            tool_calls_made=tool_calls,
        )

    # ── Status ────────────────────────────────────────────────────

    def get_all_status(self) -> list[ModuleStatus]:
        """Return status of all registered modules."""
        return [m.get_status() for m in self._modules.values()]


module_manager = ModuleManager()
