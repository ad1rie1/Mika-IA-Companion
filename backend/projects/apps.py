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

        # Parler d'un projet à Mika EST un retour humain. Sans cet abonnement,
        # `runs_since_user_input` ne redescendait que sur résolution d'une
        # action en attente — chemin impossible pour un projet
        # `requires_approval=False`, c'est-à-dire le défaut : le compteur
        # montait à 10, `_list_due` excluait le projet et il se figeait
        # définitivement, sans erreur ni log d'alerte.
        from pipeline.signals import TURN_COMPLETED

        async def _reset_runs_since_user_input(event) -> None:
            # Règle de tri du lanceur, portée ici : un déclenchement interne
            # (notification de module, initiative de la conscience) n'est
            # personne qui parle du projet, même quand il porte le person_id
            # d'un vrai interlocuteur.
            if event.data.get("intent") == "INTERNAL_TRIGGER":
                return
            project_id = event.data.get("project_id")
            if not project_id:
                return
            await project_runner.notify_user_input(project_id)

        event_bus.subscribe(
            _reset_runs_since_user_input,
            # Nom distinct de « projects » ci-dessus : un abonnement de même
            # nom REMPLACE le précédent au lieu de s'y ajouter.
            name="projects.user_input",
            pattern=TURN_COMPLETED,
            # Late pour la même raison : un UPDATE indexé n'a aucune raison
            # de passer avant les réactions qui, elles, changent le tour.
            priority=PRIORITY_LATE,
        )
