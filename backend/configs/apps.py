from django.apps import AppConfig

# Paquets porteurs d'un ``config_schema`` sans être une application Django.
_SCHEMAS_HORS_APPS = ("pipeline.config_schema",)


class ConfigsConfig(AppConfig):
    name = "configs"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Discover schemas declared by every installed app (via
        # ``<app>.config_schema`` module). BaseModule-declared schemas
        # are registered later by ModuleManager when modules boot.
        from configs.registry import registry
        registry.autodiscover()

        # ``autodiscover`` ne parcourt que les applications Django installées.
        # Les paquets qui n'en sont pas — ``pipeline`` n'a ni modèle ni
        # migration, le déclarer app pour un fichier de schéma serait le
        # promouvoir pour la mauvaise raison — se déclarent ici. La liste est
        # explicite : un paquet non listé n'a simplement pas de réglage.
        for nom in _SCHEMAS_HORS_APPS:
            try:
                import importlib
                mod = importlib.import_module(nom)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Schéma %s illisible", nom)
                continue
            registry.register(getattr(mod, "CONFIG_SCHEMA", None) or ())

        # Valide CONFIG_ENCRYPTION_KEY tant que la cause est encore lisible :
        # sinon une clé mal formée n'échoue qu'au premier chiffrement, dans
        # l'enregistrement d'un formulaire de configuration.
        from configs import secrets
        secrets.verifier_cle()
