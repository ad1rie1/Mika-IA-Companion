from django.apps import AppConfig


class ModulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules"

    def ready(self):
        from modules.email import EmailModule
        from modules.manager import module_manager
        from modules.rss import RSSModule
        from modules.telegram import TelegramModule
        from modules.urls import _populate_urls
        from modules.wake import WakeModule

        module_manager.register(TelegramModule())
        module_manager.register(WakeModule())
        module_manager.register(EmailModule())
        module_manager.register(RSSModule())

        _populate_urls()
