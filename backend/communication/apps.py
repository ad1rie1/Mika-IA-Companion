from django.apps import AppConfig


class CommunicationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "communication"

    def ready(self):
        # Telegram is a first-class communication channel, not a plugin
        # module, so its config schema is registered here (same pattern
        # any other core app would use).
        from communication.channels.telegram_config_schema import CONFIG_SCHEMA
        from configs.registry import registry as config_registry
        config_registry.register(CONFIG_SCHEMA)
