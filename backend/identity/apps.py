from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "identity"

    def ready(self):
        # Register the active-identification MCP facade (accept/reject a
        # claim, record corroborating evidence, unbind) with the plugin bus
        # — same piggyback pattern as memory/apps.py: the identity layer
        # stays a core app, only its tool surface rides the bus.
        from identity.module import IdentityToolsModule
        from modules.manager import module_manager
        module_manager.register(IdentityToolsModule())
