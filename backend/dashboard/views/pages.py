"""HTML page views — one per dashboard tab.

Each view simply renders a thin template that extends
``dashboard/base.html`` and pulls its own JS module. All data loading
happens client-side via the ``/dashboard/api/*`` endpoints so pages stay
cheap and cacheable.
"""
from __future__ import annotations

from django.shortcuts import render


# Menu spec — single source of truth for the sidebar (order + groups +
# labels + route names). Rendered by ``dashboard/base.html``. Adding a
# new tab is one entry here + a page view + a template + a JS file.
MENU: list[dict] = [
    {"group": "Overview", "items": [
        {"key": "overview",     "label": "Overview",     "icon": "◈"},
        {"key": "personality",  "label": "Personnalité", "icon": "✦"},
        {"key": "narrative",    "label": "Self-Concept", "icon": "☍"},
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
    {"group": "Social", "items": [
        {"key": "persons",      "label": "Personnes",    "icon": "☻"},
        {"key": "commitments",  "label": "Engagements",  "icon": "✓"},
    ]},
    {"group": "Conscience", "items": [
        {"key": "observations", "label": "Observations", "icon": "◉"},
        {"key": "logs",         "label": "Décisions",    "icon": "▤"},
        {"key": "scheduled",    "label": "Planification","icon": "⏱"},
    ]},
    {"group": "Agent", "items": [
        {"key": "projects",     "label": "Projets",      "icon": "◱"},
        {"key": "modules",      "label": "Modules",      "icon": "▦"},
        {"key": "quota",        "label": "Quota IA",     "icon": "⟠"},
    ]},
    {"group": "Système", "items": [
        {"key": "system",       "label": "Système",      "icon": "⚙"},
        {"key": "config",       "label": "Configuration","icon": "⚒"},
    ]},
]


TITLES = {
    "overview": "Overview", "personality": "Personnalité", "narrative": "Self-Concept",
    "emotion": "Émotions", "drives": "Drives", "ruminations": "Ruminations",
    "sleep": "Sommeil & Rêves", "souvenirs": "Souvenirs", "connaissances": "Connaissances",
    "themes": "Thèmes", "entities": "Entités", "messages": "Messages",
    "persons": "Personnes", "commitments": "Engagements", "observations": "Observations",
    "logs": "Journal conscience", "scheduled": "Actions planifiées",
    "projects": "Projets", "modules": "Modules", "quota": "Quota IA",
    "system": "Système", "config": "Configuration",
}


def _render(request, key: str):
    return render(
        request,
        f"dashboard/{key}.html",
        {"menu": MENU, "active_view": key, "title": TITLES.get(key, key)},
    )


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
def commitments(request):  return _render(request, "commitments")
def observations(request): return _render(request, "observations")
def logs(request):         return _render(request, "logs")
def scheduled(request):    return _render(request, "scheduled")
def projects(request):     return _render(request, "projects")
def modules(request):      return _render(request, "modules")
def quota(request):        return _render(request, "quota")
def system(request):       return _render(request, "system")
def config(request):       return _render(request, "config")
