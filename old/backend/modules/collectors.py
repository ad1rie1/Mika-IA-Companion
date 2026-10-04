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

# ``is_owner`` vit dans ``identity/roles.py`` (trois niveaux : compte de
# conversation, opérateur, propriétaire). Réexporté ici parce que c'est le nom
# que les consommateurs du contexte privé importent (``files/service.py``,
# ``conscience/travaux.py``) — et celui que les tests patchent.
from old.backend.identity.roles import is_owner  # noqa: F401 (réexport)
from old.backend.modules.registry import ModuleRegistry
from old.backend.modules.types import ModuleCapability, ModuleTool
from old.backend.utils.degradation import degraded


from old.backend.utils.tool_results import en_echec as _signale_une_erreur, instrumenter

logger = logging.getLogger(__name__)


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
                    tool, handler=self._wrap_handler(tool.name, tool.handler), module_name=module.name,
                ))
        self._tools_cache = tools
        return tools

    def tools_for(self, module_names: list[str]) -> list[ModuleTool]:
        """``tools()`` narrowed to an allow-list of modules."""
        wanted = set(module_names)
        owner_of: dict[str, str] = {}
        for module_name in wanted:
            module = self._registry.get(module_name)
            if module is None:
                # Un nom qu'aucun module ne porte repartait sans un mot. C'est
                # ainsi que la conscience demandait « frontend » et
                # « telegram » — les valeurs de `Observation.source`, qui ne
                # sont des modules ni l'un ni l'autre — et repartait avec une
                # trousse vide en croyant l'avoir remplie.
                with degraded(f"modules: outils demandes a un inconnu ({module_name})"):
                    raise LookupError(module_name)
                continue
            if not module.is_running:
                continue
            try:
                owner_of.update({t.name: module_name for t in module.return_tools()})
            except Exception:
                logger.exception("return_tools() failed for module %s", module_name)
        return [t for t in self.tools() if t.module_name in wanted]

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools()]

    @staticmethod
    def _wrap_handler(name: str, handler):
        """Journalise l'appel, son issue et sa durée — un seul étage.

        Ce point de passage est partagé par la conversation, la conscience, le
        lanceur de projets et la forge : instrumenter ici plutôt que chez
        chaque appelant est ce qui évite quatre copies qui divergeraient.

        Il répare un aveuglement précis : la boucle d'outils ne remonte que
        `block.name`, sans résultat ni marqueur d'erreur, si bien que trois
        outils qui plantent satisfont la curiosité exactement comme trois
        réussites. Le carnet rend l'issue lisible sans changer le contrat de
        la boucle — un `raise` reste un `raise`, le modèle reçoit toujours son
        `is_error`.

        Un outil qui signale son échec à la façon MCP (un dict portant
        `isError`) n'a jamais levé : sans cette lecture, la moitié des échecs
        resterait comptée comme des succès.
        """
        return instrumenter(name, handler)

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

    def sujets(self) -> list[tuple[str, str]]:
        """``(module, sujet)`` pour tout ce que les modules ont à proposer.

        Lu depuis la boucle de décision : chaque module répond **de mémoire**,
        sans requête (voir `BaseModule.propose_sujets`). Un module qui lève est
        compté et sauté — une curiosité ne doit pas tomber parce qu'un flux est
        cassé.

        Pas de filtre de visibilité, contrairement à `context()` : ces sujets
        ne partent dans aucun prompt destiné à quelqu'un. Ils servent à ce
        qu'elle décide, pour elle-même, de quoi elle a envie de s'occuper.
        """
        out: list[tuple[str, str]] = []
        for module in self._registry.running():
            try:
                proposes = module.propose_sujets() or []
            except Exception:
                logger.exception("propose_sujets() failed for module %s", module.name)
                continue
            for sujet in proposes:
                texte = str(sujet).strip()
                if texte:
                    out.append((module.name, texte))
        return out

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
        """Django URL patterns under ``/api/modules/{module}/{route.path}``."""
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
                patterns.append(path(url_path, route.handler, name=url_name))
        return patterns

    # ── Dashboard views ───────────────────────────────────────────
