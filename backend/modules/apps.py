from django.apps import AppConfig


class ModulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules"

    def ready(self):
        from modules.camera import CameraModule
        from modules.email import EmailModule
        from modules.manager import module_manager
        from modules.project_tools import ProjectToolsModule
        from modules.rss import RSSModule
        from modules.urls import _populate_urls
        from modules.wake import WakeModule

        # Note:
        # - FilesModule is registered by files.apps.FilesConfig.ready()
        #   because files is a core Django app, not a plugin.
        # - Telegram is a communication channel, not a plugin — it is
        #   started/stopped directly by the ASGI lifespan and its config
        #   schema is registered by communication.apps.CommunicationConfig.
        module_manager.register(WakeModule())
        module_manager.register(EmailModule())
        module_manager.register(RSSModule())
        module_manager.register(CameraModule())
        module_manager.register(ProjectToolsModule())

        _populate_urls()
