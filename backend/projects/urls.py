from django.urls import path

from projects import views

urlpatterns = [
    path("api/projects/", views.list_projects, name="projects-list"),
    path("api/projects/create", views.create_project, name="projects-create"),
    path("api/projects/<int:project_id>", views.project_detail, name="projects-detail"),
    path("api/projects/<int:project_id>/advance",
         views.advance_project, name="projects-advance"),
    path("api/projects/<int:project_id>/tasks",
         views.add_task, name="projects-add-task"),
    path("api/projects/<int:project_id>/tasks/<int:task_id>",
         views.task_detail, name="projects-task-detail"),
    path("api/projects/pending/", views.list_pending, name="projects-pending-list"),
    path("api/projects/pending/<int:action_id>/approve",
         views.approve_pending, name="projects-approve"),
    path("api/projects/pending/<int:action_id>/reject",
         views.reject_pending, name="projects-reject"),
    path("api/projects/<int:project_id>/history",
         views.project_prompt_history, name="projects-prompt-history"),
]
