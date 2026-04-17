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
    conscience,
    drives as drives_api,
    emotion as emotion_api,
    memory,
    modules as modules_api,
    narrative as narrative_api,
    overview,
    personality as personality_api,
    persons,
    projects as projects_api,
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
    path("dashboard/commitments/",  pages.commitments,  name="dash-commitments"),
    path("dashboard/observations/", pages.observations, name="dash-observations"),
    path("dashboard/logs/",         pages.logs,         name="dash-logs"),
    path("dashboard/scheduled/",    pages.scheduled,    name="dash-scheduled"),
    path("dashboard/projects/",     pages.projects,     name="dash-projects"),
    path("dashboard/modules/",      pages.modules,      name="dash-modules"),
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
    path("dashboard/api/commitments",         persons.commitments),
    path("dashboard/api/projects",            projects_api.projects),
    path("dashboard/api/modules",             modules_api.modules),
    path("dashboard/api/quota",               quota_api.quota),
    path("dashboard/api/system/consolidation",system.consolidation),
    path("dashboard/api/system/ai-config",    system.ai_config),
]
