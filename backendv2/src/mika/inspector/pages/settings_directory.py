"""Une entrée lisible vers les réglages déclarés, sans charger leurs valeurs."""

from __future__ import annotations

import unicodedata
from typing import Any

from starlette.requests import Request

from mika.inspector.catalog import Panel
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX
from mika.kernel.inspect import Param


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


@TABS.tab("reglages.apercu", title="Tous les réglages", group="", order=0,
          description="Trouve le bon réglage : personnalité, modèles, connexions ou accès.")
async def directory(ui: Any, request: Request) -> dict[str, Any]:
    terms = _fold(request.query_params.get("q", "")).split()
    groups: dict[str, dict[str, Any]] = {}
    total = count = 0
    for page in sorted(ui.builtins.values(), key=lambda item: (item.order, item.title)):
        if not page.key.startswith("reglages.") or page.key == "reglages.apercu":
            continue
        total += 1
        if not all(term in _fold(f"{page.title} {page.description} {page.group} {page.slug}") for term in terms):
            continue
        count += 1
        group = groups.setdefault(page.group or "Autres", {
            "title": page.group or "Autres", "id": f"reglages-groupe-{len(groups)}", "items": [],
            "advanced": page.group.startswith("Comportement"),
        })
        description = page.description
        if len(description) > 180:
            description = description[:177].rsplit(" ", 1)[0] + "…"
        group["items"].append({"title": page.title, "description": description,
                               "href": page.href or f"{PREFIX}/reglages/{page.slug}"})
    return {"filters": (Param("q", "Rechercher un réglage", placeholder="ex. voix, modèle, boîte, mémoire"),),
            "panel": Panel("settings_directory.html", {
                "settings_groups": list(groups.values()), "settings_count": count, "settings_total": total,
                "settings_search": bool(terms),
            })}
