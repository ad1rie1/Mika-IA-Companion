from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "projects"

    def ready(self):
        # The projects subsystem lives here — models, runner, scheduler,
        # HTTP views. Its MCP facade (ProjectToolsModule) plugs into the
        # module bus so Claude can call create_project / add_project_task
        # / ... during a chat turn. Registered here, not by modules.apps.
        from modules.manager import module_manager
        from projects.tools import ProjectToolsModule
        module_manager.register(ProjectToolsModule())
