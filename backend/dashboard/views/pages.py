"""HTML page views — one per dashboard tab.

Each view simply renders a thin template that extends
``dashboard/base.html`` and pulls its own JS module. All data loading
happens client-side via the ``/dashboard/api/*`` endpoints so pages stay
cheap and cacheable.
"""
from __future__ import annotations

from django.http import Http404
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template


# Menu spec — single source of truth for the sidebar (order + groups +
# labels + route names). Rendered by ``dashboard/base.html``. Adding a
# new tab is one entry here + a page view + a template + a JS file.
MENU: list[dict] = [
    {"group": "Overview", "items": [
        {"key": "overview",     "label": "Overview",     "icon": "◈"},
    ]},
    {"group": "Vie intérieure", "items": [
        {"key": "emotion",      "label": "Émotions",     "icon": "❋"},
        {"key": "drives",       "label": "Drives",       "icon": "∿"},
        {"key": "ruminations",  "label": "Ruminations",  "icon": "◐"},
        {"key": "sleep",        "label": "Sommeil & Rêves", "icon": "☾"},
    ]},
    {"group": "Mémoire", "items": [
        {"key": "souvenirs",    "label": "Souvenirs",    "icon": "❖"},
        {"key": "connaissances","label": "Connaissances","icon": "◇"},
        {"key": "themes",       "label": "Thèmes",       "icon": "#"},
        {"key": "entities",     "label": "Entités",      "icon": "⛨"},
        {"key": "messages",     "label": "Messages",     "icon": "✉"},
    ]},
    # Ordered the way the system prompt assembles these blocks: identity
    # qualifies the person fiche ("--- QUI TU AS EN FACE ---" sits
    # immediately before "--- CE QUE TU SAIS DE CETTE PERSONNE ---"), so
    # reading the group top-down is qui parle → ce qu'elle en sait → ce
    # qu'elle leur a promis.
    {"group": "Social", "items": [
        {"key": "identity",     "label": "Identités",    "icon": "⚿"},
        {"key": "persons",      "label": "Personnes",    "icon": "☻"},
        {"key": "commitments",  "label": "Engagements",  "icon": "✓"},
    ]},
    {"group": "Conscience", "items": [
        {"key": "narrative",    "label": "Self-Concept", "icon": "☍"},
        {"key": "observations", "label": "Observations", "icon": "◉"},
        {"key": "logs",         "label": "Décisions",    "icon": "▤"},
        {"key": "scheduled",    "label": "Planification","icon": "⏱"},
    ]},
    {"group": "Agent", "items": [
        {"key": "projects",     "label": "Projets",      "icon": "◱"},
    ]},
    {"group": "Système", "items": [
        {"key": "system",       "label": "Système",      "icon": "⚙"},
        {"key": "quota",        "label": "Quota IA",     "icon": "⟠"},
        {"key": "personality",  "label": "Personnalité", "icon": "✦"},
        {"key": "config",       "label": "Configuration","icon": "⚒"},
        {"key": "modules",      "label": "Gestion des modules", "icon": "▦"},
    ]},
]


TITLES = {
    "overview": "Overview", "personality": "Personnalité", "narrative": "Self-Concept",
    "emotion": "Émotions", "drives": "Drives", "ruminations": "Ruminations",
    "sleep": "Sommeil & Rêves", "souvenirs": "Souvenirs", "connaissances": "Connaissances",
    "themes": "Thèmes", "entities": "Entités", "messages": "Messages",
    "persons": "Personnes", "identity": "Identités & confiance",
    "commitments": "Engagements", "observations": "Observations",
    "logs": "Journal conscience", "scheduled": "Actions planifiées",
    "projects": "Projets", "modules": "Gestion des modules", "quota": "Quota IA",
    "system": "Système", "config": "Configuration",
}


def _build_module_menu() -> list[dict]:
    """Snapshot of module-contributed dashboard views, grouped by module.

    Inserted into the sidebar under a "Modules · <name>" group for
    every running module that declares at least one view. Rebuilt on
    every page render so enabling/disabling a module is reflected
    immediately without a server restart.
    """
    try:
        from modules.manager import module_manager
    except Exception:
        return []

    groups: list[dict] = []
    try:
        views_by_module = module_manager.collect_views()
    except Exception:
        views_by_module = {}
    for module_name, views in views_by_module.items():
        items = [
            {
                "key": f"mv:{module_name}:{v.key}",
                "label": v.label,
                "icon": v.icon,
                "url": f"/dashboard/modules/{module_name}/{v.key}/",
            }
            for v in views
        ]
        groups.append({
            "group": f"Module · {module_name}",
            "items": items,
        })
    return groups


