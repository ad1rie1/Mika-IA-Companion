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
class ModuleViewAction:
    """A side-effect action attached to a module view.

    Mounted under /dashboard/api/modules/{module}/views/{view}/actions/{key}.
    Handlers receive the Django ``request`` and return a JSON-serializable
    dict (``JsonResponse`` is built by the dashboard wrapper).
    """

    key: str
    label: str
    handler: Callable  # async (request) -> dict | Any (JSON-serializable)
    method: str = "POST"
    confirm: str | None = None  # optional confirmation prompt for the UI


@dataclass
class ModuleView:
    """A visualization page a module exposes in the dashboard.

    Symmetrical to ``config_schema()`` — each module declares its own
    pages (inbox, history, stats…) and the dashboard shell auto-mounts
    them: one HTML route (``/dashboard/modules/{mod}/{view_key}/``),
    one JSON API (``/dashboard/api/modules/{mod}/views/{view_key}``),
    and optionally N action endpoints.

    Fields:
      key            — slug unique within the module (used in URLs)
      label          — sidebar label
      icon           — single-character icon (kept consistent with the
                        rest of the dashboard menu)
      order          — sort order in the module sub-nav
      data_handler   — async ``(request) -> dict`` returning the JSON
                        payload the front-end consumes. Supports
                        pagination by reading ``request.GET``
                        (``page``, ``limit``, ``q``, …).
      template       — template name (e.g. ``"email/inbox.html"``)
                        resolved from the module's own
                        ``templates/`` directory. Falls back to
                        ``dashboard/module_view.html`` (generic shell)
                        when ``None``.
      js             — static path to a JS module, relative to
                        ``STATIC_URL``. Loaded into the page via a
                        plain ``<script>`` tag. Falls back to the
                        module's own
                        ``static/<module>/views/<view_key>.js`` if
                        present.
      actions        — list of side-effect handlers exposed under
                        ``.../actions/<key>``.
    """

    key: str
    label: str
    icon: str = "▦"
    order: int = 100
    data_handler: Callable | None = None  # async (request) -> dict
    detail_handler: Callable | None = None
    # async (request, item_id: str) -> dict
    # When set, the generic renderer auto-appends a "Voir" column to
    # table rows; clicking it fetches
    # ``/dashboard/api/modules/{m}/views/{v}/items/{id}`` and opens a
    # modal rendering the returned JSON (key/value by default, or
    # ``{html: "..."}`` for a raw HTML body).
    id_field: str = "id"
    # Name of the per-row key that holds the identifier passed to
    # ``detail_handler``. Rows whose dict lacks this field hide the
    # "Voir" button instead of linking to a 404.
    template: str | None = None
    js: str | None = None
    actions: list = field(default_factory=list)  # list[ModuleViewAction]


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
class ModuleCapability:
    """High-level capability a module provides.

    Used by the Conscience to know what actions are available
    without loading all MCP tools into every prompt.
    The Conscience reads capabilities to decide which modules
    are relevant, then loads only those modules' tools.
    """

    description: str  # Natural language: "Lire et envoyer des emails"
    tool_names: list[str] = field(default_factory=list)  # Linked MCP tools


@dataclass
class ModuleStatus:
    """Module health/debug status."""

    name: str
    running: bool
    available: bool
    uptime_seconds: float = 0.0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
