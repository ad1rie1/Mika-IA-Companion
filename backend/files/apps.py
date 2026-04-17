from django.apps import AppConfig


class FilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "files"

    def ready(self):
        # Register the MCP facade with the plugin bus so that Claude's
        # tool inventory still includes files_list / files_read / ... .
        # The underlying service lives in this app (core), not in
        # backend/modules/, but it piggybacks on the existing module
        # plumbing rather than inventing a parallel registration path.
        from files.module import FilesModule
        from modules.manager import module_manager
        module_manager.register(FilesModule())
