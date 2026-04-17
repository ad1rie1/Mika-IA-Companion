from django.apps import AppConfig


class ConfigsConfig(AppConfig):
    name = "configs"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Discover schemas declared by every installed app (via
        # ``<app>.config_schema`` module). BaseModule-declared schemas
        # are registered later by ModuleManager when modules boot.
        from configs.registry import registry
        registry.autodiscover()

        # One-shot migration from .env: the runtime never consults
        # Django settings for managed keys — this hook materialises
        # existing .env values into ConfigValue rows on first boot so
        # existing deployments don't see their config vanish.
        # Wrapped + silent on DB unavailability (e.g. migrate fresh).
        try:
            from django.db import connection
            if connection.introspection.table_names():  # migrations applied
                from configs.service import config_service
                config_service.seed_from_env()
        except Exception:
            pass
