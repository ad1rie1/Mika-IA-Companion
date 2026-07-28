"""Routage de GestionSystème.

Deux principes :

- **Tout est une URL.** L'onglet actif, la page, les filtres et le tri sont
  dans l'adresse, jamais dans localStorage. Un écran se partage, se met en
  favori, et le retour arrière du navigateur fait ce qu'on attend.
- **Toute écriture est un POST.** Aucune action destructrice derrière un GET :
  un préchargement de navigateur ou un aspirateur de liens suffirait à la
  déclencher.

Espace de noms ``gestionsysteme``.
"""
from __future__ import annotations

from django.urls import path

from GestionSysteme.views import (
    api,
    config,
    conscience,
    inner,
    memory,
    modules,
    overview,
    projects,
    social,
    system,
)

app_name = "gestionsysteme"

urlpatterns = [
    path("", overview.overview, name="overview"),

    # ── État de l'IA ─────────────────────────────────────────────────
    path("interieur/", inner.inner, name="inner"),
    path("interieur/<slug:tab>/", inner.inner, name="inner-tab"),

    path("memoire/", memory.memory, name="memory"),
    path("memoire/<slug:tab>/", memory.memory, name="memory-tab"),

    path("social/", social.social, name="social"),
    path("social/personnes/<int:entity_id>/", social.person_detail, name="person-detail"),
    path(
        "social/personnes/<int:entity_id>/<slug:tab>/",
        social.person_detail, name="person-detail-tab",
    ),
    path("social/identites/<int:identity_id>/", social.identity_detail, name="identity-detail"),
    path("social/identites/<int:identity_id>/action/", social.identity_action, name="identity-action"),
    path("social/demandes/<int:claim_id>/action/", social.claim_action, name="claim-action"),
    path("social/<slug:tab>/", social.social, name="social-tab"),

    path("conscience/", conscience.conscience, name="conscience"),
    path("conscience/<slug:tab>/", conscience.conscience, name="conscience-tab"),

    # Les segments littéraux sont déclarés avant ``<slug:tab>``, qui les
    # capturerait sinon : « nouveau » est une page, pas un onglet. Le détail
    # passe en premier sans ambiguïté, le convertisseur ``int`` ne capturant
    # pas « actifs ».
    path("projets/", projects.projects, name="projects"),
    path("projets/nouveau/", projects.project_new, name="project-new"),
    path("projets/action/<int:action_id>/", projects.pending_action, name="project-pending-action"),
    path("projets/<int:project_id>/", projects.project_detail, name="project-detail"),
    path("projets/<int:project_id>/modifier/", projects.project_edit, name="project-edit"),
    path("projets/<int:project_id>/supprimer/", projects.project_delete, name="project-delete"),
    path("projets/<int:project_id>/taches/", projects.task_create, name="task-create"),
    path(
        "projets/<int:project_id>/taches/<int:task_id>/",
        projects.task_update, name="task-update",
    ),
    path("projets/<slug:tab>/", projects.projects, name="projects-tab"),

    # ── Administration ───────────────────────────────────────────────
    path("modules/", modules.modules, name="modules"),
    path("modules/<str:module>/", modules.module_space, name="module-space"),
    path("modules/<str:module>/etat/", modules.module_lifecycle, name="module-lifecycle"),
    path("modules/<str:module>/p/<slug:panel>/", modules.module_panel, name="module-panel"),
    path(
        "modules/<str:module>/p/<slug:panel>/action/<slug:action>/",
        modules.module_action, name="module-action",
    ),

    path("configuration/", config.config_home, name="config"),
    path("configuration/<slug:section>/", config.config_section, name="config-section"),
    # Les clés de configuration contiennent des points (``ai.models``) : le
    # convertisseur ``str`` les accepte, il n'exclut que la barre oblique.
    path("configuration/<slug:section>/<str:key>/nouveau/", config.record_new, name="config-record-new"),
    path("configuration/<slug:section>/<str:key>/<str:row_id>/", config.record_edit, name="config-record-edit"),
    path(
        "configuration/<slug:section>/<str:key>/<str:row_id>/supprimer/",
        config.record_delete, name="config-record-delete",
    ),

    path("systeme/", system.system, name="system"),
    path("systeme/<slug:tab>/", system.system, name="system-tab"),

    # ── Point d'accès JSON ───────────────────────────────────────────
    # Le seul de toute l'application : il n'alimente que la barre supérieure.
    # Tout le reste est rendu par le serveur.
    path("api/vitaux", api.vitals, name="api-vitals"),
]
