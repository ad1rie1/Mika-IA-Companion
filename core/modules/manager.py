import logging
from typing import Callable, Awaitable

from fastapi import APIRouter

from core.modules.base_module import BaseModule

logger = logging.getLogger(__name__)


class ModuleManager:
    """Central registry that owns all modules.

    The core never imports specific modules directly.
    It only talks to this manager via:
      - start_all / stop_all
      - get_module(name)
      - collect_routers() for API routes exposed by modules
    """

    def __init__(self):
        self._modules: dict[str, BaseModule] = {}

    def register(self, module: BaseModule):
        if module.name in self._modules:
            raise ValueError(f"Module '{module.name}' is already registered")
        self._modules[module.name] = module
        logger.info("Module registered: %s", module.name)

    def get_module(self, name: str) -> BaseModule | None:
        return self._modules.get(name)

    async def start_all(self, chat_handler: Callable[[str, str], Awaitable]):
        """Start every registered module, injecting the shared chat handler."""
        for module in self._modules.values():
            if hasattr(module, "set_chat_handler"):
                module.set_chat_handler(chat_handler)
            await module.start()

    async def stop_all(self):
        """Stop every running module (reverse order)."""
        for module in reversed(list(self._modules.values())):
            if module.is_running:
                try:
                    await module.stop()
                except Exception:
                    logger.exception("Error stopping module %s", module.name)

    def collect_routers(self) -> list[APIRouter]:
        """Gather API routers from modules that expose one."""
        routers = []
        for module in self._modules.values():
            if hasattr(module, "get_router"):
                router = module.get_router()
                if router:
                    routers.append(router)
        return routers
