from django.apps import AppConfig


class MemoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "memory"

    def ready(self):
        # Register the active-recall MCP facade (memory_search,
        # memory_read_journal, memory_*_commitment...) with the plugin
        # bus — same piggyback pattern as files/apps.py: the memory
        # engine stays a core app, only the tool surface rides the bus.
        from memory.module import MemoryToolsModule
        from modules.manager import module_manager
        module_manager.register(MemoryToolsModule())