def _render(request, key: str, *, extra: dict | None = None):
    ctx = {
        "menu": MENU + _build_module_menu(),
        "active_view": key,
        "title": TITLES.get(key, key),
    }
    if extra:
        ctx.update(extra)
    return render(request, f"dashboard/{key}.html", ctx)


def module_view(request, module: str, view_key: str):
    """Render a module-declared dashboard page.

    Resolves the template from the module's own ``templates/``
    directory (e.g. ``email/inbox.html``) when the view specifies one;
    otherwise falls back to the generic shell
    ``dashboard/module_view.html`` which loads the view's JS by key.
    """
    from modules.manager import module_manager

    view = module_manager.get_view(module, view_key)
    if view is None:
        raise Http404(f"Module view '{module}/{view_key}' not found")

    active_key = f"mv:{module}:{view_key}"
    ctx = {
        "menu": MENU + _build_module_menu(),
        "active_view": active_key,
        "title": view.label,
        "module_name": module,
        "view_key": view_key,
        "view_label": view.label,
        "view_js": view.js,
        "view_has_detail": view.detail_handler is not None,
        "view_id_field": view.id_field,
        "view_actions": [
            {"key": a.key, "label": a.label, "method": a.method,
             "confirm": a.confirm}
            for a in (view.actions or [])
        ],
    }

    template_name = view.template or "dashboard/module_view.html"
    try:
        get_template(template_name)
    except TemplateDoesNotExist:
        template_name = "dashboard/module_view.html"
    return render(request, template_name, ctx)


def overview(request):     return _render(request, "overview")
def personality(request):  return _render(request, "personality")
def narrative(request):    return _render(request, "narrative")
def emotion(request):      return _render(request, "emotion")
def drives(request):       return _render(request, "drives")
def ruminations(request):  return _render(request, "ruminations")
def sleep(request):        return _render(request, "sleep")
def souvenirs(request):    return _render(request, "souvenirs")
def connaissances(request):return _render(request, "connaissances")
def themes(request):       return _render(request, "themes")
def entities(request):     return _render(request, "entities")
def messages(request):     return _render(request, "messages")
def persons(request):      return _render(request, "persons")
def identity(request):     return _render(request, "identity")


def person_detail(request, entity_id):
    """Full-page detail view for one person (profile header + memory tabs)."""
    from memory.models import Entity

    entity = Entity.objects.filter(entity_type="person", id=entity_id).first()
    if entity is None:
        raise Http404("Person not found")
    ctx = {
        "menu": MENU + _build_module_menu(),
        "active_view": "persons",
        "title": f"Personne · {entity.name}",
        "entity_id": entity.id,
    }
    return render(request, "dashboard/person_detail.html", ctx)


def project_detail(request, project_id):
    """Full-page detail view for one project (header + info/tasks/logs/prompts tabs)."""
    from projects.models import Project

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        raise Http404("Project not found")
    ctx = {
        "menu": MENU + _build_module_menu(),
        "active_view": "projects",
        "title": f"Projet · {project.title}",
        "project_id": project.id,
    }
    return render(request, "dashboard/project_detail.html", ctx)


def project_edit(request, project_id):
    """Full-page edit form for one project (all fields + task management)."""
    from projects.models import Project

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        raise Http404("Project not found")
    ctx = {
        "menu": MENU + _build_module_menu(),
        "active_view": "projects",
        "title": f"Éditer · {project.title}",
        "project_id": project.id,
    }
    return render(request, "dashboard/project_edit.html", ctx)


def project_new(request):
    """Full-page creation form (same template as edit, no project id)."""
    ctx = {
        "menu": MENU + _build_module_menu(),
        "active_view": "projects",
        "title": "Nouveau projet",
        "project_id": None,
    }
    return render(request, "dashboard/project_edit.html", ctx)


def commitments(request):  return _render(request, "commitments")
def observations(request): return _render(request, "observations")
def logs(request):         return _render(request, "logs")
def scheduled(request):    return _render(request, "scheduled")
def projects(request):     return _render(request, "projects")
def modules(request):      return _render(request, "modules")
def quota(request):        return _render(request, "quota")
def system(request):       return _render(request, "system")
def config(request):       return _render(request, "config")
