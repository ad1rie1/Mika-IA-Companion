"""Type definitions for the VTuber module plugin infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


class ToolParameterType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


@dataclass
class ToolParameter:
    """Single parameter for a module tool."""

    name: str
    type: ToolParameterType
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ModuleTool:
    """Tool definition that a module exposes to Claude.

    The ModuleManager converts these into SdkMcpTool instances
    for the claude_agent_sdk MCP server.
    """

    name: str
    description: str
    parameters: list[ToolParameter]
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

    def to_json_schema(self) -> dict:
        """Convert parameters to JSON Schema for MCP tool registration."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type.value,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            if param.required:
                required.append(param.name)
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema


@dataclass
class ModuleRoute:
    """HTTP route a module exposes.

    Routes are mounted under /api/modules/{module_name}/{path}.
    """

    path: str
    handler: Callable
    method: str = "POST"
    name: str | None = None


@dataclass
class ModuleNotification:
    """Structured notification from a module to the AI.

    Used by notify_ai() to wake Claude with module-originated events.
    Claude receives this + all available tools and decides what to do.
    """

    source_module: str
    summary: str
    details: str
    urgency: str = "normal"  # low | normal | high | critical
    suggested_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIDecision:
    """Result of notify_ai(): what Claude decided to do."""

    response_text: str
    emotion: Any  # EmotionData
    tool_calls_made: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleEvent:
    """Event for the inter-module event bus."""

    event_type: str  # e.g. "email.received", "wake.triggered"
    source_module: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleStatus:
    """Module health/debug status."""

    name: str
    running: bool
    available: bool
    uptime_seconds: float = 0.0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
