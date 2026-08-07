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

        # Valide CONFIG_ENCRYPTION_KEY tant que la cause est encore lisible :
        # sinon une clé mal formée n'échoue qu'au premier chiffrement, dans
        # l'enregistrement d'un formulaire de configuration.
        from configs import secrets
        secrets.verifier_cle()
