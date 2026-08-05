"""ModuleCollectors — the five things the core asks every module for.

Tools, capabilities, prompt context, HTTP routes, dashboard views. They were
five method pairs on ``ModuleManager``, interleaved with lifecycle and
scheduling, sharing one hand-invalidated cache field. Grouped here they are
visibly the same shape — *ask every running module, merge, hand back* — and
the one piece of real logic in the set (per-person visibility of prompt
context) stops being buried between a cron loop and a DDL helper.

Everything here reads the registry and never mutates it. The only state is
the tool cache, invalidated by the lifecycle whenever the running set moves.
"""

from __future__ import annotations

import dataclasses
import logging

from django.urls import path
from django.views.decorators.http import require_http_methods

from modules.registry import ModuleRegistry
from modules.types import ModuleCapability, ModuleTool

logger = logging.getLogger(__name__)


def is_owner(person_id: str) -> bool:
    """May this person see owner-scoped (private) module context?

    Trusted: configured owners, authenticated users (``user_*``), and Mika's
    own internal channels (``conscience*``, ``module_*``). Anonymous web
    guests (``anon_*``) and external contacts are not — unread email subjects
    and pending wake-ups are not small talk.
    """
    if not person_id:
        return False
    from django.conf import settings

    if person_id in getattr(settings, "OWNER_PERSON_IDS", []):
        return True
    return person_id.startswith(("user_", "conscience", "module_"))


class ModuleCollectors:
    """Aggregation of everything modules contribute to the rest of the app."""

    def __init__(self, registry: ModuleRegistry) -> None:
        self._registry = registry
        self._tools_cache: list[ModuleTool] | None = None

    def invalidate(self) -> None:
        """Force a rebuild of the tool cache on next access."""
        self._tools_cache = None

    # ── Tools ─────────────────────────────────────────────────────

    def tools(self) -> list[ModuleTool]:
        """Aggregate ``return_tools()`` from all running modules.

        Handlers are wrapped with logging before being exposed, so every
        consumer (the Claude provider's MCP server, a future function-calling
        back-end, the admin UI) gets the same observability for free rather
        than each re-implementing it.

        A duplicate tool name is dropped with a warning rather than allowed
        to shadow: with modules authored at runtime, a name collision is a
        question of when, and silently rebinding a tool the model already
        knows how to call is the worse failure.
        """
        if self._tools_cache is not None:
            return self._tools_cache
        tools: list[ModuleTool] = []
        seen: set[str] = set()
        for module in self._registry.running():
            try:
                declared = module.return_tools()
            except Exception:
                logger.exception("return_tools() failed for module %s", module.name)
                continue
            for tool in declared:
                if tool.name in seen:
                    logger.warning(
                        "Duplicate tool name '%s' from module '%s', skipping",
                        tool.name, module.name,
                    )
                    continue
                seen.add(tool.name)
                tools.append(dataclasses.replace(
                    tool, handler=self._wrap_handler(tool.name, tool.handler),
                ))
        self._tools_cache = tools
        return tools

    def tools_for(self, module_names: list[str]) -> list[ModuleTool]:
        """``tools()`` narrowed to an allow-list of modules."""
        wanted = set(module_names)
        owner_of: dict[str, str] = {}
        for module_name in wanted:
            module = self._registry.get(module_name)
            if module is None or not module.is_running:
                continue
            try:
                owner_of.update({t.name: module_name for t in module.return_tools()})
            except Exception:
                logger.exception("return_tools() failed for module %s", module_name)
        return [t for t in self.tools() if owner_of.get(t.name) in wanted]

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools()]

    @staticmethod
    def _wrap_handler(name: str, handler):
        """Wrap a tool handler with call/return/error logging."""
        async def logged_handler(params):
            logger.info("tool called: %s (params=%s)", name, params)
            try:
                result = await handler(params)
                logger.info("tool %s returned: %s", name, str(result)[:200])
                return result
            except Exception:
                logger.exception("tool %s failed", name)
                raise
        return logged_handler

    # ── Capabilities ──────────────────────────────────────────────

    def capabilities(self) -> dict[str, list[ModuleCapability]]:
        """``{module_name: [capabilities]}`` for running modules.

        The Conscience reads these to know what actions exist without
        loading every MCP tool into a prompt.
        """
        result: dict[str, list[ModuleCapability]] = {}
        for module in self._registry.running():
            try:
                caps = module.get_capabilities()
            except Exception:
                logger.exception(
                    "get_capabilities() failed for module %s", module.name,
                )
                continue
            if caps:
                result[module.name] = caps
        return result

    def capabilities_summary(self) -> str:
        """Capabilities as prompt-ready lines, e.g. ``[email] Envoyer un mail``."""
        return "\n".join(
            f"[{module_name}] {cap.description}"
            for module_name, caps in self.capabilities().items()
            for cap in caps
        )

    # ── Prompt context ────────────────────────────────────────────

    def context(self, person_id: str = "") -> str:
        """Per-person context strings from all running modules.

        Modules default to ``CONTEXT_VISIBILITY == "owner"`` and are only
        injected for trusted persons, so private information never reaches
        an anonymous guest's prompt by way of a module that never thought
        about who was listening.
        """
        owner = is_owner(person_id)
        parts: list[str] = []
        for module in self._registry.running():
            if getattr(module, "CONTEXT_VISIBILITY", "owner") == "owner" and not owner:
                continue
            try:
                ctx = module.get_context(person_id)
            except Exception:
                logger.exception("get_context() failed for module %s", module.name)
                continue
            if ctx:
                parts.append(f"[{module.name}] {ctx}")
        return "\n".join(parts)

    # ── HTTP routes ───────────────────────────────────────────────

    def routes(self) -> list:
        """Django URL patterns under ``/api/modules/{module}/{route.path}``.

        ``ModuleRoute.method`` est appliqué ici, une fois pour tous les
        modules. Le handler était monté tel quel, si bien qu'un ``GET``
        atteignait une route déclarée ``POST`` — et Django ne protège pas les
        GET par CSRF, puisqu'ils sont présumés sans effet de bord. Une simple
        balise ``<img src=…>`` sur une page visitée suffisait donc à déclencher
        un effet de bord sur un endpoint monté hors du préfixe ``/gestion/``.
        Un module qui déclare autre chose que la méthode montée reçoit un 405.
        """
        patterns = []
        for module in self._registry.active():
            try:
                declared = module.get_routes()
            except Exception:
                logger.exception("get_routes() failed for module %s", module.name)
                continue
            for route in declared:
                url_path = (
                    f"{module.name}/{route.path}" if route.path else module.name
                )
                url_name = (
                    route.name or f"module_{module.name}_{route.path or 'index'}"
                )
                handler = route.handler
                if route.method:
                    handler = require_http_methods(
                        [route.method.upper()]
                    )(handler)
                patterns.append(path(url_path, handler, name=url_name))
        return patterns

    # ── Dashboard views ───────────────────────────────────────────
