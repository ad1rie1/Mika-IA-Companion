import logging
from typing import Awaitable, Callable

from modules.base import BaseModule

logger = logging.getLogger(__name__)


class ModuleManager:
    """Central registry — the core never imports specific modules.

    Modules register themselves in ModulesConfig.ready().
    The core only talks to this manager.
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
        for module in self._modules.values():
            if hasattr(module, "set_chat_handler"):
                module.set_chat_handler(chat_handler)
            await module.start()

    async def stop_all(self):
        for module in reversed(list(self._modules.values())):
            if module.is_running:
                try:
                    await module.stop()
                except Exception:
                    logger.exception("Error stopping module %s", module.name)


module_manager = ModuleManager()
