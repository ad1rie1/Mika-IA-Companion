from django.apps import AppConfig


class ModulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules"

    def ready(self):
        from modules.camera import CameraModule
        from modules.email import EmailModule
        from modules.files import FilesModule
        from modules.manager import module_manager
        from modules.rss import RSSModule
        from communication.channels import TelegramModule
        from modules.urls import _populate_urls
        from modules.wake import WakeModule

        module_manager.register(TelegramModule())
        module_manager.register(WakeModule())
        module_manager.register(EmailModule())
        module_manager.register(RSSModule())
        module_manager.register(FilesModule())
        module_manager.register(CameraModule())

        _populate_urls()
