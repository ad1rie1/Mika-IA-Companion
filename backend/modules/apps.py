from django.apps import AppConfig


class ModulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules"

    def ready(self):
        from modules.plugins.camera import CameraModule
        from modules.plugins.email import EmailModule
        from modules.plugins.forge import ForgeModule
        from modules.manager import module_manager
        from modules.plugins.rss import RSSModule
        from modules.urls import _populate_urls
        from modules.plugins.wake import WakeModule

        # Core apps register their own MCP facades (not plugins):
        # - FilesModule       → files.apps.FilesConfig.ready()
        # - ProjectToolsModule → projects.apps.ProjectsConfig.ready()
        # - Telegram channel   → communication.apps.CommunicationConfig
        #                        (started by ASGI lifespan, not a module)
        module_manager.register(WakeModule())
        module_manager.register(EmailModule())
        module_manager.register(RSSModule())
        module_manager.register(CameraModule())
        module_manager.register(ForgeModule())

        _populate_urls()
