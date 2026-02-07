from django.apps import AppConfig


class ModulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules"

    def ready(self):
        from modules.manager import module_manager
        from modules.telegram import TelegramModule
        from modules.wake import WakeModule

        module_manager.register(TelegramModule())
        module_manager.register(WakeModule(poll_interval=30.0))
