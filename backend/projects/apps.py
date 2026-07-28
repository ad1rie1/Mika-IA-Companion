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

        # Wake projects whose schedule is `event:<type>`. This used to be an
        # inline import at the tail of ModuleManager.emit_event — the emitter
        # knowing, by name, about a subsystem it has no business knowing
        # about. The interest is declared here, where it belongs, and shows
        # up in `event_bus.stats()` like any other subscriber.
        from utils.eventbus import PRIORITY_LATE, event_bus
        from projects.runner import project_runner

        async def _wake_scheduled_projects(event) -> None:
            await project_runner.notify_event(event.event_type)

        event_bus.subscribe(
            _wake_scheduled_projects,
            name="projects",
            # Late: setting next_run_at is bookkeeping, and running it after
            # the conscience and the modules keeps a slow reactor from
            # delaying a cheap indexed UPDATE.
            priority=PRIORITY_LATE,
        )
