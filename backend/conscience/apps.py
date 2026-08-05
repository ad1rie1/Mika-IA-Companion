from django.apps import AppConfig


class ConscienceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "conscience"

    def ready(self):
        # Enregistre la façade MCP des actions différées (schedule_action,
        # list_scheduled_actions, cancel_scheduled_action) sur le bus des
        # modules — même greffe que memory/apps.py : la conscience reste une
        # app cœur, seule sa surface d'outils passe par le bus. Ces outils
        # étaient logés dans le module « wake », dont on pouvait donc couper
        # la moitié du cycle de vie des actions sans couper l'autre.
        from conscience.module import ConscienceToolsModule
        from modules.manager import module_manager
        module_manager.register(ConscienceToolsModule())
