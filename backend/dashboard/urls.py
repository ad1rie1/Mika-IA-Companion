"""Dashboard routing.

Two kinds of routes:
  - HTML pages    : ``/dashboard/``, ``/dashboard/<tab>/`` — one per
                    sidebar entry. Each serves a thin template that
                    extends ``dashboard/base.html`` and pulls its own JS.
  - JSON APIs     : ``/dashboard/api/<resource>`` — one per view module.
                    Read-only GET.
"""
from django.urls import path

from dashboard.views import pages
from dashboard.views.api import (
    configuration,
    personality_editor,
    conscience,
    drives as drives_api,
    emotion as emotion_api,
    identity as identity_api,
    memory,
    module_views,
    modules as modules_api,
    narrative as narrative_api,
    overview,
    personality as personality_api,
    persons,
    providers as providers_api,
    quota as quota_api,
    sleep as sleep_api,
    system,
)


urlpatterns = [
    # ── HTML pages ───────────────────────────────────────────────
    path("dashboard/",              pages.overview,     name="dash-home"),
    path("dashboard/overview/",     pages.overview,     name="dash-overview"),
    path("dashboard/personality/",  pages.personality,  name="dash-personality"),
    path("dashboard/narrative/",    pages.narrative,    name="dash-narrative"),
    path("dashboard/emotion/",      pages.emotion,      name="dash-emotion"),
    path("dashboard/drives/",       pages.drives,       name="dash-drives"),
    path("dashboard/ruminations/",  pages.ruminations,  name="dash-ruminations"),
    path("dashboard/sleep/",        pages.sleep,        name="dash-sleep"),
    path("dashboard/souvenirs/",    pages.souvenirs,    name="dash-souvenirs"),
    path("dashboard/connaissances/",pages.connaissances,name="dash-connaissances"),
    path("dashboard/themes/",       pages.themes,       name="dash-themes"),
    path("dashboard/entities/",     pages.entities,     name="dash-entities"),
    path("dashboard/messages/",     pages.messages,     name="dash-messages"),
    path("dashboard/persons/",      pages.persons,      name="dash-persons"),
    path("dashboard/persons/<int:entity_id>/", pages.person_detail, name="dash-person-detail"),
    path("dashboard/identity/",     pages.identity,     name="dash-identity"),
    path("dashboard/commitments/",  pages.commitments,  name="dash-commitments"),
    path("dashboard/observations/", pages.observations, name="dash-observations"),
    path("dashboard/logs/",         pages.logs,         name="dash-logs"),
    path("dashboard/scheduled/",    pages.scheduled,    name="dash-scheduled"),
    path("dashboard/projects/",     pages.projects,     name="dash-projects"),
    path("dashboard/projects/new/",              pages.project_new,    name="dash-project-new"),
    path("dashboard/projects/<int:project_id>/",      pages.project_detail, name="dash-project-detail"),
    path("dashboard/projects/<int:project_id>/edit/", pages.project_edit,   name="dash-project-edit"),
    path("dashboard/modules/",      pages.modules,      name="dash-modules"),
    # Module-contributed visualization pages (declared via get_views())
    path(
        "dashboard/modules/<str:module>/<str:view_key>/",
        pages.module_view,
        name="dash-module-view",
    ),
    path("dashboard/quota/",        pages.quota,        name="dash-quota"),
    path("dashboard/system/",       pages.system,       name="dash-system"),
    path("dashboard/config/",       pages.config,       name="dash-config"),

    # ── JSON API ─────────────────────────────────────────────────
    path("dashboard/api/overview",            overview.overview),
    path("dashboard/api/personality",         personality_api.personality),
    path("dashboard/api/narrative",           narrative_api.narrative),
    path("dashboard/api/emotion",             emotion_api.emotion),
    path("dashboard/api/emotion/history",     emotion_api.emotion_history),
    path("dashboard/api/drives",              drives_api.drives),
    path("dashboard/api/ruminations",         conscience.ruminations),
    path("dashboard/api/observations",        conscience.observations),
    path("dashboard/api/conscience/logs",     conscience.conscience_logs),
    path("dashboard/api/scheduled",           conscience.scheduled_actions),
    path("dashboard/api/sleep",               sleep_api.sleep),
    path("dashboard/api/sleep/dreams",        sleep_api.dreams),
    path("dashboard/api/sleep/journals",      sleep_api.journals),
    path("dashboard/api/souvenirs",           memory.souvenirs),
    path("dashboard/api/connaissances",       memory.connaissances),
    path("dashboard/api/themes",              memory.themes),
    path("dashboard/api/entities",            memory.entities),
    path("dashboard/api/messages",            memory.messages),
    path("dashboard/api/persons",             persons.persons),
    path("dashboard/api/persons/<int:entity_id>", persons.person_detail),
    path("dashboard/api/commitments",         persons.commitments),

    # Identity layer — who is behind a handle, how sure, what it unlocks.
    # The literal segments are declared before <int:identity_id> so a
    # future non-numeric sub-resource can't be shadowed by the detail route.
    path("dashboard/api/identity",            identity_api.identities),
    path("dashboard/api/identity/claims",     identity_api.claims),
    path("dashboard/api/identity/policy",     identity_api.policy),
    path("dashboard/api/identity/claims/<int:claim_id>/accept",
         identity_api.claim_accept),
    path("dashboard/api/identity/claims/<int:claim_id>/reject",
         identity_api.claim_reject),
    path("dashboard/api/identity/<int:identity_id>",
         identity_api.identity_detail),
    path("dashboard/api/identity/<int:identity_id>/bind",
         identity_api.identity_bind),
    path("dashboard/api/identity/<int:identity_id>/evidence",
         identity_api.identity_evidence),
    path("dashboard/api/identity/<int:identity_id>/revoke",
         identity_api.identity_revoke),
    path("dashboard/api/modules",             modules_api.modules),
    path("dashboard/api/modules/<str:name>/enable",    modules_api.module_enable),
    path("dashboard/api/modules/<str:name>/disable",   modules_api.module_disable),
    path("dashboard/api/modules/<str:name>/uninstall", modules_api.module_uninstall),

    # Module-declared visualization views (data + side-effect actions)
    path(
        "dashboard/api/modules/<str:module>/views",
        module_views.list_views,
    ),
    path(
        "dashboard/api/modules/<str:module>/views/<str:view_key>",
        module_views.view_data,
    ),
    path(
        "dashboard/api/modules/<str:module>/views/<str:view_key>/items/<str:item_id>",
        module_views.view_item,
    ),
    path(
        "dashboard/api/modules/<str:module>/views/<str:view_key>/actions/<str:action_key>",
        module_views.view_action,
    ),
    path("dashboard/api/quota",               quota_api.quota),
    path("dashboard/api/system/consolidation",system.consolidation),
    path("dashboard/api/system/ai-config",    system.ai_config),
    path("dashboard/api/system/health",       system.health),

    # Configuration system (schema-driven editor)
    path("dashboard/api/config/schema",            configuration.schema),
    path("dashboard/api/config/values",            configuration.value_write),  # PATCH/DELETE
    path("dashboard/api/config/values/all",        configuration.values),        # GET
    path("dashboard/api/config/rows",              configuration.rows),
    path("dashboard/api/config/rows/create",       configuration.row_add),
    # row_id is backend-defined (UUID for generic storage, stringified
    # PK for adapters that wrap a module's own Django model)
    path("dashboard/api/config/rows/<str:row_id>",configuration.row_detail),
    path("dashboard/api/config/history",           configuration.history),

    # Personality YAML editor
    path("dashboard/api/personality/yaml",          personality_editor.personality_read),
    path("dashboard/api/personality/yaml/write",    personality_editor.personality_write),

    # Provider introspection (list models / test connection)
    path("dashboard/api/providers/<str:provider>/models", providers_api.list_models),
    path("dashboard/api/providers/<str:provider>/test",   providers_api.test_provider),
]
